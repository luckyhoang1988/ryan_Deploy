"""Celery tasks cho machines: đồng bộ AD và kiểm tra online định kỳ."""
import logging
from concurrent.futures import ThreadPoolExecutor

from celery import shared_task
from django.conf import settings
from django.db import connections

from .ad_sync import sync_computers_from_ad
from .connectivity import refresh_machine_status
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


def _refresh_and_close(machine) -> bool:
    """Refresh 1 máy rồi đóng kết nối DB thread-local — luồng của ThreadPoolExecutor
    nằm ngoài vòng đời Celery task nên Django không tự đóng connection cho chúng."""
    try:
        return refresh_machine_status(machine)
    finally:
        connections.close_all()


@shared_task(name="apps.machines.tasks.check_all_online")
def check_all_online():
    """Kiểm tra song song trạng thái online của mọi máy enabled."""
    machines = list(Machine.objects.filter(enabled=True))
    if not machines:
        return {"checked": 0, "online": 0}

    max_workers = settings.RYANDEPLOY.get("MACHINE_ONLINE_SCAN_WORKERS", 64)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_refresh_and_close, machines))

    online = sum(1 for r in results if r)
    logger.info("Online check: %s/%s máy online", online, len(machines))
    return {"checked": len(machines), "online": online}
