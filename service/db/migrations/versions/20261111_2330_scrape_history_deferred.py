"""scrape_history.history_deferred_at — a Silent mass-only chat's deep history, deferred

One nullable column: when a `{}` sweep kept only page 1 of a chat whose page 1 is all our queued mass
rows (OF reports more, no fan message and no ledger spend in the DB) and left its cursor NULL. Every cursor write clears it.
NULL = not deferred (every row before this). Inspector-guarded + idempotent; init_db's additive-column
catch-up adds it on boot too. Downgrade drops the marker: a deferred chat then reads as never scraped.

Revision ID: 0116_scrape_history_deferred
Revises: 0116_drop_vault_jev_enabled
Create Date: 2026-11-09
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0116_scrape_history_deferred"
down_revision: str | Sequence[str] | None = "0116_drop_vault_jev_enabled"  # was 0115; re-parented after main added 0116_drop_vault_jev_enabled (one head)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "scrape_history", "history_deferred_at"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
