from dataclasses import dataclass

@dataclass(frozen=True)
class ResourcePrediction:
    resource_id: str
    probability: float
    
@dataclass(frozen=True)
class PredictionMetrics:
    total_predictions: int
    correct_predictions: int
    top_k_correct_predictions: int
    top_k: int
    
    @property
    def accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        
        return self.correct_predictions / self.total_predictions
    
    @property
    def top_k_accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        
        return self.top_k_correct_predictions / self.total_predictions
