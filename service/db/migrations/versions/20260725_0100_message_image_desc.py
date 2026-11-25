from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0052_message_image_desc"
down_revision: str | Sequence[str] | None = "0051_fan_language_and_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# hand-written add_column, never --autogenerate: render_as_batch would rewrite the whole messages table
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    msg_cols = {c["name"] for c in inspector.get_columns("messages")}
    if "image_desc" not in msg_cols:
        op.add_column("messages", sa.Column("image_desc", sa.Text, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    msg_cols = {c["name"] for c in inspector.get_columns("messages")}
    if "image_desc" in msg_cols:
        op.drop_column("messages", "image_desc")
