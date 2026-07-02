"""Production settings."""
from .base import *  # noqa: F401,F403

DEBUG = False

# Bắt buộc có SECRET_KEY và VAULT_KEY thật ở prod
if SECRET_KEY == "insecure-dev-key-change-me":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY phải được đặt ở môi trường production.")
if not PYDEPLOY["VAULT_KEY"]:  # noqa: F405
    raise RuntimeError("PYDEPLOY_VAULT_KEY phải được đặt để mã hóa credential ở production.")

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CORS_ALLOW_ALL_ORIGINS = False
