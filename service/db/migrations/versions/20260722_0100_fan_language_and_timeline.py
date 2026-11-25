from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0051_fan_language_and_timeline"
down_revision: str | Sequence[str] | None = "0050_resolution_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Hand-written add_column, never --autogenerate: render_as_batch would rewrite the whole 1.5 GB fans table.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cfg_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "language" not in cfg_cols:
        op.add_column("account_ai_config", sa.Column("language", sa.String, nullable=True))

    fan_cols = {c["name"] for c in inspector.get_columns("fans")}
    if "language" not in fan_cols:
        op.add_column("fans", sa.Column("language", sa.String, nullable=True))
    if "language_source" not in fan_cols:
        op.add_column("fans", sa.Column("language_source", sa.String, nullable=True))
    if "recent_events_timeline" not in fan_cols:
        op.add_column("fans", sa.Column("recent_events_timeline", sa.Text, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    fan_cols = {c["name"] for c in inspector.get_columns("fans")}
    for col in ("recent_events_timeline", "language_source", "language"):
        if col in fan_cols:
            op.drop_column("fans", col)

    cfg_cols = {c["name"] for c in inspector.get_columns("account_ai_config")}
    if "language" in cfg_cols:
        op.drop_column("account_ai_config", "language")
