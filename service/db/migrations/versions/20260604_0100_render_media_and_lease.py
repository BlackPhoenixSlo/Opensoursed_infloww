from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0025_render_media_and_lease"
down_revision: str | Sequence[str] | None = "0024_chatter_login"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "message_media" not in existing:
        op.create_table(
            "message_media",
            sa.Column("account_id", sa.String, nullable=False),
            sa.Column("fan_id", sa.BigInteger, nullable=False),
            sa.Column("message_id", sa.BigInteger, nullable=False),
            sa.Column("media_id", sa.BigInteger, nullable=False),
            sa.Column("type", sa.String, nullable=True),
            sa.Column("width", sa.Integer, nullable=True),
            sa.Column("height", sa.Integer, nullable=True),
            sa.Column("thumb_url", sa.Text, nullable=True),
            sa.Column("source_url", sa.Text, nullable=True),
            sa.Column("duration_ms", sa.Integer, nullable=True),
            sa.Column(
                "ingested_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint(
                "account_id", "fan_id", "message_id", "media_id",
                name="pk_message_media",
            ),
            sa.ForeignKeyConstraint(
                ["account_id", "fan_id", "message_id"],
                ["messages.account_id", "messages.fan_id", "messages.message_id"],
                name="fk_message_media_account_id_messages",
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_message_media_media", "message_media", ["account_id", "media_id"],
        )

    if "fan_lease" not in existing:
        op.create_table(
            "fan_lease",
            sa.Column("account_id", sa.String, nullable=False),
            sa.Column("fan_id", sa.BigInteger, nullable=False),
            sa.Column("automation_kind", sa.String, nullable=False),
            sa.Column("leased_until", sa.DateTime, nullable=False),
            sa.Column(
                "acquired_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("account_id", "fan_id", name="pk_fan_lease"),
        )
        op.create_index(
            "ix_fan_lease_expiry", "fan_lease", ["leased_until"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if "fan_lease" in existing:
        op.drop_table("fan_lease")
    if "message_media" in existing:
        op.drop_table("message_media")
