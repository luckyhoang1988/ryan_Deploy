import requests

import pytest

from ryandeploy_agent.client import AgentClient, ApiError
from ryandeploy_agent.config import AgentConfig


def _config(**overrides):
    base = dict(server_url="https://ryandeploy.example.com", token="s3cr3t")
    base.update(overrides)
    return AgentConfig(**base)


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, headers=None, chunks=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self._chunks = chunks or []
        self.text = text

    def json(self):
        return self._json

    def iter_content(self, chunk_size=None):
        return iter(self._chunks)


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.headers = {}
        self._response = response
        self._exc = exc
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self._exc:
            raise self._exc
        return self._response


def test_sets_bearer_header():
    session = FakeSession(response=FakeResponse())
    AgentClient(_config(), session=session)
    assert session.headers["Authorization"] == "Bearer s3cr3t"


def test_poll_job_returns_job_dict():
    session = FakeSession(response=FakeResponse(json_data={"job": {"job_id": 1}}))
    client = AgentClient(_config(), session=session)
    assert client.poll_job() == {"job_id": 1}
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://ryandeploy.example.com/api/agent/jobs/poll/"


def test_poll_job_returns_none_when_no_job():
    session = FakeSession(response=FakeResponse(json_data={"job": None}))
    client = AgentClient(_config(), session=session)
    assert client.poll_job() is None


def test_report_job_posts_fields():
    session = FakeSession(response=FakeResponse(json_data={"status": "success"}))
    client = AgentClient(_config(), session=session)
    result = client.report_job(42, exit_code=0, stdout="ok", error="", needs_reboot=False, verify_passed=None)
    assert result == {"status": "success"}
    method, url, kwargs = session.calls[0]
    assert url == "https://ryandeploy.example.com/api/agent/jobs/42/report/"
    assert kwargs["json"]["exit_code"] == 0


def test_heartbeat_posts_agent_version():
    session = FakeSession(response=FakeResponse(json_data={"detail": "ok"}))
    client = AgentClient(_config(), session=session)
    client.heartbeat("1.0.0")
    method, url, kwargs = session.calls[0]
    assert url == "https://ryandeploy.example.com/api/agent/heartbeat/"
    assert kwargs["json"] == {"agent_version": "1.0.0"}


def test_download_to_writes_file_and_returns_sha_header(tmp_path):
    dest = tmp_path / "payload.exe"
    session = FakeSession(
        response=FakeResponse(chunks=[b"abc", b"def"], headers={"X-Ryandeploy-Sha256": "deadbeef"})
    )
    client = AgentClient(_config(), session=session)
    sha = client.download_to("https://ryandeploy.example.com/api/agent/packages/1/download/", str(dest))
    assert sha == "deadbeef"
    assert dest.read_bytes() == b"abcdef"
    method, url, kwargs = session.calls[0]
    assert kwargs["stream"] is True


def test_download_to_returns_none_without_sha_header(tmp_path):
    dest = tmp_path / "script.ps1"
    session = FakeSession(response=FakeResponse(chunks=[b"Write-Output 1"]))
    client = AgentClient(_config(), session=session)
    sha = client.download_to("https://ryandeploy.example.com/api/agent/scripts/x.ps1/", str(dest))
    assert sha is None


def test_request_exception_raises_api_error():
    session = FakeSession(exc=requests.ConnectionError("refused"))
    client = AgentClient(_config(), session=session)
    with pytest.raises(ApiError, match="Lỗi kết nối"):
        client.poll_job()


def test_http_error_status_raises_api_error():
    session = FakeSession(response=FakeResponse(status_code=401, text="Token agent không hợp lệ."))
    client = AgentClient(_config(), session=session)
    with pytest.raises(ApiError, match="401"):
        client.poll_job()


def test_download_to_rejects_cross_origin_url(tmp_path):
    dest = tmp_path / "payload.exe"
    session = FakeSession(response=FakeResponse(chunks=[b"abc"]))
    client = AgentClient(_config(), session=session)
    with pytest.raises(ApiError, match="khác origin"):
        client.download_to("https://evil.example.org/steal.exe", str(dest))
    assert session.calls == []  # không gửi request (và không kèm token) ra ngoài
    assert not dest.exists()


def test_download_to_rejects_cross_port_same_host(tmp_path):
    dest = tmp_path / "payload.exe"
    session = FakeSession(response=FakeResponse(chunks=[b"abc"]))
    client = AgentClient(_config(), session=session)
    with pytest.raises(ApiError, match="khác origin"):
        client.download_to("https://ryandeploy.example.com:8443/api/agent/packages/1/download/", str(dest))
    assert session.calls == []


def test_download_to_allows_default_https_port_match(tmp_path):
    dest = tmp_path / "payload.exe"
    session = FakeSession(
        response=FakeResponse(chunks=[b"abc"], headers={"X-Ryandeploy-Sha256": "deadbeef"})
    )
    client = AgentClient(_config(), session=session)
    # server_url không ghi rõ :443, URL server trả cũng không — vẫn phải coi là cùng origin.
    sha = client.download_to("https://ryandeploy.example.com/api/agent/scripts/verify.ps1", str(dest))
    assert sha == "deadbeef"
    assert len(session.calls) == 1


def test_verify_tls_passed_through():
    session = FakeSession(response=FakeResponse(json_data={"job": None}))
    client = AgentClient(_config(verify_tls=False), session=session)
    client.poll_job()
    _, _, kwargs = session.calls[0]
    assert kwargs["verify"] is False


# ---------------- self-enrollment: enroll() không kèm Authorization ----------------


def test_no_bearer_header_when_no_token():
    session = FakeSession(response=FakeResponse())
    AgentClient(_config(token="", enrollment_secret="shared-secret"), session=session)
    assert "Authorization" not in session.headers


def test_enroll_posts_without_auth_header():
    session = FakeSession(response=FakeResponse(json_data={"token": "new-real-token"}))
    client = AgentClient(_config(token="", enrollment_secret="shared-secret"), session=session)

    result = client.enroll("shared-secret", "PC-01")

    assert result == "new-real-token"
    assert "Authorization" not in session.headers
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://ryandeploy.example.com/api/agent/enroll/"
    assert kwargs["json"] == {"secret": "shared-secret", "hostname": "PC-01"}
