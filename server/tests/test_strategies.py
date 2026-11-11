from app.strategies.factory import create_strategy
from app.strategies.fifo import FIFOStrategy
from app.strategies.lfu import LFUStrategy
from app.strategies.lru import LRUStrategy

def test_lru_eviction():
    cache = LRUStrategy(capacity=2)

    cache.put("A", "1")
    cache.put("B", "2")

    assert cache.get("A") == "1"

    cache.put("C", "3")

    assert cache.get("B") is None
    assert cache.get("A") == "1"
    assert cache.get("C") == "3"


def test_lfu_eviction():
    cache = LFUStrategy(capacity=2)

    cache.put("A", "1")
    cache.put("B", "2")

    cache.get("A")
    cache.get("A")

    cache.put("C", "3")

    assert cache.get("B") is None
    assert cache.get("A") == "1"
    assert cache.get("C") == "3"

def test_fifo_eviction():
    cache = FIFOStrategy(capacity=2)

    cache.put("A", "1")
    cache.put("B", "2")

    cache.get("A")

    cache.put("C", "3")

    assert cache.get("A") is None
    assert cache.get("B") == "2"
    assert cache.get("C") == "3"

def test_hit_rate():
    cache = LRUStrategy(capacity=2)
    
    cache.put("A", "1")

    cache.get("A")
    cache.get("B")

    metrics = cache.get_metrics()

    assert metrics.hits == 1
    assert metrics.misses == 1
    assert metrics.hit_rate == 0.5
    assert metrics.miss_rate == 0.5

def test_strategy_factory():
    assert isinstance(
        create_strategy("lru", 10),
        LRUStrategy,
    )
    
    assert isinstance(
        create_strategy("lfu", 10),
        LFUStrategy,
    )
    
    assert isinstance(
        create_strategy("fifo", 10),
        FIFOStrategy,
    )

def test_strategy_factory_is_case_insensitive():
    assert isinstance(
        create_strategy("LRU", 10),
        LRUStrategy,
    )

def test_strategy_factory_reject_unknown_strategy():
    try:
        create_strategy("unkmown", 10)
        assert False
    except ValueError:
        pass
    
def test_lru_byte_capacity_eviction():
    cache = LRUStrategy(capacity=10, size_of=int)

    cache.put("A", "4")
    cache.put("B", "4")

    cache.get("A")

    evicted = cache.put_with_evictions("C", "4")

    assert evicted == ["B"]
    assert cache.contains("A")
    assert cache.contains("C")
    assert not cache.contains("B")
    assert cache.used_capacity == 8
    

def test_lru_byte_capacity_update():
    cache = LRUStrategy(capacity=10, size_of=int)

    cache.put("A", "4")
    cache.put("B", "4")

    evicted = cache.put_with_evictions("A", "8")

    assert evicted == ["B"]
    assert cache.contains("A")
    assert not cache.contains("B")
    assert cache.used_capacity == 8


def test_lru_rejects_oversized_object():
    cache = LRUStrategy(capacity=10, size_of=int)

    cache.put("A", "4")

    evicted = cache.put_with_evictions("B", "20")

    assert evicted == []
    assert cache.contains("A")
    assert not cache.contains("B")
    assert cache.used_capacity == 4
