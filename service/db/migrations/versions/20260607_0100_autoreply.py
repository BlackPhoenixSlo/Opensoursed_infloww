from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0030_autoreply"
down_revision: str | Sequence[str] | None = "0029_webhook_dispatch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "autoreply_config_json" not in ai_cols:
        op.add_column(
            "account_ai_config",
            sa.Column("autoreply_config_json", sa.Text, nullable=True),
        )

    if "autoreply_state" not in set(inspector.get_table_names()):
        op.create_table(
            "autoreply_state",
            sa.Column("account_id", sa.String, primary_key=True),
            sa.Column("fan_id", sa.BigInteger, primary_key=True),
            sa.Column("spell_inbound_at", sa.DateTime, nullable=True),
            sa.Column("nudges_sent", sa.Integer, nullable=False,
                      server_default="0"),
            sa.Column("last_nudge_at", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "autoreply_state" in set(inspector.get_table_names()):
        op.drop_table("autoreply_state")
    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "autoreply_config_json" in ai_cols:
        op.drop_column("account_ai_config", "autoreply_config_json")
