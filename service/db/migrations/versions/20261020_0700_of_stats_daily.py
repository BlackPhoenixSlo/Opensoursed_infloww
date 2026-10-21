"""of_stats_daily — OnlyFans Statistics figures per Creator per UTC day

Roadmap W5 5.5 (05-analytics B4, M12). The daily snapshot job
(service/of_stats_daily.py) writes one row per Creator per UTC day, so Creator
reports can sum any window of figures OnlyFans only answers live.

  of_stats_daily.account_id   PK, FK accounts.id ON DELETE CASCADE
  of_stats_daily.day          PK, 'YYYY-MM-DD' UTC
  of_stats_daily.visitors     Reach's profile visitors
  of_stats_daily.new_subs     the Subscriptions chart's New tab
  of_stats_daily.renewals     its Renews tab
  of_stats_daily.active_fans  the subscriber roster at the day's last crawl
  of_stats_daily.renew_on     of those, the fans with auto-renew on
  of_stats_daily.fetched_at
  of_stats_daily.attempts      the OF fetches tried for this day (the job's
                               daily cap, kept across restarts)
  of_stats_daily.attempted_at  the last of them

The ORM model in db/models.py declares the same table, so `init_db()`'s
create_all brings it to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
the table; that loses the days OnlyFans no longer charts.

Revision ID: 0084_of_stats_daily
Revises: 0083_tx_rollup_fee_vat
Create Date: 2026-10-20
"""
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


def downgrade() -> None:
    if "of_stats_daily" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("of_stats_daily")
