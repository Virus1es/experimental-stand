from collections.abc import Callable, Sequence

from app.models.prediction import ResourcePrediction
from app.services.cache_service import CacheService

class PrefetchService:
    def __init__(
        self,
        cache: CacheService,
        fetch_resource: Callable[[str], str],
        probability_threshold: float = 0.2,
        max_prefetch: int = 3,
    ) -> None:
        if not 0 <= probability_threshold <= 1:
            raise ValueError( "Probability threshold must be between 0 and 1")
        
        if max_prefetch <= 0:
            raise ValueError("max_prefetch must be positive")
        
        self._cache = cache
        self._fetch_resource = fetch_resource
        self._threshold = probability_threshold
        self._max_prefetch = max_prefetch
        
    def prefetch(self, predictions: Sequence[ResourcePrediction]) -> list[str]:
        """Предварительно загружает выбранные ресурсы."""
        
        loaded: list[str] = []
        seen: set[str] = set()
        for prediction in predictions:
            if len(loaded) >= self._max_prefetch:
                break
            
            resource_id = prediction.resource_id
            
            if resource_id in seen:
                continue
            
            seen.add(resource_id)
            
            if prediction.probability < self._threshold:
                continue
            
            if self._cache.contains(resource_id):
                continue
            
            value = self._fetch_resource(resource_id)
            
            self._cache.put(
                key=resource_id,
                value=value,
            )
            
            loaded.append(resource_id)
        
        return loaded