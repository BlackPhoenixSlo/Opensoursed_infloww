from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021_mass_broadcast_cache"
down_revision: str | Sequence[str] | None = "0020_saved_reply_script"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mass_broadcast_cache" in inspector.get_table_names():
        return
    op.create_table(
        "mass_broadcast_cache",
        sa.Column(
            "account_id", sa.String,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("queue_id", sa.BigInteger, primary_key=True),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("text", sa.Text, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("giphy_id", sa.String, nullable=True),
        sa.Column("is_free", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("is_tip", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("media_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("media_json", sa.Text, nullable=True),
        sa.Column("previews_json", sa.Text, nullable=True),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("viewed_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("is_canceled", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("can_unsend", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("unsend_seconds", sa.Integer, nullable=True),
        sa.Column("template", sa.String, nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime,
            nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_mass_broadcast_cache_account_sent_at",
        "mass_broadcast_cache",
        ["account_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mass_broadcast_cache_account_sent_at",
        table_name="mass_broadcast_cache",
    )
    op.drop_table("mass_broadcast_cache")
