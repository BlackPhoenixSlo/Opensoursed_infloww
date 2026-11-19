"""Keep running guards — Create reservations, per-Creator Keep state, campaign guard columns

docs/spec/phase-01-promo-preempt.md (Schema), one revision for both slices:
  • promo_create_reservations (NEW): every promo create is a row before its POST (ADR-0040);
    partial unique uq_promo_create_open = one open row per Creator.
  • promo_keep_state (NEW): the claim memo and the Re-check slot (+ its owning job), one row per Creator.
  • promo_campaigns + recreates_left, keep_host_id, keep_warning, keep_warning_at, keep_ticked_at (nullable)
    and preempt (NOT NULL DEFAULT 1, read by Slice B only).
  • uq_promo_keep_one: one Kept campaign per Creator. A legacy Creator with several keeps the one ticked
    (else created) last; the rest are unticked with keep_warning 'kept_duplicate' (the boot notice tells
    the owners, promo_create_guard.duplicate_notices).
`create_all()` / `db.engine.init_db`'s additive catch-up bring the same to a booting box;
this file keeps the alembic chain linear. Inspector-guarded + idempotent, like 0125.

Revision ID: 0126_promo_preempt
Revises: 0125_promo_campaign_expiry
Create Date: 2026-11-19
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0126_promo_preempt"
down_revision: str | Sequence[str] | None = "0125_promo_campaign_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAMPAIGNS = "promo_campaigns"
_RESERVATIONS = "promo_create_reservations"
_STATE = "promo_keep_state"
_OPEN = "state IN ('pending','sending','unknown')"
_KEPT = "auto_reactivate = 1"
# Same statement as db.engine's boot catch-up (a box upgrades through init_db, not alembic).
_DEDUPE_KEPT = (
    "UPDATE promo_campaigns SET auto_reactivate = 0, keep_warning = 'kept_duplicate', "
    "keep_warning_at = CURRENT_TIMESTAMP WHERE auto_reactivate = 1 AND id <> ("
    "SELECT k.id FROM promo_campaigns k WHERE k.account_id = promo_campaigns.account_id "
    "AND k.auto_reactivate = 1 ORDER BY COALESCE(k.keep_ticked_at, k.created_at) DESC, k.id DESC LIMIT 1)")


def _cols() -> tuple[sa.Column, ...]:
    return (sa.Column("recreates_left", sa.Integer(), nullable=True),
            sa.Column("keep_host_id", sa.String(), nullable=True),
            sa.Column("keep_warning", sa.String(), nullable=True),
            sa.Column("keep_warning_at", sa.DateTime(), nullable=True),
            sa.Column("keep_ticked_at", sa.DateTime(), nullable=True),
            sa.Column("preempt", sa.Boolean(), nullable=False, server_default=sa.text("1")))


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    live = {c["name"] for c in insp.get_columns(_CAMPAIGNS)}
    for col in _cols():
        if col.name not in live:
            op.add_column(_CAMPAIGNS, col)
    if "uq_promo_keep_one" not in {i["name"] for i in insp.get_indexes(_CAMPAIGNS)}:
        op.execute(_DEDUPE_KEPT)
        op.create_index("uq_promo_keep_one", _CAMPAIGNS, ["account_id"], unique=True,
                        sqlite_where=sa.text(_KEPT), postgresql_where=sa.text("auto_reactivate"))
    if _RESERVATIONS not in tables:
        op.create_table(
            _RESERVATIONS,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("campaign_id", sa.Integer,
                      sa.ForeignKey("promo_campaigns.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String, nullable=False),
            sa.Column("state", sa.String, nullable=False),
            sa.Column("terms_json", sa.Text, nullable=False),
            sa.Column("pre_ids_json", sa.Text, nullable=True),
            sa.Column("replaced_of_promo_id", sa.BigInteger, nullable=True),
            sa.Column("claims_seen", sa.Integer, nullable=True),
            sa.Column("first_claims", sa.Integer, nullable=True),
            sa.Column("host_id", sa.String, nullable=True),
            sa.Column("of_promo_id", sa.BigInteger, nullable=True),
            sa.Column("listed_at", sa.DateTime, nullable=True),
            sa.Column("error_class", sa.String, nullable=True),
            sa.Column("retry_after_s", sa.Integer, nullable=True),
            sa.Column("not_before", sa.DateTime, nullable=True),
            sa.Column("reconcile_reads", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime, nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("sent_at", sa.DateTime, nullable=True),
            sa.Column("settled_at", sa.DateTime, nullable=True),
        )
    have = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_RESERVATIONS)}
    if "uq_promo_create_open" not in have:
        op.create_index("uq_promo_create_open", _RESERVATIONS, ["account_id"], unique=True,
                        sqlite_where=sa.text(_OPEN), postgresql_where=sa.text(_OPEN))
    if "ix_promo_create_account_time" not in have:
        op.create_index("ix_promo_create_account_time", _RESERVATIONS, ["account_id", "created_at"])
    if _STATE not in tables:
        op.create_table(
            _STATE,
            sa.Column("account_id", sa.String, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("kept_of_promo_id", sa.BigInteger, nullable=True),
            sa.Column("first_claims", sa.Integer, nullable=True),
            sa.Column("last_claims", sa.Integer, nullable=True),
            sa.Column("seen_below", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("finished_at", sa.Text, nullable=True),
            sa.Column("read_at", sa.DateTime, nullable=True),
            sa.Column("recheck_at", sa.DateTime, nullable=True),
            sa.Column("recheck_job_id", sa.Integer, nullable=True),
            sa.Column("skew_s", sa.Integer, nullable=True),
            sa.Column("wait_reason", sa.String, nullable=True),
        )
    elif "recheck_job_id" not in {c["name"] for c in insp.get_columns(_STATE)}:
        op.add_column(_STATE, sa.Column("recheck_job_id", sa.Integer, nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for t in (_STATE, _RESERVATIONS):
        if t in tables:
            op.drop_table(t)
    if "uq_promo_keep_one" in {i["name"] for i in insp.get_indexes(_CAMPAIGNS)}:
        op.drop_index("uq_promo_keep_one", table_name=_CAMPAIGNS)
    live = {c["name"] for c in insp.get_columns(_CAMPAIGNS)}
    gone = [c.name for c in _cols() if c.name in live]
    if gone:
        with op.batch_alter_table(_CAMPAIGNS) as b:
            for name in gone:
                b.drop_column(name)
