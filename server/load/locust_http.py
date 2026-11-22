import json
import os
import gevent
import httpx

from itertools import cycle
from pathlib import Path
from locust import HttpUser, constant_pacing, task, events
from locust.env import Environment
from gevent.event import Event
from gevent.lock import Semaphore

from app.services.resource_path_mapper import ResourcePathMapper
from app.services.trace_service import TraceService

SERVER_DIR = Path(__file__).resolve().parents[1]

trace = TraceService.load_csv(str(SERVER_DIR / "data/traces/web_workload.csv"))

split_index = int(len(trace) * 0.8)

train_trace = trace[:split_index]
test_trace = trace[split_index:]

mapper = ResourcePathMapper(
    access.resource_id
    for access in train_trace
)

known_paths = {
    access.resource_id
    for access in train_trace
}

resource_ids = [
    mapper.id_for(access.resource_id)
    for access in test_trace
    if access.resource_id in known_paths
]

if not resource_ids:
    raise RuntimeError("No valid workload resources")

requests_cycle = cycle(resource_ids)

traffic_allowed = Event()
traffic_allowed.set()

requests_idle = Event()
requests_idle.set()

active_requests = 0
requests_lock = Semaphore()

def begin_request() -> None:
    global active_requests
    
    traffic_allowed.wait()
    
    with requests_lock:
        active_requests += 1
        requests_idle.clear()

def end_request() -> None:
    global active_requests
    
    with requests_lock:
        active_requests -= 1
        
        if active_requests == 0:
            requests_idle.set()

class CacheLabUser(HttpUser):
    wait_time = constant_pacing(0.25)
    
    @task
    def request_resource(self):
        begin_request()
        
        try:
            resource_id = next(requests_cycle)
            
            with self.client.get(
                f"/api/resources/{resource_id}",
                name="/api/resources/{id}",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    return

                result = response.json()
                
                if result.get("resource_id") != resource_id:
                    response.failure("Incorrect resource returned")
        finally:
            end_request()
    
@events.quitting.add_listener
def save_final_statistics(environment: Environment, **_kwargs: object):
    """Сохраняет статистику после завершения Locust."""
    
    output_path = os.getenv("CACHELAB_LOCUST_FINAL_STATS")
    
    if not output_path:
        return
    
    result = collect_locust_stats(environment)
    
    Path(output_path).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
            
def collect_locust_stats(environment: Environment) -> dict:
    stats = environment.stats.total
    
    latency = {
        "average": 0.0,
        "p50": 0.0,
        "p95": 0.0,
        "p99": 0.0,
    }
    
    if stats.num_requests > 0:
        latency = {
            "average": stats.avg_response_time,
            "p50": stats.get_response_time_percentile(0.50),
            "p95": stats.get_response_time_percentile(0.95),
            "p99": stats.get_response_time_percentile(0.99),
        }
    
    return {
        "request_count": stats.num_requests,
        "failure_count": stats.num_failures,
        "rps": stats.total_rps or 0.0,
        "latency_ms": latency
    }
    
def run_continuous_phases(environment: Environment) -> None:
    warmup = int(os.environ["CACHELAB_WARMUP_SECONDS"])
    duration = int(os.environ["CACHELAB_MEASURE_SECONDS"])
    
    result_path = Path(os.environ["CACHELAB_PHASE_RESULT"])
    
    backend_url = os.environ.get(
        "CACHELAB_BACKEND_URL",
        "http://127.0.0.1:8000",
    )
    
    def pause_and_snapshot(client: httpx.Client) -> dict:
        traffic_allowed.clear()
        
        if not requests_idle.wait(timeout=30):
            raise TimeoutError("Active HTTP reqests did not finish")
        
        response = client.post(
            "/api/experiment/wait-idle",
            timeout=25
        )
        response.raise_for_status()
        
        if response.json()["status"] != "idle":
            raise RuntimeError("Backend did not become idle")
        
        response = client.get("/api/resources/stats")
        response.raise_for_status()
        
        return response.json()

    try:
        with httpx.Client(
            base_url=backend_url, 
            timeout=25, 
            trust_env=False
        ) as client:
            print(f"Continuous warmup: {warmup}s", flush=True)
            
            gevent.sleep(warmup)
            
            counters_before = pause_and_snapshot(client)
            warmup_stats = collect_locust_stats(environment)
            
            environment.stats.reset_all()
            
            traffic_allowed.set()
            
            print(f"Continuous measurement: {duration}s", flush=True)
            
            gevent.sleep(duration)
            
            counters_after = pause_and_snapshot(client)
            measurement_stats = collect_locust_stats(environment)
        
        result = {
            "status": "completed",
            "warmup_seconds": warmup,
            "duration_seconds": duration,
            "warmup_stats": warmup_stats,
            "measurement_stats": measurement_stats,
            "counters_at_measurement_start": counters_before,
            "counters_at_measurement_end": counters_after,
        }
        
        result_path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8"
        )
    except Exception as exc:
        environment.process_exit_code = 2
        
        result_path.write_text(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        if environment.runner is not None:
            environment.runner.quit()

@events.test_start.add_listener
def configure_continuous_experiment(
    environment: Environment,
    **_kwargs: object,
) -> None:
    if os.getenv("CACHELAB_CONTINUOUS") != "true":
        return
    
    @environment.events.spawning_complete.add_listener
    def start_phases(user_count: int, **_kwargs: object) -> None:
        gevent.spawn(run_continuous_phases, environment)