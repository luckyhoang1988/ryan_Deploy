"""
Theo dõi chủ sở hữu Celery task (cho endpoint poll /api/tasks/<id>/).

Không có cách nào hỏi ngược từ AsyncResult "ai đã .delay() task này" — phải tự ghi lại lúc
dispatch. Dùng Django cache (Redis, đã cấu hình sẵn cho Celery/Channels) với TTL ngắn, đủ cho
khoảng thời gian client poll tới lúc xong.
"""
from django.core.cache import cache

_TTL = 3600  # 1h — đủ cho các tác vụ nền dài nhất (sync AD, tải installer lớn)


def _key(task_id: str) -> str:
    return f"ryandeploy:task_owner:{task_id}"


def remember_task_owner(task_id: str, user_id: int) -> None:
    cache.set(_key(task_id), user_id, _TTL)


def get_task_owner(task_id: str) -> int | None:
    return cache.get(_key(task_id))
