from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082_s4s_media_blocks"
down_revision: str | Sequence[str] | None = "0081_priority_mass"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEDIA_COLS = ("from_media_json", "to_media_json")


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "s4s_media" not in tables:
        op.create_table(
            "s4s_media",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("post_id", sa.Integer(), nullable=True),
            sa.Column("vault_media_id", sa.BigInteger(), nullable=False),
            sa.Column("media_type", sa.String(16), nullable=False),
            sa.Column("file_name", sa.String(80), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            _ts("created_at"),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                    name="fk_s4s_media_account_id_accounts"),
            sa.ForeignKeyConstraint(["post_id"], ["s4s_posts.id"], ondelete="SET NULL",
                                    name="fk_s4s_media_post_id_s4s_posts"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_s4s_media_account", "s4s_media", ["account_id"])
        op.create_index("ix_s4s_media_post", "s4s_media", ["post_id"])

    if "s4s_blocks" not in tables:
        op.create_table(
            "s4s_blocks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agency_user_id", sa.String(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("projection_json", sa.Text(), nullable=False),
            _ts("created_at"),
            sa.ForeignKeyConstraint(["agency_user_id"], ["users.id"], ondelete="CASCADE",
                                    name="fk_s4s_blocks_agency_user_id_users"),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                    name="fk_s4s_blocks_account_id_accounts"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agency_user_id", "account_id", name="uq_s4s_blocks_agency_account"),
        )

    live = {c["name"] for c in insp.get_columns("s4s_requests")}
    missing = [c for c in _MEDIA_COLS if c not in live]
    for col in missing:
    # Plain ALTERs, not batch: a rebuild of s4s_requests would have to carry its partial unique index.
        op.add_column("s4s_requests", sa.Column(col, sa.Text(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    live = {c["name"] for c in insp.get_columns("s4s_requests")}
    present = [c for c in _MEDIA_COLS if c in live]
    for col in present:
        op.drop_column("s4s_requests", col)
    tables = set(insp.get_table_names())
    if "s4s_blocks" in tables:
        op.drop_table("s4s_blocks")
    if "s4s_media" in tables:
        op.drop_index("ix_s4s_media_post", table_name="s4s_media")
        op.drop_index("ix_s4s_media_account", table_name="s4s_media")
        op.drop_table("s4s_media")
