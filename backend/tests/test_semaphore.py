"""Semaphore concurrency per-deployment (đếm slot trên Redis, fake trong test)."""
import pytest
import redis

from apps.deployments import semaphore


class FakeRedis:
    """Fake tối thiểu: incr/decr/get/expire/delete/eval cho semaphore counter."""

    def __init__(self):
        self.store = {}

    def incr(self, k):
        self.store[k] = self.store.get(k, 0) + 1
        return self.store[k]

    def decr(self, k):
        self.store[k] = self.store.get(k, 0) - 1
        return self.store[k]

    def expire(self, k, ttl):
        return True

    def get(self, k):
        v = self.store.get(k)
        return None if v is None else str(v).encode()

    def delete(self, k):
        self.store.pop(k, None)

    def eval(self, script, numkeys, *keys_and_args):
        # Chỉ mô phỏng _RELEASE_LUA: GET rồi DECR nếu > 0 (atomic trong fake đơn luồng).
        key = keys_and_args[0]
        v = self.store.get(key, 0)
        if v > 0:
            self.store[key] = v - 1
            return self.store[key]
        return 0


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(semaphore, "_client", fake)
    return fake


def test_acquire_up_to_limit_then_blocks(fake_redis):
    dep = 1
    assert semaphore.acquire_slot(dep, limit=2, ttl=60) is True
    assert semaphore.acquire_slot(dep, limit=2, ttl=60) is True
    # slot thứ 3 vượt trần → phải chờ
    assert semaphore.acquire_slot(dep, limit=2, ttl=60) is False


def test_release_frees_a_slot(fake_redis):
    dep = 1
    semaphore.acquire_slot(dep, limit=1, ttl=60)
    assert semaphore.acquire_slot(dep, limit=1, ttl=60) is False
    semaphore.release_slot(dep)
    assert semaphore.acquire_slot(dep, limit=1, ttl=60) is True


def test_release_never_goes_negative(fake_redis):
    dep = 1
    semaphore.release_slot(dep)  # chưa acquire → không được xuống âm
    assert fake_redis.store.get(semaphore._key(dep), 0) == 0


def test_release_uses_atomic_eval(fake_redis, monkeypatch):
    """release_slot phải đi qua eval (Lua) — không còn GET rồi DECR tách rời."""
    calls = []
    orig = fake_redis.eval

    def tracking_eval(script, numkeys, *keys_and_args):
        calls.append((numkeys, keys_and_args[0]))
        return orig(script, numkeys, *keys_and_args)

    monkeypatch.setattr(fake_redis, "eval", tracking_eval)
    semaphore.acquire_slot(1, limit=1, ttl=60)
    semaphore.release_slot(1)
    assert calls == [(1, semaphore._key(1))]
    assert fake_redis.store[semaphore._key(1)] == 0


def test_clear_resets_counter(fake_redis):
    dep = 1
    semaphore.acquire_slot(dep, limit=5, ttl=60)
    semaphore.clear_slots(dep)
    assert semaphore._key(dep) not in fake_redis.store


def test_limit_zero_is_unlimited(fake_redis):
    # max_concurrency <= 0 → không giới hạn
    for _ in range(100):
        assert semaphore.acquire_slot(1, limit=0, ttl=60) is True


def test_acquire_redis_error_fails_closed(fake_redis, monkeypatch):
    # Redis lỗi → từ chối slot (fail-closed), KHÔNG cấp slot mặc định (fail-open cũ).
    def boom(k):
        raise redis.RedisError("connection refused")

    monkeypatch.setattr(fake_redis, "incr", boom)
    assert semaphore.acquire_slot(1, limit=5, ttl=60) is False
