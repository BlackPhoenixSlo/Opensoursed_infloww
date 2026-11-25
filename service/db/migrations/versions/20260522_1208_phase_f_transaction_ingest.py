from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_phase_f_transaction_ingest"
down_revision: str | Sequence[str] | None = "0012_phase_d_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_VIEW_SQL = """
CREATE VIEW per_employee_revenue_with_attribution AS
WITH message_linked AS (
  SELECT
    m.sent_by_employee_id,
    m.account_id,
    t.kind,
    t.amount_cents,
    t.occurred_at
  FROM transactions t
  INNER JOIN messages m
    ON m.account_id = t.account_id
   AND m.message_id = t.message_id
  WHERE t.message_id IS NOT NULL
    AND t.kind IN ('ppv', 'tip')
),
standalone_tips_ranked AS (
  SELECT
    t.id AS tx_id,
    t.account_id,
    t.amount_cents,
    t.kind,
    t.occurred_at,
    m.sent_by_employee_id,
    ROW_NUMBER() OVER (
      PARTITION BY t.id
      ORDER BY m.created_at DESC
    ) AS rn
  FROM transactions t
  LEFT JOIN messages m
    ON m.account_id = t.account_id
   AND m.fan_id = t.fan_id
   AND m.direction = 'out'
   AND m.sent_by_employee_id IS NOT NULL
   AND m.created_at <= t.occurred_at
   AND m.created_at > datetime(t.occurred_at, '-7 days')
  WHERE t.kind = 'tip' AND t.message_id IS NULL
)
SELECT sent_by_employee_id, account_id, kind, amount_cents, occurred_at
  FROM message_linked
UNION ALL
SELECT sent_by_employee_id, account_id, kind, amount_cents, occurred_at
  FROM standalone_tips_ranked
 WHERE rn = 1
"""


def upgrade() -> None:
    # Drop first: the batch rebuild fails with "no such table: main.transactions" while the view binds it.
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))

    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("provider_transaction_id", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column(
                "status",
                sa.String(24),
                nullable=False,
                server_default=sa.text("'cleared'"),
            )
        )
        batch.add_column(sa.Column("cleared_at", sa.DateTime, nullable=True))
        batch.add_column(sa.Column("payout_pending_days", sa.Integer, nullable=True))
        batch.add_column(sa.Column("net_cents", sa.Integer, nullable=True))
        batch.add_column(sa.Column("fee_cents", sa.Integer, nullable=True))
        batch.add_column(sa.Column("vat_cents", sa.Integer, nullable=True))
        batch.add_column(sa.Column("description", sa.Text, nullable=True))
        batch.add_column(
            sa.Column(
                "source",
                sa.String(8),
                nullable=False,
                server_default=sa.text("'ws'"),
            )
        )

    op.execute(sa.text("UPDATE transactions SET source='ws' WHERE source IS NULL"))
    op.execute(sa.text("UPDATE transactions SET status='cleared' WHERE status IS NULL"))

    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_tx_provider_id
              ON transactions(account_id, provider_transaction_id)
              WHERE provider_transaction_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX ix_tx_status_occurred
              ON transactions(status, occurred_at)
            """
        )
    )

    op.create_table(
        "transaction_scan_history",
        sa.Column("account_id", sa.String, nullable=False),
        sa.Column("last_scan_at", sa.DateTime, nullable=True),
        sa.Column("last_marker", sa.Integer, nullable=True),
        sa.Column("oldest_seen_occurred_at", sa.DateTime, nullable=True),
        sa.Column("newest_seen_occurred_at", sa.DateTime, nullable=True),
        sa.Column(
            "fully_backfilled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("backfill_floor", sa.DateTime, nullable=True),
        sa.Column(
            "current_status",
            sa.String,
            nullable=False,
            server_default=sa.text("'idle'"),
        ),
        sa.Column("last_error", sa.String, nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("paused_until", sa.DateTime, nullable=True),
        sa.Column(
            "rows_inserted_total",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rows_patched_total",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("account_id", name="pk_transaction_scan_history"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_transaction_scan_history_account_id_accounts",
        ),
    )

    op.execute(sa.text(_OLD_VIEW_SQL))


def downgrade() -> None:
    # Drop first: the batch rebuild fails with "no such table: main.transactions" while the view binds it.
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))

    op.drop_table("transaction_scan_history")
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tx_status_occurred"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_tx_provider_id"))

    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("source")
        batch.drop_column("description")
        batch.drop_column("vat_cents")
        batch.drop_column("fee_cents")
        batch.drop_column("net_cents")
        batch.drop_column("payout_pending_days")
        batch.drop_column("cleared_at")
        batch.drop_column("status")
        batch.drop_column("provider_transaction_id")

    op.execute(sa.text(_OLD_VIEW_SQL))
