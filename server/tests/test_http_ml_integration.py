from app.services.http_prefetch_coordinator import HttpPrefetchCoordinator
from app.services.predictor import LogisticRegressionPredictor
from app.services.trace_service import TraceService
from app.services.resource_path_mapper import PathMappedPredictor, ResourcePathMapper

def test_trained_ml_predictor_with_http_coordinator():
    trace = TraceService.load_csv(
        "data/traces/web_workload.csv"
    )

    split_index = int(len(trace) * 0.8)

    train_trace = trace[:split_index]
    test_trace = trace[split_index:]

    predictor = LogisticRegressionPredictor(
        history_size=3,
        random_state=42,
    )

    predictor.fit(train_trace)

    # Формируем отображение только по обучающим данным.
    mapper = ResourcePathMapper(
        access.resource_id
        for access in train_trace
    )

    initial_accesses = train_trace[
        -predictor.history_size:
    ]

    initial_history = [
        mapper.http_path(access.resource_id)
        for access in initial_accesses
    ]

    mapped_predictor = PathMappedPredictor(
        predictor=predictor,
        mapper=mapper
    )

    coordinator = HttpPrefetchCoordinator(
        predictor=mapped_predictor,
        history_size=predictor.history_size,
        initial_history=initial_history,
        probability_threshold=0.2,
        max_prefetch=3,
    )

    original_history = [
        access.resource_id
        for access in initial_accesses
    ]

    total_selected = 0

    for access in test_trace[:100]:
        current_path = access.resource_id
        resource_id = mapper.register(current_path)

        original_history.append(current_path)
        original_history = original_history[
            -predictor.history_size:
        ]

        raw_predictions = predictor.predict_next(
            original_history,
            top_k=3,
        )

        selected = coordinator.observe_and_select(
            resource_id
        )

        # Независимо рассчитываем ожидаемый результат
        # отбора по прогнозам исходной модели.
        expected = [
            mapper.id_for(prediction.resource_id)
            for prediction in raw_predictions
            if (
                prediction.probability >= 0.2
                and prediction.resource_id != current_path
            )
        ]

        assert selected == expected
        total_selected += len(selected)

    print(f"\nTraining requests: {len(train_trace)}")
    print(f"Test requests: {len(test_trace)}")
    print("Processed requests: 100")
    print(f"Selected prefetch candidates: {total_selected}")
