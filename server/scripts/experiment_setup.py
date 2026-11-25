import json
import subprocess
import sys

from pathlib import Path

from app.services.trace_service import TraceService
from scripts.experiment_metadata import file_sha256

SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SERVER_DIR.parent

TRACE_PATH = SERVER_DIR / "data/traces/web_workload.csv"
METADATA_PATH = SERVER_DIR / "data/traces/web_workload.metadata.json"

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "compose.experiment.yml"
]

def ensure_experiment_services() -> None:
    """Подготавливает трассу и базовые сервисы эксперимента"""
    
    if not TRACE_PATH.is_file():
        print("Wrokload trace is missing. Generating...", flush=True)
        
        subprocess.run(
            [sys.executable, "-m", "scripts.generate_web_trace"],
            cwd=SERVER_DIR,
            check=True,
        )
    
    if not METADATA_PATH.is_file():
        raise RuntimeError(
            f"Trace metadata is missing: {METADATA_PATH}. "
            "Restore the metadata without overwriting the CSV."
        )
    
    metadata = json.loads(
        METADATA_PATH.read_text(encoding="utf-8")
    )
    
    trace = TraceService.load_csv(TRACE_PATH)
    
    actual_metadata = TraceService.build_metadata(
        trace,
        source=metadata["source"],
        source_format=metadata["format"],
        parameters=metadata.get("parameters"),
    )
    
    if actual_metadata["sha256"] != metadata["sha256"]:
        raise RuntimeError(
            "Trace check sum mismatch. "
            "The CSV does not match its metadata."
        )
    
    print(f"Trace verified: {len(trace)} requests", flush=True)
    
    subprocess.run(
        [
            *COMPOSE,
            "up",
            "-d",
            "--wait",
            "redis",
            "origin",
        ],
        cwd=PROJECT_DIR,
        check=True,
    )

def verify_backend_trace() -> None:
    """Проверяет совпадение CSV на хосте и внутри Backend"""
    
    expected_sha256 = file_sha256(TRACE_PATH)
    
    command = (
        "from pathlib import Path; "
        "import hashlib; "
        "p = Path('/app/data/traces/web_workload.csv'); "
        "print(hashlib.sha256(p.read_bytes()).hexdigest())"
    )
    
    process = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "backend",
            "python",
            "-c",
            command,
        ],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )
    
    actual_sha256 = process.stdout.strip()
    
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "Backend trace differs from the local trace. "
            "The backend image may need rebuilding."
        )
    
    print("Backend trace SHA256: MATCHED", flush=True)