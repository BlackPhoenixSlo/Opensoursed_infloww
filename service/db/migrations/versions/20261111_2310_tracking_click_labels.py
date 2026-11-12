"""Raw click labels for redirect-link stats.

Revision ID: 0114_tracking_click_labels
Revises: 0113_vault_jev_enabled
"""
from __future__ import annotations
from typing import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0114_tracking_click_labels"
down_revision: str | Sequence[str] | None = "0113_vault_jev_enabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tracking_clicks")}
    for name, kind in (("country", sa.String(2)), ("in_app", sa.String()), ("ref", sa.String())):
        if name not in cols:
            op.add_column("tracking_clicks", sa.Column(name, kind, nullable=True))
    if "verified" not in cols:
        op.add_column("tracking_clicks", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.create_index("ix_tracking_clicks_stats", "tracking_clicks",
                    ["tracking_link_id", "clicked_at", "verified", "country", "in_app", "ref"], if_not_exists=True)
    op.drop_index("ix_tracking_clicks_link_time", "tracking_clicks", if_exists=True)


def downgrade() -> None:
    op.create_index("ix_tracking_clicks_link_time", "tracking_clicks", ["tracking_link_id", "clicked_at"], if_not_exists=True)
    op.drop_index("ix_tracking_clicks_stats", "tracking_clicks", if_exists=True)
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tracking_clicks")}
    for name in ("verified", "ref", "in_app", "country"):
        if name in cols:
            op.drop_column("tracking_clicks", name)
