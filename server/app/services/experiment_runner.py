from collections.abc import Iterable

from app.models.access import ResourseAccess
from app.models.experiment import (
    ExperimentConfig,
    ExperimentResult
)
from app.services.cache_service import CacheService

class ExperimentRunner:
    
    def run(
        self, 
        trace: Iterable[ResourseAccess],
        config: ExperimentConfig,
    ) -> ExperimentResult:
        cache = CacheService(
            strategy=config.strategy,
            capacity=config.capacity
        )
        
        total_latency_ms = 0.0
        
        for access in trace:
            cached_value = cache.get(access.resource_id)
            
            if cached_value is not None:
                total_latency_ms += config.hit_latency_ms
            else:
                total_latency_ms += config.miss_latency_ms
                
                cache.put(
                    key=access.resource_id,
                    value=access.resource_id,
                )
        
        metrics = cache.get_metrics()
        
        total_requests = metrics.total_requests
        
        average_latency_ms = (
            total_latency_ms / total_requests
            if total_requests > 0
            else 0.0
        )
        
        return ExperimentResult(
            strategy=config.strategy.lower(),
            capacity=config.capacity,
            total_requests=total_requests,
            hits=metrics.hits,
            misses=metrics.misses,
            hit_rate=metrics.hit_rate,
            miss_rate=metrics.miss_rate,
            total_latency_ms=total_latency_ms,
            average_latency_ms=average_latency_ms
        )
    
    def compare(
        self, 
        trace: Iterable[ResourseAccess],
        configs: Iterable[ExperimentConfig],
    ) -> list[ExperimentResult]:
        requests = list(trace)
        
        return [
            self.run(requests, config)
            for config in configs
        ]
        
