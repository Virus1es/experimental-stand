import pytest

from app.models.access import ResourseAccess
from app.models.experiment import ExperimentConfig
from app.services.experiment_runner import ExperimentRunner

@pytest.fixture
def sample_trace():
    return [
        ResourseAccess(0, "A", 1024),
        ResourseAccess(100, "B", 1024),
        ResourseAccess(200, "A", 1024),
        ResourseAccess(300, "C", 1024),
        ResourseAccess(400, "A", 1024),
    ]

def test_lru_experiment(sample_trace):
    runner = ExperimentRunner()
    
    result = runner.run(
        sample_trace,
        ExperimentConfig(
            strategy="lru",
            capacity=2,
            hit_latency_ms=2,
            miss_latency_ms=100,
        ),
    )
    
    assert result.total_requests == 5
    assert result.hits == 2
    assert result.misses == 3
    
    assert result.hit_rate == pytest.approx(0.4)
    assert result.miss_rate == pytest.approx(0.6)
    
    assert result.total_latency_ms == pytest.approx(304)
    assert result.average_latency_ms == pytest.approx(60.8)
    
def test_compare_uses_same_trace(sample_trace):
    runner = ExperimentRunner()
    
    configs = [
        ExperimentConfig("lru", capacity=2),
        ExperimentConfig("lfu", capacity=2),
        ExperimentConfig("fifo", capacity=2),
    ]
    
    results = runner.compare(sample_trace, configs)
    
    assert len(results) == 3
    
    assert [result.strategy for result in results] == [
        "lru",
        "lfu",
        "fifo",
    ]
    
    assert all(
        result.total_requests == len(sample_trace)
        for result in results
    )

def test_compare_accepts_generator(sample_trace):
    runner = ExperimentRunner()
    
    results = runner.compare(
        iter(sample_trace),
        [
            ExperimentConfig("lru", capacity=2),
            ExperimentConfig("fifo", capacity=2),
        ],
    )
    
    assert len(results) == 2
    assert all(result.total_requests == 5 for result in results)
    
def test_empty_trace():
    result = ExperimentRunner().run(
        [],
        ExperimentConfig("lru", capacity=2)
    )
    
    assert result.total_requests == 0
    assert result.hits == 0
    assert result.misses == 0
    assert result.hit_rate == 0
    assert result.average_latency_ms == 0
    
def test_invalid_experiment_config():
    with pytest.raises(ValueError):
        ExperimentConfig("lru", capacity=0)
    with pytest.raises(ValueError):
        ExperimentConfig(
            "lru",
            capacity=2,
            hit_latency_ms=-1,
        )

def test_unknown_strategy():
    with pytest.raises(ValueError):
        ExperimentRunner().run(
            [],
            ExperimentConfig("unknown", capacity=2),
        )
