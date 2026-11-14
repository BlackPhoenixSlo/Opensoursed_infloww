"""ai_decisions — Full AI Chat's Decision ledger (Phase 01, Shadow mode)

One NEW table, written only by the `full_ai_chat` shadow runner; no existing row is touched. `create_all()`
brings it (and its three indexes, declared on the model) to a booting box; this file keeps the alembic chain
linear. The table and each index are created only when the inspector lacks them; downgrade drops the table.

Revision ID: 0117_full_ai_decisions
Revises: 0116_scrape_history_deferred
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0117_full_ai_decisions"
down_revision: str | Sequence[str] | None = "0116_scrape_history_deferred"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_decisions"


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def upgrade() -> None:
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("fan_id", sa.BigInteger, nullable=False),
            sa.Column("mode", sa.String, nullable=False),
            sa.Column("trigger_kind", sa.String, nullable=False),
            sa.Column("trigger_key", sa.String, nullable=False),
            sa.Column("parent_id", sa.Integer, sa.ForeignKey("ai_decisions.id"), nullable=True),
            sa.Column("anchor_message_id", sa.BigInteger, nullable=True),
            sa.Column("anchor_created_at", sa.DateTime, nullable=True),
            sa.Column("arm", sa.String, nullable=True),
            sa.Column("salt_ver", sa.Integer, nullable=True),
            sa.Column("route", sa.String, nullable=False),
            sa.Column("heat", sa.Integer, nullable=False),
            sa.Column("route_row", sa.String, nullable=False),
            sa.Column("question_version", sa.String, nullable=False),
            sa.Column("router_model", sa.String, nullable=True),
            sa.Column("writer_model", sa.String, nullable=True),
            sa.Column("jev_json", sa.Text, nullable=True),
            sa.Column("jev_ms", sa.Integer, nullable=True),
            sa.Column("jev_error", sa.Text, nullable=True),
            sa.Column("status", sa.String, nullable=False),
            _ts("created_at"), _ts("updated_at"),
        )
    have = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    for name, cols, unique in (
        ("uq_ai_decisions_turn", ["account_id", "fan_id", "mode", "trigger_key"], True),
        ("ix_ai_decisions_fan_time", ["account_id", "fan_id", "created_at"], False),
        ("ix_ai_decisions_acct_mode_time", ["account_id", "mode", "created_at"], False),
    ):
        if name not in have:
            op.create_index(name, _TABLE, cols, unique=unique)


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
