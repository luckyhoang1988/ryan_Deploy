"""HTTP client mỏng cho /api/agent/* — chỉ gọi API và trả JSON/header thô, không chứa logic
nghiệp vụ (đó là việc của executor.py/poll_loop.py)."""
import logging
from typing import Optional

import requests

from .config import AgentConfig

logger = logging.getLogger("ryandeploy_agent.client")

_DOWNLOAD_CHUNK_SIZE = 1024 * 256


class ApiError(Exception):
    """Lỗi gọi API server (mạng, timeout, hoặc HTTP status lỗi) — caller quyết định retry."""


class AgentClient:
    def __init__(self, config: AgentConfig, session: Optional[requests.Session] = None):
        self._config = config
        self._session = session or requests.Session()
        # Máy chưa enroll không có token thật — request tới /enroll (mặt phẳng chưa tin cậy)
        # không được kèm header Authorization.
        if config.token:
            self._session.headers["Authorization"] = f"Bearer {config.token}"

    def enroll(self, secret: str, hostname: str) -> str:
        """Đổi enrollment secret lấy token thật (xem enrollment.py). Không kèm Authorization —
        chỉ hợp lệ khi config chưa có token, đúng lúc __init__ không set header này."""
        resp = self._request("POST", "/api/agent/enroll/", json={"secret": secret, "hostname": hostname})
        return resp.json()["token"]

    def poll_job(self) -> Optional[dict]:
        """Trả dict job nếu server có job đang chờ cho máy này, None nếu không có."""
        resp = self._request("POST", "/api/agent/jobs/poll/")
        return resp.json().get("job")

    def report_job(self, job_id: int, **fields) -> dict:
        resp = self._request("POST", f"/api/agent/jobs/{job_id}/report/", json=fields)
        return resp.json()

    def heartbeat(self, agent_version: str) -> None:
        self._request("POST", "/api/agent/heartbeat/", json={"agent_version": agent_version})

    def download_to(self, url: str, dest_path: str) -> Optional[str]:
        """Tải file (URL tuyệt đối do server trả) về dest_path, streaming. Trả header
        X-Ryandeploy-Sha256 nếu server có gửi kèm (installer), None nếu không (script nội bộ)."""
        resp = self._request("GET", url, absolute=True, stream=True)
        sha256_header = resp.headers.get("X-Ryandeploy-Sha256") or None
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    fh.write(chunk)
        return sha256_header

    def _request(self, method: str, path: str, *, absolute: bool = False, **kwargs) -> requests.Response:
        url = path if absolute else self._config.build_url(path)
        timeout = kwargs.pop("timeout", self._config.request_timeout)
        try:
            resp = self._session.request(
                method, url, timeout=timeout, verify=self._config.verify_tls, **kwargs
            )
        except requests.RequestException as e:
            raise ApiError(f"Lỗi kết nối server ({method} {url}): {e}") from e
        if resp.status_code >= 400:
            raise ApiError(f"Server trả lỗi {resp.status_code} cho {method} {url}: {resp.text[:500]}")
        return resp
