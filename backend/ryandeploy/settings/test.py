"""Test/verify settings — dùng SQLite để chạy check/makemigrations không cần Postgres."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*", "testserver"]
RYANDEPLOY = {**RYANDEPLOY, "VAULT_DEV_FALLBACK": True}  # noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",  # noqa: F405
    }
}
# Chạy Celery đồng bộ khi test
CELERY_TASK_ALWAYS_EAGER = True
# Lưu kết quả task chạy eager vào result backend để endpoint /tasks/<id>/ đọc được
CELERY_TASK_STORE_EAGER_RESULT = True

# Cache in-memory để test không phụ thuộc Redis (throttle dùng cache)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Channel layer in-memory để test WebSocket không phụ thuộc Redis thật.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
