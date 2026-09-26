import random

from app.models.access import ResourseAccess

class TraceGenerator:
    def __init__(self, num_resources: int, zipf_alpha: float = 1.0, seed: int = 42):
        if num_resources <= 0:
            raise ValueError("Number of resources must be positive")
        
        if zipf_alpha < 0:
            raise ValueError("Zipf alpha cannot be negative")
        
        self._rng = random.Random(seed)
        
        self._resources = [
            f"/api/resources/{i}"
            for i in range(1, num_resources + 1)
        ]
        
        self._weights = [
            1.0 / (rank ** zipf_alpha)
            for rank in range(1, num_resources + 1)
        ]
        
        self._sizes = {
            resource: self._rng.randint(1024, 1024 * 100)
            for resource in self._resources
        }
    
    def generate(
        self, 
        num_requests: int, 
        interval_ms: int = 100
    ) ->  list[ResourseAccess]:
        if num_requests < 0:
            raise ValueError("Number of requests cannot be negative")
        if interval_ms < 0:
            raise ValueError("Interval cannot be negative")
        
        selected = self._rng.choices(
            population=self._resources,
            weights=self._weights,
            k=num_requests,
        )
        
        return [
            ResourseAccess(
                timestamp_ms=index * interval_ms,
                resource_id=resource,
                size_bytes=self._sizes[resource],
            )
            for index, resource in enumerate(selected)
        ]