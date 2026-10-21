"""promo_list — Profile promotions' "Add fans to list" (promo_list_settings)

Backs service/link_metrics.py's promotion List: Infloww's account-level switch
and list on its Profile promotion page. While enabled, every promotion's
claimers go into the chosen OnlyFans list through OF's own add-to-list.

  promo_list_settings.account_id  PK, FK accounts.id ON DELETE CASCADE
  promo_list_settings.enabled     the switch
  promo_list_settings.list_id     OF's custom list id (a number, kept as text)
  promo_list_settings.list_name   its name when picked
  promo_list_settings.updated_at

The ORM model in db/models.py declares the same table, so `init_db()`'s
create_all brings it to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
the table; that loses only the setting (the fans already in the list stay on OF).

Revision ID: 0076_promo_list
Revises: 0075_clock_last_seen
Create Date: 2026-10-19
"""
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
