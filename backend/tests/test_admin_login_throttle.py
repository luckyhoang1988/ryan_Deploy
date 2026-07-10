from django.core.cache import cache
from django.test import Client


def test_admin_login_rate_limited_after_threshold(db, settings):
    rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]
    limit = int(rate.split("/")[0])
    cache.clear()
    c = Client(REMOTE_ADDR="203.0.113.10")

    for _ in range(limit):
        resp = c.post("/admin/login/", {"username": "nope", "password": "nope"})
        assert resp.status_code != 429

    resp = c.post("/admin/login/", {"username": "nope", "password": "nope"})
    assert resp.status_code == 429


def test_admin_login_throttle_is_per_ip(db, settings):
    rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]
    limit = int(rate.split("/")[0])
    cache.clear()
    attacker = Client(REMOTE_ADDR="203.0.113.20")
    other = Client(REMOTE_ADDR="203.0.113.21")

    for _ in range(limit + 1):
        attacker.post("/admin/login/", {"username": "nope", "password": "nope"})

    resp = other.post("/admin/login/", {"username": "nope", "password": "nope"})
    assert resp.status_code != 429


def test_admin_login_get_not_throttled(db, settings):
    rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]
    limit = int(rate.split("/")[0])
    cache.clear()
    c = Client(REMOTE_ADDR="203.0.113.30")

    for _ in range(limit + 5):
        resp = c.get("/admin/login/")
        assert resp.status_code != 429
