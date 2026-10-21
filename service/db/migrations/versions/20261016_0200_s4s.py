"""s4s — S4S profiles, S4S posts, S4S requests and S4S slots

Backs the `/admin/s4s` router (service/s4s_api.py,
docs/spec/phase-03-share-for-share.md, Schema):

  s4s_profiles   — one Creator's S4S Setting: opt-in, Discovery Page
                   Visibility, Daily limit (1..3) and the display fields.
  s4s_posts      — a Creator's S4S posts (captions ≤ 5000 characters); the
                   partial unique index keeps at most one Primary post.
  s4s_requests   — S4S requests between two Creators, with caption and
                   projection snapshots; the partial unique index keeps at
                   most one open (pending or skipped) request per direction.
  s4s_schedule   — S4S slots, one per side of an accepted request.

Every foreign key to `accounts` is ON DELETE CASCADE. The ORM models in
db/models.py declare the same tables and indexes, so `init_db()`'s create_all
brings them to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention).

Downgrade drops the four tables in reverse order; that is the documented
recovery path, and it loses only S4S data.

Revision ID: 0068_s4s
Revises: 0067_shifts
Create Date: 2026-10-16
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068_s4s"
down_revision: str | Sequence[str] | None = "0067_shifts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRIMARY = "is_primary"
_OPEN = "status IN ('pending','skipped')"


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False)


def _account_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["accounts.id"], ondelete="CASCADE",
                                   name=f"fk_{table}_{column}_accounts")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "s4s_profiles" not in tables:
        op.create_table(
            "s4s_profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("opted_in", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.Column("discovery_visible", sa.Boolean(), server_default=sa.text("1"), nullable=False),
            sa.Column("daily_limit", sa.Integer(), server_default=sa.text("1"), nullable=False),
            sa.Column("display_name", sa.String(length=64), nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("avatar_url", sa.Text(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.CheckConstraint("daily_limit BETWEEN 1 AND 3", name="ck_s4s_profiles_daily_limit"),
            _account_fk("s4s_profiles", "account_id"),
            sa.PrimaryKeyConstraint("id", name="pk_s4s_profiles"),
            sa.UniqueConstraint("account_id", name="uq_s4s_profiles_account_id"),
        )

    if "s4s_posts" not in tables:
        op.create_table(
            "s4s_posts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("caption", sa.Text(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            _ts("created_at"),
            _ts("updated_at"),
            sa.CheckConstraint("length(caption) <= 5000", name="ck_s4s_posts_caption_length"),
            _account_fk("s4s_posts", "account_id"),
            sa.PrimaryKeyConstraint("id", name="pk_s4s_posts"),
        )
        op.create_index(
            "uq_s4s_posts_primary", "s4s_posts", ["account_id"], unique=True,
            sqlite_where=sa.text(_PRIMARY), postgresql_where=sa.text(_PRIMARY),
        )

    if "s4s_requests" not in tables:
        op.create_table(
            "s4s_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("from_account_id", sa.String(), nullable=False),
            sa.Column("to_account_id", sa.String(), nullable=False),
            sa.Column("slot_at", sa.DateTime(), nullable=False),
            sa.Column("from_caption", sa.Text(), nullable=False),
            sa.Column("to_caption", sa.Text(), nullable=False),
            sa.Column("from_projection_json", sa.Text(), nullable=False),
            sa.Column("to_projection_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
            sa.Column("cancel_reason", sa.Text(), nullable=True),
            _ts("created_at"),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("from_account_id <> to_account_id", name="ck_s4s_requests_distinct_parties"),
            sa.CheckConstraint(
                "status IN ('pending','accepted','declined','skipped','cancelled','expired')",
                name="ck_s4s_requests_status",
            ),
            _account_fk("s4s_requests", "from_account_id"),
            _account_fk("s4s_requests", "to_account_id"),
            sa.PrimaryKeyConstraint("id", name="pk_s4s_requests"),
        )
        op.create_index(
            "uq_s4s_requests_open_pair", "s4s_requests", ["from_account_id", "to_account_id"], unique=True,
            sqlite_where=sa.text(_OPEN), postgresql_where=sa.text(_OPEN),
        )
        op.create_index("ix_s4s_requests_to_status", "s4s_requests", ["to_account_id", "status"])
        op.create_index("ix_s4s_requests_from_status", "s4s_requests", ["from_account_id", "status"])

    if "s4s_schedule" not in tables:
        op.create_table(
            "s4s_schedule",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("request_id", sa.Integer(), nullable=False),
            sa.Column("poster_account_id", sa.String(), nullable=False),
            sa.Column("partner_account_id", sa.String(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("slot_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.Text(), server_default=sa.text("'scheduled'"), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("post_id", sa.Integer(), nullable=True),
            sa.Column("of_post_id", sa.BigInteger(), nullable=True),
            sa.Column("posted_at", sa.DateTime(), nullable=True),
            sa.Column("remove_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "status IN ('scheduled','posting','posted','canceled','failed')", name="ck_s4s_schedule_status",
            ),
            sa.ForeignKeyConstraint(["request_id"], ["s4s_requests.id"], ondelete="CASCADE",
                                    name="fk_s4s_schedule_request_id_s4s_requests"),
            _account_fk("s4s_schedule", "poster_account_id"),
            _account_fk("s4s_schedule", "partner_account_id"),
            sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL",
                                    name="fk_s4s_schedule_post_id_posts"),
            sa.PrimaryKeyConstraint("id", name="pk_s4s_schedule"),
        )
        op.create_index("ix_s4s_schedule_poster_slot", "s4s_schedule", ["poster_account_id", "slot_at"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "s4s_schedule" in tables:
        op.drop_index("ix_s4s_schedule_poster_slot", table_name="s4s_schedule")
        op.drop_table("s4s_schedule")
    if "s4s_requests" in tables:
        op.drop_index("ix_s4s_requests_from_status", table_name="s4s_requests")
        op.drop_index("ix_s4s_requests_to_status", table_name="s4s_requests")
        op.drop_index("uq_s4s_requests_open_pair", table_name="s4s_requests")
        op.drop_table("s4s_requests")
    if "s4s_posts" in tables:
        op.drop_index("uq_s4s_posts_primary", table_name="s4s_posts")
        op.drop_table("s4s_posts")
    if "s4s_profiles" in tables:
        op.drop_table("s4s_profiles")
