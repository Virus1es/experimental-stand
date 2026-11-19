import json
import os
import subprocess
import sys
import time
import httpx
import argparse

from datetime import datetime
from pathlib import Path
from statistics import mean

SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SERVER_DIR.parent

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "compose.experiment.yml",
]

BASE_URL = "http://127.0.0.1:8000"

def run_compose(*args: str, environment: dict[str, str]) -> None:
    subprocess.run(
        [*COMPOSE, *args], 
        cwd=PROJECT_DIR, 
        env=environment, 
        check=True
    )

def prepare_backend(mode: str) -> None:
    """Создаёт чистое окружение для одного прогона"""
    
    environment = os.environ.copy()
    
    environment["PREFETCH_ENABLED"] = (
        "true" if mode == "lru-ml" else "false"
    )
    environment["EXPERIMENT_CONTROL_ENABLED"] = "true"
    
    run_compose("stop", "backend", environment=environment)
    
    run_compose(
        "exec",
        "-T",
        "redis",
        "redis-cli",
        "-n",
        "0",
        "FLUSHDB",
        environment=environment
    )
    
    run_compose(
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "backend",
        environment=environment,
    )
    
    wait_until_ready(mode)
    
def wait_until_ready(mode: str) -> None:
    """Ожидает готовности backend и проверяет режим"""
    
    expect_ml = mode == "lru-ml"
    deadline = time.monotonic() + 90
    
    with httpx.Client(
        base_url=BASE_URL,
        timeout=5,
        trust_env=False,
    ) as client:
        while time.monotonic() < deadline:
            try:
                health = client.get("/api/health")
                health.raise_for_status()
                
                response = client.post("/api/experiment/wait-idle")
                response.raise_for_status()
                
                actual_ml = response.json()["prefetch_enabled"]
                
                if actual_ml != expect_ml:
                    raise RuntimeError(
                        f"Expected ML = {expect_ml}",
                        f"got ML = {actual_ml}",
                    )
                
                stats_response = client.get("/api/resources/stats")
                stats_response.raise_for_status()
                
                stats = stats_response.json()
                
                if any(
                    stats[name] != 0
                    for name in (
                        "hits",
                        "misses",
                        "origin_requests"
                    )
                ):
                    raise RuntimeError("Cache counters are not zero")
                
                return
            
            except httpx.HTTPError:
                time.sleep(0.5)
                
    raise TimeoutError("Backend did not become ready")
        
def execute_workload(mode: str, output_dir: Path) -> dict:
    """Запускает существующий HTTP smoke-тест"""
    
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.smoke_http_ml",
            "--mode",
            mode,
        ],
        cwd=SERVER_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    
    log_path = output_dir / f"{mode}.log"
    log_path.write_text(
        result.stdout + "\n" + result.stderr,
        encoding="utf-8",
    )
    
    print(result.stdout)
    
    if result.returncode != 0:
        raise RuntimeError(f"{mode} failed. See {log_path}")

    raw_csv = None
    
    for line in result.stdout.splitlines():
        prefix = "Raw results saved to:"
        if line.startswith(prefix):
            relative_path = line[len(prefix):].strip()
            raw_csv = str((SERVER_DIR / relative_path).resolve())
    
    summary_path = None
    
    for line in result.stdout.splitlines():
        prefix = "Summary saved to:"
        
        if line.startswith(prefix):
            relative_path = line[len(prefix):].strip()
            
            summary_path = (SERVER_DIR / relative_path).resolve()
        
    if summary_path is None or not summary_path.is_file():
        raise RuntimeError(f"Summary JSON not found for mode {mode}")
    
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    
    if summary["mode"] != mode:
        raise RuntimeError(
            f"Result mode mismatch: expected {mode}, "
            f"got {summary['mode']}"
        )
    
    return {
        "mode": mode,
        "log": str(log_path.resolve()),
        "raw_csv": raw_csv,
        "summary_json": str(summary_path),
        "results": summary,
        "exit_code": result.returncode,
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Number of paired experiment runs"
    )
    
    args = parser.parse_args()
    
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
    
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    output_dir = SERVER_DIR / "results" / "pairs" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    
    manifest = {
        "run_id": run_id,
        "experiment_type": "sequential_http_smoke",
        "requested_repeats": args.repeats,
        "pairs": [],
    }
    
    try:
        for pair_index in range(1, args.repeats + 1):
            if pair_index % 2 == 1:
                order = ("lru", "lru-ml")
            else:
                order = ("lru-ml", "lru")
            
            pair_dir = output_dir / f"pair_{pair_index:02d}"
            pair_dir.mkdir()
            
            pair = {
                "pair_index": pair_index,
                "run_order": list(order),
                "runs": [],
            }
            
            manifest["pairs"].append(pair)
            
            print(f"\n === Pair {pair_index}/{args.repeats} ===", flush=True)
            
            for mode in order:
                print(f"=== Preparing {mode} ===", flush=True)

                prepare_backend(mode)
                
                result = execute_workload(mode, pair_dir)
                
                pair["runs"].append(result)
            
            by_mode = {
                run["mode"]: run["results"]
                for run in pair["runs"]
            }
            
            lru = by_mode["lru"]
            ml = by_mode["lru-ml"]
            
            lru_p95 = lru["latency_ms"]["p95"]
            ml_p95 = ml["latency_ms"]["p95"]
            
            reduction_pct = (lru_p95 - ml_p95) / lru_p95 * 100
            
            hit_rate_change_pp = (ml["hit_rate"] - lru["hit_rate"]) * 100
            
            pair["comparison"] = {
                "lru_p95_ms": lru_p95,
                "ml_p95_ms": ml_p95,
                "p95_reduction_pct": reduction_pct,
                "hit_rate_change_pp": hit_rate_change_pp,
                "origin_requests_delta": ml["metrics"]["origin_requests"] - lru["metrics"]["origin_requests"]
            }
            
            print(
                f"\nPair {pair_index}: "
                f"p95 reduction = {reduction_pct:+.2f}%",
                flush=True
            )
        
        reductions = [
            pair["comparison"]["p95_reduction_pct"]
            for pair in manifest["pairs"]
            if "comparison" in pair
        ]
        
        manifest["summary"] = {
            "completed_pairs": len(reductions),
            "p95_reductions_pct": reductions,
            "mean_p95_reduction_pct": mean(reductions),
            "pairs_with_improvement": sum(value > 0 for value in reductions)
        }
        
        print("\n=== Overall Summary ===")
        print(f"Completed pairs: {len(reductions)}")
        print(f"Mean p95 reduction: {mean(reductions):+.2f}%")
    
    finally:
        manifest_path = output_dir / "manifest.json"
        
        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )
        
        print(f"\nManifest: {manifest_path}", flush=True)

if __name__ == "__main__":
    main()