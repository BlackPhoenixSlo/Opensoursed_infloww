from __future__ import annotations

from datetime import timedelta
from itertools import groupby

import sqlalchemy as sa

# Boot catch-up only (relay DB never runs alembic); idempotent: only NULL rows are read.
LEGACY_GAP = timedelta(hours=2)

_turns = sa.table(
    "assistant_turns",
    sa.column("id", sa.Integer), sa.column("ts", sa.DateTime),
    sa.column("user_id", sa.String), sa.column("chatter_id", sa.String),
    sa.column("account_id", sa.String), sa.column("thread_id", sa.String),
)


def _asker(r) -> tuple:
    return r.user_id, r.chatter_id, r.account_id


def _order(r) -> tuple:
    return tuple((v is not None, v or "") for v in _asker(r)) + (r.id,)


def backfill_thread_ids(conn: sa.Connection) -> int:
    insp = sa.inspect(conn)
    if not insp.has_table("assistant_turns"):
        return 0
    if "thread_id" not in {c["name"] for c in insp.get_columns("assistant_turns")}:
        return 0
    rows = conn.execute(
        sa.select(_turns.c.id, _turns.c.ts, _turns.c.user_id, _turns.c.chatter_id,
                  _turns.c.account_id)
        .where(_turns.c.thread_id.is_(None))).all()
    params: list[dict] = []
    for _, run in groupby(sorted(rows, key=_order), key=_asker):
        thread, last = None, None
        for r in run:
            if thread is None or r.ts - last > LEGACY_GAP:
                thread = f"legacy-{r.id}"
            last = r.ts
            params.append({"rid": r.id, "tid": thread})
    if params:
        conn.execute(
            _turns.update().where(_turns.c.id == sa.bindparam("rid"))
            .values(thread_id=sa.bindparam("tid")), params)
    return len(params)
