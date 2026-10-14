from __future__ import annotations

from collections.abc import Iterable, Sequence

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from app.models.access import ResourseAccess
from app.models.prediction import (
    PredictionMetrics,
    ResourcePrediction,
)

class LogisticRegressionPredictor:
    """Прогнозирует следующий ресурс по истории обращений."""
    def __init__(
        self, 
        history_size: int = 3, 
        random_state: int = 42
    ) -> None:
        if history_size <= 0:
            raise ValueError("History size must be positive")
        
        self.history_size = history_size
        self.random_state = random_state
        
        self._vectorizer: DictVectorizer | None = None
        self._model: LogisticRegression | None = None
        self._single_class: str | None = None
        
        self._initial_history: list[str] = []
        self._fitted = False
    
    def _make_features(self, history: Sequence[str]) -> dict[str, str]:
        if len(history) < self.history_size:
            raise ValueError(
                f"At least {self.history_size} "
                "historical requests are required"
            )
        
        recent = history[-self.history_size:]
        
        return {
            f"previous_{offset}": recent[-offset]
            for offset in range(1, self.history_size + 1)
        }
    
    def fit(self, trace: Iterable[ResourseAccess]) -> LogisticRegressionPredictor:
        """Обучает модель на последовательности запросов."""
        
        resource_ids = [
            access.resource_id
            for access in trace
        ]
        
        if len(resource_ids) <= self.history_size:
            raise ValueError(
                "Training trace must contain more requests "
                "than history_size"
            )
        
        self._fitted = False
        self._vectorizer = None
        self._model = None
        self._single_class = None
        
        features = []
        targets = []
        
        for index in range(
            self.history_size,
            len(resource_ids),
        ):
            history = resource_ids[
                index - self.history_size:index
            ]
            
            features.append(self._make_features(history))
            
            targets.append(resource_ids[index])
        
        self._initial_history = resource_ids[-self.history_size:]
        
        unique_targets = set(targets)
        
        if len(unique_targets) == 1:
            self._single_class = targets[0]
            self._fitted = True
            return self
        
        self._vectorizer = DictVectorizer(
            sparse=True
        )
        
        encoded_features = (
            self._vectorizer.fit_transform(features)
        )
        
        self._model = LogisticRegression(
            max_iter=1000,
            random_state=self.random_state,
        )
        
        self._model.fit(
            encoded_features,
            targets,
        )
        
        self._fitted = True
        
        return self
    
    def predict_next(self, history: Sequence[str], top_k: int = 3) -> list[ResourcePrediction]:
        """Возвращает top_k наиболее вероятных ресурсов."""
        
        if not self._fitted:
            raise RuntimeError("Prediction must be fitted before prediction")
        
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        
        features = self._make_features(history)
        
        if self._single_class is not None:
            return [
                ResourcePrediction(
                    resource_id=self._single_class,
                    probability=1.0,
                )
            ]
        
        assert self._vectorizer is not None
        assert self._model is not None
        
        encoded = self._vectorizer.transform(features)
        
        probabilities = self._model.predict_proba(encoded)[0]
        
        predictions = [
            ResourcePrediction(
                resource_id=resource_id,
                probability=float(probability),
            )
            for resource_id, probability in zip(
                self._model.classes_,
                probabilities,
            )
        ]
        
        predictions.sort(
            key=lambda item: item.probability,
            reverse=True
        )
        
        return predictions[:top_k]
    
    def evaluate(self, test_trace: Iterable[ResourseAccess], top_k: int = 3) -> PredictionMetrics:
        """Оценивает прогнозы на последующей части трассы.

        После каждого прогноза в историю добавляется фактический
        запрос. Это имитирует последовательную работу модели,
        получающей информацию о поступающих запросах.
        """
        
        if not self._fitted:
            raise RuntimeError("Predictor must be fitted before evaluation")
        
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        
        history = self._initial_history.copy()
        
        total_predictions = 0
        correct_predictions = 0
        top_k_correct_predictions = 0
        
        for access in test_trace:
            predictions = self.predict_next(
                history,
                top_k=top_k,
            )
            
            predicted_ids = [
                prediction.resource_id
                for prediction in predictions
            ]
            
            total_predictions += 1
            
            if(predicted_ids and predicted_ids[0] == access.resource_id):
                correct_predictions += 1
            
            if access.resource_id in predicted_ids:
                top_k_correct_predictions += 1
                
            history.append(access.resource_id)
            history = history[-self.history_size:]
        
        return PredictionMetrics(
            total_predictions=total_predictions,
            correct_predictions=correct_predictions,
            top_k_correct_predictions=top_k_correct_predictions,
            top_k=top_k,
        )