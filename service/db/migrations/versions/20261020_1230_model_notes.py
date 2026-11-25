from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0092_model_notes"
down_revision: str | Sequence[str] | None = "0089_agency_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("account_ai_config")}


def upgrade() -> None:
    if "model_notes" not in _columns():
        op.add_column("account_ai_config", sa.Column("model_notes", sa.Text, nullable=True))


def downgrade() -> None:
    if "model_notes" in _columns():
        with op.batch_alter_table("account_ai_config") as batch:
            batch.drop_column("model_notes")
