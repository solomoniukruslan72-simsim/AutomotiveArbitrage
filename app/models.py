import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Source(Base):
    __tablename__ = "source"
    source_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Listing(Base):
    __tablename__ = "listing"
    listing_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.source_id"), nullable=False)
    source_listing_id: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_type: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicle"
    vehicle_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vin: Mapped[str | None] = mapped_column(String(17), unique=True)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    generation: Mapped[str | None] = mapped_column(String(100))
    year: Mapped[int | None] = mapped_column(Integer)
    engine_type: Mapped[str | None] = mapped_column(String(30))
    transmission: Mapped[str | None] = mapped_column(String(30))
    engine_volume: Mapped[int | None] = mapped_column(Integer)
    power_hp: Mapped[int | None] = mapped_column(Integer)
    drive_type: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VehicleLink(Base):
    __tablename__ = "vehicle_link"
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listing.listing_id"), primary_key=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicle.vehicle_id"), primary_key=True)
    match_method: Mapped[str] = mapped_column(String(30), nullable=False)
    match_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VehicleSnapshot(Base):
    __tablename__ = "vehicle_snapshot"
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listing.listing_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    equipment_hash: Mapped[str | None] = mapped_column(String(64))
    condition_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    inputs_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
