"""bio_profiles.background_image — a bio page's own backdrop picture (ultra-mode ticket 12)

One String NOT NULL DEFAULT '' (a file name under profiles/<id>, like `avatar`; '' = none, the page as before).
The relay DB's additive-column catch-up (`db.engine.init_db`) adds it too. Self-contained, inspector-guarded +
idempotent.

Revision ID: 0122_bio_profile_background
Revises: 0121_ultra_plans
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0122_bio_profile_background"
down_revision: str | Sequence[str] | None = "0121_ultra_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "bio_profiles", "background_image"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.String(), nullable=False, server_default=sa.text("''")))


def downgrade() -> None:
    if _COL in _live():
        with op.batch_alter_table(_TABLE) as b:
            b.drop_column(_COL)
