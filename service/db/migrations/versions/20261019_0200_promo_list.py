from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076_promo_list"
down_revision: str | Sequence[str] | None = "0075_clock_last_seen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "promo_list_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "promo_list_settings",
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("list_id", sa.String(length=32), nullable=True),
        sa.Column("list_name", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                name="fk_promo_list_settings_account_id_accounts"),
        sa.PrimaryKeyConstraint("account_id", name="pk_promo_list_settings"),
    )


def downgrade() -> None:
    if "promo_list_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("promo_list_settings")
