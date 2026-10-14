from app.services.redis_cache_service import RedisCacheService

def main() -> None:
    cache = RedisCacheService(
        namespace="cachelab:smoke",
        ttl_seconds=60,
    )
    
    if not cache.ping():
        raise RuntimeError("Redis ping failed")
    
    cache.clear()
    
    cache.put("health-check", "ok")
    
    value = cache.get("health-check")
    
    if value != "ok":
        raise AssertionError(
            f"Expected 'ok', received {value!r}"
        )
    
    print("Redis connection: OK")
    print(f"Stored value: {value}")
    print(f"Cache size: {cache.size()}")
    print(f"Cache hits: {cache.get_metrics().hits}")
    
    cache.remove("health-check")
    
    if cache.get("health-check") is not None:
        raise AssertionError("Key was not removed")
    
    print("Redis cache operations: OK")
    

if __name__ == "__main__":
    main()