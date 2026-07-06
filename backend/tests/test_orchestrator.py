"""
Retrigger 1 deployment không được kế thừa attempts/started_at/celery_task_id từ lần
chạy trước — nếu không, job mới sẽ mất hết lượt retry ngay từ lần thử đầu tiên (do
`job.attempts <= deployment.retry_limit` so với giá trị attempts cũ còn sót lại).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentAction
from apps.deployments import orchestrator as orch
from apps.jobs.models import Job, JobStatus
from apps.machines.models import Machine
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
