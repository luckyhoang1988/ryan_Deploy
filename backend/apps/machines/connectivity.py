"""Xác định trạng thái online của 1 máy trạm.

Kết hợp OR 3 tín hiệu, ưu tiên rẻ → đắt để short-circuit sớm khi máy online:
  1) ICMP echo (icmplib, privileged=True — raw socket, cần root/CAP_NET_RAW)
  2) TCP 135 (RPC endpoint mapper — Windows luôn lắng nghe nếu máy bật)
  3) TCP 445 (SMB — tín hiệu gốc trước đây, giữ lại cho máy chỉ mở SMB/chặn ICMP)

Một số máy Windows chặn ICMP Echo Request theo policy tường lửa mặc định (rule
"File and Printer Sharing - Echo Request" thường tắt) — khi đó ping luôn fail và
tự fallback xuống 2 check TCP, chỉ tăng nhẹ latency cho các máy đó chứ không sai
kết quả.
"""
import logging
import socket

from django.utils import timezone
from icmplib import ping as icmp_ping
from icmplib.exceptions import ICMPSocketError, NameLookupError

logger = logging.getLogger("apps.machines")

_PING_TIMEOUT = 1.5  # giây — ICMP, rẻ nhất
_PORT_TIMEOUT = 2.0  # giây — TCP connect, đủ dung sai cho WAN/VPN


def _ping_ok(host: str, timeout: float = _PING_TIMEOUT) -> bool:
    try:
        return icmp_ping(host, count=1, timeout=timeout, privileged=True).is_alive
    except NameLookupError:
        return False
    except ICMPSocketError:
        # Không phải "host offline" thật — có thể container thiếu quyền root/CAP_NET_RAW.
        logger.warning("icmplib socket error khi ping %s", host, exc_info=True)
        return False


def _port_open(host: str, port: int, timeout: float = _PORT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_online(host: str) -> bool:
    if not host:
        return False
    return _ping_ok(host) or _port_open(host, 135) or _port_open(host, 445)


def refresh_machine_status(machine) -> bool:
    """Cập nhật is_online + last_seen cho 1 máy. Trả trạng thái online."""
    online = is_online(machine.target_address)
    machine.is_online = online
    if online:
        machine.last_seen = timezone.now()
    machine.save(update_fields=["is_online", "last_seen"])
    return online
