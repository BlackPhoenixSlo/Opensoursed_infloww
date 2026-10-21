"""smart_list_sync — a Smart List can own and sync a real OnlyFans user list

`smart_lists` gains the sync state the `smart_list_sync` automation keeps:
of_list_id / of_list_name (the OF list it created and the name it last wrote),
is_active (synced or not, under a per-account quota), sync_state (syncing |
ok | pending | error | deleting — `syncing` is the edit/delete lock,
deleting a tombstone awaiting its OF list delete), sync_error,
synced_at ("Last updated") and member_count.

The ORM model declares the same columns, so `init_db()`'s ADD-COLUMN catch-up
brings them to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the columns.

Revision ID: 0080_smart_list_sync
Revises: 0079_link_shares
Create Date: 2026-10-20
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080_smart_list_sync"
down_revision: str | Sequence[str] | None = "0079_link_shares"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("of_list_id", sa.BigInteger(), nullable=True),
    sa.Column("of_list_name", sa.String(), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    sa.Column("sync_state", sa.String(), nullable=True),
    sa.Column("sync_error", sa.Text(), nullable=True),
    sa.Column("synced_at", sa.DateTime(), nullable=True),
    sa.Column("member_count", sa.Integer(), nullable=True),
)


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("smart_lists")}


def upgrade() -> None:
    have = _columns()
    missing = [c for c in _COLUMNS if c.name not in have]
    if missing:
        with op.batch_alter_table("smart_lists") as batch:
            for col in missing:
                batch.add_column(col)


def downgrade() -> None:
    have = _columns()
    present = [c.name for c in _COLUMNS if c.name in have]
    if present:
        with op.batch_alter_table("smart_lists") as batch:
            for name in present:
                batch.drop_column(name)
