from app.strategies.base import CacheStrategy
from app.strategies.factory import create_strategy

class CacheService:

    def __init__(self, strategy: str, capacity: int):
        self._strategy: CacheStrategy = create_strategy(name=strategy, capacity=capacity)
        
    def get(self, key: str) -> str | None:
        return self._strategy.get(key)
    
    def put(self, key: str, value: str) -> str | None:
        self._strategy.put(key, value)
    
    def remove(self, key: str) -> None:
        self._strategy.remove(key)
    
    def clear(self) -> None:
        self._strategy.clear()
    
    def get_metrics(self):
        self._strategy.get_metrics()
    
    def size(self) -> int:
        return len(self._strategy)