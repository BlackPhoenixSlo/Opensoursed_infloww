"""full_ai_offers — the Offer on its Decision row (Full AI Chat 03b)

Eight nullable columns on `ai_decisions` (spec 03b › Schema): the quoted and list price, the
locked/preview media, the item ref, the sent Offer's message id (NULL in test; the Phase 05 join
key), and the outcome with its time and join source. Plus the partial UNIQUE index
`uq_ai_decisions_offer_message` on `(account_id, offer_message_id) WHERE offer_message_id IS NOT
NULL`. No new table, no existing row touched. init_db's additive-column and index catch-up brings
both to a booting box; this file keeps the alembic chain linear. Inspector-guarded + idempotent.

Revision ID: 0120_full_ai_offers
Revises: 0119_full_ai_test_chat
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0120_full_ai_offers"
down_revision: str | Sequence[str] | None = "0119_full_ai_test_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_decisions"
_INDEX = "uq_ai_decisions_offer_message"
_COLUMNS = (
    ("offer_price_cents", sa.Integer), ("offer_list_cents", sa.Integer),
    ("offer_media_json", sa.Text), ("offer_item_ref", sa.Text),
    ("offer_message_id", sa.BigInteger), ("outcome", sa.String),
    ("outcome_at", sa.DateTime), ("join_src", sa.String),
)
_WHERE = "offer_message_id IS NOT NULL"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns(_TABLE)}
    for col, typ in _COLUMNS:
        if col not in have:
            op.add_column(_TABLE, sa.Column(col, typ, nullable=True))
    if _INDEX not in {i["name"] for i in insp.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["account_id", "offer_message_id"], unique=True,
                        sqlite_where=sa.text(_WHERE), postgresql_where=sa.text(_WHERE))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _INDEX in {i["name"] for i in insp.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    have = {c["name"] for c in insp.get_columns(_TABLE)}
    for col, _typ in reversed(_COLUMNS):
        if col in have:
            op.drop_column(_TABLE, col)
