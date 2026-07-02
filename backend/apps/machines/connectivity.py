"""Kiểm tra máy trạm online qua SMB (445)."""
import socket

from django.utils import timezone


def is_online(host: str, port: int = 445, timeout: float = 3.0) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def refresh_machine_status(machine) -> bool:
    """Cập nhật is_online + last_seen cho 1 máy. Trả trạng thái online."""
    online = is_online(machine.target_address)
    machine.is_online = online
    if online:
        machine.last_seen = timezone.now()
    machine.save(update_fields=["is_online", "last_seen"])
    return online
