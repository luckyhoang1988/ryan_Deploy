"""scheduled_at: beat task auto-trigger + view đánh dấu SCHEDULED cho lịch tương lai."""
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.utils import timezone

from apps.deployments import tasks as dep_tasks
from apps.deployments.models import Deployment, DeploymentStatus
from apps.credentials.models import DeployCredential
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def deployment(db):
    pkg = Package.objects.create(name="Office")
    pv = PackageVersion.objects.create(
        package=pkg, version="2024", installer_file="repository/x/2024/s.exe",
        installer_type=InstallerType.EXE,
    )
    cred = DeployCredential.objects.create(name="svc", username="svc_deploy")
    dep = Deployment.objects.create(name="Rollout", package_version=pv, credential=cred)
    dep.target_machines.add(Machine.objects.create(hostname="PC-1"))
    return dep


def test_due_scheduled_is_triggered(deployment, monkeypatch):
    calls = []
    monkeypatch.setattr(dep_tasks, "launch_deployment", lambda d: calls.append(d.id) or 1)
    deployment.status = DeploymentStatus.SCHEDULED
    deployment.scheduled_at = timezone.now() - timedelta(minutes=1)
    deployment.save()

    result = dep_tasks.trigger_scheduled_deployments()

    assert result == {"launched": 1, "due": 1}
    assert calls == [deployment.id]
    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.RUNNING


def test_future_scheduled_is_not_triggered(deployment, monkeypatch):
    calls = []
    monkeypatch.setattr(dep_tasks, "launch_deployment", lambda d: calls.append(d.id) or 1)
    deployment.status = DeploymentStatus.SCHEDULED
    deployment.scheduled_at = timezone.now() + timedelta(hours=1)
    deployment.save()

    result = dep_tasks.trigger_scheduled_deployments()

    assert result == {"launched": 0, "due": 0}
    assert calls == []
    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.SCHEDULED


def test_due_but_no_enabled_machine_closes_deployment(deployment, monkeypatch):
    # launch trả 0 (không máy enabled) → deployment không được để kẹt RUNNING.
    monkeypatch.setattr(dep_tasks, "launch_deployment", lambda d: 0)
    deployment.status = DeploymentStatus.SCHEDULED
    deployment.scheduled_at = timezone.now() - timedelta(minutes=1)
    deployment.save()

    dep_tasks.trigger_scheduled_deployments()

    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.COMPLETED


def test_launch_error_marks_failed(deployment, monkeypatch):
    # launch_deployment ném lỗi (broker/DB) sau khi đã claim RUNNING → phải revert FAILED,
    # không để kẹt RUNNING vĩnh viễn.
    def boom(d):
        raise RuntimeError("broker down")

    monkeypatch.setattr(dep_tasks, "launch_deployment", boom)
    deployment.status = DeploymentStatus.SCHEDULED
    deployment.scheduled_at = timezone.now() - timedelta(minutes=1)
    deployment.save()

    dep_tasks.trigger_scheduled_deployments()

    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.FAILED
    assert deployment.finished_at is not None


def test_reconcile_no_jobs_timeout_fails(deployment):
    # RUNNING quá lâu mà chưa có job nào → reconcile đánh FAILED.
    deployment.status = DeploymentStatus.RUNNING
    deployment.started_at = timezone.now() - timedelta(
        seconds=dep_tasks._STUCK_NO_JOB_SECONDS + 60
    )
    deployment.save()

    result = dep_tasks.reconcile_stuck_deployments()

    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.FAILED
    assert result["failed"] == 1


def test_reconcile_no_jobs_within_grace_left_running(deployment):
    # Vừa chuyển RUNNING, job chưa kịp tạo (trong thời gian gia hạn) → để yên.
    deployment.status = DeploymentStatus.RUNNING
    deployment.started_at = timezone.now()
    deployment.save()

    dep_tasks.reconcile_stuck_deployments()

    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.RUNNING


def test_trigger_view_future_schedule_marks_scheduled(deployment):
    Group.objects.get_or_create(name="admin")
    User.objects.create_superuser("admin", "a@a.com", "pass12345")
    c = Client()
    c.post("/api/auth/login/", {"username": "admin", "password": "pass12345"}, content_type="application/json")

    deployment.scheduled_at = timezone.now() + timedelta(hours=2)
    deployment.save()

    r = c.post(f"/api/deployments/{deployment.id}/trigger/", {}, content_type="application/json")

    assert r.status_code == 202
    assert r.json()["status"] == DeploymentStatus.SCHEDULED
    deployment.refresh_from_db()
    assert deployment.status == DeploymentStatus.SCHEDULED
