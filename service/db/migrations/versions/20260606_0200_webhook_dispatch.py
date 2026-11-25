from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0029_webhook_dispatch"
down_revision: str | Sequence[str] | None = "0028_chatter_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "webhook_config_json" not in ai_cols:
        op.add_column(
            "account_ai_config",
            sa.Column("webhook_config_json", sa.Text, nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ai_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "webhook_config_json" in ai_cols:
        op.drop_column("account_ai_config", "webhook_config_json")
