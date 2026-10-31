from collections.abc import Sequence
from app.models.access import ResourseAccess
from app.models.experiment import ExperimentConfig
from app.models.prediction import ResourcePrediction
from app.services.experiment_runner import ExperimentRunner
from app.services.prefetch_experiment_runner import (
    PrefetchExperimentRunner,
)


def make_trace(
    resource_ids: list[str],
) -> list[ResourseAccess]:
    return [
        ResourseAccess(
            timestamp_ms=index * 100,
            resource_id=resource_id,
            size_bytes=1000,
        )
        for index, resource_id in enumerate(resource_ids)
    ]


class FixedPredictor:
    """Предсказатель для детерминированных тестов."""

    history_size = 2

    def __init__(self, predicted_resource: str) -> None:
        self.predicted_resource = predicted_resource
        self.training_requests = 0

    def fit(self, trace: Sequence[ResourseAccess]) -> "FixedPredictor":
        self.training_requests = len(trace)
        return self

    def predict_next(self, history, top_k=3) -> list[ResourcePrediction]:
        return [
            ResourcePrediction(
                resource_id=self.predicted_resource,
                probability=1.0,
            )
        ][:top_k]

class BatchPredictor:
    """Возвращает заданную последовательность ресурсов"""
    history_size = 2
    
    def __init__(
        self,
        resource_ids: Sequence[str]
    ) -> None:
        self.resource_ids = list(resource_ids)
    
    def fit(
        self,
        trace: Sequence[ResourseAccess]
    ) -> "BatchPredictor":
        return self
    
    def predict_next(
        self,
        history: Sequence[str],
        top_k: int = 3
    ) -> list[ResourcePrediction]:
        return [
            ResourcePrediction(
                resource_id=resource_id,
                probability=1.0
            )
            for resource_id in self.resource_ids
        ]

class ScriptedPredictor(BatchPredictor):
    """Возвращает отдельную пачку предсказайний на каждый вызов"""
    
    def __init__(self, batches: Sequence[Sequence[str]]) -> None:
        super().__init__([])
        self.batches = [list(batch) for batch in batches]
        self.next_batch_index = 0
        
    def predict_next(
        self, 
        history: Sequence[str], 
        top_k: int = 3
    ) -> list[ResourcePrediction]:
        if self.next_batch_index >= len(self.batches):
            return []
        
        batch = self.batches[self.next_batch_index]
        self.next_batch_index += 1
        
        return[
            ResourcePrediction(
                resource_id=resource_id,
                probability=1.0
            )
            for resource_id in batch[:top_k]
        ]

def test_prefetch_improves_hit_rate():
    train = make_trace(["A", "B", "A", "B"])
    test = make_trace(["A", "B", "A", "B"])

    config = ExperimentConfig(
        strategy="lru",
        capacity=2,
    )

    baseline = ExperimentRunner().run(test, config)

    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=config,
        predictor=FixedPredictor("B"),
    )

    assert baseline.hits == 2
    assert baseline.misses == 2

    assert result.experiment.hits == 3
    assert result.experiment.misses == 1

    assert result.prefetch.prefetch_count == 1
    assert result.prefetch.prefetch_hits == 1
    assert result.prefetch.prefetch_precision == 1.0


def test_prefetch_does_not_change_user_request_count():
    train = make_trace(["A", "B", "A", "B"])
    test = make_trace(["A", "B", "A"])

    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=ExperimentConfig("lru", 2),
        predictor=FixedPredictor("B"),
    )

    assert result.experiment.total_requests == len(test)
    assert (
        result.experiment.hits + result.experiment.misses
        == len(test)
    )


def test_prefetch_origin_traffic_is_counted():
    train = make_trace(["A", "B", "A", "B"])
    test = make_trace(["A", "B"])

    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=ExperimentConfig("lru", 2),
        predictor=FixedPredictor("B"),
    )

    # A загружен при пользовательском промахе,
    # B предварительно загружен.
    assert result.experiment.origin_requests == 2
    assert result.experiment.origin_bytes == 2000

    assert result.prefetch.prefetch_count == 1
    assert result.prefetch.prefetch_origin_bytes == 1000


def test_unused_prefetch_can_be_evicted():
    train = make_trace(["A", "B", "A", "B"])
    test = make_trace(["A", "A"])

    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=ExperimentConfig("lru", 1),
        predictor=FixedPredictor("B"),
    )

    # После первого запроса A предзагрузка B вытесняет A.
    # При следующем запросе A вытесняется B без использования.
    assert result.prefetch.prefetch_hits == 0
    assert result.prefetch.prefetch_wasted_evictions >= 1
    assert result.experiment.misses == 2


def test_predictor_trains_only_on_training_trace():
    train = make_trace(["A", "B", "A", "B"])
    test = make_trace(["A", "B", "A"])

    predictor = FixedPredictor("B")

    PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=ExperimentConfig("lru", 2),
        predictor=predictor,
    )

    assert predictor.training_requests == len(train)


def test_no_requests_produces_zero_metrics():
    train = make_trace(["A", "B", "A", "B"])

    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=[],
        config=ExperimentConfig("lru", 2),
        predictor=FixedPredictor("B"),
    )

    assert result.experiment.total_requests == 0
    assert result.experiment.hit_rate == 0.0
    assert result.prefetch.prefetch_count == 0
    assert result.prefetch.prefetch_precision == 0.0
    
def test_prefetch_eviction_within_batch_is_counted():
    train = make_trace(["A", "B", "A", "B"])
    test = make_trace(["C"])
    
    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=ExperimentConfig(
            strategy="lru",
            capacity=1
        ),
        predictor=BatchPredictor(["A", "B"]),
        max_prefetch=2,
    )
    
    assert result.experiment.total_requests == 1
    assert result.experiment.hits == 0
    assert result.experiment.misses == 1
    
    assert result.experiment.origin_requests == 3
    assert result.experiment.origin_bytes == 3000
    
    assert result.prefetch.prefetch_count == 2
    assert result.prefetch.prefetch_hits == 0
    assert result.prefetch.prefetch_wasted_evictions == 1
    assert result.prefetch.prefetch_unused_at_end == 1
    assert result.prefetch.prefetch_origin_bytes == 2000
    
    accounted_prefetches = (
        result.prefetch.prefetch_hits
        + result.prefetch.prefetch_wasted_evictions
        + result.prefetch.prefetch_unused_at_end
    )
    
    assert accounted_prefetches == result.prefetch.prefetch_count
    
def test_evicted_prefetch_can_be_loaded_again_in_next_batch():
    train = make_trace(["A", "B", "C", "A"])
    test = make_trace(["D", "A"])
    
    predictor = ScriptedPredictor([
        ["A", "B"],
        ["C", "B"],
    ])
    
    result = PrefetchExperimentRunner().run(
        train_trace=train,
        test_trace=test,
        config=ExperimentConfig(
            strategy="lru",
            capacity=2,
        ),
        predictor=predictor,
        max_prefetch=2,
    )
    
    assert result.experiment.total_requests == 2
    assert result.experiment.hits == 1
    assert result.experiment.misses == 1
    
    assert result.experiment.origin_requests == 5
    assert result.experiment.origin_bytes == 5000
    
    assert result.prefetch.prefetch_count == 4
    assert result.prefetch.prefetch_hits == 1
    assert result.prefetch.prefetch_wasted_evictions == 1
    assert result.prefetch.prefetch_unused_at_end == 2
    assert result.prefetch.prefetch_origin_bytes == 4000
    
    accounted_prefetch = (
        result.prefetch.prefetch_hits
        + result.prefetch.prefetch_wasted_evictions
        + result.prefetch.prefetch_unused_at_end
    )
    
    assert accounted_prefetch == result.prefetch.prefetch_count
     