from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0061_rhythm_stepout"
down_revision: str | Sequence[str] | None = "0060_day_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cols(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    rs = _cols(inspector, "rhythm_state")
    if not rs:
        return
    if "stepout_mark" not in rs:
        op.add_column("rhythm_state", sa.Column("stepout_mark", sa.Integer, nullable=True))
    if "stepout_target" not in rs:
        op.add_column("rhythm_state", sa.Column("stepout_target", sa.Integer, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    rs = _cols(inspector, "rhythm_state")
    if "stepout_target" in rs:
        op.drop_column("rhythm_state", "stepout_target")
    if "stepout_mark" in rs:
        op.drop_column("rhythm_state", "stepout_mark")
