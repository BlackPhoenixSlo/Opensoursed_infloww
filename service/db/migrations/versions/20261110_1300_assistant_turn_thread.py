from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# column only: old rows get thread_id at boot (backfill_thread_ids); relay DB never runs alembic
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
