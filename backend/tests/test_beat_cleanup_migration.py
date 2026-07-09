"""Migration machines.0005 phải xóa PeriodicTask rác 'refresh-machine-online-status' còn sót
trong DB beat (task check_all_online đã bị gỡ khỏi code) mà KHÔNG đụng các beat task khác.
"""
import importlib

import pytest
from django_celery_beat.models import IntervalSchedule, PeriodicTask

# Module migration bắt đầu bằng số nên không import bằng cú pháp thường được.
mig = importlib.import_module(
    "apps.machines.migrations.0005_remove_stale_check_all_online_beat",
)


@pytest.mark.django_db
def test_migration_removes_only_the_stale_task():
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=15, period=IntervalSchedule.MINUTES,
    )
    stale = PeriodicTask.objects.create(
        name="refresh-machine-online-status",
        task="apps.machines.tasks.check_all_online",
        interval=schedule,
    )
    keep = PeriodicTask.objects.create(
        name="mark-stale-machines-offline",
        task="apps.machines.tasks.mark_stale_machines_offline",
        interval=schedule,
    )

    mig.remove_stale_beat_task(_DjangoAppsProxy(), None)

    assert not PeriodicTask.objects.filter(pk=stale.pk).exists()
    assert PeriodicTask.objects.filter(pk=keep.pk).exists()


@pytest.mark.django_db
def test_migration_is_idempotent_when_task_absent():
    # Không có dòng rác (deploy sạch) — chạy migration không được lỗi.
    mig.remove_stale_beat_task(_DjangoAppsProxy(), None)


class _DjangoAppsProxy:
    """Migration nhận `apps` (registry lịch sử). Trong test dùng registry thật để lấy model."""

    def get_model(self, app_label, model_name):
        from django.apps import apps as django_apps

        return django_apps.get_model(app_label, model_name)
