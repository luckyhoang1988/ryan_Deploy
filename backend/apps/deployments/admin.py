from django.contrib import admin

from .models import Deployment, DeploymentSchedule


@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "package_version",
        "status",
        "scheduled_at",
        "success_count",
        "failed_count",
        "total_count",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("name", "package_version__package__name")
    filter_horizontal = ("target_machines",)
    readonly_fields = ("started_at", "finished_at")


@admin.register(DeploymentSchedule)
class DeploymentScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "action",
        "recurrence_type",
        "enabled",
        "last_triggered_at",
        "created_at",
    )
    list_filter = ("recurrence_type", "enabled")
    search_fields = ("name",)
    filter_horizontal = ("target_machines",)
    readonly_fields = ("last_triggered_at",)
