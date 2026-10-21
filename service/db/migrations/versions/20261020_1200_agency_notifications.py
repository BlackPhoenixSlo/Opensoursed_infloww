"""agency_notifications — the Agency owner's notification centre

  agency_notifications — one notification for one Agency (users.id): a role
                         change, a deactivated employee, an unsent message, a
                         missed clock-in or a Creator's dead session
                         (service/notifications_api.py). Unread while
                         `read_at` is NULL; `dedupe_key` is unique per Agency.
                         Indexed by (Agency, created_at) for the feed and by
                         created_at for the sweep's 90-day retention DELETE.

The ORM model declares the same table and indexes, so `init_db()`'s
create_all brings it to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
the table, losing only notifications.

Revision ID: 0089_agency_notifications
Revises: 0088_fan_salary
Create Date: 2026-10-20
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089_agency_notifications"
down_revision: str | Sequence[str] | None = "0088_fan_salary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agency_notifications"
_INDEXES = {
    "ix_agency_notifications_agency_created": ["agency_user_id", "created_at"],
    "ix_agency_notifications_created": ["created_at"],
}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in set(insp.get_table_names()):
        _create_table()
    have = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    for name, cols in _INDEXES.items():
        if name not in have:
            op.create_index(name, _TABLE, cols)


def _create_table() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agency_user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_agency_notifications_agency_user_id_users"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL",
                                name="fk_agency_notifications_employee_id_employees"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_user_id", "dedupe_key", name="uq_agency_notifications_dedupe"),
    )


def downgrade() -> None:
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    have = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    for name in _INDEXES:
        if name in have:
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
