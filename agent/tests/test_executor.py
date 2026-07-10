import hashlib
import subprocess
import time
from unittest.mock import Mock

from ryandeploy_agent import executor as executor_module
from ryandeploy_agent.client import AgentClient, ApiError
from ryandeploy_agent.executor import run_job

JOB_TIMEOUT = 30


def test_command_without_payload_success():
    client = Mock(spec=AgentClient)
    job = {"command": "cmd /c exit 0", "success_exit_codes": [0]}
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code == 0
    assert outcome.error == ""
    assert outcome.needs_reboot is False
    assert outcome.verify_passed is None
    client.download_to.assert_not_called()


def test_command_failure_exit_code():
    client = Mock(spec=AgentClient)
    job = {"command": "cmd /c exit 5", "success_exit_codes": [0]}
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code == 5


def test_needs_reboot_on_3010():
    client = Mock(spec=AgentClient)
    job = {"command": "cmd /c exit 3010", "success_exit_codes": [0, 3010]}
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code == 3010
    assert outcome.needs_reboot is True


def test_payload_downloaded_and_substituted_into_command():
    content = b"hello ryandeploy agent"
    sha = hashlib.sha256(content).hexdigest()

    def fake_download(url, dest_path):
        with open(dest_path, "wb") as fh:
            fh.write(content)
        return None

    client = Mock(spec=AgentClient)
    client.download_to.side_effect = fake_download

    job = {
        "command": 'cmd /c type {file}',
        "success_exit_codes": [0],
        "payload": {"download_url": "https://x/download", "filename": "payload.txt", "sha256": sha},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code == 0
    assert outcome.stdout.strip() == content.decode()
    client.download_to.assert_called_once()


def test_payload_sha256_mismatch_refuses_to_run():
    def fake_download(url, dest_path):
        with open(dest_path, "wb") as fh:
            fh.write(b"tampered content")
        return None

    client = Mock(spec=AgentClient)
    client.download_to.side_effect = fake_download

    job = {
        "command": "cmd /c type {file}",
        "success_exit_codes": [0],
        "payload": {"download_url": "https://x/download", "filename": "payload.txt", "sha256": "0" * 64},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code is None
    assert "KHÔNG khớp" in outcome.error


def test_payload_download_error_short_circuits():
    client = Mock(spec=AgentClient)
    client.download_to.side_effect = ApiError("server unreachable")

    job = {
        "command": "cmd /c type {file}",
        "success_exit_codes": [0],
        "payload": {"download_url": "https://x/download", "filename": "payload.txt", "sha256": ""},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code is None
    assert "Tải payload thất bại" in outcome.error


_VERIFY_SCRIPT = (
    "param([string]$Name, [int]$Present = 1)\n"
    "if ($Present -eq 1) { exit 0 } else { exit 1 }\n"
)


def test_verify_runs_after_successful_command_and_passes():
    def fake_download(url, dest_path):
        with open(dest_path, "w", encoding="utf-8") as fh:
            fh.write(_VERIFY_SCRIPT)
        return None

    client = Mock(spec=AgentClient)
    client.download_to.side_effect = fake_download

    job = {
        "command": "cmd /c exit 0",
        "success_exit_codes": [0],
        "verify": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip", "present": True},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code == 0
    assert outcome.verify_passed is True


def test_verify_not_run_when_command_failed():
    client = Mock(spec=AgentClient)
    job = {
        "command": "cmd /c exit 1",
        "success_exit_codes": [0],
        "verify": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip", "present": True},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.verify_passed is None
    client.download_to.assert_not_called()


def test_command_timeout_returns_promptly_not_hung():
    # ping -n 31 127.0.0.1 chạy khoảng 30s nếu không bị dọn — job_timeout=1 phải khiến
    # _run_command trả về NGAY (kill cả cây tiến trình), không đợi tới hết 30s.
    start = time.monotonic()
    exit_code, _stdout, error = executor_module._run_command(
        "ping -n 31 127.0.0.1 >nul", ".", 1,
    )
    elapsed = time.monotonic() - start
    assert exit_code is None
    assert "Timeout" in error
    assert elapsed < 15, f"đáng lẽ trả về trong vài giây (đã dọn cây tiến trình), thực tế {elapsed}s"


def test_command_timeout_invokes_kill_process_tree(monkeypatch):
    killed_pids = []
    monkeypatch.setattr(executor_module, "_kill_process_tree", killed_pids.append)
    try:
        exit_code, _stdout, error = executor_module._run_command(
            "ping -n 31 127.0.0.1 >nul", ".", 1,
        )
        assert exit_code is None
        assert "Timeout" in error
        assert len(killed_pids) == 1
    finally:
        # _kill_process_tree bị no-op hoá ở trên — tự dọn tiến trình ping thật để không sót lại.
        if killed_pids:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(killed_pids[0])], capture_output=True,
            )


def test_verify_download_error_returns_none_not_false():
    client = Mock(spec=AgentClient)
    client.download_to.side_effect = ApiError("timeout")

    job = {
        "command": "cmd /c exit 0",
        "success_exit_codes": [0],
        "verify": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip", "present": True},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.exit_code == 0
    assert outcome.verify_passed is None


_PRECHECK_FOUND_SCRIPT = (
    "param([string]$Name, [int]$Present = 1)\n"
    "exit 0\n"
)
_PRECHECK_NOT_FOUND_SCRIPT = (
    "param([string]$Name, [int]$Present = 1)\n"
    "exit 1\n"
)


def test_precheck_skips_install_when_already_present():
    def fake_download(url, dest_path):
        with open(dest_path, "w", encoding="utf-8") as fh:
            fh.write(_PRECHECK_FOUND_SCRIPT)
        return None

    client = Mock(spec=AgentClient)
    client.download_to.side_effect = fake_download

    job = {
        # Nếu lỡ chạy (không skip) sẽ lộ ra qua exit_code=99 thay vì 0.
        "command": "cmd /c exit 99",
        "success_exit_codes": [0],
        "precheck": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip"},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.skipped is True
    assert outcome.exit_code == 0
    client.download_to.assert_called_once()  # chỉ tải script tiền kiểm, không tải payload/chạy command


def test_precheck_proceeds_with_install_when_not_present():
    def fake_download(url, dest_path):
        with open(dest_path, "w", encoding="utf-8") as fh:
            fh.write(_PRECHECK_NOT_FOUND_SCRIPT)
        return None

    client = Mock(spec=AgentClient)
    client.download_to.side_effect = fake_download

    job = {
        "command": "cmd /c exit 0",
        "success_exit_codes": [0],
        "precheck": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip"},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.skipped is False
    assert outcome.exit_code == 0


def test_precheck_download_error_proceeds_with_install():
    client = Mock(spec=AgentClient)
    client.download_to.side_effect = ApiError("timeout")

    job = {
        "command": "cmd /c exit 0",
        "success_exit_codes": [0],
        "precheck": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip"},
    }
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.skipped is False
    assert outcome.exit_code == 0


def test_no_precheck_key_runs_command_normally():
    client = Mock(spec=AgentClient)
    job = {"command": "cmd /c exit 0", "success_exit_codes": [0]}
    outcome = run_job(client, job, JOB_TIMEOUT)
    assert outcome.skipped is False
