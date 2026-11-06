"""saved_reply_sequences + saved_replies.conditional / sent_count (Growth > Scripts at Infloww size)

One NEW table, `saved_reply_sequences` (a sequence's position, Created by, description, dates; joined to
its steps by name, `saved_replies.script_id`), and two additive columns on `saved_replies`:
`conditional` (TEXT, NULL: a Condition step option's text) and `sent_count` (INTEGER NOT NULL DEFAULT 0).
No existing row is rewritten. `create_all()` + init_db's ADD-COLUMN catch-up bring them to a booting box;
this file keeps the alembic chain linear. Inspector-guarded + idempotent.

Revision ID: 0103_saved_reply_sequences
Revises: 0101_push_subscriptions
Create Date: 2026-11-06
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103_saved_reply_sequences"
down_revision: str | Sequence[str] | None = "0101_push_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("saved_replies")}


def upgrade() -> None:
    have = _columns()
    with op.batch_alter_table("saved_replies") as batch:
        if "conditional" not in have:
            batch.add_column(sa.Column("conditional", sa.Text(), nullable=True))
        if "sent_count" not in have:
            batch.add_column(sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"))
    if "saved_reply_sequences" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "saved_reply_sequences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("position", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("account_id", "name", name="uq_saved_reply_sequences_account_name"),
    )


def downgrade() -> None:
    if "saved_reply_sequences" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("saved_reply_sequences")
    have = _columns()
    with op.batch_alter_table("saved_replies") as batch:
        for name in ("conditional", "sent_count"):
            if name in have:
                batch.drop_column(name)
