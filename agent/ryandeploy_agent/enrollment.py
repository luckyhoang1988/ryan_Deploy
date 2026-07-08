"""Tự động đổi enrollment secret lấy token thật lúc agent khởi động lần đầu (self-enrollment
theo OU) — thay thế việc admin phải cấp token thủ công cho từng máy khi rollout hàng loạt."""
import dataclasses
import logging
import socket
import threading

from .client import AgentClient, ApiError
from .config import AgentConfig, persist_token

logger = logging.getLogger("ryandeploy_agent.enrollment")

_MAX_BACKOFF_SECONDS = 300
_INITIAL_BACKOFF_SECONDS = 5


def get_hostname() -> str:
    return socket.gethostname()


def ensure_enrolled(
    config: AgentConfig, config_path: str, stop_event: threading.Event, client: AgentClient = None,
) -> AgentConfig:
    """No-op nếu đã có token. Nếu không, lặp gọi /enroll với backoff mũ (tối đa 300s) tới khi
    thành công hoặc stop_event được set — secret có thể chưa được admin tạo lúc máy vừa boot,
    hoặc server tạm unreachable. Trả AgentConfig mới (đã có token) nếu thành công; nếu bị dừng
    giữa chừng, trả lại config gốc (caller phải tự kiểm tra needs_enrollment)."""
    if not config.needs_enrollment:
        return config

    hostname = get_hostname()
    agent_client = client or AgentClient(config)
    backoff = _INITIAL_BACKOFF_SECONDS
    while not stop_event.is_set():
        try:
            token = agent_client.enroll(config.enrollment_secret, hostname)
        except ApiError as e:
            logger.warning("Enroll thất bại, thử lại sau %ss: %s", backoff, e)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
            continue

        persist_token(config_path, token)
        logger.info("Enroll thành công (hostname=%s).", hostname)
        return dataclasses.replace(config, token=token, enrollment_secret="")

    return config
