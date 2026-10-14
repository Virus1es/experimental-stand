from fnmatch import fnmatch

import pytest

from app.services.redis_cache_service import RedisCacheService


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    def ping(self):
        return True

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, **kwargs):
        self.data[key] = str(value)
        return True

    def delete(self, *keys):
        removed = 0

        for key in keys:
            if key in self.data:
                del self.data[key]
                removed += 1

        return removed

    def scan_iter(self, match="*"):
        return iter([
            key
            for key in list(self.data)
            if fnmatch(key, match)
        ])


@pytest.fixture
def fake_redis():
    return FakeRedis()


def test_put_and_get(fake_redis):
    cache = RedisCacheService(
        namespace="test",
        client=fake_redis,
    )

    assert cache.get("A") is None

    cache.put("A", "value-A")

    assert cache.get("A") == "value-A"

    metrics = cache.get_metrics()

    assert metrics.hits == 1
    assert metrics.misses == 1


def test_remove(fake_redis):
    cache = RedisCacheService(
        namespace="test",
        client=fake_redis,
    )

    cache.put("A", "value-A")
    cache.remove("A")

    assert cache.get("A") is None


def test_clear_only_removes_own_namespace(fake_redis):
    first = RedisCacheService(
        namespace="first",
        client=fake_redis,
    )
    second = RedisCacheService(
        namespace="second",
        client=fake_redis,
    )

    first.put("A", "one")
    second.put("A", "two")

    first.clear()

    assert first.get("A") is None
    assert second.get("A") == "two"


def test_size(fake_redis):
    cache = RedisCacheService(
        namespace="test",
        client=fake_redis,
    )

    cache.put("A", "1")
    cache.put("B", "2")

    assert cache.size() == 2


def test_invalid_configuration(fake_redis):
    with pytest.raises(ValueError):
        RedisCacheService(
            namespace=" ",
            client=fake_redis,
        )

    with pytest.raises(ValueError):
        RedisCacheService(
            namespace="test",
            ttl_seconds=0,
            client=fake_redis,
        )