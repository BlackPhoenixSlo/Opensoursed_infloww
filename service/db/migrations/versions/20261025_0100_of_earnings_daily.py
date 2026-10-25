"""of_earnings_daily — OnlyFans' own earnings per Creator per UTC day per category

The daily OF Statistics job (service/of_stats_daily.py) stores what OnlyFans'
Statistics › Statements charts (`/earnings/chart`) for each complete day, back
to `_EARNINGS_HISTORY_DAYS`, so the Dashboard and Creator reports show a
Creator's real earnings for days before it was connected, or that the ledger
missed (stats.py reads these days in place of the ledger's).

  of_earnings_daily.account_id   PK, FK accounts.id ON DELETE CASCADE
  of_earnings_daily.day          PK, 'YYYY-MM-DD' UTC
  of_earnings_daily.category     PK, OF's key (subscribes, tips, messages, post, stream)
  of_earnings_daily.net_cents    OF's charted net for the day
  of_earnings_daily.gross_cents  that net at the reply's gross/net ratio
  of_earnings_daily.sales        OF's charted count for the day
  of_earnings_daily.fetched_at

The ORM model in db/models.py declares the same table, so `init_db()`'s
create_all brings it to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
the table; the next job run reads the days back from OnlyFans.

Revision ID: 0096_of_earnings_daily
Revises: 0095_grok_user_daily_cost
Create Date: 2026-10-25
"""
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
