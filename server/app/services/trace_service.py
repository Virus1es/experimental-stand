import csv
from pathlib import Path
from collections.abc import Iterable, Iterator

from app.models.access import ResourseAccess

class TraceService:
    @staticmethod
    def save_csv(trace: Iterable[ResourseAccess], path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.writer(file)
            
            writer.writerow([
                "timestamp_ms",
                "resource_id",
                "size_bytes",
            ])
            
            for access in trace:
                writer.writerow([
                    access.timestamp_ms,
                    access.resource_id,
                    access.size_bytes,
                ])
    
    @staticmethod
    def load_csv(path: str | Path) -> list[ResourseAccess]:
        with Path(path).open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(file)
            
            return [
                ResourseAccess(
                    timestamp_ms=int(row["timestamp_ms"]),
                    resource_id=row["resource_id"],
                    size_bytes=int(row["size_bytes"]),
                )
                for row in reader
            ]
    
    @staticmethod
    def replay(trace: Iterable[ResourseAccess]) -> Iterator[ResourseAccess]:
        yield from trace