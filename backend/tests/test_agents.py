"""
Chế độ agent (outbound HTTPS, song song SMB — xem plan_agent.md):
- services: cấp/thu hồi token (giữ lịch sử, không vi phạm UniqueConstraint 1-active).
- auth: AgentTokenAuthentication chấp nhận/từ chối đúng theo trạng thái token/máy.
- views: poll (claim nguyên tử), download (chặn ngoài phạm vi job RUNNING), report, heartbeat.
- MachineViewSet: provision/revoke/bulk-provision token chỉ admin.
"""
import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.test import APIClient, APIRequestFactory

from apps.agents.auth import AgentTokenAuthentication
from apps.agents.models import AgentToken
from apps.agents.permissions import IsAuthenticatedAgent
from apps.agents.services import hash_token, issue_token, revoke_token
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
