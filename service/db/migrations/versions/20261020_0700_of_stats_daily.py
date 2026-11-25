from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084_of_stats_daily"
down_revision: str | Sequence[str] | None = "0083_tx_rollup_fee_vat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "of_stats_daily" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "of_stats_daily",
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("visitors", sa.Integer(), nullable=True),
        sa.Column("new_subs", sa.Integer(), nullable=True),
        sa.Column("renewals", sa.Integer(), nullable=True),
        sa.Column("active_fans", sa.Integer(), nullable=True),
        sa.Column("renew_on", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                name="fk_of_stats_daily_account_id_accounts"),
        sa.PrimaryKeyConstraint("account_id", "day", name="pk_of_stats_daily"),
    )


# Downgrade loses the days OnlyFans no longer charts.
def downgrade() -> None:
    if "of_stats_daily" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("of_stats_daily")
