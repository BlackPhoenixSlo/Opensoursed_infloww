"""agency_notifications.dismissed_at — the owner's "Clear" on an Agency notification

One nullable timestamp: a dismissed row leaves the list but stays (its `dedupe_key` keeps a
sweep from filing the same event again) until the retention prune drops it.
Inspector-guarded + idempotent; init_db's additive-column catch-up adds it on boot too.

Revision ID: 0109_agency_notification_dismissed
Revises: 0108_tracking_link_bot_check
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0109_agency_notification_dismissed"
down_revision: str | Sequence[str] | None = "0108_tracking_link_bot_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COL = "agency_notifications", "dismissed_at"


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _live():
        op.add_column(_TABLE, sa.Column(_COL, sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _COL in _live():
        op.drop_column(_TABLE, _COL)
