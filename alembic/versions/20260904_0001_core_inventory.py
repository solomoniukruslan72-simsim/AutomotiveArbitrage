"""Create core inventory tables.

Revision ID: 20260904_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260904_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "source",
        sa.Column("source_id", sa.String(50), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("length(country_code) = 2", name="ck_source_country_code"),
    )
    op.create_table(
        "listing",
        sa.Column("listing_id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", sa.String(50), sa.ForeignKey("source.source_id"), nullable=False),
        sa.Column("source_listing_id", sa.String(255), nullable=False),
        sa.Column("seller_type", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "source_listing_id", name="uq_listing_source_external_id"),
    )
    op.create_index("ix_listing_status", "listing", ["status"])
    op.create_table(
        "vehicle",
        sa.Column("vehicle_id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vin", sa.String(17), unique=True),
        sa.Column("make", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("generation", sa.String(100)),
        sa.Column("year", sa.Integer()),
        sa.Column("engine_type", sa.String(30)),
        sa.Column("transmission", sa.String(30)),
        sa.Column("engine_volume", sa.Integer()),
        sa.Column("power_hp", sa.Integer()),
        sa.Column("drive_type", sa.String(10)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vehicle_make_model_year", "vehicle", ["make", "model", "year"])
    op.create_table(
        "vehicle_link",
        sa.Column("listing_id", sa.UUID(), sa.ForeignKey("listing.listing_id"), primary_key=True),
        sa.Column("vehicle_id", sa.UUID(), sa.ForeignKey("vehicle.vehicle_id"), primary_key=True),
        sa.Column("match_method", sa.String(30), nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("match_confidence >= 0 AND match_confidence <= 100", name="ck_link_confidence"),
    )
    op.create_index("ix_vehicle_link_vehicle_id", "vehicle_link", ["vehicle_id"])
    op.create_table(
        "vehicle_snapshot",
        sa.Column("snapshot_id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("listing_id", sa.UUID(), sa.ForeignKey("listing.listing_id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3)),
        sa.Column("mileage_km", sa.Integer()),
        sa.Column("equipment_hash", sa.String(64)),
        sa.Column("condition_data", postgresql.JSONB()),
        sa.Column("inputs_snapshot", postgresql.JSONB()),
        sa.Column("raw_data", postgresql.JSONB()),
    )
    op.create_index("ix_vehicle_snapshot_listing_captured", "vehicle_snapshot", ["listing_id", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_vehicle_snapshot_listing_captured", table_name="vehicle_snapshot")
    op.drop_table("vehicle_snapshot")
    op.drop_index("ix_vehicle_link_vehicle_id", table_name="vehicle_link")
    op.drop_table("vehicle_link")
    op.drop_index("ix_vehicle_make_model_year", table_name="vehicle")
    op.drop_table("vehicle")
    op.drop_index("ix_listing_status", table_name="listing")
    op.drop_table("listing")
    op.drop_table("source")
