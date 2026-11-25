from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0054_persona_claims"
down_revision: str | Sequence[str] | None = "0053_persona_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("fans")}
    if "persona_claims_json" not in cols:
        op.add_column("fans", sa.Column("persona_claims_json", sa.Text, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("fans")}
    if "persona_claims_json" in cols:
        op.drop_column("fans", "persona_claims_json")
