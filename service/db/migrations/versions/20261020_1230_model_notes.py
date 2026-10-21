"""model_notes — My Automations › Get to know fans' short "Model info" note

`account_ai_config.model_notes` (TEXT, NULL): a short free-text note about the
model, editable by anyone with access to the account, pinned into every chat
prompt by automations._persona.compose_persona. NULL until someone saves one.

The ORM model declares the same column, so `init_db()`'s ADD-COLUMN catch-up
brings it to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops the column.

Revision ID: 0092_model_notes
Revises: 0089_agency_notifications
Create Date: 2026-10-20
"""
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
