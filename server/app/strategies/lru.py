from collections import OrderedDict
from collections.abc import Callable

from app.strategies.base import CacheStrategy

class LRUStrategy(CacheStrategy):

    def __init__(
        self, 
        capacity: int, 
        *, 
        size_of: Callable[[str], int] | None = None
    ) -> None:
        super().__init__(capacity)

        self._cache: OrderedDict[str, str] = OrderedDict()
        self._size_of = size_of or (lambda value: 1)
        self._used_capacity = 0
        
    @property
    def used_capacity(self) -> int:
        return self._used_capacity

    def get(self, key: str) -> str | None:
        if key not in self._cache:
            self.metrics.misses += 1
            return None

        self._cache.move_to_end(key)

        self.metrics.hits += 1

        return self._cache[key]

    def put(self, key: str, value: str) -> None:
       self.put_with_evictions(key, value)

    def put_with_evictions(
        self,
        key: str,
        value: str,
    ) -> list[str]:
        new_size = self._size_of(value)
        
        if new_size <= 0:
            raise ValueError("Value size must be positive")
        
        existed = key in self._cache
        
        if existed:
            old_value = self._cache.pop(key)
            self._used_capacity -= self._size_of(old_value)
        
        if new_size > self.capacity:
            return [key] if existed else []
        
        self._cache[key] = value
        self._used_capacity += new_size
        
        evicted: list[str] = []
        
        while self._used_capacity > self.capacity:
            old_key, old_value = self._cache.popitem(last=False)
            self._used_capacity -= self._size_of(old_value)
            evicted.append(old_key)
        
        return evicted

    def remove(self, key: str) -> None:
        value = self._cache.pop(key, None)
        
        if value is not None:
            self._used_capacity -= self._size_of(value)

    def clear(self) -> None:
        self._cache.clear()
        self._used_capacity = 0
    
    def contains(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)