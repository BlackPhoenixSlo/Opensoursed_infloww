"""tx_scan_last_full_at — the ledger full walk's scheduling watermark survives a restart

One nullable column on transaction_scan_history: the window end of the account's last
attempted full walk (success, failure or cut short) or its one-time seed. Before, it lived
in memory, so a relay boot full-walked every account at once (measured AE 2026-11-08: 13
accounts, 5 failed on a second 429 and re-walked every tick). NULL = not yet seeded.
Inspector-guarded + idempotent; init_db's additive-column catch-up adds it on boot too.

Revision ID: 0106_tx_scan_last_full_at
Revises: 0105_of_consent_accepts
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106_tx_scan_last_full_at"
down_revision: str | Sequence[str] | None = "0105_of_consent_accepts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "transaction_scan_history", "last_full_at"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
