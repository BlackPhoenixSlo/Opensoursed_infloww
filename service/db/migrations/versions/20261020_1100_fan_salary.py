"""fan_salary — Fan insights › Profile's Salary, Salary frequency, Last pay date

`fans.salary`, `fans.salary_frequency`, `fans.last_pay_date` (all TEXT, NULL):
set by hand in the Fan drawer. NULL until someone fills them in.

The ORM model declares the same columns, so `init_db()`'s ADD-COLUMN catch-up
brings them to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the columns.

Revision ID: 0088_fan_salary
Revises: 0087_account_deactivated
Create Date: 2026-10-20
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088_fan_salary"
down_revision: str | Sequence[str] | None = "0087_account_deactivated"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("salary", "salary_frequency", "last_pay_date")


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("fans")}


def upgrade() -> None:
    missing = [c for c in _COLUMNS if c not in _columns()]
    if missing:
        with op.batch_alter_table("fans") as batch:
            for name in missing:
                batch.add_column(sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    present = [c for c in _COLUMNS if c in _columns()]
    if present:
        with op.batch_alter_table("fans") as batch:
            for name in present:
                batch.drop_column(name)
