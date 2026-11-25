from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106_tx_scan_last_full_at"
down_revision: str | Sequence[str] | None = "0105_of_consent_accepts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "transaction_scan_history"
_COLUMNS = (sa.Column("last_full_at", sa.DateTime(), nullable=True),
            sa.Column("backfill_stalls", sa.Integer(), nullable=True))


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    live = _live()
    for col in _COLUMNS:
        if col.name not in live:
            op.add_column(_TABLE, col)


def downgrade() -> None:
    live = _live()
    for col in reversed(_COLUMNS):
        if col.name in live:
            op.drop_column(_TABLE, col.name)
