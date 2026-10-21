"""split_inbox — account_ai_config.split_inbox_json

Revision ID: 0066_split_inbox
Revises: 0065_user_settings
Create Date: 2026-10-14

Split Inbox groups for a Creator (ADR-0004), stored beside the Creator's
account config so every Employee on every device reads the same split:

  account_ai_config  — + split_inbox_json: JSON {group_count: 1..9,
                       assignments: {"<fanId>": 1..group_count}}, written by
                       service/split_inbox_api.py. NULL → not split.

No backfill: NULL is the intended default. init_db's ADD-COLUMN catch-up
applies the same column on a booting box, so this migration keeps the alembic
chain canonical. Additive + nullable + idempotent (inspector-guarded, house
convention).
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0066_split_inbox"
down_revision: str | Sequence[str] | None = "0065_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "split_inbox_json" not in ai_cols:
        op.add_column(
            "account_ai_config",
            sa.Column("split_inbox_json", sa.Text, nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "split_inbox_json" in ai_cols:
        op.drop_column("account_ai_config", "split_inbox_json")
