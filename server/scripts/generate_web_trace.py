import json

from pathlib import Path

from app.models.web_workload import WebWorkloadConfig
from app.services.trace_service import TraceService
from app.services.web_workload_generator import WebWorkloadGenerator

def main() -> None:
    config = WebWorkloadConfig(
        num_products=100,
        num_requests=10_000,
        zipf_alpha=1.2,
        seed=42,
        request_interval_ms=100,
        session_gap_ms=2_000,
    )
    
    generator = WebWorkloadGenerator(config)
    trace = generator.generate()
    
    output_dir = Path("data/traces")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    csv_path = output_dir / "web_workload.csv"
    json_path = output_dir / "web_workload.json"
    
    parameters = {
        "num_products": config.num_products,
        "num_requests": config.num_requests,
        "zipf_alpha": config.zipf_alpha,
        "seed": config.seed,
        "request_interval_ms": config.request_interval_ms,
        "session_gap_ms": config.session_gap_ms,
    }
    
    trace_service = TraceService()
    
    trace_service.save_csv(trace, csv_path)
    
    trace_service.save_json(
        trace,
        json_path,
        source="synthetic_web_workload",
        parameters=parameters,
    )
    
    metadata_path = output_dir / "web_workload.metadata.json"
    
    trace_service.save_metadata(
        trace,
        metadata_path,
        source="synthetic_web_workload",
        source_format="csv",
        parameters=parameters
    )
    
    with metadata_path.open("r", encoding="utf-8") as file:
        metadata = json.load(file)
    
    print("Web workload generated successfully")
    print(f"Requests: {len(trace)}")
    print(
        "Unique resources: "
        f"{len({item.resource_id for item in trace})}"
    )
    
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(f"SHA256: {metadata['sha256']}")

if __name__ == "__main__":
    main()
    