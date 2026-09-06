"""DTOs для ingestion foundation.

Слой DTO не зависит от SQLAlchemy-моделей (app/models.py:13) и
предназначен для передачи данных между источником, нормализацией и
сохранением. Используется Pydantic v2 для валидации.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Общие ограничения, синхронизированы с миграцией 20260904_0001_core_inventory.py
# и моделями app/models.py
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_HEX64_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def _ensure_tz_aware(value: datetime) -> datetime:
    """Гарантирует timezone-aware datetime, приводит naive к UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _canonical_json(value: Any) -> str:
    """Канонический JSON с сортировкой ключей и разделителями.

    Используется для стабильного хэша снимка.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_snapshot_content_hash_from_fields(
    *,
    price: Decimal | None,
    currency: str | None,
    mileage_km: int | None,
    equipment_hash: str | None,
    condition_data: dict[str, Any] | None,
    inputs_snapshot: dict[str, Any] | None,
    raw_data: dict[str, Any] | None,
) -> str:
    """Вычисляет стабильный SHA-256 хэш канонического содержимого снимка.

    Не включает технические поля: snapshot_id, listing_id, captured_at,
    snapshot_content_hash.
    """
    # Нормализуем Decimal к строке без экспоненты, сохраняя 2 знака при наличии
    price_str: str | None = None
    if price is not None:
        # price уже валидирован как Decimal(12,2)
        price_str = format(price, "f")

    payload: dict[str, Any] = {
        "condition_data": condition_data,
        "currency": currency,
        "equipment_hash": equipment_hash,
        "inputs_snapshot": inputs_snapshot,
        "mileage_km": mileage_km,
        "price": price_str,
        "raw_data": raw_data,
    }
    canonical = _canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RawListingDTO(BaseModel):
    """Исходное объявление как получено от внешнего источника.

    Содержит минимум идентификаторов и сырые данные без нормализации.
    Не выполняет сетевых запросов — только контейнер данных.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(
        min_length=1,
        max_length=50,
        description="Идентификатор источника (FK -> source.source_id)",
    )
    source_listing_id: str = Field(
        min_length=1,
        max_length=255,
        description="Внешний ID объявления в системе источника",
    )
    fetched_at: datetime = Field(
        description="Момент получения данных от источника (UTC)",
    )
    raw_data: dict[str, Any] = Field(
        description="Сырой payload источника, как есть (JSON-совместимый)",
    )
    url: str | None = Field(
        default=None,
        max_length=2048,
        description="Оригинальный URL объявления, если доступен",
    )
    seller_type: str | None = Field(
        default=None,
        max_length=20,
        description="Тип продавца как в источнике (dealer/private/...)",
    )

    @field_validator("fetched_at", mode="after")
    @classmethod
    def _validate_fetched_at(cls, value: datetime) -> datetime:
        return _ensure_tz_aware(value)

    @field_validator("source_id", mode="after")
    @classmethod
    def _strip_source_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_id не может быть пустым")
        return value.strip()

    @field_validator("source_listing_id", mode="after")
    @classmethod
    def _strip_external_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_listing_id не может быть пустым")
        return value.strip()


class NormalizedVehicleDTO(BaseModel):
    """Нормализованный автомобиль — каноническое представление ТС.

    Соответствует полям app/models.py:31 Vehicle без PK/меток времени.
    VIN валидируется по ISO 3779 (без I, O, Q).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    vin: str | None = Field(
        default=None,
        min_length=17,
        max_length=17,
        pattern=r"^[A-HJ-NPR-Z0-9]{17}$",
        description="VIN 17 символов, без I/O/Q, верхний регистр",
    )
    make: str = Field(min_length=1, max_length=100, description="Марка")
    model: str = Field(min_length=1, max_length=100, description="Модель")
    generation: str | None = Field(default=None, max_length=100, description="Поколение/кузов")
    year: int | None = Field(default=None, ge=1886, le=2100, description="Год выпуска")
    engine_type: str | None = Field(default=None, max_length=30, description="Тип двигателя")
    transmission: str | None = Field(default=None, max_length=30, description="КПП")
    engine_volume: int | None = Field(
        default=None, ge=0, le=10000, description="Объём двигателя, куб.см"
    )
    power_hp: int | None = Field(default=None, ge=0, le=3000, description="Мощность, л.с.")
    drive_type: str | None = Field(default=None, max_length=10, description="Привод")

    @field_validator("vin", mode="before")
    @classmethod
    def _normalize_vin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            v = value.strip().upper()
            if v == "":
                return None
            return v
        return value  # type: ignore[return-value]

    @field_validator("make", "model", mode="after")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("поле не может быть пустым")
        return value.strip()


class NormalizedListingDTO(BaseModel):
    """Нормализованное объявление — связка listing без Snapshot.

    Соответствует app/models.py:20 Listing.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=50)
    source_listing_id: str = Field(min_length=1, max_length=255)
    seller_type: str | None = Field(default=None, max_length=20)
    status: Literal["ACTIVE", "SOLD", "ARCHIVED", "INACTIVE"] = Field(
        default="ACTIVE",
        description="Статус объявления",
    )
    first_seen: datetime = Field(description="Первое появление объявления")
    last_seen: datetime = Field(description="Последнее подтверждение наличия")

    @field_validator("first_seen", "last_seen", mode="after")
    @classmethod
    def _ensure_tz_listing(cls, value: datetime) -> datetime:
        return _ensure_tz_aware(value)

    @field_validator("last_seen", mode="after")
    @classmethod
    def _validate_period(cls, value: datetime, info) -> datetime:  # type: ignore[no-untyped-def]
        first = info.data.get("first_seen")
        if first is not None and value < first:
            raise ValueError("last_seen не может быть раньше first_seen")
        return value


class VehicleSnapshotDTO(BaseModel):
    """Снимок состояния объявления на момент времени.

    Соответствует app/models.py:57 VehicleSnapshot.
    Цена хранится как Decimal(12,2), валюта — ISO 4217.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    snapshot_id: uuid.UUID | None = Field(default=None, description="PK снимка, None до сохранения")
    listing_id: uuid.UUID | None = Field(
        default=None, description="FK -> listing.listing_id, None до линковки"
    )
    captured_at: datetime = Field(description="Момент снимка (UTC)")
    price: Decimal | None = Field(
        default=None,
        ge=Decimal(0),
        max_digits=12,
        decimal_places=2,
        description="Цена, Numeric(12,2)",
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Валюта ISO 4217 (EUR/USD/UAH)",
    )
    mileage_km: int | None = Field(default=None, ge=0, le=5_000_000, description="Пробег, км")
    equipment_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-fA-F0-9]{64}$",
        description="SHA-256 хэш комплектации (hex, 64 символа)",
    )
    snapshot_content_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-fA-F0-9]{64}$",
        description="SHA-256 хэш канонического содержимого (без timestamp-полей)",
    )
    condition_data: dict[str, Any] | None = Field(default=None, description="Состояние/повреждения")
    inputs_snapshot: dict[str, Any] | None = Field(
        default=None, description="Снимок входных параметров расчёта"
    )
    raw_data: dict[str, Any] | None = Field(default=None, description="Сырой фрагмент для аудита")

    @model_validator(mode="after")
    def _compute_hash_if_missing(self) -> VehicleSnapshotDTO:
        """Автоматически вычисляет snapshot_content_hash, если не задан.

        Не включает captured_at, listing_id, snapshot_id.
        """
        if self.snapshot_content_hash is None:
            object.__setattr__(
                self,
                "snapshot_content_hash",
                compute_snapshot_content_hash_from_fields(
                    price=self.price,
                    currency=self.currency,
                    mileage_km=self.mileage_km,
                    equipment_hash=self.equipment_hash,
                    condition_data=self.condition_data,
                    inputs_snapshot=self.inputs_snapshot,
                    raw_data=self.raw_data,
                ),
            )
        return self

    def compute_content_hash(self) -> str:
        """Возвращает детерминированный хэш содержимого (без timestamp)."""
        return compute_snapshot_content_hash_from_fields(
            price=self.price,
            currency=self.currency,
            mileage_km=self.mileage_km,
            equipment_hash=self.equipment_hash,
            condition_data=self.condition_data,
            inputs_snapshot=self.inputs_snapshot,
            raw_data=self.raw_data,
        )

    @field_validator("captured_at", mode="after")
    @classmethod
    def _ensure_tz_snapshot(cls, value: datetime) -> datetime:
        return _ensure_tz_aware(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            v = value.strip().upper()
            if v == "":
                return None
            return v
        return value  # type: ignore[return-value]

    @field_validator("currency", mode="after")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _CURRENCY_RE.match(value):
            raise ValueError("currency должен быть 3 заглавные буквы (ISO 4217)")
        return value

    @field_validator("equipment_hash", mode="after")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _HEX64_RE.match(value):
            raise ValueError("equipment_hash должен быть hex 64 символа")
        return value


def compute_snapshot_content_hash(snapshot: VehicleSnapshotDTO) -> str:
    """Безопасная функция для вычисления хэша снимка вне DTO.

    Использует те же канонические поля, что и DTO.compute_content_hash().
    """
    return compute_snapshot_content_hash_from_fields(
        price=snapshot.price,
        currency=snapshot.currency,
        mileage_km=snapshot.mileage_km,
        equipment_hash=snapshot.equipment_hash,
        condition_data=snapshot.condition_data,
        inputs_snapshot=snapshot.inputs_snapshot,
        raw_data=snapshot.raw_data,
    )
