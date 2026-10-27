from collections.abc import Sequence
from typing import Protocol 

from app.models.access import ResourseAccess
from app.models.experiment import (
    ExperimentConfig,
    ExperimentResult,
    RequestResult
)
from app.models.prediction import ResourcePrediction
from app.models.prefetch_experiment import (
    PrefetchExpermintResult,
    PrefetchMetrics
)
from app.services.cache_service import CacheService
from app.services.prefetch_service import PrefetchService

class NextResourcePredictor(Protocol):
    """Интерфейс модели для нового экспериментального runner."""
    
    history_size: int
    
    def fit(self, trace: Sequence[ResourseAccess]) -> "NextResourcePredictor":
        ...
    
    def predict_next(self, history: Sequence[str], top_k: int = 3) -> list[ResourcePrediction]:
        ...

class PrefetchExperimentRunner:
    def run(
        self,
        train_trace: Sequence[ResourseAccess],
        test_trace: Sequence[ResourseAccess],
        config: ExperimentConfig,
        predictor: NextResourcePredictor,
        probability_threshold: float = 0.2,
        max_prefetch: int = 3,
    ) -> PrefetchExpermintResult:
        if not train_trace:
            raise ValueError("Training trace cannot be empty")
        
        if predictor.history_size <= 0:
            raise ValueError("Predictor history_size must be positive")
        
        if len(train_trace) <= predictor.history_size:
            raise ValueError("Training trace must be longer than history_size")
        
        if not 0 <= probability_threshold <= 1:
            raise ValueError("Probability threshold must be between 0 and 1")
        
        predictor.fit(train_trace)
        
        cache = CacheService(
            strategy=config.strategy,
            capacity=config.capacity,
        )
        
        history = [
            access.resource_id
            for access in train_trace[-predictor.history_size:]
        ]
        
        known_sizes = {
            access.resource_id: access.size_bytes
            for access in train_trace
        }
        
        pending_prefetches: set[str] = set()
        
        prefetch_count = 0
        prefetch_hits = 0
        prefetch_wasted_evictions = 0
        prefetch_origin_bytes = 0
        
        demand_origin_requests = 0
        demand_origin_bytes = 0
        client_bytes = 0
        total_latency_ms = 0.0
        
        request_results: list[RequestResult] = []
        
        def fetch_resource(resource_id: str) -> str:
            """Имитирует загрузку для предзаполнения кэша."""
            
            nonlocal prefetch_count
            nonlocal prefetch_origin_bytes
            
            prefetch_count += 1
            prefetch_origin_bytes += known_sizes[resource_id]
            
            return resource_id
        
        prefetch_service = PrefetchService(
            cache=cache,
            fetch_resource=fetch_resource,
            probability_threshold=probability_threshold,
            max_prefetch=max_prefetch,
        )
        
        def account_evictions() -> None:
            """Находит неиспользованные предзагрузки, вытеснение из кэша."""
            nonlocal prefetch_wasted_evictions
            
            evicted = {
                resource_id
                for resource_id in pending_prefetches
                if not cache.contains(resource_id)
            }
            
            prefetch_wasted_evictions += len(evicted)
            pending_prefetches.difference_update(evicted)
        
        for access in test_trace:
            resource_id = access.resource_id
            known_sizes[resource_id] = access.size_bytes
            
            cached_value = cache.get(resource_id)
            cache_hit = cached_value is not None
            
            client_bytes += access.size_bytes
            
            if cache_hit:
                latency_ms = config.hit_latency_ms
                if resource_id in pending_prefetches:
                    prefetch_hits += 1
                    pending_prefetches.remove(resource_id)
                
                origin_request = False
                request_origin_bytes = 0
            
            else:
                latency_ms = config.miss_latency_ms
                
                demand_origin_requests += 1
                demand_origin_bytes += access.size_bytes
                
                origin_request = True
                request_origin_bytes = access.size_bytes
                
                cache.put(
                    key=resource_id,
                    value=resource_id
                )
                
                account_evictions()
            
            total_latency_ms += latency_ms
            
            request_results.append(
                RequestResult(
                    timestamp_ms=access.timestamp_ms,
                    resource_id=resource_id,
                    size_bytes=access.size_bytes,
                    cache_hit=cache_hit,
                    latency_ms=latency_ms,
                    origin_request=origin_request,
                    origin_bytes=request_origin_bytes,
                    cache_size=cache.size(),
                )
            )
            
            history.append(resource_id)
            history = history[-predictor.history_size:]
            
            predictions = predictor.predict_next(
                history,
                top_k=max_prefetch,
            )
            
            available_predictions = [
                prediction
                for prediction in predictions
                if prediction.resource_id in known_sizes
            ]
            
            loaded = prefetch_service.prefetch(
                available_predictions
            )
            
            account_evictions()
            
            pending_prefetches.update(loaded)
            
        metrics = cache.get_metrics()
        total_requests = metrics.total_requests
        
        average_latency_ms = (
            total_latency_ms / total_requests
            if total_requests
            else 0.0
        )
        
        total_origin_requests = demand_origin_requests + prefetch_count
        
        total_origin_bytes = demand_origin_bytes + prefetch_origin_bytes
        
        experiment_result = ExperimentResult(
            strategy=config.strategy,
            capacity=config.capacity,
            total_requests=total_requests,
            hits=metrics.hits,
            misses=metrics.misses,
            hit_rate=metrics.hit_rate,
            miss_rate=metrics.miss_rate,
            total_latency_ms=total_latency_ms,
            average_latency_ms=average_latency_ms,
            origin_requests=total_origin_requests,
            client_bytes=client_bytes,
            origin_bytes=total_origin_bytes,
            requests=request_results,
        )
        
        prefetch_metrics = PrefetchMetrics(
            prefetch_count=prefetch_count,
            prefetch_hits=prefetch_hits,
            prefetch_wasted_evictions=prefetch_wasted_evictions,
            prefetch_unused_at_end=len(pending_prefetches),
            prefetch_origin_bytes=prefetch_origin_bytes
        )
        
        return PrefetchExpermintResult(
            experiment=experiment_result,
            prefetch=prefetch_metrics,
        )