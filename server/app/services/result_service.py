import csv
import json

from dataclasses import asdict
from pathlib import Path

from app.models.experiment import ExperimentResult

class ResultService:
    
    @staticmethod
    def save_json(
        result: ExperimentResult,
        path: str | Path,
    ) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with path.open("w", encoding="utf-8") as file:
            json.dump(
                asdict(result),
                file,
                ensure_ascii=False,
                indent=2,
            )
    
    @staticmethod
    def save_requests_csv(
        result: ExperimentResult,
        path: str | Path,
    ) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        fields = [
            "timestamp_ms",
            "resource_id",
            "size_bytes",
            "cache_hit",
            "latency_ms",
            "origin_request",
            "origin_bytes",
            "cache_size",
        ]
        
        with path.open(
            "w",
            newline="",
            encoding="utf-8"
        ) as file:
            write = csv.DictWriter(
                file,
                fieldnames=fields,
            )
            
            write.writeheader()
            
            for request in result.requests:
                write.writerow(asdict(request))
    
    @staticmethod
    def save_summary_csv(
        results: list[ExperimentResult],
        path: str | Path,
    ) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        fields = [
            "strategy",
            "capacity",
            "total_requests",
            "hits",
            "misses",
            "hit_rate",
            "miss_rate",
            "total_latency_ms",
            "average_latency_ms",
            "origin_requests",
            "client_bytes",
            "origin_bytes",
        ]
        
        with path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
            )
            
            writer.writeheader()
            
            for result in results:
                data = asdict(result)
                
                writer.writerow({
                    field: data[field]
                    for field in fields
                })