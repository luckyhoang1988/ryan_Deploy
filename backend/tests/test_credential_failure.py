"""
Giải mã credential lỗi (VD xoay VAULT_KEY, ciphertext hỏng) không được để job kẹt
RUNNING vĩnh viễn — job phải chuyển FAILED và task không ném exception ra ngoài Celery.
"""
import pytest

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentAction
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import deploy_to_machine
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


@pytest.fixture
def job(credential):
    pkg = Package.objects.create(name="Firefox")
    pv = PackageVersion.objects.create(
        package=pkg, version="1", installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE, install_command='"{file}" /S',
    )
    dep = Deployment.objects.create(
        name="D", action=DeploymentAction.INSTALL, package_version=pv, credential=credential
    )
    m = Machine.objects.create(hostname="PC-1")
    dep.target_machines.add(m)
    return Job.objects.create(deployment=dep, machine=m, status=JobStatus.QUEUED)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("apps.deployments.semaphore.acquire_slot", lambda *a, **k: True)
    monkeypatch.setattr("apps.deployments.semaphore.release_slot", lambda *a, **k: None)


def test_decrypt_failure_marks_job_failed_not_stuck_running(job, monkeypatch):
    def _boom(self):
        raise ValueError("sai VAULT_KEY hoặc dữ liệu hỏng")

    monkeypatch.setattr(DeployCredential, "get_password", _boom)

    # Task không được ném exception ra ngoài (nếu không Celery sẽ để job kẹt RUNNING).
    result = deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert job.status != JobStatus.RUNNING
    assert "giải mã" in job.error_output.lower()
    assert result["status"] == "failed"
    assert result["error"] == "credential_decrypt_failed"
