from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0069_attr_view_sales_records"
down_revision: str | Sequence[str] | None = "0068_s4s"
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
    t.occurred_at,
    t.id AS tx_id,
    CASE
      WHEN t.attributed_employee_id IS NOT NULL THEN 'manual'
      WHEN m.sent_by_employee_id IS NOT NULL THEN 'message'
      ELSE 'unassigned'
    END AS rule
  FROM transactions t
  INNER JOIN messages m
    ON m.account_id = t.account_id
   AND m.fan_id = t.fan_id
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
    CASE
      WHEN t.attributed_employee_id IS NOT NULL THEN 'manual'
      WHEN m.sent_by_employee_id IS NOT NULL THEN 'tip_lookback'
      ELSE 'unassigned'
    END AS rule,
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
),
orphan_rows AS (
  SELECT
    t.attributed_employee_id AS sent_by_employee_id,
    NULL AS automation_kind,
    t.account_id,
    t.kind,
    t.amount_cents,
    t.occurred_at,
    t.id AS tx_id,
    CASE WHEN t.attributed_employee_id IS NOT NULL THEN 'manual' ELSE 'unassigned' END AS rule
  FROM transactions t
  WHERE t.kind IN (
      'ppv', 'ppv_message', 'ppv_post', 'ppv_stream',
      'tip', 'tip_post', 'tip_stream',
      'custom'
    )
    AND t.status IN ('cleared', 'pending')
    AND NOT (t.kind IN ('tip', 'tip_post', 'tip_stream') AND t.message_id IS NULL)
    AND NOT EXISTS (
      SELECT 1 FROM messages m
       WHERE m.account_id = t.account_id
         AND m.fan_id = t.fan_id
         AND m.message_id = t.message_id
    )
)
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at, tx_id, rule
  FROM message_linked
UNION ALL
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at, tx_id, rule
  FROM standalone_tips_ranked
 WHERE rn = 1
UNION ALL
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at, tx_id, rule
  FROM orphan_rows
"""


_OLD_VIEW_SQL = """
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
   AND m.fan_id = t.fan_id
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
),
orphan_rows AS (
  SELECT
    t.attributed_employee_id AS sent_by_employee_id,
    NULL AS automation_kind,
    t.account_id,
    t.kind,
    t.amount_cents,
    t.occurred_at
  FROM transactions t
  WHERE t.kind IN (
      'ppv', 'ppv_message', 'ppv_post', 'ppv_stream',
      'tip', 'tip_post', 'tip_stream',
      'custom'
    )
    AND t.status IN ('cleared', 'pending')
    AND NOT (t.kind IN ('tip', 'tip_post', 'tip_stream') AND t.message_id IS NULL)
    AND NOT EXISTS (
      SELECT 1 FROM messages m
       WHERE m.account_id = t.account_id
         AND m.fan_id = t.fan_id
         AND m.message_id = t.message_id
    )
)
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at
  FROM message_linked
UNION ALL
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at
  FROM standalone_tips_ranked
 WHERE rn = 1
UNION ALL
SELECT sent_by_employee_id, automation_kind, account_id, kind, amount_cents, occurred_at
  FROM orphan_rows
"""


def upgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_NEW_VIEW_SQL))


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_OLD_VIEW_SQL))
