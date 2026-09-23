from collections import OrderedDict

from app.strategies.base import CacheStrategy

class FIFOStrategy(CacheStrategy):

    def __init__(self, capacity: int):
        super().__init__(capacity)

        self._cache: OrderedDict[str, str] = OrderedDict()

    def get(self, key: str) -> str | None:
        if key not in self._cache:
            self.metrics.misses += 1
            return None

        self.metrics.hits += 1

        return self._cache[key]

    def put(self, key: str, value: str) -> None:
        if key in self._cache:
            self._cache[key] = value
            return

        if len(self._cache) >= self.capacity:
            self._cache.popitem(last=False)

        self._cache[key] = value

    def remove(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)