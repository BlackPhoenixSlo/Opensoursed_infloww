"""service/audience_crawl.py — the Audience crawl of a mass send, paced and resumable, in
the background (docs/spec/phase-02-audience-crawl.md). The rules are
audience_crawl_decide's; this is the I/O.

  record_after_send(account_id, client, mass_run_id, *, user_lists, included_users,
                    excluded_users, excluded_user_lists, filters, online_only,
                    verified_lists, sent_at, deadline_at=None)
      Returns at once: queues the request and starts the Creator's crawler if none runs
      (in a fresh contextvars.Context: nothing of the first sender's context, e.g. its
      request or run slot, leaks into the crawls it later serves).
      `sent_at`: the monotonic time OF accepted the POST; the request's deadline is
      `sent_at + AUDIENCE_CRAWL_DEADLINE_S`; `deadline_at` (wall clock, epoch s), when
      given, is the deadline instead (recover_at_boot: the run's own, from its started_at).
      `verified_lists` {OF list id: frozenset of
      members}: the exclude lists the send verified under `broadcast_lock` (Auto_Exclude
      on its exact path, AUTOFENCE once its read-back matched), subtracted as given and
      never read. send_mass_message's step 6 and the
      Composer's run close (mass_queue_api._close_mass_run) hand off here in `paced`
      mode; `legacy` mode runs today's inline audiences.resolve_recipients_blocking.
  drain(account_id=None, *, timeout_s=None)
      Awaits every queued and running crawl (of one Creator, or all). Past `timeout_s` the
      rest are cancelled: no audience_crawl_end line, no stamp (the send stays NULL, the
      sweep counts it `lost`); each cancelled crawler logs one `audience_crawl_cancelled`
      warning naming its dropped runs (in flight + queued) and clears its queue. Shutdown
      calls it, bounded.
  recover_at_boot(load_client)
      Once at boot (server's startup), `paced` mode only: the sends a restart cut off.
      Every mass_runs row with a queue_id (an immediate send OF accepted), status ok,
      recipients_json NULL, crawl_outcome NULL or `error` (its crawl never ended, or failed
      retryably: any other stamped outcome, e.g. `incomplete` or `skipped_incomplete`, is
      never crawled again) and started_at within AUDIENCE_CRAWL_DEADLINE_S of now, whose
      audience_filter parses, names `user_lists` and says `online` and `filters` false
      (rows written before those two keys are skipped), is handed to record_after_send
      with that audience, no verified lists (re-read from offset 0: no cursor survives a
      restart) and `deadline_at` = started_at + the deadline. A Creator whose client does
      not load (`load_client(account_id)`) is skipped. Reads only; never raises.

One crawler per Creator (an asyncio task, held in `_crawlers`), serving its queue in
rounds. A round takes every request queued before it started (so every read it makes
began after each of their POSTs); one queued meanwhile waits for the next round.
In a round (the rules are audience_crawl_decide's `needs` / `needers` / `coalesced`):
  * filters / online -> `online`; a list name other than fans / following / a numeric
    list id, or a non-numeric exclude list -> `unknown_list`: no read.
  * P2b, a comparable request (audience_crawl_decide `audience_key`: a roster audience
    with no explicit ids; a list-only one is crawled as before) with a mass run reads its
    Creator's earlier sends once (`_priors`: the same automation_kind, an audience_filter
    `_recoverable` reads with the same key, newest first) for the skip after a failed verdict
    (the newest with a verdict, `recorded` / `incomplete` / `deadline`, was `incomplete` or
    `deadline` less than AUDIENCE_CRAWL_REPROBE_S ago: NULL `skipped_incomplete`, no read;
    past that one real crawl re-probes the roster). A row that does not parse right is
    skipped (no prior); anything else failing there fails that request only (`error`).
  * the rest need their include sources (fans, following, list ids) and every exclude
    list not in their `verified_lists`; the union is read once, every list (include or
    exclude) before the rosters (a broken exclude list fails its requests before any
    roster page), else first seen, each source inside
    `of_pacing.walk(account_id, "audience_crawl", retry_429=False)`: every page through
    the Creator's shared background pacer (a page thread in `asyncio.to_thread`),
    counted as `walk:audience_crawl` (of_call_counter), on the first needer's client.
  * a request whose last needed source is read is finished at once, not at the round's
    end: recorded = audiences.final_audience(included ∪ include sources, [excluded_users,
    verified or read exclude sets]), stamped by attribution.stamp_mass_recipients, its
    line logged (so another request's 429 ladder never delays it past its deadline).
  * the completeness gate (P2b), on a request that read a roster (its walk ended on OF's
    own end): its set's size over OF's own count of this
    send (`complete`), the sentCount of its queue id in the mass feed (`_crawl`'s `count`: one GET of
    the newest FEED_LIMIT sends per round, the first such request's, paced and charged like a
    page; no GET leaves past a live request's deadline); recorded only complete by OF's count
    (AUDIENCE_CRAWL_COMPLETE_MIN..MAX), under it NULL `incomplete`, over it or no count (not in
    the feed, 0, or the read failed in any way: 401 / 403, a 429 wait past the deadline, an
    error) NULL `no_count`: never `dead_session` or `deadline`, never a verdict (its rosters
    were read in time). A prior send's count cannot prove this set complete: lists and
    rosters churn between sends.
  * every outcome is stamped on mass_runs.crawl_outcome (best effort) but a recovered
    crawl's `deadline` (the restart's leftover time, no verdict on the roster).
  * a source that does not complete fails only the live requests needing it (NULL, its
    outcome); a source still unread that only failed requests need is skipped; a
    request whose deadline passes before its reads end is NULL `deadline`, its line
    logged then (not at the round's end, nor when its own source's read starts), the
    others read on. `dead_session` ends the round: every request still live is NULL
    `dead_session`.
  * one `audience_crawl_end` line per request, whatever happened, unless cancelled
    (drain's timeout; the cancelled line names only the runs not yet finished).

The pager (one source):
  * 429: waits ON THE LOOP the Backoff ladder (`next_wait`: OF's Retry-After header or
    body ask when longer, else 30 s doubling to 300 s), then resumes one page back
    (`resume_offset`), never from 0; OF's answer read by of_pacing.upstream / allow_s.
    Rows dedupe by id; the overlap page is exempt from the "page added nothing" stop. The ladder resets only once a page at or past the
    offset that failed succeeds.
  * 401 / 403: `dead_session`, no retry. Any other error: retried at the same offset,
    AUDIENCE_CRAWL_PAGE_TRIES in all, 1 s then 2 s apart (audiences._ResumableLists), then `error`.
  * AUDIENCE_CRAWL_MAX_PAGES pages with more to read: `truncated`.
  * a repeated page (every id already read, not the overlap page): a list whose ids match
    its usersCount is complete (one count GET), else `truncated`; a roster re-reads that
    offset once, a second repeat in a row `truncated` (never recorded off a repeat: a roster
    ends only on OF's own end, a short or empty page or no more).
  * no GET leaves and no wait starts that would end past the deadline of any request of
    the round still live (needing this source or not): that request is `deadline`; the
    source stops (`deadline`) once no needer is left.
  End rules as of_paging.page_all_checked: an empty page, or an envelope without hasMore.

Line (one per request, never per page):
  audience_crawl_end account=<id> run=<mass_run_id> outcome=<...> pages=<n> failed=<n>
  resumes=<n> waited_s=<n> reused=<n> coalesced=<n> recipients=<n|-> sent_count=<n|-> ratio=<r|->
  count_delay_s=<n|->
`pages` successful calls (pages, the mass feed's GET, and a list's count GET after a repeat; a failed
one is in `failed`), `failed` failed attempts (each 429 and each errored try),
`resumes` overlap re-reads, `waited_s` the waits: a shared read's are charged once, to
the first still-live request of the round needing it (so the lines of a round sum to
its calls).
`reused` the verified lists not read, `coalesced` the other requests of the round
sharing at least one read with this one. `sent_count` OF's count of the send (`-`: the gate
never ran, or the feed gave none; watch.py's audience_crawl_count_finish compares it with OF's
later chat_queue_finish total), `ratio` the crawled size over it, `count_delay_s` how long
after the send that count was read (`-`: not read).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import audience_crawl_decide as acd
import of_pacing
import of_paging

log = logging.getLogger("of-relay.audience_crawl")

# Shutdown's bound on drain(): crawls still running past it are cut off (NULL).
# ASSUMPTION: 10 s inside docker's 75 s stop grace after the automation drain's 45 s; a
# crawl in a 30-300 s 429 wait cannot finish anyway. Cut-off sends are what a boot re-crawl
# would pick up (ticket 07); a sweep showing many `lost` runs at deploys would overturn it.
SHUTDOWN_DRAIN_S = 10.0

# Seams (tests replace them): the monotonic clock and the loop's sleep.
_now = time.monotonic
_sleep = asyncio.sleep
_wall = time.time   # recover_at_boot's deadlines: a run's started_at is wall clock

# How many of a Creator's latest runs of the same kind `_priors` scans for comparable ones (parsed in
# Python: audience_filter is JSON). ~2 days of sends at ~24/day.
_LOOKBACK = 50
# The mass feed's newest sends `_crawl` reads (one page, server.py's feed route's limit): a round's sends are
# its newest. Its dates are padded by FEED_PAD_S both ways: OF may read them as local time (the same pad as the other OF feed reads).
FEED_LIMIT = 20
FEED_PAD_S = 14 * 3600.0
_FEED_FMT = "%Y-%m-%d %H:%M:%S"

_queues: dict[str, deque] = {}
_crawlers: dict[str, asyncio.Task] = {}


@dataclass(frozen=True)
class _Request:
    account_id: str
    client: Any
    mass_run_id: int | None
    user_lists: tuple
    included_users: tuple
    excluded_users: tuple
    excluded_user_lists: tuple
    filters: dict | None
    online_only: bool
    verified: dict              # OF list id -> frozenset of members the send verified
    deadline: float
    sent_at: float              # monotonic: OF's accept (the deadline's start)
    recovered: bool = False     # recover_at_boot's: its deadline is the cut-off run's own


@dataclass
class _Tally:
    pages: int = 0
    failed: int = 0
    resumes: int = 0
    waited_s: float = 0.0


@dataclass(eq=False)   # by identity: the round's `needers` keys
class _Served:
    """One request's part of a round. `done` once its line is logged: the one place
    "finished" is tracked."""
    req: _Request
    tally: _Tally = field(default_factory=_Tally)
    inc: tuple = ()        # include sources (acd.needs)
    exc: tuple = ()        # exclude lists to read
    reused: tuple = ()     # verified exclude list ids, never read
    coalesced: int = 0
    sent: int | None = None            # OF's count of this send (P2b, `_crawl`'s `count`)…
    count_delay: float | None = None   # …read this long after the send
    done: bool = False

    @property
    def sources(self) -> tuple:
        return (*self.inc, *self.exc)


async def record_after_send(account_id, client, mass_run_id, *,
                            user_lists: Iterable = (), included_users: Iterable = (),
                            excluded_users: Iterable = (), excluded_user_lists: Iterable = (),
                            filters: dict | None = None, online_only: bool = False,
                            verified_lists: dict | None = None,
                            sent_at: float | None = None,
                            deadline_at: float | None = None) -> None:
    aid = str(account_id)
    knobs = acd.knobs()
    if deadline_at is not None:
        deadline = _now() + (float(deadline_at) - _wall())
    else:
        deadline = (_now() if sent_at is None else float(sent_at)) + knobs.deadline_s
    _queues.setdefault(aid, deque()).append(_Request(
        account_id=aid, client=client, mass_run_id=mass_run_id,
        user_lists=tuple(user_lists or ()), included_users=tuple(included_users or ()),
        excluded_users=tuple(excluded_users or ()), excluded_user_lists=tuple(excluded_user_lists or ()),
        filters=filters, online_only=bool(online_only),
        verified=dict(verified_lists or {}),
        deadline=deadline, sent_at=deadline - knobs.deadline_s, recovered=deadline_at is not None))
    t = _crawlers.get(aid)
    if t is None or t.done():
        _crawlers[aid] = asyncio.get_running_loop().create_task(
            _crawler(aid), name=f"audience-crawl-{aid}", context=contextvars.Context())


async def recover_at_boot(load_client) -> None:
    # ASSUMPTION: the client loader is a required parameter (server passes `_load_client`, as
    # vault_upload.sweep takes `client_for`; tests a fake) where the spec writes a bare
    # `recover_at_boot()`. Rung 3. Overturned if a second caller needs a default loader.
    try:
        k = acd.knobs()
        if k.mode != "paced":
            return
        rows = await _cut_off_runs(k.deadline_s)
    except Exception:  # noqa: BLE001 — recovery only reads; a boot never fails on it
        log.warning("audience_crawl_recover failed — no cut-off send re-crawled", exc_info=True)
        return
    clients: dict = {}
    handed = skipped = 0
    for run_id, aid, started_at, raw in rows:
        try:
            aud = _recoverable(raw)
            if aud is None:
                skipped += 1
                continue
            if aid not in clients:
                try:
                    clients[aid] = load_client(aid)
                except Exception as e:  # noqa: BLE001 — no session (yet): its runs stay NULL
                    log.warning("audience_crawl_recover no client account=%s: %s", aid, e)
                    clients[aid] = None
            if clients[aid] is None:
                skipped += 1
                continue
            started = started_at.replace(tzinfo=timezone.utc).timestamp()   # UTC-naive (db.models._now)
            await record_after_send(aid, clients[aid], run_id, **aud, deadline_at=started + k.deadline_s)
            handed += 1
        except Exception:  # noqa: BLE001 — one bad row fails only itself
            log.warning("audience_crawl_recover bad run=%s", run_id, exc_info=True)
            skipped += 1
    log.info("audience_crawl_recover runs=%d skipped=%d", handed, skipped)


async def _cut_off_runs(deadline_s: float) -> list[tuple]:
    """(id, account_id, started_at, audience_filter) of every immediate ok send still
    unrecorded, its crawl never ended or ended `error` (retryable), started within
    `deadline_s` of now."""
    from sqlalchemy import or_, select
    from db.engine import get_session
    from db.models import MASS_RUN_OK, MassRun
    since = datetime.fromtimestamp(_wall() - deadline_s, tz=timezone.utc).replace(tzinfo=None)
    async with get_session() as s:
        res = await s.execute(
            select(MassRun.id, MassRun.account_id, MassRun.started_at, MassRun.audience_filter)
            .where(MassRun.queue_id.is_not(None), MassRun.status == MASS_RUN_OK,
                   MassRun.recipients_json.is_(None),
                   or_(MassRun.crawl_outcome.is_(None), MassRun.crawl_outcome == "error"),
                   MassRun.started_at >= since)
            .order_by(MassRun.id))
        return [tuple(r) for r in res.all()]


def _recoverable(raw) -> dict | None:
    """record_after_send's audience from a run's audience_filter, or None: unparsable, no
    `user_lists`, or not both `online` and `filters` present and false."""
    try:
        af = json.loads(raw or "")
    except ValueError:
        return None
    if (not isinstance(af, dict) or not af.get("user_lists") or "online" not in af or "filters" not in af
            or af["online"] or af["filters"]):
        return None
    return dict(user_lists=af["user_lists"], included_users=af.get("included_users") or (),
                excluded_users=af.get("excluded_users") or (),
                excluded_user_lists=af.get("excluded_user_lists") or ())


async def drain(account_id=None, *, timeout_s: float | None = None) -> None:
    loop = asyncio.get_running_loop()
    end = None if timeout_s is None else loop.time() + timeout_s
    while True:
        mine = {a: t for a, t in list(_crawlers.items())
                if (account_id is None or a == str(account_id)) and not t.done()}
        if not mine:
            return
        left = None if end is None else end - loop.time()
        if left is not None and left <= 0:
            for t in mine.values():
                t.cancel()
            await asyncio.gather(*mine.values(), return_exceptions=True)
            for a in mine:   # a crawler cancelled before its first step never ran its handler
                if _queues.get(a):
                    _log_cancelled(a, list(_queues[a]))
                    _queues[a].clear()
            log.warning("audience_crawl_drain cancelled crawlers=%d (past %.0f s): their sends stay "
                        "unrecorded (runs in the audience_crawl_cancelled lines)", len(mine), timeout_s)
            return
        await asyncio.wait(mine.values(), timeout=left)


async def _crawler(aid: str) -> None:
    q = _queues[aid]
    cur: list[_Served] = []
    try:
        while q:
            cur = [_Served(r) for r in q]    # the round: every request queued before it started
            q.clear()
            await _round(aid, cur)
            cur = []
    except asyncio.CancelledError:
        _log_cancelled(aid, [x.req for x in cur if not x.done] + list(q))
        q.clear()
        raise
    finally:   # no await between the last empty check and here: a new request starts a new crawler
        if _crawlers.get(aid) is asyncio.current_task():
            del _crawlers[aid]


def _log_cancelled(aid: str, dropped: list[_Request]) -> None:
    log.warning("audience_crawl_cancelled account=%s runs=%s — those sends stay unrecorded",
                aid, ",".join(str(r.mass_run_id) for r in dropped) or "-")


async def _round(aid: str, served: list[_Served]) -> None:
    k = acd.knobs()
    for x in served:
        r = x.req
        refused = acd.refusal(r.user_lists, r.filters, r.online_only, r.excluded_user_lists)
        if refused is None:
            try:
                x.inc, x.exc, x.reused = acd.needs(r.user_lists, r.excluded_user_lists, r.verified)
                key = acd.audience_key(r.user_lists, r.excluded_user_lists, r.included_users)
                if key is not None and r.mass_run_id is not None:
                    last, last_age = await _priors(r, key)
                    if acd.skips(last, last_age, k):
                        refused = "skipped_incomplete"
            except Exception:  # noqa: BLE001 — a bad value fails only its own request
                log.warning("audience_crawl bad request account=%s run=%s", aid, r.mass_run_id, exc_info=True)
                refused = "error"
        if refused is not None:
            await _finish(x, refused)
    crawl = [x for x in served if not x.done]
    if not crawl:
        return
    by_src = acd.lists_first(acd.needers({x: x.sources for x in crawl}))
    for x in crawl:
        x.coalesced = acd.coalesced(x, by_src)
    try:
        await _crawl(crawl, by_src, k)
    except Exception:  # noqa: BLE001 — the sends are out; a crawl that breaks costs their records only
        log.warning("audience_crawl failed account=%s runs=%s — the runs stay unrecorded", aid,
                    ",".join(str(x.req.mass_run_id) for x in crawl if not x.done), exc_info=True)
        for x in crawl:
            if not x.done:
                await _finish(x, "error")


def _audience(x: _Served, read: dict) -> list[int]:
    """The one set algebra: included ∪ include sources, minus excluded ids and every
    exclude set (verified as given, else read)."""
    from audiences import final_audience
    r = x.req
    base = {int(u) for u in r.included_users if u is not None}.union(*(read[s] for s in x.inc))
    excl = {int(u) for u in r.excluded_users if u is not None}
    out = final_audience(sorted(base), [excl, *(r.verified[lid] for lid in x.reused), *(read[s] for s in x.exc)])
    return list(out.included)


async def _finish(x: _Served, outcome: str, read: dict | None = None) -> None:
    """Log `x`'s line now; `recorded` (its sources all in `read`) also computes its
    audience, passes it through the completeness gate when it read a roster (against
    `x.sent`, OF's count), and stamps it. The outcome lands on
    mass_runs.crawl_outcome. Anything failing here fails `x` only (`error`)."""
    from attribution import stamp_mass_recipients
    r = x.req
    recorded = ratio = None
    gated = False
    if outcome == "recorded" and _now() >= r.deadline:
        outcome = "deadline"
    if outcome == "recorded":
        try:
            recorded = _audience(x, read or {})
            if any(s in acd.ROSTERS for s in x.inc):   # a roster read off OF: judged against OF's own count
                gated = True
                outcome, ratio = acd.complete(len(recorded), x.sent, acd.knobs())
            if outcome != "recorded":
                recorded = None
            elif await stamp_mass_recipients(r.mass_run_id, recorded) is None:
                outcome, recorded = "error", None
        except Exception:  # noqa: BLE001
            log.warning("audience_crawl stamp failed account=%s run=%s — the run stays unrecorded",
                        r.account_id, r.mass_run_id, exc_info=True)
            outcome, recorded = "error", None
    await _stamp_outcome(r, outcome)
    t = x.tally
    log.info("audience_crawl_end account=%s run=%s outcome=%s pages=%d failed=%d resumes=%d "
             "waited_s=%.1f reused=%d coalesced=%d recipients=%s sent_count=%s ratio=%s count_delay_s=%s",
             r.account_id, r.mass_run_id, outcome, t.pages, t.failed, t.resumes, t.waited_s, len(x.reused),
             x.coalesced, "-" if recorded is None else len(recorded), "-" if not gated or x.sent is None else x.sent,
             "-" if ratio is None else f"{ratio:.3f}",
             "-" if not gated or x.count_delay is None else f"{x.count_delay:.1f}")
    x.done = True


async def _priors(r: _Request, key: tuple) -> tuple:
    """(verdict, age_s) of the Creator's newest earlier run comparable to `r` with a crawl verdict
    (VERDICTS): the same automation_kind, an audience_filter `_recoverable` reads (online / filters false)
    with the same `audience_key`. Age from its started_at; Nones when none in the last _LOOKBACK runs. A read
    that fails: Nones (crawl, as before). A row that does not parse right is skipped (no prior; one debug
    line per request)."""
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import MassRun
    own_kind = select(MassRun.automation_kind).where(MassRun.id == int(r.mass_run_id)).scalar_subquery()
    try:
        async with get_session() as s:
            rows = (await s.execute(
                select(MassRun.crawl_outcome, MassRun.started_at, MassRun.audience_filter)
                .where(MassRun.account_id == r.account_id, MassRun.id < int(r.mass_run_id),
                       MassRun.automation_kind.is_not_distinct_from(own_kind),
                       MassRun.crawl_outcome.in_(acd.VERDICTS))
                .order_by(MassRun.id.desc()).limit(_LOOKBACK))).all()
    except Exception:  # noqa: BLE001
        log.warning("audience_crawl priors read failed account=%s run=%s — crawling", r.account_id,
                    r.mass_run_id, exc_info=True)
        return None, None
    verdict, bad = (None, None), 0
    for outcome, started_at, raw in rows:
        try:
            aud = _recoverable(raw)
            if aud is None or acd.audience_key(aud["user_lists"], aud["excluded_user_lists"],
                                               aud["included_users"]) != key:
                continue
            verdict = outcome, _wall() - started_at.replace(tzinfo=timezone.utc).timestamp()   # UTC-naive
            break
        except Exception:  # noqa: BLE001 — a row that does not parse right is no prior, never an error
            bad += 1
    if bad:
        log.debug("audience_crawl priors account=%s run=%s skipped %d malformed row(s)", r.account_id,
                  r.mass_run_id, bad)
    return verdict


async def _stamp_outcome(r: _Request, outcome: str) -> None:
    """mass_runs.crawl_outcome = `outcome`, best effort (the skip and the boot re-crawl read it). A
    recovered crawl's `deadline` is the restart's leftover time, no verdict on the roster: not stamped."""
    from sqlalchemy import update
    from db.engine import get_session
    from db.models import MassRun
    if r.mass_run_id is None or (r.recovered and outcome == "deadline"):
        return
    try:
        async with get_session() as s:
            await s.execute(update(MassRun).where(MassRun.id == int(r.mass_run_id)).values(crawl_outcome=outcome))
    except Exception:  # noqa: BLE001
        log.warning("audience_crawl outcome stamp failed account=%s run=%s", r.account_id, r.mass_run_id,
                    exc_info=True)


async def _crawl(crawl: list[_Served], by_src: dict, k: acd.Knobs) -> None:
    """Read the round's sources once each; finish each request the moment its last
    source is read (a roster reader once OF's count of its send is read too), or the
    moment it fails."""
    read: dict = {}
    feed: dict = {}   # the round's one read of the mass feed: tried; if good, counts {queue id: sentCount}, at
    loop = asyncio.get_running_loop()

    def alive_for(needers: list[_Served]):
        async def alive(t: float) -> bool:
            """Finish (`deadline`) every request of the round whose deadline is not after `t`
            (needing this source or not: none is read while this one pages); a needer left?"""
            for x in crawl:
                if not x.done and t >= x.req.deadline:
                    await _finish(x, "deadline")
            return any(not x.done for x in needers)
        return alive

    def charge_for(needers: list[_Served]):
        # ASSUMPTION: a shared read is charged to its first live needer only, so a round's lines
        # sum to its calls (spec names no owner for a shared page); once that one is finished
        # (deadline), the next live needer carries the rest.
        return lambda: next(x.tally for x in needers if not x.done)

    def feed_alive(needers: list[_Served]):
        async def alive(t: float) -> bool:
            """alive_for's, but a request whose reads all ended is `no_count`, not `deadline`: its rosters
            were read in time, only OF's count of it is missing."""
            for x in crawl:
                if not x.done and t >= x.req.deadline:
                    await _finish(x, "no_count" if all(s in read for s in x.sources) else "deadline")
            return any(not x.done for x in needers)
        return alive

    async def paced(needers: list[_Served], fetch, page: int, ids: set, alive=None, what: str = "",
                    size=None) -> str:
        alive = alive or alive_for(needers)

        async def admit_on_loop() -> None:
            if not await alive(_now()):
                raise _Deadline

        def admit() -> None:
            # paced runs in the page worker. Finish expired requests on their owning loop
            # before departure, so only a live needer can be charged for this call.
            asyncio.run_coroutine_threadsafe(admit_on_loop(), loop).result()

        return await of_pacing.walk(needers[0].req.account_id, "audience_crawl",
                                    lambda: _page(fetch, page, ids, alive, k, charge_for(needers),
                                                  what=what, size=size),
                                    retry_429=False, before_call=admit)

    async def count(x: _Served) -> None:
        """x.sent: its queue id's sentCount in the round's one read of the mass feed (made now, for every
        live roster reader, if not tried yet). A read that fails in any way leaves no count (`no_count`)."""
        qid = await _queue_id(x.req)
        if qid is None:
            return
        if "tried" not in feed:
            feed["tried"] = True
            got: dict = {}
            needers = [x] + [y for y in crawl if y is not x and not y.done and any(s in acd.ROSTERS for s in y.inc)]
            outcome = await paced(needers, _feed(x.req.client, got), FEED_LIMIT, set(), alive=feed_alive(needers))
            items = got["r"].get("items") if isinstance(got.get("r"), dict) else None
            if outcome == "ok" and isinstance(items, list):
                feed.update(at=_now(), counts={})
                for it in items:
                    try:
                        feed["counts"][int(it["id"])] = int(it.get("sentCount") or 0)
                    except (TypeError, ValueError, KeyError, AttributeError):
                        continue
        if "counts" in feed:
            x.sent, x.count_delay = feed["counts"].get(qid), feed["at"] - x.req.sent_at

    async def finish_if_read(x: _Served) -> None:
        if x.done or not all(s in read for s in x.sources):
            return
        if any(s in acd.ROSTERS for s in x.inc):
            await count(x)
            if not x.done and _now() >= x.req.deadline:   # read in time; only the count came late
                await _finish(x, "no_count")
        if not x.done:
            await _finish(x, "recorded", read)

    for x in crawl:   # explicit ids only (or every list verified): nothing to read
        await finish_if_read(x)
    for src, who in by_src.items():
        needers = [x for x in who if not x.done]
        if not needers:   # only failed requests need it: skipped
            continue
        ids: set[int] = set()
        outcome = await paced(needers, _fetch(needers[0].req.client, src, k), _page_size(src, k), ids,
                              what=f"account={needers[0].req.account_id} src={src}",
                              size=_size(needers[0].req.client, src))
        if outcome == "dead_session":   # every source shares the session: the round ends
            for x in crawl:
                if not x.done:
                    await _finish(x, "dead_session")
            break
        if outcome != "ok":
            for x in needers:
                if not x.done:
                    await _finish(x, outcome)
            continue
        read[src] = ids
        for x in needers:
            await finish_if_read(x)


def _feed(client, got: dict):
    """The mass feed's newest FEED_LIMIT sends (server.py's feed route's call) as one pager call: OF's
    answer kept in `got["r"]`, the pager handed an empty last page (its loop ends on it, no paging)."""
    def fetch(_offset):
        now = datetime.fromtimestamp(_wall(), tz=timezone.utc).replace(tzinfo=None)
        got["r"] = client.mass_message_history(
            start_date=(now - timedelta(seconds=FEED_PAD_S + 86400)).strftime(_FEED_FMT),
            end_date=(now + timedelta(seconds=FEED_PAD_S)).strftime(_FEED_FMT), limit=FEED_LIMIT, offset=0)
        return {"list": [], "hasMore": False}
    return fetch


async def _queue_id(r: _Request) -> int | None:
    """The send's OF queue id (mass_runs.queue_id): None with no run, none set, or a failed read."""
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import MassRun
    if r.mass_run_id is None:
        return None
    try:
        async with get_session() as s:
            q = (await s.execute(select(MassRun.queue_id).where(MassRun.id == int(r.mass_run_id)))).scalar()
        return None if q is None else int(q)
    except Exception:  # noqa: BLE001 — no queue id: no count (`no_count`)
        log.warning("audience_crawl queue id read failed account=%s run=%s", r.account_id, r.mass_run_id,
                    exc_info=True)
        return None


def _page_size(src, k: acd.Knobs) -> int:
    return k.roster_page if src in acd.ROSTERS else of_paging.LIST_PAGE


def _fetch(client, src, k: acd.Knobs):
    if src == "fans":
        return lambda off: client.subscribers(type="active", limit=k.roster_page, offset=off)
    if src == "following":
        return lambda off: client.following(type="active", limit=k.roster_page, offset=off)
    return lambda off: client.list_users_in(src[1], limit=of_paging.LIST_PAGE, offset=off)


def _size(client, src):
    """A custom list's metadata GET (`/lists/{id}`: its usersCount), None for a roster."""
    if src in acd.ROSTERS:
        return None
    return lambda: client.get_list(src[1])


class _Deadline(Exception):
    """The paced page never departed: no live request still needs it."""


async def _page(fetch, page: int, ids: set[int], alive, k: acd.Knobs, charge, *,
                what: str = "", size=None) -> str:
    """One source paged into `ids`: `ok`, or the reason it stopped (`truncated`,
    `deadline`, `dead_session`, `error`). `await alive(t)`: does a request needing this
    source still have its deadline after `t` (it finishes every request of the round
    that does not, at once).
    `charge()`: the _Tally each call and wait is counted on.
    A repeated page (non-empty, every id seen, outside a resume overlap): a list (`size()`, its
    usersCount) whose read holds exactly that many ids is `ok` (OF echoes its page past the end),
    else `truncated`; a roster re-reads the same offset once (the repeat is transient: AE,
    2026-11-11, one fans offset repeated in about half the crawls), a second repeat in a row
    `truncated`. Each repeat logs one `audience_crawl repeated page` warning (`what`, offset,
    verdict `ok` / `retry` / `truncated`). A read OF ends on the overlap page after a 429,
    before the offset that failed (that page never read): a list by the same count, a roster
    `truncated` (`audience_crawl ended before its failed page`)."""
    offset = pages = attempt = tries = 0
    seen: set = set()            # raw row ids already taken (of_paging.take_page)
    fail_at: int | None = None   # the furthest offset a 429 hit since the ladder last reset
    retried = False              # the current offset already re-read after a repeat

    async def counted() -> tuple[str, int | None]:
        """A list's `GET /lists/{id}`: `ok` iff the ids read number its usersCount, else `truncated`."""
        count = None
        try:
            count = of_paging.users_count(await asyncio.to_thread(size))
            charge().pages += 1
        except _Deadline:
            return "deadline", None
        except Exception as e:  # noqa: BLE001 — no count: the read stays unproven
            charge().failed += 1
            log.warning("audience_crawl list count failed %s: %s", what, e)
        if not await alive(_now()):   # the count answered past the deadline: never record late
            return "deadline", count
        return ("ok" if count == len(ids) else "truncated"), count

    while True:
        if pages >= k.max_pages:
            log.warning("audience_crawl hit its %d-page backstop (%d rows)", k.max_pages, len(ids))
            return "truncated"
        if not await alive(_now()):
            return "deadline"
        try:
            r = await asyncio.to_thread(fetch, offset)
        except _Deadline:
            return "deadline"
        except Exception as e:  # noqa: BLE001 — classified below; the request's outcome
            charge().failed += 1
            status, body, header = of_pacing.upstream(e)
            live = await alive(_now())
            if status in (401, 403):
                return "dead_session"
            if not live:
                return "deadline"
            if status == 429:
                wait = acd.next_wait(attempt, acd.asked_wait(header, of_pacing.allow_s(body)), k)
                attempt += 1
                if not await alive(_now() + wait):
                    return "deadline"
                await _sleep(wait)
                charge().waited_s += wait
                fail_at = offset if fail_at is None else max(fail_at, offset)
                back = acd.resume_offset(offset, page)
                if back < offset:
                    charge().resumes += 1
                offset, tries = back, 0
                continue
            tries += 1
            if tries >= k.page_tries:
                log.warning("audience_crawl page failed %d times offset=%d: %s", tries, offset, e)
                return "error"
            wait = 1.0 + (tries - 1)
            if not await alive(_now() + wait):
                return "deadline"
            await _sleep(wait)
            charge().waited_s += wait
            continue
        tries = 0
        pages += 1
        charge().pages += 1
        if not await alive(_now()):
            return "deadline"
        overlap = fail_at is not None and offset < fail_at
        # ASSUMPTION: "past the offset that failed" read as at-or-past (the failed page
        # itself succeeding resets the ladder); the spec's wording allows either.
        if fail_at is not None and not overlap:
            fail_at, attempt = None, 0
        rows, n, more = of_paging.take_page(r, seen)
        ids.update(of_paging.int_ids(rows))
        if n and not rows and not overlap:
            count = None
            if size is not None:
                verdict, count = await counted()
                if verdict == "deadline":
                    return verdict
            else:
                verdict = "retry" if not retried else "truncated"
            log.warning("audience_crawl repeated page %s offset=%d n=%d more=%s pages=%d rows=%d "
                        "users_count=%s -> %s", what, offset, n, more, pages, len(ids),
                        "-" if count is None else count, verdict)
            if verdict != "retry":
                return verdict
            retried = True
            continue
        retried = False
        if not more:
            if overlap:
                # OF ended the read on the overlap page, before the offset whose 429 it resumed
                # from: the page it had promised there was never read. A list proves itself by
                # its count; a roster is unproven.
                verdict, count = await counted() if size is not None else ("truncated", None)
                if verdict == "deadline":
                    return verdict
                log.warning("audience_crawl ended before its failed page %s offset=%d failed_at=%d n=%d "
                            "pages=%d rows=%d users_count=%s -> %s", what, offset, fail_at, n, pages,
                            len(ids), "-" if count is None else count, verdict)
                return verdict
            return "ok"
        offset += n
