from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0086_auth_sessions_2fa"
down_revision: str | Sequence[str] | None = "0085_chatter_stats_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("users", "chatters")
_COLUMNS = (
    ("sessions_valid_after", sa.DateTime()),
    ("totp_secret", sa.String()),
    ("totp_enabled_at", sa.DateTime()),
    ("totp_recovery", sa.Text()),
    ("totp_last_step", sa.Integer()),
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table in _TABLES:
        have = _columns(table)
        for name, type_ in _COLUMNS:
            if name not in have:
                op.add_column(table, sa.Column(name, type_, nullable=True))


# Downgrade turns 2FA off for everyone and un-revokes old cookies.
def downgrade() -> None:
    for table in _TABLES:
        have = _columns(table)
        for name, _ in _COLUMNS:
            if name in have:
                op.drop_column(table, name)
