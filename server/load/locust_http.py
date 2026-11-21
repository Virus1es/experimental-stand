import json
import os

from itertools import cycle
from pathlib import Path
from locust import HttpUser, constant_pacing, task, events
from locust.env import Environment

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

class CacheLabUser(HttpUser):
    wait_time = constant_pacing(0.25)
    
    @task
    def request_resource(self):
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
    
@events.quitting.add_listener
def save_final_statistics(environment: Environment, **_kwargs: object):
    """Сохраняет статистику после завершения Locust."""
    
    output_path = os.getenv("CACHELAB_LOCUST_FINAL_STATS")
    
    if not output_path:
        return
    
    stats = environment.stats.total
    
    if stats.num_requests > 0:
        latency = {
            "average": stats.avg_response_time,
            "p50": stats.get_response_time_percentile(0.50),
            "p95": stats.get_response_time_percentile(0.95),
            "p99": stats.get_response_time_percentile(0.99),
        }
    else:
        latency = {
            "average": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }
        
    result = {
        "request_count": stats.num_requests,
        "failure_count": stats.num_failures,
        "rps": stats.total_rps or 0.0,
        "latency_ms": latency
    }
    
    Path(output_path).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
            