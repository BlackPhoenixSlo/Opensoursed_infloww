from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0060_day_log"
down_revision: str | Sequence[str] | None = "0059_customs_owed_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cfg_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "day_log_json" not in cfg_cols:
        op.add_column("account_ai_config", sa.Column("day_log_json", sa.Text, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cfg_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "day_log_json" in cfg_cols:
        op.drop_column("account_ai_config", "day_log_json")
