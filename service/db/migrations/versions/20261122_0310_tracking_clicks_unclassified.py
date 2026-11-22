"""Partial index of unclassified redirect clicks (NULL ref).

The boot classifier (tracking_stats._classify_chunk) reads `WHERE ref IS NULL AND id > :last ORDER BY id`;
without this index each restart walked every tracking_clicks row to find none.

Revision ID: 0133_tracking_clicks_unclassified
Revises: 0131_vault_solo_sequences
Create Date: 2026-11-22
"""
from __future__ import annotations
from typing import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0133_tracking_clicks_unclassified"
down_revision: str | Sequence[str] | None = "0131_vault_solo_sequences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_tracking_clicks_unclassified", "tracking_clicks", ["id"], if_not_exists=True,
                    sqlite_where=sa.text("ref IS NULL"), postgresql_where=sa.text("ref IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_tracking_clicks_unclassified", "tracking_clicks", if_exists=True)
