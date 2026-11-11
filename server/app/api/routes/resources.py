import os
import httpx

from fastapi import APIRouter, HTTPException, Path, Request

router = APIRouter(prefix="/api/resources", tags=["Resources"])

ORIGIN_URL = os.getenv("ORIGIN_URL", "http://origin:8001").rstrip("/")

@router.get("/{resource_id}")
async def get_resource(request: Request, resource_id: int = Path(gt=0)) -> dict[str, int | str]:
    client: httpx.AsyncClient = request.app.state.origin_client
    
    try:
        response = await client.get(f"{ORIGIN_URL}/resources/{resource_id}")
        response.raise_for_status()
        
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Origin service unavailable") from exc
