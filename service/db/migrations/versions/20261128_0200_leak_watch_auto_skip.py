from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0142_leak_watch_auto_skip"
down_revision: str | Sequence[str] | None = "0141_leak_watch_opt_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "leak_watch_auto_skip"


def upgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("agency_user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("retry_after", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
