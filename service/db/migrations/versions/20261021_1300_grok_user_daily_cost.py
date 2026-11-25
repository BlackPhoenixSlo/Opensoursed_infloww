from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0095_grok_user_daily_cost"
down_revision: str | Sequence[str] | None = "0092_model_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "grok_user_daily_cost"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False),
        sa.Column("is_capped", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_grok_user_daily_cost_user_id_users"),
        sa.PrimaryKeyConstraint("day", "user_id", "provider"),
    )


# Loses only today's no-account spend counters.
def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
