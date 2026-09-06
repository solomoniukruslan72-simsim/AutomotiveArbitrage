"""Тесты ingestion service: дедупликация, хэш, savepoint, commit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.ingestion.dtos import (
    NormalizedListingDTO,
    NormalizedVehicleDTO,
    VehicleSnapshotDTO,
    compute_snapshot_content_hash_from_fields,
)
from app.ingestion.service import IngestionItem, process_batch, process_listing_item
from app.models import Listing, Source, Vehicle, VehicleLink, VehicleSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
UTC_LATER = UTC_NOW + timedelta(hours=2)
UTC_EARLIER = UTC_NOW - timedelta(days=1)

SOURCE_ID = "mobile.de.test"
VIN_1 = "WBA5A31000HZ12345"
VIN_2 = "WBA5A31000HZ99999"


def _ensure_utc(dt: datetime) -> datetime:
    """SQLite возвращает naive datetime, считаем его UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _make_engine():  # type: ignore[no-untyped-def]
    # SQLite in-memory для unit-тестов
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine


def _make_session(engine):  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory()


def _listing_dto(
    source_listing_id: str = "ext-001",
    first_seen: datetime = UTC_EARLIER,
    last_seen: datetime = UTC_NOW,
    status: str = "ACTIVE",
    source_id: str = SOURCE_ID,
) -> NormalizedListingDTO:
    return NormalizedListingDTO(
        source_id=source_id,
        source_listing_id=source_listing_id,
        first_seen=first_seen,
        last_seen=last_seen,
        status=status,  # type: ignore[arg-type]
    )


def _vehicle_dto(
    vin: str | None = VIN_1,
    make: str = "BMW",
    model: str = "5 Series",
) -> NormalizedVehicleDTO:
    return NormalizedVehicleDTO(
        vin=vin,
        make=make,
        model=model,
        generation="G30",
        year=2020,
        engine_type="Benzin",
        transmission="Schaltgetriebe",
        engine_volume=2998,
        power_hp=252,
        drive_type="RWD",
    )


def _snapshot_dto(
    captured_at: datetime = UTC_NOW,
    price: Decimal | None = Decimal("25000.00"),
    currency: str | None = "EUR",
    mileage: int | None = 50000,
    listing_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    raw_data: dict | None = None,
) -> VehicleSnapshotDTO:
    return VehicleSnapshotDTO(
        captured_at=captured_at,
        price=price,
        currency=currency,
        mileage_km=mileage,
        equipment_hash="a" * 64,
        condition_data={"accident": False},
        inputs_snapshot={"fx": 1.0},
        raw_data=raw_data or {"price": str(price)},
        listing_id=listing_id,
        snapshot_id=snapshot_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_process_listing_item_creates_all_entities() -> None:
    engine = _make_engine()
    session = _make_session(engine)

    listing = _listing_dto()
    vehicle = _vehicle_dto()
    snapshot = _snapshot_dto()

    # process_listing_item не делает commit, только flush
    db_listing, db_vehicle, db_snapshot = process_listing_item(
        session, listing=listing, vehicle=vehicle, snapshot=snapshot
    )

    # flush уже выполнен, данные видны в той же сессии
    assert db_listing.source_listing_id == "ext-001"
    assert db_vehicle.vin == VIN_1
    assert db_vehicle.make == "BMW"
    # нормализация: Benzin → PETROL, Schaltgetriebe → MANUAL
    assert db_vehicle.engine_type == "PETROL"
    assert db_vehicle.transmission == "MANUAL"
    assert db_snapshot is not None
    assert db_snapshot.snapshot_content_hash is not None
    assert len(db_snapshot.snapshot_content_hash) == 64

    # VehicleLink обязательные поля
    link = session.query(VehicleLink).filter_by(listing_id=db_listing.listing_id).one()
    assert link.match_method in {"VIN_EXACT", "LISTING_FALLBACK", "LISTING_LINK"}
    assert link.match_confidence is not None
    assert 0 <= link.match_confidence <= 100
    assert _ensure_utc(link.matched_at).tzinfo is not None

    # Source создан
    src = session.get(Source, SOURCE_ID)
    assert src is not None

    # пока не commit — в SQLite данные видны, но проверяем что commit не вызван внутри
    # сделаем commit вручную для проверки персистентности
    session.commit()

    # проверяем что всё сохранилось
    assert session.query(Listing).count() == 1
    assert session.query(Vehicle).count() == 1
    assert session.query(VehicleLink).count() == 1
    assert session.query(VehicleSnapshot).count() == 1


def test_vehicle_dedup_by_vin() -> None:
    engine = _make_engine()
    session = _make_session(engine)

    # первый листинг с VIN
    listing1 = _listing_dto("ext-001")
    vehicle1 = _vehicle_dto(vin=VIN_1, make="BMW", model="5 Series")
    snap1 = _snapshot_dto()

    process_listing_item(session, listing=listing1, vehicle=vehicle1, snapshot=snap1)
    session.commit()

    # второй листинг с тем же VIN но другим external id
    listing2 = _listing_dto("ext-002")
    vehicle2 = _vehicle_dto(
        vin=VIN_1,
        make="BMW",
        model="5 Series",
    )
    # меняем generation чтобы проверить merge (более качественное?)
    vehicle2 = vehicle2.model_copy(update={"generation": "G30 LCI"})
    snap2 = _snapshot_dto(price=Decimal("26000.00"))

    process_listing_item(session, listing=listing2, vehicle=vehicle2, snapshot=snap2)
    session.commit()

    # должен быть один Vehicle по VIN
    assert session.query(Vehicle).count() == 1
    veh = session.query(Vehicle).filter(Vehicle.vin == VIN_1).one()
    # два листинга
    assert session.query(Listing).count() == 2
    # две связи
    assert session.query(VehicleLink).count() == 2
    # два снимка (разные цены → разные хэши)
    assert session.query(VehicleSnapshot).count() == 2
    # проверяем что vehicle остался один
    assert veh.vehicle_id is not None


def test_vehicle_dedup_via_link_when_vin_none() -> None:
    engine = _make_engine()
    session = _make_session(engine)

    listing = _listing_dto("ext-003")
    vehicle_no_vin = _vehicle_dto(vin=None, make="Audi", model="A6")
    snap = _snapshot_dto()

    # первый раз — создаёт vehicle без VIN
    _, veh1, _ = process_listing_item(
        session, listing=listing, vehicle=vehicle_no_vin, snapshot=snap
    )
    session.commit()
    veh1_id = veh1.vehicle_id

    # второй раз тот же листинг (тот же source_listing_id) без VIN — должен найти через VehicleLink
    listing_same = _listing_dto("ext-003", last_seen=UTC_LATER)
    # новый vehicle DTO с более качественным generation (было G30, теперь G30 + пакет)
    vehicle_update = _vehicle_dto(vin=None, make="Audi", model="A6")
    vehicle_update = vehicle_update.model_copy(update={"generation": "C8"})
    snap2 = _snapshot_dto(captured_at=UTC_LATER, price=Decimal("25500.00"))

    _, veh2, _ = process_listing_item(
        session, listing=listing_same, vehicle=vehicle_update, snapshot=snap2
    )
    session.commit()

    assert veh1_id == veh2.vehicle_id
    assert session.query(Vehicle).count() == 1
    # проверяем что generation обновилось (было G30, стало C8? но по логике только если existing пустое — не перезапишет)
    # В нашем случае veh1 generation было G30, veh2 хочет C8 — по эвристике более длинное? C8 короче, поэтому не перезапишет
    # Но если бы veh1 generation был None, то обновилось бы — проверим другой кейс
    # Создадим vehicle без generation, затем с generation
    listing2 = _listing_dto("ext-004")
    v_no_gen = NormalizedVehicleDTO(make="Audi", model="A6", vin=None, generation=None)
    snap3 = _snapshot_dto(captured_at=UTC_LATER + timedelta(hours=1))
    _, veh_a, _ = process_listing_item(session, listing=listing2, vehicle=v_no_gen, snapshot=snap3)
    session.commit()
    assert veh_a.generation is None

    # теперь обновляем тот же листинг с generation
    v_with_gen = NormalizedVehicleDTO(make="Audi", model="A6", vin=None, generation="C8")
    snap4 = _snapshot_dto(captured_at=UTC_LATER + timedelta(hours=2), price=Decimal("30000.00"))
    _, veh_b, _ = process_listing_item(
        session,
        listing=_listing_dto("ext-004", last_seen=UTC_LATER + timedelta(hours=2)),
        vehicle=v_with_gen,
        snapshot=snap4,
    )
    session.commit()
    assert veh_b.generation == "C8"


def test_snapshot_dedup_same_content_skips_creation_and_updates_last_seen() -> None:
    engine = _make_engine()
    session = _make_session(engine)

    listing = _listing_dto("ext-005", first_seen=UTC_EARLIER, last_seen=UTC_NOW)
    vehicle = _vehicle_dto()
    snap1 = _snapshot_dto(captured_at=UTC_NOW, price=Decimal("25000.00"))

    _, _, created1 = process_listing_item(session, listing=listing, vehicle=vehicle, snapshot=snap1)
    session.commit()
    assert created1 is not None
    assert session.query(VehicleSnapshot).count() == 1

    # второй снимок с тем же каноническим содержимым, но другим captured_at
    # хэш не должен включать captured_at, поэтому дубликат
    snap2 = _snapshot_dto(captured_at=UTC_LATER, price=Decimal("25000.00"))
    # вычисляем хэши — должны совпасть несмотря на разный captured_at
    assert snap1.compute_content_hash() == snap2.compute_content_hash()

    listing2 = _listing_dto("ext-005", first_seen=UTC_EARLIER, last_seen=UTC_LATER)
    _, _, created2 = process_listing_item(
        session, listing=listing2, vehicle=vehicle, snapshot=snap2
    )
    session.commit()

    # снимок не создан
    assert created2 is None
    assert session.query(VehicleSnapshot).count() == 1
    # last_seen обновлён
    db_listing = session.query(Listing).filter_by(source_listing_id="ext-005").one()
    assert _ensure_utc(db_listing.last_seen) == UTC_LATER


def test_snapshot_creates_new_when_content_changes() -> None:
    engine = _make_engine()
    session = _make_session(engine)

    listing = _listing_dto("ext-006")
    vehicle = _vehicle_dto()
    snap1 = _snapshot_dto(price=Decimal("25000.00"))

    process_listing_item(session, listing=listing, vehicle=vehicle, snapshot=snap1)
    session.commit()
    assert session.query(VehicleSnapshot).count() == 1

    snap2 = _snapshot_dto(captured_at=UTC_LATER, price=Decimal("26000.00"))
    listing2 = _listing_dto("ext-006", last_seen=UTC_LATER)
    _, _, created = process_listing_item(session, listing=listing2, vehicle=vehicle, snapshot=snap2)
    session.commit()
    assert created is not None
    assert session.query(VehicleSnapshot).count() == 2


def test_process_batch_one_commit_and_savepoint_isolation() -> None:
    engine = _make_engine()
    session = _make_session(engine)

    # подготовим 3 валидных item + 1 с ошибкой (принудительно)
    item1 = IngestionItem(
        listing=_listing_dto("ext-101"),
        vehicle=_vehicle_dto(vin=VIN_1),
        snapshot=_snapshot_dto(captured_at=UTC_NOW),
    )
    item2 = IngestionItem(
        listing=_listing_dto("ext-102"),
        vehicle=_vehicle_dto(vin=VIN_2),
        snapshot=_snapshot_dto(captured_at=UTC_NOW, price=Decimal("10000.00")),
    )
    item_bad = IngestionItem(
        listing=_listing_dto("ext-bad"),
        vehicle=_vehicle_dto(vin="WBA00000000000001"),
        snapshot=_snapshot_dto(captured_at=UTC_NOW, price=Decimal("9999.00")),
    )
    item3 = IngestionItem(
        listing=_listing_dto("ext-103"),
        vehicle=_vehicle_dto(vin=None, make="Skoda", model="Octavia"),
        snapshot=_snapshot_dto(captured_at=UTC_LATER, price=Decimal("15000.00")),
    )

    # отслеживаем commit
    commit_calls = {"count": 0}
    orig_commit = session.commit

    def counting_commit():  # type: ignore[no-untyped-def]
        commit_calls["count"] += 1
        return orig_commit()

    session.commit = counting_commit  # type: ignore[method-assign]

    # заставляем второй item падать через патч
    original_process = process_listing_item

    def failing_process(db: Session, *, listing, vehicle, snapshot):  # type: ignore[no-untyped-def]
        if listing.source_listing_id == "ext-bad":
            raise ValueError("forced error for test isolation")
        return original_process(db, listing=listing, vehicle=vehicle, snapshot=snapshot)

    with patch("app.ingestion.service.process_listing_item", side_effect=failing_process):
        # process_batch импортирует process_listing_item напрямую, нужен патч по пути
        # поэтому патчим также в текущем модуле
        import app.ingestion.service as svc

        with patch.object(svc, "process_listing_item", side_effect=failing_process):
            result = process_batch(session, [item1, item_bad, item2, item3])

    # один commit на весь batch
    assert commit_calls["count"] == 1
    assert result.total == 4
    assert result.succeeded == 3
    assert result.failed == 1
    assert any("ext-bad" in err[0] for err in result.errors)

    # успешные items сохранены, bad откатился
    assert session.query(Listing).filter_by(source_listing_id="ext-bad").count() == 0
    assert session.query(Listing).filter_by(source_listing_id="ext-101").count() == 1
    assert session.query(Listing).filter_by(source_listing_id="ext-102").count() == 1
    assert session.query(Listing).filter_by(source_listing_id="ext-103").count() == 1
    # Vehicle для bad не создан
    assert session.query(Vehicle).filter(Vehicle.vin == "WBA00000000000001").count() == 0


def test_process_batch_does_not_log_raw_json_or_url(caplog) -> None:  # type: ignore[no-untyped-def]
    import logging

    caplog.set_level(logging.WARNING)
    engine = _make_engine()
    session = _make_session(engine)

    bad = IngestionItem(
        listing=_listing_dto("ext-secret"),
        vehicle=_vehicle_dto(),
        snapshot=_snapshot_dto(raw_data={"secret": "SUPER_TOKEN", "url": "https://evil.com"}),
    )

    def raising(db: Session, *, listing, vehicle, snapshot):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    import app.ingestion.service as svc

    with patch.object(svc, "process_listing_item", side_effect=raising):
        process_batch(session, [bad])

    # логи должны содержать safe id, но не raw JSON / URL / токен
    logged = "".join(caplog.messages)
    assert "ext-secret" in logged
    assert "SUPER_TOKEN" not in logged
    assert "https://evil.com" not in logged
    assert "boom" in logged


def test_snapshot_hash_excludes_timestamp() -> None:
    # Прямо проверяем детерминированность хэша
    base_kwargs = {
        "price": Decimal("25000.00"),
        "currency": "EUR",
        "mileage_km": 50000,
        "equipment_hash": "a" * 64,
        "condition_data": {"a": 1},
        "inputs_snapshot": {"fx": 1},
        "raw_data": {"x": 1},
    }
    h1 = compute_snapshot_content_hash_from_fields(**base_kwargs)  # type: ignore[arg-type]
    h2 = compute_snapshot_content_hash_from_fields(**base_kwargs)  # type: ignore[arg-type]
    assert h1 == h2
    assert len(h1) == 64

    snap1 = VehicleSnapshotDTO(captured_at=UTC_NOW, **base_kwargs)  # type: ignore[arg-type]
    snap2 = VehicleSnapshotDTO(captured_at=UTC_LATER, **base_kwargs)  # type: ignore[arg-type]
    # captured_at различается, но хэш одинаковый
    assert snap1.snapshot_content_hash == snap2.snapshot_content_hash
    assert snap1.compute_content_hash() == snap2.compute_content_hash()

    # изменение цены меняет хэш
    snap3 = VehicleSnapshotDTO(
        captured_at=UTC_NOW,
        price=Decimal("26000.00"),
        currency="EUR",
        mileage_km=50000,
        equipment_hash="a" * 64,
    )  # type: ignore[call-arg]
    assert snap1.snapshot_content_hash != snap3.snapshot_content_hash


# ---------------------------------------------------------------------------
# IngestionService как класс (ТЗ 2)
# ---------------------------------------------------------------------------


def test_ingestion_service_class_exists() -> None:
    from app.ingestion.service import IngestionService

    assert hasattr(IngestionService, "process_listing_item")
    assert hasattr(IngestionService, "process_batch")

    engine = _make_engine()
    session = _make_session(engine)
    svc = IngestionService(session)
    assert svc.db is session


def test_ingestion_service_process_listing_item_delegates() -> None:
    from app.ingestion.service import IngestionService

    engine = _make_engine()
    session = _make_session(engine)
    svc = IngestionService(session)

    listing = _listing_dto("ext-service-001")
    vehicle = _vehicle_dto()
    snapshot = _snapshot_dto()

    db_listing, db_vehicle, db_snapshot = svc.process_listing_item(
        listing=listing, vehicle=vehicle, snapshot=snapshot
    )
    assert db_listing.source_listing_id == "ext-service-001"
    assert db_vehicle.vin == VIN_1
    assert db_snapshot is not None
    # функциональная обёртка должна давать тот же результат
    # проверяем что VehicleLink создан
    link = session.query(VehicleLink).filter_by(listing_id=db_listing.listing_id).one()
    assert link.match_method in {"VIN_EXACT", "LISTING_FALLBACK"}


def test_ingestion_service_snapshot_dedup() -> None:
    from app.ingestion.service import IngestionService

    engine = _make_engine()
    session = _make_session(engine)
    svc = IngestionService(session)

    listing = _listing_dto("ext-service-005", first_seen=UTC_EARLIER, last_seen=UTC_NOW)
    vehicle = _vehicle_dto()
    snap1 = _snapshot_dto(captured_at=UTC_NOW, price=Decimal("25000.00"))

    _, _, created1 = svc.process_listing_item(listing=listing, vehicle=vehicle, snapshot=snap1)
    session.commit()
    assert created1 is not None
    assert session.query(VehicleSnapshot).count() == 1

    snap2 = _snapshot_dto(captured_at=UTC_LATER, price=Decimal("25000.00"))
    assert snap1.compute_content_hash() == snap2.compute_content_hash()

    listing2 = _listing_dto("ext-service-005", first_seen=UTC_EARLIER, last_seen=UTC_LATER)
    _, _, created2 = svc.process_listing_item(listing=listing2, vehicle=vehicle, snapshot=snap2)
    session.commit()
    assert created2 is None
    assert session.query(VehicleSnapshot).count() == 1
    db_listing = session.query(Listing).filter_by(source_listing_id="ext-service-005").one()
    assert _ensure_utc(db_listing.last_seen) == UTC_LATER


def test_ingestion_service_process_batch_savepoint_and_one_commit() -> None:
    from app.ingestion.service import IngestionService

    engine = _make_engine()
    session = _make_session(engine)
    svc = IngestionService(session)

    item1 = IngestionItem(
        listing=_listing_dto("ext-svc-101"),
        vehicle=_vehicle_dto(vin=VIN_1),
        snapshot=_snapshot_dto(captured_at=UTC_NOW),
    )
    item_bad = IngestionItem(
        listing=_listing_dto("ext-svc-bad"),
        vehicle=_vehicle_dto(vin="WBA00000000000002"),
        snapshot=_snapshot_dto(captured_at=UTC_NOW),
    )
    item2 = IngestionItem(
        listing=_listing_dto("ext-svc-102"),
        vehicle=_vehicle_dto(vin=VIN_2),
        snapshot=_snapshot_dto(captured_at=UTC_NOW, price=Decimal("10000.00")),
    )

    commit_calls = {"count": 0}
    orig_commit = session.commit

    def counting_commit():  # type: ignore[no-untyped-def]
        commit_calls["count"] += 1
        return orig_commit()

    session.commit = counting_commit  # type: ignore[method-assign]

    import app.ingestion.service as svc_mod

    orig_func = svc_mod.process_listing_item

    def failing_process(db: Session, *, listing, vehicle, snapshot):  # type: ignore[no-untyped-def]
        if listing.source_listing_id == "ext-svc-bad":
            raise ValueError("forced error via service class")
        return orig_func(db, listing=listing, vehicle=vehicle, snapshot=snapshot)

    with patch.object(svc_mod, "process_listing_item", side_effect=failing_process):
        result = svc.process_batch([item1, item_bad, item2])

    assert commit_calls["count"] == 1
    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert session.query(Listing).filter_by(source_listing_id="ext-svc-bad").count() == 0
    assert session.query(Listing).filter_by(source_listing_id="ext-svc-101").count() == 1
    assert session.query(Listing).filter_by(source_listing_id="ext-svc-102").count() == 1


def test_ingestion_service_compatibility_with_functions() -> None:
    """Функции остаются, класс делегирует — оба пути эквивалентны."""
    from app.ingestion.service import IngestionService

    engine1 = _make_engine()
    session1 = _make_session(engine1)
    listing = _listing_dto("ext-compat-001")
    vehicle = _vehicle_dto()
    snap = _snapshot_dto()

    # через функцию
    process_listing_item(session1, listing=listing, vehicle=vehicle, snapshot=snap)
    session1.commit()
    count_func = session1.query(VehicleSnapshot).count()

    engine2 = _make_engine()
    session2 = _make_session(engine2)
    svc = IngestionService(session2)
    svc.process_listing_item(listing=listing, vehicle=vehicle, snapshot=snap)
    session2.commit()
    count_svc = session2.query(VehicleSnapshot).count()

    assert count_func == count_svc == 1
