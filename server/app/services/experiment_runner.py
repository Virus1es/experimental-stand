from collections.abc import Iterable

from app.models.access import ResourseAccess
from app.models.experiment import (
    ExperimentConfig,
    ExperimentResult,
    RequestResult
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
        
        origin_requests = 0
        client_bytes = 0
        origin_bytes = 0
        
        request_results: list[RequestResult] = []
        
        for access in trace:
            cached_value = cache.get(access.resource_id)
            cache_hit = cached_value is not None
            
            client_bytes += access.size_bytes
            
            if cache_hit:
                latency_ms = config.hit_latency_ms
                
                request_origin_bytes = 0
                origin_request = False
            else:
                latency_ms = config.miss_latency_ms
                
                origin_requests += 1
                origin_bytes += access.size_bytes
                
                request_origin_bytes = access.size_bytes
                origin_request = True
                
                cache.put(
                    key=access.resource_id,
                    value=access.resource_id,
                )
        
            total_latency_ms += latency_ms
            
            request_results.append(
                RequestResult(
                    timestamp_ms=access.timestamp_ms,
                    resource_id=access.resource_id,
                    size_bytes=access.size_bytes,
                    cache_hit=cache_hit,
                    latency_ms=latency_ms,
                    origin_request=origin_request,
                    origin_bytes=request_origin_bytes,
                    cache_size=cache.size(),
                )
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
            average_latency_ms=average_latency_ms,
            origin_requests=origin_requests,
            client_bytes=client_bytes,
            origin_bytes=origin_bytes,
            requests=request_results,
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
        
