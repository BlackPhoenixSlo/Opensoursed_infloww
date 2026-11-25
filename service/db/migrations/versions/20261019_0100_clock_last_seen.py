from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075_clock_last_seen"
down_revision: str | Sequence[str] | None = "0074_link_list"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("clock_events")}


def upgrade() -> None:
    if "last_seen_utc" not in _columns():
        op.add_column("clock_events", sa.Column("last_seen_utc", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if "last_seen_utc" in _columns():
        # Native DROP COLUMN: a batch copy would rebuild the table and could lose the partial index.
        op.drop_column("clock_events", "last_seen_utc")
