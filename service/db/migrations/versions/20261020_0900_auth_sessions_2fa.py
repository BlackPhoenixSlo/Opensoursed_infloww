"""auth_sessions_2fa — session revoke and personal 2FA on users and chatters

Five nullable columns on both `users` and `chatters` (db.models._LoginSecurity,
service/account_security.py):

  sessions_valid_after DATETIME  a session cookie issued before it is refused
  totp_secret          TEXT      base32 TOTP secret; set means 2FA is on
  totp_enabled_at      DATETIME  when 2FA was turned on ("Enabled on <date>")
  totp_recovery        TEXT      JSON list of the unused backup codes' sha256
  totp_last_step       INTEGER   the last accepted TOTP step (replay guard)

All NULL on existing rows: no session is revoked and nobody has 2FA. The ORM
models declare the same columns, so `init_db()`'s ADD-COLUMN catch-up brings
them to a booting box; this revision keeps the alembic chain canonical.
Idempotent (inspector-guarded, house convention). Downgrade drops them, which
turns 2FA off for everyone and un-revokes old cookies.

Revision ID: 0086_auth_sessions_2fa
Revises: 0085_chatter_stats_index
Create Date: 2026-10-20
"""
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


def downgrade() -> None:
    for table in _TABLES:
        have = _columns(table)
        for name, _ in _COLUMNS:
            if name in have:
                op.drop_column(table, name)
