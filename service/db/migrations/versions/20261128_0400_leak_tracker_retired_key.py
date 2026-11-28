from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0144_leak_tracker_retired_key"
down_revision: str | Sequence[str] | None = "0143_leak_tracker_tenant_via_instance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "leak_tracker_tenant"


def upgrade() -> None:
    live = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name, typ in (("retired_tenant_id", sa.String()), ("retired_key", sa.Text())):
        if name not in live:
            op.add_column(_TABLE, sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "retired_key")
    op.drop_column(_TABLE, "retired_tenant_id")
