import asyncio
import json
import httpx

from app.services.cache_storage import AsyncCacheStorage
from app.strategies.lru import LRUStrategy

class HttpCacheController:
    def __init__(
        self,
        redis_client: AsyncCacheStorage,
        origin_client: httpx.AsyncClient,
        capacity_bytes: int,
        origin_url: str,
    ) -> None:
        if capacity_bytes <= 0:
            raise ValueError("Cache capacity must be positive")
        
        self._redis = redis_client
        self._origin = origin_client
        self._origin_url = origin_url
        
        self._capacity_bytes = capacity_bytes
        self._lru = LRUStrategy(capacity=capacity_bytes, size_of=int)
        
        self._metadata_lock = asyncio.Lock()
        self._key_locks: dict[str, asyncio.Lock] = {}
        
        self.hits = 0
        self.misses = 0
        self.origin_requests = 0
        
        self.prefetch_requests = 0
        self.prefetch_hits = 0
        self.prefetch_skipped = 0
        
        self._prefetch_unused: set[str] = set()
    
    async def get_resource(self, resource_id: int) -> dict:
        key = f"resource:{resource_id}"
        key_lock = self._key_locks.setdefault(key, asyncio.Lock())
        
        async with key_lock:
            async with self._metadata_lock:
                if self._lru.contains(key):
                    cached = await self._redis.get(key)
                    
                    if cached is not None:
                        self._lru.get(key)
                        self.hits += 1
                        
                        if key in self._prefetch_unused:
                            self._prefetch_unused.remove(key)
                            self.prefetch_hits += 1
                        
                        return json.loads(cached)
                    
                    self._lru.remove(key)
                
                self.misses += 1
            
            self.origin_requests += 1
            
            response = await self._origin.get(f"{self._origin_url}/resources/{resource_id}")
            response.raise_for_status()
            
            payload = response.content
            result = response.json()
            
            if len(payload) <= self._capacity_bytes:
                async with self._metadata_lock:
                    await self._redis.set(key, payload)
                    
                    evicted = self._lru.put_with_evictions(key, str(len(payload)))
                    
                    for evicted_key in evicted:
                        await self._redis.delete(evicted_key)
                        self._prefetch_unused.discard(evicted_key)
            
            return result
        
    async def prefetch_resource(self, resource_id: int) -> bool:
        key = f"resource:{resource_id}"
        
        key_lock = self._key_locks.setdefault(key, asyncio.Lock())
        
        async with key_lock:
            async with self._metadata_lock:
                if self._lru.contains(key):
                    cached = await self._redis.get(key)
                    
                    if cached is not None:
                        self.prefetch_skipped += 1
                        return False
                    self._lru.remove(key)
                    self._prefetch_unused.discard(key)
            
            self.origin_requests += 1
            self.prefetch_requests += 1
            
            response = await self._origin.get(f"{self._origin_url}/resources/{resource_id}")
                        
            response.raise_for_status()
            
            payload = response.content
            
            if len(payload) > self._capacity_bytes:
                return False
            
            async with self._metadata_lock:
                await self._redis.set(key, payload)
                
                evicted = self._lru.put_with_evictions(key, str(len(payload)))
                
                for evicted_key in evicted:
                    await self._redis.delete(evicted_key)
                    self._prefetch_unused.discard(evicted_key)
                
                self._prefetch_unused.add(key)
            
            return True
                        