from collections import Counter

from app.strategies.base import CacheStrategy

class LFUStrategy(CacheStrategy):

    def __init__(self, capacity: int):
        super().__init__(capacity)

        self._cache: dict[str, str] = {}
        self._frequency: Counter[str] = Counter()

    def get(self, key: str) -> str | None:
        if key not in self._cache:
            self.metrics.misses += 1
            return None

        self._frequency[key] += 1
        self.metrics.hits += 1

        return self._cache[key]

    def put(self, key: str, value: str) -> None:
        if key in self._cache:
            self._cache[key] = value
            return

        if len(self._cache) >= self.capacity:
            least_frequency_key = min(
                self._cache,
                key=lambda item: self._frequency[item]
            )

            self.remove(least_frequency_key)

        self._cache[key] = value
        self._frequency[key] = 0

    def remove(self, key: str) -> None:
        self._cache.pop(key, None)
        self._frequency.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()
        self._frequency.clear()

    def __len__(self) -> int:
        return len(self._cache)