from dataclasses import dataclass
from typing import Sequence

@dataclass(frozen=True)
class FixedWorkloadPlan:
    """План запросов одного виртуального пользователя"""
    
    user_index: int
    warmup: tuple[int, ...]
    measurement: tuple[int, ...]
    
def build_fixed_workload_plan(
    resource_ids: Sequence[int],
    user_index: int,
    user_count: int,
    warmup_requests: int,
    measurement_requests: int,
) -> FixedWorkloadPlan:
    """Создаёт детерминированный план нагрузки"""
    
    if user_count <= 0:
        raise ValueError("user_count must be positive")
    
    if not 0 <= user_index < user_count:
        raise ValueError("Invalid user index")
    
    if warmup_requests < 0:
        raise ValueError("warmup_requests must be non-negative")
    
    if measurement_requests <= 0:
        raise ValueError("measurement_requests must be positive")
    
    user_resources = resource_ids[user_index::user_count]
    
    required = warmup_requests + measurement_requests
    
    if required > len(user_resources):
        raise ValueError(
            f"Not enough resources for user {user_index}: "
            f"required={required}, "
            f"available={len(user_resources)}"
        )
    
    warmup = tuple(user_resources[:warmup_requests])
    
    measurement = tuple(user_resources[warmup_requests:required])
    
    return FixedWorkloadPlan(
        user_index=user_index,
        warmup=warmup,
        measurement=measurement,
    )