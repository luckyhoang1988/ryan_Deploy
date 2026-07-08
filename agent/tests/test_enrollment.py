import threading
from unittest.mock import Mock

from ryandeploy_agent import enrollment
from ryandeploy_agent.client import ApiError
from ryandeploy_agent.config import AgentConfig, load_config
from ryandeploy_agent.enrollment import ensure_enrolled


def _write(tmp_path, content: str) -> str:
    path = tmp_path / "agent.ini"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _config(**overrides):
    base = dict(server_url="https://x", token="", enrollment_secret="shared-secret")
    base.update(overrides)
    return AgentConfig(**base)


def test_noop_when_already_enrolled(tmp_path):
    config = _config(token="real-token", enrollment_secret="")
    client = Mock()

    result = ensure_enrolled(config, str(tmp_path / "agent.ini"), threading.Event(), client=client)

    assert result is config
    client.enroll.assert_not_called()


def test_successful_enroll_persists_token_and_clears_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "get_hostname", lambda: "PC-01")
    path = _write(tmp_path, "[agent]\nserver_url = https://x\nenrollment_secret = shared-secret\n")
    config = load_config(path)

    client = Mock()
    client.enroll.return_value = "new-real-token"

    result = ensure_enrolled(config, path, threading.Event(), client=client)

    client.enroll.assert_called_once_with("shared-secret", "PC-01")
    assert result.token == "new-real-token"
    assert result.enrollment_secret == ""

    # Persist thật vào file — service khởi động lại vẫn đọc được token đã enroll.
    reloaded = load_config(path)
    assert reloaded.token == "new-real-token"
    assert reloaded.needs_enrollment is False


def test_retries_with_backoff_until_success(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "_INITIAL_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(enrollment, "_MAX_BACKOFF_SECONDS", 0)
    path = _write(tmp_path, "[agent]\nserver_url = https://x\nenrollment_secret = shared-secret\n")
    config = load_config(path)

    client = Mock()
    calls = {"n": 0}

    def fake_enroll(secret, hostname):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ApiError("server tạm unreachable")
        return "new-real-token"

    client.enroll.side_effect = fake_enroll

    result = ensure_enrolled(config, path, threading.Event(), client=client)

    assert calls["n"] == 3
    assert result.token == "new-real-token"


def test_stops_when_stop_event_set_mid_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "_INITIAL_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(enrollment, "_MAX_BACKOFF_SECONDS", 0)
    path = _write(tmp_path, "[agent]\nserver_url = https://x\nenrollment_secret = shared-secret\n")
    config = load_config(path)

    stop_event = threading.Event()
    client = Mock()

    def fake_enroll(secret, hostname):
        stop_event.set()  # service bị dừng đúng lúc đang chờ retry
        raise ApiError("server tạm unreachable")

    client.enroll.side_effect = fake_enroll

    result = ensure_enrolled(config, path, stop_event, client=client)

    assert result is config
    assert result.needs_enrollment is True
