from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087_account_deactivated"
down_revision: str | Sequence[str] | None = "0086_auth_sessions_2fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("account_health")}


def upgrade() -> None:
    if "deactivated_at" not in _columns():
        op.add_column("account_health", sa.Column("deactivated_at", sa.DateTime(), nullable=True))


# downgrade re-activates every deactivated Creator
def downgrade() -> None:
    if "deactivated_at" in _columns():
        op.drop_column("account_health", "deactivated_at")
