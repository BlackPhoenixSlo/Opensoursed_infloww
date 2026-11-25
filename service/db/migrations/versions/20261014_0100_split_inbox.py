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
