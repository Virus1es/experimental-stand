from collections.abc import Sequence

from app.models.access import ResourseAccess
from app.models.experiment import ExperimentResult
from app.models.prefetch_experiment import PrefetchExpermintResult, PrefetchMetrics

def validate_prefetch_result(
    result: PrefetchExpermintResult,
    test_trace: Sequence[ResourseAccess]
) -> None:
    """Проверяет согласованность результата эксперимента."""
    _validate_user_requests(result.experiment, test_trace)
    _validate_prefetch_accounting(result.prefetch)
    _validate_traffic(result.experiment, result.prefetch, test_trace)
    

def _validate_user_requests(
    experiment: ExperimentResult, 
    test_trace: Sequence[ResourseAccess]
) -> None:
    """Проверяет количество пользовательских запросов."""
    
    expected_request = len(test_trace)
    
    if experiment.total_requests != expected_request:
        raise RuntimeError(
            "User request accounting mismatch: "
            f"expected={expected_request}, "
            f"actual={experiment.total_requests}"
        )
        
    accounted_requests = experiment.hits + experiment.misses
    
    if accounted_requests != experiment.total_requests:
        raise RuntimeError(
            "Cache request accounting mismatch: "
            f"total={experiment.total_requests}, "
            f"hits_and_misses={accounted_requests}"
        )

def _validate_prefetch_accounting(
    prefetch: PrefetchMetrics
) -> None:
    """Проверяет расспределение предзагрузок по исходам."""

    accounted_prefetches = (
        prefetch.prefetch_hits
        + prefetch.prefetch_wasted_evictions
        + prefetch.prefetch_unused_at_end
    )
    
    if accounted_prefetches != prefetch.prefetch_count:
        raise RuntimeError(
            "Prefetch accounting mismatch: "
            f"loaded={prefetch.prefetch_count}, "
            f"accounted={accounted_prefetches}"
        )

def _validate_traffic(
    experiment: ExperimentResult,
    prefetch: PrefetchMetrics,
    test_trace:Sequence[ResourseAccess],
) -> None:
    """Проверяет количество обращений к источнику и объём данных."""
    
    demand_requests_from_log = sum(
                request.origin_request
                for request in experiment.requests
            )
            
    expected_origin_requests = demand_requests_from_log + prefetch.prefetch_count
    
    if experiment.origin_requests != expected_origin_requests:
        raise RuntimeError(
            "Origin request accounting mismatch: "
            f"expected={expected_origin_requests}, "
            f"actual={experiment.origin_requests}"
        )
    
    demand_bytes_from_log = sum(
        request.origin_bytes
        for request in experiment.requests
    )
    
    expected_origin_bytes = demand_bytes_from_log + prefetch.prefetch_origin_bytes
    
    if experiment.origin_bytes != expected_origin_bytes:
        raise RuntimeError(
            "Origin byte accounting mismatch: "
            f"expected={expected_origin_bytes}, "
            f"actual={experiment.origin_bytes}"
        )
        
    expected_client_bytes = sum(
        access.size_bytes
        for access in test_trace
    )
    
    if experiment.client_bytes != expected_client_bytes:
        raise RuntimeError(
            "Client byte accounting mismatch: "
            f"expected={expected_client_bytes}, "
            f"actual={experiment.client_bytes}"
        )