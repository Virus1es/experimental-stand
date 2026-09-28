from pathlib import Path

from app.models.experiment import ExperimentConfig
from app.services.experiment_runner import ExperimentRunner
from app.services.result_service import ResultService
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
    
    output_dir = Path("data/results/sample")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Requests in trace: {len(trace)}\n")
    
    header = (
        f"{'Strategy':<10}"
        f"{'Hit rate':>12}"
        f"{'Avg latency':>16}"
        f"{'Origin req.':>14}"
        f"{'Origin bytes':>16}"
    )
    
    print(header)
    print("-" * len(header))
    
    for result in results:
        print(
            f"{result.strategy.upper():<10}"
            f"{result.hit_rate:>11.2%}"
            f"{result.average_latency_ms:>13.2f} ms"
            f"{result.origin_requests:>14}"
            f"{result.origin_bytes:>16}"
        )
        
        ResultService.save_json(
            result,
            output_dir / f"{result.strategy}.json"
        )
        
        ResultService.save_requests_csv(
            result,
            output_dir / f"{result.strategy}_requests.csv"
        )
        
    ResultService.save_summary_csv(
        results,
        output_dir / "summary.csv"
    )
    
    print(f"\nResults saved to: {output_dir}")
    
if __name__ == "__main__":
    main()