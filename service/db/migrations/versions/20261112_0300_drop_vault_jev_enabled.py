"""drop account_ai_config.vault_jev_enabled — Jev v8 is the default for every vault photo

The per-account opt-in (0113) is gone: the describe / flags sweeps run Jev on every photo (`service/vault_jev.py`).
No data to keep (the column only gated the pass). The relay DB never runs alembic; a leftover column there is
unread. Self-contained (no app import), inspector-guarded + idempotent.

Revision ID: 0116_drop_vault_jev_enabled
Revises: 0115_bio_pages
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0116_drop_vault_jev_enabled"
down_revision: str | Sequence[str] | None = "0115_bio_pages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "account_ai_config", "vault_jev_enabled"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL in _live():
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COL)


def downgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.Boolean(), nullable=True))
