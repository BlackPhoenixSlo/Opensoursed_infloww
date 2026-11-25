from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0023_employees_per_user"
down_revision: str | Sequence[str] | None = "0022_users_and_user_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("employees")}
    if "user_id" not in cols:
        op.add_column(
            "employees",
            sa.Column("user_id", sa.String, nullable=True),
        )
        op.create_index(
            "ix_employees_user_id", "employees", ["user_id"]
        )
    # Automation sentinel stays NULL so it never shows in a picker.
    bind.execute(sa.text(
        "UPDATE employees SET user_id = ("
        "  SELECT id FROM users WHERE username = 'founder'"
        ") WHERE user_id IS NULL AND display_name <> 'Automation'"
    ))


def downgrade() -> None:
    op.drop_index("ix_employees_user_id", table_name="employees")
    op.drop_column("employees", "user_id")
