import asyncio
import logging

from typing import Protocol

logger = logging.getLogger(__name__)

class PrefetchCoordiantor(Protocol):
    def observe_and_select(self, resource_id: int) -> list[int]:
        ...

class PrefetchCache(Protocol):
    async def prefetch_resource(self, resource_id: int) -> bool:
        ...

class HttpPrefetchExecutor:
    def __init__(
        self,
        coordinator: PrefetchCoordiantor,
        cache: PrefetchCache,
        max_queue_size: int = 256,
        prefetch_workers: int = 2,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        
        if prefetch_workers <= 0:
            raise ValueError("prefetch_workers must be positive")
        
        self._coordinator = coordinator
        self._cache = cache
        self._prefetch_workers = prefetch_workers
        
        self._requests: asyncio.Queue[int] = asyncio.Queue(maxsize=max_queue_size)
        
        self._candidates: asyncio.Queue[int] = asyncio.Queue(maxsize=max_queue_size)
        
        self._pending: set[int] = set()
        self._tasks: list[asyncio.Task[None]] = []
        
        self._running = False
        
        self.dropped_requests = 0
        self.dropped_candidates = 0
        
    def start(self) -> None:
        if self._running:
            raise RuntimeError("Executor is already running")
        
        self._running = True
        
        self._tasks.append(asyncio.create_task(self._prediction_worker()))
        
        for _ in range(self._prefetch_workers):
            self._tasks.append(asyncio.create_task(self._prefetch_worker()))
    
    def submit(self, resource_id: int) -> bool:
        """Добавляет пользовательский запрос без ожидания"""
        
        if not self._running:
            return False
        
        try:
            self._requests.put_nowait(resource_id)
            return True
        
        except asyncio.QueueFull:
            self.dropped_requests += 1
            return False
    
    async def _prediction_worker(self) -> None:
        while True:
            resource_id = await self._requests.get()
            
            try:
                selected = await asyncio.to_thread(
                    self._coordinator.observe_and_select,
                    resource_id,
                )
                
                for predicted_id in selected:
                    if predicted_id in self._pending:
                        continue
                    
                    try:
                        self._candidates.put_nowait(predicted_id)
                    except asyncio.QueueFull:
                        self.dropped_candidates += 1
                    
                    else:
                        self._pending.add(predicted_id)
            except Exception:
                logger.exception("Failed to process ML prediction")
            
            finally:
                self._requests.task_done()
    
    async def _prefetch_worker(self) -> None:
        while True:
            resource_id = await self._candidates.get()
            
            try:
                await self._cache.prefetch_resource(resource_id)
            except Exception:
                logger.exception("Failed to prefetch resource %s", resource_id)
            finally: 
                self._pending.discard(resource_id)
                self._candidates.task_done()
    
    async def stop(self) -> None:
        """Дожидается завершения приянтых заданий"""
        
        if not self._running:
            return
        
        self._running = False
        
        await self._requests.join()
        await self._candidates.join()
        
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()