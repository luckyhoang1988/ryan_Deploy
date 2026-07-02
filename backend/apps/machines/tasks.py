"""Celery tasks cho machines: đồng bộ AD và kiểm tra online định kỳ."""
import logging
from concurrent.futures import ThreadPoolExecutor

from celery import shared_task

from .ad_sync import sync_computers_from_ad
from .connectivity import refresh_machine_status
from .models import Machine

logger = logging.getLogger("apps.machines")


@shared_task(name="apps.machines.tasks.sync_from_ad")
def sync_from_ad(search_ou: str | None = None):
    result = sync_computers_from_ad(search_ou=search_ou)
    return result.as_dict()


@shared_task(name="apps.machines.tasks.check_all_online")
def check_all_online():
    """Kiểm tra song song trạng thái online của mọi máy enabled."""
    machines = list(Machine.objects.filter(enabled=True))
    if not machines:
        return {"checked": 0, "online": 0}

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(refresh_machine_status, machines))

    online = sum(1 for r in results if r)
    logger.info("Online check: %s/%s máy online", online, len(machines))
    return {"checked": len(machines), "online": online}
