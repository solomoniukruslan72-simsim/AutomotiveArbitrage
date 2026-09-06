"""Ingestion foundation — DTOs, нормализаторы, интерфейсы и сервис."""

from app.ingestion.dtos import (
    NormalizedListingDTO,
    NormalizedVehicleDTO,
    RawListingDTO,
    VehicleSnapshotDTO,
    compute_snapshot_content_hash,
    compute_snapshot_content_hash_from_fields,
)
from app.ingestion.interfaces import (
    AsyncIngestionSource,
    IngestionSource,
    IngestionSourceProtocol,
)
from app.ingestion.normalizer import FieldNormalizer, normalize_fuel, normalize_transmission
from app.ingestion.service import (
    BatchResult,
    IngestionItem,
    IngestionService,
    process_batch,
    process_listing_item,
)

__all__ = [
    "AsyncIngestionSource",
    "BatchResult",
    "FieldNormalizer",
    "IngestionItem",
    "IngestionService",
    "IngestionSource",
    "IngestionSourceProtocol",
    "NormalizedListingDTO",
    "NormalizedVehicleDTO",
    "RawListingDTO",
    "VehicleSnapshotDTO",
    "compute_snapshot_content_hash",
    "compute_snapshot_content_hash_from_fields",
    "normalize_fuel",
    "normalize_transmission",
    "process_batch",
    "process_listing_item",
]
