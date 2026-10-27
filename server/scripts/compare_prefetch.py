from app.models.experiment import ExperimentConfig
from app.services.experiment_runner import ExperimentRunner
from app.services.prefetch_experiment_runner import (
    PrefetchExperimentRunner,
)
from app.services.predictor import LogisticRegressionPredictor
from app.services.trace_service import TraceService


def main() -> None:
    trace = TraceService.load_csv(
        "data/traces/sample.csv"
    )

    if len(trace) < 20:
        raise ValueError(
            "At least 20 requests are required"
        )

    split_index = int(len(trace) * 0.8)

    train_trace = trace[:split_index]
    test_trace = trace[split_index:]

    config = ExperimentConfig(
        strategy="lru",
        capacity=20,
        hit_latency_ms=2.0,
        miss_latency_ms=100.0,
    )

    # Baseline: обычный LRU.
    baseline = ExperimentRunner().run(
        test_trace,
        config,
    )

    # Эксперимент: LRU + ML-prefetching.
    predictor = LogisticRegressionPredictor(
        history_size=3,
        random_state=42,
    )

    ml_result = PrefetchExperimentRunner().run(
        train_trace=train_trace,
        test_trace=test_trace,
        config=config,
        predictor=predictor,
        probability_threshold=0.2,
        max_prefetch=3,
    )

    ml = ml_result.experiment
    prefetch = ml_result.prefetch

    print("\n=== CACHELAB: BASELINE VS ML PREFETCH ===")
    print(f"Training requests: {len(train_trace)}")
    print(f"Test requests: {len(test_trace)}")
    print(f"Cache capacity: {config.capacity}")

    print("\n--- Baseline LRU ---")
    print(f"Hit rate: {baseline.hit_rate:.2%}")
    print(f"Hits: {baseline.hits}")
    print(f"Misses: {baseline.misses}")
    print(f"Origin requests: {baseline.origin_requests}")
    print(f"Origin bytes: {baseline.origin_bytes}")
    print(
        f"Average latency: "
        f"{baseline.average_latency_ms:.2f} ms"
    )

    print("\n--- LRU + ML Prefetch ---")
    print(f"Hit rate: {ml.hit_rate:.2%}")
    print(f"Hits: {ml.hits}")
    print(f"Misses: {ml.misses}")
    print(f"Origin requests: {ml.origin_requests}")
    print(f"Origin bytes: {ml.origin_bytes}")
    print(
        f"Average latency: "
        f"{ml.average_latency_ms:.2f} ms"
    )

    print("\n--- Prefetch Metrics ---")
    print(f"Prefetch count: {prefetch.prefetch_count}")
    print(f"Prefetch hits: {prefetch.prefetch_hits}")
    print(
        f"Evicted unused: "
        f"{prefetch.prefetch_wasted_evictions}"
    )
    print(
        f"Unused at end: "
        f"{prefetch.prefetch_unused_at_end}"
    )
    print(
        f"Prefetch precision: "
        f"{prefetch.prefetch_precision:.2%}"
    )
    print(
        f"Prefetch origin bytes: "
        f"{prefetch.prefetch_origin_bytes}"
    )

    print("\n--- Comparison ---")

    hit_rate_diff = (
        ml.hit_rate - baseline.hit_rate
    ) * 100

    origin_requests_diff = (
        ml.origin_requests - baseline.origin_requests
    )

    origin_bytes_diff = (
        ml.origin_bytes - baseline.origin_bytes
    )

    latency_diff = (
        ml.average_latency_ms
        - baseline.average_latency_ms
    )

    print(
        f"Hit rate difference: "
        f"{hit_rate_diff:+.2f} percentage points"
    )
    print(
        f"Origin requests difference: "
        f"{origin_requests_diff:+d}"
    )
    print(
        f"Origin bytes difference: "
        f"{origin_bytes_diff:+d}"
    )
    print(
        f"Average latency difference: "
        f"{latency_diff:+.2f} ms"
    )


if __name__ == "__main__":
    main()