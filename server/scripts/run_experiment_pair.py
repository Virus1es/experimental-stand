import json
import os
import subprocess
import sys
import time
import httpx
import argparse
import csv

from datetime import datetime
from pathlib import Path
from statistics import mean
from datetime import timezone

from scripts.experiment_metadata import collect_environment_metadata, collect_docker_images
from scripts.experiment_setup import ensure_experiment_services, verify_backend_trace

SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SERVER_DIR.parent

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "compose.experiment.yml",
]

BASE_URL = "http://127.0.0.1:8000"

def container_path(path: Path) -> str:
    """Преобразует путь хоста в путь внутри контейнера Locust"""
    
    relative_path = path.resolve().relative_to(SERVER_DIR.resolve())
    
    return "/app/" + relative_path.as_posix()

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
    verify_backend_trace()
    
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

def read_locust_stats(csv_path: Path) -> dict:
    """Читает итоговую агрегированную статистику Locuct"""
    
    if not csv_path.is_file():
        raise FileNotFoundError(f"Locust stats not found: {csv_path}")

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        rows = list(csv.DictReader(file))
    
    aggregated = next(
        (
            row for row in rows
            if row["Name"] == "Aggregated"
        ),
        None,
    )
    
    if aggregated is None:
        raise RuntimeError("Aggregated Locust statistics not found")
    
    return {
        "request_count": int(aggregated["Request Count"]),
        "failure_count": int(aggregated["Failure Count"]),
        "rps": float(aggregated["Requests/s"]),
        "latency_ms": {
            "average": float(aggregated["Average Response Time"]),
            "p50": float(aggregated["50%"]),
            "p95": float(aggregated["95%"]),
            "p99": float(aggregated["99%"])
        },
    }

def run_locust_warmup(
    mode: str,
    output_dir: Path,
    users: int,
    duration: int,
) -> dict:
    """Запускает прогрев без включения его в измерение."""
    
    log_path = output_dir / f"{mode}_warmup.log"
    stats_path = output_dir / f"{mode}_warmup_final.json"
    
    environment = os.environ.copy()
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = "127.0.0.1,localhost"
    environment["CACHELAB_LOCUST_FINAL_STATS"] = str(stats_path.resolve())
    
    command = [
        sys.executable,
        "-m", "locust",
        "-f", "load/locust_http.py",
        "--headless",
        "--only-summary",
        "--host", BASE_URL,
        "--users", str(users),
        "--spawn-rate", str(users),
        "--run-time", f"{duration}s",
        "--stop-timeout", "10s",
        "--exit-code-on-error", "2"
    ]
    
    print(
        f"Warmup: {mode}, {duration}s",
        flush=True
    )
    
    result = subprocess.run(
        command,
        cwd=SERVER_DIR,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    
    log_path.write_text(
        result.stdout + "\n" + result.stderr,
        encoding="utf-8"
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Warmup failed: {log_path}")
    
    if not stats_path.is_file():
        raise RuntimeError("Warmup final statistics are missing")
    
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    
    if stats["request_count"] == 0 or stats["failure_count"] != 0:
        raise RuntimeError(f"Invalid wamup statistics: {stats}")
    
    return stats
 
def execute_locust_workload(
    mode: str,
    output_dir: Path,
    users: int,
    duration: int,
    warmup: int = 0,
) -> dict:
    """Запускает Locust и собирает метрики backend."""
    
    expected_ml = mode == "lru-ml"
    
    csv_base = output_dir / f"{mode}_locust"
    log_path = output_dir / f"{mode}.log"
    summary_path = output_dir / f"{mode}_summary.json"
    final_stats_path = output_dir / f"{mode}_locust_final.json"
    
    environment = os.environ.copy()
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = "127.0.0.1,localhost"
    environment["CACHELAB_LOCUST_FINAL_STATS"] = str(final_stats_path.resolve())
    
    with httpx.Client(base_url=BASE_URL, timeout=25.0, trust_env=False) as client:
        
        response = client.get("/api/resources/stats")
        response.raise_for_status()
        before = response.json()
        
        if any(value != 0 for value in before.values()):
            raise RuntimeError(f"Non-zero initial counters: {before}")
        
        warmup_stats = None
        
        if warmup > 0:
            warmup_stats = run_locust_warmup(
                mode=mode,
                output_dir=output_dir,
                users=users,
                duration=warmup
            )

            idle_response = client.post("/api/experiment/wait-idle")
            idle_response.raise_for_status()
            
            idle_result = idle_response.json()
            
            if idle_result["status"] != "idle" or idle_result["prefetch_enabled"] != expected_ml:
                raise RuntimeError("Invalid backend state after warmup")
            
            response = client.get("/api/resources/stats")
            response.raise_for_status()
            before = response.json()
            
            if before["hits"] + before["misses"] != warmup_stats["request_count"]:
                raise RuntimeError("Warmup request counters do not match")
            
        
        print(
            f"Starting Locust: {mode}, "
            f"users={users}, duration={duration}s",
            flush=True
        )
        
        command = [
            sys.executable,
            "-m",
            "locust",
            "-f",
            "load/locust_http.py",
            "--headless",
            "--only-summary",
            "--host",
            BASE_URL,
            "--users",
            str(users),
            "--spawn-rate",
            str(users),
            "--run-time",
            f"{duration}s",
            "--stop-timeout",
            "10s",
            "--exit-code-on-error",
            "2",
            "--csv",
            str(csv_base)
        ]
        
        result = subprocess.run(
            command,
            cwd=SERVER_DIR,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        log_path.write_text(
            result.stdout + "\n" + result.stderr,
            encoding="utf-8"
        )
        
        if result.returncode != 0:
            raise RuntimeError(
                f"Locust failed for {mode}. "
                f"See {log_path}"
            )
        
        idle_response = client.post("/api/experiment/wait-idle")
        
        idle_result = idle_response.json()
        
        if idle_result["status"] != "idle":
            raise RuntimeError("Prefetch executor is not idle")
        
        if idle_result["prefetch_enabled"] != expected_ml:
            raise RuntimeError(f"Unexpected backend mode for {mode}")
        
        response = client.get("/api/resources/stats")
        response.raise_for_status()
        after = response.json()
        
        metrics = {
            name: after[name] - before.get(name, 0)
            for name in after
        }
        
        csv_path = Path(f"{csv_base}_stats.csv")
        
        if not final_stats_path.is_file():
            raise RuntimeError(f"Final Locust statistics not found: {final_stats_path}")
        
        locust_stats = json.loads(final_stats_path.read_text(encoding="utf-8"))
        
        csv_stats = read_locust_stats(csv_path)
        
        if csv_stats["request_count"] != locust_stats["request_count"]:
            print(
                "Locust CSV snapshot differs from final stats: "
                f"CSV={csv_stats['request_count']}, "
                f"final={locust_stats['request_count']}",
                flush=True,
            )
        
        request_count = locust_stats["request_count"]
        backend_requests = metrics["hits"] + metrics["misses"]
        
        if request_count == 0:
            raise RuntimeError("Locust sent zero requests")
        
        if locust_stats["failure_count"] != 0:
            raise RuntimeError("Locust recorded HTTP failures")
        
        if backend_requests != request_count:
            raise RuntimeError(
                "Request count mismatch: "
                f"Locust={request_count}, "
                f"backend={backend_requests}"
            )
        
        if metrics["origin_requests"] != (metrics["misses"] + metrics["prefetch_requests"]):
            raise RuntimeError("Origin request counters are inconsistent")
        
        if not expected_ml and metrics["prefetch_requests"] != 0:
            raise RuntimeError("Prefetch occured in LRU mode")
            
        
        summary = {
            "mode": mode,
            "workload": "locust",
            "users": users,
            "duration_seconds": duration,
            "sent_requests": request_count,
            "failure_count": locust_stats["failure_count"],
            "rps": locust_stats["rps"],
            "hit_rate": metrics["hits"] / request_count,
            "metrics": metrics,
            "latency_ms": locust_stats["latency_ms"],
            "percentile_method": "locust_approximate",
            "locust_stats_csv": str(csv_path.resolve()),
            "final_stats_json": str(final_stats_path.resolve()),
            "warmup_seconds": warmup,
            "warmup_stats": warmup_stats,
            "counters_at_measurement_start": before if warmup > 0 else None
        }
        
        summary_path.write_text(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        
        print(
            f"{mode}: requests={request_count}, "
            f"RPS={summary['rps']:.2f}, "
            f"hit_rate={summary['hit_rate']:.2f}, "
            f"p95={summary['latency_ms']['p95']:.2f} ms",
            flush=True,
        )
        
        return {
            "mode": mode,
            "log": str(log_path.resolve()),
            "summary_json": str(summary_path.resolve()),
            "locust_stats_csv": str(csv_path.resolve()),
            "final_stats_json": str(final_stats_path.resolve()),
            "results": summary,
            "exit_code": result.returncode,
        }

def execute_locust_continuous(
    mode: str,
    output_dir: Path,
    users: int,
    duration: int,
    warmup: int,
    fixed_count: bool = False,
    warmup_requests: int | None = None,
    measurement_requests: int | None = None,
    phase_timeout: int = 120,
    locust_runtime: str = "host",
) -> dict:
    """Проводит прогрев и измерение в одном процессе Locust."""
    
    expected_ml = mode == "lru-ml"
    
    phase_path = output_dir / f"{mode}_phases.json"
    final_path = output_dir / f"{mode}_locust_final.json"
    summary_path = output_dir / f"{mode}_summary.json"
    trace_path = output_dir / f"{mode}_request_trace.json"
    log_path = output_dir / f"{mode}.log"
    csv_base = output_dir / f"{mode}_locust"
    
    environment = os.environ.copy()
    
    environment.update({
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "CACHELAB_CONTINUOUS": "true",
        "CACHELAB_USERS": str(users),
        "CACHELAB_WARMUP_SECONDS": str(warmup),
        "CACHELAB_MEASURE_SECONDS": str(duration),
        "CACHELAB_PHASE_RESULT": str(phase_path.resolve()),
        "CACHELAB_LOCUST_FINAL_STATS": str(final_path.resolve()),
        "CACHELAB_TRACE_RESULT": str(trace_path.resolve()),
        "CACHELAB_BACKEND_URL": BASE_URL,
        "CACHELAB_FIXED_COUNT": "true" if fixed_count else "false",
        "CACHELAB_WARMUP_REQUESTS": str(warmup_requests if fixed_count else 0),
        "CACHELAB_MEASUREMENT_REQUESTS": str(measurement_requests if fixed_count else 0),
        "CACHELAB_PHASE_TIMEOUT_SECONDS": str(phase_timeout),
    })
    
    if locust_runtime == "docker":
        environment.update({
            "CACHELAB_PHASE_RESULT": container_path(phase_path),
            "CACHELAB_LOCUST_FINAL_STATS": container_path(final_path),
            "CACHELAB_TRACE_RESULT": container_path(trace_path),
            "CACHELAB_BACKEND_URL": "http://backend:8000",
        })
    
    with httpx.Client(
        base_url=BASE_URL,
        timeout=25.0,
        trust_env=False,
    ) as client:
        response = client.get("/api/resources/stats")
        response.raise_for_status()
        initial = response.json()
        
        if any(value != 0 for value in initial.values()):
            raise RuntimeError(f"Non-zero initial counters: {initial}")
        
        response = client.post("/api/experiment/wait-idle")
        response.raise_for_status()
        
        if response.json()["prefetch_enabled"] != expected_ml:
            raise RuntimeError(f"Unexpected backend mode: {mode}")
    
    locust_args = [
        "-f", "load/locust_http.py",
        "--headless",
        "--only-summary",
        "--host", environment["CACHELAB_BACKEND_URL"],
        "--users", str(users),
        "--spawn-rate", str(users),
        "--stop-timeout", "10s",
        "--exit-code-on-error", "2",
        "--csv", (
            container_path(csv_base)
            if locust_runtime == "docker"
            else str(csv_base)
        ),
    ]
    
    if locust_runtime == "docker":
        container_env_names = (
            "CACHELAB_CONTINUOUS",
            "CACHELAB_USERS",
            "CACHELAB_WARMUP_SECONDS",
            "CACHELAB_MEASURE_SECONDS",
            "CACHELAB_PHASE_RESULT",
            "CACHELAB_LOCUST_FINAL_STATS",
            "CACHELAB_TRACE_RESULT",
            "CACHELAB_BACKEND_URL",
            "CACHELAB_FIXED_COUNT",
            "CACHELAB_WARMUP_REQUESTS",
            "CACHELAB_MEASUREMENT_REQUESTS",
            "CACHELAB_PHASE_TIMEOUT_SECONDS",
        )
        
        container_env_args = []
        
        for name in container_env_names:
            container_env_args.extend([
                "--env",
                f"{name}={environment[name]}",
            ])
        
        command = [
            *COMPOSE,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            *container_env_args,
            "locust",
            *locust_args,
        ]
        
        process_cwd = PROJECT_DIR
    else:
        command = [
            sys.executable,
            "-m",
            "locust",
            *locust_args,
        ]
        
        process_cwd = PROJECT_DIR
    
    if fixed_count:
        print(
            f"Fixed-count Locust: {mode}, "
            f"users={users}",
            f"warmup={warmup_requests}/user "
            f"({users * (warmup_requests or 0)} total), "
            f"measurement={measurement_requests}/user "
            f"({users * (measurement_requests or 0)} total)",
            flush=True,
        )
    else:
        print(
            f"Continuous Locust: {mode}, "
            f"warmup={warmup}s, "
            f"measurement={duration}s, " 
            f"users={users}",
            flush=True,
        )
    
    process_timeout = (
        2 * phase_timeout + 45
        if fixed_count
        else warmup + duration + 120
    )
    
    try:
        process = subprocess.run(
            command,
            cwd=process_cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=process_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            f"Locust timeout: {exc}",
            encoding="utf-8",
        )
        raise RuntimeError(f"Continuous Locust timed out: {mode}") from exc
    
    log_path.write_text(
        process.stdout + "\n" + process.stderr,
        encoding="utf-8",
    )
    
    if process.returncode != 0:
        raise RuntimeError(f"Continuous Locust failed: {log_path}")
    
    if not phase_path.is_file():
        raise RuntimeError(f"Phase results not found: {phase_path}")
    
    phases = json.loads(
        phase_path.read_text(encoding="utf-8")
    )
    
    if phases.get("status") != "completed":
        raise RuntimeError(f"Invalid phase result: {phases}")
    
    if not trace_path.is_file():
        raise RuntimeError(f"Request trace not found: {trace_path}")
    
    
    warmup_stats = phases["warmup_stats"]
    measurement_stats = phases["measurement_stats"]
    
    before = phases["counters_at_measurement_start"]
    after = phases["counters_at_measurement_end"]
    
    actual_warmup_requests = before["hits"] + before["misses"]
    
    if actual_warmup_requests != warmup_stats["request_count"]:
        raise RuntimeError(
            "Warmup request count mismatch: "
            f"backend={actual_warmup_requests}, "
            f"Locust={warmup_stats['request_count']}"
        )
    
    if warmup_stats["failure_count"] != 0:
        raise RuntimeError("Warmup contains HTTP failures")
    
    metrics = {
        name: after[name] - before[name]
        for name in after
    }
    
    request_count = measurement_stats["request_count"]
    backend_requests = metrics["hits"] + metrics["misses"]
    
    if request_count == 0:
        raise RuntimeError("No measurement requests")
    
    if measurement_stats["failure_count"] != 0:
        raise RuntimeError("Measurement contains HTTP failures")
    
    if backend_requests != request_count:
        raise RuntimeError(
            "Measurement request count mismatch: "
            f"backend={backend_requests}, "
            f"Locust={request_count}"
        )
        
    origin_requests = metrics["origin_requests"]
    
    expected_origin_requests = metrics["misses"] + metrics["prefetch_requests"]
    
    if origin_requests != expected_origin_requests:
        raise RuntimeError(
            "Origin counters are inconsistent: "
            f"origin={metrics['origin_requests']}, "
            f"misses={metrics['misses']}, "
            f"prefetch={metrics['prefetch_requests']}"
        )
    
    if not expected_ml and metrics["prefetch_requests"] != 0:
        raise RuntimeError("Unexpected prefetch in LRU mode")
    
    if not final_path.is_file():
        raise RuntimeError(f"Final Locust stats not found: {final_path}")
    
    final_stats = json.loads(
        final_path.read_text(encoding="utf-8")
    )
    
    if final_stats["request_count"] != request_count:
        raise RuntimeError(f"Final Locust count differs from phase result")
    
    if fixed_count:
        if phases.get("execution") != "fixed_count":
            raise RuntimeError("Locust did not execute fixed-count mode")
        
        expected_warmup = users * (warmup_requests or 0)
        expected_measurement = users * (measurement_requests or 0)
        
        if actual_warmup_requests != expected_warmup:
            raise RuntimeError(
                "Incorrect warmup request count: "
                f"expected={expected_warmup}, "
                f"actual={actual_warmup_requests}"
            )
        
        if request_count != expected_measurement:
            raise RuntimeError(
                "Incorrect measurement request count: "
                f"expected={expected_measurement}, "
                f"actual={request_count}"
            )
        
        request_trace = json.loads(trace_path.read_text(encoding="utf-8"))
        
        for phase_name, expected_per_user in (
            ("warmup", warmup_requests),
            ("measurement", measurement_requests)
        ):
            user_traces = request_trace["phases"][phase_name]["users"]
            
            if len(user_traces) != users:
                raise RuntimeError(f"Unexpected user count in {phase_name}")
            
            for user_index in range(users):
                actual = user_traces[str(user_index)]["request_count"]
                
                if actual != expected_per_user:
                    raise RuntimeError(
                        f"{phase_name}, user {user_index}: "
                        f"expected={expected_per_user}, actual={actual}"
                    )
                    
    phase_elapsed = phases.get("phase_elapsed_seconds")
    
    if fixed_count:
        if not isinstance(phase_elapsed, dict):
            raise RuntimeError("Phase durations are missing")
        
        measurement_elapsed = phase_elapsed["measurement"]
        
        if measurement_elapsed is None or measurement_elapsed <= 0:
            raise RuntimeError("Invalid measurement duration")
        
        actual_rps = request_count / measurement_elapsed
    else:
        actual_rps = measurement_stats["rps"]
    
    summary = {
        "mode": mode,
        "workload": "locust",
        "execution": "continuous",
        "users": users,
        "warmup_seconds": warmup,
        "duration_seconds": duration,
        "warmup_stats": warmup_stats,
        "sent_requests": request_count,
        "failure_count": measurement_stats["failure_count"],
        "rps": actual_rps,
        "hit_rate": metrics["hits"] / request_count,
        "metrics": metrics,
        "latency_ms": measurement_stats["latency_ms"],
        "percentile_method": "locust_approximate",
        "counters_at_measurement_start": before,
        "counters_at_measurement_end": after,
        "phase_result_json": str(phase_path.resolve()),
        "final_stats_json": str(final_path.resolve()),
        "request_trace_json": str(trace_path.resolve()),
        "termination": "fixed_count" if fixed_count else "duration",
        "warmup_requests_per_user": warmup_requests if fixed_count else None,
        "measurement_requests_per_user": measurement_requests if fixed_count else None,
        "phase_elapsed_seconds": phase_elapsed,
    }
    
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8"
    )
    
    print(
        f"{mode}: "
        f"warmup_requests={actual_warmup_requests}, "
        f"measurement_requests={request_count}, "
        f"RPS={summary['rps']:.2f}, "
        f"hit rate={summary['hit_rate']:.2%}, "
        f"p95={summary['latency_ms']['p95']:.2f} ms",
        flush=True
    )
    
    return {
        "mode": mode,
        "log": str(log_path.resolve()),
        "summary_json": str(summary_path.resolve()),
        "phase_result_json": str(phase_path.resolve()),
        "final_stats_json": str(final_path.resolve()),
        "request_trace_json": str(trace_path.resolve()),
        "results": summary,
        "exit_code": process.returncode,
    }
    
    
def find_sets(value, path="manifest"):
    """Находит множества во сложенных структурах"""
    
    if isinstance(value, (set, frozenset)):
        print(
            f"Invalid JSON value at {path}: {value!r}",
            flush=True
        )
    
    elif isinstance(value, dict):
        for key, item in value.items():
            find_sets(item, f"{path}[{key!r}]")
    
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            find_sets(item, f"{path}[{index}]")
    
def compare_request_traces(lru_path: Path, ml_path: Path) -> dict:
    """Проверяет идентичность фактической нагрузки"""
    
    lru = json.loads(lru_path.read_text(encoding="utf-8"))
    ml = json.loads(ml_path.read_text(encoding="utf-8"))
    
    mismatches = []
    
    for field in (
        "source_trace_length",
        "source_trace_sha256",
        "user_count"
    ):
        if lru[field] != ml[field]:
            mismatches.append(
                f"{field}: LRU={lru[field]}, ML={ml[field]}"
            )
    
    for phase in ("warmup", "measurement"):
        lru_phase = lru["phases"][phase]
        ml_phase = ml["phases"][phase]
        
        if lru_phase["request_count"] != ml_phase["request_count"]:
            mismatches.append(
                f"{phase}: different total request counts"
            )
        
        lru_users = lru_phase["users"]
        ml_users = ml_phase["users"]
        
        all_user_ids = sorted(
            set(lru_users) | set(ml_users),
            key=int,
        )
        
        for user_id in all_user_ids:
            lru_user = lru_users.get(user_id)
            ml_user = ml_users.get(user_id)
            
            if lru_user is None or ml_user is None:
                mismatches.append(
                    f"{phase}, user {user_id}: missing user"
                )
                continue
            
            if (
                lru_user["request_count"] != ml_user["request_count"] or
                lru_user["sha256"] != ml_user["sha256"] or
                lru_user["resource_ids"] != ml_user["resource_ids"]
            ):
                mismatches.append(
                    f"{phase}, user {user_id}: request sequence differ"
                )
    
    return {
        "matched": len(mismatches) == 0,
        "mismatches": mismatches,
        "lru_trace": str(lru_path.resolve()),
        "ml_trace": str(ml_path.resolve()),
    }
    
def main() -> None:
    parser = argparse.ArgumentParser()
    
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to experiment configuration JSON"
    )
    
    parser.add_argument(
        "--locust-runtime",
        choices=("host", "docker"),
        default="host",
        help="Locust execution environment"
    )
    
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Number of paired experiment runs"
    )
    
    parser.add_argument(
        "--workload",
        choices=("smoke", "locust"),
        default="smoke",
        help="Workload type"
    )
    
    parser.add_argument(
        "--users",
        type=int,
        default=5,
        help="Concurrent Locust users"
    )
    
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Locust duration in seconds"
    )
    
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="Warmup duration in seconds"
    )
    
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Use continuous Locust warmup and measurement"
    )
    
    parser.add_argument(
        "--fixed-count",
        action="store_true",
        help="Use a fixed number of requests per user"
    )
    
    parser.add_argument(
        "--warmup-requests",
        type=int,
        default=None,
        help="Warmup requests per user in fixed-count mode"
    )
    
    parser.add_argument(
        "--measurement-requests",
        type=int,
        default=None,
        help="Measurement requests per user in fixed-count mode"
    )
    
    parser.add_argument(
        "--phase-timeout",
        type=int,
        default=120,
        help="Maximum duration of each phase in seconds"
    )
    
    config_args, _ = parser.parse_known_args()
    
    config_path = None
    
    if config_args.config is not None:
        config_path = config_args.config
        
        if not config_path.is_absolute():
            config_path = SERVER_DIR / config_path
        
        if not config_path.is_file():
            parser.error(f"Configuration file not found: {config_path}")
        
        config = json.loads(config_path.read_text(encoding="utf-8"))
        
        if not isinstance(config, dict):
            parser.error("Experiment configuration nust be a JSON object")
        
        allowed_keys = {
            "repeats",
            "workload",
            "users",
            "duration",
            "warmup",
            "continuous",
            "fixed_count",
            "warmup_requests",
            "measurement_requests",
            "phase_timeout",
            "locust_runtime",
        }
        
        unknown_keys = set(config) - allowed_keys
        
        if unknown_keys:
            parser.error(
                "Unknown configuration parameters: "
                + ", ".join(sorted(unknown_keys))
            )
        
        parser.set_defaults(**config)
    
    args = parser.parse_args()
    
    if args.locust_runtime == "docker":
        if not (args.workload == "locust" and args.continuous):
            parser.error(
                "--locust-runtime docker requires "
                "--workload locust --continuous"
            )
    
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
        
    if args.users <= 0:
        parser.error("--users must be positive")
    
    if args.duration <= 0:
        parser.error("--duration must be positive")
    
    if args.warmup < 0:
        parser.error("--warmup must be non-negative")
    
    if args.continuous and args.workload != "locust":
        parser.error("--continuous requires --workload locust")
        
    if args.fixed_count and not (args.workload == "locust" and args.continuous):
        parser.error("--fixed-count requires --workload locust --continuous")
    
    if args.phase_timeout <= 0:
        parser.error("--phase-timeout must be positive")
    
    if args.fixed_count:
        if args.warmup_requests is None or args.warmup_requests < 0:
            parser.error("--warmup-requests must be non-negative")
        
        if args.measurement_requests is None or args.measurement_requests <= 0:
            parser.error("--measurement-requests must be positive")
    elif args.warmup_requests is not None or args.measurement_requests is not None:
        parser.error("--warmup-requests and --measurement-requests requires --fixed-count")
        

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    output_dir = SERVER_DIR / "results" / "pairs" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    
    manifest = {
        "run_id": run_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": None,
        "config_file": (
            str(args.config)
            if args.config is not None
            else None
        ),
        "effective_arguments": {
            key: value
            for key, value in vars(args).items()
            if key != "config"
        },
        "experiment_type": (
            "concurrent_http_locust"
            if args.workload == "locust"
            else "sequential_http_smoke"
        ),
        "workload_config": {
            "workload": args.workload,
            "locust_runtime": args.locust_runtime,
            "users": (
                args.users
                if args.workload == "locust"
                else None
            ),
            "duration_seconds": (
                args.duration
                if args.workload == "locust" and not args.fixed_count
                else None
            ),
            "warmup_seconds": (
                args.warmup 
                if args.workload == "locust" and not args.fixed_count
                else None
            ),
            "continuous": (
                args.continuous
                if args.workload == "locust"
                else None
            ),
            "fixed_count": args.fixed_count,
            "warmup_requests_per_user": ( 
                args.warmup_requests
                if args.fixed_count else None
            ),
            "measurement_requests_per_user": ( 
                args.measurement_requests
                if args.fixed_count else None
            ),
            "phase_timeout_seconds": ( 
                args.phase_timeout
                if args.fixed_count else None
            ),
        },
        "requested_repeats": args.repeats,
        "pairs": [],
    }
    
    try:
        ensure_experiment_services()
        
        manifest["environment"] = collect_environment_metadata()
        
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
                
                docker_images = collect_docker_images()
                
                if args.workload == "locust" and args.continuous:
                    result = execute_locust_continuous(
                        mode=mode,
                        output_dir=pair_dir,
                        users=args.users,
                        duration=args.duration,
                        warmup=args.warmup,
                        fixed_count=args.fixed_count,
                        warmup_requests=args.warmup_requests,
                        measurement_requests=args.measurement_requests,
                        phase_timeout=args.phase_timeout,
                        locust_runtime=args.locust_runtime,
                    )
                elif args.workload == "locust":
                    result = execute_locust_workload(
                        mode=mode,
                        output_dir=pair_dir,
                        users=args.users,
                        duration=args.duration,
                        warmup=args.warmup,
                    )
                else:
                    result = execute_workload(
                        mode=mode, 
                        output_dir=pair_dir
                    )
                
                result["docker_images"] = docker_images
                
                pair["runs"].append(result)
            
            by_mode = {
                run["mode"]: run["results"]
                for run in pair["runs"]
            }
            
            lru = by_mode["lru"]
            ml = by_mode["lru-ml"]
            
            if args.workload == "locust" and args.continuous:
                validation = compare_request_traces(
                    lru_path=Path(lru["request_trace_json"]),
                    ml_path=Path(ml["request_trace_json"]),
                )
                
                pair["workload_validation"] = validation
                
                if validation["matched"]:
                    print("Workload validation: MATCHED", flush=True)
                else:
                    print("Workload validation: NOT MATCHED", flush=True)
                    
                    for mismatch in validation["mismatches"]:
                        print(f"  - {mismatch}", flush=True)
            
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
        
        if args.workload == "locust" and args.continuous:
            matched_pairs = [
                pair
                for pair in manifest["pairs"]
                if pair.get("workload_validation", {}).get("matched", False)
            ]
            
            matched_reductions = [
                pair["comparison"]["p95_reduction_pct"]
                for pair in matched_pairs
                if "comparison" in pair
            ]
            
            manifest["summary"]["matched_workload_pairs"] = len(matched_pairs)
            
            manifest["summary"]["mean_p95_reduction_matched_pct"] = (
                mean(matched_reductions)
                if matched_reductions
                else None
            )
        
        print("\n=== Overall Summary ===")
        print(f"Completed pairs: {len(reductions)}")
        print(f"Mean p95 reduction: {mean(reductions):+.2f}%")
        
        manifest["status"] = "completed"
    
    except Exception as exc:
        manifest["status"] = "failed"
        
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": str(exc)
        }
        
        raise
    
    finally:
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        
        manifest_path = output_dir / "manifest.json"
        
        find_sets(manifest)
        
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