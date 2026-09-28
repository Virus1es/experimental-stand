from app.services.trace_generator import TraceGenerator
from app.services.trace_service import TraceService


generator = TraceGenerator(
    num_resources=100,
    zipf_alpha=1.2,
    seed=42,
)

trace = generator.generate(
    num_requests=10000,
    interval_ms=50,
)

TraceService.save_csv(
    trace,
    "data/traces/sample.csv",
)

print(f"Generated {len(trace)} requests")
print(f"First request: {trace[0]}")