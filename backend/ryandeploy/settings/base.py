"""
Base settings for RyanDeploy — shared across all environments.
Môi trường cụ thể (dev/prod) import từ file này.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ryandeploy/settings/base.py -> BASE_DIR = backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Nạp .env ở gốc repo (một cấp trên backend/) nếu có
load_dotenv(BASE_DIR.parent / ".env")


def env(key: str, default=None):
    return os.getenv(key, default)


def env_bool(key: str, default=False):
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_int(key: str, default=0):
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 3rd party
    "rest_framework",
    "corsheaders",
    "django_celery_results",
    "django_celery_beat",
    # RyanDeploy apps
    "apps.core",
    "apps.credentials",
    "apps.packages",
    "apps.machines",
    "apps.deployments",
    "apps.jobs",
    "apps.audit",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ryandeploy.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ryandeploy.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "ryandeploy"),
        "USER": env("POSTGRES_USER", "ryandeploy"),
        "PASSWORD": env("POSTGRES_PASSWORD", "ryandeploy"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.core.permissions.IsViewerOrAbove",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",  # chống brute-force đăng nhập
        "deployment_action": "30/min",  # chống spam trigger/cancel deployment
    },
}

# --- Celery ---
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env_int("RYANDEPLOY_JOB_TIMEOUT", 1800) + 300
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# --- Cache (Redis) ---
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --- CORS (dev UI) ---
CORS_ALLOW_ALL_ORIGINS = DEBUG

# ============================================================
# RyanDeploy — deployment engine config
# ============================================================
RYANDEPLOY = {
    "VAULT_KEY": env("RYANDEPLOY_VAULT_KEY"),
    "TARGET_DIR": env("RYANDEPLOY_TARGET_DIR", r"RyanDeploy\Runner"),
    "SERVICE_PREFIX": env("RYANDEPLOY_SERVICE_PREFIX", "RyanDeployRunner"),
    "MAX_CONCURRENCY": env_int("RYANDEPLOY_MAX_CONCURRENCY", 15),
    "JOB_TIMEOUT": env_int("RYANDEPLOY_JOB_TIMEOUT", 1800),
    # Trần kích thước file installer được upload (MB) — chặn làm đầy đĩa. Django stream
    # file lớn ra temp disk (không nạp hết RAM) nên đây là giới hạn dung lượng, không phải RAM.
    "MAX_INSTALLER_MB": env_int("RYANDEPLOY_MAX_INSTALLER_MB", 2048),
    # --- Catalog / Auto Download ---
    # Timeout (giây) khi tải installer từ URL ngoài (downloader.py).
    "DOWNLOAD_TIMEOUT": env_int("RYANDEPLOY_DOWNLOAD_TIMEOUT", 300),
}

# Chặn body form phi-file quá lớn (không áp cho file upload — file đã có trần riêng ở
# serializer PackageVersion). Mặc định Django là 2.5MB; giữ nguyên mức đó cho rõ ràng.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2621440  # 2.5 MB

# --- Active Directory (Phase 5) ---
AD = {
    "SERVER": env("AD_SERVER", ""),
    "BASE_DN": env("AD_BASE_DN", ""),
    "BIND_USER": env("AD_BIND_USER", ""),
    "BIND_PASSWORD": env("AD_BIND_PASSWORD", ""),
    "USE_SSL": env_bool("AD_USE_SSL", False),
}

# --- Celery Beat: lịch định kỳ ---
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "refresh-machine-online-status": {
        "task": "apps.machines.tasks.check_all_online",
        "schedule": 900.0,  # mỗi 15 phút
    },
    "nightly-ad-sync": {
        "task": "apps.machines.tasks.sync_from_ad",
        "schedule": crontab(hour=2, minute=0),  # 02:00 hằng đêm
    },
    "trigger-scheduled-deployments": {
        "task": "apps.deployments.tasks.trigger_scheduled_deployments",
        "schedule": 60.0,  # mỗi phút: kích hoạt deployment đã tới giờ hẹn
    },
    "reconcile-stuck-deployments": {
        "task": "apps.deployments.tasks.reconcile_stuck_deployments",
        "schedule": 300.0,  # mỗi 5 phút: gỡ deployment kẹt RUNNING nếu chord callback không chạy
    },
    "packages-auto-download": {
        "task": "apps.packages.tasks.auto_download_check",
        "schedule": crontab(hour=3, minute=0),  # 03:00: tải bản mới nhất cho package auto
    },
    "packages-auto-approve": {
        "task": "apps.packages.tasks.auto_approve_pending",
        "schedule": crontab(hour=3, minute=30),  # 03:30: tự duyệt version đã qua cửa sổ chờ
    },
}

# --- Logging ---
# DJANGO_LOG_JSON=true → mỗi dòng 1 object JSON (ELK/Datadog/Loki). Mặc định dùng format
# người-đọc cho dev.
LOG_JSON = env_bool("DJANGO_LOG_JSON", False)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} [{levelname}] {name}: {message}",
            "style": "{",
        },
        "json": {
            "()": "ryandeploy.logformat.JsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_JSON else "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.db.backends": {"level": "WARNING"},
    },
}
