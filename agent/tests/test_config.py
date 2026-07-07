import pytest

from ryandeploy_agent.config import ConfigError, load_config


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
