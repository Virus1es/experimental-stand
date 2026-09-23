from app.strategies.base import CacheStrategy
from app.core.registries import CACHE_STRATEGIES

def create_strategy(
    name: str,
    capacity: int,
) -> CacheStrategy:
    try:
        strategy_class = CACHE_STRATEGIES[name.lower()]
    except KeyError:
        available = ", ".join(CACHE_STRATEGIES.keys())

        raise ValueError(
            f"Unknown cache strategy '{name}'. "
            f"Available strategies: {available}"
        )

    return strategy_class(capacity=capacity)