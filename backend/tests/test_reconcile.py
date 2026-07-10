"""
reconcile_stuck_deployments phải tự phát hiện job "ma" kẹt RUNNING sau worker crash
(acks_late redeliver thấy claim fail, coi là "đã xử lý" rồi return êm — không ai từng ghi
FAILED cho job đó) và đánh FAILED, thay vì bỏ qua deployment vô thời hạn. Job SMB stale
còn phải best-effort cleanup_now (service/file tạm có thể còn trên máy đích).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentStatus
from apps.deployments.tasks import reconcile_stuck_deployments
from apps.jobs.models import Job, JobStatus
from apps.machines.models import ConnectionMode, Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    # Không phụ thuộc Redis thật trong test — chỉ cần biết release_slot có được gọi không.
    calls = []
    monkeypatch.setattr("apps.deployments.semaphore.release_slot", lambda dep_id: calls.append(dep_id))
    return calls


@pytest.fixture(autouse=True)
def _stub_cleanup(monkeypatch):
    # Không kết nối SMB thật khi watchdog dọn residue — chỉ ghi lại lời gọi.
    calls = []

    def fake_cleanup(job, machine, credential, job_token):
        calls.append({"job_id": job.pk, "hostname": machine.hostname, "job_token": job_token})

    monkeypatch.setattr("apps.jobs.tasks._cleanup_target_residue", fake_cleanup)
    return calls


@pytest.fixture
def deployment(db):
    pkg = Package.objects.create(name="Office")
    pv = PackageVersion.objects.create(
        package=pkg, version="2024", installer_file="repository/x/2024/setup.exe",
        installer_type=InstallerType.EXE,
    )
    cred = DeployCredential.objects.create(name="svc", username="svc_deploy")
    dep = Deployment.objects.create(
        name="Rollout", package_version=pv, credential=cred, status=DeploymentStatus.RUNNING
    )
    dep.started_at = timezone.now()
    dep.save(update_fields=["started_at"])
    return dep


def test_fresh_running_job_is_untouched(deployment):
    m = Machine.objects.create(hostname="PC-1")
    job = Job.objects.create(
        deployment=deployment, machine=m, status=JobStatus.RUNNING,
        started_at=timezone.now() - timedelta(minutes=5),  # mới, chưa quá timeout
    )
    reconcile_stuck_deployments()
    job.refresh_from_db()
    deployment.refresh_from_db()
    assert job.status == JobStatus.RUNNING
    assert deployment.status == DeploymentStatus.RUNNING


def test_stale_running_job_marked_failed_and_deployment_finalized(deployment, _no_redis, _stub_cleanup):
    m1 = Machine.objects.create(hostname="PC-1")  # mặc định connection_mode=smb
    m2 = Machine.objects.create(hostname="PC-2")
    stale_job = Job.objects.create(
        deployment=deployment, machine=m1, status=JobStatus.RUNNING,
        started_at=timezone.now() - timedelta(hours=1),  # quá timeout (mặc định 30 phút + 5 phút dư)
    )
    Job.objects.create(deployment=deployment, machine=m2, status=JobStatus.SUCCESS)

    result = reconcile_stuck_deployments()

    stale_job.refresh_from_db()
    deployment.refresh_from_db()
    assert stale_job.status == JobStatus.FAILED
    assert "watchdog" in stale_job.error_output.lower()
    assert deployment.status == DeploymentStatus.COMPLETED_WITH_ERRORS  # 1 success + 1 failed
    assert result["stale_jobs_failed"] == 1
    assert result["reconciled"] == 1
    assert deployment.id in _no_redis  # release_slot đã được gọi cho job kẹt
    assert _stub_cleanup == [
        {"job_id": stale_job.pk, "hostname": "PC-1", "job_token": f"job{stale_job.pk}"},
    ]


def test_stale_agent_job_marked_failed_without_smb_cleanup(deployment, _stub_cleanup):
    """Máy agent không dùng PushExecutor — watchdog không gọi cleanup SMB."""
    m = Machine.objects.create(hostname="AGENT-1", connection_mode=ConnectionMode.AGENT)
    stale_job = Job.objects.create(
        deployment=deployment, machine=m, status=JobStatus.RUNNING,
        started_at=timezone.now() - timedelta(hours=1),
    )

    result = reconcile_stuck_deployments()

    stale_job.refresh_from_db()
    assert stale_job.status == JobStatus.FAILED
    assert result["stale_jobs_failed"] == 1
    assert _stub_cleanup == []


def test_agent_job_queued_past_timeout_marked_failed(deployment, settings):
    """Job của máy connection_mode=agent ở QUEUED quá AGENT_JOB_QUEUE_TIMEOUT (agent chưa
    từng poll tới — offline/chưa cài) phải tự đánh FAILED, không kẹt vô thời hạn."""
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "AGENT_JOB_QUEUE_TIMEOUT": 3600}
    m = Machine.objects.create(hostname="AGENT-STUCK", connection_mode=ConnectionMode.AGENT)
    stuck_job = Job.objects.create(deployment=deployment, machine=m, status=JobStatus.QUEUED)
    Job.objects.filter(pk=stuck_job.pk).update(created_at=timezone.now() - timedelta(hours=2))

    result = reconcile_stuck_deployments()

    stuck_job.refresh_from_db()
    assert stuck_job.status == JobStatus.FAILED
    assert "Agent chưa từng poll" in stuck_job.error_output
    assert result["agent_queued_failed"] == 1


def test_agent_job_queued_within_timeout_left_untouched(deployment, settings):
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "AGENT_JOB_QUEUE_TIMEOUT": 3600}
    m = Machine.objects.create(hostname="AGENT-FRESH", connection_mode=ConnectionMode.AGENT)
    job = Job.objects.create(deployment=deployment, machine=m, status=JobStatus.QUEUED)

    result = reconcile_stuck_deployments()

    job.refresh_from_db()
    assert job.status == JobStatus.QUEUED
    assert result["agent_queued_failed"] == 0
