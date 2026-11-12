
from collections.abc import Sequence

from app.models.prediction import ResourcePrediction
from app.services.http_prefetch_coordinator import (
    HttpPrefetchCoordinator,
)


class FakePredictor:
    def __init__(self) -> None:
        self.last_history: list[str] = []

    def predict_next(
        self,
        history: Sequence[str],
        top_k: int = 3,
    ) -> list[ResourcePrediction]:
        self.last_history = list(history)

        return [
            ResourcePrediction(
                resource_id="/api/resources/42",
                probability=0.75,
            ),
            ResourcePrediction(
                resource_id="/api/resources/7",
                probability=0.15,
            ),
            ResourcePrediction(
                resource_id="/api/resources/15",
                probability=0.30,
            ),
        ][:top_k]


def test_selects_predictions_above_threshold():
    predictor = FakePredictor()

    coordinator = HttpPrefetchCoordinator(
        predictor=predictor,
        history_size=3,
        initial_history=[
            "/api/resources/1",
            "/api/resources/2",
            "/api/resources/3",
        ],
        probability_threshold=0.2,
        max_prefetch=3,
    )

    selected = coordinator.observe_and_select(4)

    assert selected == [42, 15]

    assert predictor.last_history == [
        "/api/resources/2",
        "/api/resources/3",
        "/api/resources/4",
    ]


def test_waits_for_sufficient_history():
    predictor = FakePredictor()

    coordinator = HttpPrefetchCoordinator(
        predictor=predictor,
        history_size=3,
    )

    assert coordinator.observe_and_select(1) == []
    assert coordinator.observe_and_select(2) == []

    selected = coordinator.observe_and_select(3)

    assert selected == [42, 15]


def test_does_not_select_current_resource():
    predictor = FakePredictor()

    coordinator = HttpPrefetchCoordinator(
        predictor=predictor,
        initial_history=[
            "/api/resources/1",
            "/api/resources/2",
            "/api/resources/3",
        ],
    )

    selected = coordinator.observe_and_select(42)

    assert selected == [15]
