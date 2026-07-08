"""
Chế độ agent (outbound HTTPS, song song SMB — xem plan_agent.md):
- services: cấp/thu hồi token (giữ lịch sử, không vi phạm UniqueConstraint 1-active).
- auth: AgentTokenAuthentication chấp nhận/từ chối đúng theo trạng thái token/máy.
- views: poll (claim nguyên tử), download (chặn ngoài phạm vi job RUNNING), report, heartbeat.
- MachineViewSet: provision/revoke/bulk-provision token chỉ admin.
"""
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import F
from django.test import Client
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.test import APIClient, APIRequestFactory

from apps.agents.auth import AgentTokenAuthentication
from apps.agents.models import AgentToken, EnrollmentSecret
from apps.agents.permissions import IsAuthenticatedAgent
from apps.agents.services import (
    EnrollmentError,
    enroll_machine,
    hash_token,
    issue_enrollment_secret,
    issue_token,
    revoke_enrollment_secret,
    revoke_token,
)
from apps.audit.models import AuditLog
from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentAction
from apps.deployments import semaphore
from apps.jobs.models import Job, JobStatus
from apps.machines.models import ConnectionMode, Machine
from apps.packages.models import InstallerType, Package, PackageVersion
from apps.packages.repository import compute_sha256


@pytest.fixture(autouse=True)
def _no_redis_semaphore(monkeypatch):
    # Test không cần Redis thật — chỉ quan tâm logic view, không quan tâm cơ chế đếm slot.
    # views.py import acquire_slot/release_slot cục bộ TRONG hàm (như jobs/tasks.py) chính
    # là để patch tại đây có tác dụng bất kể thứ tự các module đã được import trước đó.
    monkeypatch.setattr(semaphore, "acquire_slot", lambda *a, **k: True)
    monkeypatch.setattr(semaphore, "release_slot", lambda *a, **k: None)


@pytest.fixture
def agent_machine(db):
    return Machine.objects.create(hostname="AGENT-PC01", connection_mode=ConnectionMode.AGENT, enabled=True)


@pytest.fixture
def credential(db):
    cred = DeployCredential.objects.create(name="svc-agent", domain="CORP", username="svc")
    cred.set_password("x")
    cred.save()
    return cred


@pytest.fixture
def package_version(db):
    pkg = Package.objects.create(name="7zip")
    content = b"MZ-fake-installer-bytes"
    upload = SimpleUploadedFile("7zip.exe", content)
    sha = compute_sha256(upload)
    return PackageVersion.objects.create(
        package=pkg, version="1.0", installer_file=upload, installer_type=InstallerType.EXE,
        install_command='"{file}" /S', success_exit_codes=[0], sha256=sha, file_size=len(content),
    )


@pytest.fixture
def install_deployment(db, agent_machine, credential, package_version):
    dep = Deployment.objects.create(
        name="Deploy 7zip qua agent", action=DeploymentAction.INSTALL,
        package_version=package_version, credential=credential,
    )
    dep.target_machines.add(agent_machine)
    Job.objects.create(deployment=dep, machine=agent_machine, status=JobStatus.QUEUED)
    return dep


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
def operator_client(db, roles):
    user = User.objects.create_user("op", "op@a.com", "pass12345")
    user.groups.add(Group.objects.get(name="operator"))
    c = Client()
    c.post("/api/auth/login/", {"username": "op", "password": "pass12345"}, content_type="application/json")
    return c


# ---------------- services.py: issue_token / revoke_token ----------------


def test_issue_token_revokes_previous_and_keeps_history(agent_machine):
    raw1 = issue_token(agent_machine)
    t1 = AgentToken.objects.get(machine=agent_machine)
    assert t1.token_hash == hash_token(raw1)
    assert t1.revoked_at is None

    raw2 = issue_token(agent_machine)
    t1.refresh_from_db()
    assert t1.revoked_at is not None  # token cũ bị thu hồi
    assert AgentToken.objects.filter(machine=agent_machine).count() == 2  # giữ lịch sử

    t2 = AgentToken.objects.get(machine=agent_machine, revoked_at__isnull=True)
    assert t2.token_hash == hash_token(raw2)


def test_issue_token_after_full_revoke_history_does_not_violate_unique_constraint(agent_machine):
    issue_token(agent_machine)
    revoke_token(agent_machine)
    raw3 = issue_token(agent_machine)  # không được vi phạm UniqueConstraint 1-active-per-machine
    t3 = AgentToken.objects.get(machine=agent_machine, revoked_at__isnull=True)
    assert t3.token_hash == hash_token(raw3)


def test_revoke_token_idempotent(agent_machine):
    issue_token(agent_machine)
    assert revoke_token(agent_machine) is True
    assert revoke_token(agent_machine) is False  # không còn token active để thu hồi


# ---------------- auth.py: AgentTokenAuthentication ----------------


def test_auth_accepts_valid_token_and_binds_agent_machine(agent_machine):
    raw = issue_token(agent_machine)
    req = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    result = AgentTokenAuthentication().authenticate(req)
    assert result is not None
    assert req.agent_machine.pk == agent_machine.pk
    assert IsAuthenticatedAgent().has_permission(req, None) is True


def test_auth_no_header_returns_none(db):
    req = APIRequestFactory().get("/")
    assert AgentTokenAuthentication().authenticate(req) is None


def test_auth_rejects_wrong_token(agent_machine):
    issue_token(agent_machine)
    req = APIRequestFactory().get("/", HTTP_AUTHORIZATION="Bearer wrong-token")
    with pytest.raises(exceptions.AuthenticationFailed):
        AgentTokenAuthentication().authenticate(req)


def test_auth_rejects_revoked_token(agent_machine):
    raw = issue_token(agent_machine)
    revoke_token(agent_machine)
    req = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    with pytest.raises(exceptions.AuthenticationFailed):
        AgentTokenAuthentication().authenticate(req)


def test_auth_rejects_disabled_machine(agent_machine):
    raw = issue_token(agent_machine)
    agent_machine.enabled = False
    agent_machine.save(update_fields=["enabled"])
    req = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    with pytest.raises(exceptions.AuthenticationFailed):
        AgentTokenAuthentication().authenticate(req)


# ---------------- views.py: poll / report / download / heartbeat ----------------


def _auth_header(raw_token):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"}


def test_poll_claims_job_atomically_only_one_winner(agent_machine, install_deployment):
    raw = issue_token(agent_machine)
    job = Job.objects.get(deployment=install_deployment)

    from apps.jobs.models import Job as JobModel
    from django.db.models import F

    # 2 lần "poll" đồng thời mô phỏng bằng UPDATE có điều kiện trực tiếp (đúng cơ chế view dùng)
    c1 = JobModel.objects.filter(pk=job.pk, status=JobStatus.QUEUED).update(
        status=JobStatus.RUNNING, attempts=F("attempts") + 1, started_at=timezone.now(),
    )
    c2 = JobModel.objects.filter(pk=job.pk, status=JobStatus.QUEUED).update(
        status=JobStatus.RUNNING, attempts=F("attempts") + 1, started_at=timezone.now(),
    )
    assert (c1, c2) in [(1, 0), (0, 1)]  # chỉ đúng 1 UPDATE thắng

    # Qua view thật: job đã RUNNING (giả lập ở trên) -> poll không còn gì để trả
    client = APIClient()
    resp = client.post("/api/agent/jobs/poll/", **_auth_header(raw))
    assert resp.status_code == 200
    assert resp.json() == {"job": None}


def test_poll_returns_job_payload_and_marks_running(agent_machine, install_deployment, package_version):
    raw = issue_token(agent_machine)
    job = Job.objects.get(deployment=install_deployment)

    client = APIClient()
    resp = client.post("/api/agent/jobs/poll/", **_auth_header(raw))
    assert resp.status_code == 200
    data = resp.json()["job"]
    assert data["job_id"] == job.pk
    assert data["action"] == "install"
    assert data["payload"]["sha256"] == package_version.sha256
    assert data["payload"]["download_url"].endswith(f"/api/agent/packages/{package_version.pk}/download/")

    job.refresh_from_db()
    assert job.status == JobStatus.RUNNING

    # Không còn job QUEUED nào khác cho máy này
    resp2 = client.post("/api/agent/jobs/poll/", **_auth_header(raw))
    assert resp2.json() == {"job": None}


def test_download_rejected_without_running_job_for_that_version(agent_machine, package_version):
    raw = issue_token(agent_machine)
    client = APIClient()
    resp = client.get(f"/api/agent/packages/{package_version.pk}/download/", **_auth_header(raw))
    assert resp.status_code == 403


def test_download_succeeds_with_running_job_and_sets_sha256_header(
    agent_machine, install_deployment, package_version,
):
    raw = issue_token(agent_machine)
    client = APIClient()
    client.post("/api/agent/jobs/poll/", **_auth_header(raw))  # claim -> RUNNING

    resp = client.get(f"/api/agent/packages/{package_version.pk}/download/", **_auth_header(raw))
    assert resp.status_code == 200
    assert resp["X-Ryandeploy-Sha256"] == package_version.sha256


def test_report_success_writes_job_and_releases(agent_machine, install_deployment):
    raw = issue_token(agent_machine)
    client = APIClient()
    poll = client.post("/api/agent/jobs/poll/", **_auth_header(raw)).json()["job"]

    resp = client.post(
        f"/api/agent/jobs/{poll['job_id']}/report/",
        {"exit_code": 0, "stdout": "install ok", "needs_reboot": False},
        format="json", **_auth_header(raw),
    )
    assert resp.status_code == 200
    job = Job.objects.get(pk=poll["job_id"])
    assert job.status == JobStatus.SUCCESS
    assert job.exit_code == 0


def test_report_verify_passed_false_forces_failed(agent_machine, install_deployment):
    raw = issue_token(agent_machine)
    client = APIClient()
    poll = client.post("/api/agent/jobs/poll/", **_auth_header(raw)).json()["job"]

    resp = client.post(
        f"/api/agent/jobs/{poll['job_id']}/report/",
        {"exit_code": 0, "stdout": "ok", "verify_passed": False},
        format="json", **_auth_header(raw),
    )
    assert resp.status_code == 200
    job = Job.objects.get(pk=poll["job_id"])
    assert job.status == JobStatus.FAILED
    assert "Hậu kiểm" in job.error_output


def test_report_twice_second_call_conflicts(agent_machine, install_deployment):
    raw = issue_token(agent_machine)
    client = APIClient()
    poll = client.post("/api/agent/jobs/poll/", **_auth_header(raw)).json()["job"]
    client.post(
        f"/api/agent/jobs/{poll['job_id']}/report/", {"exit_code": 0}, format="json", **_auth_header(raw),
    )
    resp = client.post(
        f"/api/agent/jobs/{poll['job_id']}/report/", {"exit_code": 0}, format="json", **_auth_header(raw),
    )
    assert resp.status_code == 409


def test_report_rejects_job_of_another_machine(agent_machine, install_deployment):
    other = Machine.objects.create(hostname="AGENT-PC02", connection_mode=ConnectionMode.AGENT, enabled=True)
    raw_other = issue_token(other)
    job = Job.objects.get(deployment=install_deployment)

    client = APIClient()
    resp = client.post(
        f"/api/agent/jobs/{job.pk}/report/", {"exit_code": 0}, format="json", **_auth_header(raw_other),
    )
    assert resp.status_code == 404


def test_heartbeat_updates_online_and_agent_version(agent_machine):
    raw = issue_token(agent_machine)
    client = APIClient()
    resp = client.post("/api/agent/heartbeat/", {"agent_version": "1.2.3"}, format="json", **_auth_header(raw))
    assert resp.status_code == 200
    agent_machine.refresh_from_db()
    assert agent_machine.is_online is True
    assert agent_machine.agent_version == "1.2.3"


def test_wrong_token_rejected_with_401(db):
    client = APIClient()
    resp = client.post("/api/agent/jobs/poll/", HTTP_AUTHORIZATION="Bearer nope")
    assert resp.status_code == 401


def test_poll_ignores_job_when_machine_not_in_agent_mode(agent_machine, install_deployment):
    # Máy có token hợp lệ nhưng bị chuyển (hoặc rollback) về connection_mode=smb — ví dụ giữa
    # lúc xử lý sự cố (plan_agent.md §8). Agent KHÔNG được claim job của máy này, để không
    # race với đường SMB (deploy_to_machine dispatch ngay qua Celery) và tôn trọng đúng lựa
    # chọn transport hiện tại của admin.
    raw = issue_token(agent_machine)
    agent_machine.connection_mode = ConnectionMode.SMB
    agent_machine.save(update_fields=["connection_mode"])

    client = APIClient()
    resp = client.post("/api/agent/jobs/poll/", **_auth_header(raw))
    assert resp.status_code == 200
    assert resp.json() == {"job": None}

    job = Job.objects.get(deployment=install_deployment)
    assert job.status == JobStatus.QUEUED  # không bị claim


# ---------------- MachineViewSet: provision/revoke/bulk-provision (admin-only) ----------------


def test_provision_agent_token_admin_only(admin_client, operator_client, agent_machine):
    resp_operator = operator_client.post(f"/api/machines/{agent_machine.pk}/provision_agent_token/")
    assert resp_operator.status_code == 403

    resp_admin = admin_client.post(f"/api/machines/{agent_machine.pk}/provision_agent_token/")
    assert resp_admin.status_code == 201
    raw = resp_admin.json()["token"]
    assert AgentToken.objects.get(machine=agent_machine).token_hash == hash_token(raw)


def test_revoke_agent_token_via_api(admin_client, agent_machine):
    admin_client.post(f"/api/machines/{agent_machine.pk}/provision_agent_token/")
    resp = admin_client.post(f"/api/machines/{agent_machine.pk}/revoke_agent_token/")
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    assert AgentToken.objects.get(machine=agent_machine).revoked_at is not None


def test_machine_detail_exposes_agent_token_status(admin_client, agent_machine):
    resp_none = admin_client.get(f"/api/machines/{agent_machine.pk}/")
    assert resp_none.status_code == 200
    assert resp_none.json()["agent_token"] is None  # chưa từng cấp token

    admin_client.post(f"/api/machines/{agent_machine.pk}/provision_agent_token/")
    resp = admin_client.get(f"/api/machines/{agent_machine.pk}/")
    info = resp.json()["agent_token"]
    assert info["is_active"] is True
    assert info["revoked_at"] is None
    assert info["last_used_at"] is None
    assert len(info["token_prefix"]) == 8

    admin_client.post(f"/api/machines/{agent_machine.pk}/revoke_agent_token/")
    resp2 = admin_client.get(f"/api/machines/{agent_machine.pk}/")
    info2 = resp2.json()["agent_token"]
    assert info2["is_active"] is False
    assert info2["revoked_at"] is not None


def test_bulk_provision_agent_tokens_by_ad_ou(admin_client, db):
    m1 = Machine.objects.create(hostname="OU-PC1", ad_ou="OU=Warehouse,DC=corp", enabled=True)
    m2 = Machine.objects.create(hostname="OU-PC2", ad_ou="OU=Warehouse,DC=corp", enabled=True)
    Machine.objects.create(hostname="OTHER-PC", ad_ou="OU=Office,DC=corp", enabled=True)

    resp = admin_client.post(
        "/api/machines/bulk-provision-agent-tokens/", {"ad_ou": "Warehouse"}, content_type="application/json",
    )
    assert resp.status_code == 200
    csv_text = resp.content.decode("utf-8-sig")
    assert "hostname,token" in csv_text
    assert "OU-PC1" in csv_text and "OU-PC2" in csv_text
    assert "OTHER-PC" not in csv_text
    assert AgentToken.objects.filter(machine__in=[m1, m2]).count() == 2


def test_bulk_set_connection_mode_by_ad_ou(admin_client, db):
    m1 = Machine.objects.create(hostname="ZP-PC1", ad_ou="OU=ZP,DC=corp", connection_mode=ConnectionMode.SMB)
    m2 = Machine.objects.create(hostname="ZP-PC2", ad_ou="OU=ZP,DC=corp", connection_mode=ConnectionMode.SMB)
    other = Machine.objects.create(hostname="OTHER-PC", ad_ou="OU=Office,DC=corp", connection_mode=ConnectionMode.SMB)

    resp = admin_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"ad_ou": "ZP", "connection_mode": "agent"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2, "connection_mode": "agent"}

    m1.refresh_from_db(); m2.refresh_from_db(); other.refresh_from_db()
    assert m1.connection_mode == ConnectionMode.AGENT
    assert m2.connection_mode == ConnectionMode.AGENT
    assert other.connection_mode == ConnectionMode.SMB  # ngoài OU — không đổi


def test_bulk_set_connection_mode_by_machine_ids_and_rollback(admin_client, db):
    m1 = Machine.objects.create(hostname="PILOT-1", connection_mode=ConnectionMode.SMB)

    resp = admin_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"machine_ids": [m1.pk], "connection_mode": "agent"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    m1.refresh_from_db()
    assert m1.connection_mode == ConnectionMode.AGENT

    # Rollback về SMB cho đúng máy đó.
    resp2 = admin_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"machine_ids": [m1.pk], "connection_mode": "smb"},
        content_type="application/json",
    )
    assert resp2.status_code == 200
    m1.refresh_from_db()
    assert m1.connection_mode == ConnectionMode.SMB


def test_bulk_set_connection_mode_rejects_invalid_mode_and_missing_scope(admin_client, db):
    Machine.objects.create(hostname="PC-X", connection_mode=ConnectionMode.SMB)

    resp = admin_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"machine_ids": [1], "connection_mode": "bogus"},
        content_type="application/json",
    )
    assert resp.status_code == 400

    resp2 = admin_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"connection_mode": "agent"},
        content_type="application/json",
    )
    assert resp2.status_code == 400


def test_bulk_set_connection_mode_requires_admin(admin_client, operator_client, agent_machine):
    resp_operator = operator_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"machine_ids": [agent_machine.pk], "connection_mode": "smb"},
        content_type="application/json",
    )
    assert resp_operator.status_code == 403

    resp_admin = admin_client.post(
        "/api/machines/bulk-set-connection-mode/",
        {"machine_ids": [agent_machine.pk], "connection_mode": "smb"},
        content_type="application/json",
    )
    assert resp_admin.status_code == 200


# ---------------- services.py: issue_enrollment_secret / revoke_enrollment_secret / enroll_machine ----------------


def _future(hours=1):
    return timezone.now() + timedelta(hours=hours)


def test_enroll_success_issues_token_and_audit(agent_machine):
    raw_secret, secret = issue_enrollment_secret("", _future())
    raw_token, machine = enroll_machine(raw_secret, agent_machine.hostname)

    assert machine.pk == agent_machine.pk
    assert AgentToken.objects.get(machine=agent_machine).token_hash == hash_token(raw_token)
    secret.refresh_from_db()
    assert secret.use_count == 1


def test_enroll_success_global_secret_any_ou(db):
    machine = Machine.objects.create(hostname="ANY-OU-PC", ad_ou="OU=Whatever,DC=corp", enabled=True)
    raw_secret, _ = issue_enrollment_secret("", _future())  # ad_ou trống = global
    raw_token, enrolled = enroll_machine(raw_secret, machine.hostname)
    assert enrolled.pk == machine.pk
    assert AgentToken.objects.filter(machine=machine, token_hash=hash_token(raw_token)).exists()


def test_enroll_success_scoped_ou_matches_sub_ou(db):
    machine = Machine.objects.create(hostname="SUB-OU-PC", ad_ou="OU=Sub,OU=Warehouse,DC=corp", enabled=True)
    raw_secret, _ = issue_enrollment_secret("OU=Warehouse,DC=corp", _future())
    _, enrolled = enroll_machine(raw_secret, machine.hostname)
    assert enrolled.pk == machine.pk


def test_enroll_rejects_unknown_hostname(db):
    raw_secret, _ = issue_enrollment_secret("", _future())
    with pytest.raises(EnrollmentError, match="chưa tồn tại"):
        enroll_machine(raw_secret, "GHOST-PC")


def test_enroll_rejects_disabled_machine(db):
    machine = Machine.objects.create(hostname="DISABLED-PC", enabled=False)
    raw_secret, _ = issue_enrollment_secret("", _future())
    with pytest.raises(EnrollmentError, match="vô hiệu hóa"):
        enroll_machine(raw_secret, machine.hostname)


def test_enroll_rejects_wrong_ou(db):
    machine = Machine.objects.create(hostname="WRONG-OU-PC", ad_ou="OU=Office,DC=corp", enabled=True)
    raw_secret, _ = issue_enrollment_secret("OU=Warehouse,DC=corp", _future())
    with pytest.raises(EnrollmentError, match="phạm vi OU"):
        enroll_machine(raw_secret, machine.hostname)


def test_enroll_rejects_expired_secret(agent_machine):
    raw_secret, secret = issue_enrollment_secret("", _future(hours=1))
    EnrollmentSecret.objects.filter(pk=secret.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(EnrollmentError, match="hết hạn"):
        enroll_machine(raw_secret, agent_machine.hostname)


def test_enroll_rejects_revoked_secret(agent_machine):
    raw_secret, secret = issue_enrollment_secret("", _future())
    revoke_enrollment_secret(secret)
    with pytest.raises(EnrollmentError, match="thu hồi"):
        enroll_machine(raw_secret, agent_machine.hostname)


def test_enroll_rejects_max_uses_exhausted(db):
    m1 = Machine.objects.create(hostname="MU-PC1", enabled=True)
    m2 = Machine.objects.create(hostname="MU-PC2", enabled=True)
    raw_secret, _secret = issue_enrollment_secret("", _future(), max_uses=1)

    enroll_machine(raw_secret, m1.hostname)  # dùng hết lượt duy nhất

    with pytest.raises(EnrollmentError, match="hết lượt"):
        enroll_machine(raw_secret, m2.hostname)


def test_enroll_rejects_machine_already_has_active_token(agent_machine):
    issue_token(agent_machine)  # máy đã có token active từ trước (vd cấp thủ công)
    raw_secret, _ = issue_enrollment_secret("", _future())
    with pytest.raises(EnrollmentError, match="đã có token agent đang hoạt động"):
        enroll_machine(raw_secret, agent_machine.hostname)


def test_enroll_rejects_invalid_secret(agent_machine):
    with pytest.raises(EnrollmentError, match="không hợp lệ"):
        enroll_machine("not-a-real-secret", agent_machine.hostname)


def test_enroll_hostname_case_insensitive(db):
    machine = Machine.objects.create(hostname="CaseSensitive-PC", enabled=True)
    raw_secret, _ = issue_enrollment_secret("", _future())
    _, enrolled = enroll_machine(raw_secret, "casesensitive-pc")
    assert enrolled.pk == machine.pk


def test_enroll_race_simulated_via_monkeypatch(db):
    """
    enroll_machine() tăng use_count bằng 1 câu UPDATE nguyên tử ở tầng SQL
    (`EnrollmentSecret.objects.filter(pk=...).update(use_count=F("use_count") + 1)`), không
    phải kiểu đọc-rồi-ghi phía Python (sẽ mất update nếu 2 request race nhau ghi đè lên nhau).
    Test này xác nhận trực tiếp tính chất "không mất update" của câu UPDATE đó — không dựng
    thread thật vì SQLite test không chịu được ghi đa luồng (xem test_phase2.py). Việc chặn
    đúng 2 request /enroll đồng thời không "cùng vượt qua" điều kiện max_uses/expires_at (đọc
    rồi mới quyết định) phụ thuộc vào select_for_update() khóa hàng EnrollmentSecret trong
    enroll_machine() — cơ chế lock đó chỉ có hiệu lực thật trên Postgres production, SQLite bỏ
    qua (no-op) nên không thể kiểm chứng bằng test tự động ở đây.
    """
    _raw_secret, secret = issue_enrollment_secret("", _future())

    # Mô phỏng 2 UPDATE race nhau bằng đúng biểu thức F() mà enroll_machine() dùng.
    EnrollmentSecret.objects.filter(pk=secret.pk).update(use_count=F("use_count") + 1)
    EnrollmentSecret.objects.filter(pk=secret.pk).update(use_count=F("use_count") + 1)

    secret.refresh_from_db()
    assert secret.use_count == 2  # không có update nào bị mất


# ---------------- views.py: AgentEnrollView (/api/agent/enroll/, không cần token) ----------------


def test_enroll_endpoint_success_returns_token_and_audit(agent_machine):
    raw_secret, _ = issue_enrollment_secret("", _future())
    client = APIClient()
    resp = client.post(
        "/api/agent/enroll/", {"secret": raw_secret, "hostname": agent_machine.hostname}, format="json",
    )
    assert resp.status_code == 201
    raw_token = resp.json()["token"]
    assert AgentToken.objects.get(machine=agent_machine).token_hash == hash_token(raw_token)
    assert AuditLog.objects.filter(action=AuditLog.Action.AGENT_ENROLL).exists()


def test_enroll_endpoint_missing_fields_returns_400(db):
    client = APIClient()
    resp = client.post("/api/agent/enroll/", {"hostname": "X"}, format="json")
    assert resp.status_code == 400


def test_enroll_endpoint_rejects_bad_secret_with_403(agent_machine):
    client = APIClient()
    resp = client.post(
        "/api/agent/enroll/", {"secret": "bogus", "hostname": agent_machine.hostname}, format="json",
    )
    assert resp.status_code == 403


def test_enroll_endpoint_works_without_authorization_header(agent_machine):
    """Endpoint /enroll là điểm untrusted DUY NHẤT của mặt phẳng agent (máy chưa có token) —
    KHÔNG được yêu cầu Authorization, khác mọi view agent khác (_AgentAPIView)."""
    raw_secret, _ = issue_enrollment_secret("", _future())
    client = APIClient()  # không set credentials/Authorization
    resp = client.post(
        "/api/agent/enroll/", {"secret": raw_secret, "hostname": agent_machine.hostname}, format="json",
    )
    assert resp.status_code == 201


# ---------------- Admin API: EnrollmentSecretViewSet (/api/enrollment-secrets/) ----------------


def test_create_enrollment_secret_admin_only(admin_client, operator_client, db):
    resp_operator = operator_client.post(
        "/api/enrollment-secrets/", {"ad_ou": "", "expires_in_hours": 48}, content_type="application/json",
    )
    assert resp_operator.status_code == 403

    resp_admin = admin_client.post(
        "/api/enrollment-secrets/", {"ad_ou": "", "expires_in_hours": 48}, content_type="application/json",
    )
    assert resp_admin.status_code == 201


def test_create_enrollment_secret_returns_raw_secret_once(admin_client, db):
    resp = admin_client.post(
        "/api/enrollment-secrets/",
        {"ad_ou": "OU=Warehouse,DC=corp", "expires_in_hours": 24, "max_uses": 100, "note": "rollout"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "secret" in data and len(data["secret"]) > 20
    secret = EnrollmentSecret.objects.get(pk=data["id"])
    assert secret.secret_hash == hash_token(data["secret"])
    assert secret.note == "rollout"
    assert AuditLog.objects.filter(action=AuditLog.Action.AGENT_ENROLLMENT_SECRET_CREATE).exists()


def test_create_enrollment_secret_requires_expiry(admin_client, db):
    resp = admin_client.post("/api/enrollment-secrets/", {"ad_ou": ""}, content_type="application/json")
    assert resp.status_code == 400


def test_list_never_exposes_hash(admin_client, db):
    issue_enrollment_secret("", _future())
    resp = admin_client.get("/api/enrollment-secrets/")
    assert resp.status_code == 200
    body = resp.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    assert len(items) == 1
    assert "secret_hash" not in items[0]
    assert "secret" not in items[0]
    assert items[0]["secret_prefix"]


def test_revoke_enrollment_secret_via_api(admin_client, db):
    raw_secret, secret = issue_enrollment_secret("", _future())
    resp = admin_client.post(f"/api/enrollment-secrets/{secret.pk}/revoke/")
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    secret.refresh_from_db()
    assert secret.revoked_at is not None
    assert AuditLog.objects.filter(action=AuditLog.Action.AGENT_ENROLLMENT_SECRET_REVOKE).exists()

    # Đã revoke -> secret không còn dùng được để enroll.
    with pytest.raises(EnrollmentError, match="thu hồi"):
        enroll_machine(raw_secret, "ANY-PC")


def test_enrollment_secret_update_and_delete_not_allowed(admin_client, db):
    _secret_raw, secret = issue_enrollment_secret("", _future())
    resp_put = admin_client.put(
        f"/api/enrollment-secrets/{secret.pk}/", {"note": "x"}, content_type="application/json",
    )
    assert resp_put.status_code == 405
    resp_delete = admin_client.delete(f"/api/enrollment-secrets/{secret.pk}/")
    assert resp_delete.status_code == 405
