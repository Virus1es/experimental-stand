import pytest

from pathlib import Path

from load.fixed_workload import build_fixed_workload_plan

from app.services.trace_service import TraceService
from app.services.resource_path_mapper import ResourcePathMapper

def test_fixed_workload_partition():
    """Разные пользователи получают разные части трассы."""

    resources = list(range(15))

    plans = [
        build_fixed_workload_plan(
            resource_ids=resources,
            user_index=i,
            user_count=3,
            warmup_requests=2,
            measurement_requests=3,
        )
        for i in range(3)
    ]

    assert plans[0].warmup == (0, 3)
    assert plans[0].measurement == (6, 9, 12)

    assert plans[1].warmup == (1, 4)
    assert plans[1].measurement == (7, 10, 13)

    assert plans[2].warmup == (2, 5)
    assert plans[2].measurement == (8, 11, 14)


def test_fixed_workload_is_deterministic():
    """Одинаковые параметры дают одинаковый план."""

    resources = list(range(100))

    first = build_fixed_workload_plan(
        resources, 0, 5, 3, 7
    )

    second = build_fixed_workload_plan(
        resources, 0, 5, 3, 7
    )

    assert first == second


def test_fixed_workload_no_phase_overlap():
    """Измерение продолжает прогрев без повтора позиций."""

    resources = list(range(30))

    plan = build_fixed_workload_plan(
        resources, 0, 3, 2, 4
    )

    assert plan.warmup == (0, 3)
    assert plan.measurement == (6, 9, 12, 15)


def test_fixed_workload_insufficient_resources():
    """Недостаточная длина трассы вызывает ошибку."""

    with pytest.raises(
        ValueError,
        match="Not enough resources",
    ):
        build_fixed_workload_plan(
            resource_ids=list(range(10)),
            user_index=0,
            user_count=5,
            warmup_requests=2,
            measurement_requests=5,
        )


@pytest.mark.parametrize(
    "user_index,user_count,warmup,measurement",
    [
        (0, 0, 1, 2),
        (-1, 5, 1, 2),
        (5, 5, 1, 2),
        (0, 5, -1, 2),
        (0, 5, 1, 0),
    ],
)
def test_fixed_workload_invalid_parameters(
    user_index,
    user_count,
    warmup,
    measurement,
):
    with pytest.raises(ValueError):
        build_fixed_workload_plan(
            resource_ids=list(range(100)),
            user_index=user_index,
            user_count=user_count,
            warmup_requests=warmup,
            measurement_requests=measurement,
        )

def test_fixed_workload_real_trace():
    server_dir = Path(__file__).resolve().parents[1]

    trace = TraceService.load_csv(
        str(server_dir / "data/traces/web_workload.csv")
    )

    split_index = int(len(trace) * 0.8)

    train_trace = trace[:split_index]
    test_trace = trace[split_index:]

    mapper = ResourcePathMapper(
        access.resource_id for access in train_trace
    )

    known_paths = {
        access.resource_id for access in train_trace
    }

    resource_ids = [
        mapper.id_for(access.resource_id)
        for access in test_trace
        if access.resource_id in known_paths
    ]

    plans = [
        build_fixed_workload_plan(
            resource_ids=resource_ids,
            user_index=i,
            user_count=5,
            warmup_requests=13,
            measurement_requests=28,
        )
        for i in range(5)
    ]

    assert len(resource_ids) == 1992
    assert sum(len(plan.warmup) for plan in plans) == 65
    assert sum(len(plan.measurement) for plan in plans) == 140

    for plan in plans:
        assert len(plan.warmup) == 13
        assert len(plan.measurement) == 28