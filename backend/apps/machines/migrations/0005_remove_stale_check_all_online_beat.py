"""Gỡ PeriodicTask rác 'refresh-machine-online-status' khỏi DB beat.

Bối cảnh: trước đây online-status được xác định bằng task Celery beat `check_all_online`
(quét SMB/ping mỗi 15 phút). Từ khi agent trở thành nguồn xác định online duy nhất
(commit a06ad1c), task này đã bị gỡ khỏi CELERY_BEAT_SCHEDULE trong settings. Nhưng
DatabaseScheduler (django_celery_beat) KHÔNG tự xóa dòng PeriodicTask tương ứng trong DB
khi entry biến mất khỏi settings — nó vẫn nằm lại và beat vẫn kích hoạt task đã bị xóa
code (gây lỗi/nhiễu log). Migration này dọn dòng rác đó một cách idempotent khi deploy,
thay cho thao tác gõ shell tay dễ quên trên prod.
"""
from django.db import migrations

STALE_TASK_NAME = "refresh-machine-online-status"


def remove_stale_beat_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=STALE_TASK_NAME).delete()


def noop_reverse(apps, schema_editor):
    # Không tái tạo: task này đã bị gỡ có chủ đích, rollback không nên dựng lại nó.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0004_machine_agent_version_machine_connection_mode"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(remove_stale_beat_task, noop_reverse),
    ]
