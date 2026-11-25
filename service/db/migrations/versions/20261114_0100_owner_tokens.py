from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0118_owner_tokens"
down_revision: str | Sequence[str] | None = "0117_full_ai_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _INDEX = "owner_tokens", "ix_owner_tokens_user_id"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("hint", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("last_used_at", sa.DateTime, nullable=True),
            sa.Column("revoked_at", sa.DateTime, nullable=True),
        )
    if _INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["user_id"])
    if "via" not in {c["name"] for c in insp.get_columns("actions")}:
        op.add_column("actions", sa.Column("via", sa.String, nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "via" in {c["name"] for c in insp.get_columns("actions")}:
        op.drop_column("actions", "via")
    if _TABLE in insp.get_table_names():
        op.drop_table(_TABLE)
