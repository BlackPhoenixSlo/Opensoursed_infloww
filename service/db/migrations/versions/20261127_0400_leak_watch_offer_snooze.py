from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0140_leak_watch_offer_snooze"
down_revision: str | Sequence[str] | None = "0139_leak_watch_tombstone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "leak_watch", "offer_snoozed_until"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
