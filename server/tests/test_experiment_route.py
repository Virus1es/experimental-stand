
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.experiment import router


class FakeExecutor:
    def __init__(self) -> None:
        self.wait_calls = 0

    async def wait_idle(self) -> None:
        self.wait_calls += 1


def test_wait_idle_with_prefetch():
    app = FastAPI()
    app.include_router(router)

    executor = FakeExecutor()
    app.state.prefetch_executor = executor

    with TestClient(app) as client:
        response = client.post(
            "/api/experiment/wait-idle"
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "idle",
        "prefetch_enabled": True,
    }

    assert executor.wait_calls == 1


def test_wait_idle_without_prefetch():
    app = FastAPI()
    app.include_router(router)

    app.state.prefetch_executor = None

    with TestClient(app) as client:
        response = client.post(
            "/api/experiment/wait-idle"
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "idle",
        "prefetch_enabled": False,
    }
