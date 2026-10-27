r"""converters_window — Converters credits the last human chatter within the Agency's window

Revision ID: 0099_converters_window
Revises: 0098_runtime_switches
Create Date: 2026-10-27

Infloww's Converters rule (web bundle v5.2.9, help article 262080): "Sale is
attributed to the last Chatter who messaged the fan within X hours and Y
minutes of the sale", for every sale kind it governs, with one window per
Agency (Sales Settings `attribution.converters_window_seconds`, 1 h by
default, at most 999 h 59 min). Until now Converters was the linked message's
sender, else for a standalone tip the last outbound sender of 7 days (any
sender), so it credited exactly as Message sender did.

  transactions.credit_sender_id     the linked message's sender (Message sender)
  transactions.credit_converter_id  the last human chatter's send to the fan at
  transactions.credit_converter_at  or before the sale within 999 h 59 min:
                                    its Employee and time
  per_employee_revenue_with_attribution
      every tracked revenue sale (REVENUE_KINDS, cleared or pending) once:
      `sent_by_employee_id` the override, else the converter when it is inside
      the default 1 h window; `rule` manual | converters | unassigned;
      `automation_kind` the linked message's; and the three columns above.
      A human chatter's send: outbound, an Employee's, no mass message, no
      automation kind, not the Automation sentinel.

The columns are written only by tx_rollup's triggers (init_db installs them
and recomputes every row once behind its `data_migrations` marker); the view
is the oracle `tx_rollup.credit_mismatches` checks the triggers against, and
`db.engine.ensure_attribution_view` reads `_NEW_VIEW_SQL` from this file.
The Agency's own window is versioned Sales Settings and is applied in the read
path (sales_attribution.credit), so neither the view nor the triggers read
settings. Idempotent (inspector-guarded, house convention). Downgrade drops
the triggers that write the columns (init_db reinstalls its own), the columns,
and restores revision 0069's view byte for byte.
"""
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

# 999 h 59 min and 1 h, in seconds; the human-send predicate is
# tx_rollup.human_send's, written out so this revision stays fixed.
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
    """Revision 0069's view (20261016_0300_attr_view_sales_records.py)."""
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
    # init_db's triggers (tx_rollup.py) write the columns dropped below: drop
    # them first, or the next sale or message write fails. Named here, not
    # imported, so this revision stays fixed.
    for name in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute(sa.text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
    op.execute(sa.text(_predecessor_view_sql()))
    live = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("transactions")}
    for name, _ in _COLS:
        if name in live:
            op.drop_column("transactions", name)
