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
