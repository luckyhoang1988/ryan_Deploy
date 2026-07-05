"""Semaphore concurrency per-deployment (đếm slot trên Redis, fake trong test)."""
import pytest
import redis

from apps.deployments import semaphore


class FakeRedis:
    """Fake tối thiểu: incr/decr/get/expire/delete cho semaphore counter."""

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
