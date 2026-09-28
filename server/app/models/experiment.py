from dataclasses import dataclass, field

@dataclass(frozen=True)
class ExperimentConfig:
    strategy: str
    capacity: int
    
    hit_latency_ms: float = 2.0
    
    miss_latency_ms: float = 100.0
    
    def __post_init__(self) -> None:
        if not self.strategy:
            raise ValueError("Strategy cannot be empty")
        if self.capacity <= 0:
            raise ValueError("Cache capacity must be positive")
        if self.hit_latency_ms < 0:
            raise ValueError("Hit latency cannot be negative")
        if self.miss_latency_ms < 0:
            raise ValueError("Miss latency cannot be negative")

@dataclass(frozen=True)
class RequestResult:
    timestamp_ms: int
    resource_id: str
    size_bytes: int
    
    cache_hit: bool
    latency_ms: float
    
    origin_request: bool
    origin_bytes: int
    
    cache_size: int  

@dataclass(frozen=True)
class ExperimentResult:
    strategy: str
    capacity: int
    
    total_requests: int
    hits: int
    misses: int
    
    hit_rate: float
    miss_rate: float
    
    total_latency_ms: float
    average_latency_ms: float
    
    origin_requests: int = 0
    client_bytes: int = 0
    origin_bytes: int = 0
    
    requests: list[RequestResult] = field(default_factory=list)