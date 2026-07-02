"""
AD discovery — enumerate computer objects từ Active Directory qua LDAP và
đồng bộ vào bảng Machine. Không nhập tay danh sách máy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from .models import Machine

logger = logging.getLogger("apps.machines")

_COMPUTER_ATTRS = [
    "name",
    "dNSHostName",
    "operatingSystem",
    "operatingSystemVersion",
    "distinguishedName",
]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    total: int = 0
    error: str = ""

    def as_dict(self):
        return {
            "created": self.created,
            "updated": self.updated,
            "total": self.total,
            "error": self.error,
        }


def sync_computers_from_ad(base_dn: str | None = None, search_ou: str | None = None) -> SyncResult:
    """
    Query AD (objectClass=computer) và upsert vào Machine.
    - base_dn / search_ou: mặc định lấy từ settings.AD['BASE_DN'].
    Trả SyncResult với số created/updated.
    """
    cfg = settings.AD
    result = SyncResult()

    if not cfg.get("SERVER") or not cfg.get("BIND_USER"):
        result.error = "Chưa cấu hình AD (AD_SERVER / AD_BIND_USER)."
        logger.warning(result.error)
        return result

    search_base = search_ou or base_dn or cfg.get("BASE_DN")
    if not search_base:
        result.error = "Thiếu BASE_DN để tìm kiếm."
        return result

    try:
        from ldap3 import ALL, NTLM, SUBTREE, Connection, Server
    except ImportError:
        result.error = "ldap3 chưa được cài."
        return result

    try:
        server = Server(cfg["SERVER"], use_ssl=cfg.get("USE_SSL", False), get_info=ALL)
        conn = Connection(
            server,
            user=cfg["BIND_USER"],
            password=cfg["BIND_PASSWORD"],
            authentication=NTLM,
            auto_bind=True,
        )
    except Exception as e:  # noqa: BLE001
        result.error = f"Kết nối/bind AD thất bại: {e}"
        logger.error(result.error)
        return result

    try:
        conn.search(
            search_base=search_base,
            search_filter="(objectClass=computer)",
            search_scope=SUBTREE,
            attributes=_COMPUTER_ATTRS,
        )
        entries = conn.entries
    except Exception as e:  # noqa: BLE001
        result.error = f"Tìm kiếm AD thất bại: {e}"
        return result
    finally:
        conn.unbind()

    for entry in entries:
        hostname = _attr(entry, "name")
        if not hostname:
            continue
        fqdn = _attr(entry, "dNSHostName")
        os_name = _attr(entry, "operatingSystem")
        os_version = _attr(entry, "operatingSystemVersion")
        dn = _attr(entry, "distinguishedName")
        ou = _extract_ou(dn)

        _, created = Machine.objects.update_or_create(
            hostname=hostname,
            defaults={
                "fqdn": fqdn or "",
                "os_name": os_name or "",
                "os_version": os_version or "",
                "ad_ou": ou,
            },
        )
        if created:
            result.created += 1
        else:
            result.updated += 1

    result.total = result.created + result.updated
    logger.info("AD sync: %s created, %s updated", result.created, result.updated)
    return result


def _attr(entry, name: str) -> str:
    try:
        val = getattr(entry, name).value
    except Exception:
        return ""
    if isinstance(val, list):
        val = val[0] if val else ""
    return str(val) if val is not None else ""


def _extract_ou(dn: str) -> str:
    """Lấy phần OU=... đầu tiên từ distinguishedName."""
    if not dn:
        return ""
    parts = [p.strip() for p in dn.split(",") if p.strip().upper().startswith("OU=")]
    return ",".join(parts)
