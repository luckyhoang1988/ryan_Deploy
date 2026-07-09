import hashlib
import logging
import secrets

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import AgentToken, EnrollmentSecret

logger = logging.getLogger(__name__)


class EnrollmentError(Exception):
    """Message an toàn để trả thẳng cho agent/log — không bao giờ lộ chi tiết nội bộ."""


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


def issue_enrollment_secret(ad_ou: str, expires_at, *, max_uses=None, user=None, note="") -> tuple[str, EnrollmentSecret]:
    """Tạo secret dùng chung cho self-enrollment. Trả raw secret — chỉ hiển thị 1 lần."""
    raw = generate_token()
    secret = EnrollmentSecret.objects.create(
        ad_ou=ad_ou or "",
        secret_hash=hash_token(raw),
        secret_prefix=raw[:8],
        expires_at=expires_at,
        max_uses=max_uses,
        created_by=user if (user and getattr(user, "is_authenticated", False)) else None,
        note=note,
    )
    return raw, secret


def revoke_enrollment_secret(secret) -> bool:
    """Thu hồi enrollment secret. Trả True nếu secret bị thu hồi (chưa revoke từ trước)."""
    updated = EnrollmentSecret.objects.filter(pk=secret.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now(),
    )
    return updated > 0


def _ou_in_scope(machine_ad_ou: str, secret_ad_ou: str) -> bool:
    """Secret không có ad_ou (rỗng) = global, khớp với mọi máy."""
    if not secret_ad_ou:
        return True
    m = (machine_ad_ou or "").strip().lower()
    s = secret_ad_ou.strip().lower()
    return m == s or m.endswith("," + s)


def enroll_machine(secret_raw: str, hostname: str, source_ip: str = "") -> tuple[str, "Machine"]:
    """
    Đổi enrollment secret lấy 1 AgentToken thật cho máy `hostname`. Atomic (select_for_update
    trong 1 transaction) để chống race giữa 2 request cùng dùng chung secret hoặc cùng
    hostname. use_count chỉ tăng SAU KHI mọi điều kiện đã xác nhận sẽ enroll thành công.
    """
    from apps.machines.models import Machine

    now = timezone.now()
    with transaction.atomic():
        try:
            secret = EnrollmentSecret.objects.select_for_update().get(secret_hash=hash_token(secret_raw))
        except EnrollmentSecret.DoesNotExist:
            raise EnrollmentError("Secret không hợp lệ.")
        if secret.revoked_at is not None:
            raise EnrollmentError("Secret đã bị thu hồi.")
        if secret.expires_at is not None and secret.expires_at <= now:
            raise EnrollmentError("Secret đã hết hạn.")
        if secret.max_uses is not None and secret.use_count >= secret.max_uses:
            raise EnrollmentError("Secret đã hết lượt sử dụng.")

        try:
            # iexact: sync AD (ad_sync.py) và socket.gethostname() phía agent có thể lệch hoa/thường.
            machine = Machine.objects.select_for_update().get(hostname__iexact=hostname)
        except Machine.DoesNotExist:
            raise EnrollmentError("Máy chưa tồn tại trong hệ thống — cần sync AD trước khi enroll.")
        if not machine.enabled:
            raise EnrollmentError("Máy đang bị vô hiệu hóa.")
        if not _ou_in_scope(machine.ad_ou, secret.ad_ou):
            raise EnrollmentError("Máy không thuộc phạm vi OU của secret này.")
        if AgentToken.objects.filter(machine=machine, revoked_at__isnull=True).exists():
            raise EnrollmentError("Máy đã có token agent đang hoạt động — cần thu hồi trước khi enroll lại.")

        logger.info(
            "Agent enroll: hostname=%s ip=%s secret_prefix=%s",
            hostname, source_ip, secret.secret_prefix,
        )
        EnrollmentSecret.objects.filter(pk=secret.pk).update(use_count=F("use_count") + 1)
        raw_token = issue_token(machine, user=None)

    return raw_token, machine
