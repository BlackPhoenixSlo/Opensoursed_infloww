"""tx_scan_full_walk_failures — a failing ledger full walk stays visible through recent successes

One nullable integer on transaction_scan_history: full walks failed or cut short since the last
completed one. Before, a recent walk's success reset status/last_error to ok, so a full walk that
failed every period read green (disputes poll, >24 h status flips, gap check never ran). > 0: /health
is not green (status full_walk_failed between ticks); only a completed full walk resets it. NULL reads 0.
Inspector-guarded + idempotent; init_db's additive-column catch-up adds it on boot too.

Revision ID: 0111_tx_scan_full_walk_failures
Revises: 0110_assistant_turn_thread
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0111_tx_scan_full_walk_failures"
down_revision: str | Sequence[str] | None = "0110_assistant_turn_thread"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "transaction_scan_history", "full_walk_failures"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.Integer(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
