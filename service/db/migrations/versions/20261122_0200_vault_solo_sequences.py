from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0131_vault_solo_sequences"
down_revision: str | Sequence[str] | None = "0130_ai_decisions_offer_attempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# nullable, no default: NULL reads as on (vault_settings.DEFAULTS), keeping solo-only Fill for existing rows
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
