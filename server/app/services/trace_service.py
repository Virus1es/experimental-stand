import csv
import hashlib
import json

from dataclasses import asdict
from pathlib import Path
from collections.abc import Iterable, Iterator

from app.models.access import ResourseAccess

class TraceService:
    """Загрузка, сохранение и проверка трасс обращений."""
    @staticmethod
    def validate(trace: Iterable[ResourseAccess]) -> list[ResourseAccess]:
        accesses = list(trace)
        previous_timestamp = -1
        
        for index, access in enumerate(accesses, start=1):
            if access.timestamp_ms < previous_timestamp:
                raise ValueError(f"Trace is not chronological at request {index}")

            previous_timestamp = access.timestamp_ms
        
        return accesses
    
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
        accesses = []
        
        with Path(path).open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(file)
            
            required_fields = {
                "timestamp_ms",
                "resource_id",
                "size_bytes",
            }
            
            if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
                raise ValueError(
                    "CSV must contain timestamp_ms, "
                    "resource_id and size_bytes columns"
                )
            
            for index, row in enumerate(reader, start=1):
                try:
                    resource_id = row["resource_id"]
                    
                    if not resource_id:
                        raise ValueError("Resource ID is empty")
                    
                    access = ResourseAccess(
                        timestamp_ms=int(row["timestamp_ms"]),
                        resource_id=resource_id,
                        size_bytes=int(row["size_bytes"])
                    )
                    
                    accesses.append(access)
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"Invalid CSV request at row {index + 1}: {error}"
                    ) from error
            
        return TraceService.validate(accesses)
    
    @staticmethod
    def save_json(
        trace: Iterable[ResourseAccess], 
        path: str | Path, 
        *,
        source: str = "unspecified",
        parameters: dict[str, object] | None = None,
    ) -> None:
        accesses = TraceService.validate(trace)
        
        metadata = TraceService.build_metadata(
            accesses,
            source=source,
            source_format="json",
            parameters=parameters
        )
        
        document = {
            "schema_version": 1,
            "metadata": metadata,
            "requests": [
                asdict(access)
                for access in accesses
            ]
        }
        
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with path.open("w", encoding="utf-8") as file:
            json.dump(
                document,
                file,
                ensure_ascii=False,
                indent=2,
            )
    
    @staticmethod
    def load_json(path: str | Path) -> list[ResourseAccess]:
        with Path(path).open(
            "r",
            encoding="utf-8-sig",
        ) as file:
            document = json.load(file)
        
        if isinstance(document, list):
            rows = document
        elif isinstance(document, dict):
            if document.get("schema_version") != 1:
                raise ValueError("Unsupported or missing trace schema_version")
            
            rows = document.get("requests")
            
            if not isinstance(rows, list):
                raise ValueError("JSON trace must contain a requests array")
        else:
            raise ValueError("JSON trace must be an object or an array")
        accesses = []
        
        for index, row in enumerate(rows, start=1):
            try:
                if not isinstance(row, dict):
                    raise ValueError("Request must be an object")
                
                resource_id = row["resource_id"]
                
                if not isinstance(resource_id, str) or not resource_id:
                    raise ValueError("Invalid resource_id")
                
                access = ResourseAccess(
                    timestamp_ms=int(row["timestamp_ms"]),
                    resource_id=resource_id,
                    size_bytes=int(row["size_bytes"])
                )
                
                accesses.append(access)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid JSON request at index {index + 1}: {error}"
                ) from error
        
        return TraceService.validate(accesses)
    
    @staticmethod
    def build_metadata(
        trace: Iterable[ResourseAccess],
        *,
        source: str,
        source_format: str,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        accesses = TraceService.validate(trace)
        
        if not source.strip():
            raise ValueError("Trace source cannot be empty")
        
        if not source_format.strip():
            raise ValueError("Trace format cannot be empty")

        canonical_trace = json.dumps(
            [asdict(access) for access in accesses],
            sort_keys=True,
            separators=(",",":"),
            ensure_ascii=False
        )
        
        checksum = hashlib.sha256(canonical_trace.encode("utf-8")).hexdigest()
        
        return {
            "source": source,
            "format": source_format,
            "request_count": len(accesses),
            "unique_resources": len({
                access.resource_id
                for access in accesses
            }),
            "timestamp_start_ms": (
                accesses[0].timestamp_ms if accesses else None
            ),
            "timestamp_end_ms": (
                accesses[-1].timestamp_ms if accesses else None
            ),
            "sha256": checksum,
            "parameters": parameters or []
        }
    
    @staticmethod
    def save_metadata(
        trace: Iterable[ResourseAccess],
        path: str | Path,
        *,
        source: str,
        source_format: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        metadata = TraceService.build_metadata(
            trace,
            source=source,
            source_format=source_format,
            parameters=parameters
        )
        
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with path.open("w", encoding="utf-8") as file:
            json.dump(
                metadata,
                file,
                ensure_ascii=False,
                indent=2,
            )
    
    @staticmethod
    def replay(trace: Iterable[ResourseAccess]) -> Iterator[ResourseAccess]:
        yield from trace