from fastapi import FastAPI

from app.api.routes.health import router as health_router

app = FastAPI(
    title="CacheLab API",
    description="Experimental platform for intelligent caching and prefetching methods",
    version="0.1.0",
)

app.include_router(health_router)

@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "CacheLab API",
        "version": "0.1.0",
        "status": "running",
    }