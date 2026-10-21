"""shifts — Shifts, Shift assignments and Clock events, each scoped to its Agency

Backs the `/admin/shifts` router (service/shifts_api.py,
docs/spec/phase-02-shifts-time-tracking.md):

  shifts             — one planned interval per row: first occurrence in UTC,
                       its IANA `tz`, an optional weekly repeat, and a soft
                       `status` ('scheduled' | 'cancelled').
  shift_assignments  — one row per (Employee, Creator) pair of a Shift.
  clock_events       — one clock-in and its clock-out for one Employee on one
                       Creator; the partial unique index keeps at most one
                       open event (out_utc IS NULL) per Employee.

The ORM models in db/models.py declare the same tables and indexes, so
`init_db()`'s create_all brings them to a booting box; this revision keeps the
alembic chain canonical. Idempotent (inspector-guarded, house convention).

Downgrade drops the three tables in reverse order and loses only shift and
clock data; nothing else reads it.

Revision ID: 0067_shifts
Revises: 0066_split_inbox
Create Date: 2026-10-16
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067_shifts"
down_revision: str | Sequence[str] | None = "0066_split_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN = "out_utc IS NULL"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "shifts" not in tables:
        op.create_table(
            "shifts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agency_user_id", sa.String(), nullable=False),
            sa.Column("start_utc", sa.DateTime(), nullable=False),
            sa.Column("end_utc", sa.DateTime(), nullable=False),
            sa.Column("tz", sa.Text(), nullable=False),
            sa.Column("repeat_days", sa.Text(), nullable=True),
            sa.Column("repeat_until", sa.Date(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("status IN ('scheduled','cancelled')", name="ck_shifts_status"),
            sa.ForeignKeyConstraint(["agency_user_id"], ["users.id"], ondelete="CASCADE",
                                    name="fk_shifts_agency_user_id_users"),
            sa.PrimaryKeyConstraint("id", name="pk_shifts"),
        )
        op.create_index("ix_shifts_agency_start", "shifts", ["agency_user_id", "start_utc"])

    if "shift_assignments" not in tables:
        op.create_table(
            "shift_assignments",
            sa.Column("shift_id", sa.Integer(), nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="CASCADE",
                                    name="fk_shift_assignments_shift_id_shifts"),
            sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE",
                                    name="fk_shift_assignments_employee_id_employees"),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE",
                                    name="fk_shift_assignments_account_id_accounts"),
            sa.PrimaryKeyConstraint("shift_id", "employee_id", "account_id", name="pk_shift_assignments"),
        )
        op.create_index("ix_shift_assignments_employee", "shift_assignments", ["employee_id"])
        op.create_index("ix_shift_assignments_account", "shift_assignments", ["account_id"])

    if "clock_events" not in tables:
        op.create_table(
            "clock_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agency_user_id", sa.String(), nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=True),
            sa.Column("account_id", sa.String(), nullable=True),
            sa.Column("shift_id", sa.Integer(), nullable=True),
            sa.Column("in_utc", sa.DateTime(), nullable=False),
            sa.Column("out_utc", sa.DateTime(), nullable=True),
            sa.Column("close_reason", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "close_reason IS NULL OR close_reason IN ('manual','auto','owner_edit')",
                name="ck_clock_events_close_reason",
            ),
            sa.ForeignKeyConstraint(["agency_user_id"], ["users.id"], ondelete="CASCADE",
                                    name="fk_clock_events_agency_user_id_users"),
            sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL",
                                    name="fk_clock_events_employee_id_employees"),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL",
                                    name="fk_clock_events_account_id_accounts"),
            sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="SET NULL",
                                    name="fk_clock_events_shift_id_shifts"),
            sa.PrimaryKeyConstraint("id", name="pk_clock_events"),
        )
        op.create_index(
            "uq_clock_events_open_employee", "clock_events", ["employee_id"], unique=True,
            sqlite_where=sa.text(_OPEN), postgresql_where=sa.text(_OPEN),
        )
        op.create_index("ix_clock_events_agency_in", "clock_events", ["agency_user_id", "in_utc"])
        op.create_index("ix_clock_events_account_in", "clock_events", ["account_id", "in_utc"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "clock_events" in tables:
        op.drop_index("ix_clock_events_account_in", table_name="clock_events")
        op.drop_index("ix_clock_events_agency_in", table_name="clock_events")
        op.drop_index("uq_clock_events_open_employee", table_name="clock_events")
        op.drop_table("clock_events")
    if "shift_assignments" in tables:
        op.drop_index("ix_shift_assignments_account", table_name="shift_assignments")
        op.drop_index("ix_shift_assignments_employee", table_name="shift_assignments")
        op.drop_table("shift_assignments")
    if "shifts" in tables:
        op.drop_index("ix_shifts_agency_start", table_name="shifts")
        op.drop_table("shifts")
