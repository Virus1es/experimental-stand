import re

from collections.abc import Iterable, Sequence

from app.models.prediction import ResourcePrediction
from app.services.http_prefetch_coordinator import PredictionProvider

class ResourcePathMapper:
    """Сопоставляет URL веб-трассы с ID HTTP-ресурсов"""
    
    def __init__(self, known_paths: Iterable[str]) -> None:
        paths = sorted(set(known_paths))
        
        self._path_to_id = {
            path: index + 1
            for index, path in enumerate(paths)
        }
        
        self._id_to_path = {
            resource_id: path
            for path, resource_id in self._path_to_id.items()
        }
    
    def register(self, path: str) -> int:
        """Регистрирует новый путь при его появлении"""
        
        if path not in self._path_to_id:
            resource_id = len(self._path_to_id) + 1
            
            self._path_to_id[path] = resource_id
            self._id_to_path[resource_id] = path
        
        return self._path_to_id[path]
    
    def id_for(self, path: str) -> int:
        """Возвращает ID уже известного ресурса"""
        
        return self._path_to_id[path]
    
    def http_path(self, path: str) -> str:
        """Преобразует исходный URL в маршрут стенда"""
        
        resource_id = self.id_for(path)
        
        return f"/api/resources/{resource_id}"
    
    def original_path(self, http_path: str) -> str:
        """Восстанавливает исходный URL по маршруту"""
        
        match = re.fullmatch(
            r"/api/resources/([1-9]\d*)",
            http_path,
        )
        
        if match is None:
            raise ValueError("Invalid HTTP resource path")
        
        resource_id = int(match.group(1))
        
        return self._id_to_path[resource_id]
    

class PathMappedPredictor:
    """Адаптирует идентификаторы ресурсов для ML-модели"""
    
    def __init__(
        self,
        predictor: PredictionProvider,
        mapper: ResourcePathMapper
    ) -> None:
        self._predictor = predictor
        self._mapper = mapper
    
    def predict_next(
        self,
        history: Sequence[str],
        top_k: int = 3,
    ) -> list[ResourcePrediction]:
        original_history = [
            self._mapper.original_path(path)
            for path in history
        ]
        
        predictions = self._predictor.predict_next(
            original_history,
            top_k=top_k
        )
        
        return [
            ResourcePrediction(
                resource_id=self._mapper.http_path(prediction.resource_id),
                probability=prediction.probability,
            )
            for prediction in predictions
        ]