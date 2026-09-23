from app.strategies.base import CacheStrategy
from app.strategies.fifo import FIFOStrategy
from app.strategies.lru import LRUStrategy
from app.strategies.lfu import LFUStrategy

CACHE_STRATEGIES: dict[str, type[CacheStrategy]] = {
    "lru": LRUStrategy,
    "lfu": LFUStrategy,
    "fifo": FIFOStrategy,
}