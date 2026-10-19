from app.models.prediction import ResourcePrediction
from app.services.cache_service import CacheService
from app.services.prefetch_service import PrefetchService

def fetch_resource(resource_id: str) -> str:
    print(f"Fetching resource: {resource_id}")
    return f"content:{resource_id}"

def main() -> None:
    cache = CacheService(strategy="lru", capacity=5)
    
    prefetch_service = PrefetchService(
        cache=cache,
        fetch_resource=fetch_resource,
        probability_threshold=0.2,
        max_prefetch=2,
    )
    
    predictions = [
        ResourcePrediction("A", 0.65),
        ResourcePrediction("B", 0.25),
        ResourcePrediction("C", 0.10),
    ]
    
    loaded = prefetch_service.prefetch(predictions)
    
    print(f"Prefetched resources: {loaded}")
    print(f"Cache size: {cache.size()}")
    
    value = cache.get("A")
    
    print(f"Requested value: {value}")
    print(f"Cache hits: {cache.get_metrics().hits}")
    print(f"Cache misses: {cache.get_metrics().misses}")
    
if __name__ == "__main__":
    main()