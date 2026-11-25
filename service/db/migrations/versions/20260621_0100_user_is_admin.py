from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0039_user_is_admin"
down_revision: str | Sequence[str] | None = "0038_attr_view_fan_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_admin" not in user_cols:
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Boolean, nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_admin" in user_cols:
        op.drop_column("users", "is_admin")
