"""HTTP client mỏng cho /api/agent/* — chỉ gọi API và trả JSON/header thô, không chứa logic
nghiệp vụ (đó là việc của executor.py/poll_loop.py)."""
import logging
from typing import Optional
from urllib.parse import urlsplit

import requests

from .config import AgentConfig

logger = logging.getLogger("ryandeploy_agent.client")

_DOWNLOAD_CHUNK_SIZE = 1024 * 256
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or _DEFAULT_PORTS.get(parts.scheme)


class ApiError(Exception):
    """Lỗi gọi API server (mạng, timeout, hoặc HTTP status lỗi) — caller quyết định retry.

    status_code = HTTP status nếu server có trả lời (>=400); None nếu lỗi mạng/timeout (request
    chưa tới được server). Dùng để phân biệt 401 (token đã bị xóa/thu hồi trên server → agent
    phải re-enroll) với lỗi tạm thời (chỉ cần backoff rồi thử lại)."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


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
        """Tải file (URL tuyệt đối do server trả trong payload job) về dest_path, streaming. Trả
        header X-Ryandeploy-Sha256 nếu server có gửi kèm (installer), None nếu không (script nội
        bộ). `_request` tự chặn nếu `url` khác origin với `server_url` cấu hình — session này
        luôn kèm header Authorization: Bearer <token thật> cho MỌI request (xem __init__), nên
        nếu lỡ nhận một job có download_url/script_url trỏ ra host khác (server bị compromise,
        bug tạo URL sai, hay MITM chèn payload), agent sẽ tự gửi token sống cho host lạ đó nếu
        không có chốt chặn same-origin này."""
        resp = self._request("GET", url, absolute=True, stream=True)
        sha256_header = resp.headers.get("X-Ryandeploy-Sha256") or None
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    fh.write(chunk)
        return sha256_header

    def _request(self, method: str, path: str, *, absolute: bool = False, **kwargs) -> requests.Response:
        url = path if absolute else self._config.build_url(path)
        if absolute and _origin(url) != _origin(self._config.server_url):
            # Không gửi request này ra ngoài: self._session kèm sẵn header Authorization cho mọi
            # request (kể cả absolute=True), nên gửi tới origin khác đồng nghĩa lộ token thật ra
            # ngoài server đã cấu hình.
            raise ApiError(f"URL '{url}' khác origin với server_url cấu hình — từ chối gửi kèm token.")
        timeout = kwargs.pop("timeout", self._config.request_timeout)
        try:
            resp = self._session.request(
                method, url, timeout=timeout, verify=self._config.verify_tls, **kwargs
            )
        except requests.RequestException as e:
            raise ApiError(f"Lỗi kết nối server ({method} {url}): {e}") from e
        if resp.status_code >= 400:
            raise ApiError(
                f"Server trả lỗi {resp.status_code} cho {method} {url}: {resp.text[:500]}",
                status_code=resp.status_code,
            )
        return resp
