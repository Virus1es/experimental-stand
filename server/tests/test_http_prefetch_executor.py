import asyncio

from app.services.http_prefetch_executor import (
    HttpPrefetchExecutor,
)


class FakeCoordinator:
    def __init__(self) -> None:
        self.observed: list[int] = []

    def observe_and_select(
        self,
        resource_id: int,
    ) -> list[int]:
        self.observed.append(resource_id)
        return [42]


class FakePrefetchCache:
    def __init__(self) -> None:
        self.loaded: list[int] = []

        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def prefetch_resource(
        self,
        resource_id: int,
    ) -> bool:
        self.loaded.append(resource_id)

        self.started.set()

        # Блокируем завершение предзагрузки,
        # чтобы проверить фоновое выполнение.
        await self.release.wait()

        return True


def test_prefetch_executor_runs_in_background():
    async def scenario():
        coordinator = FakeCoordinator()
        cache = FakePrefetchCache()

        executor = HttpPrefetchExecutor(
            coordinator=coordinator,
            cache=cache,
            prefetch_workers=2,
        )

        executor.start()

        # Запрос принят без ожидания HTTP-загрузки.
        accepted = executor.submit(10)

        assert accepted is True

        # Дожидаемся начала предзагрузки,
        # но пока не разрешаем ей завершиться.
        await asyncio.wait_for(
            cache.started.wait(),
            timeout=2,
        )

        assert coordinator.observed == [10]
        assert cache.loaded == [42]

        # Только теперь разрешаем завершить загрузку.
        cache.release.set()

        await asyncio.wait_for(
            executor.stop(),
            timeout=2,
        )

        # После остановки новые запросы не принимаются.
        assert executor.submit(11) is False

        assert executor.dropped_requests == 0
        assert executor.dropped_candidates == 0

    asyncio.run(scenario())
