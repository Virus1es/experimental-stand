import httpx

from fastapi import APIRouter, HTTPException, Path, Request

from app.services.http_cache_controller import HttpCacheController
from app.services.http_prefetch_executor import HttpPrefetchExecutor

router = APIRouter(prefix="/api/resources", tags=["Resources"])

@router.get("/stats")
async def get_cache_stats(request: Request) -> dict[str, int]:
    controller: HttpCacheController = request.app.state.cache_controller
    executor:HttpPrefetchExecutor = request.app.state.prefetch_executor
    
    return {
        "hits": controller.hits,
        "misses": controller.misses,
        "origin_requests": controller.origin_requests,
        "prefetch_requests": controller.prefetch_requests,
        "prefetch_hits": controller.prefetch_hits,
        "prefetch_skipped": controller.prefetch_skipped,
        "dropped_requests": (
            executor.dropped_requests
            if executor is not None else 0
        ),
        "dropped_candidates": (
            executor.dropped_candidates
            if executor is not None else 0
        )
    }

@router.get("/{resource_id}")
async def get_resource(request: Request, resource_id: int = Path(gt=0)) -> dict[str, int | str]:
    controller: HttpCacheController = request.app.state.cache_controller
    
    try:
        result = await controller.get_resource(resource_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Origin service unavailable") from exc
    
    executor = request.app.state.prefetch_executor
    mapper = request.app.state.resource_mapper
    
    if executor is not None and mapper is not None:
        try:
            mapper.original_path(f"/api/resources/{resource_id}")
        except (KeyError, ValueError):
            pass
        else:
            executor.submit(resource_id)
    
    return result
