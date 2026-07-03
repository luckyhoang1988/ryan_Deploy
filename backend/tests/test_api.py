import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.core.permissions import ROLE_OPERATOR, ROLE_VIEWER
from apps.credentials.models import DeployCredential


@pytest.fixture
def roles(db):
    for name in ("admin", "operator", "viewer"):
        Group.objects.get_or_create(name=name)


@pytest.fixture
def operator_client(db, roles):
    u = User.objects.create_user("operator", password="pass12345")
    u.groups.add(Group.objects.get(name=ROLE_OPERATOR))
    c = Client()
    c.post("/api/auth/login/", {"username": "operator", "password": "pass12345"}, content_type="application/json")
    return c


@pytest.fixture
def admin_client(db, roles):
    User.objects.create_superuser("admin", "a@a.com", "pass12345")
    c = Client()
    c.post("/api/auth/login/", {"username": "admin", "password": "pass12345"}, content_type="application/json")
    return c


@pytest.fixture
def viewer_client(db, roles):
    u = User.objects.create_user("viewer", password="pass12345")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    c = Client()
    c.post("/api/auth/login/", {"username": "viewer", "password": "pass12345"}, content_type="application/json")
    return c


def test_login_returns_roles(admin_client):
    r = admin_client.get("/api/auth/me/")
    assert r.status_code == 200
    assert "admin" in r.json()["roles"]


def test_login_wrong_password(db, roles):
    User.objects.create_user("bob", password="right")
    c = Client()
    r = c.post("/api/auth/login/", {"username": "bob", "password": "wrong"}, content_type="application/json")
    assert r.status_code == 401


def test_stats_endpoint(admin_client):
    r = admin_client.get("/api/stats/")
    assert r.status_code == 200
    assert "machines" in r.json()


def test_admin_creates_credential_password_hidden(admin_client):
    r = admin_client.post(
        "/api/credentials/",
        {"name": "svc", "domain": "CORP", "username": "svc_deploy", "password": "secret"},
        content_type="application/json",
    )
    assert r.status_code == 201
    # Password KHÔNG bao giờ lộ ra response
    assert "password" not in r.json()
    # DB chỉ chứa ciphertext, giải mã đúng
    cred = DeployCredential.objects.get(id=r.json()["id"])
    assert cred.password_encrypted not in ("", "secret")
    assert cred.get_password() == "secret"


def test_admin_update_credential_audited(admin_client):
    from apps.audit.models import AuditLog

    r = admin_client.post(
        "/api/credentials/",
        {"name": "svc", "username": "u", "password": "p"},
        content_type="application/json",
    )
    cid = r.json()["id"]
    r2 = admin_client.patch(
        f"/api/credentials/{cid}/", {"name": "svc-renamed"}, content_type="application/json"
    )
    assert r2.status_code == 200
    assert AuditLog.objects.filter(
        action=AuditLog.Action.CREDENTIAL_UPDATE, target_id=str(cid)
    ).exists()


def test_admin_delete_credential_audited(admin_client):
    from apps.audit.models import AuditLog

    r = admin_client.post(
        "/api/credentials/",
        {"name": "throwaway", "username": "u", "password": "p"},
        content_type="application/json",
    )
    cid = r.json()["id"]
    r2 = admin_client.delete(f"/api/credentials/{cid}/")
    assert r2.status_code == 204
    # Log ghi TRƯỚC khi xóa nên vẫn giữ được target_id/tên.
    assert AuditLog.objects.filter(
        action=AuditLog.Action.CREDENTIAL_DELETE, target_id=str(cid)
    ).exists()


def test_viewer_cannot_create_credential(viewer_client):
    r = viewer_client.post(
        "/api/credentials/",
        {"name": "x", "username": "y", "password": "z"},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_viewer_can_read_machines(viewer_client):
    r = viewer_client.get("/api/machines/")
    assert r.status_code == 200


def test_unauthenticated_blocked(db):
    r = Client().get("/api/machines/")
    assert r.status_code in (401, 403)


# --- RBAC Tier-0: chỉ admin được upload package / sync AD / sửa máy ---


def test_operator_cannot_create_package(operator_client):
    r = operator_client.post(
        "/api/packages/",
        {"name": "Malicious", "vendor": "x"},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_admin_can_create_package(admin_client):
    r = admin_client.post(
        "/api/packages/",
        {"name": "7-Zip", "vendor": "Igor Pavlov"},
        content_type="application/json",
    )
    assert r.status_code == 201


def test_operator_cannot_sync_ad(operator_client):
    r = operator_client.post("/api/machines/sync_ad/", {}, content_type="application/json")
    assert r.status_code == 403


def test_operator_cannot_create_machine(operator_client):
    r = operator_client.post(
        "/api/machines/",
        {"hostname": "PC-EVIL"},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_operator_cannot_create_machine_group(operator_client):
    # Nhóm máy là Tier-0 (quyết định target deploy) → chỉ admin được tạo/sửa.
    r = operator_client.post(
        "/api/machine-groups/",
        {"name": "Nhóm lạ"},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_viewer_can_read_machine_groups(viewer_client):
    r = viewer_client.get("/api/machine-groups/")
    assert r.status_code == 200


def test_admin_can_create_machine_group(admin_client):
    r = admin_client.post(
        "/api/machine-groups/",
        {"name": "Kế toán"},
        content_type="application/json",
    )
    assert r.status_code == 201


# --- Sửa/Xóa package + version (CRUD admin) ---


def _create_version(admin_client, pkg_name="7-Zip", version="1.0"):
    """Tạo package + upload 1 version qua API, trả (package_id, version_id)."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    pr = admin_client.post("/api/packages/", {"name": pkg_name}, content_type="application/json")
    pid = pr.json()["id"]
    installer = SimpleUploadedFile("setup.msi", b"MZ fake installer bytes", content_type="application/octet-stream")
    vr = admin_client.post(
        "/api/package-versions/",
        {"package": pid, "version": version, "installer_file": installer},
    )
    assert vr.status_code == 201, vr.content
    return pid, vr.json()["id"]


def test_admin_update_package_audited(admin_client):
    from apps.audit.models import AuditLog

    pr = admin_client.post("/api/packages/", {"name": "Firefox"}, content_type="application/json")
    pid = pr.json()["id"]
    r = admin_client.patch(
        f"/api/packages/{pid}/", {"vendor": "Mozilla", "total_licenses": 50}, content_type="application/json"
    )
    assert r.status_code == 200
    assert r.json()["vendor"] == "Mozilla"
    assert AuditLog.objects.filter(action=AuditLog.Action.PACKAGE_UPDATE, target_id=str(pid)).exists()


def test_admin_delete_version_removes_file_and_audits(admin_client):
    import os

    from apps.audit.models import AuditLog
    from apps.packages.models import PackageVersion

    _pid, vid = _create_version(admin_client)
    path = PackageVersion.objects.get(id=vid).installer_file.path
    assert os.path.exists(path)

    r = admin_client.delete(f"/api/package-versions/{vid}/")
    assert r.status_code == 204
    assert not PackageVersion.objects.filter(id=vid).exists()
    assert not os.path.exists(path)  # file installer đã bị dọn khỏi repository
    assert AuditLog.objects.filter(action=AuditLog.Action.PACKAGE_VERSION_DELETE, target_id=str(vid)).exists()


def test_admin_delete_package_cascades_and_audits(admin_client):
    import os

    from apps.audit.models import AuditLog
    from apps.packages.models import Package, PackageVersion

    pid, vid = _create_version(admin_client, pkg_name="Chrome")
    path = PackageVersion.objects.get(id=vid).installer_file.path

    r = admin_client.delete(f"/api/packages/{pid}/")
    assert r.status_code == 204
    assert not Package.objects.filter(id=pid).exists()
    assert not PackageVersion.objects.filter(id=vid).exists()
    assert not os.path.exists(path)
    assert AuditLog.objects.filter(action=AuditLog.Action.PACKAGE_DELETE, target_id=str(pid)).exists()


def test_delete_version_referenced_by_deployment_blocked(admin_client):
    from apps.credentials.models import DeployCredential
    from apps.deployments.models import Deployment
    from apps.packages.models import PackageVersion

    _pid, vid = _create_version(admin_client, pkg_name="Notepad++")
    version = PackageVersion.objects.get(id=vid)
    cred = DeployCredential.objects.create(name="c", username="u")
    Deployment.objects.create(name="dep", package_version=version, credential=cred)

    # FK PROTECT → phải bị chặn với lỗi thân thiện (400), không phải 500.
    r = admin_client.delete(f"/api/package-versions/{vid}/")
    assert r.status_code == 400
    assert PackageVersion.objects.filter(id=vid).exists()
