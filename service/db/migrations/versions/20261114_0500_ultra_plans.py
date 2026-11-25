from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0121_ultra_plans"
down_revision: str | Sequence[str] | None = "0120_full_ai_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _INDEX = "ultra_plans", "ix_ultra_plans_owner_user_id"


def upgrade() -> None:
    if _TABLE not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("owner_user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source", sa.String(8), nullable=False),
            sa.Column("plan_json", sa.Text, nullable=False),
            sa.Column("plan_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("step_states", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("approved_at", sa.DateTime, nullable=True),
            sa.Column("finished_at", sa.DateTime, nullable=True),
        )
    if _INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["owner_user_id"])


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
