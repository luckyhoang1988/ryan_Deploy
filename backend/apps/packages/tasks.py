"""Celery tasks cho catalog: tải version từ URL, tự tải & tự duyệt theo policy."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.audit.models import AuditLog

from . import downloader
from .models import AutoDownloadPolicy, Package, PackageDownload, PackageVersion

logger = logging.getLogger("apps.packages")


def _user(user_id):
    if not user_id:
        return None
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk=user_id).first()


@shared_task(name="apps.packages.tasks.fetch_package_version")
def fetch_package_version(package_id: int, url: str, version: str, user_id: int | None = None):
    """Tải 1 installer từ URL về repository (kích hoạt từ UI). Ghi audit."""
    pkg = Package.objects.filter(pk=package_id).first()
    if not pkg:
        return {"error": "package không tồn tại"}

    user = _user(user_id)
    dl = downloader.fetch(pkg, url, version, requested_by=user)
    AuditLog.record(
        AuditLog.Action.PACKAGE_FETCH,
        user=user,
        target=pkg,
        package=pkg.name,
        version=version,
        status=dl.status,
    )
    return {"download_id": dl.id, "status": dl.status, "version_id": dl.package_version_id}


@shared_task(name="apps.packages.tasks.auto_download_check")
def auto_download_check():
    """
    Beat: mỗi Package có download_url và policy != manual → tải bản mới nhất.
    Nhãn version dùng ngày (auto-YYYYMMDD); downloader tự dedup theo SHA-256 nên chạy lại
    trong ngày không tạo trùng. Bỏ qua nếu đã có nhãn hôm nay để tránh xung đột nhãn.
    """
    today = timezone.now().strftime("%Y%m%d")
    version = f"auto-{today}"
    checked = created = 0
    for pkg in (
        Package.objects.exclude(auto_download=AutoDownloadPolicy.MANUAL).exclude(download_url="")
    ):
        checked += 1
        if pkg.versions.filter(version=version).exists():
            continue
        dl = downloader.fetch(pkg, pkg.download_url, version)
        if dl.status == PackageDownload.Status.SUCCESS:
            created += 1
    logger.info("auto_download_check: kiểm %s package, tạo %s version mới", checked, created)
    return {"checked": checked, "created": created}


@shared_task(name="apps.packages.tasks.auto_approve_pending")
def auto_approve_pending():
    """
    Beat: duyệt các version chưa duyệt của package policy=automatic khi đã qua đủ N ngày
    (auto_approve_after_days) kể từ lúc tải — cửa sổ chờ để phát hiện bản lỗi trước khi cho
    deploy (mirror PDQ 'Automatic after N days').
    """
    now = timezone.now()
    approved = 0
    qs = PackageVersion.objects.filter(
        approved=False, package__auto_download=AutoDownloadPolicy.AUTOMATIC
    ).select_related("package")
    for pv in qs:
        threshold = pv.created_at + timedelta(days=pv.package.auto_approve_after_days)
        if now >= threshold:
            pv.approved = True
            pv.approved_at = now
            pv.save(update_fields=["approved", "approved_at", "updated_at"])
            AuditLog.record(
                AuditLog.Action.PACKAGE_APPROVE,
                target=pv,
                package=pv.package.name,
                version=pv.version,
                auto=True,
            )
            approved += 1
    logger.info("auto_approve_pending: duyệt %s version", approved)
    return {"approved": approved}
