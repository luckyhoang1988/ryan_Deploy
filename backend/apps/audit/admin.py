from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "user", "target_type", "target_id", "machine_hostname")
    list_filter = ("action",)
    search_fields = ("user__username", "target_id", "machine_hostname")
    readonly_fields = ("created_at", "action", "user", "target_type", "target_id", "machine_hostname", "detail")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
