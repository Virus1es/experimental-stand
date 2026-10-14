from typing import Any, cast

from app.core.redis_client import get_redis_client
from app.strategies.base import CacheMetrics

class RedisCacheService:
    def __init__(
        self,
        namespace: str = "cachelab",
        ttl_seconds: int | None = None,
        client: Any | None = None,
    ) -> None:
        if not namespace.strip():
            raise ValueError("Namespace cannot be empty")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("TTL must be positive")
        
        self._prefix = f"{namespace.rstrip(':')}:"
        self._ttl_seconds = ttl_seconds
        self._client = (
            client if client is not None
            else get_redis_client()
        )
        self._metrics = CacheMetrics()
        
    def _make_key(self, key: str) -> str:
        if not key:
            raise ValueError("Cache key cannot be empty")
        
        return f"{self._prefix}{key}"
    
    def get(self, key: str) -> str | None:
        value = cast(
            str | None,
            self._client.get(self._make_key(key))
        )
        
        if value is None:
            self._metrics.misses += 1
        else:
            self._metrics.hits += 1
        
        return value
    
    def put(self, key: str, value: str) -> None:
        options = {}
        
        if self._ttl_seconds is not None:
            options["ex"] = self._ttl_seconds
        
        self._client.set(
            self._make_key(key),
            value,
            **options,
        )
    
    def remove(self, key: str) -> None:
        self._client.delete(self._make_key(key))
    
    def clear(self) -> None:
        for key in self._client.scan_iter(
            match=f"{self._prefix}*"
        ):
            self._client.delete(key)
    
    def size(self) -> int:
        return sum(
            1
            for _ in self._client.scan_iter(
                match=f"{self._prefix}*"
            )
        )
    
    def get_metrics(self) -> CacheMetrics:
        return self._metrics
    
    def ping(self) -> bool:
        return bool(self._client.ping())
    