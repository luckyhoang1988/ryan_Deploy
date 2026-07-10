from django.contrib import admin

from .models import Package, PackageDownload, PackageVersion


class PackageVersionInline(admin.TabularInline):
    model = PackageVersion
    extra = 0
    readonly_fields = ("sha256", "file_size", "created_at")


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "total_licenses", "used_licenses", "available_licenses")
    search_fields = ("name", "vendor")
    inlines = [PackageVersionInline]


@admin.register(PackageVersion)
class PackageVersionAdmin(admin.ModelAdmin):
    list_display = (
        "package", "version", "installer_type", "source", "approved", "file_size", "created_at"
    )
    list_filter = ("installer_type", "source", "approved")
    search_fields = ("package__name", "version", "sha256")
    readonly_fields = ("sha256", "file_size")


@admin.register(PackageDownload)
class PackageDownloadAdmin(admin.ModelAdmin):
    list_display = ("package", "version_str", "status", "file_size", "requested_by", "created_at")
    list_filter = ("status",)
    search_fields = ("package__name", "url")
    readonly_fields = ("sha256", "file_size")
