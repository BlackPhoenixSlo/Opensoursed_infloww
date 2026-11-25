from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0041_account_health"
down_revision: str | Sequence[str] | None = "0040_wall_media_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "account_health" not in inspector.get_table_names():
        op.create_table(
            "account_health",
            sa.Column("account_id", sa.String, primary_key=True),
            sa.Column("session_dead_at", sa.DateTime, nullable=True),
            sa.Column("session_dead_reason", sa.String, nullable=True),
            sa.Column("last_probe_at", sa.DateTime, nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "account_health" in inspector.get_table_names():
        op.drop_table("account_health")
