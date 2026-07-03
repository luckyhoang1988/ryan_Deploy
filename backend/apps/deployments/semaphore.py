"""
Semaphore đếm slot chạy song song PER-DEPLOYMENT trên Redis.

Giới hạn `max_concurrency` của một Deployment không thể biểu diễn bằng Celery
`rate_limit` (rate_limit là giới hạn tần suất theo loại-task/worker, không phải số
job chạy đồng thời theo từng deployment). Thay vào đó dùng một bộ đếm Redis:
mỗi job `deploy_to_machine` xin 1 slot trước khi chạy, trả lại slot khi xong.

Thiết kế fail-open: nếu Redis lỗi/không sẵn sàng, coi như cấp slot (không chặn deploy)
— throttle chỉ là best-effort, không được biến sự cố Redis thành sự cố deploy.
Bộ đếm có TTL an toàn: nếu worker bị kill giữa chừng làm rò slot, TTL sẽ tự reset
để deployment không kẹt vĩnh viễn.
"""
import logging

import redis
from django.conf import settings

logger = logging.getLogger("apps.deployments")

_client = None


def _redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL)
    return _client


def _key(deployment_id: int) -> str:
    return f"ryandeploy:sema:deploy:{deployment_id}"


def acquire_slot(deployment_id: int, limit: int, ttl: int) -> bool:
    """
    Thử chiếm 1 slot. Trả True nếu được chạy, False nếu đã đầy (cần chờ).
    limit <= 0 nghĩa là không giới hạn → luôn cấp.
    """
    if limit is None or limit <= 0:
        return True
    key = _key(deployment_id)
    try:
        r = _redis()
        n = r.incr(key)
        # Đặt/gia hạn TTL an toàn để chống rò slot khi worker chết.
        r.expire(key, ttl)
        if n > limit:
            r.decr(key)  # vượt trần → trả lại, báo caller chờ
            return False
        return True
    except redis.RedisError as e:  # fail-open
        logger.warning("Semaphore acquire lỗi Redis (cấp slot fail-open): %s", e)
        return True


def release_slot(deployment_id: int) -> None:
    """Trả lại 1 slot (guarded: không cho đếm xuống âm)."""
    key = _key(deployment_id)
    try:
        r = _redis()
        if int(r.get(key) or 0) > 0:
            r.decr(key)
    except redis.RedisError as e:
        logger.warning("Semaphore release lỗi Redis (bỏ qua): %s", e)


def clear_slots(deployment_id: int) -> None:
    """Xóa hẳn bộ đếm — gọi khi bắt đầu lại hoặc kết thúc deployment."""
    try:
        _redis().delete(_key(deployment_id))
    except redis.RedisError as e:
        logger.warning("Semaphore clear lỗi Redis (bỏ qua): %s", e)
