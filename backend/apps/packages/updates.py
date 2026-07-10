"""
Update tracking — so sánh phần mềm đã cài trên toàn fleet (InstalledSoftware, thu từ
action inventory) với version mới nhất đã duyệt trong catalog → liệt kê máy lỗi thời.

Đây là bản "133 Updates" của RyanDeploy: data-driven, tận dụng inventory sẵn có thay vì
CDN như PDQ Deploy.

So sánh version bằng `packaging.version` (đã cài); fallback so chuỗi khi không parse được
(theo LESSONS: so version phải làm ở Python, không SQL).
"""
import logging

from packaging.version import InvalidVersion, Version

logger = logging.getLogger("apps.packages")


def _parse(v: str):
    try:
        return Version(v)
    except (InvalidVersion, TypeError):
        return None


def is_outdated(installed: str, latest: str) -> bool:
    """
    True nếu bản đã cài cũ hơn bản mới nhất.
    - Parse được cả hai → so theo ngữ nghĩa version (118 < 1200 đúng).
    - Không parse được → coi là lỗi thời khi hai chuỗi KHÁC nhau (thận trọng: bằng nhau
      chắc chắn không lỗi thời).
    """
    installed = (installed or "").strip()
    latest = (latest or "").strip()
    if not installed or not latest:
        return False
    pi, pl = _parse(installed), _parse(latest)
    if pi is not None and pl is not None:
        return pi < pl
    return installed != latest


def _representative(rows):
    """
    Máy có thể có nhiều bản ghi khớp match_name (vd 'Google Chrome' và 'Google Chrome
    Helper'). Chọn bản ghi có tên NGẮN nhất làm đại diện (thường là sản phẩm gốc), và nếu
    máy đã có đúng bản mới nhất ở bất kỳ dòng nào thì coi như không lỗi thời.
    """
    return min(rows, key=lambda r: len(r.name))


def _updates_for_package(pkg) -> dict | None:
    """
    Trả dict cập nhật cho 1 package, hoặc None nếu không có latest/không có máy lỗi thời.
    Cấu trúc: {package_id, package_name, latest_version_id, latest_version, match_name,
               count, outdated: [{machine_id, hostname, installed_version}]}.
    """
    from apps.machines.models import InstalledSoftware

    latest = pkg.latest_version
    if latest is None:
        return None
    match = pkg.match_name
    if not match:
        return None

    rows = list(
        InstalledSoftware.objects.filter(name__icontains=match)
        .select_related("machine")
        .order_by("machine__hostname")
    )
    # Gom theo máy
    by_machine: dict[int, list] = {}
    for sw in rows:
        by_machine.setdefault(sw.machine_id, []).append(sw)

    outdated = []
    for machine_rows in by_machine.values():
        # Máy đã có đúng bản mới nhất ở dòng nào đó → bỏ qua.
        if any((sw.version or "").strip() == latest.version.strip() for sw in machine_rows):
            continue
        rep = _representative(machine_rows)
        if is_outdated(rep.version, latest.version):
            outdated.append(
                {
                    "machine_id": rep.machine_id,
                    "hostname": rep.machine.hostname,
                    "installed_version": rep.version,
                }
            )

    if not outdated:
        return None
    outdated.sort(key=lambda o: o["hostname"])
    return {
        "package_id": pkg.id,
        "package_name": pkg.name,
        "latest_version_id": latest.id,
        "latest_version": latest.version,
        "match_name": match,
        "count": len(outdated),
        "outdated": outdated,
    }


def compute_updates() -> list[dict]:
    """Danh sách package có ít nhất 1 máy lỗi thời (sắp theo số máy giảm dần)."""
    from django.db.models import Prefetch

    from .models import APPROVED_VERSIONS_ATTR, Package, PackageVersion

    # Prefetch riêng bản đã duyệt mới nhất mỗi package (to_attr) → latest_version/match_name
    # dùng cache Python thay vì mỗi package tự query lại (tránh N+1 trên toàn catalog).
    approved_prefetch = Prefetch(
        "versions",
        queryset=PackageVersion.objects.filter(approved=True).order_by("-created_at"),
        to_attr=APPROVED_VERSIONS_ATTR,
    )
    results = []
    for pkg in Package.objects.prefetch_related(approved_prefetch):
        item = _updates_for_package(pkg)
        if item:
            results.append(item)
    results.sort(key=lambda r: r["count"], reverse=True)
    return results


def outdated_machine_ids(pkg) -> list[int]:
    """ID các máy lỗi thời của 1 package (cho deploy cập nhật 1 chạm)."""
    item = _updates_for_package(pkg)
    return [o["machine_id"] for o in item["outdated"]] if item else []
