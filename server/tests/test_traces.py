import pytest

from app.models.access import ResourseAccess
from app.services.trace_generator import TraceGenerator
from app.services.trace_service import TraceService

def test_trace_generation():
    generator = TraceGenerator(
        num_resources=10,
        seed=42
    )
    
    trace = generator.generate(
        num_requests=100,
        interval_ms=50
    )
    
    assert len(trace) == 100
    assert trace[0].timestamp_ms == 0
    assert trace[-1].timestamp_ms == 4950
    
    assert all(
        access.size_bytes > 0
        for access in trace
    )

def test_trace_reproducibility():
    first = TraceGenerator(
        num_resources=10,
        seed=42
    ).generate(num_requests=100)
    
    second = TraceGenerator(
        num_resources=10,
        seed=42
    ).generate(num_requests=100)
    
    assert first == second

def test_resource_size_is_consistent():
    trace = TraceGenerator(
        num_resources=3,
        seed=42
    ).generate(num_requests=100)
    
    sizes = {}
    
    for access in trace:
        if access.resource_id in sizes:
            assert sizes[access.resource_id] == access.size_bytes
        
        sizes[access.resource_id] = access.size_bytes
    
def test_trace_csv_roundtrip(tmp_path):
    trace = TraceGenerator(
        num_resources=5,
        seed=42
    ).generate(num_requests=20)
    
    path = tmp_path / "trace.csv"
    
    TraceService.save_csv(trace, path)
    loaded = TraceService.load_csv(path)
    
    assert loaded == trace
    
def test_trace_replay():
    trace = [
        ResourseAccess(0, "/api/a", 1024),
        ResourseAccess(100, "/api/b", 2048),
    ]
    
    replayed = list(TraceService.replay(trace))
    
    assert replayed == trace
    
def test_invalid_generator_parameters():
    with pytest.raises(ValueError):
        TraceGenerator(num_resources=0)
    
    with pytest.raises(ValueError):
        TraceGenerator(
            num_resources=10,
            zipf_alpha=-1,
        )