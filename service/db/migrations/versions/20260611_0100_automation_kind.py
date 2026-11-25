from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0032_automation_kind"
down_revision: str | Sequence[str] | None = "0031_style_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_VIEW_SQL = """
CREATE VIEW per_employee_revenue_with_attribution AS
WITH message_linked AS (
  SELECT
    COALESCE(t.attributed_employee_id, m.sent_by_employee_id) AS sent_by_employee_id,
    m.automation_kind,
    m.account_id,
    t.kind,
    t.amount_cents,
    t.occurred_at
  FROM transactions t
  INNER JOIN messages m
    ON m.account_id = t.account_id
   AND m.message_id = t.message_id
  WHERE t.message_id IS NOT NULL
    AND t.kind IN (
      'ppv', 'ppv_message', 'ppv_post', 'ppv_stream',
      'tip', 'tip_post', 'tip_stream',
      'custom'
    )
    AND t.status IN ('cleared', 'pending')
),
standalone_tips_ranked AS (
  SELECT
    t.id AS tx_id,
    t.account_id,
    t.amount_cents,
    t.kind,
    t.occurred_at,
    COALESCE(t.attributed_employee_id, m.sent_by_employee_id) AS sent_by_employee_id,
    m.automation_kind,
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
  WHERE t.kind IN ('tip', 'tip_post', 'tip_stream')
    AND t.message_id IS NULL
    AND t.status IN ('cleared', 'pending')
)
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at
  FROM message_linked
UNION ALL
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at
  FROM standalone_tips_ranked
 WHERE rn = 1
"""


_OLD_VIEW_SQL = """
CREATE VIEW per_employee_revenue_with_attribution AS
WITH message_linked AS (
  SELECT
    COALESCE(t.attributed_employee_id, m.sent_by_employee_id) AS sent_by_employee_id,
    m.account_id,
    t.kind,
    t.amount_cents,
    t.occurred_at
  FROM transactions t
  INNER JOIN messages m
    ON m.account_id = t.account_id
   AND m.message_id = t.message_id
  WHERE t.message_id IS NOT NULL
    AND t.kind IN (
      'ppv', 'ppv_message', 'ppv_post', 'ppv_stream',
      'tip', 'tip_post', 'tip_stream',
      'custom'
    )
    AND t.status IN ('cleared', 'pending')
),
standalone_tips_ranked AS (
  SELECT
    t.id AS tx_id,
    t.account_id,
    t.amount_cents,
    t.kind,
    t.occurred_at,
    COALESCE(t.attributed_employee_id, m.sent_by_employee_id) AS sent_by_employee_id,
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
  WHERE t.kind IN ('tip', 'tip_post', 'tip_stream')
    AND t.message_id IS NULL
    AND t.status IN ('cleared', 'pending')
)
SELECT sent_by_employee_id, account_id, kind, amount_cents, occurred_at
  FROM message_linked
UNION ALL
SELECT sent_by_employee_id, account_id, kind, amount_cents, occurred_at
  FROM standalone_tips_ranked
 WHERE rn = 1
"""


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    msg_cols = {c["name"] for c in inspector.get_columns("messages")}
    if "automation_kind" not in msg_cols:
        op.add_column("messages", sa.Column("automation_kind", sa.String, nullable=True))

    run_cols = {c["name"] for c in inspector.get_columns("mass_runs")}
    if "queue_id" not in run_cols:
        op.add_column("mass_runs", sa.Column("queue_id", sa.BigInteger, nullable=True))
    if "automation_kind" not in run_cols:
        op.add_column("mass_runs", sa.Column("automation_kind", sa.String, nullable=True))

    msg_idx = {ix["name"] for ix in inspector.get_indexes("messages")}
    if "ix_messages_automation_kind" not in msg_idx:
        op.create_index(
            "ix_messages_automation_kind",
            "messages",
            ["account_id", "automation_kind", "created_at"],
            sqlite_where=sa.text("automation_kind IS NOT NULL"),
            postgresql_where=sa.text("automation_kind IS NOT NULL"),
        )
    run_idx = {ix["name"] for ix in inspector.get_indexes("mass_runs")}
    if "ix_mass_runs_queue" not in run_idx:
        op.create_index(
            "ix_mass_runs_queue",
            "mass_runs",
            ["account_id", "queue_id"],
            sqlite_where=sa.text("queue_id IS NOT NULL"),
            postgresql_where=sa.text("queue_id IS NOT NULL"),
        )

    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_NEW_VIEW_SQL))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_OLD_VIEW_SQL))

    run_idx = {ix["name"] for ix in inspector.get_indexes("mass_runs")}
    if "ix_mass_runs_queue" in run_idx:
        op.drop_index("ix_mass_runs_queue", table_name="mass_runs")
    msg_idx = {ix["name"] for ix in inspector.get_indexes("messages")}
    if "ix_messages_automation_kind" in msg_idx:
        op.drop_index("ix_messages_automation_kind", table_name="messages")

    run_cols = {c["name"] for c in inspector.get_columns("mass_runs")}
    if "automation_kind" in run_cols:
        op.drop_column("mass_runs", "automation_kind")
    if "queue_id" in run_cols:
        op.drop_column("mass_runs", "queue_id")
    msg_cols = {c["name"] for c in inspector.get_columns("messages")}
    if "automation_kind" in msg_cols:
        op.drop_column("messages", "automation_kind")
