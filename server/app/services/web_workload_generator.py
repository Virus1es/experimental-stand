import random

from app.models.access import ResourseAccess
from app.models.web_workload import WebWorkloadConfig

class WebWorkloadGenerator:
    """Генератор последовательностей запросов интернет-магазина."""
    
    def __init__(self, config: WebWorkloadConfig) -> None:
        self.config = config
        self._rng = random.Random(config.seed)
        
        self._products = [
            f"/api/products/{index}"
            for index in range(1, config.num_products + 1)
        ]
        
        self._weights = [
            1.0 / (rank ** config.zipf_alpha)
            for rank in range(1, config.num_products + 1)
        ]
        
        self._sizes = {
            "/api/home": 8 * 1024,
            "/api/catalog": 24 * 1024,
            "/api/cart": 4 * 1024,
        }
        
        for resource_id in self._products:
            self._sizes[resource_id] = self._rng.randint(4 * 1024, 64 * 1024)
    
    def _choose_product(self) -> str:
        """Выбирает товар с учётом его популярности."""
        
        return self._rng.choices(
            population=self._products,
            weights=self._weights,
            k=1,
        )[0]
    
    def _generate_session(self) -> list[str]:
        """Формирует один сценарий поведения пользователя."""
        
        product_id = self._choose_product()
        
        if self._rng.random() < 0.7:
            session = [
                "/api/home",
                "/api/catalog",
                product_id
            ]
        else:
            session = [
                "/api/home",
                product_id
            ]
        
        if self._rng.random() < 0.25:
            session.append(product_id)
        
        if self._rng.random() < 0.35:
            session.append("/api/cart")
            
        return session
    
    def generate(self) -> list[ResourseAccess]:
        """Генерирует трассу заданной длины."""
        
        result: list[ResourseAccess] = []
        timestamp_ms = 0
        
        while len(result) < self.config.num_requests:
            session = self._generate_session()
            
            for resource_id in session:
                if len(result) >= self.config.num_requests:
                    break
                
                result.append(
                    ResourseAccess(
                        timestamp_ms=timestamp_ms,
                        resource_id=resource_id,
                        size_bytes=self._sizes[resource_id],
                    )
                )
                
                timestamp_ms += self.config.request_interval_ms
                
            timestamp_ms += self.config.session_gap_ms
        
        return result