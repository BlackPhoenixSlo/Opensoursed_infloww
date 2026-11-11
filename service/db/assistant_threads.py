"""Give every `assistant_turns` row from before threads (NULL `thread_id`) one.

The help widget lists and continues conversations by `thread_id`, and the
prompt's PREVIOUS TURNS are the ask's thread (assistant_api `_context_turns`),
so a row with none can be neither listed stably nor continued. Each asker's
(user_id, chatter_id) NULL rows on one account, in id order, form runs whose
neighbours are at most LEGACY_GAP apart — the old context rule (assistant_api
`CONTEXT_WINDOW`) — and each run becomes thread `legacy-<its first id>`.

Idempotent: only NULL rows are read, and none is left after a run, so a second
run changes nothing. Called from init_db's boot catch-up only (the relay DB
never runs alembic; revision 0110 adds the column alone). DELETE with that
block (see the marker there). SQLAlchemy only: no app import.
"""
from __future__ import annotations

from datetime import timedelta
from itertools import groupby

import sqlalchemy as sa

# = assistant_api.CONTEXT_WINDOW (pinned by test_assistant_api.py).
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
    """Asker then id, with NULL keys sortable."""
    return tuple((v is not None, v or "") for v in _asker(r)) + (r.id,)


def backfill_thread_ids(conn: sa.Connection) -> int:
    """Set `legacy-<first id>` on every NULL-thread row (see the module
    docstring); returns how many rows changed. `conn` is a sync connection
    inside a transaction. No table or no column yet → 0."""
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
