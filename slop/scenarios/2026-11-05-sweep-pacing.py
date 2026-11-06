"""Background OnlyFans list walks, paced (service/of_pacing.py): the hourly link prewarm pass
(link_metrics.prewarm_all: tracking links, trials, promotions), the lifecycle roster crawl
(subscribers), two passes of the 300 s ledger supervisor (transaction_ingest.supervisor_cycle,
payouts transactions) and a Growth page's claimer refresh (link_metrics.maybe_refresh) run at
once, against OF's own rate limit, while `--users` chatters work half the Creators and their Fan
List fills names in the background.

World: `agency_inbox` (an Agency, its Creators, fans, threads) with a captured session per
Creator (seed/of_sessions.py), so the relay's REAL OFClient talks to lib/of_wire.py (`OF_WIRE`).
OF's side per Creator (lib/sweep_pacing_wire.py, set here): `--set promos=` promotions (350 small,
1,150 medium: the prewarm's 12-page cap is 1,200), `--set subscribers=` active subscribers (500 /
2,400 / 5,000, OF's 50 a page: 48 pages at medium) and `--set transactions=` ledger rows of the
last 6 days (400 / 1,000 / 2,000). Half the Creators are busy (chatters + their Fan List), half
idle. On every idle Creator OF answers one page 429 once whatever the pace: promotions offset 100
("Please allow 2 seconds"), subscribers offset 100 ("... allow 1 seconds"), transactions offset
100 ("Too many requests": no wait named); on the first busy Creator its first background
/users/list ("... allow 1 seconds"). The last idle Creator (TERMINAL) holds a roster mirror from a
crawl 2 h ago (TERMINAL_SNAPSHOT subscriber_snapshot rows, by SQL) and OF answers its subscribers
offset 100 429 TWICE (the first send and the retry). The last busy Creator (GROWTH) has GROWTH_PROMOS
promotions (3 pages: its Promotions page reads them unpaced, as a person's), the first
GROWTH_CLAIMED of them with GROWTH_CLAIMS claimers each (5 claimer pages each: 25 pages, so even
unpaced the refresh outlasts OF's bucket and meets the other walks).

Flow: prewarm_all's spread is compressed to 0 (`POST /__slop/sweep-pacing/knobs`; prod 30 min);
of_pacing.USER_WINDOW_S is the product's 10 s. `--users` chatters (actors/chatter.py) read and answer the busy Creators' threads; every reply is a real
`POST /api/of/v2/chats/{fan}/messages`, a person's OF request. The owner opens GROWTH's Promotions
page (`GET /admin/promotions`: its claimer refresh starts in the background) and, from then on,
GROWTH's tracking-link earnings (`GET /admin/of-tracking-links/earnings`, the Growth page's read)
EARNINGS_N times EARNINGS_EVERY_S apart. GROWTH_SETTLE_S later (OF's bucket refills after the
page's 3 reads), each busy Creator's Fan List fires BURSTS bursts, BURST_EVERY_S apart, of BURST_N
background name lookups at once (`GET /api/of/v2/users/list?view=x`, `X-Priority: background`, as
useChatList / useSubscribeDateFill do) and, from 3 s into each, USER_AT_S lookups of a person's own
(`view=m`, no header: useOFUser); a prewarm pass, every Creator's roster crawl and TX_CYCLES
supervisor passes start (`POST /__slop/sweep-pacing/run`: the production functions); the scenario
waits for all of them, stops the people, waits USER_WINDOW_S (+ IDLE_SLACK_S) and runs the next
prewarm pass.

Checks (names in lib/sweep_pacing_faults.py):
  pages_spaced           per Creator, every background walk GET OF saw (campaigns, trials,
                         promotions, subscribers incl. claimers, transactions), across all its
                         jobs, left >= PAGE_GAP_S after the one before (SPACE_SLACK_S for the wire).
                         GROWTH's Promotions page reads are a person's (not counted).
  retry_once_per_429     every first 429 OF gave a background request (walk page or name-fill
                         lookup) was followed by exactly one request for the SAME page (same
                         query) within RETRY_WINDOW_S, no sooner than OF asked; a retry's 429 by none; every injected
                         429 fired.
  no_429_on_user_reads   zero 429s on a person's reads: every view=m lookup and every Promotions
                         page read reached OF and got 200, and the relay answered each 200.
  prewarm_skips_busy_creators  pass 1 logged one skip per busy Creator (a person's read < 10 s
                         ago) and none for an idle one, sent no prewarm GET for a busy Creator and
                         walked every idle one; pass 2 (everyone idle) skipped none and walked every
                         busy one.
  growth_refresh_walked  the Promotions page answered refreshing; OF saw every claimer page of
                         GROWTH's claimed promotions; link_claimers holds GROWTH_CLAIMS rows each.
  growth_route_not_blocked  every earnings read answered 200 within EARNINGS_MAX_MS, at
                         least one while GROWTH's claimer walk was on OF (between its first and
                         last claimer GET): no walk holds the lock that read takes.
  terminal_429_keeps_mirror  TERMINAL's subscribers offset 100 was sent exactly twice, both 429;
                         its roster crawl failed (an error, never an empty roster); its
                         subscriber_snapshot rows and their newest seen_at are unchanged.
  walk_counts_match      every run ended (TERMINAL's roster crawl with its 429); per Creator,
                         link_meta promo rows == OF's promotions, subscriber_snapshot rows == OF's
                         subscribers (TERMINAL: its mirror), new transactions rows == OF's ledger
                         rows (a failed page never looks empty).
  no_5xx                 no 5xx or transport error on any call, apart from a name-fill lookup
                         whose OF answer stayed 429 after its retry (retry_once_per_429 owns it).
  user_read_p95          the person's lookup p95 <= USER_READ_P95_MS (budget).
  background_lookup_p95  the name fill's lookup p95 <= BACKGROUND_LOOKUP_P95_MS (budget): it is
                         user-triggered, never paced (paced, it measured 11-13 s).
  stock "p95 within 1.25x (+50ms) of the last green run": both lookups (P95_VS_LAST).
Pacing covers OF's API list pages only: CDN, media and /img fetches are not walks here.
Measured, not checked: metric `tx_supervisor`, each supervisor pass's wall time and pages per
Creator (the first fill, then the steady state).

Bypasses (declared):
  - OF's rate limit is a GUESS (lib/sweep_pacing_wire.py), not OF's measured policy: a token bucket
    per Creator across its four list routes (10 deep, 2 a second); an empty one answers 429 with OF's measured body ("Too many
    requests. Please allow 1 seconds"); its injected 429s too. Latency is lib/of_wire.py's 50 ms.
    The people's load is sized to that guess: a person's lookups + the name fill (~0.9/s per busy
    Creator) beside a paced walk (~0.9/s) stay under the refill. of_wire.py is not edited:
    the extension swaps its server's handler class for a subclass (harness side).
  - The jobs' cadences (hourly prewarm_all with its spread, the 30 min lifecycle sweep, the 300 s
    ledger supervisor's sleep) are `POST /__slop/sweep-pacing/run` (lib/sweep_pacing_relay.py),
    which runs the production functions in fresh contexts (no request around them); the spread is
    compressed (above). USER_WINDOW_S, PAGE_GAP_S, JITTER_S and the 429 retry are the product's.
  - The tracking links and trials are of_wire's empty ones; only GROWTH's claimed promotions have
    claimers. A GROWTH /campaigns GET OF saw during an earnings read is that read's (a person's),
    not a walk's. Chatters reach the relay directly (no Next proxy); the Fan List's lookups are httpx
    calls, not a browser.

Break-it-once (verified, not assumed): sweep-unpaced (the scenario's FAULT: no gap, retry kept)
turns pages_spaced and walk_counts_match red: unpaced, a Creator's walks drain its bucket within a
second, the single retry meets a second 429 and the roster crawls fail. A person's lookup can also
meet GROWTH's empty bucket (no_429_on_user_reads, no_5xx), and GROWTH's refresh can lose the race
for the retry (growth_refresh_walked): noise, not targets (red in some runs only, measured). sweep-no-429-retry
(`--fault=`: gap kept, no retry) turns retry_once_per_429, terminal_429_keeps_mirror and
walk_counts_match red. The lookups' p95s and growth_route_not_blocked stay.
"""
from __future__ import annotations

import asyncio
import itertools
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from slop.actors import chatter
from slop.lib.client import Recorder
from slop.lib.procmon import pct
from slop.lib.sweep_pacing_faults import (BG_P95, COUNTS, GROWTH, GROWTH_ROUTE, NO_429_USER, NO_5XX,
                                          PAGES_SPACED, RETRY_ONCE, SKIPS, TERMINAL, USER_P95)
from slop.lib.sweep_pacing_wire import TOO_MANY, SweepWire
from slop.seed import of_sessions, ts

sys.path.append(str(Path(__file__).resolve().parents[2] / "service"))   # a stdlib leaf: the pace itself
from of_pacing import JITTER_S, PAGE_GAP_S  # noqa: E402

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "sweep-unpaced"
KNOBS = {"PREWARM_SPREAD_S": 0.0}
IDLE_SLACK_S = 1.0           # past USER_WINDOW_S before pass 2: every Creator idle
SPACE_SLACK_S = 0.1          # a GET's send-to-arrival time varies by a few ms under load
RETRY_SLACK_S = 0.1
RETRY_WINDOW_S = 15.0        # a retry leaves within OF's wait (<= 10 s) + a pacer turn; later = another walk
BURSTS, BURST_N, BURST_EVERY_S = 6, 8, 15.0
USER_AT_S = tuple(round(3.0 + 1.6 * k, 1) for k in range(5))   # a person's lookups, into each burst
GROWTH_SETTLE_S = 2.5        # after GROWTH's Promotions page (3 reads), before the first burst (8)
EARNINGS_N, EARNINGS_EVERY_S, EARNINGS_MAX_MS = 24, 0.5, 2_000
TX_CYCLES = 2
GROWTH_PROMOS, GROWTH_CLAIMED, GROWTH_CLAIMS = 250, 5, 100
TERMINAL_SNAPSHOT = 120
RUN_TIMEOUT_S = 900
USER_READ_P95_MS = 1_000     # measured 66-68 ms small / 20 users, 99-635 ms medium / 200 users
BACKGROUND_LOOKUP_P95_MS = 3_000   # one OF wait (1 s) + the retry; paced at the route it was 11-13 s
P95_VS_LAST = (1.25, 50)
P95_VS_LAST_MIN_N = 10
# A walk OF cut short with a 429 logs its failure with the traceback.
EXPECTED_TRACEBACKS = tuple((m, '"code": 429') for m in (
    "OF fetch failed", "ingest_tx_scan failed", "ingest_tx_scan_failed", "ingest_tx_backfill failed",
    "link_metrics refresh failed", "link_metrics prewarm failed"))
WALK_ROUTES = ("campaigns", "trials", "promotions", "subscribers", "transactions")
PREWARM_ROUTES = ("campaigns", "trials", "promotions")
_SKIP = re.compile(r"bg_walk_skip account=(\S+) kind=link_prewarm")
_ALLOW = re.compile(r"allow\s+(\d+(?:\.\d+)?)\s*sec", re.I)


def _asked(text: str | None) -> float:
    m = _ALLOW.search(text or "")
    return float(m.group(1)) if m else 1.0


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")   # OF's timestamps


def _seed_of(sw: SweepWire, w, aids: list[str], n_promo: dict[str, int], n_sub: int, n_tx: int,
             growth: str) -> None:
    """OF's side, deterministic from the world's seed."""
    rng = w.rng("scenario:sweep-pacing:of")
    fans = w.data["fans"]
    for i, a in enumerate(aids):
        base = 10_000_000_000 + i * 1_000_000
        n = n_promo[a]
        sw.promos[a] = [{"id": base + k, "message": f"slop promo {k}", "price": 4.99, "type": "all",
                         "claimsCount": GROWTH_CLAIMS if a == growth and k < GROWTH_CLAIMED else 0,
                         "subscribeCounts": 10, "subscribeDays": 0,
                         "createdAt": _iso(w.now - timedelta(days=n - k)), "finishedAt": None,
                         "isFinished": True, "canClaim": False} for k in range(n)]
        ids = [f["id"] for f in fans[a]]
        ids += [base + 500_000 + k for k in range(max(0, n_sub - len(ids)))]
        sw.subs[a] = [{"id": fid, "name": f"Fan {fid}", "username": f"u{fid}",
                       "subscribedOnData": {"status": "Active" if rng.random() < 0.7 else "Cancelled",
                                            "subscribeAt": _iso(w.now - timedelta(days=rng.randint(1, 300))),
                                            "expiredAt": _iso(w.now + timedelta(days=rng.randint(1, 30))),
                                            "renewedAt": None}} for fid in ids[:n_sub]]
        if a == growth:
            for k in range(GROWTH_CLAIMED):
                sw.claims[(a, base + k)] = [
                    {"id": base + 700_000 + k * 1_000 + j, "name": f"Claimer {j}", "username": f"c{k}_{j}",
                     "subscribedOnData": {"subscribeAt": _iso(w.now - timedelta(days=j + 1))}}
                    for j in range(GROWTH_CLAIMS)]
        rows = []
        for k in range(n_tx):
            fan = rng.choice(ids)
            cents = rng.randint(5, 50) * 100
            at = w.now - timedelta(minutes=1 + k * 6 * 24 * 60 // max(n_tx, 1))
            rows.append({"id": base + 900_000 + k, "user": {"id": fan}, "amount": cents / 100, "currency": "USD",
                         "createdAt": _iso(at), "status": "done",
                         "net": cents * 0.8 / 100, "fee": cents * 0.2 / 100, "vatAmount": 0,
                         "description": f"Tip from u{fan}"})
        sw.txs[a] = rows   # newest first


def _seed_mirror(w, aid: str, fans: list[dict]) -> str:
    """TERMINAL's roster as a complete crawl 2 h ago wrote it (subscriber_snapshot). Its seen_at."""
    seen = ts(w.now - timedelta(hours=2))
    con = w.sql()
    con.executemany(
        "INSERT INTO subscriber_snapshot (account_id, fan_id, subscribe_at, expired_at, renew_on, seen_at,"
        " resubscribed_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
        [(aid, int(f["id"]), ts(w.now - timedelta(days=30)), ts(w.now + timedelta(days=5)), 1, seen)
         for f in fans[:TERMINAL_SNAPSHOT]])
    con.commit()
    con.close()
    return seen


def _snapshot(w, aid: str) -> tuple[int, str | None]:
    con = w.sql()
    n, last = con.execute("SELECT COUNT(*), MAX(seen_at) FROM subscriber_snapshot WHERE account_id = ?",
                          (aid,)).fetchone()
    con.close()
    return n, last


async def run(ctx) -> None:  # noqa: C901  one flow, its checks in order
    w = await ctx.build(PROFILE)
    aids = [c["id"] for c in w.data["creators"]]
    of_sessions.seed(w, w.data["creators"])
    busy, idle = aids[::2], aids[1::2]
    growth, terminal = busy[-1], idle[-1]
    n_promo_all = int(ctx.param("promos", w.size["sweep_pacing_promos"]))
    n_promo = {a: GROWTH_PROMOS if a == growth else n_promo_all for a in aids}
    n_sub = int(ctx.param("subscribers", w.size["sweep_pacing_subscribers"]))
    n_tx = int(ctx.param("transactions", w.size["sweep_pacing_transactions"]))
    fake = ctx.of_wire
    sw = SweepWire(fake)
    _seed_of(sw, w, aids, n_promo, n_sub, n_tx, growth)
    for a in idle:
        sw.inject[(a, "promotions")] = {"offset": 100, "text": "Too many requests. Please allow 2 seconds"}
        sw.inject[(a, "subscribers")] = {"offset": 100, "text": TOO_MANY}
        sw.inject[(a, "transactions")] = {"offset": 100, "text": "Too many requests"}
    sw.inject[(terminal, "subscribers")] = {"offset": 100, "text": TOO_MANY, "times": 2}
    sw.inject[(busy[0], "users_list")] = {"offset": 0, "view": "x", "text": TOO_MANY}
    sw.install()
    mirror_seen = _seed_mirror(w, terminal, sw.subs[terminal])
    mirror0 = _snapshot(w, terminal)
    con = w.sql()
    tx0 = dict(con.execute("SELECT account_id, COUNT(*) FROM transactions GROUP BY account_id").fetchall())
    con.close()
    ctx.metric("world", {"creators": len(aids), "busy": busy, "idle": idle, "growth": growth, "terminal": terminal,
                         "promos": n_promo_all, "subscribers": n_sub, "transactions": n_tx, "users": ctx.users})

    r = await ctx.owner.post("/__slop/sweep-pacing/knobs", json=KNOBS)
    r.raise_for_status()
    knobs = r.json()
    gap, jitter = PAGE_GAP_S, JITTER_S

    # ── people on the busy Creators ─────────────────────────────────────────
    ur, br = Recorder(), Recorder()            # a person's lookups / the Fan List's background ones
    users_http, bg_http = ctx.owner.share(rec=ur, limits=50), ctx.owner.share(rec=br, limits=100)
    look_ids = itertools.count(20_000_000_000)
    lookups: list[dict] = []

    async def lookup(a: str, background: bool) -> None:
        ids = [next(look_ids) for _ in range(10)]
        hdr = {"X-Account-Id": a, **({"X-Priority": "background"} if background else {})}
        q = "&".join(f"ids={i}" for i in ids) + f"&view={'x' if background else 'm'}"
        t0 = time.perf_counter()
        try:
            st = (await (bg_http if background else users_http).get(f"/api/of/v2/users/list?{q}", headers=hdr)).status_code
        except Exception:  # noqa: BLE001  recorded as 599 by the client
            st = 599
        lookups.append({"account": a, "background": background, "status": st, "t": time.time(),
                        "ms": (time.perf_counter() - t0) * 1000})

    await asyncio.gather(*(lookup(a, False) for a in busy))   # the busy Creators are busy before any walk
    chat_http = ctx.owner.share(limits=max(10, ctx.users))
    chatters = chatter.Chatters({a: chat_http for a in busy}, {a: 1.0 for a in busy},
                                w.rng("scenario:sweep-pacing:chatters"))
    chatters.start(max(1, ctx.users))

    async def fan_list(a: str) -> None:
        for _ in range(BURSTS):
            t0 = time.monotonic()

            async def person(d: float) -> None:
                await asyncio.sleep(d)
                await lookup(a, False)

            await asyncio.gather(*(lookup(a, True) for _ in range(BURST_N)), *(person(d) for d in USER_AT_S))
            await asyncio.sleep(max(0.0, BURST_EVERY_S - (time.monotonic() - t0)))

    # ── every walk at once ──────────────────────────────────────────────────
    earn_http = ctx.owner.share(limits=4)
    earnings: list[dict] = []

    async def earnings_reads() -> None:   # the Growth page's read, while GROWTH's claimer walk runs
        for _ in range(EARNINGS_N):
            t0 = time.time()
            try:
                st = (await earn_http.get(f"/admin/of-tracking-links/earnings?account_id={growth}")).status_code
            except Exception:  # noqa: BLE001  recorded as 599 by the client
                st = 599
            t1 = time.time()
            earnings.append({"t0": t0, "t1": t1, "status": st, "ms": round((t1 - t0) * 1000, 1)})
            await asyncio.sleep(max(0.0, EARNINGS_EVERY_S - (t1 - t0)))

    ctx.rec.stage = "walks"
    t_walks = time.time()
    gr = await ctx.owner.get(f"/admin/promotions?account_id={growth}")   # its claimer refresh starts
    t_growth = time.time()
    growth_page = {"status": gr.status_code, **({k: gr.json().get(k) for k in ("of_available", "metrics_refreshing")}
                                                if gr.status_code == 200 else {})}
    earn = asyncio.ensure_future(earnings_reads())
    await asyncio.sleep(GROWTH_SETTLE_S)
    bursts = asyncio.gather(*(fan_list(a) for a in busy))
    for job, extra in (("link_prewarm", {}), ("subscribers", {"account_ids": aids}), ("tx_cycles", {"cycles": TX_CYCLES})):
        (await ctx.owner.post("/__slop/sweep-pacing/run", json={"job": job, **extra})).raise_for_status()
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while True:
        got = (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()
        if all(x["t1"] for x in got["runs"]) or time.monotonic() > deadline:
            break
        await asyncio.sleep(0.5)
    walls = time.time() - t_walks
    await bursts
    await earn
    await chatters.stop()
    # ── pass 2: everyone idle past the window, the next prewarm pass walks the skipped ──────────
    await asyncio.sleep(knobs["USER_WINDOW_S"] + IDLE_SLACK_S)
    (await ctx.owner.post("/__slop/sweep-pacing/run", json={"job": "link_prewarm"})).raise_for_status()
    while True:
        got = (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()
        if all(x["t1"] for x in got["runs"]) or time.monotonic() > deadline:
            break
        await asyncio.sleep(0.5)
    timed_out = time.monotonic() > deadline
    ctx.rec.stage = None
    for h in (users_http, bg_http, chat_http, earn_http):
        await h.aclose()
    runs, plog = got["runs"], got["log"]
    log = [e for e in sw.snapshot() if e["t"] >= t_walks - 5]

    def person_read(e) -> bool:   # GROWTH's Promotions page / an earnings read: their own OF reads, unpaced
        if e["account"] != growth:
            return False
        if e["route"] == "promotions":
            return t_walks <= e["t"] <= t_growth
        return e["route"] == "campaigns" and any(x["t0"] <= e["t"] <= x["t1"] for x in earnings)

    def walk_get(e) -> bool:
        return e["route"] in WALK_ROUTES and not person_read(e)

    def bg(e) -> bool:
        return walk_get(e) or (e["route"] == "users_list" and e["view"] == "x")

    # ── pages_spaced ────────────────────────────────────────────────────────
    per: dict[str, list[dict]] = defaultdict(list)
    for e in log:
        if walk_get(e):
            per[e["account"]].append(e)
    floor = gap - SPACE_SLACK_S
    space = {}
    for a in aids:
        ts_ = sorted(e["t"] for e in per[a])
        gaps = [b - x for x, b in zip(ts_, ts_[1:])]
        space[a] = {"gets": len(ts_), "min_gap_s": round(min(gaps), 3) if gaps else None,
                    "under": sum(1 for g in gaps if g < floor)}
    ctx.check(PAGES_SPACED, all(space[a]["gets"] > 1 and space[a]["under"] == 0 for a in aids),
              page_gap_s=gap, floor_s=round(floor, 3), relay_knobs=knobs, per_creator=space)

    # ── retry_once_per_429 ──────────────────────────────────────────────────
    same: dict[tuple, list[dict]] = defaultdict(list)
    for e in log:
        if bg(e):
            same[(e["account"], e["route"], e["query"])].append(e)
    bad_retry, n429, terminal_429s = [], 0, 0
    for e in log:
        if e["status"] != 429 or not bg(e):
            continue
        n429 += 1
        page = same[(e["account"], e["route"], e["query"])]
        before = [x for x in page if x["t"] < e["t"]]
        nxt = [x for x in page if e["t"] < x["t"] <= e["t"] + RETRY_WINDOW_S]
        if before and before[-1]["status"] == 429:   # this is the retry: OF's second 429 ends the page
            terminal_429s += 1
            ok = not nxt
        else:
            ok = len(nxt) == 1 and nxt[0]["t"] >= e["t"] + _asked(e["asked"]) - RETRY_SLACK_S
        if not ok:
            bad_retry.append({"account": e["account"], "route": e["route"], "offset": e["offset"],
                              "asked_s": _asked(e["asked"]),
                              "after": [(x["status"], round(x["t"] - e["t"], 2)) for x in nxt][:3]})
    unfired = [f"{a} {r_}" for (a, r_), v in sw.inject.items() if not v.get("done")]
    ctx.check(RETRY_ONCE, n429 > 0 and not bad_retry and not unfired, of_429s=n429, retry_429s=terminal_429s,
              wrong=len(bad_retry), e_g=bad_retry[:5], injected=len(sw.inject), unfired=unfired)

    # ── no_429_on_user_reads ────────────────────────────────────────────────
    user_of = [e for e in log if e["route"] == "users_list" and e["view"] == "m"]
    user_relay = [x for x in lookups if not x["background"]]
    page_of = [e for e in log if person_read(e) and e["route"] == "promotions"]
    of_bad = Counter((e["route"], e["status"]) for e in user_of + page_of if e["status"] != 200)
    relay_bad = sum(1 for x in user_relay if x["status"] != 200)
    why = [{"account": e["account"], "route": e["route"], "t": round(e["t"] - t_walks, 2), "tokens": e.get("tokens")}
           for e in user_of + page_of if e["status"] != 200]
    ctx.check(NO_429_USER, bool(user_of) and len(user_of) == len(user_relay) and bool(page_of) and not of_bad
              and relay_bad == 0 and growth_page.get("status") == 200,
              of_saw=len(user_of), asked=len(user_relay), page_reads=len(page_of),
              of_not_200={f"{r} {st}": n for (r, st), n in of_bad.items()}, relay_not_200=relay_bad, e_g=why[:4])

    # ── prewarm_skips_busy_creators ─────────────────────────────────────────
    passes = [x for x in runs if x["job"] == "link_prewarm"]
    def in_pass(t, x) -> bool:
        return x["t0"] <= t <= (x["t1"] or float("inf"))

    def skips(x) -> Counter:
        return Counter(m.group(1) for y in plog if in_pass(y["t"], x) and (m := _SKIP.search(y["msg"])))

    def prewarm_gets(x, a) -> int:
        return sum(1 for e in per[a] if e["route"] in PREWARM_ROUTES and in_pass(e["t"], x))
    sk = {}
    if len(passes) == 2:
        p1, p2 = passes
        s1, s2 = skips(p1), skips(p2)
        sk = {
            "pass1_busy_not_skipped_once": [a for a in busy if s1.get(a) != 1],
            "pass1_idle_skipped": sorted(a for a in s1 if a in idle),
            "pass1_busy_walked": {a: n for a in busy if (n := prewarm_gets(p1, a))},
            "pass1_idle_not_walked": [a for a in idle if not prewarm_gets(p1, a)],
            "pass2_skipped": sorted(s2),
            "pass2_busy_not_walked": [a for a in busy if not prewarm_gets(p2, a)],
        }
    ctx.check(SKIPS, len(passes) == 2 and bool(busy) and not any(sk.values()), passes=len(passes), **sk,
              pass_s=[round(x["t1"] - x["t0"], 1) if x["t1"] else None for x in passes])

    # ── growth_refresh_walked ───────────────────────────────────────────────
    claimed = [p["id"] for p in sw.promos[growth] if p["claimsCount"]]
    claim_gets = Counter()
    for e in per[growth]:
        m = re.search(r"filter%5BpromoId%5D=(\d+)|filter\[promoId\]=(\d+)", e["query"])
        if e["route"] == "subscribers" and m:
            claim_gets[int(m.group(1) or m.group(2))] += 1
    con = w.sql()
    rows = dict(con.execute("SELECT of_id, COUNT(*) FROM link_claimers WHERE account_id = ? AND kind = 'promo'"
                            " GROUP BY of_id", (growth,)).fetchall())
    con.close()
    pages_each = -(-GROWTH_CLAIMS // 20)
    gw = {p: {"of_gets": claim_gets.get(p, 0), "rows": rows.get(p, 0)} for p in claimed}
    ctx.check(GROWTH, growth_page.get("status") == 200 and growth_page.get("metrics_refreshing") is True
              and all(v["of_gets"] >= pages_each and v["rows"] == GROWTH_CLAIMS for v in gw.values()),
              page=growth_page, pages_each=pages_each, per_promo=gw)

    # ── growth_route_not_blocked ────────────────────────────────────────────
    cts = sorted(e["t"] for e in per[growth] if e["route"] == "subscribers" and "filter" in e["query"])
    walk_span = (cts[0], cts[-1]) if cts else None
    during = [x for x in earnings if walk_span and x["t0"] < walk_span[1] and x["t1"] > walk_span[0]]
    slow_e = [x for x in earnings if x["status"] != 200 or x["ms"] > EARNINGS_MAX_MS]
    ctx.check(GROWTH_ROUTE, len(earnings) == EARNINGS_N and not slow_e and bool(during),
              reads=len(earnings), during_walk=len(during), claimer_pages=len(cts),
              walk_s=round(walk_span[1] - walk_span[0], 1) if walk_span else None, budget_ms=EARNINGS_MAX_MS,
              max_ms=max((x["ms"] for x in earnings), default=None),
              max_ms_during_walk=max((x["ms"] for x in during), default=None),
              p50_ms=pct([x["ms"] for x in earnings], 0.5) if earnings else None,
              not_ok=[(x["status"], x["ms"], round(x["t0"] - t_walks, 1)) for x in slow_e][:5])

    # ── terminal_429_keeps_mirror ───────────────────────────────────────────
    tpage = [e for e in log if e["account"] == terminal and e["route"] == "subscribers" and e["offset"] == 100
             and "filter" not in e["query"]]
    trun = [x for x in runs if x["job"] == "subscribers" and x["account"] == terminal]
    mirror1 = _snapshot(w, terminal)
    ctx.check(TERMINAL, [e["status"] for e in tpage] == [429, 429] and len(trun) == 1
              and bool(trun[0]["error"]) and "429" in (trun[0]["error"] or "") and mirror1 == mirror0,
              sends=[(e["status"], round(e["t"] - tpage[0]["t"], 2)) for e in tpage], run=trun[:1],
              mirror_before=mirror0, mirror_after=mirror1, seeded_seen_at=mirror_seen)

    # ── walk_counts_match ───────────────────────────────────────────────────
    con = w.sql()
    meta = dict(con.execute("SELECT account_id, COUNT(*) FROM link_meta WHERE kind='promo' GROUP BY account_id"))
    snap = dict(con.execute("SELECT account_id, COUNT(*) FROM subscriber_snapshot GROUP BY account_id"))
    tx1 = dict(con.execute("SELECT account_id, COUNT(*) FROM transactions GROUP BY account_id"))
    con.close()
    errs = [{k: x[k] for k in ("job", "account", "error")} for x in runs
            if (x["error"] and not (x["job"] == "subscribers" and x["account"] == terminal))
            or (x["job"] == "subscribers" and x["account"] != terminal
                and (x["result"] or {}).get("roster") != "crawled")]
    cnt_bad = {}
    for a in aids:
        got_ = {"promos": meta.get(a, 0), "subscribers": snap.get(a, 0), "transactions": tx1.get(a, 0) - tx0.get(a, 0)}
        want = {"promos": n_promo[a], "subscribers": mirror0[0] if a == terminal else n_sub, "transactions": n_tx}
        if got_ != want:
            cnt_bad[a] = {"got": got_, "want": want}
    ctx.check(COUNTS, not errs and not cnt_bad and not timed_out and len(runs) == 3 + len(aids),
              runs=len(runs), failed=errs[:6], n_failed=len(errs), wrong=cnt_bad, timed_out=timed_out)

    # ── no_5xx ──────────────────────────────────────────────────────────────
    lost = sum(1 for k, page in same.items() if k[1] == "users_list" and page[-1]["status"] == 429)
    look5 = sum(1 for x in lookups if x["status"] >= 500)
    other5 = {k: v["5xx"] for rec in (ctx.rec,) for k, v in rec.summary().items() if v["5xx"]}
    ctx.check(NO_5XX, not other5 and look5 <= lost and not any(x["status"] == 599 for x in lookups),
              other_5xx=other5, lookup_5xx=look5, lookups_left_429=lost, chatter_actions=chatters.actions)

    # ── user_read_p95 / background_lookup_p95 ───────────────────────────────
    lat = [x["ms"] for x in user_relay if x["status"] == 200]
    p95 = pct(lat)
    ctx.check(USER_P95, p95 is not None and p95 <= USER_READ_P95_MS, budget=True,
              p95_ms=p95, n=len(lat), budget_ms=USER_READ_P95_MS)
    bgl = [x["ms"] for x in lookups if x["background"]]
    bg95 = pct(bgl)
    ctx.check(BG_P95, bg95 is not None and bg95 <= BACKGROUND_LOOKUP_P95_MS, budget=True,
              p95_ms=bg95, n=len(bgl), budget_ms=BACKGROUND_LOOKUP_P95_MS,
              not_200=dict(Counter(x["status"] for x in lookups if x["background"] and x["status"] != 200)))
    ctx.metric("p95_vs_last_green", {"user lookup": p95, "background lookup": bg95})
    ctx.metric("p95_vs_last_green_n", {"user lookup": len(lat), "background lookup": len(bgl)})

    # ── the ledger supervisor's passes (measured) ───────────────────────────
    txrun = next((x for x in runs if x["job"] == "tx_cycles"), None)
    cycles = ((txrun or {}).get("result") or {}).get("cycles") or []
    sup = []
    for i, c in enumerate(cycles):
        pages = Counter(e["account"] for e in log if e["route"] == "transactions" and c["t0"] <= e["t"] <= c["t1"])
        sup.append({"pass": i + 1, "wall_s": round(c["t1"] - c["t0"], 1), "creators": len(pages),
                    "pages_per_creator": sorted(pages.values()), "pages": sum(pages.values())})
    ctx.metric("tx_supervisor", sup)
    slow = sorted((x for x in user_relay if p95 is not None and x["ms"] >= p95), key=lambda x: x["t"])
    ctx.metric("user_lookups_at_or_over_p95", [{"s_into_walks": round(x["t"] - t_walks, 1), "ms": round(x["ms"]),
                                               "account": x["account"]} for x in slow])
    ctx.metric("walks", {"wall_s": round(walls, 1), "of_gets": len(log), "of_429": n429,
                         "background_lookup_p95_ms": bg95,
                         "runs": [{k: x[k] for k in ("job", "account", "error")} |
                                  {"s": round(x["t1"] - x["t0"], 1) if x["t1"] else None} for x in runs]})
    ctx.note(f"{len(aids)} Creators ({len(busy)} busy), walls {walls:.0f} s, {len(log)} list GETs at OF, "
             f"{n429} 429s, user lookup p95 {p95} ms over {len(lat)}, background lookup p95 {bg95} ms over "
             f"{len(bgl)}, {sum(chatters.actions.values())} chatter actions",
             *(f"ledger supervisor pass {s['pass']}: {s['wall_s']} s, {s['pages']} pages over {s['creators']} "
               f"Creators ({s['pages_per_creator']})" for s in sup))
