from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0143_leak_tracker_tenant_via_instance"
down_revision: str | Sequence[str] | None = "0142_leak_watch_auto_skip"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "leak_tracker_tenant", "via_instance"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
