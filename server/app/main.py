import httpx
import os

from contextlib import asynccontextmanager
from redis.asyncio import Redis
from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.resources import router as resources_router
from app.services.http_cache_controller import HttpCacheController
from app.services.redis_cache_storage import RedisCacheStorage

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_respones=False
    )
    
    try:
        await redis_client.ping()
        
        async with httpx.AsyncClient(timeout=5.0) as origin_client:
            app.state.origin_client = origin_client
            
            app.state.cache_controller = HttpCacheController(
                redis_client=RedisCacheStorage(redis_client),
                origin_client=origin_client,
                capacity_bytes=int(os.getenv("CACHE_CAPACITY_BYTES", "50000")),
                origin_url=os.getenv(
                    "ORIGIN_URL",
                    "http://origin:8001",
                )
            )
            
            yield
    finally:
        await redis_client.aclose()
    

app = FastAPI(
    title="CacheLab API",
    description="Experimental platform for intelligent caching and prefetching methods",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(health_router)
app.include_router(resources_router)

@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "CacheLab API",
        "version": "0.1.0",
        "status": "running",
    }