"""
Retrigger 1 deployment không được kế thừa attempts/started_at/celery_task_id từ lần
chạy trước — nếu không, job mới sẽ mất hết lượt retry ngay từ lần thử đầu tiên (do
`job.attempts <= deployment.retry_limit` so với giá trị attempts cũ còn sót lại).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentAction, DeploymentStatus
from apps.deployments import orchestrator as orch
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import finalize_deployment
from apps.machines.models import ConnectionMode, Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture(autouse=True)
def _no_chord(monkeypatch):
    # Test chỉ quan tâm Job row được tạo/reset đúng field — không cần chord thật enqueue
    # deploy_to_machine (sẽ đụng PushExecutor/SMB thật).
    monkeypatch.setattr(orch, "chord", lambda header: (lambda cb: None))


def test_relaunch_resets_attempts_started_at_celery_task_id(db):
    pkg = Package.objects.create(name="Firefox")
    pv = PackageVersion.objects.create(
        package=pkg, version="1", installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE, install_command='"{file}" /S',
    )
    credential = DeployCredential.objects.create(name="svc", username="svc_deploy")
    dep = Deployment.objects.create(
        name="D", action=DeploymentAction.INSTALL, package_version=pv,
        credential=credential, retry_limit=1,
    )
    m = Machine.objects.create(hostname="PC-1")
    dep.target_machines.add(m)

    # Job từ lần chạy trước: đã hết retry_limit, còn started_at/celery_task_id cũ.
    stale = timezone.now() - timedelta(hours=2)
    Job.objects.create(
        deployment=dep, machine=m, status=JobStatus.FAILED,
        attempts=5, started_at=stale, celery_task_id="old-task-id",
    )

    count = orch.launch_deployment(dep)

    assert count == 1
    job = Job.objects.get(deployment=dep, machine=m)
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0
    assert job.started_at is None
    assert job.celery_task_id == ""


def test_mixed_smb_agent_only_smb_job_dispatched_via_chord(db, monkeypatch):
    """
    Deployment lai (1 máy SMB + 1 máy agent): chord chỉ được tạo cho job SMB — job của máy
    agent giữ nguyên QUEUED, chờ AgentJobPollView claim khi agent tự poll tới (xem
    plan_agent.md mục 4).
    """
    recorded = {}

    def fake_chord(header):
        recorded["job_ids"] = [sig.args[0] for sig in header]
        return lambda cb: None

    monkeypatch.setattr(orch, "chord", fake_chord)

    pkg = Package.objects.create(name="Firefox")
    pv = PackageVersion.objects.create(
        package=pkg, version="1", installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE, install_command='"{file}" /S',
    )
    credential = DeployCredential.objects.create(name="svc2", username="svc_deploy2")
    dep = Deployment.objects.create(
        name="D-mixed", action=DeploymentAction.INSTALL, package_version=pv, credential=credential,
    )
    smb_machine = Machine.objects.create(hostname="SMB-1", connection_mode=ConnectionMode.SMB)
    agent_machine = Machine.objects.create(hostname="AGENT-1", connection_mode=ConnectionMode.AGENT)
    dep.target_machines.add(smb_machine, agent_machine)

    count = orch.launch_deployment(dep)

    assert count == 2
    smb_job = Job.objects.get(deployment=dep, machine=smb_machine)
    agent_job = Job.objects.get(deployment=dep, machine=agent_machine)
    assert recorded["job_ids"] == [smb_job.pk]
    assert agent_job.status == JobStatus.QUEUED  # không bị chord đụng vào


def test_finalize_deployment_waits_for_agent_job_before_finalizing(db, monkeypatch):
    """finalize_deployment (callback chord) không được chốt trạng thái khi job của máy agent
    (nằm ngoài chord) vẫn chưa terminal — tránh tính sai kết quả deployment lai."""
    monkeypatch.setattr(orch, "chord", lambda header: (lambda cb: None))

    pkg = Package.objects.create(name="Chrome")
    pv = PackageVersion.objects.create(
        package=pkg, version="1", installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE, install_command='"{file}" /S',
    )
    credential = DeployCredential.objects.create(name="svc3", username="svc_deploy3")
    dep = Deployment.objects.create(
        name="D-guard", action=DeploymentAction.INSTALL, package_version=pv, credential=credential,
    )
    smb_machine = Machine.objects.create(hostname="SMB-2", connection_mode=ConnectionMode.SMB)
    agent_machine = Machine.objects.create(hostname="AGENT-2", connection_mode=ConnectionMode.AGENT)
    dep.target_machines.add(smb_machine, agent_machine)
    orch.launch_deployment(dep)

    smb_job = Job.objects.get(deployment=dep, machine=smb_machine)
    agent_job = Job.objects.get(deployment=dep, machine=agent_machine)
    Job.objects.filter(pk=smb_job.pk).update(status=JobStatus.SUCCESS)

    finalize_deployment(None, dep.id)
    dep.refresh_from_db()
    assert dep.status == DeploymentStatus.RUNNING  # job agent (QUEUED) chưa xong -> chưa chốt

    Job.objects.filter(pk=agent_job.pk).update(status=JobStatus.SUCCESS)
    finalize_deployment(None, dep.id)
    dep.refresh_from_db()
    assert dep.status == DeploymentStatus.COMPLETED
