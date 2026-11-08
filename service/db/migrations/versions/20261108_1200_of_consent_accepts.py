"""of_consent_accepts — a Creator's "Auto-accept OnlyFans consent" switch and its history

One NEW append-only table (one row per change: account, on/off, who, when; the newest
row is the setting, none = off). No existing row is touched. `create_all()` brings it
to a booting box; this file keeps the alembic chain linear. Inspector-guarded + idempotent.

Revision ID: 0105_of_consent_accepts
Revises: 0104_assistant_turns
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0105_of_consent_accepts"
down_revision: str | Sequence[str] | None = "0104_assistant_turns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "of_consent_accepts"


def upgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("user_id", sa.String, nullable=True),
        sa.Column("username", sa.String, nullable=True),
        sa.Column("employee_id", sa.Integer, nullable=True),
        sa.Column("at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_of_consent_accepts_account_id", _TABLE, ["account_id", "id"])


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
