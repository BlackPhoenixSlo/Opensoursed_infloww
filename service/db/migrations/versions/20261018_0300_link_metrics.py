"""link_metrics — per-link local state and claimers for Growth's link figures

Backs service/link_metrics.py (Free trial links' and Profile promotions'
Earnings, Fans who spent, Spend/Claim and AEPS; the Edit dialog's Promo cost,
Source and Tag on Free trial links and Tracking links):

  link_meta      — one row per (account, kind, OF id): the operator's Promo
                   cost, Source and Tags (never written to OnlyFans), and the
                   claimers cache state (claim count at the last walk, walk and
                   check times, our promo campaign id across re-arms).
  link_claimers  — the fans OnlyFans lists under a trial link or promotion,
                   with subscribeAt as first seen (never moved later) and OF's
                   lifetime spend sums.

Both foreign keys to `accounts` are ON DELETE CASCADE. The ORM models in
db/models.py declare the same tables, so `init_db()`'s create_all brings them
to a booting box; this revision keeps the alembic chain canonical. Idempotent
(inspector-guarded, house convention). Downgrade drops both tables; that loses
only cached claimers (re-walked from OnlyFans) and the operator's cost, source
and tags.

Revision ID: 0073_link_metrics
Revises: 0072_saved_reply_tags_notes
Create Date: 2026-10-18
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073_link_metrics"
down_revision: str | Sequence[str] | None = "0072_saved_reply_tags_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _account_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                   name=f"fk_{table}_account_id_accounts")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "link_meta" not in tables:
        op.create_table(
            "link_meta",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(length=8), nullable=False),
            sa.Column("of_id", sa.BigInteger(), nullable=False),
            sa.Column("promo_cost_cents", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(length=100), nullable=True),
            sa.Column("tags_json", sa.Text(), nullable=True),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("claim_count", sa.Integer(), nullable=True),
            sa.Column("walked_at", sa.DateTime(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                      nullable=False),
            _account_fk("link_meta"),
            sa.PrimaryKeyConstraint("id", name="pk_link_meta"),
            sa.UniqueConstraint("account_id", "kind", "of_id", name="uq_link_meta_link"),
        )

    if "link_claimers" not in tables:
        op.create_table(
            "link_claimers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(length=8), nullable=False),
            sa.Column("of_id", sa.BigInteger(), nullable=False),
            sa.Column("fan_id", sa.BigInteger(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("username", sa.String(), nullable=True),
            sa.Column("subscribe_at", sa.DateTime(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("lifetime_total_cents", sa.Integer(), nullable=True),
            sa.Column("lifetime_subs_cents", sa.Integer(), nullable=True),
            sa.Column("lifetime_posts_cents", sa.Integer(), nullable=True),
            sa.Column("lifetime_messages_cents", sa.Integer(), nullable=True),
            sa.Column("lifetime_streams_cents", sa.Integer(), nullable=True),
            sa.Column("lifetime_tips_cents", sa.Integer(), nullable=True),
            _account_fk("link_claimers"),
            sa.PrimaryKeyConstraint("id", name="pk_link_claimers"),
            sa.UniqueConstraint("account_id", "kind", "of_id", "fan_id", name="uq_link_claimers_fan"),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for t in ("link_claimers", "link_meta"):
        if t in tables:
            op.drop_table(t)
