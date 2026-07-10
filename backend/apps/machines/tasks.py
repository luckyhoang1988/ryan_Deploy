"""Celery tasks cho machines: đồng bộ AD và dọn is_online quá hạn (agent ngừng heartbeat)."""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .ad_sync import sync_computers_from_ad
from .models import Machine

logger = logging.getLogger("apps.machines")


@shared_task(name="apps.machines.tasks.sync_from_ad")
def sync_from_ad(search_ou: str | None = None, user_id: int | None = None, purge: bool = False):
    """
    Đồng bộ máy từ AD (chạy nền để không chặn web worker).
    - purge: nếu True, xóa máy không còn trong kết quả AD (dọn máy cũ khi đổi OU).
    Ghi audit tại đây — cả khi kích hoạt từ UI (user_id) lẫn beat nightly (user_id=None).
    """
    from apps.audit.models import AuditLog

    data = sync_computers_from_ad(search_ou=search_ou, purge=purge).as_dict()

    user = None
    if user_id:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
    AuditLog.record(AuditLog.Action.MACHINE_SYNC, user=user, search_ou=search_ou or "", **data)
    return data


@shared_task(name="apps.machines.tasks.mark_stale_machines_offline")
def mark_stale_machines_offline():
    """
    Agent là nguồn duy nhất xác định is_online (không còn port/ping scan) — nhưng
    AgentHeartbeatView chỉ set is_online=True, không tự set lại False khi agent ngừng
    heartbeat (tắt máy, service dừng, mất mạng). Task này đóng vai trò "phát hiện offline":
    máy đang is_online=True mà last_seen quá hạn (không heartbeat kịp) thì tự chuyển False.
    """
    threshold = settings.RYANDEPLOY.get("AGENT_OFFLINE_THRESHOLD", 900)
    cutoff = timezone.now() - timedelta(seconds=threshold)
    updated = Machine.objects.filter(is_online=True).filter(
        Q(last_seen__lt=cutoff) | Q(last_seen__isnull=True)
    ).update(is_online=False)
    if updated:
        logger.info("Đã đánh offline %s máy quá hạn heartbeat (> %ss)", updated, threshold)
    return {"marked_offline": updated}
