from django.contrib import admin

from .models import Package, PackageVersion


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
    list_display = ("package", "version", "installer_type", "file_size", "sha256", "created_at")
    list_filter = ("installer_type",)
    search_fields = ("package__name", "version", "sha256")
    readonly_fields = ("sha256", "file_size")
