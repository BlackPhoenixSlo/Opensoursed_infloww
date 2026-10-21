"""tx_rollup_fee_vat — OnlyFans' fee and VAT summed in the hourly and daily rollups

Roadmap W5 5.13 (the VAT / fee breakdown). Creator reports' Earnings ledger
reads Platform fee and VAT collected from the rollups, as it reads gross and net.

  tx_hourly.fee_cents  SUM(COALESCE(transactions.fee_cents, 0)) per bucket
  tx_hourly.vat_cents  SUM(COALESCE(transactions.vat_cents, 0)) per bucket
  tx_daily.fee_cents   the same per UTC day
  tx_daily.vat_cents

Written only by tx_rollup's triggers, which `init_db()` replaces on boot (their
text changed), and filled once per box by its backfill, whose marker was renamed
for this (tx_rollup `_BACKFILL`): it rebuilds both rollups from the ledger. The
ORM models declare the columns with a server default, so `init_db()`'s ADD-COLUMN
catch-up brings them to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
them; nothing is lost (both are derived from the ledger).

Revision ID: 0083_tx_rollup_fee_vat
Revises: 0082_s4s_media_blocks
Create Date: 2026-10-20
"""
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
    # init_db's triggers (tx_rollup.py) write these columns: drop the ones that
    # name them first, or the next sale write fails. Named here, not imported,
    # so this revision stays fixed.
    for name in ("trg_tx_credit_ins", "trg_tx_rollup_upd", "trg_tx_rollup_del"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table in _TABLES:
        live = _columns(table)
        for name in _COLS:
            if name in live:
                op.drop_column(table, name)
