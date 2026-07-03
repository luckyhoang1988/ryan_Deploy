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
