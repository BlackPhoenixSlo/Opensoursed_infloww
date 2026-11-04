"""push_subscriptions + push_sent — Web Push subscriptions and their sent tags (push_api / push_send)

Two NEW tables, no change to any existing one. `create_all()` materializes it on
boot from its model (init_db in db/engine.py); this file keeps the alembic
chain linear for the alembic-managed copies. Inspector-guarded + idempotent.

Revision ID: 0101_push_subscriptions
Revises: 0099_converters_window
Create Date: 2026-11-03
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0101_push_subscriptions"
down_revision: str | Sequence[str] | None = "0099_converters_window"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    have = sa.inspect(op.get_bind()).get_table_names()
    if "push_sent" not in have:
        op.create_table(
            "push_sent",
            sa.Column("sub_id", sa.String, primary_key=True),
            sa.Column("tag", sa.String, primary_key=True),
            sa.Column("sent_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index("ix_push_sent_sent_at", "push_sent", ["sent_at"])
    if "push_subscriptions" in have:
        return
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("endpoint", sa.Text, nullable=False, unique=True),
        sa.Column("p256dh", sa.String, nullable=False),
        sa.Column("auth", sa.String, nullable=False),
        sa.Column("principal_kind", sa.String, nullable=False),
        sa.Column("principal_id", sa.String, nullable=False),
        sa.Column("issued_ms", sa.BigInteger, nullable=False),
        sa.Column("types", sa.Text, nullable=False, server_default="[]"),
        sa.Column("platforms", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_push_subscriptions_principal", "push_subscriptions", ["principal_kind", "principal_id"])


def downgrade() -> None:
    have = sa.inspect(op.get_bind()).get_table_names()
    for t in ("push_sent", "push_subscriptions"):
        if t in have:
            op.drop_table(t)
