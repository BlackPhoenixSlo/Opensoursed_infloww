from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074_link_list"
down_revision: str | Sequence[str] | None = "0073_link_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = (
    ("list_id", sa.String(length=32)),
    ("list_name", sa.String(length=64)),
    ("list_added_count", sa.Integer()),
)


def _have() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("link_meta")}


def upgrade() -> None:
    have = _have()
    with op.batch_alter_table("link_meta") as b:
        for name, typ in _COLS:
            if name not in have:
                b.add_column(sa.Column(name, typ, nullable=True))


# Loses only which list a link feeds; the fans already in it stay on OF.
def downgrade() -> None:
    have = _have()
    with op.batch_alter_table("link_meta") as b:
        for name, _typ in reversed(_COLS):
            if name in have:
                b.drop_column(name)
