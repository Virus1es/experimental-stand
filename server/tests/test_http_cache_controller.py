
import asyncio

import httpx

from app.services.http_cache_controller import HttpCacheController


class FakeRedis:
    def __init__(self):
        self.data: dict[str, bytes] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value: bytes):
        self.data[key] = value

    async def delete(self, key: str):
        self.data.pop(key, None)


def create_origin(calls: list[int], payload_size: int = 20):
    def handler(request: httpx.Request):
        resource_id = int(request.url.path.split("/")[-1])

        calls.append(resource_id)

        return httpx.Response(
            status_code=200,
            json={
                "resource_id": resource_id,
                "payload": "x" * payload_size,
            },
        )

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )


def test_http_cache_miss_then_hit():
    async def scenario():
        redis = FakeRedis()
        origin_calls = []

        async with create_origin(origin_calls) as origin:
            controller = HttpCacheController(
                redis_client=redis,
                origin_client=origin,
                capacity_bytes=1000,
                origin_url="http://origin:8001",
            )

            first = await controller.get_resource(42)
            second = await controller.get_resource(42)

            assert first == second

            assert controller.misses == 1
            assert controller.hits == 1
            assert controller.origin_requests == 1

            assert origin_calls == [42]
            assert "resource:42" in redis.data

    asyncio.run(scenario())


def test_http_cache_lru_eviction():
    async def scenario():
        redis = FakeRedis()
        origin_calls = []

        sample = httpx.Response(
            200,
            json={"resource_id": 1, "payload": "x" * 20},
        )
        object_size = len(sample.content)

        async with create_origin(origin_calls) as origin:
            controller = HttpCacheController(
                redis_client=redis,
                origin_client=origin,
                capacity_bytes=2 * object_size,
                origin_url="http://origin:8001",
            )

            await controller.get_resource(1)
            await controller.get_resource(2)
            await controller.get_resource(1)
            await controller.get_resource(3)

            assert "resource:1" in redis.data
            assert "resource:2" not in redis.data
            assert "resource:3" in redis.data

            assert controller.hits == 1
            assert controller.misses == 3
            assert controller.origin_requests == 3

    asyncio.run(scenario())


def test_http_cache_oversized_resource():
    async def scenario():
        redis = FakeRedis()
        origin_calls = []

        async with create_origin(origin_calls) as origin:
            controller = HttpCacheController(
                redis_client=redis,
                origin_client=origin,
                capacity_bytes=10,
                origin_url="http://origin:8001",
            )

            first = await controller.get_resource(42)
            second = await controller.get_resource(42)

            assert first == second
            assert redis.data == {}

            assert controller.hits == 0
            assert controller.misses == 2
            assert controller.origin_requests == 2

            assert origin_calls == [42, 42]

    asyncio.run(scenario())

def test_concurrent_requests_load_resource_once():
    async def scenario():
        redis = FakeRedis()
        origin_calls: list[int] = []

        async def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            resource_id = int(request.url.path.split("/")[-1])
            origin_calls.append(resource_id)

            # Имитируем задержку источника,
            # чтобы запросы выполнялись конкурентно.
            await asyncio.sleep(0.05)

            return httpx.Response(
                status_code=200,
                json={
                    "resource_id": resource_id,
                    "payload": "x" * 20,
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as origin:
            controller = HttpCacheController(
                redis_client=redis,
                origin_client=origin,
                capacity_bytes=1000,
                origin_url="http://origin:8001",
            )

            # Десять конкурентных запросов одного ресурса.
            results = await asyncio.gather(
                *(
                    controller.get_resource(42)
                    for _ in range(10)
                )
            )

            assert len(results) == 10
            assert all(result == results[0] for result in results)

            assert origin_calls == [42]
            assert controller.origin_requests == 1
            assert controller.misses == 1
            assert controller.hits == 9

            assert "resource:42" in redis.data

    asyncio.run(scenario())

def test_prefetch_resource_then_client_hit():
    async def scenario():
        redis = FakeRedis()
        origin_calls: list[int] = []

        async def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            resource_id = int(
                request.url.path.split("/")[-1]
            )

            origin_calls.append(resource_id)

            return httpx.Response(
                status_code=200,
                json={
                    "resource_id": resource_id,
                    "payload": "x" * 20,
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as origin:
            controller = HttpCacheController(
                redis_client=redis,
                origin_client=origin,
                capacity_bytes=1000,
                origin_url="http://origin:8001",
            )

            # Шаг 1. Загружаем ресурс заранее.
            loaded = await controller.prefetch_resource(42)

            assert loaded is True
            assert controller.prefetch_requests == 1

            # Предзагрузка не считается пользовательским запросом.
            assert controller.hits == 0
            assert controller.misses == 0

            # Шаг 2. Пользователь запрашивает ресурс.
            result = await controller.get_resource(42)

            assert result["resource_id"] == 42

            # Ответ получен из кэша.
            assert controller.hits == 1
            assert controller.misses == 0
            assert controller.prefetch_hits == 1

            # Источник был вызван только один раз.
            assert controller.origin_requests == 1
            assert origin_calls == [42]

            # Шаг 3. Повторный запрос.
            await controller.get_resource(42)

            assert controller.hits == 2

            # Один объект не должен давать два prefetch hit.
            assert controller.prefetch_hits == 1

    asyncio.run(scenario())


def test_concurrent_prefetch_loads_resource_once():
    async def scenario():
        redis = FakeRedis()
        origin_calls: list[int] = []

        async def handler(
            request: httpx.Request,
        ) -> httpx.Response:
            resource_id = int(
                request.url.path.split("/")[-1]
            )

            origin_calls.append(resource_id)

            # Имитируем задержку HTTP-источника.
            await asyncio.sleep(0.05)

            return httpx.Response(
                status_code=200,
                json={
                    "resource_id": resource_id,
                    "payload": "x" * 20,
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as origin:
            controller = HttpCacheController(
                redis_client=redis,
                origin_client=origin,
                capacity_bytes=1000,
                origin_url="http://origin:8001",
            )

            results = await asyncio.gather(
                *(
                    controller.prefetch_resource(42)
                    for _ in range(5)
                )
            )

            # Только одна предзагрузка должна
            # действительно сохранить объект.
            assert results.count(True) == 1
            assert results.count(False) == 4

            # Остальные запросы не обращаются к источнику.
            assert origin_calls == [42]

            assert controller.prefetch_requests == 1
            assert controller.prefetch_skipped == 4
            assert controller.origin_requests == 1

            # Предзагрузка не влияет на пользовательские
            # попадания и промахи.
            assert controller.hits == 0
            assert controller.misses == 0

            # Первый пользовательский запрос получает
            # уже предзагруженный ресурс.
            await controller.get_resource(42)

            assert controller.hits == 1
            assert controller.prefetch_hits == 1

    asyncio.run(scenario())
