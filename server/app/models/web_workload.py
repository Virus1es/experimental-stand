from dataclasses import dataclass

@dataclass(frozen=True)
class WebWorkloadConfig:
    num_products: int = 100
    num_requests: int = 10_000
    zipf_alpha: float = 1.2
    seed: int = 42
    request_interval_ms: int = 100
    session_gap_ms: int = 2_000
    
    def __post_init__(self) -> None:
        if self.num_products <= 0:
            raise ValueError("num_products must be positive")
        
        if self.num_requests <= 0:
            raise ValueError("num_requests must be positive")
        
        if self.zipf_alpha < 0:
            raise ValueError("zipf_alpha cannot be negative")
        
        if self.request_interval_ms < 0:
            raise ValueError("request_interval_ms cannot be negative")
        
        if self.session_gap_ms < 0:
            raise ValueError("session_gap_ms cannot be negative")
            