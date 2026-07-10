"""Đọc cấu hình agent từ file .ini cục bộ (ghi bởi GPO startup script hoặc thủ công khi
test). Không phụ thuộc Django — agent chạy độc lập trên máy đích."""
import configparser
import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional, Union

DEFAULT_CONFIG_PATH = r"C:\ProgramData\RyanDeployAgent\agent.ini"

_TRUE_VALUES = ("true", "1", "yes")
_FALSE_VALUES = ("false", "0", "no")

_CONFIG_INITIAL_BACKOFF_SECONDS = 5
_CONFIG_MAX_BACKOFF_SECONDS = 60

logger = logging.getLogger("ryandeploy_agent.config")


class ConfigError(Exception):
    """Cấu hình agent thiếu hoặc không hợp lệ — agent không thể khởi động."""


@dataclass
class AgentConfig:
    server_url: str
    token: str
    # Đặt khi máy chưa enroll — dùng đổi lấy token thật qua /api/agent/enroll/ (xem enrollment.py).
    # GPO startup script mới ghi field này thay vì 'token' để cấp quyền hàng loạt không cần biết
    # trước hostname từng máy.
    enrollment_secret: str = ""
    poll_interval: int = 20
    heartbeat_interval: int = 300
    job_timeout: int = 1800
    request_timeout: int = 30
    # True = verify TLS bằng CA hệ thống; False = tắt verify (KHÔNG khuyến khích); chuỗi =
    # đường dẫn file CA bundle .pem (dùng khi server dùng CA nội bộ tự ký).
    verify_tls: Union[bool, str] = True

    @property
    def needs_enrollment(self) -> bool:
        return bool(self.enrollment_secret and not self.token)

    def build_url(self, path: str) -> str:
        return f"{self.server_url.rstrip('/')}{path}"


def load_config(path: str = DEFAULT_CONFIG_PATH) -> AgentConfig:
    if not os.path.isfile(path):
        raise ConfigError(f"Không tìm thấy file cấu hình agent: {path}")

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if not parser.has_section("agent"):
        raise ConfigError(f"File cấu hình '{path}' thiếu section [agent].")
    section = parser["agent"]

    server_url = section.get("server_url", "").strip()
    token = section.get("token", "").strip()
    enrollment_secret = section.get("enrollment_secret", "").strip()
    if not server_url:
        raise ConfigError(f"Thiếu 'server_url' trong '{path}'.")
    if not token and not enrollment_secret:
        raise ConfigError(f"Thiếu 'token' hoặc 'enrollment_secret' trong '{path}'.")

    return AgentConfig(
        server_url=server_url,
        token=token,
        enrollment_secret=enrollment_secret,
        poll_interval=section.getint("poll_interval", fallback=20),
        heartbeat_interval=section.getint("heartbeat_interval", fallback=300),
        job_timeout=section.getint("job_timeout", fallback=1800),
        request_timeout=section.getint("request_timeout", fallback=30),
        verify_tls=_parse_verify_tls(section.get("verify_tls", "true").strip()),
    )


def wait_for_config(path: str, stop_event: threading.Event) -> Optional[AgentConfig]:
    """Lặp load_config() với backoff tới khi thành công hoặc stop_event được set. Cần thiết vì
    agent.ini có thể CHƯA TỒN TẠI lúc service khởi động lần đầu: MSI cố tự start service ngay
    sau khi cài xong (ServiceControl Start="install"), trước khi GPO startup script hoặc admin
    kịp ghi file cấu hình — nếu để load_config() raise thẳng ra ngoài, service thoát ngay lập
    tức và Windows Installer/SCM báo "service failed to start". Trả None nếu bị dừng giữa
    chừng (caller phải tự dừng sạch, không start PollLoop)."""
    backoff = _CONFIG_INITIAL_BACKOFF_SECONDS
    while not stop_event.is_set():
        try:
            return load_config(path)
        except ConfigError as e:
            logger.warning("Chưa có cấu hình hợp lệ (%s), thử lại sau %ss.", e, backoff)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, _CONFIG_MAX_BACKOFF_SECONDS)
    return None


def persist_token(path: str, token: str) -> None:
    """Ghi token thật vào agent.ini sau khi enroll thành công. GIỮ NGUYÊN 'enrollment_secret':
    nếu sau này token bị xóa/thu hồi trên server (vd admin purge máy → CASCADE xóa token, sự cố
    2026-07-09), agent cần secret này để tự re-enroll thay vì kẹt 401 vĩnh viễn phải cài lại tay.
    Secret là bí mật dùng chung theo OU đã có sẵn trên máy (GPO ghi lúc rollout) nên giữ lại
    không tăng đáng kể bề mặt lộ, và server vẫn có thể thu hồi/để hết hạn secret khi cần. Ghi qua
    file tạm + os.replace() để tránh corrupt file nếu service bị kill giữa lúc ghi."""
    _rewrite(path, {"token": token})


def clear_token(path: str) -> None:
    """Xóa 'token' khỏi agent.ini để buộc agent enroll lại (dùng khi token bị server từ chối lặp
    lại — token đã chết). Giữ nguyên 'enrollment_secret' để enroll lại được. Ghi xuống đĩa (không
    chỉ trong RAM) để nếu service crash giữa lúc khôi phục, lần khởi động sau vẫn re-enroll."""
    _rewrite(path, remove=("token",))


def _rewrite(path: str, set_options: Optional[dict] = None, remove: tuple = ()) -> None:
    """Đọc–sửa–ghi agent.ini nguyên tử (file tạm + os.replace), giữ nguyên các option khác."""
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if not parser.has_section("agent"):
        parser.add_section("agent")
    for key, value in (set_options or {}).items():
        parser.set("agent", key, value)
    for key in remove:
        parser.remove_option("agent", key)

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        parser.write(fh)
    os.replace(tmp_path, path)


def _parse_verify_tls(raw: str) -> Union[bool, str]:
    low = raw.lower()
    if low in _TRUE_VALUES or low == "":
        return True
    if low in _FALSE_VALUES:
        return False
    return raw  # đường dẫn CA bundle
