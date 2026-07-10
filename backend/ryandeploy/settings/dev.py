"""Development settings."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
RYANDEPLOY = {**RYANDEPLOY, "VAULT_DEV_FALLBACK": True}  # noqa: F405

# Chạy Celery task đồng bộ trong process khi dev nếu cần debug nhanh:
# CELERY_TASK_ALWAYS_EAGER = True
