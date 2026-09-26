from dataclasses import dataclass

@dataclass(frozen=True)
class ResourseAccess:
    timestamp_ms: int;
    resource_id: str;
    size_bytes: int;
    
    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("Timestamp cannot be negative")
        if not self.resource_id:
            raise ValueError("Resource ID cannot be empty")
        if self.size_bytes <= 0:
            raise ValueError("Resource size must be positive")
