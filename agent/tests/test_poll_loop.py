import dataclasses
import threading
from unittest.mock import Mock

from ryandeploy_agent import poll_loop as poll_loop_module
from ryandeploy_agent.client import ApiError
from ryandeploy_agent.config import AgentConfig, load_config
from ryandeploy_agent.poll_loop import PollLoop


def _config(**overrides):
    base = dict(server_url="https://x", token="t", poll_interval=0, heartbeat_interval=0, job_timeout=30)
    base.update(overrides)
    return AgentConfig(**base)


def test_heartbeat_called_first_iteration():
    stop_event = threading.Event()
    client = Mock()

    def fake_poll():
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()
    client.heartbeat.assert_called_once()


def test_job_is_executed_and_reported():
    stop_event = threading.Event()
    client = Mock()
    job = {"job_id": 7, "command": "cmd /c exit 0", "success_exit_codes": [0]}

    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return job
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()

    client.report_job.assert_called_once()
    args, kwargs = client.report_job.call_args
    assert args[0] == 7
    assert kwargs["exit_code"] == 0
    assert kwargs["verify_passed"] is None
    assert kwargs["skipped"] is False


def test_job_skipped_by_precheck_is_reported_with_skipped_true():
    stop_event = threading.Event()
    client = Mock()
    job = {
        # Nếu lỡ chạy (không skip) sẽ lộ ra qua exit_code=99 thay vì 0 do precheck.
        "job_id": 9, "command": "cmd /c exit 99", "success_exit_codes": [0],
        "precheck": {"script_url": "https://x/scripts/verify_installed.ps1", "name": "7-Zip"},
    }

    def fake_download(url, dest_path):
        with open(dest_path, "w", encoding="utf-8") as fh:
            fh.write("param([string]$Name, [int]$Present = 1)\nexit 0\n")
        return None

    client.download_to.side_effect = fake_download
    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return job
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()

    client.report_job.assert_called_once()
    args, kwargs = client.report_job.call_args
    assert args[0] == 9
    assert kwargs["skipped"] is True
    assert kwargs["exit_code"] == 0


def test_backoff_on_poll_error_then_recovers():
    stop_event = threading.Event()
    client = Mock()
    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ApiError("network down")
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()
    assert calls["n"] == 3


def test_report_error_does_not_crash_loop():
    stop_event = threading.Event()
    client = Mock()
    job = {"job_id": 1, "command": "cmd /c exit 0", "success_exit_codes": [0]}
    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return job
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    client.report_job.side_effect = ApiError("409 conflict")

    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()  # không được ném lỗi ra ngoài
    assert calls["n"] == 2


# ---------------- tự khôi phục khi token bị xóa/thu hồi trên server (401 lặp lại) ----------------


def _write_ini(tmp_path, *, token="dead-token", secret="shared-secret") -> str:
    lines = ["[agent]", "server_url = https://x", "poll_interval = 0", "heartbeat_interval = 0"]
    if token:
        lines.append(f"token = {token}")
    if secret:
        lines.append(f"enrollment_secret = {secret}")
    path = tmp_path / "agent.ini"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_reenroll_after_repeated_401(tmp_path, monkeypatch):
    """Token chết -> poll trả 401 đủ ngưỡng -> agent tự re-enroll, dựng client mới, poll lại được."""
    path = _write_ini(tmp_path)
    stop_event = threading.Event()

    dead_client = Mock()
    dead_client.poll_job.side_effect = ApiError("401 unauthorized", status_code=401)

    new_client = Mock()

    def good_poll():
        stop_event.set()  # dừng loop ngay sau khi poll bằng token mới thành công
        return None

    new_client.poll_job.side_effect = good_poll

    def fake_ensure_enrolled(config, config_path, ev, client=None):
        # Giả lập enroll thành công: trả config có token mới (giữ secret như hành vi thật).
        return dataclasses.replace(config, token="fresh-token")

    monkeypatch.setattr(poll_loop_module, "ensure_enrolled", fake_ensure_enrolled)
    monkeypatch.setattr(poll_loop_module, "AgentClient", lambda config: new_client)

    loop = PollLoop(
        _config(token="dead-token", enrollment_secret="shared-secret"),
        stop_event, client=dead_client, config_path=path,
    )
    loop.run_forever()

    assert dead_client.poll_job.call_count == 3  # đúng ngưỡng rồi mới khôi phục
    assert new_client.poll_job.called  # đã chuyển sang client mới
    # token cũ đã bị xóa khỏi đĩa trong lúc khôi phục (secret vẫn còn để enroll lại).
    reloaded = load_config(path)
    assert reloaded.token == ""
    assert reloaded.enrollment_secret == "shared-secret"


def test_no_reenroll_when_401_resolves_before_threshold(tmp_path, monkeypatch):
    """Vài 401 lẻ rồi poll lại OK (chưa tới ngưỡng) thì KHÔNG re-enroll."""
    path = _write_ini(tmp_path)
    stop_event = threading.Event()
    client = Mock()
    calls = {"n": 0}

    def flaky_poll():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ApiError("401", status_code=401)
        stop_event.set()
        return None

    client.poll_job.side_effect = flaky_poll
    ensure = Mock()
    monkeypatch.setattr(poll_loop_module, "ensure_enrolled", ensure)

    loop = PollLoop(
        _config(token="t", enrollment_secret="shared-secret"),
        stop_event, client=client, config_path=path,
    )
    loop.run_forever()

    ensure.assert_not_called()


def test_gives_up_reenroll_when_no_secret(tmp_path, monkeypatch):
    """401 lặp nhưng cấu hình không có enrollment_secret -> không thể tự enroll, không crash."""
    path = _write_ini(tmp_path, secret="")  # chỉ có token, không secret
    stop_event = threading.Event()
    client = Mock()
    calls = {"n": 0}

    def poll_401():
        calls["n"] += 1
        if calls["n"] >= 5:
            stop_event.set()  # tránh loop vô hạn trong test
        raise ApiError("401", status_code=401)

    client.poll_job.side_effect = poll_401
    ensure = Mock()
    monkeypatch.setattr(poll_loop_module, "ensure_enrolled", ensure)

    loop = PollLoop(
        _config(token="dead-token", enrollment_secret=""),
        stop_event, client=client, config_path=path,
    )
    loop.run_forever()  # không được ném lỗi ra ngoài

    ensure.assert_not_called()  # không có secret -> không gọi enroll
