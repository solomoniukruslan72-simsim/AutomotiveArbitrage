"""Add snapshot_content_hash to vehicle_snapshot.

Revision ID: 20260905_0002
Revises: 20260904_0001
"""

from alembic import op
import sqlalchemy as sa

revision = "20260905_0002"
down_revision = "20260904_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем колонку с NOT NULL. Для существующих строк (если есть) ставим
    # временный server_default, чтобы не падать на PostgreSQL, затем убираем.
    # В свежей БД строк нет, но совместимость с Neon требует default.
    op.add_column(
        "vehicle_snapshot",
        sa.Column(
            "snapshot_content_hash",
            sa.String(64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.alter_column("vehicle_snapshot", "snapshot_content_hash", server_default=None)
    op.create_index(
        "ix_vehicle_snapshot_snapshot_content_hash",
        "vehicle_snapshot",
        ["snapshot_content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_vehicle_snapshot_snapshot_content_hash", table_name="vehicle_snapshot")
    op.drop_column("vehicle_snapshot", "snapshot_content_hash")
