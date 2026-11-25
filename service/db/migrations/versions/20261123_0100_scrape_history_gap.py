from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0135_scrape_history_gap"
down_revision: str | Sequence[str] | None = "0134_audit_credential_scrub"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COLS = "scrape_history", ("gap_after_id", "gap_before_id")


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    live = _live()
    for col in _COLS:
        if col not in live:
            op.add_column(_TABLE, sa.Column(col, sa.BigInteger(), nullable=True))


def downgrade() -> None:
    live = _live()
    for col in _COLS:
        if col in live:
            op.drop_column(_TABLE, col)
