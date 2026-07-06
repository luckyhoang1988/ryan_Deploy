"""
Hậu kiểm cài đặt (chống false-success): sau khi installer báo thành công, chạy PowerShell
kiểm registry. Nếu không thấy phần mềm → job FAILED thay vì SUCCESS.
"""
import pytest

from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment, DeploymentAction
from apps.executor.push_executor import ExecResult
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import deploy_to_machine
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


def _pv(verify_name=""):
    pkg = Package.objects.create(name="Firefox")
    return PackageVersion.objects.create(
        package=pkg, version="1", installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE, install_command='"{file}" /S', verify_name=verify_name,
    )


def _job(credential, pv):
    dep = Deployment.objects.create(
        name="D", action=DeploymentAction.INSTALL, package_version=pv, credential=credential
    )
    m = Machine.objects.create(hostname="PC-1")
    dep.target_machines.add(m)
    return Job.objects.create(deployment=dep, machine=m, status=JobStatus.QUEUED)


class _FakeExecutor:
    """
    start() = khởi chạy install (không trả kết quả); poll_once() lần đầu trả về
    install_result (giả lập cài xong ngay ở lần poll đầu tiên); run() dùng cho cả 2 bước
    kiểm registry qua job_token (đặt bởi apps.jobs.tasks): "...c" = precheck "đã tồn tại"
    (theo precheck_result), "...v" = hậu kiểm sau install (theo verify_result).
    """

    install_result = None
    verify_result = None
    # Mặc định: không kết luận được (exit_code None) -> _start_and_dispatch cứ tiến hành cài
    # bình thường, giữ đúng hành vi trước khi có precheck (test không cần khai báo lại).
    precheck_result = None
    commands = []
    log = []

    def __init__(self, **kw):
        pass

    def start(self, command, **kw):
        _FakeExecutor.commands.append(command)
        return "faketoken"

    def poll_once(self, job_token, **kw):
        return _FakeExecutor.install_result

    def run(self, command, *, job_token=None, **kw):
        _FakeExecutor.commands.append(command)
        if job_token and job_token.endswith("c"):
            return _FakeExecutor.precheck_result
        return _FakeExecutor.verify_result


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    # Không SMB thật + không Redis: mock executor và semaphore. eager mode chạy
    # collect_job_result.apply_async(...) ĐỒNG BỘ ngay trong deploy_to_machine.apply() (xem
    # LESSONS.md/plan) nên 1 lần .apply().get() vẫn chạy trọn chuỗi start→poll→verify.
    _FakeExecutor.commands = []
    _FakeExecutor.precheck_result = ExecResult(success=False, exit_code=None, error="")
    monkeypatch.setattr("apps.jobs.tasks.PushExecutor", _FakeExecutor)
    monkeypatch.setattr("apps.deployments.semaphore.acquire_slot", lambda *a, **k: True)
    monkeypatch.setattr("apps.deployments.semaphore.release_slot", lambda *a, **k: None)


def _res(success, exit_code, stdout=""):
    return ExecResult(success=success, exit_code=exit_code, stdout=stdout, step_reached="done")


def test_verify_fail_marks_job_failed(credential):
    # Install "thành công" (exit 0) nhưng verify không thấy phần mềm → FAILED.
    job = _job(credential, _pv(verify_name="Firefox"))
    _FakeExecutor.install_result = _res(True, 0)
    _FakeExecutor.verify_result = _res(False, 1, stdout="NOT FOUND: *Firefox*")

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert job.current_step == "verify"
    assert "HẬU KIỂM THẤT BẠI" in job.error_output
    assert len(_FakeExecutor.commands) == 3  # precheck "đã tồn tại" + install + verify


def test_verify_pass_marks_job_success(credential):
    job = _job(credential, _pv(verify_name="Firefox"))
    _FakeExecutor.install_result = _res(True, 0)
    _FakeExecutor.verify_result = _res(True, 0, stdout="FOUND: Mozilla Firefox 128")

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS
    assert len(_FakeExecutor.commands) == 3  # precheck "đã tồn tại" + install + verify


def test_no_verify_name_skips_check(credential):
    # Không đặt verify_name → không chạy bước verify (chỉ 1 lần run).
    job = _job(credential, _pv(verify_name=""))
    _FakeExecutor.install_result = _res(True, 0)
    _FakeExecutor.verify_result = _res(False, 1)  # sẽ không được dùng tới

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS
    assert len(_FakeExecutor.commands) == 1


def test_verify_inconclusive_keeps_success(credential):
    # Verify không chạy tới nơi (exit_code None = lỗi SMB/precheck) → GIỮ thành công.
    job = _job(credential, _pv(verify_name="Firefox"))
    _FakeExecutor.install_result = _res(True, 0)
    _FakeExecutor.verify_result = ExecResult(success=False, exit_code=None, error="SMB lỗi", step_reached="precheck")

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS


def test_precheck_already_installed_skips_job(credential):
    # Máy đích ĐÃ có phần mềm (precheck FOUND) → job SKIPPED, không chạy install/verify.
    job = _job(credential, _pv(verify_name="Firefox"))
    _FakeExecutor.precheck_result = _res(True, 0, stdout="FOUND: Mozilla Firefox 128")

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.SKIPPED
    assert "đã tồn tại" in job.output
    assert len(_FakeExecutor.commands) == 1  # chỉ chạy precheck, không install/verify


def test_precheck_not_installed_proceeds_with_install(credential):
    # Máy đích CHƯA có phần mềm (precheck NOT FOUND) → tiến hành cài như bình thường.
    job = _job(credential, _pv(verify_name="Firefox"))
    _FakeExecutor.precheck_result = _res(False, 1, stdout="NOT FOUND: *Firefox*")
    _FakeExecutor.install_result = _res(True, 0)
    _FakeExecutor.verify_result = _res(True, 0, stdout="FOUND: Mozilla Firefox 128")

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS
    assert len(_FakeExecutor.commands) == 3  # precheck + install + verify


def test_precheck_skipped_for_uninstall_action(credential):
    # Precheck "đã tồn tại" chỉ áp dụng cho action install — uninstall không bị ảnh hưởng
    # dù package version có verify_name.
    pv = _pv(verify_name="Firefox")
    dep = Deployment.objects.create(
        name="U", action=DeploymentAction.UNINSTALL, package_version=pv, credential=credential
    )
    m = Machine.objects.create(hostname="PC-2")
    dep.target_machines.add(m)
    job = Job.objects.create(deployment=dep, machine=m, status=JobStatus.QUEUED)

    _FakeExecutor.precheck_result = _res(True, 0, stdout="FOUND: Mozilla Firefox 128")
    _FakeExecutor.install_result = _res(True, 0)
    # Hậu kiểm uninstall (Present=0) ĐẠT: script trả success khi phần mềm đã mất.
    _FakeExecutor.verify_result = _res(True, 0, stdout="NOT FOUND: *Firefox*")

    deploy_to_machine.apply(args=[job.id]).get()

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS
    assert len(_FakeExecutor.commands) == 2  # uninstall + hậu kiểm — KHÔNG có precheck
