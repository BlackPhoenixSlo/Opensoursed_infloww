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
