from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0123_vault_folder_prices"
down_revision: str | Sequence[str] | None = "0122_bio_profile_background"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "vault_folder_prices"


def upgrade() -> None:
    if _TABLE not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("folder_ref", sa.String(64), primary_key=True),
            sa.Column("price_cents", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
