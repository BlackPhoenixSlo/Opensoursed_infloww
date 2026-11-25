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
    return conn.execute(sa.text(BACKFILL)).rowcount or 0


# Guarded + backfill once: init_db runs backfill on the boot whose catch-up added the column.
def upgrade() -> None:
    cols = _cols(sa.inspect(op.get_bind()), "ai_decisions")
    if cols and "offer_attempt_at" not in cols:
        op.add_column("ai_decisions", sa.Column("offer_attempt_at", sa.DateTime(), nullable=True))
        backfill(op.get_bind())


def downgrade() -> None:
    if "offer_attempt_at" in _cols(sa.inspect(op.get_bind()), "ai_decisions"):
        with op.batch_alter_table("ai_decisions") as b:
            b.drop_column("offer_attempt_at")
