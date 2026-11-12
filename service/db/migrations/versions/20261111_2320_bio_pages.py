"""bio pages (ofl.ink ported): bio_profiles, bio_links, bio_custom_domains, bio_spare_domains, bio_daily

Five NEW tables, read by the public bio app (service/bio_pages on BIO_PORT); no existing row is touched.
`create_all()` brings them (and the partial unique index, declared on the model) to a booting box; this file
keeps the alembic chain linear. Each table and index is created only when the inspector lacks it.

Revision ID: 0115_bio_pages
Revises: 0114_tracking_click_labels
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0115_bio_pages"
down_revision: str | Sequence[str] | None = "0114_tracking_click_labels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("bio_daily", "bio_spare_domains", "bio_custom_domains", "bio_links", "bio_profiles")  # drop order


def _s(name: str) -> sa.Column:
    """A NOT NULL text column defaulting to ''."""
    return sa.Column(name, sa.String, nullable=False, server_default=sa.text("''"))


def _b(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean, nullable=False, server_default=sa.text("0"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = set(insp.get_table_names())
    if "bio_profiles" not in have:
        op.create_table(
            "bio_profiles",
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("owner_user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("username", sa.String, nullable=False),
            _s("display_name"), _s("bio"), _s("avatar"), _s("mode"), _s("v1_key"), _b("verified"),
            sa.Column("slot", sa.Integer, nullable=True),
            _ts("created_at"), _ts("updated_at"),
            sa.UniqueConstraint("username", name="uq_bio_profiles_username"),
        )
    if "bio_links" not in have:
        op.create_table(
            "bio_links",
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("profile_id", sa.String, sa.ForeignKey("bio_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("link_id", sa.String(12), nullable=False),
            _s("title"),
            sa.Column("destination", sa.Text, nullable=False, server_default=sa.text("''")),
            _s("default_tracking_code"), _s("mode"), _s("icon"), _s("background_image"), _s("v1_key"),
            sa.Column("geo", sa.Text, nullable=True),
            _b("is_adult"), _b("tracking"),
            sa.Column("sort_order", sa.Float, nullable=False, server_default=sa.text("0")),
            _b("bot_check"), _ts("created_at"), _ts("updated_at"),
            sa.UniqueConstraint("link_id", name="uq_bio_links_link_id"),
        )
    if "bio_custom_domains" not in have:
        op.create_table(
            "bio_custom_domains",
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("profile_id", sa.String, sa.ForeignKey("bio_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("domain", sa.String, nullable=False),
            sa.Column("status", sa.String, nullable=False),
            _s("token"),
            sa.Column("checked", sa.DateTime, nullable=True),
            sa.UniqueConstraint("profile_id", name="uq_bio_custom_domains_profile_id"),
        )
    if "bio_spare_domains" not in have:
        op.create_table(
            "bio_spare_domains",
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("domain", sa.String, nullable=False),
            sa.UniqueConstraint("domain", name="uq_bio_spare_domains_domain"),
        )
    if "bio_daily" not in have:
        op.create_table(
            "bio_daily",
            sa.Column("day", sa.String, primary_key=True),
            sa.Column("profile_id", sa.String, sa.ForeignKey("bio_profiles.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("link_id", sa.String, primary_key=True),
            sa.Column("country", sa.String, primary_key=True),
            sa.Column("in_app", sa.String, primary_key=True),
            sa.Column("code", sa.String, primary_key=True),
            sa.Column("views", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("clicks", sa.Integer, nullable=False, server_default=sa.text("0")),
        )
    for name, table, cols, kw in (
        ("ix_bio_links_profile_order", "bio_links", ["profile_id", "sort_order"], {}),
        ("ix_bio_custom_domains_live", "bio_custom_domains", ["domain"],
         {"unique": True, "sqlite_where": sa.text("status = 'live'"),
          "postgresql_where": sa.text("status = 'live'")}),
        ("ix_bio_daily_profile_day", "bio_daily", ["profile_id", "day"], {}),
    ):
        if name not in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(name, table, cols, **kw)


def downgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _TABLES:
        if table in have:
            op.drop_table(table)
