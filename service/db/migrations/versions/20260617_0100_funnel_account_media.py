from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0035_funnel_account_media"
down_revision: str | Sequence[str] | None = "0034_ppv_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Old global media columns on mass_message_funnels stay in place as the runtime fallback for pairs not yet seeded here.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "funnel_account_media" not in inspector.get_table_names():
        op.create_table(
            "funnel_account_media",
            sa.Column(
                "funnel_id",
                sa.Integer,
                sa.ForeignKey("mass_message_funnels.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "account_id",
                sa.String,
                sa.ForeignKey("accounts.id"),
                primary_key=True,
            ),
            sa.Column("opening_media_ids", sa.Text, nullable=False, server_default="[]"),
            sa.Column("steps_media_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "funnel_account_media" in inspector.get_table_names():
        op.drop_table("funnel_account_media")
