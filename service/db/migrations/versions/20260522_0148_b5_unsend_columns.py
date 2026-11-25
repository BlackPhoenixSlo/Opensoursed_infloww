from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_b5_unsend_columns"
down_revision: str | Sequence[str] | None = "0009_phase_a_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("unsent_by_employee_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("unsent_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("unsent_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            # server_default required: the SQLite batch rebuild must backfill existing rows.
            sa.Column("is_promise", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("promise_due_date", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_messages_unsent_by_employee_id_employees"),
            "employees",
            ["unsent_by_employee_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_messages_unsent_by_employee_id_employees"), type_="foreignkey"
        )
        batch_op.drop_column("promise_due_date")
        batch_op.drop_column("is_promise")
        batch_op.drop_column("unsent_at")
        batch_op.drop_column("unsent_reason")
        batch_op.drop_column("unsent_by_employee_id")
