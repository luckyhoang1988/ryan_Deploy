"""
Trang Deployments và Packages trước đây gọi API không phân trang (chỉ lấy
listOf() của trang đầu) trong khi backend vẫn áp PAGE_SIZE toàn cục (25) —
cùng lớp lỗi đã phát hiện ở bảng job trong DeploymentDetail (xem
test_job_pagination_export.py): có nhiều hơn 25 bản ghi thì UI hiển thị thiếu
mà không báo. Test này khoá lại hành vi mới: 30 bản ghi/trang, lọc được
(status cho Deployment, folder cho Package), và export CSV không crash với
deployment không có package_version (action reboot/shutdown/inventory).
"""
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.core.permissions import ROLE_OPERATOR
from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentStatus
from apps.packages.models import InstallerType, Package, PackageFolder, PackageVersion


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


def _make_package_version():
    pkg = Package.objects.create(name="7-Zip")
    return PackageVersion.objects.create(
        package=pkg, version="24.0", installer_file="repository/x/24.0/setup.exe",
        installer_type=InstallerType.EXE,
    )


def _make_deployments(n, status=DeploymentStatus.COMPLETED, action="install", package_version=None):
    cred = DeployCredential.objects.create(name=f"cred-{status}-{action}", username="svc")
    for i in range(n):
        Deployment.objects.create(
            name=f"dep-{status}-{i}", credential=cred, action=action,
            package_version=package_version, status=status,
        )


def test_deployments_list_paginates_30_per_page(operator_client):
    pv = _make_package_version()
    _make_deployments(35, package_version=pv)

    r = operator_client.get("/api/deployments/")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 35
    assert len(body["results"]) == 30

    r_p2 = operator_client.get("/api/deployments/?page=2")
    assert len(r_p2.json()["results"]) == 5


def test_deployments_list_filters_by_status(operator_client):
    pv = _make_package_version()
    _make_deployments(3, status=DeploymentStatus.COMPLETED, package_version=pv)
    _make_deployments(2, status=DeploymentStatus.FAILED, package_version=pv)

    r = operator_client.get(f"/api/deployments/?status={DeploymentStatus.FAILED}")
    body = r.json()
    assert body["count"] == 2
    assert all(d["status"] == DeploymentStatus.FAILED for d in body["results"])


def test_deployments_export_handles_null_package_version(operator_client):
    # action=inventory KHÔNG gắn package_version (xem model) — export không được crash.
    _make_deployments(1, action="inventory", package_version=None, status=DeploymentStatus.COMPLETED)

    r = operator_client.get("/api/deployments/export/")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")
    csv_text = r.content.decode("utf-8-sig")
    lines = csv_text.splitlines()
    assert "Tên" in lines[0]
    assert "dep-completed-0" in csv_text


def test_deployments_export_respects_status_filter(operator_client):
    pv = _make_package_version()
    _make_deployments(1, status=DeploymentStatus.COMPLETED, package_version=pv)
    _make_deployments(1, status=DeploymentStatus.FAILED, package_version=pv)

    r = operator_client.get(f"/api/deployments/export/?status={DeploymentStatus.FAILED}")
    csv_text = r.content.decode("utf-8-sig")
    assert "dep-failed-0" in csv_text
    assert "dep-completed-0" not in csv_text


def _make_packages(n, folder=None, prefix="pkg"):
    for i in range(n):
        Package.objects.create(name=f"{prefix}-{i}", folder=folder)


def test_packages_list_paginates_30_per_page(operator_client):
    _make_packages(35)

    r = operator_client.get("/api/packages/")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 35
    assert len(body["results"]) == 30

    r_p2 = operator_client.get("/api/packages/?page=2")
    assert len(r_p2.json()["results"]) == 5


def test_packages_list_filters_by_folder(operator_client):
    folder = PackageFolder.objects.create(name="Custom Packages")
    _make_packages(2, folder=folder, prefix="in-folder")
    _make_packages(3, folder=None, prefix="root")

    r = operator_client.get(f"/api/packages/?folder={folder.id}")
    body = r.json()
    assert body["count"] == 2
    assert all(p["folder"] == folder.id for p in body["results"])


def test_packages_export_returns_csv(operator_client):
    pkg = Package.objects.create(name="Firefox", total_licenses=10, used_licenses=3)
    PackageVersion.objects.create(
        package=pkg, version="120", installer_file="repository/x/120/setup.exe",
        installer_type=InstallerType.EXE, approved=True,
    )
    Package.objects.create(name="Chrome")  # chưa có version → "Chưa có installer"

    r = operator_client.get("/api/packages/export/")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")
    csv_text = r.content.decode("utf-8-sig")
    lines = csv_text.splitlines()
    assert "Tên" in lines[0]
    assert "Firefox" in csv_text and "Sẵn sàng" in csv_text
    assert "Chrome" in csv_text and "Chưa có installer" in csv_text
