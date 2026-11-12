"""account_ai_config.vault_jev_enabled — per-account opt-in for the Jev v8 vault flags pass

One nullable boolean (NULL ≡ off): when set, the describe/flags sweeps run TypeSafe Jev + NudeNet on each
vault photo first (`service/vault_jev.py`) and store `ai_fields_json["_jev"]`. The relay DB never runs
alembic; its additive-column catch-up (`db.engine.init_db`) adds this column too. Self-contained (no app
import), inspector-guarded + idempotent.

Revision ID: 0113_vault_jev_enabled
Revises: 0112_mass_run_crawl_outcome
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0113_vault_jev_enabled"
down_revision: str | Sequence[str] | None = "0112_mass_run_crawl_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "account_ai_config", "vault_jev_enabled"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.Boolean(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
