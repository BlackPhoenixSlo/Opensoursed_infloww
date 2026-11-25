from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0104_assistant_turns"
down_revision: str | Sequence[str] | None = "0103_saved_reply_sequences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "assistant_turns"


def upgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("user_id", sa.String, nullable=True),
        sa.Column("chatter_id", sa.String, nullable=True),
        sa.Column("account_id", sa.String, nullable=True),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("model", sa.String, nullable=True),
        sa.Column("provider", sa.String, nullable=True),
        sa.Column("cost_millicents", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
    )
    op.create_index("ix_assistant_turns_user_ts", _TABLE, ["user_id", "ts"])
    op.create_index("ix_assistant_turns_chatter_ts", _TABLE, ["chatter_id", "ts"])
    op.create_index("ix_assistant_turns_ts", _TABLE, ["ts"])


def downgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
