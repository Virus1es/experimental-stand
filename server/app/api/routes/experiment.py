import asyncio

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/experiment", tags=["Experiment"])

@router.post("/wait-idle")
async def wait_idle(request: Request) -> dict:
    executor = request.app.state.prefetch_executor
    
    if executor is None:
        return {
            "status": "idle",
            "prefetch_enabled": False
        }
    
    try:
        await asyncio.wait_for(
            executor.wait_idle(),
            timeout=20.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Prefetch executor did not become idle")
    
    return {
        "status": "idle",
        "prefetch_enabled": True,
    }