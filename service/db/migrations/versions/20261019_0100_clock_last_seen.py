"""clock_last_seen — the Clock event's heartbeat, for the inactivity clock-out

`clock_events.last_seen_utc` (DATETIME, NULL): the latest
`POST /admin/shifts/clock-heartbeat` while the event is open. The lazy Auto
clock-out counts its deadline from the later of the clock-in, this and the
Employee's latest audit row (service/clock_api.py `_auto_clock_out`). NULL for
events closed before this and for events never seen since their clock-in.

The ORM model declares the same column, so `init_db()`'s ADD-COLUMN catch-up
brings it to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the column;
that loses only heartbeats, and the sweep falls back to the clock-in and the
audit rows.

Revision ID: 0075_clock_last_seen
Revises: 0074_link_list
Create Date: 2026-10-19
"""
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
        # Native ALTER TABLE DROP COLUMN (SQLite 3.35+), as 0070_employee_groups:
        # a batch copy would rebuild the table and could lose the partial index.
        op.drop_column("clock_events", "last_seen_utc")
