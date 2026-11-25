from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0053_persona_facts"
down_revision: str | Sequence[str] | None = "0052_message_image_desc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "persona_facts_json" not in cols:
        op.add_column("account_ai_config",
                      sa.Column("persona_facts_json", sa.Text, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "persona_facts_json" in cols:
        op.drop_column("account_ai_config", "persona_facts_json")
