"""user_settings — one Settings blob per agency (owner) and Settings tab

Backs `GET/PUT /admin/settings/{tab}` (service/settings_api.py, ADR-0007): the
six Blob tabs of Settings each keep one whole JSON object per agency. One row
per (user_id, tab); a PUT replaces `config_json` whole. Nothing reads these
values yet (ADR-0008).

`ON DELETE CASCADE` removes an agency's blobs with its `users` row.

Nothing seeds this table; an absent row reads as `{}`.

Revision ID: 0065_user_settings
Revises: 0064_user_llm_keys
Create Date: 2026-10-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065_user_settings"
down_revision: str | Sequence[str] | None = "0064_user_llm_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tab", sa.String(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tab"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
