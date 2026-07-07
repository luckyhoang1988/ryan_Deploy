import hashlib
import secrets

from django.utils import timezone

from .models import AgentToken


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(machine, user=None) -> str:
    """Thu hồi token cũ của máy (nếu có) rồi cấp token mới. Trả raw token — chỉ hiển thị 1 lần."""
    raw = generate_token()
    AgentToken.objects.filter(machine=machine, revoked_at__isnull=True).update(
        revoked_at=timezone.now(),
    )
    AgentToken.objects.create(
        machine=machine,
        token_hash=hash_token(raw),
        token_prefix=raw[:8],
        created_by=user if (user and getattr(user, "is_authenticated", False)) else None,
    )
    return raw


def revoke_token(machine) -> bool:
    """Thu hồi token đang hiệu lực của máy. Trả True nếu có token bị thu hồi."""
    updated = AgentToken.objects.filter(machine=machine, revoked_at__isnull=True).update(
        revoked_at=timezone.now(),
    )
    return updated > 0
