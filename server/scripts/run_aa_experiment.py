import argparse
import json

from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from scripts.experiment_setup import ensure_experiment_services
from scripts.experiment_metadata import collect_environment_metadata, collect_docker_images
from scripts.run_experiment_pair import prepare_backend, execute_locust_continuous, compare_request_traces

SERVER_DIR = Path(__file__).resolve().parents[1]

def main() -> None:
    parser = argparse.ArgumentParser()
    
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/experiment.json"),
    )
    
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
    )
    
    args = parser.parse_args()
    
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
        
    config_path = args.config
    
    if not config_path.is_absolute():
        config_path = SERVER_DIR / config_path
    
    config = json.loads(config_path.read_text(encoding="utf-8"))
    
    if not config.get("continuous") or not config.get("fixed_count"):
        raise ValueError("A/A experiment requires continuous fixed-count workload")
    
    users = int(config["users"])
    warmup_requests = int(config["warmup_requests"])
    measurement_requests = int(config["measurement_requests"])
    phase_timeout = int(config["phase_timeout"])
    
    locust_runtime = config.get("locust_runtime", "host")
    
    if locust_runtime not in ("host", "docker"):
        raise ValueError("Invalid Locust runtime")
    
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    output_dir = SERVER_DIR / "results" / "aa" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    
    manifest = {
        "run_id": run_id,
        "experiment_type": "aa_validation",
        "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": config,
        "requested_repeats": args.repeats,
        "environment": None,
        "pairs": [],
    }
    
    try:
        ensure_experiment_services()
        
        manifest["environment"] = collect_environment_metadata()
        
        for pair_index in range(1, args.repeats + 1):
            print(f"\n=== A/A Pair {pair_index}/{args.repeats} ===", flush=True)
            
            pair_dir = output_dir / f"pair_{pair_index:02d}"
            
            pair = {
                "pair_index": pair_index,
                "runs": [],
            }
            
            manifest["pairs"].append(pair)
            
            for label in ("A", "B"):
                print(f"\nPreparing LRU run {label}", flush=True)
                
                run_dir = pair_dir / label.lower()
                run_dir.mkdir(parents=True, exist_ok=False)
                
                prepare_backend("lru")
                
                result = execute_locust_continuous(
                    mode="lru",
                    output_dir=run_dir,
                    users=users,
                    duration=int(config.get("duration", 30)),
                    warmup=int(config.get("warmup", 0)),
                    fixed_count=True,
                    warmup_requests=warmup_requests,
                    measurement_requests=measurement_requests,
                    phase_timeout=phase_timeout,
                    locust_runtime=locust_runtime,
                )
                
                if result["exit_code"] != 0:
                    raise RuntimeError(f"A/A run {label} failed")
                
                if result["results"]["failure_count"] != 0:
                    raise RuntimeError(f"A/A run {label} contains HTTP failures")
                
                result["label"] = label
                result["docker_images"] = collect_docker_images()
                
                pair["runs"].append(result)
            
            first = pair["runs"][0]["results"]
            second = pair["runs"][1]["results"]
            
            first_trace = Path(first["request_trace_json"])
            second_trace = Path(second["request_trace_json"])
            
            if first_trace.resolve() == second_trace.resolve():
                raise RuntimeError(
                    "A/A runs must have different request trace files"
                )
            
            validation = compare_request_traces(
                Path(first["request_trace_json"]),
                Path(second["request_trace_json"]),
            )
            
            pair["workload_validation"] = {
                "matched": validation["matched"],
                "mismatches": validation["mismatches"],
            }
            
            if not validation["matched"]:
                raise RuntimeError(f"A/A pair {pair_index}: workload mismatch")
            
            p95_a = first["latency_ms"]["p95"]
            p95_b = second["latency_ms"]["p95"]
            
            pair["comparison"] = {
                "p95_a_ms": p95_a,
                "p95_b_ms": p95_b,
                "p95_difference_ms": p95_b - p95_a,
                "hit_rate_difference_pp": (
                    second["hit_rate"] - first["hit_rate"]
                ) * 100,
            }
            
            print(
                f"A/A pair {pair_index}: "
                f"p95 A={p95_a:.2f} ms, "
                f"B={p95_b:.2f} ms, "
                f"difference={p95_b - p95_a:+.2f} ms",
                flush=True
            )
        
        difference = [
            pair["comparison"]["p95_difference_ms"]
            for pair in manifest["pairs"]
        ]
        
        manifest["summary"] = {
            "completed_pairs": len(difference),
            "mean_p95_difference_ms": mean(difference),
            "max_absolute_p95_difference_ms": max(
                abs(value) for value in difference
            ),
            "matched_workload_pairs": sum(
                pair["workload_validation"]["matched"]
                for pair in manifest["pairs"]
            ),
        }
        
        manifest["status"] = "completed"

        print("\n=== A/A Summary ===", flush=True)
        print(f"Completed pairs: {len(difference)}")
        print(f"Mean p95 difference: {mean(difference):+.2f} ms")
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        raise
    finally:
        manifest["finished_at_utc"] = (
            datetime.now(timezone.utc).isoformat()
        )
        
        manifest_path = output_dir / "manifest.json"
        
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        
        print(f"\nManifest: {manifest_path}", flush=True)

if __name__ == "__main__":
    main()