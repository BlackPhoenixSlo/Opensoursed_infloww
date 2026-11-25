from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079_link_shares"
down_revision: str | Sequence[str] | None = "0078_shift_scope_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "link_shares" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "link_shares",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("of_ids_json", sa.Text(), nullable=False),
        sa.Column("include_earnings", sa.Boolean(), nullable=False),
        sa.Column("rows_json", sa.Text(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                name="fk_link_shares_account_id_accounts"),
        sa.PrimaryKeyConstraint("id", name="pk_link_shares"),
    )
    op.create_index("ix_link_shares_account_id", "link_shares", ["account_id"])


# Downgrade ends every share link; reports are rebuilt from owner reads, nothing else is lost.
def downgrade() -> None:
    if "link_shares" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_index("ix_link_shares_account_id", table_name="link_shares")
        op.drop_table("link_shares")
