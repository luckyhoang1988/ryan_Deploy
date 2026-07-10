from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0002_alter_auditlog_action'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(choices=[('package_upload', 'Upload package'), ('package_update', 'Sửa package'), ('package_delete', 'Xóa package'), ('package_version_delete', 'Xóa version'), ('credential_create', 'Tạo credential'), ('credential_update', 'Sửa credential'), ('credential_delete', 'Xóa credential'), ('deployment_create', 'Tạo deployment'), ('deployment_trigger', 'Kích hoạt deployment'), ('deployment_cancel', 'Hủy deployment'), ('job_start', 'Bắt đầu job'), ('job_finish', 'Kết thúc job'), ('machine_sync', 'Đồng bộ máy từ AD')], db_index=True, max_length=32),
        ),
    ]
