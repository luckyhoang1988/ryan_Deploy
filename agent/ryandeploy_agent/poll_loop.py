"""Vòng lặp chính của agent: heartbeat định kỳ + poll job định kỳ, backoff khi lỗi mạng.
Chạy trong 1 thread riêng — `stop_event` dùng để dừng hợp tác từ service.py/__main__.py."""
import logging
import threading
import time

from . import __version__
from .client import AgentClient, ApiError
from .config import AgentConfig
from .executor import run_job

logger = logging.getLogger("ryandeploy_agent.poll_loop")

_MAX_BACKOFF_SECONDS = 300


class PollLoop:
    def __init__(self, config: AgentConfig, stop_event: threading.Event, client: AgentClient = None):
        self._config = config
        self._stop_event = stop_event
        self._client = client or AgentClient(config)
        self._last_heartbeat = 0.0

    def run_forever(self):
        backoff = self._config.poll_interval
        while not self._stop_event.is_set():
            self._maybe_heartbeat()

            try:
                job = self._client.poll_job()
            except ApiError as e:
                logger.warning("Poll lỗi: %s", e)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                self._wait(backoff)
                continue

            backoff = self._config.poll_interval
            if job is None:
                self._wait(self._config.poll_interval)
                continue

            logger.info("Nhận job %s (action=%s)", job.get("job_id"), job.get("action"))
            self._run_and_report(job)

    def _run_and_report(self, job: dict):
        outcome = run_job(self._client, job, self._config.job_timeout)
        try:
            self._client.report_job(
                job["job_id"],
                exit_code=outcome.exit_code,
                stdout=outcome.stdout,
                error=outcome.error,
                needs_reboot=outcome.needs_reboot,
                verify_passed=outcome.verify_passed,
            )
        except ApiError as e:
            # Server có thể đã tự hủy job này (vd cancel) — không có gì thêm để làm ngoài log,
            # vòng poll tiếp theo sẽ không thấy job này nữa (đã terminal hoặc CANCELLED).
            logger.error("Report job %s thất bại: %s", job.get("job_id"), e)

    def _maybe_heartbeat(self):
        now = time.monotonic()
        if now - self._last_heartbeat < self._config.heartbeat_interval:
            return
        try:
            self._client.heartbeat(agent_version=__version__)
        except ApiError as e:
            logger.warning("Heartbeat lỗi: %s", e)
        finally:
            # Luôn dời mốc kể cả lỗi — tránh spam heartbeat mỗi vòng poll khi server unreachable
            # kéo dài; lần thử kế tiếp vẫn cách đều theo heartbeat_interval.
            self._last_heartbeat = now

    def _wait(self, seconds: float):
        self._stop_event.wait(seconds)
