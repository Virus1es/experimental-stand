import csv
import json

import pytest

from app.models.access import ResourseAccess
from app.models.experiment import ExperimentConfig
from app.services.experiment_runner import ExperimentRunner
from app.services.result_service import ResultService

@pytest.fixture
def expriment_result():
    trace = [
        ResourseAccess(0, "A", 1000),
        ResourseAccess(100, "B", 2000),
        ResourseAccess(200, "A", 1000),
        ResourseAccess(300, "C", 3000),
        ResourseAccess(400, "A", 1000),
    ]
    
    return ExperimentRunner().run(
        trace,
        ExperimentConfig(
            strategy="lru",
            capacity=2,
            hit_latency_ms=2,
            miss_latency_ms=100,
        ),
    )

def test_extended_metrics(expriment_result):
    result = expriment_result
    
    assert result.total_requests == 5
    assert result.hits == 2
    assert result.misses == 3
    
    assert result.origin_requests == 3
    
    assert result.client_bytes == 8000
    
    assert result.origin_bytes == 6000
    
    assert result.total_latency_ms == pytest.approx(304)
    assert result.average_latency_ms == pytest.approx(60.8)
   
def test_request_history(expriment_result):
    requests = expriment_result.requests
    
    assert len(requests) == 5
    
    assert [request.cache_hit for request in requests] == [
        False,
        False,
        True,
        False,
        True,
    ]
    
    assert [request.cache_size for request in requests] == [
        1, 2, 2, 2, 2,
    ]
    
    assert requests[0].origin_bytes == 1000
    assert requests[2].origin_bytes == 0
    
def test_save_json(expriment_result, tmp_path):
    path = tmp_path / "result.json"
    
    ResultService.save_json(expriment_result, path)
    
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
        
    assert data["strategy"] == "lru"
    assert data["origin_requests"] == 3
    assert data["origin_bytes"] == 6000
    assert len(data["requests"]) == 5
    
def test_save_requests_csv(expriment_result, tmp_path):
    path = tmp_path / "requests.csv"
    
    ResultService.save_requests_csv(expriment_result, path)
    
    with path.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))
    
    assert len(rows) == 5
    assert rows[0]["resource_id"] == "A"
    assert rows[0]["cache_hit"] == "False"
    assert rows[2]["cache_hit"] == "True"
    
def test_save_summary_csv(expriment_result, tmp_path):
    path = tmp_path / "summary.csv"
    
    ResultService.save_summary_csv([expriment_result], path)
    
    with path.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))
    
    assert len(rows) == 1
    assert rows[0]["strategy"] == "lru"
    assert int(rows[0]["origin_bytes"]) == 6000
    