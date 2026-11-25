from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0036_fan_is_muted"
down_revision: str | Sequence[str] | None = "0035_funnel_account_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    fan_cols = {c["name"] for c in inspector.get_columns("fans")}
    if "is_muted" not in fan_cols:
        op.add_column(
            "fans",
            sa.Column("is_muted", sa.Boolean, nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    fan_cols = {c["name"] for c in inspector.get_columns("fans")}
    if "is_muted" in fan_cols:
        op.drop_column("fans", "is_muted")
