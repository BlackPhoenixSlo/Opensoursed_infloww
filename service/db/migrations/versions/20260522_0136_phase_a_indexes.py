from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_phase_a_indexes"
down_revision: str | Sequence[str] | None = "0008_phase_a_drop_bought_amount"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prompts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("response_schema_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("prompts", schema=None) as batch_op:
        batch_op.drop_column("response_schema_json")
