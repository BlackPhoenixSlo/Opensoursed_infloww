"""vault_account_settings.solo_sequences — Script Fill puts only solo media into Sequences

Per-Creator switch, ON by default (client rule). One nullable Boolean column, no default: NULL
reads as on (`vault_settings.DEFAULTS`), so every existing row and every account with no row keeps
the solo-only Fill. Boxes upgrade through db.engine's init_db additive catch-up (nullable = safe);
this file keeps the alembic chain linear. Inspector-guarded + idempotent, like 0128.

Revision ID: 0131_vault_solo_sequences
Revises: 0130_ai_decisions_offer_attempt
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0131_vault_solo_sequences"
down_revision: str | Sequence[str] | None = "0130_ai_decisions_offer_attempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "vault_account_settings"


def _cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    cols = _cols()
    if cols and "solo_sequences" not in cols:
        op.add_column(_TABLE, sa.Column("solo_sequences", sa.Boolean(), nullable=True))


def downgrade() -> None:
    if "solo_sequences" in _cols():
        with op.batch_alter_table(_TABLE) as b:
            b.drop_column("solo_sequences")
