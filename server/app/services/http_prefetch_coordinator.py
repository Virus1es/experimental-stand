import re

from collections import deque
from collections.abc import Sequence
from typing import Protocol

from app.models.prediction import ResourcePrediction

class PredictionProvider(Protocol):
    def predict_next(
        self,
        history: Sequence[str],
        top_k: int = 3,
    ) -> list[ResourcePrediction]:
        ...
    
class HttpPrefetchCoordinator:
    def __init__(
        self,
        predictor: PredictionProvider,
        history_size: int = 3,
        initial_history: Sequence[str] = (),
        probability_threshold: float = 0.2,
        max_prefetch: int = 3,
    ) -> None:
        if history_size <= 0:
            raise ValueError("history_size must be positive")
        
        if not 0 <= probability_threshold <= 1:
            raise ValueError("probability_threshold must be between 0 and 1")
        
        if max_prefetch <= 0:
            raise ValueError("max_prefetch must be positive")
        
        self._predictor = predictor
        self._history_size = history_size
        self._threshold = probability_threshold
        self._max_prefetch = max_prefetch
        self._history = deque(initial_history, maxlen=history_size)
    
    def observe_and_select(self, resource_id: int) -> list[int]:
        current_resource = f"/api/resources/{resource_id}"
        
        self._history.append(current_resource)
        
        if len(self._history) < self._history_size:
            return []
        
        predictions = self._predictor.predict_next(
            list(self._history),
            top_k=self._max_prefetch,
        )
        
        selected: list[int] = []
        seen: set[int] = set()
        
        for prediction in predictions:
            if len(selected) >= self._max_prefetch:
                break;
            
            if prediction.probability < self._threshold:
                continue
            
            match = re.fullmatch(
                r"/api/resources/([1-9]\d*)",
                prediction.resource_id
            )
            
            if match is None:
                continue
            
            predicted_id = int(match.group(1))
            
            if predicted_id == resource_id:
                continue
            
            if predicted_id in seen:
                continue
            
            seen.add(predicted_id)
            selected.append(predicted_id)
        
        return selected