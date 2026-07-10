"""DeploymentSchedule (lịch lặp interval/weekly, kiểu PDQ 'Repeating'/'Recurring'):
is_due(), spawn_deployment(), task trigger_due_schedules, RBAC admin-only reboot/shutdown.
"""
from datetime import time, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.utils import timezone

from apps.credentials.models import DeployCredential
from apps.deployments import tasks as dep_tasks
from apps.deployments.models import (
    Deployment,
    DeploymentAction,
    DeploymentSchedule,
    DeploymentStatus,
    RecurrenceType,
)
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


@pytest.fixture
def package_version(db):
    pkg = Package.objects.create(name="7-Zip")
    return PackageVersion.objects.create(
        package=pkg, version="23.01", installer_file="repository/x/23.01/s.exe",
        installer_type=InstallerType.EXE,
    )


@pytest.fixture
def schedule(db, credential, package_version):
    sched = DeploymentSchedule.objects.create(
        name="Cập nhật 7-Zip",
        action=DeploymentAction.INSTALL,
        package_version=package_version,
        credential=credential,
        recurrence_type=RecurrenceType.INTERVAL,
        interval_minutes=60,
    )
    sched.target_machines.add(Machine.objects.create(hostname="SCH-1"))
    return sched


# ==================== is_due() — interval ====================


def test_interval_due_when_never_triggered(schedule):
    assert schedule.is_due(timezone.now()) is True


def test_interval_not_due_before_elapsed(schedule):
    schedule.last_triggered_at = timezone.now() - timedelta(minutes=10)
    assert schedule.is_due(timezone.now()) is False


def test_interval_due_after_elapsed(schedule):
    schedule.last_triggered_at = timezone.now() - timedelta(minutes=61)
    assert schedule.is_due(timezone.now()) is True


def test_disabled_schedule_never_due(schedule):
    schedule.enabled = False
    assert schedule.is_due(timezone.now()) is False


def test_interval_without_minutes_never_due(schedule):
    schedule.interval_minutes = None
    assert schedule.is_due(timezone.now()) is False


# ==================== is_due() — weekly ====================


def test_weekly_due_on_matching_day_after_time(schedule):
    now = timezone.localtime(timezone.now())
    schedule.recurrence_type = RecurrenceType.WEEKLY
    schedule.weekly_days = [now.weekday()]
    schedule.weekly_time = (now - timedelta(minutes=5)).time()
    assert schedule.is_due(timezone.now()) is True


def test_weekly_not_due_wrong_day(schedule):
    now = timezone.localtime(timezone.now())
    schedule.recurrence_type = RecurrenceType.WEEKLY
    schedule.weekly_days = [(now.weekday() + 1) % 7]  # ngày khác hôm nay
    schedule.weekly_time = time(0, 0)
    assert schedule.is_due(timezone.now()) is False


def test_weekly_not_due_before_time(schedule):
    now = timezone.localtime(timezone.now())
    schedule.recurrence_type = RecurrenceType.WEEKLY
    schedule.weekly_days = [now.weekday()]
    schedule.weekly_time = (now + timedelta(hours=1)).time()
    assert schedule.is_due(timezone.now()) is False


def test_weekly_not_due_already_triggered_today(schedule):
    now = timezone.now()
    local_now = timezone.localtime(now)
    schedule.recurrence_type = RecurrenceType.WEEKLY
    schedule.weekly_days = [local_now.weekday()]
    schedule.weekly_time = (local_now - timedelta(minutes=30)).time()
    schedule.last_triggered_at = now - timedelta(minutes=10)  # đã chạy sau giờ hẹn hôm nay
    assert schedule.is_due(now) is False


# ==================== spawn_deployment ====================


def test_spawn_deployment_copies_config(schedule):
    dep = schedule.spawn_deployment()
    assert dep.schedule_id == schedule.id
    assert dep.action == schedule.action
    assert dep.package_version_id == schedule.package_version_id
    assert dep.credential_id == schedule.credential_id
    assert list(dep.target_machines.values_list("id", flat=True)) == list(
        schedule.target_machines.values_list("id", flat=True)
    )
    assert schedule.name in dep.name


# ==================== task trigger_due_schedules ====================


def test_trigger_due_schedules_launches_and_updates_last_triggered(schedule, monkeypatch):
    calls = []
    monkeypatch.setattr(dep_tasks, "launch_deployment", lambda d: calls.append(d.id) or 1)

    result = dep_tasks.trigger_due_schedules()

    assert result == {"triggered": 1}
    assert len(calls) == 1
    schedule.refresh_from_db()
    assert schedule.last_triggered_at is not None
    dep = Deployment.objects.get(pk=calls[0])
    assert dep.schedule_id == schedule.id


def test_trigger_due_schedules_skips_not_due(schedule, monkeypatch):
    schedule.last_triggered_at = timezone.now()  # vừa chạy → chưa tới hạn tiếp
    schedule.save()
    calls = []
    monkeypatch.setattr(dep_tasks, "launch_deployment", lambda d: calls.append(d.id) or 1)

    result = dep_tasks.trigger_due_schedules()

    assert result == {"triggered": 0}
    assert calls == []


def test_trigger_due_schedules_launch_error_marks_failed(schedule, monkeypatch):
    def boom(d):
        raise RuntimeError("broker down")

    monkeypatch.setattr(dep_tasks, "launch_deployment", boom)

    dep_tasks.trigger_due_schedules()

    dep = Deployment.objects.filter(schedule=schedule).first()
    assert dep is not None
    assert dep.status == DeploymentStatus.FAILED


def test_trigger_due_schedules_launch_error_reverts_last_triggered(schedule, monkeypatch):
    # Trước fix: last_triggered_at bị ghi NGAY dù launch fail → mất nguyên 1 chu kỳ.
    # Sau fix: revert lại giá trị cũ để lịch được thử lại ở tick kế tiếp.
    previous = timezone.now() - timedelta(minutes=61)
    schedule.last_triggered_at = previous
    schedule.save()

    def boom(d):
        raise RuntimeError("broker down")

    monkeypatch.setattr(dep_tasks, "launch_deployment", boom)
    dep_tasks.trigger_due_schedules()

    schedule.refresh_from_db()
    assert schedule.last_triggered_at == previous
    assert schedule.is_due(timezone.now()) is True


def test_trigger_due_schedules_no_machines_completes(schedule, monkeypatch):
    schedule.target_machines.clear()
    monkeypatch.setattr(dep_tasks, "launch_deployment", lambda d: 0)

    dep_tasks.trigger_due_schedules()

    dep = Deployment.objects.filter(schedule=schedule).first()
    assert dep.status == DeploymentStatus.COMPLETED


# ==================== API: RBAC + validation ====================


@pytest.fixture
def roles(db):
    for name in ("admin", "operator", "viewer"):
        Group.objects.get_or_create(name=name)


def _client(username, group=None, superuser=False):
    if superuser:
        User.objects.create_superuser(username, f"{username}@x.com", "pass12345")
    else:
        u = User.objects.create_user(username, password="pass12345")
        if group:
            u.groups.add(Group.objects.get(name=group))
    c = Client()
    c.post(
        "/api/auth/login/",
        {"username": username, "password": "pass12345"},
        content_type="application/json",
    )
    return c


def test_operator_cannot_create_reboot_schedule(db, roles, credential):
    op = _client("op1", group="operator")
    r = op.post(
        "/api/deployment-schedules/",
        {
            "name": "Reboot nightly",
            "action": "reboot",
            "credential": credential.id,
            "target_machines": [Machine.objects.create(hostname="RBAC-1").id],
            "recurrence_type": "interval",
            "interval_minutes": 60,
        },
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "action" in r.json()


def test_admin_can_create_reboot_schedule(db, roles, credential):
    admin = _client("admin1", superuser=True)
    r = admin.post(
        "/api/deployment-schedules/",
        {
            "name": "Reboot nightly",
            "action": "reboot",
            "credential": credential.id,
            "target_machines": [Machine.objects.create(hostname="RBAC-1").id],
            "recurrence_type": "weekly",
            "weekly_days": [0, 2, 4],
            "weekly_time": "22:00:00",
        },
        content_type="application/json",
    )
    assert r.status_code == 201


def test_create_schedule_requires_interval_minutes(db, roles, credential, package_version):
    op = _client("op2", group="operator")
    r = op.post(
        "/api/deployment-schedules/",
        {
            "name": "Bad interval",
            "action": "install",
            "package_version": package_version.id,
            "credential": credential.id,
            "target_machines": [Machine.objects.create(hostname="RBAC-1").id],
            "recurrence_type": "interval",
        },
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "interval_minutes" in r.json()


def test_create_schedule_requires_weekly_fields(db, roles, credential, package_version):
    op = _client("op3", group="operator")
    r = op.post(
        "/api/deployment-schedules/",
        {
            "name": "Bad weekly",
            "action": "install",
            "package_version": package_version.id,
            "credential": credential.id,
            "target_machines": [Machine.objects.create(hostname="RBAC-1").id],
            "recurrence_type": "weekly",
        },
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "weekly_days" in r.json()
