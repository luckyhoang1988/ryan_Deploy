"""Middleware bổ sung cho core app."""
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

ADMIN_LOGIN_PATH = "/admin/login/"

_PERIODS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hour": 3600, "d": 86400, "day": 86400}


def _parse_rate(rate):
    num, period = rate.split("/")
    return int(num), _PERIODS[period]


class AdminLoginRateLimitMiddleware:
    """Rate-limit POST vào trang login của Django admin theo IP nguồn.

    django.contrib.admin không đi qua DRF nên không được LoginThrottle
    (apps.core.views.LoginThrottle) bảo vệ như login SPA — /admin/ vẫn là
    nơi các tài khoản superuser/staff đăng nhập nên cần chặn brute-force
    tương tự. Dùng chung rate "login" khai báo trong DEFAULT_THROTTLE_RATES
    để không lệch cấu hình giữa hai đường login.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]
        self.num_requests, self.duration = _parse_rate(rate)

    def __call__(self, request):
        if request.method == "POST" and request.path == ADMIN_LOGIN_PATH:
            ident = request.META.get("REMOTE_ADDR", "unknown")
            cache_key = f"admin_login_throttle_{ident}"
            now = time.time()
            history = [t for t in cache.get(cache_key, []) if t > now - self.duration]
            if len(history) >= self.num_requests:
                return HttpResponse(
                    "Quá nhiều lần đăng nhập, vui lòng thử lại sau.",
                    status=429,
                    content_type="text/plain; charset=utf-8",
                )
            history.append(now)
            cache.set(cache_key, history, self.duration)
        return self.get_response(request)
