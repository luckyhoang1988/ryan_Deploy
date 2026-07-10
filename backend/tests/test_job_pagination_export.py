"""
Bảng job trong DeploymentDetail trước đây chỉ hiện tối đa 25 job (mặc định
PAGE_SIZE toàn cục) dù tổng số job thực tế lớn hơn nhiều (vd 159), gây lệch
với số "x/y máy đã xong" tính độc lập từ Deployment.total_count. Test này
khoá lại hành vi mới: /api/jobs/ trả 30 job/trang, lọc được theo status, và
endpoint export CSV ẩn cột Lỗi với viewer giống JobSerializer.
"""
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.core.permissions import ROLE_OPERATOR, ROLE_VIEWER
from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment
from apps.jobs.models import Job, JobStatus
from apps.machines.models import Machine


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
def viewer_client(db, roles):
    u = User.objects.create_user("viewer", password="pass12345")
    u.groups.add(Group.objects.get(name=ROLE_VIEWER))
    c = Client()
    c.post("/api/auth/login/", {"username": "viewer", "password": "pass12345"}, content_type="application/json")
    return c


def _make_deployment_with_jobs(n_success=100, n_failed=59):
    cred = DeployCredential.objects.create(name="c", username="u")
    dep = Deployment.objects.create(name="all-7zip", credential=cred, action="inventory", status="completed_errors")
    for i in range(n_success):
        m = Machine.objects.create(hostname=f"PC-OK-{i}")
        Job.objects.create(deployment=dep, machine=m, status=JobStatus.SUCCESS)
    for i in range(n_failed):
        m = Machine.objects.create(hostname=f"PC-FAIL-{i}")
        Job.objects.create(
            deployment=dep, machine=m, status=JobStatus.FAILED,
            error_output="Không kết nối được SMB ...:445 (timed out)",
        )
    return dep


def test_jobs_list_paginates_30_per_page(operator_client):
    dep = _make_deployment_with_jobs(n_success=100, n_failed=59)  # tổng 159, giống thực tế

    r = operator_client.get(f"/api/jobs/?deployment={dep.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 159
    assert len(body["results"]) == 30

    r_last = operator_client.get(f"/api/jobs/?deployment={dep.id}&page=6")
    assert len(r_last.json()["results"]) == 9  # 159 = 5*30 + 9


def test_jobs_list_filters_by_status(operator_client):
    dep = _make_deployment_with_jobs(n_success=100, n_failed=59)

    r = operator_client.get(f"/api/jobs/?deployment={dep.id}&status=failed")
    body = r.json()
    assert body["count"] == 59
    assert all(j["status"] == JobStatus.FAILED for j in body["results"])


def test_jobs_export_hides_error_for_viewer_shows_for_operator(viewer_client, operator_client):
    dep = _make_deployment_with_jobs(n_success=1, n_failed=1)

    r_viewer = viewer_client.get(f"/api/jobs/export/?deployment={dep.id}")
    assert r_viewer.status_code == 200
    assert r_viewer["Content-Type"].startswith("text/csv")
    viewer_csv = r_viewer.content.decode("utf-8-sig")
    assert "Lỗi" not in viewer_csv.splitlines()[0]
    assert "timed out" not in viewer_csv

    r_op = operator_client.get(f"/api/jobs/export/?deployment={dep.id}&status=failed")
    op_csv = r_op.content.decode("utf-8-sig")
    assert "Lỗi" in op_csv.splitlines()[0]
    assert "timed out" in op_csv
    # export tôn trọng filter status=failed như list
    assert "PC-FAIL-0" in op_csv
    assert "PC-OK-0" not in op_csv
