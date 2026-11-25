from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0043_rhythm"
down_revision: str | Sequence[str] | None = "0042_attr_view_orphan_rows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("account_ai_config")} \
        if "account_ai_config" in inspector.get_table_names() else set()
    if "account_ai_config" in inspector.get_table_names() and "timezone" not in cols:
        op.add_column("account_ai_config", sa.Column("timezone", sa.String, nullable=True))

    if "rhythm_state" not in inspector.get_table_names():
        op.create_table(
            "rhythm_state",
            sa.Column("account_id", sa.String, primary_key=True),
            sa.Column("fan_id", sa.BigInteger, primary_key=True),
            sa.Column("context", sa.String, nullable=False, server_default="engaged"),
            sa.Column("wake_at", sa.DateTime, nullable=True),
            sa.Column("deferrals", sa.Integer, nullable=False, server_default="0"),
            sa.Column("last_cover_at", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )
        op.create_index("ix_rhythm_state_wake_at", "rhythm_state", ["wake_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "rhythm_state" in inspector.get_table_names():
        op.drop_index("ix_rhythm_state_wake_at", table_name="rhythm_state")
        op.drop_table("rhythm_state")
        # account_ai_config.timezone is left in place (additive, harmless).
