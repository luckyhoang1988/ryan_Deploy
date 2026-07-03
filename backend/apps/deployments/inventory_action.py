"""
Inventory action — quét phần mềm đã cài trên máy đích qua PowerShell + registry,
rồi lưu vào InstalledSoftware để phục vụ conditional targeting.

Script `scripts/inventory.ps1` được đẩy tới máy như payload; stdout (JSON) thu qua
cơ chế stdout.log sẵn có của PushExecutor, parse trong post_hook.
"""
import json
import logging
import os
import re

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("apps.deployments")

_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "scripts", "inventory.ps1")
_INVENTORY_COMMAND = 'powershell -NoProfile -ExecutionPolicy Bypass -File "{file}"'


def build_inventory_plan(deployment, machine):
    from .actions import ActionPlan

    return ActionPlan(
        command=_INVENTORY_COMMAND,
        payload_path=_SCRIPT_PATH,
        payload_filename="ryandeploy_inventory.ps1",
        success_exit_codes=[0],
        verify_installer=False,
        post_hook=record_inventory,
    )


def _parse_software(stdout: str) -> list[dict]:
    """Parse JSON ConvertTo-Json (object hoặc array); bền với BOM/dòng thừa."""
    text = (stdout or "").strip().lstrip("﻿")
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if not m:
            logger.warning("Inventory: stdout không phải JSON hợp lệ")
            return []
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        data = [data]
    return data if isinstance(data, list) else []


def record_inventory(machine, result):
    """post_hook: thay toàn bộ InstalledSoftware của máy bằng kết quả scan mới."""
    from apps.machines.models import InstalledSoftware

    items = _parse_software(result.stdout)
    now = timezone.now()

    rows = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        version = (it.get("version") or "").strip()
        key = (name, version)
        if key in seen:  # registry có thể trùng (unique_together = machine,name,version)
            continue
        seen.add(key)
        rows.append(
            InstalledSoftware(
                machine=machine,
                name=name[:512],
                version=version[:128],
                publisher=(it.get("publisher") or "").strip()[:255],
                scanned_at=now,
            )
        )

    with transaction.atomic():
        InstalledSoftware.objects.filter(machine=machine).delete()
        InstalledSoftware.objects.bulk_create(rows)
    logger.info("Inventory %s: ghi %s phần mềm", machine.hostname, len(rows))
