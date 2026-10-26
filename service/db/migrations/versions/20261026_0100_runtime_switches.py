"""runtime_switches — owner overrides of the relay's env kill switches and caps

Settings → System sets them (service/runtime_switches.py, PUT
/admin/system/switches/{name}); each consumer reads DB override > env > default.

  runtime_switches.name        PK, the env var's name (W7_WEBHOOK_DISPATCH_DISABLED, ...)
  runtime_switches.value_json  JSON bool or integer
  runtime_switches.updated_by  the master's username
  runtime_switches.updated_at

The ORM model in db/models.py declares the same table, so `init_db()`'s
create_all brings it to a booting box; this revision keeps the alembic chain
canonical. Idempotent (inspector-guarded, house convention). Downgrade drops
the table: every switch goes back to env / default.

Revision ID: 0098_runtime_switches
Revises: 0096_of_earnings_daily
Create Date: 2026-10-26
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0098_runtime_switches"
down_revision: str | Sequence[str] | None = "0096_of_earnings_daily"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "runtime_switches"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_runtime_switches"),
    )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
