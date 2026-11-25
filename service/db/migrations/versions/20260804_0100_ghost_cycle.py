from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0058_ghost_cycle"
down_revision: str | Sequence[str] | None = "0057_account_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cols(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    rs = _cols(inspector, "rhythm_state")
    if rs and "ghost_anchor" not in rs:
        op.add_column("rhythm_state", sa.Column("ghost_anchor", sa.DateTime, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ghost_anchor" in _cols(inspector, "rhythm_state"):
        op.drop_column("rhythm_state", "ghost_anchor")
