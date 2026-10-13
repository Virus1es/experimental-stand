import json

import pytest

from app.models.access import ResourseAccess
from app.services.trace_service import TraceService


@pytest.fixture
def sample_trace():
    return [
        ResourseAccess(0, "A", 1024),
        ResourseAccess(100, "B", 2048),
        ResourseAccess(200, "A", 1024),
    ]


def test_json_roundtrip(sample_trace, tmp_path):
    path = tmp_path / "trace.json"

    TraceService.save_json(
        sample_trace,
        path,
        source="test",
        parameters={"seed": 42},
    )

    restored = TraceService.load_json(path)

    assert restored == sample_trace


def test_json_metadata(sample_trace, tmp_path):
    path = tmp_path / "trace.json"

    TraceService.save_json(
        sample_trace,
        path,
        source="test",
        parameters={"seed": 42},
    )

    with path.open("r", encoding="utf-8") as file:
        document = json.load(file)

    metadata = document["metadata"]

    assert metadata["source"] == "test"
    assert metadata["request_count"] == 3
    assert metadata["unique_resources"] == 2
    assert metadata["timestamp_start_ms"] == 0
    assert metadata["timestamp_end_ms"] == 200
    assert len(metadata["sha256"]) == 64
    assert metadata["parameters"]["seed"] == 42


def test_same_trace_has_same_checksum(sample_trace):
    first = TraceService.build_metadata(
        sample_trace,
        source="test",
        source_format="csv",
    )

    second = TraceService.build_metadata(
        sample_trace,
        source="another source",
        source_format="json",
    )

    assert first["sha256"] == second["sha256"]


def test_rejects_out_of_order_trace():
    trace = [
        ResourseAccess(100, "A", 1024),
        ResourseAccess(50, "B", 2048),
    ]

    with pytest.raises(ValueError, match="not chronological"):
        TraceService.validate(trace)


def test_load_json_rejects_invalid_resource(tmp_path):
    path = tmp_path / "invalid.json"

    path.write_text(
        json.dumps({
            "schema_version": 1,
            "requests": [
                {
                    "timestamp_ms": 0,
                    "resource_id": "",
                    "size_bytes": 1024,
                }
            ],
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid JSON request"):
        TraceService.load_json(path)


def test_csv_and_json_produce_same_checksum(
    sample_trace,
    tmp_path,
):
    csv_path = tmp_path / "trace.csv"
    json_path = tmp_path / "trace.json"

    TraceService.save_csv(sample_trace, csv_path)

    loaded_csv = TraceService.load_csv(csv_path)

    TraceService.save_json(
        loaded_csv,
        json_path,
        source="test",
    )

    loaded_json = TraceService.load_json(json_path)

    csv_metadata = TraceService.build_metadata(
        loaded_csv,
        source="test",
        source_format="csv",
    )

    json_metadata = TraceService.build_metadata(
        loaded_json,
        source="test",
        source_format="json",
    )

    assert csv_metadata["sha256"] == json_metadata["sha256"]