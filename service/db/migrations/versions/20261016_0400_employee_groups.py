"""employee_groups — the Organization Chart's Employee groups, and each Employee's group

Backs the `/admin/employee-groups` router (service/employee_groups_api.py,
docs/spec/phase-05-remaining-parity-gaps.md, item 4, Schema "Migration A"):

  employee_groups    — one group of one Agency (`agency_user_id`), under the
                       Agency root (`parent_id` NULL) or under another of the
                       Agency's groups; `name` 1–64 characters.
                       UNIQUE(agency_user_id, parent_id, name); INDEX(agency_user_id).
  employees.group_id — the Employee's group. NULL = no group. Application-level
                       FK, like `chatter_id` (SQLite ALTER cannot add one).

The ORM models in db/models.py declare the same table, constraint, index and
column, so `init_db()`'s create_all and its ADD-COLUMN catch-up bring them to
a booting box; this revision keeps the alembic chain canonical. Idempotent
(inspector-guarded, house convention).

Downgrade drops both and loses only the group tree and who sits in which
group; nothing else reads them.

Revision ID: 0070_employee_groups
Revises: 0069_attr_view_sales_records
Create Date: 2026-10-16
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070_employee_groups"
down_revision: str | Sequence[str] | None = "0069_attr_view_sales_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "employee_groups" not in inspector.get_table_names():
        op.create_table(
            "employee_groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agency_user_id", sa.String(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["agency_user_id"], ["users.id"], ondelete="CASCADE",
                                    name="fk_employee_groups_agency_user_id_users"),
            sa.ForeignKeyConstraint(["parent_id"], ["employee_groups.id"],
                                    name="fk_employee_groups_parent_id_employee_groups"),
            sa.PrimaryKeyConstraint("id", name="pk_employee_groups"),
            sa.UniqueConstraint("agency_user_id", "parent_id", "name", name="uq_employee_groups_agency_user_id"),
        )
        op.create_index("ix_employee_groups_agency", "employee_groups", ["agency_user_id"])
    if "group_id" not in {c["name"] for c in inspector.get_columns("employees")}:
        op.add_column("employees", sa.Column("group_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "group_id" in {c["name"] for c in inspector.get_columns("employees")}:
        op.drop_column("employees", "group_id")
    if "employee_groups" in inspector.get_table_names():
        op.drop_index("ix_employee_groups_agency", table_name="employee_groups")
        op.drop_table("employee_groups")
