from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0096_of_earnings_daily"
down_revision: str | Sequence[str] | None = "0095_grok_user_daily_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "of_earnings_daily"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("net_cents", sa.Integer(), nullable=False),
        sa.Column("gross_cents", sa.Integer(), nullable=False),
        sa.Column("sales", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                name="fk_of_earnings_daily_account_id_accounts"),
        sa.PrimaryKeyConstraint("account_id", "day", "category", name="pk_of_earnings_daily"),
    )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
