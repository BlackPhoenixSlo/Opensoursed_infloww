from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0040_wall_media_price"
down_revision: str | Sequence[str] | None = "0039_user_is_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("wall_media")}
    if "price_cents" not in cols:
        op.add_column(
            "wall_media",
            sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("wall_media")}
    if "price_cents" in cols:
        op.drop_column("wall_media", "price_cents")
