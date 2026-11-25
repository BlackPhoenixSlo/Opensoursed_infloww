from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072_saved_reply_tags_notes"
down_revision: str | Sequence[str] | None = "0071_invite_setup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = ("tags_json", "notes")


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("saved_replies")}


def upgrade() -> None:
    have = _columns()
    with op.batch_alter_table("saved_replies") as batch:
        for name in _NEW:
            if name not in have:
                batch.add_column(sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    have = _columns()
    with op.batch_alter_table("saved_replies") as batch:
        for name in _NEW:
            if name in have:
                batch.drop_column(name)
