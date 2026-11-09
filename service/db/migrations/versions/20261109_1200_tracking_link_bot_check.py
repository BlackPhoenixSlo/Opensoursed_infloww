"""tracking_links.bot_check — "Bot check before redirect" (Cloudflare Turnstile) per link

One NOT NULL boolean, server default 0: every existing link stays a plain 302. When 1, GET /t/{slug}
serves the Turnstile page and the click counts only after POST /t/{slug}/verify passes.
Inspector-guarded + idempotent; init_db's additive-column catch-up adds it on boot too.

Revision ID: 0108_tracking_link_bot_check
Revises: 0106_tx_scan_last_full_at
Create Date: 2026-11-09
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0108_tracking_link_bot_check"
down_revision: str | Sequence[str] | None = "0106_tx_scan_last_full_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "tracking_links", "bot_check"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
