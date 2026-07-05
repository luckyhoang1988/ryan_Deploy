"""
Phase 2 (hardening) — kiểm thử 5 mục:
2.1 N+1 ở list deployment (annotate thay vì property/deployment)
2.2 sync AD / check online chạy nền (async) + endpoint /tasks/<id>/
2.3 hủy deployment revoke terminate=True (giết cả job đang chạy)
2.4 finalize xử lý all-cancelled + reconcile deployment kẹt RUNNING
"""
import pytest
from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.credentials.models import DeployCredential
from apps.deployments import orchestrator
from apps.deployments import tasks as dep_tasks
from apps.deployments.models import Deployment, DeploymentStatus
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import finalize_deployment
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def roles(db):
    for name in ("admin", "operator", "viewer"):
        Group.objects.get_or_create(name=name)


@pytest.fixture
def admin_client(db, roles):
    User.objects.create_superuser("admin", "a@a.com", "pass12345")
    c = Client()
    c.post("/api/auth/login/", {"username": "admin", "password": "pass12345"}, content_type="application/json")
    return c


@pytest.fixture
def package_version(db):
    pkg = Package.objects.create(name="Office")
    return PackageVersion.objects.create(
        package=pkg, version="2024", installer_file="repository/x/2024/s.exe",
        installer_type=InstallerType.EXE,
    )


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


def _make_deployment(package_version, credential, name, job_statuses):
    dep = Deployment.objects.create(name=name, package_version=package_version, credential=credential)
    for i, st in enumerate(job_statuses):
        m = Machine.objects.create(hostname=f"{name}-PC-{i}")
        dep.target_machines.add(m)
        Job.objects.create(deployment=dep, machine=m, status=st)
    return dep


# ---------------- 2.1 N+1 ----------------


def test_deployment_list_counts_correct(admin_client, package_version, credential):
    _make_deployment(
        package_version, credential, "Rollout",
        [JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT, JobStatus.FAILED, JobStatus.RUNNING],
    )
    r = admin_client.get("/api/deployments/")
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert row["total_count"] == 4
    assert row["success_count"] == 2  # gồm success_reboot
    assert row["failed_count"] == 1
    assert row["pending_count"] == 1  # running


def test_deployment_list_no_n_plus_1(admin_client, package_version, credential):
    """Số query khi list KHÔNG tăng theo số deployment (chống N+1)."""
    _make_deployment(package_version, credential, "D1", [JobStatus.SUCCESS, JobStatus.FAILED])

    with CaptureQueriesContext(connection) as ctx1:
        admin_client.get("/api/deployments/")
    q1 = len(ctx1)

    for n in range(2, 6):
        _make_deployment(package_version, credential, f"D{n}", [JobStatus.SUCCESS, JobStatus.FAILED])

    with CaptureQueriesContext(connection) as ctx5:
        admin_client.get("/api/deployments/")
    q5 = len(ctx5)

    assert q5 == q1, f"N+1: 1 deployment dùng {q1} query, 5 deployment dùng {q5}"


# ---------------- 2.2 async + task-status ----------------


def test_sync_ad_dispatches_async_and_audits(admin_client):
    r = admin_client.post("/api/machines/sync_ad/", {}, content_type="application/json")
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    assert task_id

    # Poll endpoint task-status (eager → đã xong ngay)
    t = admin_client.get(f"/api/tasks/{task_id}/")
    assert t.status_code == 200
    body = t.json()
    assert body["ready"] is True
    # Không cấu hình AD → result có 'error', nhưng audit vẫn được ghi trong task
    assert "result" in body
    assert AuditLog.objects.filter(action=AuditLog.Action.MACHINE_SYNC).exists()


def test_check_online_dispatches_async(admin_client, monkeypatch):
    # refresh thật sẽ ping/SMB + ghi DB trong ThreadPool → dưới SQLite test bị khóa bảng;
    # ở đây chỉ kiểm luồng async + endpoint task-status nên thay bằng no-op (không chạm DB).
    from apps.machines import tasks as m_tasks

    monkeypatch.setattr(m_tasks, "refresh_machine_status", lambda m: False)
    Machine.objects.create(hostname="PC-ONLINE-1", enabled=True)
    r = admin_client.post("/api/machines/check_online/", {}, content_type="application/json")
    assert r.status_code == 202
    task_id = r.json()["task_id"]

    t = admin_client.get(f"/api/tasks/{task_id}/").json()
    assert t["ready"] is True
    assert t["result"]["checked"] == 1


def test_check_online_closes_thread_local_db_connections(monkeypatch):
    # Mỗi luồng của ThreadPoolExecutor nằm ngoài vòng đời Celery task nên Django không
    # tự đóng connection cho chúng — _refresh_and_close phải tự gọi connections.close_all().
    from apps.machines import tasks as m_tasks

    calls = []
    monkeypatch.setattr(m_tasks, "refresh_machine_status", lambda m: calls.append(m) or True)
    monkeypatch.setattr(m_tasks.connections, "close_all", lambda: calls.append("closed"))

    assert m_tasks._refresh_and_close("fake-machine") is True
    assert calls == ["fake-machine", "closed"]


def test_check_online_closes_connections_even_on_error(monkeypatch):
    from apps.machines import tasks as m_tasks

    closed = []
    monkeypatch.setattr(m_tasks.connections, "close_all", lambda: closed.append(True))

    def boom(m):
        raise RuntimeError("SMB timeout")

    monkeypatch.setattr(m_tasks, "refresh_machine_status", boom)

    with pytest.raises(RuntimeError):
        m_tasks._refresh_and_close("fake-machine")
    assert closed == [True]


def test_disabling_machine_clears_stale_is_online(admin_client):
    m = Machine.objects.create(hostname="PC-STALE-1", enabled=True, is_online=True)
    r = admin_client.patch(
        f"/api/machines/{m.id}/", {"enabled": False}, content_type="application/json"
    )
    assert r.status_code == 200
    m.refresh_from_db()
    assert m.enabled is False
    assert m.is_online is False


def test_updating_other_field_does_not_touch_is_online(admin_client):
    m = Machine.objects.create(hostname="PC-STALE-2", enabled=True, is_online=True)
    r = admin_client.patch(
        f"/api/machines/{m.id}/", {"os_name": "Windows 11"}, content_type="application/json"
    )
    assert r.status_code == 200
    m.refresh_from_db()
    assert m.is_online is True


# ---------------- 2.2b trigger/cancel: claim nguyên tử chỉ 1 caller thắng ----------------


def test_trigger_atomic_claim_only_one_caller_wins(package_version, credential):
    # Audit finding "Race condition trigger thủ công": 2 request POST /trigger/ đồng thời
    # (double-click) không được cùng chuyển deployment sang RUNNING. Test trực tiếp câu
    # UPDATE có điều kiện dùng trong views.py (mô phỏng 2 caller race nhau) — không dựng
    # thread thật vì SQLite test không chịu được ghi đa luồng (xem LESSONS.md).
    dep = Deployment.objects.create(name="D", package_version=package_version, credential=credential)

    first = (
        Deployment.objects.filter(pk=dep.pk)
        .exclude(status=DeploymentStatus.RUNNING)
        .update(status=DeploymentStatus.RUNNING)
    )
    second = (
        Deployment.objects.filter(pk=dep.pk)
        .exclude(status=DeploymentStatus.RUNNING)
        .update(status=DeploymentStatus.RUNNING)
    )

    assert (first, second) == (1, 0)


def test_cancel_atomic_claim_only_one_caller_wins(package_version, credential):
    dep = _make_deployment(package_version, credential, "D2", [JobStatus.RUNNING])
    Deployment.objects.filter(pk=dep.pk).update(status=DeploymentStatus.RUNNING)

    first = (
        Deployment.objects.filter(
            pk=dep.pk, status__in=[DeploymentStatus.SCHEDULED, DeploymentStatus.RUNNING]
        ).update(status=DeploymentStatus.CANCELLED)
    )
    second = (
        Deployment.objects.filter(
            pk=dep.pk, status__in=[DeploymentStatus.SCHEDULED, DeploymentStatus.RUNNING]
        ).update(status=DeploymentStatus.CANCELLED)
    )

    assert (first, second) == (1, 0)


# ---------------- 2.3 cancel terminate ----------------


def test_cancel_revokes_with_terminate(package_version, credential, monkeypatch):
    dep = _make_deployment(package_version, credential, "Cancel", [JobStatus.RUNNING])
    job = dep.jobs.first()
    job.celery_task_id = "task-abc"
    job.save(update_fields=["celery_task_id"])

    calls = []
    from ryandeploy.celery import app

    monkeypatch.setattr(app.control, "revoke", lambda tid, **kw: calls.append((tid, kw)))
    monkeypatch.setattr(orchestrator, "clear_slots", lambda _id: None)

    orchestrator.cancel_deployment(dep)

    assert calls == [("task-abc", {"terminate": True})]
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED


def test_cancel_deployment_does_not_overwrite_job_finished_concurrently(
    package_version, credential, monkeypatch
):
    # Audit finding "Cancel bị ghi đè bởi RUNNING": trước fix, cancel_deployment() đọc
    # danh sách job "chưa kết thúc" rồi ghi CANCELLED vô điều kiện — nếu 1 worker khác
    # ghi SUCCESS đúng lúc đang lặp (vd ngay trong lúc revoke()), CANCELLED sẽ ghi đè
    # SUCCESS. Sau fix: UPDATE có điều kiện loại trừ job đã terminal → không ghi đè.
    dep = _make_deployment(package_version, credential, "RaceCancel", [JobStatus.RUNNING])
    job = dep.jobs.first()
    job.celery_task_id = "task-race"
    job.save(update_fields=["celery_task_id"])

    from ryandeploy.celery import app

    def fake_revoke(tid, **kw):
        # Giả lập worker khác vừa ghi xong SUCCESS đúng lúc cancel_deployment() đang xử lý
        # job này (cửa sổ giữa lúc build danh sách "pending" và lúc ghi CANCELLED).
        Job.objects.filter(pk=job.pk).update(status=JobStatus.SUCCESS, finished_at=None)

    monkeypatch.setattr(app.control, "revoke", fake_revoke)
    monkeypatch.setattr(orchestrator, "clear_slots", lambda _id: None)

    count = orchestrator.cancel_deployment(dep)

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS  # KHÔNG bị lật ngược thành CANCELLED
    assert count == 0


def test_write_job_result_skips_when_job_already_cancelled(package_version, credential):
    # Audit finding "Cancel bị ghi đè bởi RUNNING": _run_job trước fix ghi SUCCESS/FAILED
    # vô điều kiện sau executor.run(), có thể ghi đè CANCELLED do cancel_deployment() vừa
    # đặt. _write_job_result() phải từ chối ghi khi job đã CANCELLED.
    from apps.jobs.tasks import _write_job_result

    dep = _make_deployment(package_version, credential, "RaceRunJob", [JobStatus.RUNNING])
    job = dep.jobs.first()
    Job.objects.filter(pk=job.pk).update(status=JobStatus.CANCELLED)

    ok = _write_job_result(job, status=JobStatus.SUCCESS, exit_code=0)

    assert ok is False
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED


def test_write_job_result_writes_when_not_cancelled(package_version, credential):
    from apps.jobs.tasks import _write_job_result

    dep = _make_deployment(package_version, credential, "NoRaceRunJob", [JobStatus.RUNNING])
    job = dep.jobs.first()

    ok = _write_job_result(job, status=JobStatus.SUCCESS, exit_code=0)

    assert ok is True
    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS


# ---------------- 2.4 finalize all-cancelled + reconcile ----------------


def test_finalize_all_cancelled_is_cancelled(package_version, credential):
    dep = _make_deployment(package_version, credential, "AllCancel", [JobStatus.CANCELLED, JobStatus.CANCELLED])
    Deployment.objects.filter(id=dep.id).update(status=DeploymentStatus.RUNNING)
    finalize_deployment(None, dep.id)
    dep.refresh_from_db()
    assert dep.status == DeploymentStatus.CANCELLED


def test_reconcile_finalizes_stuck_running(package_version, credential):
    dep = _make_deployment(package_version, credential, "Stuck", [JobStatus.SUCCESS, JobStatus.SUCCESS])
    Deployment.objects.filter(id=dep.id).update(status=DeploymentStatus.RUNNING)

    result = dep_tasks.reconcile_stuck_deployments()

    assert result == {"reconciled": 1, "failed": 0}
    dep.refresh_from_db()
    assert dep.status == DeploymentStatus.COMPLETED


def test_reconcile_skips_active_running(package_version, credential):
    dep = _make_deployment(package_version, credential, "Active", [JobStatus.SUCCESS, JobStatus.RUNNING])
    Deployment.objects.filter(id=dep.id).update(status=DeploymentStatus.RUNNING)

    result = dep_tasks.reconcile_stuck_deployments()

    assert result == {"reconciled": 0, "failed": 0}
    dep.refresh_from_db()
    assert dep.status == DeploymentStatus.RUNNING  # còn job RUNNING → để yên
