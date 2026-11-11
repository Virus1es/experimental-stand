import os
import httpx

from fastapi import APIRouter, HTTPException, Path, Request

from app.services.http_cache_controller import HttpCacheController

router = APIRouter(prefix="/api/resources", tags=["Resources"])

@router.get("/stats")
async def get_cache_stats(request: Request) -> dict[str, int]:
    controller: HttpCacheController = request.app.state.cache_controller
    
    return {
        "hits": controller.hits,
        "misses": controller.misses,
        "origin_requests": controller.origin_requests
    }

@router.get("/{resource_id}")
async def get_resource(request: Request, resource_id: int = Path(gt=0)) -> dict[str, int | str]:
    controller: HttpCacheController = request.app.state.cache_controller
    
    try:
        return await controller.get_resource(resource_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Origin service unavailable") from exc
