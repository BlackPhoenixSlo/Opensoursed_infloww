"""_audience_crawl_fixtures — the fake OF, clock, log capture and mass_runs seeding the two Audience
crawl suites share (test_audience_crawl.py, test_audience_crawl_p2b.py).

Import it after `_harness` (which binds the temp DB) and `_harness.bootstrap()`. A send's row carries
the audience_filter a real send writes (`audience_filter`): what P2b's `_priors` compares, and its own
queue id: FakeOF's mass feed counts it as OF would (its rows, `counts` to say otherwise). `_setup` clears
every crawl verdict first, so no case's sends skip another's.
"""
from __future__ import annotations

import _harness  # noqa: F401 — binds the temp DB before any db import

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from types import SimpleNamespace

import audience_crawl
import of_call_counter
import of_pacing
from db.engine import get_session
from db.models import Account, MassRun


class OFErr(Exception):
    def __init__(self, status: int, text: str = '{"error":{"message":"Too many requests"}}', headers=None):
        super().__init__(f"{status}")
        self.response = SimpleNamespace(status_code=status, text=text, headers=headers or {})


TOO_MANY = OFErr  # readability at the call sites
PROBE: contextvars.ContextVar = contextvars.ContextVar("test_audience_crawl_probe", default=None)


class Clock:
    """The crawl's clock and sleep: a sleep only moves the clock."""

    def __init__(self):
        self.t = 1_000.0
        self.waits: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.waits.append(s)
        self.t += s
        await asyncio.sleep(0)


class FakeOF:
    """fans / following / custom lists, OF's page shapes; every GET goes through
    of_pacing.paced like OFClient.get_json. `script[(src, offset)]`: what the next calls at
    that offset raise, in order (None = answer); the mass feed's src is "feed". `cost_s`: clock
    seconds a roster page takes. The mass feed (`mass_message_history`; its GETs in `feeds`, not
    `calls`; free on the clock): this Creator's runs with a queue id, newest first, sentCount OF's
    audience of each from its audience_filter over the full rows (`counts[run]` instead;
    `unlisted` runs left out). `get_list` (`/lists/{id}`, in `calls` as src ("count", id)): its
    usersCount `list_counts[id]`."""

    def __init__(self, clock: Clock, *, fans=(), following=(), lists=None, account_id="ac1", cost_s=0.0):
        self.clock, self.account_id, self.cost_s = clock, account_id, cost_s
        self.rows = {"fans": list(fans), "following": list(following),
                     **{("list", int(k)): list(v) for k, v in (lists or {}).items()}}
        self.script: dict = {}
        self.counts: dict = {}         # mass run id -> the feed's sentCount
        self.unlisted: set = set()     # mass run ids the feed leaves out
        self.list_counts: dict = {}    # list id -> usersCount (get_list)
        self.calls: list[tuple] = []   # (clock t, monotonic t, src, offset, outcome, walk)
        self.feeds: list[tuple] = []   # the mass feed's, same shape
        self.ctx: list[tuple] = []     # (PROBE, caller label) per call

    def _get(self, src, offset, limit, bare=False):
        def call():
            w = of_pacing._WALK.get()
            self.ctx.append((PROBE.get(), of_call_counter.caller_kind()))
            todo = self.script.get((src, offset)) or []
            err = todo.pop(0) if todo else None
            status = getattr(getattr(err, "response", None), "status_code", "error") if err else 200
            (self.feeds if src == "feed" else self.calls).append(
                (self.clock.t, time.monotonic(), src, offset, status, (w.kind, w.retry_429) if w else None))
            self.clock.t += 0.0 if src == "feed" else self.cost_s
            if err is not None:
                raise err
            if src == "feed":
                return {"items": self._feed(limit), "hasMore": False}
            rows = self.rows[src]
            page = [{"id": i} for i in rows[offset:offset + limit]]
            return page if bare else {"list": page, "hasMore": offset + limit < len(rows)}
        return of_pacing.paced(self.account_id, call)

    def truth(self, af: dict) -> set:
        """OF's audience of a send (its audience_filter) over the full rows; a value OF would refuse adds nothing."""
        def ids(xs):
            return {int(x) for x in xs or () if str(x).strip().isdigit()}

        def rows(names):
            n = {str(x).strip().lower() for x in names or ()}
            return {u for k in n & {"fans", "following"} for u in self.rows[k]} | \
                {u for k in ids(n) for u in self.rows.get(("list", k), ())}
        return (ids(af.get("included_users")) | rows(af.get("user_lists"))) - \
            (ids(af.get("excluded_users")) | rows(af.get("excluded_user_lists")))

    def _feed(self, limit):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(_harness.DB_PATH)) as db:
            runs = db.execute("SELECT id, queue_id, audience_filter FROM mass_runs WHERE account_id = ? AND "
                              "queue_id IS NOT NULL ORDER BY id DESC", (self.account_id,)).fetchall()
        return [{"id": q, "sentCount": self.counts[r] if r in self.counts else len(self.truth(json.loads(af)))}
                for r, q, af in runs if r not in self.unlisted][:limit]

    def mass_message_history(self, *, start_date, end_date, limit=50, offset=0):
        return self._get("feed", offset, limit)

    def subscribers(self, *, type="active", limit=10, offset=0, **kw):
        return self._get("fans", offset, limit)

    def following(self, *, type="active", limit=10, offset=0, **kw):
        return self._get("following", offset, limit)

    def list_users_in(self, list_id, *, limit=20, offset=0, **kw):
        return self._get(("list", int(list_id)), offset, limit, bare=True)

    def get_list(self, list_id):
        """`/lists/{id}`: its usersCount = `list_counts[id]` (no entry: no field)."""
        def call():
            self.calls.append((self.clock.t, time.monotonic(), ("count", int(list_id)), 0, 200, None))
            n = self.list_counts.get(int(list_id))
            return {"id": int(list_id)} if n is None else {"id": int(list_id), "usersCount": n}
        return of_pacing.paced(self.account_id, call)

    def offsets(self, src="fans"):
        return [c[3] for c in self.calls if c[2] == src]


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.cancelled: list[str] = []
        self.repeats: list[str] = []   # each `audience_crawl repeated page` line's verdict

    def emit(self, rec):
        m = rec.getMessage()
        if m.startswith("audience_crawl_end"):
            self.lines.append(m)
        elif m.startswith("audience_crawl_cancelled"):
            self.cancelled.append(m)
        elif m.startswith("audience_crawl repeated page"):
            self.repeats.append(m.rsplit("-> ", 1)[-1])

    def parsed(self) -> list[dict]:
        return [dict(re.findall(r"(\w+)=(\S+)", x)) for x in self.lines]


def _reset_verdicts() -> None:
    """Cases share one DB: an earlier case's crawl verdicts must not skip a later one."""
    import sqlite3
    from contextlib import closing
    if not _harness.DB_PATH.exists():
        return
    with closing(sqlite3.connect(_harness.DB_PATH)) as db, db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'mass_runs'").fetchone():
            db.execute("UPDATE mass_runs SET crawl_outcome = NULL")
            db.execute("DELETE FROM mass_broadcast_cache")


def _setup(**env) -> tuple[Clock, Lines]:
    _reset_verdicts()
    for k in [k for k in os.environ if k.startswith("AUDIENCE_CRAWL_")]:
        os.environ.pop(k)
    os.environ.update({k: str(v) for k, v in env.items()})
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0
    of_pacing._next_at.clear()
    audience_crawl._crawlers.clear()   # each case runs on its own loop (_harness.run)
    audience_crawl._queues.clear()
    clock = Clock()
    audience_crawl._now, audience_crawl._sleep = clock.now, clock.sleep
    lines = Lines()
    lg = logging.getLogger("of-relay.audience_crawl")
    for h in list(lg.handlers):
        if isinstance(h, Lines):
            lg.removeHandler(h)
    lg.addHandler(lines)
    lg.setLevel(logging.INFO)
    return clock, lines


def audience_filter(kw: dict) -> str:
    """The mass_runs.audience_filter a real send writes for record_after_send's `kw` (send_mass_decide's keys)."""
    return json.dumps({"user_lists": list(kw.get("user_lists") or ()),
                       "included_users": list(kw.get("included_users") or ()),
                       "excluded_users": list(kw.get("excluded_users") or ()),
                       "excluded_user_lists": list(kw.get("excluded_user_lists") or ()),
                       "online": bool(kw.get("online_only")), "filters": bool(kw.get("filters"))})


_QUEUE = iter(range(8_100_000_000, 8_200_000_000))


async def _run_row(aid: str, kw: dict | None = None, *, kind: str | None = None) -> int:
    """A send's mass_runs row with its own queue id (`kw` None: all fans; `kind`: its automation_kind,
    the Composer's is None)."""
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        mr = MassRun(account_id=aid, audience_filter=audience_filter({"user_lists": ["fans"]} if kw is None else kw), recipient_count=0, status="ok",
                     automation_kind=kind, queue_id=next(_QUEUE))
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _recorded(run_id: int):
    async with get_session() as s:
        raw = (await s.get(MassRun, run_id)).recipients_json
    return None if raw is None else json.loads(raw)


async def _send(of: FakeOF, clock: Clock, *, aid="ac1", count=None, listed=True, **kw) -> int:
    """One send (`count`: OF's sentCount of it in the feed instead of its audience over the rows;
    `listed` False: the feed leaves it out)."""
    kw.setdefault("user_lists", ["fans"])
    run = await _run_row(aid, kw)
    if count is not None:
        of.counts[run] = count
    if not listed:
        of.unlisted.add(run)
    await audience_crawl.record_after_send(aid, of, run, sent_at=clock.now(), **kw)
    return run


async def _send_many(of: FakeOF, clock: Clock, *kws: dict, aid="ac1") -> list[int]:
    """Several sends queued back to back, before the crawler's first step: one round."""
    kws = [{"user_lists": ["fans"], **kw} for kw in kws]
    runs = [await _run_row(aid, kw) for kw in kws]
    for run, kw in zip(runs, kws):
        await audience_crawl.record_after_send(aid, of, run, sent_at=clock.now(), **kw)
    return runs


async def _outcome(run_id: int):
    async with get_session() as s:
        return (await s.get(MassRun, run_id)).crawl_outcome



def _line(lines: Lines, run: int) -> dict:
    got = [p for p in lines.parsed() if p.get("run") == str(run)]
    assert len(got) == 1, f"one audience_crawl_end line per request: {lines.lines}"
    return got[0]


# ── recover_at_boot rows ──
AUD = {"user_lists": ["fans"], "included_users": [], "excluded_users": [2], "excluded_user_lists": [],
        "online": False, "filters": False}


async def _boot_row(aid: str, *, age_s: float, audience=None, raw: str | None = None, queue_id=555,
                    status="ok", recipients=None, outcome=None) -> int:
    """A mass_runs row as a send that closed `age_s` ago left it (started_at UTC-naive, as MassRun's default)."""
    from datetime import datetime, timedelta
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        mr = MassRun(account_id=aid, recipient_count=0, status=status, queue_id=queue_id,
                     audience_filter=raw if raw is not None else json.dumps(audience if audience is not None else AUD),
                     started_at=datetime.utcnow() - timedelta(seconds=age_s),
                     recipients_json=None if recipients is None else json.dumps(recipients), crawl_outcome=outcome)
        s.add(mr)
        await s.flush()
        return int(mr.id)


def _loader(clients: dict):
    def load(aid):
        if aid not in clients:
            raise KeyError(aid)   # another case's Creator, or one with no session: skipped
        return clients[aid]
    return load
