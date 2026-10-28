import pytest

from app.models.web_workload import WebWorkloadConfig
from app.services.web_workload_generator import (
    WebWorkloadGenerator,
)


def test_generates_expected_number_of_requests():
    config = WebWorkloadConfig(
        num_products=10,
        num_requests=100,
    )

    trace = WebWorkloadGenerator(config).generate()

    assert len(trace) == 100


def test_generation_is_reproducible():
    config = WebWorkloadConfig(
        num_products=20,
        num_requests=500,
        seed=42,
    )

    first = WebWorkloadGenerator(config).generate()
    second = WebWorkloadGenerator(config).generate()

    assert first == second


def test_timestamps_are_non_decreasing():
    config = WebWorkloadConfig(
        num_requests=200,
        seed=42,
    )

    trace = WebWorkloadGenerator(config).generate()

    timestamps = [
        access.timestamp_ms
        for access in trace
    ]

    assert timestamps == sorted(timestamps)


def test_resource_sizes_are_consistent():
    config = WebWorkloadConfig(
        num_products=10,
        num_requests=300,
    )

    trace = WebWorkloadGenerator(config).generate()

    sizes = {}

    for access in trace:
        if access.resource_id in sizes:
            assert (
                sizes[access.resource_id]
                == access.size_bytes
            )
        else:
            sizes[access.resource_id] = access.size_bytes


def test_workload_contains_web_resources():
    config = WebWorkloadConfig(
        num_products=20,
        num_requests=500,
    )

    trace = WebWorkloadGenerator(config).generate()

    resources = {
        access.resource_id
        for access in trace
    }

    assert "/api/home" in resources
    assert "/api/catalog" in resources

    assert any(
        resource.startswith("/api/products/")
        for resource in resources
    )


def test_invalid_config_is_rejected():
    with pytest.raises(ValueError):
        WebWorkloadConfig(num_products=0)

    with pytest.raises(ValueError):
        WebWorkloadConfig(num_requests=0)

    with pytest.raises(ValueError):
        WebWorkloadConfig(zipf_alpha=-1)