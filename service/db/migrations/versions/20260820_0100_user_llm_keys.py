from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064_user_llm_keys"
down_revision: str | Sequence[str] | None = "0063_cotag_brain_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nothing seeds this: each owner pastes a key once; accounts fail closed until then, never on the house key.
    op.create_table(
        "user_llm_keys",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "provider"),
    )


def downgrade() -> None:
    op.drop_table("user_llm_keys")
