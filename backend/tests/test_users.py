import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.audit.models import AuditLog
from apps.core.permissions import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, user_roles


@pytest.fixture
def roles(db):
    for name in (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER):
        Group.objects.get_or_create(name=name)


def _login(username, password):
    c = Client()
    c.post(
        "/api/auth/login/",
        {"username": username, "password": password},
        content_type="application/json",
    )
    return c


@pytest.fixture
def admin_client(roles):
    User.objects.create_superuser("root", "r@r.com", "Str0ngPass9")
    return _login("root", "Str0ngPass9")


@pytest.fixture
def viewer_client(roles):
    u = User.objects.create_user("viewer", password="Str0ngPass9")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    return _login("viewer", "Str0ngPass9")


# --- Quyền truy cập ---

def test_viewer_cannot_list_users(viewer_client):
    assert viewer_client.get("/api/users/").status_code == 403


def test_unauthenticated_blocked(db):
    assert Client().get("/api/users/").status_code in (401, 403)


def test_admin_can_list_users(admin_client):
    r = admin_client.get("/api/users/")
    assert r.status_code == 200


# --- Tạo / mật khẩu / vai trò ---

def test_admin_creates_user_with_role_password_hidden(admin_client):
    r = admin_client.post(
        "/api/users/",
        {"username": "nva", "email": "nva@x.vn", "role": "operator", "password": "Str0ngPass9"},
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    assert "password" not in r.json()
    u = User.objects.get(username="nva")
    assert user_roles(u) == {ROLE_OPERATOR}
    # mật khẩu đặt đúng → đăng nhập được
    assert _login("nva", "Str0ngPass9").get("/api/auth/me/").status_code == 200


def test_create_requires_password(admin_client):
    r = admin_client.post(
        "/api/users/",
        {"username": "nopw", "role": "viewer"},
        content_type="application/json",
    )
    assert r.status_code == 400


def test_duplicate_username_rejected(admin_client):
    admin_client.post(
        "/api/users/",
        {"username": "dup", "role": "viewer", "password": "Str0ngPass9"},
        content_type="application/json",
    )
    r = admin_client.post(
        "/api/users/",
        {"username": "DUP", "role": "viewer", "password": "Str0ngPass9"},
        content_type="application/json",
    )
    assert r.status_code == 400


def test_admin_changes_role_and_resets_password(admin_client):
    u = User.objects.create_user("bob", password="Str0ngPass9")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    r = admin_client.patch(
        f"/api/users/{u.id}/",
        {"role": "operator", "password": "NewPass123"},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    u.refresh_from_db()
    assert user_roles(u) == {ROLE_OPERATOR}
    assert _login("bob", "NewPass123").get("/api/auth/me/").status_code == 200


def test_deactivated_user_cannot_login(admin_client):
    u = User.objects.create_user("carol", password="Str0ngPass9")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    admin_client.patch(
        f"/api/users/{u.id}/", {"is_active": False}, content_type="application/json"
    )
    assert _login("carol", "Str0ngPass9").get("/api/auth/me/").status_code in (401, 403)


# --- Guard chống mất quản trị ---

def test_cannot_delete_self(admin_client):
    root = User.objects.get(username="root")
    r = admin_client.delete(f"/api/users/{root.id}/")
    assert r.status_code == 400
    assert User.objects.filter(pk=root.pk).exists()


def test_cannot_deactivate_last_admin(admin_client):
    # root là admin duy nhất → tự khoá mình phải bị chặn
    root = User.objects.get(username="root")
    r = admin_client.patch(
        f"/api/users/{root.id}/", {"is_active": False}, content_type="application/json"
    )
    assert r.status_code == 400
    root.refresh_from_db()
    assert root.is_active is True


def test_can_delete_admin_when_another_exists(admin_client):
    # tạo admin thứ 2 rồi xoá được (vì còn root)
    r = admin_client.post(
        "/api/users/",
        {"username": "admin2", "role": "admin", "password": "Str0ngPass9"},
        content_type="application/json",
    )
    uid = r.json()["id"]
    assert admin_client.delete(f"/api/users/{uid}/").status_code == 204


# --- Audit log (đổi role/xoá user trước đây không để lại dấu vết gì) ---

def test_role_change_is_audit_logged(admin_client):
    u = User.objects.create_user("dave", password="Str0ngPass9")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    admin_client.patch(
        f"/api/users/{u.id}/", {"role": "operator"}, content_type="application/json"
    )
    log = AuditLog.objects.filter(action=AuditLog.Action.USER_UPDATE, target_id=str(u.pk)).first()
    assert log is not None
    assert log.detail["role"] == "operator"


def test_user_delete_is_audit_logged(admin_client):
    u = User.objects.create_user("erin", password="Str0ngPass9")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    admin_client.delete(f"/api/users/{u.id}/")
    log = AuditLog.objects.filter(action=AuditLog.Action.USER_DELETE, target_id=str(u.pk)).first()
    assert log is not None
    assert log.detail["username"] == "erin"
