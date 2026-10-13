from app.services.trace_service import TraceService

def main() -> None:
    trace = TraceService.load_csv(
        "data/traces/sample.csv"
    )
    
    parameters = {
        "generator": "TraceGenerator",
        "num_resources": 100,
        "zipf_alpha": 1.2,
        "seed": 42,
        "interval_ms": 50,
    }
    
    TraceService.save_json(
        trace,
        "data/traces/sample.json",
        source="synthetic_zipf",
        parameters=parameters,
    )
    
    TraceService.save_metadata(
        trace,
        "data/traces/sample.metadata.json",
        source="synthetic_zipf",
        source_format="csv",
        parameters=parameters,
    )
    
    metadata = TraceService.build_metadata(
        trace,
        source="synthetic_zipf",
        source_format="csv",
        parameters=parameters,
    )
    
    print(f"Requests: {metadata['request_count']}")
    print(f"Unique resources: {metadata['unique_resources']}")
    print(f"SHA-256: {metadata['sha256']}")
    print("Trace prepared successfully.")
    
if __name__ == "__main__":
    main()