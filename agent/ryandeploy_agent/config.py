"""Đọc cấu hình agent từ file .ini cục bộ (ghi bởi GPO startup script hoặc thủ công khi
test). Không phụ thuộc Django — agent chạy độc lập trên máy đích."""
import configparser
import os
from dataclasses import dataclass
from typing import Union

DEFAULT_CONFIG_PATH = r"C:\ProgramData\RyanDeployAgent\agent.ini"

_TRUE_VALUES = ("true", "1", "yes")
_FALSE_VALUES = ("false", "0", "no")


class ConfigError(Exception):
    """Cấu hình agent thiếu hoặc không hợp lệ — agent không thể khởi động."""


@dataclass
class AgentConfig:
    server_url: str
    token: str
    poll_interval: int = 20
    heartbeat_interval: int = 300
    job_timeout: int = 1800
    request_timeout: int = 30
    # True = verify TLS bằng CA hệ thống; False = tắt verify (KHÔNG khuyến khích); chuỗi =
    # đường dẫn file CA bundle .pem (dùng khi server dùng CA nội bộ tự ký).
    verify_tls: Union[bool, str] = True

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
    if not server_url:
        raise ConfigError(f"Thiếu 'server_url' trong '{path}'.")
    if not token:
        raise ConfigError(f"Thiếu 'token' trong '{path}'.")

    return AgentConfig(
        server_url=server_url,
        token=token,
        poll_interval=section.getint("poll_interval", fallback=20),
        heartbeat_interval=section.getint("heartbeat_interval", fallback=300),
        job_timeout=section.getint("job_timeout", fallback=1800),
        request_timeout=section.getint("request_timeout", fallback=30),
        verify_tls=_parse_verify_tls(section.get("verify_tls", "true").strip()),
    )


def _parse_verify_tls(raw: str) -> Union[bool, str]:
    low = raw.lower()
    if low in _TRUE_VALUES or low == "":
        return True
    if low in _FALSE_VALUES:
        return False
    return raw  # đường dẫn CA bundle
