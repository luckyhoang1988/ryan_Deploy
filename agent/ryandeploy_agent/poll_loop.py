"""Vòng lặp chính của agent: heartbeat định kỳ + poll job định kỳ, backoff khi lỗi mạng.
Chạy trong 1 thread riêng — `stop_event` dùng để dừng hợp tác từ service.py/__main__.py."""
import dataclasses
import logging
import threading
import time

from . import __version__
from .client import AgentClient, ApiError
from .config import DEFAULT_CONFIG_PATH, AgentConfig, ConfigError, clear_token, load_config
from .enrollment import ensure_enrolled
from .executor import run_job

logger = logging.getLogger("ryandeploy_agent.poll_loop")

_MAX_BACKOFF_SECONDS = 300
# Số lần poll bị từ chối 401 LIÊN TIẾP trước khi coi token đã chết và tự re-enroll. >1 để không
# phản ứng thái quá với một 401 lẻ (vd đúng lúc token đang xoay), nhưng token bị xóa thật thì 401
# đều đặn mỗi vòng nên vẫn khôi phục nhanh (~vài poll_interval).
_AUTH_FAILURE_THRESHOLD = 3


class PollLoop:
    def __init__(
        self,
        config: AgentConfig,
        stop_event: threading.Event,
        client: AgentClient = None,
        config_path: str = DEFAULT_CONFIG_PATH,
    ):
        self._config = config
        self._stop_event = stop_event
        self._client = client or AgentClient(config)
        self._config_path = config_path
        self._last_heartbeat = 0.0
        self._auth_failures = 0

    def run_forever(self):
        backoff = self._config.poll_interval
        while not self._stop_event.is_set():
            self._maybe_heartbeat()

            try:
                job = self._client.poll_job()
            except ApiError as e:
                if e.status_code == 401:
                    # Token bị từ chối — không backoff mũ (token chết sẽ 401 mãi), mà đếm để
                    # re-enroll; giữ nhịp poll_interval để khôi phục trong vài chục giây.
                    self._handle_auth_failure()
                    self._wait(self._config.poll_interval)
                    continue
                logger.warning("Poll lỗi: %s", e)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                self._wait(backoff)
                continue

            self._auth_failures = 0
            backoff = self._config.poll_interval
            if job is None:
                self._wait(self._config.poll_interval)
                continue

            logger.info("Nhận job %s (action=%s)", job.get("job_id"), job.get("action"))
            self._run_and_report(job)

    def _handle_auth_failure(self):
        self._auth_failures += 1
        logger.warning(
            "Poll bị từ chối 401 (%d/%d) — token có thể đã bị xóa/thu hồi trên server.",
            self._auth_failures, _AUTH_FAILURE_THRESHOLD,
        )
        if self._auth_failures >= _AUTH_FAILURE_THRESHOLD and self._recover_auth():
            self._auth_failures = 0

    def _recover_auth(self) -> bool:
        """Token đã chết → đọc lại config từ đĩa (còn giữ enrollment_secret), bỏ token cũ và
        enroll lại để lấy token mới. Trả True nếu khôi phục xong (đã cập nhật client), False nếu
        không thể (không có secret / đọc config lỗi / bị stop giữa chừng) — khi đó vòng lặp tiếp
        tục thử, không crash."""
        logger.warning("Thử tự khôi phục: re-enroll để lấy token mới.")
        try:
            fresh = load_config(self._config_path)
        except ConfigError as e:
            logger.error("Không đọc lại được cấu hình để re-enroll: %s", e)
            return False

        # Buộc enroll lại: bỏ token cũ (đã chết) cả trên đĩa lẫn trong bộ nhớ, giữ secret.
        fresh = dataclasses.replace(fresh, token="")
        if not fresh.needs_enrollment:
            logger.error(
                "Không có enrollment_secret trong cấu hình — không thể tự re-enroll. Máy này cần "
                "cấp token mới thủ công hoặc cài lại agent.",
            )
            return False
        clear_token(self._config_path)

        new_config = ensure_enrolled(fresh, self._config_path, self._stop_event)
        if new_config.needs_enrollment:
            return False  # bị stop giữa chừng — service đang dừng

        self._config = new_config
        self._client = AgentClient(new_config)
        logger.info("Re-enroll thành công — tiếp tục poll với token mới.")
        return True

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
                skipped=outcome.skipped,
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
