"""link_shares — Infloww's Share links (public read-only link reports, 7 days)

Backs service/link_share_api.py: one row per share link of some of a
Creator's free trial links or tracking links.

  link_shares.id                 PK, the public (non-secret) half of the URL
  link_shares.secret             secrets.token_urlsafe, the URL's secret half
  link_shares.account_id         FK accounts.id ON DELETE CASCADE, indexed
  link_shares.kind               trial | campaign
  link_shares.name               the owner's name for it
  link_shares.of_ids_json        the links picked (JSON list of OF ids)
  link_shares.include_earnings   Infloww's "Include earnings"
  link_shares.rows_json          the report as the public sees it
  link_shares.snapshot_at        when rows_json was last built (null: not yet)
  link_shares.created_by         the owner's users.id
  link_shares.created_at / expires_at (+7 days) / revoked_at

The ORM model in db/models.py declares the same table, so `init_db()`'s
create_all brings it to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
the table; that ends every share link (their reports are rebuilt from the
owner's reads, nothing else is lost).

Revision ID: 0079_link_shares
Revises: 0078_shift_scope_versions
Create Date: 2026-10-20
"""
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


def downgrade() -> None:
    if "link_shares" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_index("ix_link_shares_account_id", table_name="link_shares")
        op.drop_table("link_shares")
