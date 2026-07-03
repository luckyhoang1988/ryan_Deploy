"""Bộ đếm trạng thái deployment + logic finalize phải tính cả success_reboot (exit 3010)."""
import pytest

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentStatus
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import finalize_deployment
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def deployment(db):
    pkg = Package.objects.create(name="Office")
    pv = PackageVersion.objects.create(
        package=pkg, version="2024", installer_file="repository/x/2024/setup.exe",
        installer_type=InstallerType.EXE,
    )
    cred = DeployCredential.objects.create(name="svc", username="svc_deploy")
    return Deployment.objects.create(name="Rollout", package_version=pv, credential=cred)


def _add_jobs(deployment, statuses):
    for i, st in enumerate(statuses):
        m = Machine.objects.create(hostname=f"PC-{i}")
        Job.objects.create(deployment=deployment, machine=m, status=st)


def test_success_count_includes_reboot(deployment):
    _add_jobs(deployment, [JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT, JobStatus.FAILED])
    assert deployment.success_count == 2  # gồm cả success_reboot
    assert deployment.failed_count == 1


def test_finalize_all_reboot_no_fail_is_completed(deployment):
    _add_jobs(deployment, [JobStatus.SUCCESS_REBOOT, JobStatus.SUCCESS_REBOOT])
    finalize_deployment(None, deployment.id)
    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.COMPLETED


def test_finalize_reboot_plus_one_fail_is_completed_with_errors(deployment):
    # Trước fix: success_count == 0 → bị đánh FAILED sai. Sau fix → COMPLETED_WITH_ERRORS.
    _add_jobs(deployment, [JobStatus.SUCCESS_REBOOT, JobStatus.SUCCESS_REBOOT, JobStatus.FAILED])
    finalize_deployment(None, deployment.id)
    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.COMPLETED_WITH_ERRORS
