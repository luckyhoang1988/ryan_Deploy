from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deployment",
        "machine",
        "status",
        "current_step",
        "exit_code",
        "attempts",
        "finished_at",
    )
    list_filter = ("status", "current_step")
    search_fields = ("machine__hostname", "deployment__name")
    readonly_fields = ("output", "error_output", "celery_task_id", "started_at", "finished_at")
