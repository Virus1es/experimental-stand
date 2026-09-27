from app.models.experiment import ExperimentConfig
from app.services.experiment_runner import ExperimentRunner
from app.services.trace_service import TraceService

def main() -> None:
    trace = TraceService.load_csv(
        "data/traces/sample.csv"
    )
    
    configs = [
        ExperimentConfig(
            strategy=name,
            capacity=20,
            hit_latency_ms=2,
            miss_latency_ms=100,
        )
        for name in ("lru", "lfu", "fifo")
    ]
    
    runner = ExperimentRunner()
    results = runner.compare(trace, configs)
    
    print(f"Requests in trace: {len(trace)}")
    print()
    
    header = (
        f"{'Strategy':<10}"
        f"{'Hits':<10}"
        f"{'Misses':<10}"
        f"{'Hit rate':<10}"
        f"{'Avg latency':<10}"
    )
    
    print(header)
    print("-" * len(header))
    
    for result in results:
        print(
            f"{result.strategy.upper():<10}"
            f"{result.hits:<10}"
            f"{result.misses:<10}"
            f"{result.hit_rate:<11.2%}"
            f"{result.average_latency_ms:<13.2f} ms"
        )
    
if __name__ == "__main__":
    main()