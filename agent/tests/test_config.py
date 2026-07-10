import threading

import pytest

from ryandeploy_agent.config import (
    ConfigError,
    clear_token,
    load_config,
    persist_token,
    wait_for_config,
)


def _write(tmp_path, content: str) -> str:
    path = tmp_path / "agent.ini"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="Không tìm thấy"):
        load_config(str(tmp_path / "does_not_exist.ini"))


def test_missing_section_raises(tmp_path):
    path = _write(tmp_path, "[other]\nfoo = bar\n")
    with pytest.raises(ConfigError, match=r"\[agent\]"):
        load_config(path)


def test_missing_server_url_raises(tmp_path):
    path = _write(tmp_path, "[agent]\ntoken = abc123\n")
    with pytest.raises(ConfigError, match="server_url"):
        load_config(path)


def test_missing_token_raises(tmp_path):
    path = _write(tmp_path, "[agent]\nserver_url = https://ryandeploy.example.com\n")
    with pytest.raises(ConfigError, match="token"):
        load_config(path)


def test_valid_config_defaults(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\nserver_url = https://ryandeploy.example.com/\ntoken = abc123\n",
    )
    config = load_config(path)
    assert config.server_url == "https://ryandeploy.example.com/"
    assert config.token == "abc123"
    assert config.poll_interval == 20
    assert config.heartbeat_interval == 300
    assert config.job_timeout == 1800
    assert config.verify_tls is True


def test_valid_config_overrides(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\n"
        "server_url = https://ryandeploy.example.com\n"
        "token = abc123\n"
        "poll_interval = 5\n"
        "heartbeat_interval = 60\n"
        "job_timeout = 900\n"
        "verify_tls = false\n",
    )
    config = load_config(path)
    assert config.poll_interval == 5
    assert config.heartbeat_interval == 60
    assert config.job_timeout == 900
    assert config.verify_tls is False


def test_verify_tls_ca_bundle_path(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\nserver_url = https://ryandeploy.example.com\ntoken = abc123\n"
        r"verify_tls = C:\ProgramData\RyanDeployAgent\ca.pem" "\n",
    )
    config = load_config(path)
    assert config.verify_tls == r"C:\ProgramData\RyanDeployAgent\ca.pem"


def test_build_url_strips_trailing_slash(tmp_path):
    path = _write(
        tmp_path, "[agent]\nserver_url = https://ryandeploy.example.com/\ntoken = abc123\n",
    )
    config = load_config(path)
    assert config.build_url("/api/agent/heartbeat/") == "https://ryandeploy.example.com/api/agent/heartbeat/"


# ---------------- self-enrollment: enrollment_secret / needs_enrollment / persist_token ----------------


def test_missing_both_token_and_secret_raises(tmp_path):
    path = _write(tmp_path, "[agent]\nserver_url = https://ryandeploy.example.com\n")
    with pytest.raises(ConfigError, match="enrollment_secret"):
        load_config(path)


def test_enrollment_secret_without_token_loads_and_needs_enrollment(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\nserver_url = https://ryandeploy.example.com\nenrollment_secret = shared-secret\n",
    )
    config = load_config(path)
    assert config.token == ""
    assert config.enrollment_secret == "shared-secret"
    assert config.needs_enrollment is True


def test_config_with_real_token_does_not_need_enrollment(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\nserver_url = https://ryandeploy.example.com\ntoken = abc123\n"
        "enrollment_secret = leftover-secret\n",
    )
    config = load_config(path)
    # Đã có token thật (đã enroll trước đó) -> không cần enroll lại dù enrollment_secret
    # vẫn còn sót trong file (chưa kịp bị persist_token dọn ở lần trước).
    assert config.needs_enrollment is False


def test_persist_token_writes_token_and_keeps_secret(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\nserver_url = https://ryandeploy.example.com\nenrollment_secret = shared-secret\n"
        "poll_interval = 5\n",
    )
    persist_token(path, "real-token-abc")

    config = load_config(path)
    assert config.token == "real-token-abc"
    # GIỮ secret để còn tự re-enroll nếu token bị xóa/thu hồi sau này (sự cố purge 2026-07-09).
    assert config.enrollment_secret == "shared-secret"
    # Có token thật rồi thì không enroll lại dù secret vẫn còn.
    assert config.needs_enrollment is False
    assert config.poll_interval == 5  # các field khác không bị mất khi ghi lại file


def test_clear_token_removes_token_but_keeps_secret(tmp_path):
    path = _write(
        tmp_path,
        "[agent]\nserver_url = https://ryandeploy.example.com\ntoken = dead-token\n"
        "enrollment_secret = shared-secret\npoll_interval = 5\n",
    )
    clear_token(path)

    config = load_config(path)
    assert config.token == ""
    assert config.enrollment_secret == "shared-secret"
    # Không còn token nhưng còn secret -> agent sẽ enroll lại ở lần khởi động/khôi phục kế tiếp.
    assert config.needs_enrollment is True
    assert config.poll_interval == 5


# ---------------- wait_for_config: chờ agent.ini xuất hiện thay vì thoát service ----------------


def test_wait_for_config_returns_immediately_when_file_already_valid(tmp_path):
    path = _write(tmp_path, "[agent]\nserver_url = https://ryandeploy.example.com\ntoken = abc123\n")
    config = wait_for_config(path, threading.Event())
    assert config is not None
    assert config.token == "abc123"


def test_wait_for_config_retries_until_file_appears(tmp_path, monkeypatch):
    import ryandeploy_agent.config as config_module

    monkeypatch.setattr(config_module, "_CONFIG_INITIAL_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(config_module, "_CONFIG_MAX_BACKOFF_SECONDS", 0)
    path = str(tmp_path / "agent.ini")  # chưa tồn tại — mô phỏng lúc MSI vừa cài xong
    stop_event = threading.Event()

    def write_file_after_first_check():
        # Lần load_config() đầu tiên chắc chắn thất bại (file chưa có); mô phỏng GPO/admin
        # ghi file trong lúc service đang retry bằng cách ghi ngay khi wait() được gọi lần đầu.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[agent]\nserver_url = https://ryandeploy.example.com\ntoken = abc123\n")

    original_wait = stop_event.wait

    def fake_wait(timeout=None):
        write_file_after_first_check()
        return original_wait(0)

    stop_event.wait = fake_wait

    result = wait_for_config(path, stop_event)

    assert result is not None
    assert result.token == "abc123"


def test_wait_for_config_returns_none_when_stopped_while_waiting(tmp_path, monkeypatch):
    import ryandeploy_agent.config as config_module

    monkeypatch.setattr(config_module, "_CONFIG_INITIAL_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(config_module, "_CONFIG_MAX_BACKOFF_SECONDS", 0)
    path = str(tmp_path / "does_not_exist.ini")
    stop_event = threading.Event()

    original_wait = stop_event.wait

    def fake_wait(timeout=None):
        stop_event.set()  # service bị dừng đúng lúc đang chờ cấu hình
        return original_wait(0)

    stop_event.wait = fake_wait

    result = wait_for_config(path, stop_event)

    assert result is None
