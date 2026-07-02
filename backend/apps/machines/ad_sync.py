"""
AD discovery — enumerate computer objects từ Active Directory qua LDAP và
đồng bộ vào bảng Machine. Không nhập tay danh sách máy.

Cấu hình lấy theo thứ tự ưu tiên:
1. Bản ghi ADConfig trong DB (chỉnh từ Web UI) khi enabled=True.
2. Biến môi trường AD_* (settings.AD).
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


def resolve_ad_config() -> dict:
    """
    Trả về cấu hình AD hiệu lực dưới dạng dict chuẩn hóa.
    Ưu tiên ADConfig trong DB (enabled), fallback settings.AD.
    """
    from .models import ADConfig

    obj = ADConfig.objects.filter(pk=1, enabled=True).first()
    if obj and obj.server and obj.bind_user:
        return {
            "SERVER": obj.server,
            "BASE_DN": obj.base_dn,
            "SEARCH_OU": obj.search_ou,
            "BIND_USER": obj.bind_user,
            "BIND_PASSWORD": obj.get_password(),
            "USE_SSL": obj.use_ssl,
            "SOURCE": "db",
        }

    cfg = settings.AD
    return {
        "SERVER": cfg.get("SERVER", ""),
        "BASE_DN": cfg.get("BASE_DN", ""),
        "SEARCH_OU": "",
        "BIND_USER": cfg.get("BIND_USER", ""),
        "BIND_PASSWORD": cfg.get("BIND_PASSWORD", ""),
        "USE_SSL": cfg.get("USE_SSL", False),
        "SOURCE": "env",
    }


def _connect(cfg: dict):
    """Mở kết nối LDAP + bind. Trả (conn, error_str). conn=None nếu lỗi."""
    try:
        from ldap3 import ALL, NTLM, Connection, Server
    except ImportError:
        return None, "ldap3 chưa được cài."

    try:
        server = Server(cfg["SERVER"], use_ssl=cfg.get("USE_SSL", False), get_info=ALL)
        conn = Connection(
            server,
            user=cfg["BIND_USER"],
            password=cfg["BIND_PASSWORD"],
            authentication=NTLM,
            auto_bind=True,
        )
        return conn, ""
    except Exception as e:  # noqa: BLE001
        return None, f"Kết nối/bind AD thất bại: {e}"


def test_ad_connection(cfg: dict | None = None) -> dict:
    """
    Kiểm tra kết nối + bind + (nếu có base) đếm số máy tính tìm được.
    Không trả về mật khẩu. Dùng cho nút 'Test kết nối' trên UI.
    """
    cfg = cfg or resolve_ad_config()

    if not cfg.get("SERVER") or not cfg.get("BIND_USER"):
        return {"ok": False, "error": "Chưa cấu hình AD (thiếu server hoặc bind user)."}

    conn, error = _connect(cfg)
    if error:
        return {"ok": False, "error": error}

    info = {
        "ok": True,
        "server": cfg["SERVER"],
        "bound_as": cfg["BIND_USER"],
        "source": cfg.get("SOURCE", ""),
    }
    try:
        from ldap3 import SUBTREE

        base = cfg.get("SEARCH_OU") or cfg.get("BASE_DN")
        if base:
            conn.search(
                search_base=base,
                search_filter="(objectClass=computer)",
                search_scope=SUBTREE,
                attributes=["name"],
            )
            info["computers_found"] = len(conn.entries)
            info["search_base"] = base
        else:
            info["note"] = "Bind OK nhưng chưa đặt base_dn để đếm máy."
    except Exception as e:  # noqa: BLE001
        info["ok"] = False
        info["error"] = f"Bind OK nhưng tìm kiếm thất bại: {e}"
    finally:
        conn.unbind()

    return info


def sync_computers_from_ad(base_dn: str | None = None, search_ou: str | None = None) -> SyncResult:
    """
    Query AD (objectClass=computer) và upsert vào Machine.
    - search_ou / base_dn: override; mặc định lấy từ cấu hình hiệu lực.
    Trả SyncResult với số created/updated.
    """
    cfg = resolve_ad_config()
    result = SyncResult()

    if not cfg.get("SERVER") or not cfg.get("BIND_USER"):
        result.error = "Chưa cấu hình AD (server / bind user)."
        logger.warning(result.error)
        return result

    search_base = search_ou or base_dn or cfg.get("SEARCH_OU") or cfg.get("BASE_DN")
    if not search_base:
        result.error = "Thiếu BASE_DN để tìm kiếm."
        return result

    conn, error = _connect(cfg)
    if error:
        result.error = error
        logger.error(result.error)
        return result

    try:
        from ldap3 import SUBTREE

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
