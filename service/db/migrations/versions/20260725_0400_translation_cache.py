from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0055_translation_cache"
down_revision: str | Sequence[str] | None = "0054_persona_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "translation_cache" not in inspector.get_table_names():
        op.create_table(
            "translation_cache",
            sa.Column("text_hash", sa.String, primary_key=True),
            sa.Column("target", sa.String, nullable=False),
            sa.Column("src_lang", sa.String, nullable=False, server_default="und"),
            sa.Column("source_text", sa.Text, nullable=False),
            sa.Column("translated", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    existing = {i["name"] for i in sa.inspect(bind).get_indexes("translation_cache")}
    if "ix_translation_cache_created" not in existing:
        op.create_index("ix_translation_cache_created", "translation_cache", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "translation_cache" in inspector.get_table_names():
        op.drop_table("translation_cache")
