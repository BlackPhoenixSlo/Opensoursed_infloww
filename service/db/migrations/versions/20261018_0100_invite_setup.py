"""invite_setup — an invite carries the Employee's role, Creators and group

`chatters_invites.setup_json` (TEXT, NULL): the Employee setup the owner chose
on "+ Add employee" (employees.EmployeeSetup as JSON), applied when the invite
is accepted. NULL for invites minted before this and for bare invites.

The ORM model declares the same column, so `init_db()`'s ADD-COLUMN catch-up
brings it to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the column.

Revision ID: 0071_invite_setup
Revises: 0070_employee_groups
Create Date: 2026-10-18
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071_invite_setup"
down_revision: str | Sequence[str] | None = "0070_employee_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chatters_invites")}


def upgrade() -> None:
    if "setup_json" not in _columns():
        with op.batch_alter_table("chatters_invites") as batch:
            batch.add_column(sa.Column("setup_json", sa.Text(), nullable=True))


def downgrade() -> None:
    if "setup_json" in _columns():
        with op.batch_alter_table("chatters_invites") as batch:
            batch.drop_column("setup_json")
