from dataclasses import dataclass

from app.models.experiment import ExperimentResult

@dataclass(frozen=True)
class PrefetchMetrics:
    prefetch_count: int
    prefetch_hits: int
    prefetch_wasted_evictions: int
    prefetch_unused_at_end: int
    prefetch_origin_bytes: int
    
    @property
    def prefetch_precision(self) -> float:
        if self.prefetch_count == 0:
            return 0.0
        
        return self.prefetch_hits / self.prefetch_count
    
@dataclass(frozen=True)
class PrefetchExpermintResult():
    experiment: ExperimentResult
    prefetch: PrefetchMetrics
    