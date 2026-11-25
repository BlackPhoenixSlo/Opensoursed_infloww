from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0099_converters_window"
down_revision: str | Sequence[str] | None = "0098_runtime_switches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = (
    ("credit_sender_id", sa.Integer()),
    ("credit_converter_id", sa.Integer()),
    ("credit_converter_at", sa.DateTime()),
)

_NEW_VIEW_SQL = """
CREATE VIEW per_employee_revenue_with_attribution AS
WITH sales AS (
  SELECT
    t.id AS tx_id,
    t.account_id,
    t.kind,
    t.amount_cents,
    t.occurred_at,
    t.attributed_employee_id,
    (SELECT m.sent_by_employee_id FROM messages m
      WHERE m.account_id = t.account_id AND m.fan_id = t.fan_id AND m.message_id = t.message_id) AS sender_id,
    (SELECT m.automation_kind FROM messages m
      WHERE m.account_id = t.account_id AND m.fan_id = t.fan_id AND m.message_id = t.message_id) AS automation_kind,
    (SELECT m.sent_by_employee_id FROM messages m
      WHERE m.account_id = t.account_id AND m.fan_id = t.fan_id
        AND m.direction = 'out' AND m.sent_by_employee_id IS NOT NULL
        AND m.mass_run_id IS NULL AND m.automation_kind IS NULL
        AND m.sent_by_employee_id NOT IN
            (SELECT e.id FROM employees e WHERE e.display_name = 'Automation' AND e.is_active = 0)
        AND m.created_at <= t.occurred_at
        AND m.created_at >= strftime('%Y-%m-%d %H:%M:%f', t.occurred_at, '-3599940 seconds')
      ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1) AS converter_id,
    (SELECT m.created_at FROM messages m
      WHERE m.account_id = t.account_id AND m.fan_id = t.fan_id
        AND m.direction = 'out' AND m.sent_by_employee_id IS NOT NULL
        AND m.mass_run_id IS NULL AND m.automation_kind IS NULL
        AND m.sent_by_employee_id NOT IN
            (SELECT e.id FROM employees e WHERE e.display_name = 'Automation' AND e.is_active = 0)
        AND m.created_at <= t.occurred_at
        AND m.created_at >= strftime('%Y-%m-%d %H:%M:%f', t.occurred_at, '-3599940 seconds')
      ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1) AS converter_at
  FROM transactions t
  WHERE t.kind IN (
      'ppv', 'ppv_message', 'ppv_post', 'ppv_stream',
      'tip', 'tip_post', 'tip_stream',
      'custom'
    )
    AND t.status IN ('cleared', 'pending')
),
credited AS (
  SELECT *,
    strftime('%Y-%m-%d %H:%M:%f', converter_at, '+0 seconds')
      >= strftime('%Y-%m-%d %H:%M:%f', occurred_at, '-3600 seconds') AS in_default
  FROM sales
)
SELECT
  COALESCE(attributed_employee_id, CASE WHEN in_default THEN converter_id END) AS sent_by_employee_id,
  automation_kind,
  account_id,
  kind,
  amount_cents,
  occurred_at,
  tx_id,
  CASE
    WHEN attributed_employee_id IS NOT NULL THEN 'manual'
    WHEN in_default THEN 'converters'
    ELSE 'unassigned'
  END AS rule,
  sender_id,
  converter_id,
  converter_at
FROM credited
"""

_TRIGGERS = ("trg_tx_credit_ins", "trg_tx_credit_upd", "trg_msg_credit_ins", "trg_msg_credit_upd",
             "trg_msg_credit_del", "trg_tx_rollup_upd", "trg_tx_rollup_del")


def _predecessor_view_sql() -> str:
    path = Path(__file__).with_name("20261016_0300_attr_view_sales_records.py")
    spec = importlib.util.spec_from_file_location("_attr_view_0069", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig._NEW_VIEW_SQL


def upgrade() -> None:
    live = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("transactions")}
    for name, type_ in _COLS:
        if name not in live:
            op.add_column("transactions", sa.Column(name, type_, nullable=True))
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_NEW_VIEW_SQL))


def downgrade() -> None:
    # Drop init_db's triggers first, or the next sale or message write fails on the dropped columns.
    for name in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_predecessor_view_sql()))
    live = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("transactions")}
    for name, _ in _COLS:
        if name in live:
            op.drop_column("transactions", name)
