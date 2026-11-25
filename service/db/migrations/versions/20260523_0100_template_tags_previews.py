from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018_template_tags_previews"
down_revision: str | Sequence[str] | None = "0017_phase_g_messages_dir_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saved_replies",
        sa.Column(
            "tagged_users_json", sa.Text,
            nullable=False, server_default="[]",
        ),
    )
    op.add_column(
        "saved_replies",
        sa.Column(
            "previews_json", sa.Text,
            nullable=False, server_default="[]",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("saved_replies") as batch:
        batch.drop_column("previews_json")
        batch.drop_column("tagged_users_json")
