"""
Package Library seed — danh sách metadata phần mềm phổ biến (mirror PDQ Deploy
'Package Library'), để admin không phải gõ tay tên/vendor/inventory_name khi mới
bắt đầu dùng catalog.

CHỈ seed metadata (name/vendor/inventory_name/description) — KHÔNG kèm download_url
hay PackageVersion/installer: URL vendor hay đổi theo thời gian nên seed URL cứng dễ
lỗi thời/chết link; admin tự upload hoặc "Tải từ URL" (đã có sẵn ở UI Packages) sau khi
đã có sẵn khung Package này.
"""
from dataclasses import dataclass

from .models import Package


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    vendor: str
    inventory_name: str  # chuỗi khớp DisplayName trong registry Uninstall, dùng cho dò cập nhật
    description: str = ""


# Phần mềm doanh nghiệp phổ biến thường gặp trên fleet Windows. inventory_name là chuỗi
# DisplayName registry thường gặp — admin có thể sửa lại qua UI Packages nếu khác.
DEFAULT_CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry("7-Zip", "Igor Pavlov", "7-Zip", "Trình nén/giải nén file miễn phí."),
    CatalogEntry("Google Chrome", "Google", "Google Chrome", "Trình duyệt web."),
    CatalogEntry("Mozilla Firefox", "Mozilla", "Mozilla Firefox", "Trình duyệt web."),
    CatalogEntry("VLC media player", "VideoLAN", "VLC media player", "Trình phát media đa định dạng."),
    CatalogEntry("Notepad++", "Notepad++ Team", "Notepad++", "Trình soạn thảo văn bản/code."),
    CatalogEntry("Adobe Acrobat Reader DC", "Adobe", "Adobe Acrobat Reader DC", "Đọc file PDF."),
    CatalogEntry("Zoom", "Zoom", "Zoom", "Họp trực tuyến."),
    CatalogEntry("Microsoft Teams", "Microsoft", "Microsoft Teams", "Họp/chat nội bộ."),
    CatalogEntry("Slack", "Slack Technologies", "Slack", "Chat nhóm làm việc."),
    CatalogEntry("TeamViewer", "TeamViewer", "TeamViewer", "Remote desktop hỗ trợ từ xa."),
    CatalogEntry("WinRAR", "win.rar GmbH", "WinRAR", "Trình nén/giải nén file."),
    CatalogEntry("Git", "The Git Development Community", "Git", "Quản lý phiên bản mã nguồn."),
    CatalogEntry("Visual Studio Code", "Microsoft", "Microsoft Visual Studio Code", "Trình soạn code."),
    CatalogEntry("PuTTY", "Simon Tatham", "PuTTY", "SSH/Telnet client."),
    CatalogEntry("WinSCP", "Martin Prikryl", "WinSCP", "SFTP/FTP/SCP client."),
    CatalogEntry("GIMP", "The GIMP Team", "GIMP", "Chỉnh sửa ảnh."),
    CatalogEntry("LibreOffice", "The Document Foundation", "LibreOffice", "Bộ văn phòng miễn phí."),
    CatalogEntry("Wireshark", "Wireshark Foundation", "Wireshark", "Phân tích gói tin mạng."),
)


def seed_default_catalog() -> dict:
    """
    Tạo Package cho mỗi entry trong DEFAULT_CATALOG nếu CHƯA có (get_or_create theo `name`,
    vốn unique). Idempotent: gọi lại nhiều lần không tạo trùng, không ghi đè package admin
    đã chỉnh tay (chỉ tạo mới, không update package đã tồn tại).
    """
    created = 0
    skipped = 0
    for entry in DEFAULT_CATALOG:
        _, was_created = Package.objects.get_or_create(
            name=entry.name,
            defaults={
                "vendor": entry.vendor,
                "inventory_name": entry.inventory_name,
                "description": entry.description,
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1
    return {"created": created, "skipped": skipped, "total": len(DEFAULT_CATALOG)}
