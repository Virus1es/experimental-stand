import asyncio
import os

from fastapi import FastAPI, Path

app = FastAPI(title="CacheLab Origin")

ORIGIN_DELAY_MS = int(os.getenv("ORIGIN_DELAY_MS", "50"))
RESOURCE_SIZES = (1024, 4096, 16384)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/resources/{resource_id}")
async def get_resource(resource_id: int = Path(gt=0)) -> dict[str, int | str]:
    await asyncio.sleep(ORIGIN_DELAY_MS / 1000)
    
    size = RESOURCE_SIZES[
        (resource_id - 1) % len(RESOURCE_SIZES)
    ]
    
    return {
        "resource_id": resource_id,
        "payload": "x" * size,
    }
