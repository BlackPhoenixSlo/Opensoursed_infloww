from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0022_users_and_user_accounts"
down_revision: str | Sequence[str] | None = (
    "0021_mass_broadcast_cache",
    "0019_vault_response_cache",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("username", sa.String, nullable=False),
            # Plaintext by owner decision; do NOT widen DB-file exposure without switching to a hash.
            sa.Column("password", sa.String, nullable=False),
            sa.Column(
                "created_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "last_seen_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("username", name="uq_users_username"),
        )

    if "user_accounts" not in existing:
        op.create_table(
            "user_accounts",
            sa.Column(
                "user_id", sa.String,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "account_id", sa.String,
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "created_at", sa.DateTime,
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade() -> None:
    op.drop_table("user_accounts")
    op.drop_table("users")
