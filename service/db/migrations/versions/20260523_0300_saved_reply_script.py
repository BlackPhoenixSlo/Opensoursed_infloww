from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0020_saved_reply_script"
down_revision: str | Sequence[str] | None = "0019_saved_reply_gif"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saved_replies",
        sa.Column("script_id", sa.String, nullable=True),
    )
    op.add_column(
        "saved_replies",
        sa.Column("script_step", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("saved_replies") as batch:
        batch.drop_column("script_step")
        batch.drop_column("script_id")
