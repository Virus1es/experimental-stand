from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class CacheMetrics:
    hits: int = 0
    misses: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    @property
    def miss_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.misses / self.total_requests

class CacheStrategy(ABC):

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("Cache capacity must be greater than zero")
        self.capacity = capacity
        self.metrics = CacheMetrics()

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Get value from cache."""

    @abstractmethod
    def remove(self, key: str) -> None:
        """Remove value from cache."""

    @abstractmethod
    def clear(self) -> None:
        """Clear cache."""

    @abstractmethod
    def __len__(self) -> int:
        """Return current cache size."""

    def get_metrics(self) -> CacheMetrics:
        return self.metrics
    