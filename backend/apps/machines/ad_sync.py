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
from django.db.models import ProtectedError, Q
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
    deleted: int = 0
    total: int = 0
    error: str = ""

    def as_dict(self):
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
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

    # OpenSSL 3 bỏ MD4 khỏi provider mặc định; NTLM bind cần MD4 để tính NT hash.
    from ._md4_compat import install as _install_md4

    if not _install_md4():
        return None, (
            "Thiếu MD4 cho NTLM bind (OpenSSL 3 không có MD4 và pycryptodomex "
            "không khả dụng). Cân nhắc dùng LDAPS + simple bind."
        )

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
        base = cfg.get("SEARCH_OU") or cfg.get("BASE_DN")
        if base:
            entries = _paged_computer_search(conn, base, ["name"])
            info["computers_found"] = len(entries)
            info["search_base"] = base
        else:
            info["note"] = "Bind OK nhưng chưa đặt base_dn để đếm máy."
    except Exception as e:  # noqa: BLE001
        info["ok"] = False
        info["error"] = f"Bind OK nhưng tìm kiếm thất bại: {e}"
    finally:
        conn.unbind()

    return info


def sync_computers_from_ad(
    base_dn: str | None = None,
    search_ou: str | None = None,
    purge: bool = False,
) -> SyncResult:
    """
    Query AD (objectClass=computer) và upsert vào Machine.
    - search_ou / base_dn: override; mặc định lấy từ cấu hình hiệu lực.
    - purge: nếu True, xóa máy trong DB mà không còn trong kết quả AD
      (dùng khi đổi phạm vi OU để dọn máy cũ).
    Trả SyncResult với số created/updated/deleted.
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
        entries = _paged_computer_search(conn, search_base, _COMPUTER_ATTRS)
    except Exception as e:  # noqa: BLE001
        result.error = f"Tìm kiếm AD thất bại: {e}"
        return result
    finally:
        conn.unbind()

    synced_hostnames = set()
    for entry in entries:
        hostname = _attr(entry, "name")
        if not hostname:
            continue
        synced_hostnames.add(hostname)
        fqdn = _attr(entry, "dNSHostName")
        os_name = _attr(entry, "operatingSystem")
        os_version = _attr(entry, "operatingSystemVersion")
        dn = entry.get("dn", "")
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

    # Xóa máy không còn trong kết quả AD (khi đổi OU scope).
    if purge and synced_hostnames:
        candidates = Machine.objects.exclude(hostname__in=synced_hostnames)
        # search_base có thể hẹp hơn toàn domain (VD chỉ 1 OU con) — nếu vậy, giới hạn
        # tập xoá theo đúng scope này (dùng ad_ou, cùng định dạng "OU=...,OU=..." với
        # _extract_ou), tránh xoá nhầm máy thuộc OU khác đã sync ở lần chạy trước.
        # search_ou_chain rỗng nghĩa là search_base là gốc domain (không có OU=) →
        # coi như sync toàn domain, giữ nguyên hành vi xoá không giới hạn như trước.
        search_ou_chain = ",".join(
            p.strip() for p in search_base.split(",") if p.strip().upper().startswith("OU=")
        )
        if search_ou_chain:
            candidates = candidates.filter(
                Q(ad_ou__iexact=search_ou_chain) | Q(ad_ou__iendswith="," + search_ou_chain)
            )
        try:
            deleted_count, _ = candidates.delete()
        except ProtectedError:
            deleted_count = 0
            logger.warning(
                "AD sync purge: một số máy ngoài OU scope còn job liên kết, "
                "không xóa được — bỏ qua, tiếp tục sync."
            )
        result.deleted = deleted_count
        if deleted_count:
            logger.info("AD sync purge: đã xóa %s máy ngoài phạm vi", deleted_count)

    result.total = result.created + result.updated
    logger.info("AD sync: %s created, %s updated, %s deleted", result.created, result.updated, result.deleted)
    return result


def _paged_computer_search(conn, base: str, attrs: list[str]) -> list[dict]:
    """
    Tìm objectClass=computer với phân trang (paged control) để vượt giới hạn
    MaxPageSize mặc định của AD (1000). Trả list dict entry (bỏ referral).
    """
    from ldap3 import SUBTREE

    gen = conn.extend.standard.paged_search(
        search_base=base,
        search_filter="(objectClass=computer)",
        search_scope=SUBTREE,
        attributes=attrs,
        paged_size=500,
        generator=True,
    )
    # paged_search trả cả searchResRef (referral) không có 'attributes' — lọc bỏ.
    return [e for e in gen if isinstance(e, dict) and e.get("type") == "searchResEntry"]


def _attr(entry, name: str) -> str:
    attrs = entry.get("attributes", {}) if isinstance(entry, dict) else {}
    val = attrs.get(name, "")
    if isinstance(val, list):
        val = val[0] if val else ""
    return str(val) if val not in (None, "") else ""


def _extract_ou(dn: str) -> str:
    """Lấy phần OU=... đầu tiên từ distinguishedName."""
    if not dn:
        return ""
    parts = [p.strip() for p in dn.split(",") if p.strip().upper().startswith("OU=")]
    return ",".join(parts)
