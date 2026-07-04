"""
Catalog + Update Tracking (lấy cảm hứng PDQ Deploy):
- updates.is_outdated / compute_updates / outdated_machine_ids
- downloader.fetch (mock urllib): tạo version, dedup theo SHA-256, lỗi scheme.
"""
import io

import pytest

from apps.machines.models import InstalledSoftware, Machine
from apps.packages import downloader, updates
from apps.packages.models import (
    AutoDownloadPolicy,
    Package,
    PackageDownload,
    PackageVersion,
    VersionSource,
)


# ==================== is_outdated ====================


def test_is_outdated_semantic():
    assert updates.is_outdated("118.0", "120.0") is True
    assert updates.is_outdated("120.0", "120.0") is False
    assert updates.is_outdated("121.0", "120.0") is False
    # so ngữ nghĩa: 118 < 1200 (không phải lexicographic)
    assert updates.is_outdated("118", "1200") is True


def test_is_outdated_unparseable_falls_back_to_string():
    assert updates.is_outdated("2021-a", "2021-b") is True  # khác chuỗi → coi lỗi thời
    assert updates.is_outdated("weird", "weird") is False  # bằng nhau → không lỗi thời


def test_is_outdated_empty():
    assert updates.is_outdated("", "120") is False
    assert updates.is_outdated("120", "") is False


# ==================== compute_updates ====================


def _pkg_with_latest(name, version, inventory_name=""):
    pkg = Package.objects.create(name=name, inventory_name=inventory_name)
    PackageVersion.objects.create(
        package=pkg, version=version, installer_type="msi", approved=True
    )
    return pkg


def test_compute_updates_detects_outdated(db):
    pkg = _pkg_with_latest("Google Chrome", "120.0", inventory_name="Google Chrome")

    old = Machine.objects.create(hostname="OLD")
    up = Machine.objects.create(hostname="UPTODATE")
    helper = Machine.objects.create(hostname="HELPER")

    InstalledSoftware.objects.create(machine=old, name="Google Chrome", version="118.0")
    InstalledSoftware.objects.create(machine=up, name="Google Chrome", version="120.0")
    # Máy HELPER có cả bản gốc (lỗi thời) và "Helper" → đại diện là tên ngắn nhất.
    InstalledSoftware.objects.create(machine=helper, name="Google Chrome", version="118.0")
    InstalledSoftware.objects.create(machine=helper, name="Google Chrome Helper", version="118.0")

    items = updates.compute_updates()
    assert len(items) == 1
    item = items[0]
    assert item["package_id"] == pkg.id
    assert item["latest_version"] == "120.0"
    hostnames = {o["hostname"] for o in item["outdated"]}
    assert hostnames == {"OLD", "HELPER"}  # UPTODATE bị loại
    assert item["count"] == 2


def test_compute_updates_skips_when_no_approved_version(db):
    pkg = Package.objects.create(name="Foo", inventory_name="Foo")
    PackageVersion.objects.create(package=pkg, version="2.0", installer_type="msi", approved=False)
    m = Machine.objects.create(hostname="M")
    InstalledSoftware.objects.create(machine=m, name="Foo", version="1.0")
    # Không có version đã duyệt → không tính là có cập nhật.
    assert updates.compute_updates() == []


def test_outdated_machine_ids(db):
    pkg = _pkg_with_latest("7-Zip", "23.01", inventory_name="7-Zip")
    old = Machine.objects.create(hostname="Z-OLD")
    InstalledSoftware.objects.create(machine=old, name="7-Zip", version="22.00")
    Machine.objects.create(hostname="Z-NONE")  # không có 7-Zip → không lỗi thời
    assert updates.outdated_machine_ids(pkg) == [old.id]


# ==================== downloader.fetch (mock urllib) ====================


class _FakeResp:
    """Giả HTTP response cho urlopen: hỗ trợ context manager + read theo chunk + headers."""

    def __init__(self, data: bytes, headers=None):
        self._buf = io.BytesIO(data)
        self.headers = headers or {}

    def read(self, n):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, data: bytes, headers=None):
    monkeypatch.setattr(
        downloader, "urlopen", lambda req, timeout=None: _FakeResp(data, headers)
    )


def test_fetch_creates_version(db, settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    _patch_urlopen(monkeypatch, b"MZ-installer-bytes")
    pkg = Package.objects.create(name="App", auto_download=AutoDownloadPolicy.MANUAL)

    dl = downloader.fetch(pkg, "https://example.com/app.msi", "1.0")

    assert dl.status == PackageDownload.Status.SUCCESS
    pv = dl.package_version
    assert pv is not None
    assert pv.version == "1.0"
    assert pv.installer_type == "msi"
    assert pv.source == VersionSource.URL
    assert pv.approved is False  # policy MANUAL → chờ duyệt
    assert pv.sha256 and pv.file_size == len(b"MZ-installer-bytes")


def test_fetch_immediate_policy_auto_approves(db, settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    _patch_urlopen(monkeypatch, b"payload")
    pkg = Package.objects.create(name="App2", auto_download=AutoDownloadPolicy.IMMEDIATE)
    dl = downloader.fetch(pkg, "https://example.com/app.exe", "2.0")
    assert dl.package_version.approved is True
    assert dl.package_version.approved_at is not None


def test_fetch_dedup_same_content(db, settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    _patch_urlopen(monkeypatch, b"same-bytes")
    pkg = Package.objects.create(name="App3")

    dl1 = downloader.fetch(pkg, "https://example.com/a.msi", "1.0")
    assert dl1.status == PackageDownload.Status.SUCCESS
    # Tải lại nội dung y hệt với nhãn khác → dedup theo SHA, không tạo version mới.
    dl2 = downloader.fetch(pkg, "https://example.com/a.msi", "1.1")
    assert dl2.status == PackageDownload.Status.UNCHANGED
    assert dl2.package_version_id == dl1.package_version_id
    assert pkg.versions.count() == 1


def test_fetch_rejects_non_http_scheme(db):
    pkg = Package.objects.create(name="App4")
    with pytest.raises(downloader.DownloadError):
        downloader.fetch(pkg, "file:///etc/passwd", "1.0")


def test_fetch_size_cap(db, settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "MAX_INSTALLER_MB": 0}  # trần 0 → mọi file vượt
    _patch_urlopen(monkeypatch, b"anything")
    pkg = Package.objects.create(name="App5")
    dl = downloader.fetch(pkg, "https://example.com/big.exe", "1.0")
    assert dl.status == PackageDownload.Status.FAILED
    assert "trần" in dl.error.lower() or "MB" in dl.error


# ==================== API endpoints (routing + RBAC) ====================
#
# Celery eager (settings.test) → phải mock downloader.fetch & launch_deployment để endpoint
# KHÔNG tải mạng / đẩy SMB thật khi task chạy đồng bộ.
import types  # noqa: E402

from django.contrib.auth.models import Group, User  # noqa: E402
from django.test import Client  # noqa: E402

from apps.credentials.models import DeployCredential  # noqa: E402


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


def test_updates_endpoint_lists(db, roles):
    pkg = _pkg_with_latest("Chrome", "120.0", inventory_name="Chrome")
    m = Machine.objects.create(hostname="U1")
    InstalledSoftware.objects.create(machine=m, name="Chrome", version="118.0")
    c = _client("viewer1", group="viewer")
    r = c.get("/api/updates/")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["results"][0]["package_id"] == pkg.id


def test_fetch_endpoint_admin_only(db, roles, monkeypatch):
    called = {}
    monkeypatch.setattr(
        downloader,
        "fetch",
        lambda pkg, url, version, requested_by=None: called.update(url=url)
        or types.SimpleNamespace(id=1, status="unchanged", package_version_id=None),
    )
    pkg = Package.objects.create(name="FetchMe")

    op = _client("op1", group="operator")
    r = op.post(f"/api/packages/{pkg.id}/fetch/", {"url": "https://x/y.msi", "version": "1"},
                content_type="application/json")
    assert r.status_code == 403  # IsAdmin: operator không được

    admin = _client("admin1", superuser=True)
    r = admin.post(f"/api/packages/{pkg.id}/fetch/", {"url": "https://x/y.msi", "version": "1"},
                   content_type="application/json")
    assert r.status_code == 202
    assert called.get("url") == "https://x/y.msi"  # task eager đã gọi downloader (đã mock)


def test_approve_endpoint(db, roles):
    pkg = Package.objects.create(name="Appr")
    pv = PackageVersion.objects.create(
        package=pkg, version="1", installer_type="msi", approved=False
    )
    admin = _client("admin2", superuser=True)
    r = admin.post(f"/api/package-versions/{pv.id}/approve/", {}, content_type="application/json")
    assert r.status_code == 200
    pv.refresh_from_db()
    assert pv.approved is True and pv.approved_at is not None


def test_update_deploy_endpoint(db, roles, monkeypatch):
    from apps.deployments import orchestrator
    from apps.deployments.models import Deployment

    monkeypatch.setattr(orchestrator, "launch_deployment", lambda dep: 1)

    pkg = _pkg_with_latest("DeployMe", "120.0", inventory_name="DeployMe")
    m = Machine.objects.create(hostname="D1")
    InstalledSoftware.objects.create(machine=m, name="DeployMe", version="118.0")
    cred = DeployCredential.objects.create(name="svc", username="svc_deploy")

    # viewer bị chặn (IsOperatorOrAbove)
    viewer = _client("v2", group="viewer")
    r = viewer.post(f"/api/updates/{pkg.id}/deploy/", {"credential": cred.id},
                    content_type="application/json")
    assert r.status_code == 403

    op = _client("op2", group="operator")
    r = op.post(f"/api/updates/{pkg.id}/deploy/", {"credential": cred.id},
                content_type="application/json")
    assert r.status_code == 202
    dep = Deployment.objects.get(id=r.json()["deployment_id"])
    assert dep.package_version_id == pkg.latest_version.id
    assert list(dep.target_machines.values_list("id", flat=True)) == [m.id]
