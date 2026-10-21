"""priority_mass — Priority mass message runs and their frozen recipients

Backs `automations/priority_mass` and `priority_mass_api` (Smart Messages >
Priority mass message, roadmap W7 7.3):

  priority_mass_runs        — one message (text, vault media ids, previews,
                              price) to a frozen audience of one Creator, and
                              its status: resolving → running → done, or
                              cancelled / error.
  priority_mass_recipients  — PK(run_id, fan_id): each fan's status (pending →
                              claimed → sent / skipped / failed / unknown), why,
                              and OF's message id.

The ORM models in db/models.py declare the same tables, so `init_db()`'s
create_all brings them to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
both and loses only the Priority mass history; the messages sent stay in
`messages`.

Revision ID: 0081_priority_mass
Revises: 0080_smart_list_sync
Create Date: 2026-10-20
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081_priority_mass"
down_revision: str | Sequence[str] | None = "0080_smart_list_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "priority_mass_runs" not in tables:
        op.create_table(
            "priority_mass_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("created_by_employee_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("media_json", sa.Text(), nullable=False),
            sa.Column("previews_json", sa.Text(), nullable=False),
            sa.Column("price_cents", sa.Integer(), nullable=False),
            sa.Column("locked_text", sa.Boolean(), nullable=False),
            sa.Column("audience_json", sa.Text(), nullable=False),
            sa.Column("resolved_count", sa.Integer(), nullable=True),
            sa.Column("excluded_count", sa.Integer(), nullable=True),
            sa.Column("capped_count", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=_NOW, nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                    name="fk_priority_mass_runs_account_id_accounts"),
            sa.ForeignKeyConstraint(["created_by_employee_id"], ["employees.id"], ondelete="SET NULL",
                                    name="fk_priority_mass_runs_created_by_employee_id_employees"),
            sa.PrimaryKeyConstraint("id", name="pk_priority_mass_runs"),
        )
        op.create_index("ix_priority_mass_runs_account", "priority_mass_runs",
                        ["account_id", "created_at"])
    if "priority_mass_recipients" not in tables:
        op.create_table(
            "priority_mass_recipients",
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("fan_id", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("message_id", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=_NOW, nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["priority_mass_runs.id"], ondelete="CASCADE",
                                    name="fk_priority_mass_recipients_run_id_priority_mass_runs"),
            sa.PrimaryKeyConstraint("run_id", "fan_id", name="pk_priority_mass_recipients"),
        )
        op.create_index("ix_priority_mass_recipients_status", "priority_mass_recipients",
                        ["run_id", "status"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "priority_mass_recipients" in tables:
        op.drop_index("ix_priority_mass_recipients_status", table_name="priority_mass_recipients")
        op.drop_table("priority_mass_recipients")
    if "priority_mass_runs" in tables:
        op.drop_index("ix_priority_mass_runs_account", table_name="priority_mass_runs")
        op.drop_table("priority_mass_runs")
