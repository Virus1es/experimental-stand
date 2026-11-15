import argparse
import csv
import math
import time
import httpx
import json

from datetime import datetime
from pathlib import Path
from statistics import mean

from app.services.resource_path_mapper import ResourcePathMapper
from app.services.trace_service import TraceService

def percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("Values must not be empty")
    
    if not 0 < p <= 1:
        raise ValueError("Percentile must be in (0; 1]")
    
    ordered = sorted(values)
    
    index = math.ceil(len(ordered) * p) - 1
    
    return ordered[index]

def main() -> None:
    parser = argparse.ArgumentParser()
    
    parser.add_argument(
        "--mode",
        choices=["lru", "lru-ml"],
        required=True,
    )
    
    args = parser.parse_args()
    
    trace = TraceService.load_csv("data/traces/web_workload.csv")
    
    split_index = int(len(trace) * 0.8)
    
    train_trace = trace[:split_index]
    test_trace = trace[split_index:]
    
    mapper = ResourcePathMapper(
        access.resource_id
        for access in train_trace
    )
    
    sent_requests = 0
    skipped_requests = 0
    latencies_ms: list[float] = []
    request_records: list[dict] = []
    
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=10.0,
        trust_env=False,
    ) as client:
        expected_ml = args.mode == "lru-ml"
        
        mode_response = client.post(
            "/api/experiment/wait-idle",
            timeout=25.0
        )
        
        mode_response.raise_for_status()
        
        actual_ml = mode_response.json()["prefetch_enabled"]
        
        if actual_ml != expected_ml:
            raise RuntimeError(
                f"Mode mismatch expected ML={expected_ml}, ",
                f"but backend ML={actual_ml}"
            )
        
        before = client.get("/api/resources/stats").json()
        
        print("Statistics before: ", before)
        
        for access in test_trace[:100]:
            try:
                resource_id = mapper.id_for(access.resource_id)
            except KeyError:
                skipped_requests += 1
                continue
            
            started = time.perf_counter()
            
            response = client.get(f"/api/resources/{resource_id}")
            
            elapsed_ms = (time.perf_counter() - started) * 1000
            
            response.raise_for_status()
            
            assert response.json()["resource_id"] == resource_id
            
            latencies_ms.append(elapsed_ms)
            
            request_records.append({
                "request_index": sent_requests + 1,
                "resource_id": resource_id,
                "latency_ms": round(elapsed_ms, 3),
                "status_code": response.status_code,
            })
            
            sent_requests += 1
        
        idle_response = client.post(
            "api/experiment/wait-idle",
            timeout=25.0
        )
        
        idle_response.raise_for_status()
        
        idle_result = idle_response.json()
        
        assert idle_result["status"] == "idle"
        
        print("Executor status: ", idle_result)
        
        after = client.get("/api/resources/stats").json()
        
        print("\n=== HTTP ML SMOKE TEST ===")
        print(f"Sent requests: {sent_requests}")
        print(f"Skipped requests: {skipped_requests}")
        
        for name, value in after.items():
            difference = value - before.get(name, 0)
            print(f"{name}: {value} (delta: {difference:+d})")
        
        if latencies_ms:
            print("\n--- HTTP Latency ---")
            print(f"Average: {mean(latencies_ms):.2f} ms")
            print(f"p50: {percentile(latencies_ms, 0.50):.2f} ms")
            print(f"p95: {percentile(latencies_ms, 0.95):.2f} ms")
            print(f"p99: {percentile(latencies_ms, 0.99):.2f} ms")
    
    output_dir = Path("results/raw")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    output_path = output_dir / f"smoke_{args.mode}_{timestamp}.csv"
    
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "request_index",
                "resource_id",
                "latency_ms",
                "status_code",
            ],
        )
        
        writer.writeheader()
        writer.writerows(request_records)
    
    print(f"\nRaw results saved to: {output_path}")
    
    metrics_delta = {
        name: after[name] - before.get(name, 0)
        for name in after
    }
    
    latency_stats = {
        "average": mean(latencies_ms),
        "p50": percentile(latencies_ms, 0.50),
        "p95": percentile(latencies_ms, 0.95),
        "p99": percentile(latencies_ms, 0.99),
    }
    
    summary = {
        "mode": args.mode,
        "sent_requests": sent_requests,
        "skipped_requests": skipped_requests,
        "hit_rate": (
            metrics_delta["hits"] / sent_requests
            if sent_requests > 0 else 0.0
        ),
        "metrics": metrics_delta,
        "latency_ms": latency_stats,
        "percentile_method": "nearest_rank",
        "raw_csv": str(output_path.resolve()),
    }
    
    summary_path = output_path.with_suffix(".json")
    
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    
    print(f"Summary saved to: {summary_path}")

if __name__ == "__main__":
    main()
