from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0098_runtime_switches"
down_revision: str | Sequence[str] | None = "0096_of_earnings_daily"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "runtime_switches"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_runtime_switches"),
    )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
