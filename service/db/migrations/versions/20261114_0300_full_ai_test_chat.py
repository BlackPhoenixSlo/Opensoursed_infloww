"""full_ai_test_chat — Full AI Chat's Test chat reply and settings JSON

Two nullable TEXT columns, no new table or index: `ai_decisions.reply_json` (a test row's
bubbles, Writer attempts, side, wait and session fold) and `account_ai_config.full_ai_config_json`
(the settings JSON, {checkpoint, previous, draft, rev}). No existing row is touched. init_db's
additive-column catch-up brings both to a booting box; this file keeps the alembic chain linear.
Inspector-guarded + idempotent.

Revision ID: 0119_full_ai_test_chat
Revises: 0118_owner_tokens
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0119_full_ai_test_chat"
down_revision: str | Sequence[str] | None = "0118_owner_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (("ai_decisions", "reply_json"), ("account_ai_config", "full_ai_config_json"))


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, col in _COLUMNS:
        if col not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column(col, sa.Text, nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, col in _COLUMNS:
        if col in {c["name"] for c in insp.get_columns(table)}:
            op.drop_column(table, col)
