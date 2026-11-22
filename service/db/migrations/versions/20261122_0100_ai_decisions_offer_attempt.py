"""ai_decisions.offer_attempt_at — the Full AI Offer carrier's POST was attempted

`full_ai_ppv.send_priced` stamps it (conditionally, once) right before the
carrier's POST. Only an attempted row may be linked to an OF message by the
timeout readback or `full_ai_settle`'s heuristic, and an attempted, unresolved
priced Offer keeps its media reserved. One nullable DateTime column.

Backfill (`backfill`, W30 C4): a legacy live priced row that may have POSTed
(`sending`, or `sent` / `unconfirmed` with no `offer_message_id`, unresolved) gets
`offer_attempt_at = created_at`, so reap keeps it and settle may still link it.
Run when this step adds the column; db.engine's init_db runs it once, on the boot
whose catch-up added the column (`data_migrations` marker). Guarded: a later
manual `alembic upgrade head` must not re-add the column.

Revision ID: 0130_ai_decisions_offer_attempt
Revises: 0129_keep_running_rules_heal
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0130_ai_decisions_offer_attempt"
down_revision: str | Sequence[str] | None = "0129_keep_running_rules_heal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cols(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


BACKFILL = (
    "UPDATE ai_decisions SET offer_attempt_at = created_at "
    "WHERE mode = 'live' AND offer_price_cents > 0 AND offer_message_id IS NULL "
    "AND outcome IS NULL AND offer_attempt_at IS NULL "
    "AND status IN ('sending', 'sent', 'unconfirmed')"
)


def backfill(conn) -> int:
    """Stamp the legacy rows that may have POSTed (`BACKFILL`); `conn` is a sync connection
    in the caller's transaction. Returns rows stamped."""
    return conn.execute(sa.text(BACKFILL)).rowcount or 0


def upgrade() -> None:
    cols = _cols(sa.inspect(op.get_bind()), "ai_decisions")
    if cols and "offer_attempt_at" not in cols:
        op.add_column("ai_decisions", sa.Column("offer_attempt_at", sa.DateTime(), nullable=True))
        backfill(op.get_bind())


def downgrade() -> None:
    if "offer_attempt_at" in _cols(sa.inspect(op.get_bind()), "ai_decisions"):
        with op.batch_alter_table("ai_decisions") as b:
            b.drop_column("offer_attempt_at")
