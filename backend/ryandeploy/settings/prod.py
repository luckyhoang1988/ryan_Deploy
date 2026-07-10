"""Production settings."""
from .base import *  # noqa: F401,F403

DEBUG = False

# Bắt buộc có SECRET_KEY và VAULT_KEY thật ở prod
if SECRET_KEY == "insecure-dev-key-change-me":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY phải được đặt ở môi trường production.")
if not RYANDEPLOY["VAULT_KEY"]:  # noqa: F405
    raise RuntimeError("RYANDEPLOY_VAULT_KEY phải được đặt để mã hóa credential ở production.")

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CORS_ALLOW_ALL_ORIGINS = False

# Django 4+ kiểm tra Origin của POST qua HTTPS với CSRF_TRUSTED_ORIGINS (cần cả scheme).
# Mặc định suy ra từ ALLOWED_HOSTS; override bằng env DJANGO_CSRF_TRUSTED_ORIGINS (phân tách bằng dấu phẩy).
_csrf_origins = env("DJANGO_CSRF_TRUSTED_ORIGINS", "")  # noqa: F405
if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{h}"
        for h in ALLOWED_HOSTS  # noqa: F405
        if h not in ("*", "localhost", "127.0.0.1")
    ]
