"""tx_credit_rollup — attribution materialised on transactions, hourly and daily rollups

Roadmap W2 2.1 and 2.2. Stats and Sales records read these instead of the
attribution view and the wide ledger rows.

  transactions.credit_employee_id      the view's credited Employee for the row
  transactions.credit_rule             manual | message | tip_lookback | unassigned
  transactions.credit_automation_kind  the crediting message's automation_kind
  tx_hourly                            transactions summed per account, UTC hour,
                                       kind, status, linked, credit, rule, automation kind
  tx_daily                             the same per UTC day
  ix_messages_chatter_sends            covers Employee reports' "Messages sent" (S4)

The columns and tables are written only by SQLite triggers, which `init_db()` installs on every
boot (tx_rollup.ensure) and backfills once per box behind a `data_migrations`
marker. The ORM models declare the columns and the tables, so `init_db()`'s
additive catch-up brings them to a booting box; this revision keeps the
alembic chain canonical. Idempotent (inspector-guarded, house convention).
Downgrade drops them; nothing is lost (all are derived from the ledger).

Revision ID: 0077_tx_credit_rollup
Revises: 0076_promo_list
Create Date: 2026-10-19
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077_tx_credit_rollup"
down_revision: str | Sequence[str] | None = "0076_promo_list"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = (
    ("credit_employee_id", sa.Integer()),
    ("credit_rule", sa.String(length=16)),
    ("credit_automation_kind", sa.String()),
)
_TABLES = (("tx_hourly", "hour"), ("tx_daily", "day"))
_SENDS_IX = "ix_messages_chatter_sends"
_SENDS_WHERE = "sent_by_employee_id IS NOT NULL AND mass_run_id IS NULL AND automation_kind IS NULL"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    live = {c["name"] for c in inspector.get_columns("transactions")}
    for name, type_ in _COLS:
        if name not in live:
            op.add_column("transactions", sa.Column(name, type_, nullable=True))
    tables = set(inspector.get_table_names())
    for table, bucket in _TABLES:
        if table in tables:
            continue
        key = ("account_id", bucket, "kind", "status", "linked", "employee_id", "rule", "automation_kind")
        op.create_table(
            table,
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column(bucket, sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("linked", sa.Integer(), nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("rule", sa.String(), nullable=False),
            sa.Column("automation_kind", sa.String(), nullable=False),
            sa.Column("gross_cents", sa.BigInteger(), nullable=False),
            sa.Column("net_cents", sa.BigInteger(), nullable=False),
            sa.Column("net_missing", sa.Integer(), nullable=False),
            sa.Column("net_or_80_cents", sa.BigInteger(), nullable=False),
            sa.Column("sales", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint(*key, name=f"pk_{table}"),
        )
    if _SENDS_IX not in {ix["name"] for ix in inspector.get_indexes("messages")}:
        op.create_index(
            _SENDS_IX, "messages",
            ["account_id", "direction", "created_at", "sent_by_employee_id", "mass_run_id", "automation_kind"],
            sqlite_where=sa.text(_SENDS_WHERE), postgresql_where=sa.text(_SENDS_WHERE),
        )


def downgrade() -> None:
    # init_db's triggers (tx_rollup.py) write the columns and tables dropped
    # below: drop them first, or the next sale or message write fails. Named
    # here, not imported, so this revision stays fixed.
    for name in ("trg_tx_credit_ins", "trg_tx_credit_upd", "trg_msg_credit_ins", "trg_msg_credit_upd",
                 "trg_msg_credit_del", "trg_tx_rollup_ins", "trg_tx_rollup_upd", "trg_tx_rollup_del"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    inspector = sa.inspect(op.get_bind())
    if _SENDS_IX in {ix["name"] for ix in inspector.get_indexes("messages")}:
        op.drop_index(_SENDS_IX, table_name="messages")
    tables = set(inspector.get_table_names())
    for table, _ in _TABLES:
        if table in tables:
            op.drop_table(table)
    live = {c["name"] for c in inspector.get_columns("transactions")}
    for name, _ in _COLS:
        if name in live:
            op.drop_column("transactions", name)
