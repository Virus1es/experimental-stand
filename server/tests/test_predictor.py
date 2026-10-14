import pytest

from app.models.access import ResourseAccess
from app.services.predictor import LogisticRegressionPredictor


def make_trace(
    resource_ids: list[str],
) -> list[ResourseAccess]:
    return [
        ResourseAccess(
            timestamp_ms=index * 100,
            resource_id=resource_id,
            size_bytes=1024,
        )
        for index, resource_id in enumerate(resource_ids)
    ]


@pytest.fixture
def training_trace():
    pattern = [
        "A", "B", "A", "C",
        "B", "A", "C", "A", "B", "C",
    ]

    return make_trace(pattern * 20)


def test_predictor_returns_ranked_predictions(
    training_trace,
):
    predictor = LogisticRegressionPredictor(
        history_size=3,
    )

    predictor.fit(training_trace)

    predictions = predictor.predict_next(
        ["A", "B", "A"],
        top_k=3,
    )

    assert 1 <= len(predictions) <= 3

    probabilities = [
        item.probability
        for item in predictions
    ]

    assert probabilities == sorted(
        probabilities,
        reverse=True,
    )

    assert all(
        0.0 <= probability <= 1.0
        for probability in probabilities
    )

    assert sum(probabilities) == pytest.approx(1.0)


def test_predictor_evaluation(training_trace):
    predictor = LogisticRegressionPredictor(
        history_size=3,
    )

    predictor.fit(training_trace[:150])

    metrics = predictor.evaluate(
        training_trace[150:],
        top_k=3,
    )

    assert metrics.total_predictions == 50

    assert (
        0
        <= metrics.correct_predictions
        <= metrics.total_predictions
    )

    assert (
        metrics.correct_predictions
        <= metrics.top_k_correct_predictions
        <= metrics.total_predictions
    )

    assert 0.0 <= metrics.accuracy <= 1.0
    assert 0.0 <= metrics.top_k_accuracy <= 1.0


def test_predictor_handles_single_target_class():
    predictor = LogisticRegressionPredictor(
        history_size=2,
    )

    predictor.fit(
        make_trace(["A", "A", "A", "A", "A"])
    )

    predictions = predictor.predict_next(
        ["A", "A"],
        top_k=3,
    )

    assert len(predictions) == 1
    assert predictions[0].resource_id == "A"
    assert predictions[0].probability == 1.0


def test_predictor_rejects_short_training_trace():
    predictor = LogisticRegressionPredictor(
        history_size=3,
    )

    with pytest.raises(ValueError):
        predictor.fit(
            make_trace(["A", "B", "C"])
        )


def test_predictor_rejects_prediction_before_fit():
    predictor = LogisticRegressionPredictor(
        history_size=3,
    )

    with pytest.raises(RuntimeError):
        predictor.predict_next(["A", "B", "C"])


def test_predictor_rejects_short_history(
    training_trace,
):
    predictor = LogisticRegressionPredictor(
        history_size=3,
    )

    predictor.fit(training_trace)

    with pytest.raises(ValueError):
        predictor.predict_next(["A", "B"])


def test_predictor_rejects_invalid_top_k(
    training_trace,
):
    predictor = LogisticRegressionPredictor(
        history_size=3,
    )

    predictor.fit(training_trace)

    with pytest.raises(ValueError):
        predictor.predict_next(
            ["A", "B", "C"],
            top_k=0,
        )