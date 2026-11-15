"""View lease and purchases poll tiers (phase-01 1a, ADR-0031): the 30 s purchases loop polls a Creator every
PURCHASES_POLL_FAST_S while a tab leases it (`POST /admin/view-lease`) or it has an enabled Seller, every
PURCHASES_POLL_SLOW_S otherwise, whoever is signed in; a renewal that newly leases a Creator, or changes a
tab's `selected`, reads its feed at once (the Select refresh).

World: `flat_agency` with CREATORS[scale] Creators (10 small, 50 medium), each with a captured session (the
relay's REAL OFClient against lib/of_wire.py, `OF_WIRE`), the owner made admin by SQL (as an operator does).
Creators by role, k = max(1, n // 10) each (a Seller kind at least enough for three Seller Creators): Seller rules
by SQL (SELLER_KINDS, enabled), each leg's IDLE_RULES roles (Idle), OWNER (the owner's tabs lease them), CHATTER (a
chatter whose Employee setup is OWNER + CHATTER + IDLE leases them), ALL_ON (the on-screen rows of an
All-view chatter, `selected` null, whose setup is ALL_ON + ALL_OFF), ALL_OFF, one GAIN Creator (leased later),
the rest IDLE. Each Idle Creator (IDLE_RULES' too) has one seeded PPV purchase: an unpaid priced outbound
message (SQL) and its notification in OF's `type=purchases` feed (`FakeOF.purchases`).

Legs (`--set leg=latency` runs only the UI one, with the no-5xx check; `--set leg=warm` the App-open warm alone;
`--set leg=visible` the on-screen lease alone, `--set leg=dm` the plain-DM leg alone; `--set leg=rail` the out-of-scope
rail alone):
  warm     (first: the loop is not running yet, so every feed read is the warm's or a Select refresh's) WARM_PX fake
           proxies of WARM_PER_PX Creators each (lib/sweep_pacing_proxy.bind, the product's own routes), the rest
           direct; an httpx owner tab leases the last Creator of each group and waits FAST_S + 1 s (their Select
           refresh ages out). The owner's Chromium (no /api/of/ read let through) opens WARM_PAGE (Settings) first,
           its saved scope (localStorage `chatterly:scope`) one unleased Creator of the first proxy: its heartbeat's
           `opened: true` post carries it `selected` (its Select refresh; the warm skips its feed and starts that proxy
           one GAP late) and warms every Creator's read set (lib/view_lease_rail_scope.py), WARM_SENDS sends go out
           meanwhile; settled, the pass-through routes read it all back (httpx, as a tab); then, the scope back to
           All, Messages Pro (a second document load inside APP_OPEN_WARM_REUSE_S: `reused`, no read); then two
           Creator-tab clicks (an OWNER and a CHATTER Creator, both leased in tiers anyway), each a selection post.
           Its strip's tabs, warmed within REUSE_S, get no lease-gain read (ticket 20); a selection post on a tab
           leased at the click joins no read in flight (`read_joined` false), one its scroll brought on screen may.
           Screenshots `warm-trigger-settings` (just opened), `warm-settled-settings`, `warm-mp-selected`; the
           page's own view-lease posts and answers and the per-Creator feed reads in `app-open-warm.json`.
  rail     (ticket 23, lib/view_lease_rail_scope.py) the warm aged out, the owner's Messages Pro scoped to one Creator
           opens (a fresh warm); an Idle Creator's tip shows in its rail from SSE; the tab's money-list and count
           reads hit OF only for the Creators it leases.
  tiers    the loop starts (`POST /__slop/fast-poll`); P1_S with no client (Sellers alone); then P2_S with
           max(1, users // 3) tabs per lease role renewing every RENEW_S, the owner and the chatters signed in;
           inside P2 (each right after a loop cycle, so a read within 2 s is not the loop's): the owner's tab 0
           adds GAIN, then selects a CHATTER Creator (already leased by the chatter); the owner sends SENDS texts
           (`POST /api/of/v2/chats/{fan}/messages`) over OWNER and IDLE Creators, and JOBS seeded `scrape_chats`
           jobs run through `/__slop/automation-tick`. Then feed health (ticket 21, the loop still running; `_health`):
           an owner tab leases an OWNER, a CHATTER and an ALL_ON Creator (healthy: the cycle clock); for P3_S OF
           answers the feed (lib/of_wire.py `status`) 429 Retry-After RA_SHORT to a Seller Creator, 429 with
           OF's own "Please allow 1 seconds" body (`TOO_MANY_BODY`) to a second, a plain 401 to a third, 429
           Retry-After RA_LONG (over the cap) to the OWNER one, and asks the CHATTER one for a 2FA code (`otp`: a Dead session); right after an IDLE Creator's poll, CATCHUP_N purchases land on
           its feed inside one slow gap (SQL + `FakeOF.purchases`, CATCHUP_BATCHES batches CATCHUP_EVERY_S apart);
           one `/__slop/automation-tick` (the recovery probe), then the CHATTER Creator is re-captured
           (`POST /admin/session/bootstrap`, paste-curl). Then each leg's `run` (LEGS; its module docstring).
  dm       (1b story 52, lib/view_lease_dm_bust.py) an ALL_OFF Creator's money reads through the relay (the rail's
           purchases and tip lists, the bell's count), PLAIN_N plain DMs at the pump boundary, each followed by the same
           reads, then a tip DM and the reads: OF calls per stage. Evidence `dm-no-bust.json`.
  visible  (ticket 20, lib/view_lease_visible.py) the owner's pages in Chromium in the All view post exactly the
           on-screen Creators (strip + rail + open chat + OF Manager's column).
  latency  the owner's Messages Pro in Chromium (`/messages-pro`, the rail's and the strip's reads let through to
           the relay and fake OF): CLICKS Creator-tab clicks, each timed to settled (the tab selected and no
           /admin/ or let-through /api/of/ read in flight for IDLE_MS); p95 `click_settled_ms`. Screenshots
           `trigger-strip` (before the first click) and `settled-strip` (after the last).

Checks (names in lib/view_lease_faults.py): WARM_ONCE (each read-set read once, the pass-through reads no OF
call), RAIL_OUT_OF_SCOPE_LIVE and RAIL_LEASED_ONLY (the rail leg), WARM_STAGGER (the warm leg; same-proxy read starts >= GAP -
WARM_GAP_SLACK_S apart, the selected Creator's Select refresh first on its proxy, then the leased one, the groups'
first reads within GAP of each other), LEASED_FAST,
SELLER_FAST, IDLE_SLOW, ALL_VIEW_NO_LEASE, SELECT_REFRESH (with the warm leg: also the browser's two selection
posts), FAN_WRITES_KEPT (with the warm leg: its sends kept, their p95 within SEND_VS_NO_WARM of the tiers leg's,
which run with no warm), BACKOFF_429 / UNAUTH_NOT_DEAD (the hold the longer of OF's asked wait and the rung; each
failing poll's gap, from OF's answer to the next call's arrival, at least its hold capped at the Demand cap (less
LO_SLACK_S), at most a cycle more, the loop's period measured on a third leased Creator, plus GAP_SLACK_S, never
past the Demand cap plus CAP_SLACK_S),
DEAD_SILENT, DEAD_RESUME (a feed read within 1.5 x FAST_S + 1 s of the re-capture), UI_LEASE_VISIBLE (the visible
leg), FEED_CATCHUP (all CATCHUP_N flipped, inside one slow gap while the Creator is slow; evidence `feed-health.json`),
DM_NO_BUST (the dm leg: no OF read after a plain DM, one per read after the tip, all inside the pass-through's
TTL), each leg's own, CLICK_SETTLED; p95 vs the last green
run (P95_VS_LAST) of
`POST /admin/view-lease`, `GET /admin/accounts/roster-counts` (the rail leg's owner polls) and `click_settled_ms`. A purchases poll is a fake-OF call on `GET
/api2/v2/users/notifications` with `type=purchases` (not at the rail's page size: lib/view_lease_feed.is_feed); gaps are between consecutive calls per Creator.
Evidence `view-lease.json`.

Bypasses (declared): OF at its wire (lib/of_wire.py, 50 ms a call, a guess); time: the Knobs scaled at stack
start (RELAY_ENV: FAST 5 s, SLOW 20 s, TTL 6 s, the Backoff ladder 5 -> 40 s capped at 20 s; prod 30 / 300 / 60, 30 ->
900 capped at 120; the loop's 5 s minimum cycle gap is why FAST
is not lower) and the loop started on request (lib/view_lease_relay.py) with no boot grace; the admin flag and
Seller rules by SQL; the registry
read through `GET /__slop/view-lease` (read-only); the supervisor's cadence (`/__slop/automation-tick`). The tiers'
lease tabs are httpx clients naming their subsets (the browser's own lease sources are the warm, visible and latency
legs'). The warm leg's Next routes are compiled by one plain GET each first (dev server), so the reuse window measures
the relay, not a compile. The visible and dm legs': their modules'.
Break-it-once: `admin-online-all-fast` (the FAULT: the old admin branch): only IDLE_SLOW. `seller-kinds-old`:
only SELLER_FAST. `all-view-leases-every-creator`: only ALL_VIEW_NO_LEASE. `select-refresh-on-gain-only`: only
SELECT_REFRESH. `warm-messages-pro-only` (browser: `opened` only on /messages-pro): only WARM_ONCE.
`warm-unstaggered` (every Creator its own group, no gap): only WARM_STAGGER. `feed-429-ignored` (a 429 changes
nothing): only BACKOFF_429. `dead-still-polled` (the live set without the dead filter): only DEAD_SILENT.
`dead-held-in-poll-state` (`dead` a hold nothing clears): only DEAD_RESUME. `feed-no-catchup` (newest page only):
only FEED_CATCHUP.
`strip-leases-all-tabs` (browser: the strip leases every open tab): only UI_LEASE_VISIBLE. `dm-busts-money-feeds`
(every inbound DM clears the money feeds): only DM_NO_BUST. `money-events-scope-only` (the pre-1b routing: scope
only): only RAIL_OUT_OF_SCOPE_LIVE.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import re
import statistics
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from slop.lib import of_call_stats, of_wire, sweep_pacing_proxy, view_lease_dm_bust, view_lease_visible
from slop.lib import view_lease_rail_scope as rail_scope
from slop.lib.client import Http
from slop.lib.browserbase import paste_curl
from slop.lib.view_lease_faults import (ALL_VIEW_NO_LEASE, BACKOFF_429, CLICK_SETTLED, DEAD_RESUME, DEAD_SILENT,
                                        FAN_WRITES_KEPT, FEED_CATCHUP, IDLE_SLOW, LEASED_FAST, SELECT_REFRESH,
                                        SELLER_FAST, UNAUTH_NOT_DEAD, WARM_ONCE, WARM_STAGGER)
from slop.lib.view_lease_feed import POLL_ROUTE, is_feed, next_poll
from slop.lib.view_lease_feed import feed as _feed
from slop.lib.view_lease_feed import until as _until
from slop.seed import chatters as chatter_seed
from slop.seed import ppv_purchases
from slop.seed import ts

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = "admin-online-all-fast"
CREATORS = {"small": 10, "medium": 50, "huge": 50}
FAST_S, SLOW_S, TTL_S = 5.0, 20.0, 6.0
RENEW_S = 2.0                # app VIEW_LEASE_RENEW_MS (20 s) scaled as TTL
RELAY_ENV = {"PURCHASES_POLL_FAST_S": str(FAST_S), "PURCHASES_POLL_SLOW_S": str(SLOW_S),
             "VIEW_LEASE_TTL_S": str(TTL_S), "INGEST_FAST_BOOT_GRACE_S": "0", "OF_CALL_STATS_FLUSH_S": "1",
             "PURCHASES_BACKOFF_BASE_S": "5", "PURCHASES_BACKOFF_MAX_S": "40", "PURCHASES_BACKOFF_DEMAND_MAX_S": "20"}
# Feed health (ticket 21): the Backoff ladder scaled as the poll Knobs (prod 30 / 900 / 120 s).
BACKOFF_BASE_S, BACKOFF_MAX_S, BACKOFF_DEMAND_MAX_S = 5.0, 40.0, 20.0
RA_SHORT, RA_LONG = 12.0, 60.0   # OF's Retry-After: under the Demand cap, and over it (the cap wins)
P3_S = 62.0                      # the 429 / 401 / dead window
GAP_SLACK_S = 2.5                # a cycle's 0.2 s starts stagger (10 Creators) + the cycle drift
CAP_SLACK_S = 1.0                # past the Demand cap: the relay's answer-to-wire and start-to-wire only
LO_SLACK_S = 0.0                 # under OF's wait: none (a hold runs from the relay's own read of the answer)
CATCHUP_N, CATCHUP_BATCHES, CATCHUP_EVERY_S = 25, 5, 3.5   # inside one SLOW_S gap: 3 pages of 10
P1_S, P2_S = 22.0, 34.0
REFRESH_WITHIN_S = 2.0
SENDS, JOBS = 12, 4
CLICKS, IDLE_MS, CLICK_TIMEOUT_S = 20, 600, 20.0
P95_VS_LAST = (1.5, 300)     # click-to-settled on a shared machine; see the ASSUMPTION in the report
P95_VS_LAST_MIN_N = 20       # a p95 of fewer samples is a max, not a p95
# Legs, each in a file of its own (lib/view_lease_tiers_<leg>_leg.py), loaded when present: optional SELLER_KINDS
# (Seller rule kinds it adds), IDLE_RULES ({role: rule kind}: k Idle Creators each with that non-Seller rule, a
# seeded purchase, checked by IDLE_SLOW), and `async run(ctx, roles, hook, *, fast_s, slow_s)` after feed health.
LEGS = [importlib.import_module(f"slop.lib.{m.stem}")
        for m in sorted((Path(__file__).resolve().parents[1] / "lib").glob("view_lease_tiers_*_leg.py"))]
SELLER_KINDS = ("reply_mass_funnel", "purchase_followup") + tuple(k for g in LEGS for k in getattr(g, "SELLER_KINDS", ()))
IDLE_RULES = {role: kind for g in LEGS for role, kind in getattr(g, "IDLE_RULES", {}).items()}
THROUGH = (re.compile(r"/api/of/v2/users/notifications(/count)?"), re.compile(r"/api/of/v2/chats"))
PPV_BASE = 7_700_000_000
# App-open warm leg. Proxies: WARM_PX fake ones (lib/sweep_pacing_proxy.bind) of WARM_PER_PX Creators each, the rest
# direct. GAP / REUSE: app_open_warm's Knob defaults (APP_OPEN_WARM_GAP_S 1.0, APP_OPEN_WARM_REUSE_S 30), not scaled.
WARM_PX, WARM_PER_PX = 2, 4
WARM_GAP_S, WARM_GAP_SLACK_S, WARM_REUSE_S = 1.0, 0.1, 30.0
WARM_PAGE = "/settings"
WARM_SETTLE_S = 45.0
WARM_SENDS, WARM_SEND_EVERY_S = 8, 0.35
SEND_VS_NO_WARM = (1.5, 300)   # send p95 during the warm vs the tiers leg's (no warm): max(1.5x, +300 ms)


def _roles(ids: list[str]) -> dict[str, list[str]]:
    n, k = len(ids), max(1, len(ids) // 10)
    it = iter(ids)
    take = lambda m: [next(it) for _ in range(m)]  # noqa: E731
    per = max(k, -(-3 // len(SELLER_KINDS)))   # feed health needs three Seller Creators
    r = {kind: take(per) for kind in SELLER_KINDS}
    r |= {role: take(k) for role in IDLE_RULES}
    r |= {"owner": take(k), "chatter": take(k), "all_on": take(k), "all_off": take(k), "gain": take(1)}
    r["idle"] = list(it)
    assert r["idle"], f"{n} Creators leave no Idle one"
    return r


def _idle(roles: dict[str, list[str]]) -> list[str]:
    return roles["idle"] + [a for role in IDLE_RULES for a in roles[role]]


def _polls(fake, since: float) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    with fake.lock:
        for c in fake.calls:
            if c["t0"] is not None and c["t0"] >= since and is_feed(c):
                out.setdefault(c["account"], []).append(c["t0"])
    return out


def _gaps(ts_: list[float], lo: float, hi: float) -> list[float]:
    xs = [t for t in ts_ if lo <= t <= hi]
    return [round(b - a, 2) for a, b in zip(xs, xs[1:])]


async def run(ctx) -> None:
    leg = str(ctx.param("leg", "all"))
    w = ctx.world
    w.data["flat_creators"] = CREATORS[ctx.scale]
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    with ExitStack() as wires:   # the fake proxies (sweep_pacing_proxy.bind): alive to the last leg
        warm = None
        if leg in ("all", "warm"):
            warm = await _warm(ctx, creators, wires)
        if leg in ("all", "rail"):
            roster = await rail_scope.run(ctx, creators, _roles(creators), THROUGH, ttl_s=TTL_S, reuse_s=WARM_REUSE_S)
            if roster:
                _p95(ctx, "GET /admin/accounts/roster-counts", roster["p95_ms"], roster["n"])
        if leg in ("all", "tiers"):
            await _tiers(ctx, creators, warm)
        if leg in ("all", "dm"):
            await view_lease_dm_bust.run(ctx, _roles(creators)["all_off"][0])
        if leg in ("all", "visible"):
            await view_lease_visible.run(ctx, creators, TTL_S, THROUGH)
        if leg in ("all", "latency"):
            await _latency(ctx)


def _warm_counts(ctx) -> dict[str, int] | None:
    """Per Creator, the relay's OF calls under Caller kind walk:app_open_warm so far (lib/of_call_stats.py)."""
    try:
        raw, _ = of_call_stats.read(of_call_stats.path(ctx))
    except (OSError, ValueError, KeyError):
        return None
    out: dict[str, int] = {}
    for (_key, aid, _st), n in of_call_stats.counts(raw, caller="walk:app_open_warm").items():
        out[aid] = out.get(aid, 0) + n
    return out


def _delta(a: dict | None, b: dict | None) -> dict | None:
    if a is None or b is None:
        return None
    return {k: n - a.get(k, 0) for k, n in b.items() if n - a.get(k, 0)}


async def _warm(ctx, creators: list[str], wires: ExitStack) -> dict:
    """The App-open warm, from the browser (phase-01 1a): a non-Messages-Pro page opened first warms every Creator
    once (WARM_ONCE), per proxy GAP apart, leased first, proxies in parallel (WARM_STAGGER); a second open inside
    the reuse window (Messages Pro) reads nothing; the browser's own selection posts read the selected Creator
    within REFRESH_WITHIN_S (folded into SELECT_REFRESH); sends made while the warm runs (FAN_WRITES_KEPT)."""
    from slop.actors import ui

    w, fake = ctx.world, ctx.of_wire
    roles = _roles(creators)
    nick = {c["id"]: c["nickname"] for c in w.data["creators"]}
    # Next compiles each route on its first hit: before the clock that matters (the reuse window) starts.
    async with httpx.AsyncClient(timeout=180) as hc:
        for path in (WARM_PAGE, "/messages-pro"):
            try:
                await hc.get(f"{ctx.app}{path}")
            except httpx.HTTPError:
                pass
    groups = [creators[k * WARM_PER_PX:(k + 1) * WARM_PER_PX] for k in range(WARM_PX)]
    bound = await sweep_pacing_proxy.bind(ctx, wires, groups)
    group_of = {a: bound.get(a, "direct") for a in creators}
    # Leased before the open: the last Creator of each group (an httpx tab, renewing); their Select refresh reads
    # age past FAST_S first, so the warm reads them again, and first.
    leased = [g[-1] for g in groups] + [creators[-1]]
    sel = groups[0][0]          # the Creator the first open has selected: unleased, on the first proxy
    stop = asyncio.Event()

    async def lease_loop() -> None:
        while not stop.is_set():
            await ctx.owner.post("/admin/view-lease", json={"tab": "o-warm", "account_ids": leased, "selected": None,
                                                            "opened": False})
            try:
                await asyncio.wait_for(stop.wait(), RENEW_S)
            except asyncio.TimeoutError:
                pass

    lt = asyncio.create_task(lease_loop())
    await asyncio.sleep(FAST_S + 1.0)

    sends: list[dict] = []

    async def send_during() -> None:
        targets = roles["owner"] + roles["idle"]
        for i in range(WARM_SENDS):
            aid = targets[i % len(targets)]
            fan = w.data["fans"][aid][3]["id"]
            t0, t = time.monotonic(), time.time()
            r = await ctx.owner.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                     json={"text": f"slop warm {i}"})
            sends.append({"aid": aid, "fan": fan, "status": r.status_code, "t": t,
                          "ms": round((time.monotonic() - t0) * 1000, 1)})
            await asyncio.sleep(WARM_SEND_EVERY_S)

    posts: list[dict] = []
    selections: list[dict] = []
    shots: list[str] = []
    t = {}
    # No /api/of/ read let through: the rail's own notifications reads would land on the purchases feed too, and
    # this leg counts only the relay's (the warm's, the Select refresh's).
    async with ui.owner_browser(ctx) as page:
        def on_request(req) -> None:
            if req.method == "POST" and urlsplit(req.url).path == "/admin/view-lease":
                try:
                    body = json.loads(req.post_data or "{}")
                except ValueError:
                    body = {}
                post = {"t": time.time(), "page": urlsplit(page.url).path, "body": body}
                posts.append(post)
                reads.append(asyncio.ensure_future(_answer(post, req)))

        async def _answer(post: dict, req) -> None:
            # Read at once: a navigation drops the body of a response the page left behind.
            try:
                resp = await req.response()
                post["status"] = resp.status if resp else None
                post["answer"] = await resp.json() if resp and resp.status == 200 else None
            except Exception as e:  # noqa: BLE001 — a post still in flight when the page closes
                post["status"], post["answer"] = None, {"error": type(e).__name__}

        reads: list[asyncio.Future] = []
        page.on("request", on_request)
        # The first document load after this finds `sel` as the saved scope (ScopeContext's localStorage key).
        await page.add_init_script(
            "try { if (!sessionStorage.getItem('slop:warm-scope')) { sessionStorage.setItem('slop:warm-scope', '1');"
            f" localStorage.setItem('chatterly:scope', 'model:{sel}'); }} }} catch (e) {{}}")
        counts0 = _warm_counts(ctx)
        t["open1"] = time.time()
        await page.goto(f"{ctx.app}{WARM_PAGE}", wait_until="domcontentloaded")
        await _until(lambda: any(p["body"].get("opened") for p in posts), 30)
        shots.append(await ui.shot(ctx, page, "warm-trigger-settings"))
        st = asyncio.create_task(send_during())
        await _until(lambda: rail_scope.warmed_on_wire(fake, creators, t["open1"]), WARM_SETTLE_S, 0.25)
        await of_call_stats.quiet(fake, 1.5, 20)
        await st
        shots.append(await ui.shot(ctx, page, "warm-settled-settings"))
        passed = await rail_scope.pass_through(ctx, creators)   # a tab's reads of the warmed entries
        counts1 = _warm_counts(ctx)
        await page.evaluate("localStorage.setItem('chatterly:scope', 'all')")   # the second open: no selection
        t["open2"] = time.time()
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        strip = page.get_by_role("tablist", name="Creator tabs")
        await strip.wait_for(timeout=90_000)
        await _until(lambda: any(p["body"].get("opened") and p["t"] >= t["open2"] for p in posts), 30)
        await asyncio.sleep(2.0)                      # a read the second open would make has started by now
        await of_call_stats.quiet(fake, 1.5, 20)      # and ended (the warm, if it ran here: its reads, not a click's)
        counts2 = _warm_counts(ctx)
        t["click"] = time.time()
        for aid in (roles["owner"][0], roles["chatter"][0]):   # leased in the tiers leg anyway: no Idle one
            tab = strip.get_by_role("tab").filter(has_text=nick[aid]).first
            pre = [p for p in posts if p["t"] >= t["open2"]]
            leased_at = bool(pre) and aid in (pre[-1]["body"].get("account_ids") or [])   # before its scroll
            await tab.scroll_into_view_if_needed()
            n0 = len(posts)
            await tab.click()
            await _until(lambda: any(p["body"].get("selected") == aid for p in posts[n0:]), 10)
            post = next((p for p in posts[n0:] if p["body"].get("selected") == aid), None)
            if post is not None:
                await _until(lambda: _read_at(fake, aid, post["t"]) is not None, REFRESH_WITHIN_S + 1.0)
            selections.append({"aid": aid, "post": post, "leased_at_click": leased_at})
        await asyncio.sleep(0.5)
        shots.append(await ui.shot(ctx, page, "warm-mp-selected"))
        if reads:
            await asyncio.wait(reads, timeout=10)
    stop.set()
    await lt
    (await ctx.owner.post("/admin/view-lease", json={"tab": "o-warm", "account_ids": [], "selected": None,
                                                     "opened": False})).raise_for_status()

    # ── WARM_ONCE ────────────────────────────────────────────────────────────────
    reads1 = {a: v for a, v in _polls(fake, t["open1"]).items()}
    reads1 = {a: [x for x in v if x < t["open2"]] for a, v in reads1.items()}
    reads2 = {a: [x for x in v if x < t["click"]] for a, v in _polls(fake, t["open2"]).items()}
    opened = [p for p in posts if p["body"].get("opened")]
    open1 = next((p for p in opened if p["t"] < t["open2"]), None)
    open2 = next((p for p in opened if p["t"] >= t["open2"]), None)
    per1 = {a: len(reads1.get(a, [])) for a in creators}
    set1 = rail_scope.read_set(fake, t["open1"], t["open2"])
    # The scaled TTL (6 s) lapses the Settings tab's lease between its 20 s heartbeats: each re-leases `sel` as its
    # `selected` (a Select refresh, always). The tab's own roster-counts read (an /admin/ read) adds chats reads.
    regain = sum(1 for p in posts if t["open1"] < p["t"] < t["open2"] and not p["body"].get("opened")
                 and p["body"].get("selected") == sel)
    want1 = {a: {"feed": 1 + regain * (a == sel), "list:tip": 1, "list:purchases": 1, "count": 1} for a in creators}
    set2 = rail_scope.read_set(fake, t["open2"], t["click"])
    last_read = max((x for v in reads1.values() for x in v), default=None)
    once = {
        "page": WARM_PAGE, "open1": open1 and {k: open1[k] for k in ("page", "body", "status", "answer")},
        "open2": open2 and {k: open2[k] for k in ("page", "body", "status", "answer")},
        "reads_per_creator": per1, "sel_regained": regain, "read_set_open1": set1,
        "read_calls_open1": rail_scope.read_calls(fake, t["open1"], t["open2"]), "read_set_open2": set2,
        "pass_through": passed,
        "warm_calls_open1": _delta(counts0, counts1), "warm_calls_open2": _delta(counts1, counts2),
        "open2_after_warm_s": round(open2["t"] - last_read, 2) if open2 and last_read else None,
    }
    once["selected"] = sel
    wc1 = once["warm_calls_open1"]
    ok_once = (open1 is not None and open1["page"].startswith(WARM_PAGE)   # Settings redirects to /settings/account
               and open1["body"].get("selected") == sel
               and (open1["answer"] or {}).get("warm") == "started"
               and all({k: n for k, n in set1.get(a, {}).items() if k != "chats"} == want1[a]
                       and set1[a].get("chats", 0) >= 1 for a in creators)
               and (wc1 is None or wc1 == {a: len(rail_scope.READ_SET) - (a == sel) for a in creators})
               and not passed["of_calls"] and set(passed["statuses"]) == {"200"}
               and open2 is not None and (open2["answer"] or {}).get("warm") == "reused"
               and not set2 and not once["warm_calls_open2"])
    ctx.check(WARM_ONCE, ok_once, **once)

    # ── WARM_STAGGER: the first warm's reads (the open that warmed: the Settings page's, else Messages Pro's) ──
    warm1 = any(v for a, v in reads1.items() if a != sel)   # `sel`'s own read is its Select refresh's, not a warm
    first = reads1 if warm1 else reads2
    lead_sel = sel if warm1 else None
    by_group: dict[str, list[tuple[float, str]]] = {}
    for a, v in first.items():
        for x in v[:1]:
            by_group.setdefault(group_of.get(a, "direct"), []).append((x, a))
    stagger: dict = {}
    ok_stagger = len(by_group) == WARM_PX + 1
    for g, xs in by_group.items():
        xs.sort()
        gaps = [round(b[0] - a[0], 3) for a, b in zip(xs, xs[1:])]
        order = [a for _, a in xs]
        lead = [a for a in order if a in leased]
        warmed = [a for a in order if a != lead_sel]   # `sel` is its Select refresh's read, the first on its proxy
        leased_first = warmed[:len(lead)] == lead and bool(lead) and (lead_sel not in order or order[0] == lead_sel)
        stagger[g] = {"order": order, "gaps_s": gaps, "leased": lead, "leased_first": leased_first}
        ok_stagger &= all(x >= WARM_GAP_S - WARM_GAP_SLACK_S for x in gaps) and leased_first
    starts = [xs[0][0] for xs in by_group.values() if xs]
    spread = round(max(starts) - min(starts), 3) if starts else None
    ok_stagger &= spread is not None and spread < WARM_GAP_S
    ctx.check(WARM_STAGGER, ok_stagger, gap_s=WARM_GAP_S, slack_s=WARM_GAP_SLACK_S, groups=stagger,
              group_first_spread_s=spread, proxies={g: sorted(a for a in creators if group_of[a] == g)
                                                    for g in set(group_of.values())})

    sel_out = []
    for s in selections:
        p = s["post"]
        if p is None:
            sel_out.append({"aid": s["aid"], "status": None, "read_after_s": None,
                            "leased_at_click": s["leased_at_click"], "read_joined": None})
            continue
        r = _read_at(fake, s["aid"], p["t"])
        sel_out.append({"aid": s["aid"], "status": p.get("status"), "t": p["t"], "body": p["body"],
                        "leased_at_click": s["leased_at_click"],
                        "read_after_s": round(max(0.0, r[0] - p["t"]), 2) if r else None,
                        "read_joined": bool(r and r[0] < p["t"])})
    lo, hi = (min(starts), max(x for v in first.values() for x in v)) if starts else (None, None)
    during = sum(1 for s in sends if lo is not None and lo <= s["t"] <= hi)
    out = {"posts": [{k: p.get(k) for k in ("t", "page", "body", "status", "answer")} for p in posts],
           "reads_open1": reads1, "reads_open2": reads2, "t": t, "leased": leased, "bound": bound,
           "selections": sel_out, "sends": sends, "sends_during_warm": during, "screenshots": shots}
    (ctx.out / "app-open-warm.json").write_text(json.dumps(out, indent=1, default=str))
    ctx.metric("app_open_warm", {"reads": sum(per1.values()), "creators": len(creators), "posts": len(posts),
                                 "sends_during_warm": during, "screenshots": shots})
    return out


async def _tiers(ctx, creators: list[str], warm: dict | None = None) -> None:
    w, fake = ctx.world, ctx.of_wire
    roles = _roles(creators)
    now = datetime.utcnow()
    con = w.sql()
    with con:
        con.execute("UPDATE users SET is_admin=1 WHERE id=?", (w.user_id,))
        for role, kind in [(k, k) for k in SELLER_KINDS] + list(IDLE_RULES.items()):
            for aid in roles[role]:
                con.execute("INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled,"
                            " created_at) VALUES (?, ?, ?, '{}', '[]', 1, ?)", (aid, f"slop {kind}", kind, ts(now)))
    con.close()
    # One seeded PPV purchase per Idle Creator (IDLE_RULES' too): the priced outbound message and OF's notification.
    bought = {aid: (w.data["fans"][aid][0]["id"], PPV_BASE + i) for i, aid in enumerate(_idle(roles))}
    ppv_purchases.unpaid_copies(w, [(aid, fan, mid) for aid, (fan, mid) in bought.items()], price_cents=1500,
                                at=now - timedelta(hours=1), now=now)
    with fake.lock:
        for i, (aid, (fan, mid)) in enumerate(bought.items()):
            fake.purchases[aid] = [ppv_purchases.note(5_000_000 + i, fan, mid, cents=1500,
                                                      at=now - timedelta(minutes=5))]

    chat_ids = roles["owner"] + roles["chatter"] + roles["idle"]
    all_ids = roles["all_on"] + roles["all_off"]
    ch, ca = await chatter_seed.seed(w, ctx.owner, w.user_id, ["vl_chatter", "vl_allview"],
                                     account_ids=[chat_ids, all_ids])
    tabs_per = max(1, min(ctx.users, 200) // 3)

    async def login(rec: dict) -> Http:
        h = Http(ctx.relay, ctx.rec, limits=max(4, tabs_per))
        (await h.post("/chatter/login", json={"username": rec["username"], "password": rec["password"]})
         ).raise_for_status()
        return h

    h_ch, h_ca = await login(ch), await login(ca)
    hook = ctx.owner.share(limits=4)

    # ── P1: the loop alone, no client ────────────────────────────────────────────
    (await hook.post("/__slop/fast-poll")).raise_for_status()
    t_start = time.time()
    await asyncio.sleep(P1_S)
    t_p2 = time.time()

    # ── P2: lease tabs ───────────────────────────────────────────────────────────
    answers: list[dict] = []
    registry: list[dict] = []
    stop = asyncio.Event()
    owner_tab0 = {"ids": list(roles["owner"]), "selected": roles["owner"][0]}
    marks: dict[str, dict] = {}

    async def renew(h: Http, role: str, tab: str, ids: list[str], selected) -> dict:
        t = time.time()
        r = await h.post("/admin/view-lease", json={"tab": tab, "account_ids": ids, "selected": selected,
                                                    "opened": False})
        body = r.json() if r.status_code == 200 else {}
        answers.append({"t": t, "role": role, "tab": tab, "status": r.status_code, "ids": ids,
                        "selected": selected, "leased": body.get("leased")})
        return {"t": t, "status": r.status_code}

    async def tab_loop(h: Http, role: str, tab: str, ids: list[str], selected) -> None:
        while not stop.is_set():
            await renew(h, role, tab, ids, selected)
            try:
                await asyncio.wait_for(stop.wait(), RENEW_S)
            except asyncio.TimeoutError:
                pass

    async def owner0_loop() -> None:
        while not stop.is_set():
            await renew(ctx.owner, "owner", "o-0", list(owner_tab0["ids"]), owner_tab0["selected"])
            try:
                await asyncio.wait_for(stop.wait(), RENEW_S)
            except asyncio.TimeoutError:
                pass

    async def registry_loop() -> None:
        while not stop.is_set():
            r = await hook.get("/__slop/view-lease")
            registry.append({"t": time.time(), "leased": r.json().get("leased", [])})
            await asyncio.sleep(1.0)

    tasks = [asyncio.create_task(owner0_loop()), asyncio.create_task(registry_loop())]
    tasks += [asyncio.create_task(tab_loop(ctx.owner, "owner", f"o-{i}", roles["owner"], roles["owner"][0]))
              for i in range(1, tabs_per)]
    tasks += [asyncio.create_task(tab_loop(h_ch, "chatter", f"c-{i}", roles["chatter"], roles["chatter"][0]))
              for i in range(tabs_per)]
    tasks += [asyncio.create_task(tab_loop(h_ca, "all_view", f"a-{i}", roles["all_on"], None))
              for i in range(tabs_per)]

    async def after_a_cycle(aid: str) -> float:
        """Right after the loop's next poll of `aid` (a fast Creator): the next cycle is ~FAST_S away."""
        await next_poll(fake, aid, 3 * FAST_S)
        await asyncio.sleep(0.3)
        return time.time()

    async def select_refresh() -> None:
        await asyncio.sleep(2 * FAST_S)
        # (a) GAIN: a Creator nobody leases joins the owner's tab 0.
        await after_a_cycle(roles[SELLER_KINDS[0]][0])
        gain = roles["gain"][0]
        owner_tab0["ids"] = roles["owner"] + [gain]
        r = await renew(ctx.owner, "owner", "o-0", list(owner_tab0["ids"]), owner_tab0["selected"])
        marks["gain"] = {"aid": gain, **r}
        await asyncio.sleep(2 * FAST_S)
        # (b) SELECT: the owner's tab 0 selects a Creator the chatter's tabs already lease.
        sel = roles["chatter"][0]
        await after_a_cycle(sel)
        await asyncio.sleep(FAST_S / 6)   # past purchase_poll_decide.SELECT_MIN_AGE_S: a selection reads again
        owner_tab0["ids"] = roles["owner"] + [gain, sel]
        owner_tab0["selected"] = sel
        r = await renew(ctx.owner, "owner", "o-0", list(owner_tab0["ids"]), sel)
        marks["select"] = {"aid": sel, **r}

    sends: list[dict] = []

    async def fan_writes() -> dict:
        targets = roles["owner"] + roles["idle"]
        await asyncio.sleep(FAST_S)
        con = w.sql()
        with con:
            jobs = []
            for j in range(JOBS):
                aid = targets[j % len(targets)]
                fan = w.data["fans"][aid][1]["id"]
                cur = con.execute("INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts,"
                                  " created_at) VALUES (?, 'scrape_chats', ?, ?, 'pending', 0, ?)",
                                  (aid, json.dumps({"fan_ids": [fan]}), ts(datetime.utcnow() - timedelta(seconds=5)),
                                   ts(datetime.utcnow())))
                jobs.append((int(cur.lastrowid), aid))
        con.close()
        for i in range(SENDS):
            aid = targets[i % len(targets)]
            fan = w.data["fans"][aid][2]["id"]
            t0 = time.monotonic()
            r = await ctx.owner.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                     json={"text": f"slop tiers {i}"})
            sends.append({"aid": aid, "fan": fan, "status": r.status_code,
                          "ms": round((time.monotonic() - t0) * 1000, 1)})
            await asyncio.sleep(P2_S / (2 * SENDS))
        ticks = []
        for _ in range(4):
            r = await hook.post("/__slop/automation-tick", timeout=120)
            ticks.append(r.status_code)
            con = w.sql()
            try:
                left = con.execute(f"SELECT COUNT(*) FROM scheduled_jobs WHERE id IN ({','.join('?' * len(jobs))})"
                                   " AND status IN ('pending','running')", [j for j, _ in jobs]).fetchone()[0]
            finally:
                con.close()
            if not left:
                break
        return {"jobs": jobs, "ticks": ticks}

    sr = asyncio.create_task(select_refresh())
    fw = asyncio.create_task(fan_writes())
    await asyncio.sleep(P2_S)
    await sr
    writes = await fw
    t_end = time.time()
    stop.set()
    await asyncio.gather(*tasks)
    await asyncio.sleep(1.5)  # the counter flushes every 1 s
    try:
        raw, _ = of_call_stats.read(of_call_stats.path(ctx))
        sel_rows = of_call_stats.counts(raw, caller="select_refresh")
    except (OSError, ValueError, KeyError):
        sel_rows = None
    for h in (h_ch, h_ca):
        await h.aclose()

    polls = _polls(fake, t_start)
    window_p2 = (t_p2 + FAST_S + 1.0, t_end)
    window_all = (t_start + FAST_S, t_end)

    def fast_bad(ids: list[str], lo: float, hi: float) -> dict:
        bad = {}
        for aid in ids:
            g = _gaps(polls.get(aid, []), lo, hi)
            want_n = int((hi - lo) / (1.5 * FAST_S)) - 1  # every gap <= 1.5 x FAST_S, none missing
            if not g or max(g) > 1.5 * FAST_S or len(g) < want_n:
                bad[aid] = {"gaps": g, "want_n": want_n}
        return bad

    leased_ids = roles["owner"] + roles["chatter"] + roles["all_on"]
    lb = fast_bad(leased_ids, *window_p2)
    ctx.check(LEASED_FAST, not lb, creators=len(leased_ids), bad=lb,
              sample={a: _gaps(polls.get(a, []), *window_p2) for a in leased_ids[:3]})
    sellers = [a for k in SELLER_KINDS for a in roles[k]]
    sb = fast_bad(sellers, *window_all)
    ctx.check(SELLER_FAST, not sb, creators=len(sellers), bad=sb, no_client_s=P1_S,
              sample={a: _gaps(polls.get(a, []), *window_all) for a in sellers[:3]})

    idle = _idle(roles)
    span = t_end - t_start
    ib = {}
    for aid in idle:
        g = _gaps(polls.get(aid, []), t_start, t_end)
        if (g and min(g) < SLOW_S - FAST_S) or len(polls.get(aid, [])) > span / SLOW_S + 2 or not polls.get(aid):
            ib[aid] = {"gaps": g, "n": len(polls.get(aid, []))}
    con = w.sql()
    try:
        paid = {aid: con.execute("SELECT is_paid FROM messages WHERE account_id=? AND fan_id=? AND message_id=?",
                                 (aid, *bought[aid])).fetchone()[0] for aid in bought}
        cutoff = ts(datetime.utcnow() - timedelta(seconds=600))
        admin_on = con.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND last_seen_at >= ?",
                               (cutoff,)).fetchone()[0]
        chatter_on = con.execute("SELECT COUNT(*) FROM chatters WHERE is_active=1 AND last_seen_at >= ?",
                                 (cutoff,)).fetchone()[0]
        runs = con.execute("SELECT account_id, status FROM automation_runs WHERE kind='scrape_chats'").fetchall()
        job_rows = {r[0]: r[1] for r in con.execute(
            f"SELECT id, status FROM scheduled_jobs WHERE id IN ({','.join('?' * len(writes['jobs']))})",
            [j for j, _ in writes["jobs"]]).fetchall()}
    finally:
        con.close()
    unflipped = sorted(a for a, v in paid.items() if not v)
    ctx.check(IDLE_SLOW, not ib and not unflipped and admin_on >= 1 and chatter_on >= 1,
              creators=len(idle), bad=ib, unflipped=unflipped, admin_online=admin_on, chatters_online=chatter_on,
              sample={a: _gaps(polls.get(a, []), t_start, t_end) for a in idle[:3]})

    av = [a for a in answers if a["role"] == "all_view"]
    av_bad = [a for a in av if a["status"] != 200 or sorted(a["leased"] or []) != sorted(roles["all_on"])]
    reg_off = [r for r in registry if set(r["leased"]) & set(roles["all_off"])]
    reg_on = [r for r in registry if r["t"] > t_p2 + RENEW_S and not set(roles["all_on"]) <= set(r["leased"])]
    ctx.check(ALL_VIEW_NO_LEASE, bool(av) and not av_bad and not reg_off and bool(registry),
              renewals=len(av), bad_answers=av_bad[:5], registry_reads=len(registry),
              registry_with_off_screen=reg_off[:3], registry_missing_on_screen=len(reg_on))

    def read_after(m: dict) -> float | None:
        ts_ = [t for t in polls.get(m["aid"], []) if t >= m["t"]]
        return round(ts_[0] - m["t"], 2) if ts_ else None

    # The browser's own selection posts (the warm leg's Messages Pro clicks): their reads, before this leg.
    browser_marks = {f"browser_{i}": m for i, m in enumerate((warm or {}).get("selections", []))}
    sr_res = {k: {"aid": m["aid"], "status": m["status"],
                  "read_after_s": m["read_after_s"] if "read_after_s" in m else read_after(m),
                  "select_refresh_calls": (sum(n for (_k, a, _s), n in sel_rows.items() if a == m["aid"])
                                           if sel_rows is not None else None),
                  **{k2: m[k2] for k2 in ("leased_at_click", "read_joined") if k2 in m}}
              for k, m in {**marks, **browser_marks}.items()}
    want_legs = {"gain", "select"} | ({"browser_0", "browser_1"} if warm is not None else set())
    sr_ok = (set(sr_res) == want_legs
             and all(v["status"] == 200 and v["read_after_s"] is not None and v["read_after_s"] <= REFRESH_WITHIN_S
                     and (v["select_refresh_calls"] or 0) >= 1 for v in sr_res.values())
             # a tab leased at the click has no lease-gain read in flight: its read is the selection's own
             and all(v["read_joined"] is False for v in sr_res.values() if v.get("leased_at_click")))
    ctx.check(SELECT_REFRESH, sr_ok, within_s=REFRESH_WITHIN_S, legs=sr_res)

    with fake.lock:
        kept = {a: sum(1 for s in fake.sends.get(a, []) if "slop tiers" in str(s.get("text", "")))
                for a in {s["aid"] for s in sends}}
    want = {a: sum(1 for s in sends if s["aid"] == a) for a in kept}
    ok_runs = {a: sum(1 for r in runs if r[0] == a and r[1] == "ok") for _j, a in writes["jobs"]}
    want_runs = {a: sum(1 for _j, x in writes["jobs"] if x == a) for _j, a in writes["jobs"]}
    jobs_left = [j for j, s in job_rows.items() if s in ("pending", "running")]
    # The warm leg's sends (made while the App-open warm read every Creator) vs these (no warm): kept, and p95 within
    # SEND_VS_NO_WARM of this leg's.
    p95_no_warm = _p95_of([s["ms"] for s in sends])
    warm_part: dict = {"ran": warm is not None}
    warm_ok = True
    if warm is not None:
        ws = warm["sends"]
        with fake.lock:
            kept_w = {a: sum(1 for s in fake.sends.get(a, []) if "slop warm" in str(s.get("text", "")))
                      for a in {s["aid"] for s in ws}}
        want_w = {a: sum(1 for s in ws if s["aid"] == a) for a in kept_w}
        p95_w = _p95_of([s["ms"] for s in ws])
        limit = max(p95_no_warm * SEND_VS_NO_WARM[0], p95_no_warm + SEND_VS_NO_WARM[1]) if p95_no_warm else None
        warm_ok = (len(ws) == WARM_SENDS and all(s["status"] == 200 for s in ws) and kept_w == want_w
                   and limit is not None and p95_w is not None and p95_w <= limit)
        warm_part |= {"sends": len(ws), "statuses": sorted({s["status"] for s in ws}), "kept": kept_w, "want": want_w,
                      "p95_ms": p95_w, "no_warm_p95_ms": p95_no_warm, "limit_ms": limit,
                      "during_warm": warm.get("sends_during_warm")}
    ctx.check(FAN_WRITES_KEPT, len(sends) == SENDS and all(s["status"] == 200 for s in sends) and kept == want
              and ok_runs == want_runs and not jobs_left and all(t == 200 for t in writes["ticks"]) and warm_ok,
              sends=len(sends), statuses=sorted({s["status"] for s in sends}), kept=kept, want=want,
              runs_ok=ok_runs, runs_want=want_runs, jobs_left=jobs_left, ticks=writes["ticks"],
              send_p95_ms=p95_no_warm, warm=warm_part)

    vl = ctx.rec.summary().get("POST /admin/view-lease")
    if vl:
        _p95(ctx, "POST /admin/view-lease", vl["p95_ms"], vl["n"])
    await _health(ctx, roles, hook)
    for g in LEGS:
        await g.run(ctx, roles, hook, fast_s=FAST_S, slow_s=SLOW_S)
    (ctx.out / "view-lease.json").write_text(json.dumps({
        "roles": roles, "knobs": {"fast_s": FAST_S, "slow_s": SLOW_S, "ttl_s": TTL_S, "renew_s": RENEW_S},
        "t": {"start": t_start, "p2": t_p2, "end": t_end}, "polls": polls, "marks": marks,
        "answers": answers[-50:], "registry": registry, "sends": sends, "writes": writes,
    }, indent=1, default=str))
    ctx.metric("view_lease", {"renewals": len(answers), "tabs_per_role": tabs_per,
                              "polls": {k: len(v) for k, v in polls.items()}})


def _read_at(fake, aid: str, t: float) -> tuple[float, float] | None:
    """`aid`'s first purchases read (t0, answer t) still on the wire at `t` or started after it: a selection post
    that lands while the tab's own lease-gain read is in flight (the click's scroll into view) joins it
    (`purchase_poll.poll_now`, single-flight per Creator)."""
    with fake.lock:
        xs = sorted((c["t0"], c["t"]) for c in fake.calls
                    if c["account"] == aid and c["t0"] is not None and is_feed(c)
                    and (c["t"] or float("inf")) >= t and c["t0"] >= t - REFRESH_WITHIN_S)
    return xs[0] if xs else None


def _ladder(n: int, asked: float | None) -> list[float]:
    """The holds n failures in a row ask (purchase_poll_decide.after at RELAY_ENV's Knobs): the longer of OF's
    asked wait and the rung, uncapped."""
    return [max(min(BACKOFF_BASE_S * 2 ** (i - 1), BACKOFF_MAX_S), asked or 0.0) for i in range(1, n + 1)]


def _bounds(hold: float, cycle_s: float) -> tuple[float, float]:
    """A Demand Creator's gap, OF's answer to its next call, after a failing poll asking `hold`
    (purchase_poll_decide.held: the _single_flight gate starts no poll before the hold, capped at the Demand cap,
    from the answer): polled on the first cycle at or after it, or at the hold's end when that falls before the next
    tick (purchase_poll._poll_at_hold_end). So at least the capped hold, at most a cycle more (`cycle_s`,
    measured) plus the stagger, and never past the cap plus CAP_SLACK_S."""
    e = min(hold, BACKOFF_DEMAND_MAX_S)
    return e - LO_SLACK_S, min(e + cycle_s + GAP_SLACK_S, BACKOFF_DEMAND_MAX_S + CAP_SLACK_S)


def _fits(gaps: list[float], want: list[float], cycle_s: float) -> bool:
    return len(gaps) >= 2 and all(lo <= g <= hi for g, (lo, hi) in zip(gaps, (_bounds(w, cycle_s) for w in want)))


async def _health(ctx, roles: dict[str, list[str]], hook) -> None:
    """Feed health (ticket 21), the loop still running: OF answers four Creators' purchases feed 429 / 401 for P3_S
    (lib/of_wire.py `status`) and asks a fifth (leased) to confirm its login (`otp`: a Dead session). BACKOFF_429:
    the failing polls' gaps follow the longer of OF's asked wait and the rung (the Retry-After header, or OF's own
    "Please allow 1 seconds" body, which must not stop the climb), the leased / Seller cap winning. UNAUTH_NOT_DEAD:
    the 401 climbs the same ladder, never flagged. DEAD_SILENT: no feed call after the flag, the probe still runs
    (one `/__slop/automation-tick`). DEAD_RESUME: a re-capture (`POST /admin/session/bootstrap`) clears the flag and
    the next cycle reads the feed. FEED_CATCHUP: right after an Idle Creator's poll, CATCHUP_N purchases land on its
    feed inside one slow gap (CATCHUP_BATCHES batches CATCHUP_EVERY_S apart: never more than a page between two
    polls a cycle apart, so a fast-polled one needs no paging); its next poll pages back to all of them."""
    w, fake = ctx.world, ctx.of_wire
    ra12, allow1, unauth = [a for k in SELLER_KINDS for a in roles[k]][:3]
    cap, dead, idle = roles["owner"][0], roles["chatter"][0], roles["idle"][0]
    beat = roles["all_on"][0]    # leased and healthy: polled every cycle, its gaps the loop's period
    stop = asyncio.Event()

    async def lease_loop() -> None:   # the owner's tab on the leased three, through the resume
        while not stop.is_set():
            await ctx.owner.post("/admin/view-lease", json={"tab": "o-health", "account_ids": [cap, dead, beat],
                                                            "selected": None, "opened": False})
            try:
                await asyncio.wait_for(stop.wait(), RENEW_S)
            except asyncio.TimeoutError:
                pass

    def flag(aid: str):
        con = w.sql()
        try:
            return con.execute("SELECT session_dead_at, session_dead_reason FROM account_health WHERE account_id=?",
                               (aid,)).fetchone()
        finally:
            con.close()

    async def catchup() -> dict:
        """CATCHUP_N priced messages (SQL), then, from right after the Idle Creator's next poll, their
        notifications on its feed in batches; done when its next poll has flipped them all, or SLOW_S + slack."""
        now = datetime.utcnow()
        fans = w.data["fans"][idle]
        rows = [(fans[j % len(fans)]["id"], PPV_BASE + 10_000 + j) for j in range(CATCHUP_N)]
        ppv_purchases.unpaid_copies(w, [(idle, fan, mid) for fan, mid in rows], price_cents=1000,
                                    at=now - timedelta(minutes=30), now=now)
        await next_poll(fake, idle, SLOW_S + FAST_S + 5.0)
        t_poll = time.time()
        per = CATCHUP_N // CATCHUP_BATCHES
        for b in range(CATCHUP_BATCHES):
            batch = [ppv_purchases.note(6_000_000 + j, fan, mid, cents=1000, at=datetime.utcnow())
                     for j, (fan, mid) in enumerate(rows) if b * per <= j < (b + 1) * per]
            with fake.lock:
                fake.purchases[idle] = list(reversed(batch)) + list(fake.purchases.get(idle, ()))
            if b < CATCHUP_BATCHES - 1:
                await asyncio.sleep(CATCHUP_EVERY_S)
        t_last = time.time()
        caught = await _until(lambda: _paid(w, idle, rows) == CATCHUP_N, SLOW_S + FAST_S + 5.0, 0.25)
        polls = _feed(fake, idle, t_poll)
        starts = [t for i, (t, _) in enumerate(polls) if i == 0 or t - polls[i - 1][0] > 1.0]   # a poll's pages: one
        g = [round(b - a, 2) for a, b in zip(starts, starts[1:])]
        return {"slow_gaps": g, "on_slow_tier": not g or min(g) >= SLOW_S - FAST_S,"creator": idle, "seeded": CATCHUP_N, "flipped": _paid(w, idle, rows), "caught": caught,
                "batches": CATCHUP_BATCHES, "every_s": CATCHUP_EVERY_S, "span_s": round(t_last - t_poll, 2),
                "polls_after_s": [(round(t - t_poll, 2), st) for t, st in polls][:8],
                "inside_one_gap": bool(polls) and polls[0][0] > t_last}

    lt = asyncio.create_task(lease_loop())
    cu = asyncio.create_task(catchup())
    await asyncio.sleep(FAST_S + 1.0)
    modes = {ra12: (429, RA_SHORT, None), allow1: (429, None, of_wire.TOO_MANY_BODY), unauth: (401, None, None),
             cap: (429, RA_LONG, None)}
    asked = {ra12: RA_SHORT, allow1: 1.0, unauth: None, cap: RA_LONG}
    t_arm = time.time()
    with fake.lock:
        fake.status.update({(a, POLL_ROUTE): m for a, m in modes.items()})
        fake.otp.add(dead)
    flagged = await _until(lambda: bool((flag(dead) or (None,))[0]), 3 * FAST_S, 0.1)
    t_flag = time.time()
    reason = (flag(dead) or (None, None))[1]
    await asyncio.sleep(max(0.0, t_arm + P3_S - time.time()))
    with fake.lock:
        for a in modes:
            fake.status.pop((a, POLL_ROUTE), None)
    t_clear = time.time()

    # The probe, still dead (OF still wants the code); then the re-capture.
    tick = await hook.post("/__slop/automation-tick", timeout=120)
    with fake.lock:
        probes = sum(1 for c in fake.calls if c["account"] == dead and c["route"] == "GET /api2/v2/users/me"
                     and c["t0"] is not None and c["t0"] >= t_flag)
        fake.otp.discard(dead)
    boot = await ctx.owner.post("/admin/session/bootstrap", timeout=60, json={
        "mode": "paste-curl", "curl": paste_curl(dead, "slop-of-rev-202610261200"), "account_id": dead,
        "make_active": False})
    t_boot = time.time()
    dead_feed = _feed(fake, dead, t_flag, t_boot)
    resumed = await _until(lambda: bool(_feed(fake, dead, t_boot)), 1.5 * FAST_S + 1.0)
    cleared = not (flag(dead) or (None,))[0]
    cu_res = await cu
    stop.set()
    await lt
    (await ctx.owner.post("/admin/view-lease", json={"tab": "o-health", "account_ids": [], "selected": None,
                                                     "opened": False})).raise_for_status()

    def failing(aid: str) -> list[tuple[float, float]]:
        # (arrival t0, answer t). From a cycle before arming: a call on the wire while armed (its t0 earlier) is
        # answered by the mode.
        with fake.lock:
            return [(c["t0"], c["t"]) for c in fake.calls
                    if c["account"] == aid and c["t0"] is not None and is_feed(c)
                    and t_arm - FAST_S <= c["t0"] <= t_clear and c["status"] == modes[aid][0]]

    bx = [t for t, _ in _feed(fake, beat, t_arm, t_clear)]
    beat_gaps = [round(b - a, 2) for a, b in zip(bx, bx[1:])]
    cycle_s = statistics.median(beat_gaps) if beat_gaps else FAST_S
    per: dict[str, dict] = {}
    for aid, (code, ra, body) in modes.items():
        xs = failing(aid)
        gaps = [round(b[0] - a[1], 2) for a, b in zip(xs, xs[1:])]     # OF's answer -> the next call's arrival
        want = _ladder(len(gaps), asked[aid])   # all four are Demand Creators (a Seller or leased)
        per[aid] = {"code": code, "retry_after_s": ra, "body": "allow 1 seconds" if body else None,
                    "asked_s": asked[aid], "gaps": gaps, "want": want,
                    "bounds": [_bounds(x, cycle_s) for x in want], "fits": _fits(gaps, want, cycle_s)}
    ctx.check(BACKOFF_429, all(per[a]["fits"] for a in (ra12, allow1, cap)), lo_slack_s=LO_SLACK_S,
              cap_slack_s=CAP_SLACK_S, slack_s=GAP_SLACK_S, cycle_s=cycle_s, ra_short=per[ra12], allow_1_climbs=per[allow1],
              cap_over_retry_after=per[cap])
    unauth_flag = flag(unauth)
    ctx.check(UNAUTH_NOT_DEAD, per[unauth]["fits"] and not (unauth_flag or (None,))[0], **per[unauth],
              cycle_s=cycle_s, flag=unauth_flag)
    ctx.check(DEAD_SILENT, flagged and reason == "otp_required" and not dead_feed and probes >= 1
              and tick.status_code == 200, flagged=flagged, reason=reason, flag_after_s=round(t_flag - t_arm, 2),
              feed_calls_after_flag=dead_feed, probes=probes, tick=tick.status_code)
    after = _feed(fake, dead, t_boot)
    ctx.check(DEAD_RESUME, boot.status_code == 200 and cleared and resumed, bootstrap=boot.status_code,
              cleared=cleared, within_s=1.5 * FAST_S + 1.0,
              first_read_after_s=round(after[0][0] - t_boot, 2) if after else None)
    # Inside one slow gap whenever the Creator is on the slow tier (IDLE_SLOW's to judge): every one flipped.
    ctx.check(FEED_CATCHUP, cu_res["caught"] and (cu_res["inside_one_gap"] or not cu_res["on_slow_tier"]), **cu_res)
    (ctx.out / "feed-health.json").write_text(json.dumps({
        "t": {"arm": t_arm, "flag": t_flag, "clear": t_clear, "boot": t_boot},
        "modes": {a: [m[0], m[1], bool(m[2])] for a, m in modes.items()}, "dead": dead, "beat": beat,
        "beat_gaps": beat_gaps, "cycle_s": cycle_s, "per": per, "dead_feed": dead_feed, "probes": probes,
        "catchup": cu_res, "calls": {a: _feed(fake, a, t_arm - FAST_S) for a in [*modes, dead, idle]},
    }, indent=1, default=str))


def _paid(w, aid: str, rows: list[tuple[int, int]]) -> int:
    con = w.sql()
    try:
        return sum(con.execute("SELECT is_paid FROM messages WHERE account_id=? AND fan_id=? AND message_id=?",
                               (aid, fan, mid)).fetchone()[0] or 0 for fan, mid in rows)
    finally:
        con.close()


def _p95_of(xs: list[float]) -> float | None:
    return sorted(xs)[min(len(xs) - 1, int(len(xs) * 0.95))] if xs else None


def _p95(ctx, key: str, ms: float, n: int) -> None:
    for metric, v in (("p95_vs_last_green", ms), ("p95_vs_last_green_n", n)):
        cur = dict(ctx.report.metrics.get(metric) or {})
        cur[key] = v
        ctx.metric(metric, cur)


async def _latency(ctx) -> None:
    if not ctx.ui:
        ctx.skip(CLICK_SETTLED, "--no-ui: nothing to click")
        return
    from slop.actors import ui

    names = [c["nickname"] for c in ctx.world.data["creators"]]
    settled: list[float] = []
    fails: list[dict] = []
    async with ui.owner_browser(ctx, through=THROUGH) as page:
        inflight: dict = {}
        last_end = [time.monotonic()]

        def relevant(req) -> bool:
            p = urlsplit(req.url).path
            if p.startswith("/admin/perflog") or p.startswith("/events") or p in ui.OF_LIVE_PATHS:  # held: never ends
                return False
            return p.startswith("/admin/") or any(t.fullmatch(p) for t in THROUGH)

        def start(req) -> None:
            if relevant(req):
                inflight[req] = time.monotonic()

        def done(req) -> None:
            if inflight.pop(req, None) is not None:
                last_end[0] = time.monotonic()

        page.on("request", start)
        page.on("requestfinished", done)
        page.on("requestfailed", done)
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        strip = page.get_by_role("tablist", name="Creator tabs")
        await strip.wait_for(timeout=90_000)
        await _until(lambda: not inflight and time.monotonic() - last_end[0] > 2.0, 60, 0.1)
        trigger = await ui.shot(ctx, page, "trigger-strip")
        order = [names[i % len(names)] for i in range(1, CLICKS + 1)]
        for nick in order:
            tab = strip.get_by_role("tab").filter(has_text=nick).first
            await tab.scroll_into_view_if_needed()
            await _until(lambda: not inflight and time.monotonic() - last_end[0] > IDLE_MS / 1000, 15, 0.05)
            t0 = time.monotonic()
            await tab.click()
            sel_at = [None]

            async def selected() -> bool:
                if sel_at[0] is None and await tab.get_attribute("aria-selected") == "true":
                    sel_at[0] = time.monotonic()
                return sel_at[0] is not None

            end = t0 + CLICK_TIMEOUT_S
            ok = False
            while time.monotonic() < end:
                if await selected() and not inflight and time.monotonic() - max(last_end[0], sel_at[0]) >= IDLE_MS / 1000:
                    ok = True
                    break
                await asyncio.sleep(0.05)
            if ok:
                settled.append(round((max(last_end[0], sel_at[0]) - t0) * 1000, 1))
            else:
                fails.append({"tab": nick, "selected": sel_at[0] is not None, "inflight": len(inflight)})
        end_shot = await ui.shot(ctx, page, "settled-strip")
    ctx.check(CLICK_SETTLED, len(settled) == CLICKS and not fails, clicks=CLICKS, settled_ms=settled, fails=fails,
              screenshots=[trigger, end_shot])
    if settled:
        p95 = sorted(settled)[min(len(settled) - 1, int(len(settled) * 0.95))]
        _p95(ctx, "click_settled_ms", p95, len(settled))
        ctx.metric("click_settled", {"ms": settled, "median_ms": statistics.median(settled), "p95_ms": p95})
