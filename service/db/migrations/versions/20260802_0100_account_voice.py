from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0057_account_voice"
down_revision: str | Sequence[str] | None = "0056_quota_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Nullable with no server default on purpose: a default would rewrite every existing row.
    cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "voice" not in cols:
        op.add_column("account_ai_config",
                      sa.Column("voice", sa.String, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "voice" in cols:
        op.drop_column("account_ai_config", "voice")
