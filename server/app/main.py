import httpx

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.resources import router as resources_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=5.0) as client:
        app.state.origin_client = client
        yield

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