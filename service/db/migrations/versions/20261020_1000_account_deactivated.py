"""account_deactivated — the Creator deactivate switch

`account_health.deactivated_at` (DATETIME, NULL): when the owner deactivated
the Creator (Creators › ⋮ › Deactivate, `POST /admin/accounts/{id}/active`).
While set, its WS pump, transaction polls and automations stop
(service/account_health.py); NULL for every Creator that is active, which is
every Creator before this.

The ORM model declares the same column, so `init_db()`'s ADD-COLUMN catch-up
brings it to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the column,
which activates every deactivated Creator again.

Revision ID: 0087_account_deactivated
Revises: 0086_auth_sessions_2fa
Create Date: 2026-10-20
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087_account_deactivated"
down_revision: str | Sequence[str] | None = "0086_auth_sessions_2fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("account_health")}


def upgrade() -> None:
    if "deactivated_at" not in _columns():
        op.add_column("account_health", sa.Column("deactivated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if "deactivated_at" in _columns():
        op.drop_column("account_health", "deactivated_at")
