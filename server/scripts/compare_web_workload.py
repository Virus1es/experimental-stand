from app.models.experiment import ExperimentConfig
from app.services.experiment_runner import ExperimentRunner
from app.services.prefetch_experiment_runner import PrefetchExperimentRunner
from app.services.predictor import LogisticRegressionPredictor
from app.services.trace_service import TraceService

def main() -> None:
    trace = TraceService.load_csv("data/traces/web_workload.csv")
    
    split_index = int(len(trace) * 0.8)
    
    train_trace = trace[:split_index]
    test_trace = trace[split_index:]
    
    config = ExperimentConfig(
        strategy="lru",
        capacity=5,
        hit_latency_ms=2.0,
        miss_latency_ms=100.0,
    )
    
    baseline = ExperimentRunner().run(
        test_trace,
        config
    )
    
    predictor = LogisticRegressionPredictor(
        history_size=3,
        random_state=42,
    )
    
    result = PrefetchExperimentRunner().run(
        train_trace=train_trace,
        test_trace=test_trace,
        config=config,
        predictor=predictor,
        probability_threshold=0.05,
        max_prefetch=3,
    )
    
    ml = result.experiment
    prefetch = result.prefetch
    
    print("\n=== WEB WORKLOAD EXPERIMENT ===")
    print(f"Training requests: {len(train_trace)}")
    print(f"Test request: {len(test_trace)}")
    print(f"Cache capacity: {config.capacity}")
    
    print("\n Metric                    LRU       LRU + ML")
    print("-" * 51)
    
    print(
        f"{'Hit rate':<26}",
        f"{baseline.hit_rate:>8.2%}",
        f"{ml.hit_rate:>13.2%}"
    )
    
    print(
        f"{'Hits':<26}",
        f"{baseline.hits:>8}",
        f"{ml.hits:>13}"
    )
    
    print(
        f"{'Misses':<26}",
        f"{baseline.misses:>8}",
        f"{ml.misses:>13}"
    )
    
    print(
        f"{'Origin requests':<26}",
        f"{baseline.origin_requests:>8}",
        f"{ml.origin_requests:>13}"
    )
    
    print(
        f"{'Origin bytes':<26}",
        f"{baseline.origin_bytes:>8}",
        f"{ml.origin_bytes:>13}"
    )
    
    print(
        f"{'Average latency (ms)':<26}",
        f"{baseline.average_latency_ms:>8.2f}   ",
        f"{ml.average_latency_ms:>13.2f}"
    )
    
    print("\n--- Prefetch Metrics ---")
    print(f"Prefetch count: {prefetch.prefetch_count}")
    print(f"Prefetch hits: {prefetch.prefetch_hits}")
    print(
        f"Prefetch precision: "
        f"{prefetch.prefetch_precision:.2%}"
    )
    print(
        "Wasted evictions: "
        f"{prefetch.prefetch_wasted_evictions}"
    )
    print(
        "Unused at end: "
        f"{prefetch.prefetch_unused_at_end}"
    )
    print(
        "Prefetch origin bytes: "
        f"{prefetch.prefetch_origin_bytes}"
    )
    
    print("\n--- Differences ---")
    print(
        "Hit rate: "
        f"{(ml.hit_rate - baseline.hit_rate) * 100:+.2f} pp"
    )
    print(
        "Origin requests: "
        f"{ml.origin_requests - baseline.origin_requests:+d}"
    )
    print(
        "Origin bytes: "
        f"{ml.origin_bytes - baseline.origin_bytes:+d}"
    )
    
if __name__ == "__main__":
    main()