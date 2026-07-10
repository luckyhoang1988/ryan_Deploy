"""
Luồng start()/poll_once() không chặn worker: deploy_to_machine chỉ chạy nhanh (precheck/copy/
execute) rồi giao (handoff) cho collect_job_result tự poll lặp lại qua self.retry() — thay cho
executor.run() cũ vốn sleep-block cả worker suốt thời gian cài (tới 30 phút). Xem
push_executor.py (start/poll_once/cleanup_now) và jobs/tasks.py (_start_and_dispatch/
collect_job_result).

Cảnh báo khi viết test loại này (đã xác nhận qua source Celery Task.apply/Task.retry): dưới
CELERY_TASK_ALWAYS_EAGER (settings.test), self.retry() đệ quy gọi lại apply() NGAY LẬP TỨC,
không sleep thật. Fake poll_once() phải trả None một số lần HỮU HẠN rồi trả ExecResult — nếu
để vòng lặp dựa vào deadline thật (+1800s mặc định), test sẽ treo tới 30 phút.
"""
import pytest

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentAction
from apps.executor.push_executor import ExecResult, ExecutorError
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import deploy_to_machine
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


def _job(credential, retry_limit=1):
    pkg = Package.objects.create(name="Firefox")
    pv = PackageVersion.objects.create(
        package=pkg, version="1", installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE, install_command='"{file}" /S',
    )
    dep = Deployment.objects.create(
        name="D", action=DeploymentAction.INSTALL, package_version=pv, credential=credential,
        retry_limit=retry_limit,
    )
    m = Machine.objects.create(hostname="PC-1")
    dep.target_machines.add(m)
    return Job.objects.create(deployment=dep, machine=m, status=JobStatus.QUEUED)


class _FakeExecutor:
    """start() = khởi chạy install; poll_once() trả lần lượt các phần tử của poll_results
    (None = chưa xong); cleanup_now() ghi lại lời gọi để test cancel-giữa-collect."""

    start_error = None
    poll_results = []
    poll_call_count = 0
    cleanup_now_calls = []
    log = ["[precheck] ok", "[copy] ok", "[execute] ok"]

    def __init__(self, **kw):
        pass

    def start(self, command, **kw):
        if _FakeExecutor.start_error:
            raise _FakeExecutor.start_error
        return "faketoken"

    def poll_once(self, job_token, **kw):
        idx = _FakeExecutor.poll_call_count
        _FakeExecutor.poll_call_count += 1
        return _FakeExecutor.poll_results[idx]

    def cleanup_now(self, job_token):
        _FakeExecutor.cleanup_now_calls.append(job_token)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    _FakeExecutor.start_error = None
    _FakeExecutor.poll_results = []
    _FakeExecutor.poll_call_count = 0
    _FakeExecutor.cleanup_now_calls = []
    monkeypatch.setattr("apps.jobs.tasks.PushExecutor", _FakeExecutor)
    monkeypatch.setattr("apps.deployments.semaphore.acquire_slot", lambda *a, **k: True)

    release_calls = []
    monkeypatch.setattr(
        "apps.deployments.semaphore.release_slot", lambda dep_id: release_calls.append(dep_id)
    )
    return release_calls


def _res(success, exit_code, stdout="", log=None):
    return ExecResult(
        success=success, exit_code=exit_code, stdout=stdout,
        step_reached=("done" if success else "collect"), log=log or ["[collect] ok"],
    )


def test_poll_none_then_success_marks_job_success_and_releases_slot_once(credential, _patch):
    job = _job(credential)
    _FakeExecutor.poll_results = [None, _res(True, 0, log=["[collect] xong"])]

    result = deploy_to_machine.apply(args=[job.id]).get()

    assert result["status"] == "collecting"
    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS
    assert job.celery_task_id  # đã set trước khi dispatch, không rỗng
    assert "[precheck] ok" in job.output  # log start() không bị mất
    assert "[collect] xong" in job.output  # log collect được APPEND, không ghi đè
    assert _patch == [job.deployment_id]  # release_slot gọi đúng 1 lần


def test_poll_bad_exit_code_fails_without_retry(credential, _patch):
    job = _job(credential)
    _FakeExecutor.poll_results = [_res(False, 1, stdout="lỗi cài đặt")]

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert job.current_step == "collect"
    assert _patch == [job.deployment_id]


def test_start_precheck_failure_fails_after_retry_limit_exhausted(credential, _patch):
    # retry_limit=0: job.attempts sau claim = 1, 1 <= 0 là False -> fail ngay lần đầu, không
    # handoff sang collect_job_result (không có slot nào bị giữ).
    job = _job(credential, retry_limit=0)
    _FakeExecutor.start_error = ExecutorError("SMB timeout", retryable=True, step="precheck")

    result = deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert result["status"] == "failed"
    assert _patch == [job.deployment_id]


def test_cancel_during_collect_cleans_up_target_and_releases_slot_once(credential, _patch):
    job = _job(credential)
    orig_start = _FakeExecutor.start

    # Mô phỏng cancel_deployment() đặt CANCELLED đúng lúc collect_job_result sắp poll —
    # cửa sổ race giữa start() vừa xong và lần poll đầu tiên.
    def start_then_cancel(self, command, **kw):
        Job.objects.filter(pk=job.pk).update(status=JobStatus.CANCELLED)
        return "faketoken"

    _FakeExecutor.start = start_then_cancel
    try:
        deploy_to_machine.apply(args=[job.id]).get()
    finally:
        _FakeExecutor.start = orig_start  # khôi phục method gốc trên class (không del)

    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED
    assert _FakeExecutor.cleanup_now_calls == [f"job{job.pk}"]
    assert _patch == [job.deployment_id]


def test_timeout_marks_job_failed_and_cleans_up_target(credential, _patch, settings):
    # JOB_TIMEOUT cực nhỏ để deadline bị vượt ngay ở lần poll đầu tiên (None) — tránh test
    # phải chờ deadline thật (mặc định 1800s) như đã cảnh báo ở đầu file.
    # Timeout = không đọc được exit.code → phải cleanup_now (giống cancel giữa collect).
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "JOB_TIMEOUT": 0}
    job = _job(credential)
    _FakeExecutor.poll_results = [None]

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert "timeout" in job.error_output.lower()
    assert _FakeExecutor.cleanup_now_calls == [f"job{job.pk}"]
    assert _patch == [job.deployment_id]
