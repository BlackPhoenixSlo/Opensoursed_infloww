from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063_cotag_brain_settings"
down_revision: str | Sequence[str] | None = "0062_rename_of_ai_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("account_ai_config",
                  sa.Column("cotag_tag_videos", sa.Boolean(), nullable=True))
    op.add_column("account_ai_config",
                  sa.Column("cotag_username", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("account_ai_config", "cotag_username")
    op.drop_column("account_ai_config", "cotag_tag_videos")
