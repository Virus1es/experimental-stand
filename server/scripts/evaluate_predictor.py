from app.services.predictor import LogisticRegressionPredictor
from app.services.trace_service import TraceService

def main() -> None:
    trace = TraceService.load_csv("data/traces/sample.csv")
    
    if len(trace) < 20:
        raise ValueError("Trace must contain at least 20 requests")
    
    split_index = int(len(trace) * 0.8)
    
    train_trace = trace[:split_index]
    
    test_trace = trace[split_index:]
    
    predictor = LogisticRegressionPredictor(
        history_size=3,
        random_state=42,
    )
    
    predictor.fit(train_trace)
    
    metrics = predictor.evaluate(test_trace, top_k=3)
    
    print("Prediction evaluation")
    print("-" * 32)
    print(f"Training requests: {len(train_trace)}")
    print(f"Test requests: {len(test_trace)}")
    print(f"Top-1 accuracy: {metrics.accuracy:.2%}")
    print(f"Top-3 accuracy: {metrics.top_k_accuracy:.2%}")
    
    history = [access.resource_id for access in train_trace[-3:]]
    
    print("\nNext resource predictions:")
    
    for prediction in predictor.predict_next(
        history,
        top_k=3,
    ):
        print(
            f"{prediction.resource_id}: "
            f"{prediction.probability:.2%}"
        )

if __name__ == "__main__":
    main()
    