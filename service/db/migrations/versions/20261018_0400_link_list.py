"""link_list — the Edit dialog's List on Growth's links (link_meta)

Backs service/link_metrics.py's List: the OnlyFans fan list a free trial link's
or tracking link's claimers are added to with OF's own "Add to list" (one call
adds every current claimer; a repeat adds nobody twice).

  link_meta.list_id           OF's custom list id (a number, kept as text)
  link_meta.list_name         its name when picked, for the List column
  link_meta.list_added_count  OF's claim count at the last successful add;
                              NULL = not added to this list yet

All three are nullable, so `init_db()`'s additive catch-up adds them on a box
that boots without running alembic; this revision keeps the chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the columns;
that loses only which list a link feeds (the fans already in it stay on OF).

Revision ID: 0074_link_list
Revises: 0073_link_metrics
Create Date: 2026-10-18
"""
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


def downgrade() -> None:
    have = _have()
    with op.batch_alter_table("link_meta") as b:
        for name, _typ in reversed(_COLS):
            if name in have:
                b.drop_column(name)
