from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_phase_a_drop_bought_amount"
down_revision: str | Sequence[str] | None = "0007_phase_a_safety_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Run backfills/backfill_lifetime_spend.py first: fans with bought_amount > 0 and lifetime_spend_cents = 0 must be 0, else their spend data is silently lost.
def upgrade() -> None:
    with op.batch_alter_table("fans", schema=None) as batch_op:
        batch_op.drop_column("bought_amount")


def downgrade() -> None:
    with op.batch_alter_table("fans", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "bought_amount",
                sa.NUMERIC(precision=10, scale=2),
                nullable=False,
                server_default="0",
            )
        )
