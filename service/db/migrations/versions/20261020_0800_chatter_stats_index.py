"""chatter_stats_index — ix_messages_account_fan_time widened to ix_messages_chat_seq

Roadmap W5 5.1. Chatting statistics' reply times (msg_stats.reply_stats) walk
each chat in time order and pair a fan's message with the reply, so the chat
index gains the columns that read needs and covers it.

  ix_messages_chat_seq           account_id, fan_id, created_at, message_id, direction,
                                 sent_by_employee_id, mass_run_id, automation_kind
  ix_messages_account_fan_time   dropped (account_id, fan_id, created_at: the new one's prefix)

A new name, because `init_db()`'s index catch-up adds a missing index by name
only; it also drops the old one (db.engine `_RETIRED_INDEXES`). This revision
keeps the alembic chain canonical. Idempotent (inspector-guarded, house
convention). Downgrade restores the narrower index.

Revision ID: 0085_chatter_stats_index
Revises: 0084_of_stats_daily
Create Date: 2026-10-20
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085_chatter_stats_index"
down_revision: str | Sequence[str] | None = "0084_of_stats_daily"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("ix_messages_account_fan_time", ["account_id", "fan_id", "created_at"])
_NEW = ("ix_messages_chat_seq", _OLD[1] + ["message_id", "direction", "sent_by_employee_id", "mass_run_id",
                                           "automation_kind"])


def _swap(drop: tuple[str, list[str]], create: tuple[str, list[str]]) -> None:
    have = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes("messages")}
    if create[0] not in have:
        op.create_index(create[0], "messages", create[1])
    if drop[0] in have:
        op.drop_index(drop[0], table_name="messages")


def upgrade() -> None:
    _swap(_OLD, _NEW)


def downgrade() -> None:
    _swap(_NEW, _OLD)
