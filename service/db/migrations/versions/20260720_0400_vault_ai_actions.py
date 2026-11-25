from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0049_vault_ai_actions"
down_revision: str | Sequence[str] | None = "0048_vault_of_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "vault_items" in tables:
        cols = {c["name"] for c in inspector.get_columns("vault_items")}
        if "story_score" not in cols:
            op.add_column("vault_items", sa.Column("story_score", sa.Integer(), nullable=True))
        if "tip_vault_score" not in cols:
            op.add_column("vault_items", sa.Column("tip_vault_score", sa.Integer(), nullable=True))

    if "account_ai_config" in tables:
        cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
        if "vault_ai_config_json" not in cols:
            op.add_column(
                "account_ai_config",
                sa.Column("vault_ai_config_json", sa.Text(), nullable=True),
            )

    if "vault_ai_review_items" not in tables:
        op.create_table(
            "vault_ai_review_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.String(),
                      sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("baseline_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_vault_ai_review_account_status",
                        "vault_ai_review_items", ["account_id", "status"])
        op.create_index("ix_vault_ai_review_account_kind",
                        "vault_ai_review_items", ["account_id", "kind", "status"])

    if "vault_daily_usage" not in tables:
        op.create_table(
            "vault_daily_usage",
            sa.Column("account_id", sa.String(),
                      sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("media_id", sa.BigInteger(), primary_key=True),
            sa.Column("sent_on", sa.Date(), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_vault_daily_usage_account_day",
                        "vault_daily_usage", ["account_id", "sent_on"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "vault_daily_usage" in tables:
        op.drop_table("vault_daily_usage")
    if "vault_ai_review_items" in tables:
        op.drop_table("vault_ai_review_items")

    if "account_ai_config" in tables:
        cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
        if "vault_ai_config_json" in cols:
            op.drop_column("account_ai_config", "vault_ai_config_json")

    if "vault_items" in tables:
        cols = {c["name"] for c in inspector.get_columns("vault_items")}
        if "tip_vault_score" in cols:
            op.drop_column("vault_items", "tip_vault_score")
        if "story_score" in cols:
            op.drop_column("vault_items", "story_score")
