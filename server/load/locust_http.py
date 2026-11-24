import json
import os
import gevent
import httpx
import hashlib
import time

from itertools import cycle, count
from pathlib import Path
from locust import HttpUser, constant_pacing, task, events
from locust.env import Environment
from locust.exception import StopUser
from gevent.event import Event
from gevent.lock import Semaphore

from app.services.resource_path_mapper import ResourcePathMapper
from app.services.trace_service import TraceService
from load.fixed_workload import FixedWorkloadPlan, build_fixed_workload_plan

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

experiment_finishing = False

user_ids = count()

current_phase = "warmup"

observed_requests: dict[str, dict[int, list[int]]] = {
    "warmup": {},
    "measurement": {},
}

def record_request(user_index: int, resource_id: int) -> None:
    """Регистрирует ресурс в текущей фазе"""
    
    user_request = observed_requests[current_phase].setdefault(
        user_index,
        [],
    )
    
    user_request.append(resource_id)
    
def resource_sha256(resources: list[int]) -> str:
    """Хеш последовательности с учётом порядка элементов"""
    
    payload = json.dumps(
        resources,
        separators=(",", ":")
    ).encode("utf-8")
    
    return hashlib.sha256(payload).hexdigest()

def collect_request_trace(user_count: int) -> dict:
    """Формирует отчёт по фактически отправленной нагрузке"""
    
    phases = {}
    
    for phase_name in ("warmup", "measurement"):
        users = {}
        total_requests = 0
        
        for user_index in range(user_count):
            resources = observed_requests[phase_name].get(user_index, [])
            
            total_requests += len(resources)
            
            users[str(user_index)] = {
                "request_count": len(resources),
                "sha256": resource_sha256(resources),
                "resource_ids": list(resources)
            }
        
        phases[phase_name] = {
            "request_count": total_requests,
            "users": users,
        }
    
    return {
        "source_trace_length": len(resource_ids),
        "source_trace_sha256": resource_sha256(resource_ids),
        "user_count": user_count,
        "phases": phases,
    }

def resources_for_user(user_index: int, user_count: int) -> list[int]:
    """Возращает фиксированную часть тестовой трассы"""
    
    if user_count <= 0:
        raise ValueError("user_count must be positive")
    
    if not (0 <= user_index < user_count):
        raise ValueError(
            "Invalid user index: "
            f"user_index={user_index}, "
            f"user_count={user_count}"
        )
    
    assigned = resource_ids[user_index::user_count]
    
    if not assigned:
        raise RuntimeError(f"No resources assigned to user {user_index}")
    
    return assigned

traffic_allowed = Event()
traffic_allowed.set()

requests_idle = Event()
requests_idle.set()

fixed_phase_complete = {
    "warmup": Event(),
    "measurement": Event(),
}

fixed_measurement_gate = Event()

fixed_shutdown_gate = Event()

fixed_completed = {
    "warmup": 0,
    "measurement": 0,
}

fixed_count_lock = Semaphore()

active_requests = 0
requests_lock = Semaphore()

def mark_fixed_completed(phase: str) -> None:
    """Регистрирует завершение одного запроса фазы"""
    
    env_name = (
        "CAHCELAB_WARMUP_REQUESTS"
        if phase == "warmup"
        else "CACHELAB_MEASUREMENT_REQUESTS"
    )
    
    requests_per_user = int(os.environ[env_name])
    user_count = int(os.environ["CACHELAB_USERS"])
    
    expected = user_count * requests_per_user
    
    with fixed_count_lock:
        fixed_completed[phase] += 1
        
        if fixed_completed[phase] > expected:
            raise RuntimeError(f"Too many requests in {phase}")
        
        if fixed_completed[phase] == expected:
            fixed_phase_complete[phase].set()

def begin_request() -> None:
    global active_requests
    
    while True:
        traffic_allowed.wait()
        
        with requests_lock:
            if experiment_finishing:
                raise StopUser()
            
            if not traffic_allowed.is_set():
                continue
            
            active_requests += 1
            requests_idle.clear()
            return

def end_request() -> None:
    global active_requests
    
    with requests_lock:
        active_requests -= 1
        
        if active_requests == 0:
            requests_idle.set()

class CacheLabUser(HttpUser):
    wait_time = constant_pacing(0.25)
    
    def on_start(self) -> None:
        self.user_index: int | None = None
        self.fixed_plan: FixedWorkloadPlan | None = None
        
        self.fixed_positions = {
            "warmup": 0,
            "measurement": 0,
        }
        
        self.resource_iterator = requests_cycle
        
        user_count = int(os.environ["CACHELAB_USERS"])
                
        self.user_index = next(user_ids)
        
        if os.getenv("CACHELAB_CONTINUOUS") == "true":
            self.fixed_plan = build_fixed_workload_plan(
                resource_ids=resource_ids,
                user_index=self.user_index,
                user_count=user_count,
                warmup_requests=int(os.environ["CACHELAB_WARMUP_REQUESTS"]),
                measurement_requests=int(os.environ["CACHELAB_MEASUREMENT_REQUESTS"]),
            )
            return
        
        user_resources = resources_for_user(
            user_index=self.user_index,
            user_count=user_count
        )
        
        self.resource_iterator = cycle(user_resources)

    @task
    def request_resource(self):
        if self.fixed_plan is not None:
            self.run_fixed_request()
            return
        
        begin_request()
        
        try:
            resource_id = next(self.resource_iterator)
            
            if os.getenv("CACHELAB_CONTINUOUS") == "true":
                if self.user_index is None:
                    raise RuntimeError("User index was not initialized in on_start()")
                
                record_request(self.user_index, resource_id)
            
            self.send_resource_request(resource_id)
        finally:
            end_request()
    
    def send_resource_request(self, resource_id: int) -> None:
        """Отправляет HTTP-запрос и проверяет ответ"""
        
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
    
    def run_fixed_request(self) -> None:
        """Выполняет следующий запрос фиксированного плана"""
        
        if self.fixed_plan is None or self.user_index is None:
            raise RuntimeError("Fixed workload was not initialized")
        
        phase = current_phase
        
        resources = (
            self.fixed_plan.warmup
            if phase == "warmup"
            else self.fixed_plan.measurement
        )
        
        position = self.fixed_positions[phase]
        
        if position >= len(resources):
            if phase == "warmup":
                fixed_measurement_gate.wait()
                
                if experiment_finishing:
                    raise StopUser()
                
                return
            
            fixed_shutdown_gate.wait()
            raise StopUser()
        
        begin_request()
        
        try:
            resource_id = resources[position]
            
            self.fixed_positions[phase] += 1
            
            record_request(self.user_index, resource_id)
            
            self.send_resource_request(resource_id)
        finally:
            end_request()
            mark_fixed_completed(phase)
    
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
    global current_phase, experiment_finishing
    
    warmup = int(os.environ["CACHELAB_WARMUP_SECONDS"])
    duration = int(os.environ["CACHELAB_MEASURE_SECONDS"])
    
    result_path = Path(os.environ["CACHELAB_PHASE_RESULT"])
    
    trace_path = Path(os.environ["CACHELAB_TRACE_RESULT"])
    user_count = int(os.environ["CACHELAB_USERS"])
    
    fixed_count = os.getenv("CACHELAB_FIXED_COUNT") == "true"
    phase_timeout = int(os.getenv("CACHELAB_PHASE_TIMEOUT_SECONDS", "60"))
    
    warmup_elapsed_seconds = None
    measurement_elapsed_seconds = None
    
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
            if fixed_count:
                warmup_requests = int(os.environ["CACHELAB_WARMUP_REQUESTS"])
                
                if warmup_requests == 0:
                    fixed_phase_complete["warmup"].set()
                
                print(
                    f"Fixed warmup: {warmup_requests} request per user",
                    flush=True
                )
                
                started = time.monotonic()
                
                if not fixed_phase_complete["warmup"].wait(timeout=phase_timeout):
                    raise TimeoutError("Fixed warmup did not complete")
                
                warmup_elapsed_seconds = time.monotonic() - started
            else:
                print(f"Continuius warmup: {warmup}s", flush=True)
                
                gevent.sleep(warmup)
            
            counters_before = pause_and_snapshot(client)
            warmup_stats = collect_locust_stats(environment)
            
            current_phase = "measurement"
            
            environment.stats.reset_all()
            
            if fixed_count:
                measurement_requests = int(os.environ["CACHELAB_MEASUREMENT_REQUESTS"])
                
                print(
                    f"Fixed measurement: {measurement_requests} request per user",
                    flush=True
                )
                
                started = time.monotonic()
                
                traffic_allowed.set()
                fixed_shutdown_gate.set()
                
                if not fixed_phase_complete["measurement"].wait(timeout=phase_timeout):
                    raise TimeoutError("Fixed measurement did not complete")
                
                measurement_elapsed_seconds = time.monotonic() - started
            else:
                traffic_allowed.set()
                
                print(f"Continuius measurement: {duration}s", flush=True)
                
                gevent.sleep(duration)
            
            counters_after = pause_and_snapshot(client)
            measurement_stats = collect_locust_stats(environment)
            
            if warmup > 0 and warmup_stats["request_count"] == 0:
                raise RuntimeError("Warmup finished without HTTP requests")
            
            if measurement_stats["request_count"] == 0:
                raise RuntimeError("Measurement finished without HTTP requests")
            
            request_trace = collect_request_trace(user_count)
            
            for phase_name, locust_stats in (
                ("warmup", warmup_stats),
                ("measurement", measurement_stats),
            ):
                logged_count = request_trace["phases"][phase_name]["request_count"]
                
                if logged_count != locust_stats["request_count"]:
                    raise RuntimeError(
                        f"{phase_name} trace count mismatch: "
                        f"logged={logged_count}, "
                        f"locust={locust_stats['request_count']}"
                    )
            
            trace_path.write_text(
                json.dumps(
                    request_trace,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        
        result = {
            "status": "completed",
            "warmup_seconds": warmup,
            "duration_seconds": duration,
            "warmup_stats": warmup_stats,
            "measurement_stats": measurement_stats,
            "counters_at_measurement_start": counters_before,
            "counters_at_measurement_end": counters_after,
            "request_trace_json": str(trace_path.resolve()),
            "execution": "fixed_count" if fixed_count else "time_based",
            "phase_elapsed_seconds": {
                "warmup": warmup_elapsed_seconds,
                "measurement": measurement_elapsed_seconds,
            }
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
        experiment_finishing = True
        
        traffic_allowed.set()
        fixed_measurement_gate.set()
        fixed_shutdown_gate.set()
        
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