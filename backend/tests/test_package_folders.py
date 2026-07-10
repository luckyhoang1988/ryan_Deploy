"""Cây thư mục Package Library (PackageFolder, mirror PDQ Deploy) — CRUD + guard xóa."""
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.packages.models import Package, PackageFolder


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


def test_operator_cannot_create_folder(db, roles):
    op = _client("op1", group="operator")
    r = op.post("/api/package-folders/", {"name": "Custom Packages"}, content_type="application/json")
    assert r.status_code == 403


def test_admin_creates_and_lists_folder(db, roles):
    admin = _client("admin1", superuser=True)
    r = admin.post("/api/package-folders/", {"name": "Custom Packages"}, content_type="application/json")
    assert r.status_code == 201
    assert PackageFolder.objects.filter(name="Custom Packages").exists()


def test_delete_folder_with_package_is_blocked(db, roles):
    folder = PackageFolder.objects.create(name="Packages")
    Package.objects.create(name="7-Zip", folder=folder)
    admin = _client("admin2", superuser=True)
    r = admin.delete(f"/api/package-folders/{folder.id}/")
    assert r.status_code == 400
    assert PackageFolder.objects.filter(id=folder.id).exists()


def test_delete_folder_with_child_is_blocked(db, roles):
    parent = PackageFolder.objects.create(name="Packages")
    PackageFolder.objects.create(name="Sub", parent=parent)
    admin = _client("admin3", superuser=True)
    r = admin.delete(f"/api/package-folders/{parent.id}/")
    assert r.status_code == 400
    assert PackageFolder.objects.filter(id=parent.id).exists()


def test_delete_empty_folder_succeeds(db, roles):
    folder = PackageFolder.objects.create(name="Remove Updates")
    admin = _client("admin4", superuser=True)
    r = admin.delete(f"/api/package-folders/{folder.id}/")
    assert r.status_code == 204
    assert not PackageFolder.objects.filter(id=folder.id).exists()


def test_reparent_to_own_descendant_is_blocked(db, roles):
    root = PackageFolder.objects.create(name="Packages")
    child = PackageFolder.objects.create(name="Sub", parent=root)
    admin = _client("admin6", superuser=True)
    r = admin.patch(
        f"/api/package-folders/{root.id}/",
        {"parent": child.id},
        content_type="application/json",
    )
    assert r.status_code == 400
    root.refresh_from_db()
    assert root.parent_id is None


def test_package_serializer_exposes_folder(db, roles):
    folder = PackageFolder.objects.create(name="Packages")
    pkg = Package.objects.create(name="Git", folder=folder)
    admin = _client("admin5", superuser=True)
    r = admin.get(f"/api/packages/{pkg.id}/")
    assert r.status_code == 200
    assert r.json()["folder"] == folder.id
