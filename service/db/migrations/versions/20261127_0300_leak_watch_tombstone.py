from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0139_leak_watch_tombstone"
down_revision: str | Sequence[str] | None = "0138_leak_watch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "leak_watch_tombstone"


def upgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("watch_id", sa.String, primary_key=True),
        sa.Column("agency_user_id", sa.String, nullable=False),
        sa.Column("account_id", sa.String, nullable=False),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("requested_at", sa.DateTime, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
    )


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
