from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0138_leak_watch"
down_revision: str | Sequence[str] | None = "0137_leak_tracker_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "leak_watch"


def upgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agency_user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("watch_id", sa.String, nullable=False, unique=True),
        sa.Column("on", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("platform", sa.String, nullable=False),
        sa.Column("username", sa.String, nullable=False),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("display_name", sa.String(64), nullable=False, server_default=sa.text("''")),
        sa.Column("aliases_json", sa.Text, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("instagram", sa.String, nullable=True),
        sa.Column("x", sa.String, nullable=True),
        sa.Column("consent_at", sa.DateTime, nullable=False),
        sa.Column("consent_by", sa.String, nullable=False),
        sa.Column("synced_at", sa.DateTime, nullable=True),
        sa.Column("synced_paused", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("agency_user_id", "account_id", name="uq_leak_watch_account"),
        sa.UniqueConstraint("agency_user_id", "platform", "username", name="uq_leak_watch_handle"),
    )


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
