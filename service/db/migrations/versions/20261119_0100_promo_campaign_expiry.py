from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0125_promo_campaign_expiry"
down_revision: str | Sequence[str] | None = "0124_vault_account_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "promo_campaigns"
_COLS = (("finish_days", sa.Integer()), ("expires_at", sa.DateTime()))


def _live() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    live = _live()
    for name, type_ in _COLS:
        if name not in live:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    live = _live()
    gone = [name for name, _ in _COLS if name in live]
    if gone:
        with op.batch_alter_table(_TABLE) as b:
            for name in gone:
                b.drop_column(name)
