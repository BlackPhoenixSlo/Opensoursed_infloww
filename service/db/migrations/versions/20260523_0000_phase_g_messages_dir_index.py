from __future__ import annotations

from typing import Sequence

from alembic import op


revision: str = "0017_phase_g_messages_dir_index"
down_revision: str | Sequence[str] | None = "0016_phase_f_attr_view_include_pending"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_dir_created",
        "messages",
        ["account_id", "direction", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_dir_created", table_name="messages")
