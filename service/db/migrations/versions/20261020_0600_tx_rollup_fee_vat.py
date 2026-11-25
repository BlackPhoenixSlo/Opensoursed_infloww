from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083_tx_rollup_fee_vat"
down_revision: str | Sequence[str] | None = "0082_s4s_media_blocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("tx_hourly", "tx_daily")
_COLS = ("fee_cents", "vat_cents")


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table in _TABLES:
        live = _columns(table)
        for name in _COLS:
            if name not in live:
                op.add_column(table, sa.Column(name, sa.BigInteger(), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    # triggers name these columns: drop them first or the next sale write fails
    for name in ("trg_tx_credit_ins", "trg_tx_rollup_upd", "trg_tx_rollup_del"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table in _TABLES:
        live = _columns(table)
        for name in _COLS:
            if name in live:
                op.drop_column(table, name)
