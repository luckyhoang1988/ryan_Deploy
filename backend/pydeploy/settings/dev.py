"""Development settings."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Chạy Celery task đồng bộ trong process khi dev nếu cần debug nhanh:
# CELERY_TASK_ALWAYS_EAGER = True
