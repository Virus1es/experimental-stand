from redis.asyncio import Redis

class RedisCacheStorage:
    def __init__(self, client: Redis) -> None:
        self._client = client
    
    async def get(self, key: str, /) -> bytes | str | None:
        return await self._client.get(key)
    
    async def set(self, key: str, value: bytes, /) -> None:
        await self._client.set(key, value)
        
    async def delete(self, key: str, /) -> None:
        await self._client.delete(key)