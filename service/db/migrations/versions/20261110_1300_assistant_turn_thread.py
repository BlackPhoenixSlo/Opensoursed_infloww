"""assistant_turns.thread_id — the help widget's conversation a turn belongs to

One nullable string: the widget lists earlier conversations and continues one, and the prompt's
PREVIOUS TURNS come from the ask's own thread. The column alone: rows from before it get their
thread at boot only, by `db.engine.init_db` (`db/assistant_threads.backfill_thread_ids`) — the relay
DB never runs alembic, and its additive-column catch-up adds this column too. Self-contained (no
app import), inspector-guarded + idempotent.

Revision ID: 0110_assistant_turn_thread
Revises: 0109_agency_notification_dismissed
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0110_assistant_turn_thread"
down_revision: str | Sequence[str] | None = "0109_agency_notification_dismissed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "assistant_turns", "thread_id"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.String(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
