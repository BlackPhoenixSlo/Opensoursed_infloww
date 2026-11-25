from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019_vault_response_cache"
down_revision: str | Sequence[str] | None = "0018_template_tags_previews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "vault_response_cache" in inspector.get_table_names():
        return
    op.create_table(
        "vault_response_cache",
        sa.Column(
            "account_id", sa.String,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("query_key", sa.String, primary_key=True),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime,
            nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("vault_response_cache")
