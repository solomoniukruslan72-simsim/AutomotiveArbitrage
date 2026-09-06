"""Базовые тесты DTO ingestion foundation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ingestion.dtos import (
    NormalizedListingDTO,
    NormalizedVehicleDTO,
    RawListingDTO,
    VehicleSnapshotDTO,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# RawListingDTO
# ---------------------------------------------------------------------------


def test_raw_listing_valid_minimal() -> None:
    dto = RawListingDTO(
        source_id="mobile.de",
        source_listing_id="12345",
        fetched_at=_utc_now(),
        raw_data={"title": "BMW 530d", "price": 25000},
    )
    assert dto.source_id == "mobile.de"
    assert dto.seller_type is None
    assert dto.url is None
    assert dto.raw_data["title"] == "BMW 530d"


def test_raw_listing_valid_full() -> None:
    dto = RawListingDTO(
        source_id="autoscout24",
        source_listing_id="abc-999",
        fetched_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        raw_data={"id": "abc-999"},
        url="https://example.com/listing/abc-999",
        seller_type="dealer",
    )
    assert str(dto.url) == "https://example.com/listing/abc-999"
    assert dto.seller_type == "dealer"


def test_raw_listing_fetched_at_naive_becomes_utc() -> None:
    naive = datetime(2026, 9, 5, 12, 0)  # noqa: DTZ001  # без tz, проверяем авто-нормализацию
    dto = RawListingDTO(
        source_id="s1",
        source_listing_id="1",
        fetched_at=naive,
        raw_data={},
    )
    assert dto.fetched_at.tzinfo is not None
    assert dto.fetched_at.tzinfo == UTC


def test_raw_listing_invalid_empty_ids() -> None:
    with pytest.raises(ValidationError):
        RawListingDTO(
            source_id="",
            source_listing_id="1",
            fetched_at=_utc_now(),
            raw_data={},
        )
    with pytest.raises(ValidationError):
        RawListingDTO(
            source_id="s1",
            source_listing_id="   ",
            fetched_at=_utc_now(),
            raw_data={},
        )


def test_raw_listing_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        RawListingDTO(  # type: ignore[call-arg]
            source_id="s1",
            source_listing_id="1",
            fetched_at=_utc_now(),
            raw_data={},
            unknown_field="oops",
        )


def test_raw_listing_seller_type_too_long() -> None:
    with pytest.raises(ValidationError):
        RawListingDTO(
            source_id="s1",
            source_listing_id="1",
            fetched_at=_utc_now(),
            raw_data={},
            seller_type="x" * 21,
        )


# ---------------------------------------------------------------------------
# NormalizedVehicleDTO
# ---------------------------------------------------------------------------


def test_normalized_vehicle_valid_full() -> None:
    dto = NormalizedVehicleDTO(
        vin="WBA5A31000HZ12345",
        make="BMW",
        model="5 Series",
        generation="G30",
        year=2020,
        engine_type="diesel",
        transmission="automatic",
        engine_volume=2993,
        power_hp=265,
        drive_type="AWD",
    )
    assert dto.vin == "WBA5A31000HZ12345"
    assert dto.make == "BMW"
    assert dto.year == 2020


def test_normalized_vehicle_vin_normalizes_to_upper() -> None:
    dto = NormalizedVehicleDTO(
        vin="wba5a31000hz12345",
        make="BMW",
        model="X5",
    )
    assert dto.vin == "WBA5A31000HZ12345"


def test_normalized_vehicle_vin_none_allowed() -> None:
    dto = NormalizedVehicleDTO(make="Audi", model="A6", vin=None)
    assert dto.vin is None
    dto2 = NormalizedVehicleDTO(make="Audi", model="A6")
    assert dto2.vin is None


def test_normalized_vehicle_invalid_vin_pattern() -> None:
    with pytest.raises(ValidationError):
        NormalizedVehicleDTO(make="BMW", model="X5", vin="INVALID")
    with pytest.raises(ValidationError):
        # содержит запрещённые I, O, Q
        NormalizedVehicleDTO(make="BMW", model="X5", vin="WBA5A31000HZ1234I")


def test_normalized_vehicle_blank_make_model() -> None:
    with pytest.raises(ValidationError):
        NormalizedVehicleDTO(make="   ", model="X5")
    with pytest.raises(ValidationError):
        NormalizedVehicleDTO(make="BMW", model="")


def test_normalized_vehicle_year_bounds() -> None:
    with pytest.raises(ValidationError):
        NormalizedVehicleDTO(make="BMW", model="X5", year=1800)
    with pytest.raises(ValidationError):
        NormalizedVehicleDTO(make="BMW", model="X5", year=2200)


def test_normalized_vehicle_engine_volume_negative() -> None:
    with pytest.raises(ValidationError):
        NormalizedVehicleDTO(make="BMW", model="X5", engine_volume=-1)


# ---------------------------------------------------------------------------
# NormalizedListingDTO
# ---------------------------------------------------------------------------


def test_normalized_listing_valid() -> None:
    first = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    last = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    dto = NormalizedListingDTO(
        source_id="mobile.de",
        source_listing_id="999",
        first_seen=first,
        last_seen=last,
    )
    assert dto.status == "ACTIVE"
    assert dto.seller_type is None


def test_normalized_listing_status_literal() -> None:
    first = datetime(2026, 9, 1, tzinfo=UTC)
    last = datetime(2026, 9, 2, tzinfo=UTC)
    dto = NormalizedListingDTO(
        source_id="s1",
        source_listing_id="1",
        status="SOLD",
        first_seen=first,
        last_seen=last,
    )
    assert dto.status == "SOLD"
    with pytest.raises(ValidationError):
        NormalizedListingDTO(
            source_id="s1",
            source_listing_id="1",
            status="UNKNOWN",  # type: ignore[arg-type]
            first_seen=first,
            last_seen=last,
        )


def test_normalized_listing_last_before_first() -> None:
    first = datetime(2026, 9, 5, tzinfo=UTC)
    last = datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="last_seen"):
        NormalizedListingDTO(
            source_id="s1",
            source_listing_id="1",
            first_seen=first,
            last_seen=last,
        )


def test_normalized_listing_naive_datetimes_normalized() -> None:
    dto = NormalizedListingDTO(
        source_id="s1",
        source_listing_id="1",
        first_seen=datetime(2026, 9, 1, 10, 0),  # noqa: DTZ001
        last_seen=datetime(2026, 9, 2, 10, 0),  # noqa: DTZ001
    )
    assert dto.first_seen.tzinfo is not None
    assert dto.last_seen.tzinfo is not None


# ---------------------------------------------------------------------------
# VehicleSnapshotDTO
# ---------------------------------------------------------------------------


def test_vehicle_snapshot_valid_minimal() -> None:
    dto = VehicleSnapshotDTO(captured_at=_utc_now())
    assert dto.price is None
    assert dto.currency is None
    assert dto.listing_id is None
    assert dto.snapshot_id is None


def test_vehicle_snapshot_valid_full() -> None:
    lid = uuid.uuid4()
    sid = uuid.uuid4()
    dto = VehicleSnapshotDTO(
        snapshot_id=sid,
        listing_id=lid,
        captured_at=_utc_now(),
        price=Decimal("24999.99"),
        currency="eur",
        mileage_km=123456,
        equipment_hash="a" * 64,
        condition_data={"accident": False},
        inputs_snapshot={"fx": 1.0},
        raw_data={"price": "24999.99"},
    )
    assert dto.currency == "EUR"
    assert dto.price == Decimal("24999.99")
    assert dto.equipment_hash == "a" * 64
    assert dto.listing_id == lid


def test_vehicle_snapshot_currency_normalized_and_validated() -> None:
    dto = VehicleSnapshotDTO(captured_at=_utc_now(), currency="usd")
    assert dto.currency == "USD"
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), currency="EURO")
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), currency="12A")


def test_vehicle_snapshot_price_negative() -> None:
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), price=Decimal("-1.00"))


def test_vehicle_snapshot_price_precision() -> None:
    # Numeric(12,2) — более 2 знаков после запятой невалидно
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), price=Decimal("10.999"))


def test_vehicle_snapshot_mileage_negative() -> None:
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), mileage_km=-10)


def test_vehicle_snapshot_equipment_hash_invalid() -> None:
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), equipment_hash="not-hex")
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(captured_at=_utc_now(), equipment_hash="a" * 63)
    # валидный hex 64
    dto = VehicleSnapshotDTO(captured_at=_utc_now(), equipment_hash="F" * 64)
    assert dto.equipment_hash == "F" * 64


def test_vehicle_snapshot_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        VehicleSnapshotDTO(  # type: ignore[call-arg]
            captured_at=_utc_now(), unknown="field"
        )


def test_vehicle_snapshot_naive_captured_at_normalized() -> None:
    dto = VehicleSnapshotDTO(captured_at=datetime(2026, 9, 5, 12, 0))  # noqa: DTZ001
    assert dto.captured_at.tzinfo is not None
