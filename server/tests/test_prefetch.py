import pytest

from app.models.prediction import ResourcePrediction
from app.services.cache_service import CacheService
from app.services.prefetch_service import PrefetchService


def test_prefetch_loads_predicted_resources():
    cache = CacheService("lru", capacity=5)

    service = PrefetchService(
        cache=cache,
        fetch_resource=lambda key: f"value:{key}",
        probability_threshold=0.2,
        max_prefetch=2,
    )

    loaded = service.prefetch([
        ResourcePrediction("A", 0.7),
        ResourcePrediction("B", 0.2),
        ResourcePrediction("C", 0.1),
    ])

    assert loaded == ["A", "B"]
    assert cache.size() == 2

    assert cache.get("A") == "value:A"
    assert cache.get_metrics().hits == 1


def test_prefetch_does_not_change_cache_metrics():
    cache = CacheService("lru", capacity=5)

    service = PrefetchService(
        cache=cache,
        fetch_resource=lambda key: key,
    )

    service.prefetch([
        ResourcePrediction("A", 0.8),
    ])

    metrics = cache.get_metrics()

    assert metrics.hits == 0
    assert metrics.misses == 0


def test_prefetch_skips_cached_resources():
    cache = CacheService("lru", capacity=5)
    cache.put("A", "existing")

    fetched = []

    def fetch(key: str) -> str:
        fetched.append(key)
        return key

    service = PrefetchService(
        cache=cache,
        fetch_resource=fetch,
    )

    loaded = service.prefetch([
        ResourcePrediction("A", 0.9),
        ResourcePrediction("B", 0.8),
    ])

    assert loaded == ["B"]
    assert fetched == ["B"]


def test_prefetch_respects_limit():
    cache = CacheService("fifo", capacity=5)

    service = PrefetchService(
        cache=cache,
        fetch_resource=lambda key: key,
        max_prefetch=1,
        probability_threshold=0.0,
    )

    loaded = service.prefetch([
        ResourcePrediction("A", 0.7),
        ResourcePrediction("B", 0.3),
    ])

    assert loaded == ["A"]
    assert cache.size() == 1


def test_prefetch_rejects_invalid_parameters():
    cache = CacheService("lru", capacity=5)

    with pytest.raises(ValueError):
        PrefetchService(
            cache=cache,
            fetch_resource=lambda key: key,
            probability_threshold=1.5,
        )

    with pytest.raises(ValueError):
        PrefetchService(
            cache=cache,
            fetch_resource=lambda key: key,
            max_prefetch=0,
        )


def test_contains_does_not_change_lru_order():
    cache = CacheService("lru", capacity=2)

    cache.put("A", "A")
    cache.put("B", "B")

    assert cache.contains("A")

    # Если contains не изменил порядок LRU,
    # при добавлении C вытеснится A.
    cache.put("C", "C")

    assert not cache.contains("A")
    assert cache.contains("B")
    assert cache.contains("C")