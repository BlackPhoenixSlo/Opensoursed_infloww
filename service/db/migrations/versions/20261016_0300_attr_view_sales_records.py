r"""attr_view_sales_records — the attribution view gains `tx_id` and `rule` for Sales records

Revision ID: 0069_attr_view_sales_records
Revises: 0068_s4s
Create Date: 2026-10-16

Sales records (`GET /admin/stats/sales-records`, service/stats.py;
docs/spec/phase-05-remaining-parity-gaps.md, item 3, Schema "Migration B")
lists one row per sale with the Rule that credited it. One definition of
attribution is the reason this view exists, so the rows come from it rather
than from a second copy of its logic: this revision appends two columns to
EVERY UNION branch of `per_employee_revenue_with_attribution`:

  tx_id  `transactions.id` of the sale the row is.
  rule   how the row's `sent_by_employee_id` was chosen:
           manual        `transactions.attributed_employee_id` is set (the
                         override wins in every branch);
           message       branch 1, credited by the linked message's sender;
           tip_lookback  branch 2, a standalone tip credited by the 7-day
                         lookback's outbound message;
           unassigned    the employee is NULL (a linked message no Employee
                         sent, a lookback that found nothing, an orphan sale
                         with no override).

The six existing columns, their order and every branch's rows are untouched
(the new columns are appended last), and stored rows are never rewritten:
a pure view rebuild (DROP + CREATE), no table, column or index change.
`downgrade()` restores revision 0042's definition
(20260710_0200_attr_view_orphan_rows.py), byte for byte.

Positional readers, checked before writing (ticket 33): no reader selects
the view with `SELECT *` or reads its rows by position, so appending two
columns cannot shift anyone's columns. The command, run from the repo root,
and its result on 2026-10-16:

  grep -rlE "per_employee_revenue_with_attribution|_attr_view\b" service app/lib \
      app/components app/app scripts --include='*.py' --include='*.ts' \
      --include='*.tsx' --include='*.sql' --include='*.sh' \
    | grep -v "migrations/versions" \
    | xargs grep -nEi "select +\*|select\(\s*_attr_view\s*\)|fetchone\(\)\[[0-9]|row\[[0-9]+\]"

  -> no output, exit 1 (no match). The readers it searched: stats.py (the
  `_attr_view` table() proxy, named columns only), attribution_backfill.py,
  transactions.py and sales_attribution.py (docstrings only), and the tests
  that read the view by named columns or COUNT(*)/SUM(...)
  (test_ppv_link_attribution, test_automation_attribution, test_stats_revenue,
  test_attribution_backfill, test_role_enforcement, test_timesheet_api,
  test_sales_attribution_rules).

Deploys run `init_db()`, not `alembic upgrade` (Phase 2 spec, Schema), and
`init_db()` builds no views; like its predecessors this revision reaches a
database only through alembic.
"""
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


# Revision 0042's view (20260710_0200_attr_view_orphan_rows.py), restored on
# downgrade: the same rows without `tx_id` and `rule`.
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
