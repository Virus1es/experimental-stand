import hashlib
import json
import os
import platform
import subprocess
import psutil

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SERVER_DIR.parent

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "compose.experiment.yml"
]

def command_output(*args: str) -> str | None:
    """Выполняет команду и возвращает stdout"""
    
    try:
        process = subprocess.run(
            args,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    
    if process.returncode != 0:
        return None
    
    return process.stdout.strip()

def package_version(package: str) -> str | None:
    """Возвращает версию установленного Python-пакета"""
    
    try:
        return version(package)
    except PackageNotFoundError:
        return None
    
def file_sha256(path: Path) -> str | None:
    """Вычисляет SHA-256 содержимого файла"""
    
    if not path.is_file():
        return None
    
    digest = hashlib.sha256()
    
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
            
    return digest.hexdigest()

def collect_environment_metadata() -> dict:
    """Собирает сведения о коде, машине и входной трассе"""
    
    git_status = command_output("git", "status", "--porcelain")
    
    trace_path = SERVER_DIR / "data/traces/web_workload.csv"
    
    metadata_path = SERVER_DIR / "data/traces/web_workload.metadata.json"
    
    trace_metadata = {}
    
    if metadata_path.is_file():
        trace_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    
    parameters = trace_metadata.get("parameters", {})
    
    if not isinstance(parameters, dict):
        parameters = {}
        
    return {
        "git": {
            "commit": command_output("git", "rev-parse", "HEAD"),
            "working_tree_dirty": (
                None
                if git_status is None
                else bool(git_status)
            ),
        },
        "host": {
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "ram_total_bytes": psutil.virtual_memory().total,
        },
        "software": {
            "python": platform.python_version(),
            "locust": package_version("locust"),
            "fastapi": package_version("fastapi"),
            "scikit_learn": package_version("scikit-learn"),
            "redis_client": package_version("redis"),
        },
        "trace": {
            "path": "data/traces/web_workload.csv",
            "file_sha256": file_sha256(trace_path),
            "canonical_sha256": trace_metadata.get("sha256"),
            "request_count": trace_metadata.get("request_count"),
            "seed": parameters.get("seed"),
            "generator_parameters": parameters,
        },
    }

def collect_docker_images() -> dict:
    """Собирает идентификаторы образов работающих сервисов"""
    
    result = {}
    
    for service in ("redis", "origin", "backend"):
        container_id = command_output(
            *COMPOSE,
            "ps",
            "-q",
            service,
        )
        
        if not container_id:
            result[service] = {
                "image_reference": None,
                "image_id": None,
            }
            continue
        
        result[service] = {
            "image_reference": command_output(
                "docker",
                "inspect",
                "--format",
                "{{.Config.Image}}",
                container_id,
            ),
            "image_id": command_output(
                "docker",
                "inspect",
                "--format",
                "{{.Image}}",
                container_id,
            )
        }
    
    return result