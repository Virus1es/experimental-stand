import json
import os
import subprocess
import sys
import time
import httpx

from datetime import datetime
from pathlib import Path

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
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    output_dir = SERVER_DIR / "results" / "pairs" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    
    manifest = {
        "run_id": run_id,
        "experiment_type": "sequential_http_smoke",
        "run_order": ["lru", "lru-ml"],
        "runs": [],
    }
    
    try:
        for mode in ("lru", "lru-ml"):
            print(f"\n=== Preparing {mode} ===")
            
            prepare_backend(mode)
            
            result = execute_workload(mode, output_dir)
            
            manifest["runs"].append(result)
    finally:
        manifest_path = output_dir / "manifest.json"
        
        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8"
        )
        
        print(f"\nManifest: {manifest_path}")
        
if __name__ == "__main__":
    main()