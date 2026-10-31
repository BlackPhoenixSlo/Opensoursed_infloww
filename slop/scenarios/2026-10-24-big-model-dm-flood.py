"""Big model accounts under a DM flood: 5 Agencies, 20 Creators, 3 of them big
(2k / 10k / 50k fans at small / medium / huge). Fans DM through the OF pump
boundary at an open-loop rate that ramps per big Creator through stages
(--dms-per-min=50,100,200, each held --stage-s seconds; normal Creators ~5/min),
with ~3% tips, ~2% PPV purchases and typing frames mixed in. Meanwhile --users
chatters work the inbox (head page, thread, mark read, reply) and the owner's
browser holds a live tab per page in TABS (the All Models inbox, 5 models incl. the
3 big; two popout chats; Group), each with its own /events stream.

Correctness invariants (any FAIL here is a bug): every frame accepted; zero
persist drops; every DM in event_inbox and in `messages`; every DM reached its
Agency's /events stream and no other Agency's; per-thread order on every stream;
the inbox tab got every DM of its 5 models with no `resync`; unread counts per
thread match (exact for threads no chatter touched, bounded for the rest); tips
and PPV purchases each one ledger row; every chatter reply one outbound row;
every marker DM renders in the tabs that show its thread; no browser tab crashed;
no 5xx anywhere; a manual send's chat-list bump (lib/chatsCache in node, on the
owner's real head pages and a real send per model) heads the sent fan's row in its
Creator's caches, fan id string or number, other Creators' untouched. Whether each
marker also became an All Models list row is a budget (list-upd), not an invariant:
the list's pages come from OnlyFans' /chats, held in a slop run, so only an app
build that inserts live rows can show it.

Budgets (FAIL is red but marked [budget]; never loosened): per stage, p95 per
relay route, SSE lag (injection -> stream receipt) for the direct listener and
the browser tab, marker DM -> rendered in its open thread, long tasks per minute, tab heap. The
known relay defect (CLAUDE.md: p95 ~5 s at 200 concurrent DMs vs 750 ms) is
labelled where the measured value matches it.

Break-it-once: sse-fanout-reorders-within-thread (fan-out delivers a fan's DM
after their next one). Nothing is lost and the DB is right, so only the
per-thread order check on the streams can catch it.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeout

from slop.actors import chatter, fan_dm, manager, ui
from slop.lib import app_ts
from slop.lib.chats_cache_faults import SEND_BUMP
from slop.lib.events_faults import BUS_BACKOFF, BUS_NOTHING_DROPPED, BUS_ORDER

PROFILE = "multi_agency_big_models"
UI = True
FAULT = "sse-fanout-reorders-within-thread"

STAGE_S = {"small": 30, "medium": 120, "huge": 180}
P95_BUDGET_MS = {
    "POST /__slop/of-ws-frame": 750,
    "GET /admin/chats/recent": 500,
    "GET /admin/messages/:id/:id": 500,
    "POST /admin/messages/:id/:id/mark-read": 500,
    "POST /api/of/v2/chats/:id/messages": 750,
}
# CLAUDE.md: "relay p95 at 200 concurrent DMs is ~5s vs the 750ms budget".
KNOWN_DEFECT = {"POST /__slop/of-ws-frame": 5000}
SSE_LAG_BUDGET_MS = 1000       # relay -> a direct /events listener
TAB_LAG_BUDGET_MS = 2000       # relay -> Next proxy -> a browser tab's EventSource
ROW_UPDATE_BUDGET_MS = 3000    # marker DM injected -> its text rendered in the open popout / group thread
LONG_TASKS_PER_MIN_BUDGET = 30  # per tab
HEAP_BUDGET_MB = 400           # per tab
# The relay is one Python process (one event loop, the GIL): its mean CPU per stage
# (ps, lib/procmon.py), 100% = one core. 80 leaves 20% headroom below one core;
# summary.txt also shows the event-loop thread's own share.
CPU_BUDGET_PCT = 80
# Write-storm check (.scratch/fleet-sharding/03-write-storm.md). A 2 s whole-process
# stall (SIGSTOP of the relay's process group: a CPU-starved VPS, a long GC pause, a
# slow disk) in the second stage piles up every in-flight chatter request at once.
# Before the bounded DB pool, that pile-up opened one SQLite connection (one thread
# plus a schema parse) per request and turned into a self-sustaining storm: 3-9 cores
# and multi-second p95 for 10-60 s (measured). The relay must be back to normal soon after.
# Write transactions per action (write_telemetry writer labels). A reply is its
# outbound row + chat preview + yield cooldown in ONE transaction, plus the audit
# row; a mark-read is its audit row only (the unread clear rides the OF-cache
# writer's batch). Before the writer: 3 and 2 (run ...-0d27 / ...-c205). The 0.05
# is for one-off writes a first request makes (one per Agency at small: 235 txns for
# 230 reads), not for a per-call one.
REPLY_TXNS_MAX = 2.05
READ_TXNS_MAX = 1.05
CHECK_OF_WRITER = ("OF-cache writer: every op committed, and no DM / event_inbox write transaction "
                   "outside its batches")
CHECK_READ_TXNS = f"mark-read: <= {READ_TXNS_MAX:g} write transaction per call (its audit row)"
CHECK_REPLY_TXNS = f"reply: <= {REPLY_TXNS_MAX:g} write transactions per reply (row + preview + cooldown, audit)"
STALL_S = 2.0                  # --stall-s=0 turns the stall off; off by default below 60 s stages
STALL_AT_FRAC = 0.25           # into the second stage
RECOVER_WINDOW_S = 30          # from SIGCONT
STORM_CPU_MAX_PCT = 300        # relay process CPU, every second of the window (healthy max ~130; storm 400-1100)
STORM_REQ_P95_MS = 750         # actor requests SENT after SIGCONT and ended in the window
# Production write-path telemetry (service/db/write_telemetry.py): one JSON line per
# interval in relay.log (docker logs in production). Its counts must equal what was injected,
# its lines must come on time, and its drop counters must read 0.
TELEMETRY_S = float(os.environ.get("CHATTERLY_WRITE_TELEMETRY_S", "60") or 0)
TELEMETRY_SLACK_S = 5          # a line's span may be off its interval by this (loop lag, the 2 s stall)
MARKER_ID_BASE = 9_690_000_000_000
TABS = ("inbox", "popout-a", "popout-b", "group")
# The app's EventBus in node (lib/events_ts.mjs) on Agency 0's real /events while the load
# runs: a socket drop with 6 refused connects (the browser's own reconnect + 5 bus retries,
# so the backoff reaches its cap), one with 2 (it starts again at the minimum), then a pause.
EVENTS_TS = Path(__file__).resolve().parents[1] / "lib" / "events_ts.mjs"
CHATS_CACHE_TS = Path(__file__).resolve().parents[1] / "lib" / "chats_cache_ts.mjs"
SEND_BUMP_LIMIT, SEND_BUMP_PAGE = 100, 20  # head page read, rows per cache page
BUS_PLAN = {"scope": "all", "warm_ms": 2000, "outages": [6, 2], "pause_ms": 3000, "tail_ms": 3000,
            "reconnect_ms": 3000, "scale": 100, "timeout_ms": 30000}


def pct(xs, q=0.95):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * q))], 1) if xs else None


async def loop_lag(samples: list[float], stop: asyncio.Event) -> None:
    """How late this driver's own event loop wakes (qualifies every latency it measures)."""
    while not stop.is_set():
        t = time.perf_counter()
        await asyncio.sleep(0.1)
        samples.append((time.perf_counter() - t - 0.1) * 1000)


def live(page) -> bool:
    return page.slop["crashed"] is None


TAB_CALL_S = 60  # a tab whose main thread can't answer an evaluate / screenshot in this is "stalled"


async def tab_call(page, what: str, fn, *a):
    """A tab call that a crashed renderer or a saturated main thread turns into None
    (recorded in page.slop["stalls"]) instead of ending the run."""
    if not live(page):
        return None
    t0 = time.time()
    try:
        return await asyncio.wait_for(fn(page, *a), TAB_CALL_S)
    except Exception as e:  # noqa: BLE001 — Playwright "Target crashed" / timeouts
        if live(page) and not isinstance(e, (asyncio.TimeoutError, PlaywrightTimeout)):
            raise
        page.slop.setdefault("stalls", []).append({"what": what, "at": t0 * 1000,
                                                   "waited_s": round(time.time() - t0, 1)})
        return None


def tab_digest(t: dict) -> dict:
    return {"handler_p95_ms": pct(t["handler"]), "handler_events": len(t["handler"]),
            "long_tasks": len(t["longTasks"]), "heap_mb": round((t["heap"] or 0) / 2**20, 1),
            "rows": t["rows"], "resync": t["resync"], "rx": len(t["rx"])}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    rates = [int(x) for x in str(ctx.param("dms_per_min", "50,100,200")).split(",")]
    stage_s = ctx.param("stage_s", STAGE_S[ctx.scale])
    normal_dpm = ctx.param("normal_dpm", 5.0)
    # Off below 60 s stages (small): there a 2 s freeze alone holds >5% of a stage's requests.
    stall_s = ctx.param("stall_s", STALL_S if stage_s >= 60 else 0.0)
    stall: dict = {}
    creators, fans = w.data["creators"], w.data["fans"]
    agencies = w.data["agencies"]
    big = [c["id"] for c in creators if c["big"]]
    ui_models = [c["id"] for c in creators if c["owner"] == agencies[0]["user_id"]]
    owner_of = {c["id"]: c["owner"] for c in creators}
    seeded_unread = {(t["account_id"], t["fan_id"]): t["unread"] for t in w.data["threads"]}
    rng = w.rng("scenario:big-model-dm-flood")

    # Marker fans (one per big Creator, all with a thread): only markers write to them
    # and no chatter touches them, so their rows and unread counts are exact.
    threaded = {aid: [f for f in fans[aid] if (aid, f["id"]) in seeded_unread] for aid in big}
    marker_fans = [rng.choice(threaded[aid]) for aid in big]
    reserved = {(f["account_id"], f["id"]) for f in marker_fans}
    pools = {aid: [f for f in fl if (aid, f["id"]) not in reserved] for aid, fl in fans.items()}

    listeners = {a["user_id"]: manager.SseListener(a["http"].share()) for a in agencies}
    for li in listeners.values():
        await li.start()
    inject_http = ctx.owner.share(limits=200)
    paced = fan_dm.Paced(inject_http, pools, w.rng("scenario:big-model-dm-flood:fans"))
    weights = {c["id"]: (6.0 if c["big"] else 1.0) for c in creators}
    pools_by_agency = {a["user_id"]: a["http"].share(limits=max(10, ctx.users)) for a in agencies}
    chat_sessions = {c["id"]: pools_by_agency[c["owner"]] for c in creators}
    chatters = chatter.Chatters(chat_sessions, weights, w.rng("scenario:big-model-dm-flood:chatters"),
                                avoid=reserved)
    ctx.metric("world", {"agencies": len(agencies), "creators": len(creators), "big": big,
                         "ui_models": ui_models, "fans": {aid: len(fl) for aid, fl in fans.items()},
                         "threads": len(w.data["threads"]),
                         "marker_fans": [(f["account_id"], f["id"]) for f in marker_fans]})

    lag_samples: list[float] = []
    lag_stop = asyncio.Event()
    lag_task = asyncio.create_task(loop_lag(lag_samples, lag_stop))
    marker_ids = itertools.count(MARKER_ID_BASE)
    markers: list[dict] = []
    stages: list[dict] = []
    tab_takes: dict[str, dict[str, dict]] = {}
    final_rx: dict[str, dict] = {}
    ui_read: set[tuple] = set()
    ui_read_calls = [0]   # the tabs' own mark-read POSTs (2xx), for the txns-per-call check
    ui_reloads: list[str] = []

    bus_task: asyncio.Task | None = None
    bus_out: dict = {"error": "the load never started"}
    cm = ui.owner_tabs(ctx, len(TABS)) if ctx.app else None
    pages = await cm.__aenter__() if cm else None
    try:
        tab = dict(zip(TABS, pages)) if pages else {}
        if tab:
            a, b, c3 = marker_fans
            urls = {
                "inbox": "/messages-pro",
                "popout-a": f"/messages-pro/{a['account_id']}/{a['id']}",
                "popout-b": f"/messages-pro/{b['account_id']}/{b['id']}",
                "group": "/group?slots=" + ",".join(f"{f['account_id']}:{f['id']}" for f in marker_fans),
            }
            t0 = time.time()
            for name, path in urls.items():  # sequential: next dev compiles each route once
                await tab[name].goto(f"{ctx.app}{path}", wait_until="domcontentloaded", timeout=300_000)
            # next dev compiles each route on first hit; a tab whose chunk load stalls
            # meanwhile stays blank (until webpack's 120 s chunk timeout, then the error
            # boundary: "Loading chunk ... failed"). A tab counts as rendered once it
            # shows its rows and no error boundary; else reload it.
            ready = {n: "[data-chat-row]" for n in TABS}

            async def rendered(n):
                if await tab[n].get_by_text("Something broke.").count():
                    return False
                try:
                    await tab[n].locator(ready[n]).first.wait_for(timeout=45_000)
                except PlaywrightTimeout:
                    return False
                return not await tab[n].get_by_text("Something broke.").count()
            for _ in range(3):
                broken = [n for n, ok in zip(TABS, await asyncio.gather(*(rendered(n) for n in TABS))) if not ok]
                if not broken:
                    break
                for n in broken:
                    ui_reloads.append(n)
                    await tab[n].reload(wait_until="domcontentloaded", timeout=300_000)
            await asyncio.sleep(3)
            broken = [n for n in TABS if await tab[n].get_by_text("Something broke.").count()
                      or not await tab[n].locator(ready[n]).count()]
            ctx.check("every tab rendered before the load (rows shown, no error boundary)", not broken,
                      broken=broken, reloads=ui_reloads)
            for name in TABS:
                await ui.take(tab[name])  # drop the page-load samples
            ctx.metric("ui_warm_seconds", round(time.time() - t0, 1))

        paced.rates = {c["id"]: normal_dpm for c in creators if not c["big"]}
        paced.start()
        chatters.start(ctx.users)
        bus_task = asyncio.create_task(event_bus_run(ctx, agencies[0]))
        for i, rate in enumerate(rates):
            st = {"name": f"s{i + 1}-{rate}pm", "rate": rate, "t0": time.time() * 1000}
            ctx.rec.stage = paced.stage = st["name"]
            paced.rates.update({aid: float(rate) for aid in big})
            if i == 1 and stall_s > 0:
                await asyncio.sleep(stage_s * STALL_AT_FRAC)
                stall = await stall_relay(ctx, stall_s)
                await asyncio.sleep(max(0.0, stage_s * (0.5 - STALL_AT_FRAC) - stall_s))
            else:
                await asyncio.sleep(stage_s / 2)
            for f in marker_fans:  # one marker DM per big Creator, watched where its thread is open
                text = f"slop marker {st['name']} {f['account_id'][-4:]}"
                watchers = [n for n in ("inbox", "popout-a", "popout-b", "group")
                            if n in tab and (n in ("inbox", "group")
                                             or urls[n].endswith(f"/{f['account_id']}/{f['id']}"))]
                watchers = [n for n in watchers if live(tab[n])]
                await asyncio.gather(*(tab_call(tab[n], "watch", ui.watch, text, 90_000) for n in watchers))
                mid = next(marker_ids)
                t_inj = time.time() * 1000
                r = await fan_dm.inject(inject_http, f["account_id"], fan_dm.frame(mid, f, text))
                markers.append({"stage": st["name"], "account_id": f["account_id"], "fan_id": f["id"],
                                "message_id": mid, "text": text, "t0": t_inj, "status": r.status_code,
                                "watchers": watchers})
            await asyncio.sleep(stage_s / 2)
            st["t1"] = time.time() * 1000
            # Between stages nothing is attributed to a stage: a slow tab read here must
            # not stretch the stage it follows (the load keeps running at its rate).
            ctx.rec.stage = paced.stage = None
            st["relay"] = (await ctx.owner.get("/__slop/stats")).json()
            if tab:
                got = await asyncio.gather(*(tab_call(tab[n], "take", ui.take) for n in TABS))
                takes = dict(zip(TABS, got))
                tab_takes[st["name"]] = {n: t for n, t in takes.items() if t is not None}
                # Kept as they come: a tab that crashes later must not take these with it.
                ctx.metric(f"tabs {st['name']}", {n: tab_digest(t) for n, t in tab_takes[st["name"]].items()})
                await tab_call(tab["inbox"], "screenshot", lambda p, nm: ui.shot(ctx, p, nm, 55_000),
                               f"{st['name']}-all-models-inbox")
            stages.append(st)
        ctx.rec.stage = None
        bus_out = await bus_task
        await chatters.stop()
        await paced.stop()
        quiet = await manager.quiesce(ctx.owner, timeout=300)
        await asyncio.sleep(2.0)  # SSE tail
        if tab:
            for m in markers:
                m["seen"] = {n: await tab_call(tab[n], "seen", ui.seen, m["text"]) for n in m["watchers"]}
            final_rx = {n: t["rx"] for n in TABS if (t := await tab_call(tab[n], "take", ui.take)) is not None}
            for n in TABS:  # after the load: the stable end state of every tab
                await tab_call(tab[n], "screenshot", lambda p, nm: ui.shot(ctx, p, nm, 55_000), f"end-{n}")
            crashed = {}
            for n in TABS:
                at = tab[n].slop["crashed"]
                if at is not None:
                    crashed[n] = next((st["name"] for st in stages if st["t0"] <= at <= st.get("t1", at)),
                                      "after the stages" if stages and at > stages[-1]["t1"] else "warm-up")
            ctx.check("no browser tab crashed", not crashed, crashed=crashed)
            stalls = {n: tab[n].slop.get("stalls", []) for n in TABS if tab[n].slop.get("stalls")}
            ctx.check(f"every tab answered every probe/screenshot within {TAB_CALL_S}s (main thread not saturated)",
                      not stalls, budget=True, stalls={n: [(x["what"], next(
                          (st["name"] for st in stages if st["t0"] <= x["at"] <= st["t1"] + TAB_CALL_S * 1000),
                          "after")) for x in v] for n, v in stalls.items()})
            # Threads the UI itself marked read (an open ChatSurface does, on open).
            for p in pages:
                for s_, u in p.slop["statuses"]:
                    parts = urlsplit(u).path.split("/")
                    if s_ < 300 and parts[-1] == "mark-read" and len(parts) >= 5:
                        ui_read.add((parts[-3], int(parts[-2])))
                        ui_read_calls[0] += 1
            relay_5xx = [u for p in pages for s, u in p.slop["statuses"] if s >= 500 and "/api/of/" not in u]
            ctx.check("no 5xx in the browser sessions", not relay_5xx, count=len(relay_5xx), sample=relay_5xx[:5])
            ctx.metric("ui", {"held_of_reads": len(pages[0].slop["held_of_reads"]),
                              "offhost_aborted": len(pages[0].slop["offhost_aborted"])})
    finally:
        if bus_task is not None and not bus_task.done():
            bus_task.cancel()
        await chatters.stop()  # idempotent; on a crash, stop the load before its clients close
        if hasattr(paced, "_runners"):
            await paced.stop()
        if cm:
            await cm.__aexit__(None, None, None)
        lag_stop.set()
        await lag_task
        for li in listeners.values():
            await li.stop()
        await inject_http.aclose()
        for h in pools_by_agency.values():
            await h.aclose()

    ctx.metric("markers", markers)
    assess_event_bus(ctx, bus_out, listeners[agencies[0]["user_id"]])
    await assess(ctx, w, paced, chatters, listeners, markers, stages, tab_takes, final_rx, quiet,
                 seeded_unread, owner_of, ui_models, big, lag_samples, ui_read, tab)
    assess_stall(ctx, stall)
    await assess_telemetry(ctx, paced.sent + [m for m in markers if m["status"] < 300], quiet,
                           chatters.actions, ui_read_calls[0])
    await assess_send_bump(ctx, ui_models)


async def assess_send_bump(ctx, models: list[str]) -> None:
    """The send path's chat-list bump (lib/chats_cache_ts.mjs, the app's lib/chatsCache in node) on
    the owner's real head pages after the load, and one real send per model to its last row's fan.
    Last of all: the sends add outbound rows the reply and telemetry checks would otherwise count."""
    rows, sends = {}, []
    try:
        for aid in models:
            rows[aid] = await manager.recent_chats(ctx.owner, aid, SEND_BUMP_LIMIT)
            if len(rows[aid]) < 2:
                continue
            fan = rows[aid][-1]["withUser"]["id"]
            text = f"slop send bump {aid[-4:]}"
            r = await ctx.owner.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                     json={"text": text})
            sends.append({"accountId": aid, "fanId": fan, "text": text, "status": r.status_code,
                          "echo": r.json() if r.status_code < 300 else None})
        res = await app_ts.run(ctx, CHATS_CACHE_TS, {"limit": SEND_BUMP_LIMIT, "page": SEND_BUMP_PAGE,
                                                     "models": rows, "sends": sends})
        ways, out = res["ways"], res["cases"]
    except Exception as e:  # noqa: BLE001
        ctx.check(SEND_BUMP, False, error=f"{type(e).__name__}: {e}"[:1500])
        return
    sent_text = {s["accountId"]: s["text"] for s in sends}

    def bumped(r, v) -> bool:  # the fan's one row heads the cache with the sent text, nothing else moved
        return (v["head"] == [r["accountId"], r["fanId"]] and v["copies"] == 1 and v["untouched"]
                and v["text"] == sent_text[r["accountId"]] and v["before"] == v["after"])

    bad = [r for r in out if not (bumped(r, r["own"]) and bumped(r, r["all"]) and not r["others"])]
    failed = [s for s in sends if s["status"] >= 300]
    ctx.check(SEND_BUMP, bool(sends) and bool(ways) and not failed and len(out) == len(ways) * len(sends)
              and not bad,
              sends=len(sends), cases=len(out), failed_sends=[(s["accountId"], s["status"]) for s in failed],
              wrong=len(bad), sample=bad[:3])


async def event_bus_run(ctx, agency: dict) -> dict:
    """lib/events_ts.mjs on the Agency's session: the app's real EventBus through BUS_PLAN.
    A harness failure comes back as {"error"} (the bus checks fail on it), never a crashed run."""
    cookie = "; ".join(f"{k}={v}" for k, v in agency["http"].c.cookies.items())
    try:
        return await app_ts.run(ctx, EVENTS_TS, {**BUS_PLAN, "base": ctx.relay, "cookie": cookie})
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:1500]}


def assess_event_bus(ctx, out: dict, listener) -> None:
    """The bus's listeners against the relay's own order: the Agency's direct /events listener
    (no reconnects) got every DM in relay order. The bus's DMs must be exactly the span of that
    order from its first DM to its last (nothing dropped, none twice, no resync), in the same
    order; and the retry delays it armed must be RETRY_MIN doubling to the RETRY_MAX cap through
    the first outage, then RETRY_MIN again after a socket opened."""
    ctx.metric("event_bus", {k: v for k, v in out.items() if k != "got"} | {"got": len(out.get("got", []))})
    if "error" in out:
        for name in (BUS_NOTHING_DROPPED, BUS_ORDER, BUS_BACKOFF):
            ctx.check(name, False, error=out["error"])
        return
    got, relay = out["got"], listener.message_ids
    pos = {m: i for i, m in enumerate(relay)}
    seen = [m for m in got if m in pos]
    span = relay[min(pos[m] for m in seen):max(pos[m] for m in seen) + 1] if seen else []
    missing = sorted(set(span) - set(got))
    resumed = sum("last_event_id=" in u for u in out["opens"])
    ctx.check(BUS_NOTHING_DROPPED,
              bool(span) and not missing and len(got) == len(set(got)) and len(seen) == len(got)
              and not out["resync"] and out["refused"] == sum(BUS_PLAN["outages"])
              and resumed == sum(BUS_PLAN["outages"]) + 1,
              got=len(got), span=len(span), missing=len(missing), sample=missing[:5],
              duplicates=len(got) - len(set(got)), not_on_relay_stream=len(got) - len(seen),
              resync=out["resync"], refused=out["refused"], reopened_from_last_id=resumed)
    bad = next((i for i in range(1, len(seen)) if pos[seen[i]] < pos[seen[i - 1]]), None)
    ctx.check(BUS_ORDER, bool(seen) and bad is None, compared=len(seen),
              first_out_of_order=None if bad is None else {"at": bad, "got": seen[bad], "after": seen[bad - 1]})
    lo, hi = out["consts"]["retry_min_ms"], out["consts"]["retry_max_ms"]
    want: list[int] = []
    for n in BUS_PLAN["outages"]:
        ms = lo
        for _ in range(n):
            want.append(ms)
            ms = min(ms * 2, hi)
    ctx.check(BUS_BACKOFF, out["retries"] == want and max(out["retries"], default=0) <= hi,
              armed=out["retries"], want=want, cap_ms=hi)


def telemetry_lines(path) -> list[dict]:
    """The relay's write_telemetry JSON lines, in order (relay.log = what docker logs holds)."""
    out = []
    for line in path.read_text(errors="replace").splitlines():
        i = line.find(" write_telemetry {")
        if i >= 0:
            out.append(json.loads(line[i + len(" write_telemetry "):]))
    return out


async def assess_telemetry(ctx, dms: list[dict], quiet: dict, actions: dict, ui_reads: int) -> None:
    """The production telemetry line, read back from relay.log after a forced flush:
    on time, counts equal to what was injected (frames: every hook frame; DMs per
    Creator), every drop counter 0, and the write transactions per action: the
    OF-cache rows (DMs, read state) commit through the OF-cache writer's batches
    and a reply is one transaction of its own plus its audit row. Plus a summary
    table of what it measured."""
    cadence = f"write_telemetry lines: one every {TELEMETRY_S:g}s (+-{TELEMETRY_SLACK_S}s) through the run"
    counts = "write_telemetry lines: frames and DMs per account == injected"
    drops = "write_telemetry lines: every drop counter 0 (queue_full, persist_error, transcode_exception)"
    if TELEMETRY_S <= 0:
        for name in (cadence, counts, drops, CHECK_OF_WRITER, CHECK_READ_TXNS, CHECK_REPLY_TXNS):
            ctx.skip(name, "CHATTERLY_WRITE_TELEMETRY_S=0 (telemetry off, e.g. the overhead A/B)")
        return
    flushed = (await ctx.owner.post("/__slop/telemetry-flush", json={})).json().get("line")
    await asyncio.sleep(0.5)  # the log line reaches relay.log (stderr, line-buffered)
    lines = telemetry_lines(ctx.out / "relay.log")
    ivl = [x for x in lines if x["reason"] == "interval"]
    span = sum(x["s"] for x in lines)
    off = [x["s"] for x in ivl if abs(x["s"] - TELEMETRY_S) > TELEMETRY_SLACK_S]
    late_flush = bool(lines) and lines[-1]["reason"] == "flush" and lines[-1]["s"] > TELEMETRY_S + TELEMETRY_SLACK_S
    detail = {"lines": len(lines), "interval_lines": len(ivl), "span_s": round(span, 1),
              "expected_interval_lines": int(span // TELEMETRY_S), "off_spans_s": off[:5]}
    if flushed is None or not lines or lines[-1]["reason"] != "flush":
        ctx.check(cadence, False, **detail, error="no flush line in relay.log")
    elif span < TELEMETRY_S:
        ctx.skip(cadence, f"run shorter than one interval ({span:.0f}s)")
    else:
        ctx.check(cadence, not off and not late_flush and len(ivl) >= int(span // TELEMETRY_S), **detail)

    got_f = sum(x["in"]["frames"] for x in lines)
    got_d: dict[str, int] = {}
    for x in lines:
        for aid, a in x["in"]["acct"].items():
            got_d[aid] = got_d.get(aid, 0) + a["d"]
    want_d: dict[str, int] = {}
    for d in dms:
        want_d[d["account_id"]] = want_d.get(d["account_id"], 0) + 1
    bad = {aid: (got_d.get(aid, 0), n) for aid, n in want_d.items() if got_d.get(aid, 0) != n}
    bad |= {aid: (n, 0) for aid, n in got_d.items() if aid not in want_d and n}
    ctx.check(counts, got_f == quiet.get("received") and not bad,
              frames=got_f, received=quiet.get("received"), dms=sum(got_d.values()), injected_dms=len(dms),
              wrong_accounts=dict(list(bad.items())[:5]))

    total: dict[str, int] = {}
    for x in lines:
        for k, v in x["drops"].items():
            total[k] = total.get(k, 0) + v
    cum = lines[-1]["drops_cum"] if lines else {}
    ctx.check(drops, bool(lines) and not any(total.values()) and not any(cum.values())
              and quiet.get("persist_drops") == 0,
              per_reason=total, drops_cum=cum, persist_drops=quiet.get("persist_drops"))

    # Write transactions per action, by the line's writer labels.
    txns = {}
    for x in lines:
        for wn, w in x["w"].items():
            txns[wn] = txns.get(wn, 0) + w["n"]
    ow = {k: sum(x.get("ow", {}).get(k) or 0 for x in lines) for k in ("batches", "ops", "merged", "failed")}
    outside = {wn: n for wn, n in txns.items() if wn in ("persist", "transcode")}
    ctx.check(CHECK_OF_WRITER, bool(ow["batches"]) and not any(outside.values()) and not ow["failed"],
              writer=ow, outside=outside, frames=quiet.get("received"),
              txns_per_frame=round(ow["batches"] / max(1, quiet.get("received") or 0), 3))
    reads = actions.get("read", 0) + ui_reads
    read_txns = txns.get("http:POST /admin/messages/{}/{}/mark-read", 0)
    ctx.check(CHECK_READ_TXNS, reads > 0 and read_txns <= READ_TXNS_MAX * reads,
              txns=read_txns, calls=reads, per_call=round(read_txns / max(1, reads), 3), max=READ_TXNS_MAX)
    replies = actions.get("reply", 0)
    reply_txns = txns.get("http:POST /api/of/v2/chats/{}/messages", 0)
    ctx.check(CHECK_REPLY_TXNS, replies > 0 and reply_txns <= REPLY_TXNS_MAX * replies,
              txns=reply_txns, replies=replies, per_reply=round(reply_txns / max(1, replies), 3),
              max=REPLY_TXNS_MAX)

    # What the line measured (for sizing the write path), over the whole run.
    writers: dict[str, dict] = {}
    for x in lines:
        for wn, w in x["w"].items():
            a = writers.setdefault(wn, {"n": 0, "wait_p95": 0.0, "hold_p95": 0.0, "max": 0.0, "hold_s": 0.0,
                                        "locked": 0})
            a["n"] += w["n"]
            a["locked"] += w["locked"]
            a["hold_s"] += w["hold_sum_ms"] / 1000
            for k, t in (("wait_p95", w["wait"]), ("hold_p95", w["hold"])):
                if t:
                    a[k] = max(a[k], t[1])
                    a["max"] = max(a["max"], t[2])
    top = sorted(writers.items(), key=lambda kv: -kv[1]["hold_s"])[:12]
    peak = lambda key: max((x[key[0]][key[1]] or 0 for x in lines), default=0)  # noqa: E731
    acct_peaks = {}
    for x in lines:
        for aid, a in x["in"]["acct"].items():
            p_ = acct_peaks.setdefault(aid, [0, 0])
            p_[0], p_[1] = max(p_[0], a["d1"]), max(p_[1], a["d10"])
    summary = {"lines": len(lines), "lock_max": max((x["lock"] or 0 for x in lines), default=0),
               "lock_mean": round(sum(x["lock"] or 0 for x in lines) / max(1, len(lines)), 4),
               "txns_total": sum(txns.values()),
               "q_max": peak(("q", "max")), "q_age_ms_max": peak(("q", "age_ms")),
               "batch_max": peak(("q", "batch_max")), "pool_out_max": peak(("pool", "out_max")),
               "pool_open_max": peak(("pool", "open_max")),
               "sse_lag_p95_max": max(((x["sse"]["lag"] or [0, 0])[1] for x in lines), default=0),
               "dm_peaks_1s_10s": dict(sorted(acct_peaks.items(), key=lambda kv: -kv[1][1])[:5]),
               "writers": dict(top),
               "of_writer": {**ow, "batch_max": peak(("ow", "batch_max")), "q_max": peak(("ow", "q_max")),
                             "flush_p95_ms_max": max(((x.get("ow", {}).get("flush_ms") or [0, 0])[1]
                                                      for x in lines), default=0),
                             "age_p95_ms_max": max(((x.get("ow", {}).get("age_ms") or [0, 0])[1]
                                                    for x in lines), default=0)}}
    ctx.metric("write_telemetry", summary)
    ctx.note("", f"write_telemetry (measured by the product's own line; {len(lines)} lines, relay.log): "
                 f"lock busy max {summary['lock_max']:.0%} (mean {summary['lock_mean']:.1%}) of an interval, "
                 f"{summary['txns_total']} write txns, persist queue max {summary['q_max']} "
                 f"(oldest {summary['q_age_ms_max']:.0f}ms), batch max {summary['batch_max']}, pool out/open max "
                 f"{summary['pool_out_max']}/{summary['pool_open_max']}, SSE lag p95 max {summary['sse_lag_p95_max']}ms",
             "  writer                                   txns  wait-p95  hold-p95     max   hold-s  locked",
             *(f"  {wn[:40]:<40} {a['n']:>5} {a['wait_p95']:>9} {a['hold_p95']:>9} {a['max']:>7} "
               f"{a['hold_s']:>8.1f} {a['locked']:>7}" for wn, a in top),
             "  (ms; per line p95, max over lines; hold-s = lock held, summed)",
             "  OF-cache writer: {batches} txns for {ops} ops ({merged} coalesced, {failed} failed), batch max "
             "{batch_max}, queue max {q_max}, flush p95 max {flush_p95_ms_max}ms, op age p95 max "
             "{age_p95_ms_max}ms; per reply {pr:.2f}, per mark-read {pm:.2f} txns".format(
                 **summary["of_writer"],
                 pr=reply_txns / max(1, replies), pm=read_txns / max(1, reads)),
             "  DM peaks per account (most in 1 s / 10 s): " + ", ".join(
                 f"{aid[-6:]}={p_[0]}/{p_[1]}" for aid, p_ in summary["dm_peaks_1s_10s"].items()))


async def stall_relay(ctx, seconds: float) -> dict:
    """Freeze the whole relay process group for `seconds` (SIGSTOP / SIGCONT). The load
    keeps coming: every chatter request and fan frame sent meanwhile waits on the socket."""
    import os
    import signal
    t0 = time.time()
    os.killpg(ctx.stack.relay_pid, signal.SIGSTOP)
    try:
        await asyncio.sleep(seconds)
    finally:
        os.killpg(ctx.stack.relay_pid, signal.SIGCONT)
    return {"t0": t0, "t1": time.time(), "seconds": seconds}


def assess_stall(ctx, stall: dict) -> None:
    """The 30 s after SIGCONT: every second of relay CPU, and the p95 of the actor
    requests sent after the relay resumed (the ones frozen in the stall are its own
    cost, not the recovery's), must stay within normal bounds: no storm."""
    name = (f"relay absorbs a {STALL_S:g}s stall: CPU <= {STORM_CPU_MAX_PCT}% every second and p95 <= "
            f"{STORM_REQ_P95_MS}ms for requests sent in the {RECOVER_WINDOW_S}s after (no SQLite connection storm)")
    if not stall:
        ctx.skip(name, "no stall (--stall-s=0, stages under 60 s, or fewer than 2 stages)")
        return
    lo, hi = stall["t1"], stall["t1"] + RECOVER_WINDOW_S
    mon = getattr(ctx, "mon", None)
    ivs = [iv for iv in (mon.intervals if mon else []) if lo - 0.5 <= iv.get("t0", 0) < hi]
    cpu = [iv["cpu_pct"] for iv in ivs]
    req = [ms for t, route, _st, ms in ctx.rec.timeline
           if t - ms / 1000 >= lo and t < hi and not route.startswith("GET /__slop")]
    detail = {"cpu_max_pct": max(cpu) if cpu else None, "cpu_p95_pct": pct(cpu), "cpu_samples": len(cpu),
              "req_p95_ms": pct(req), "requests": len(req), "stall_s": stall["seconds"],
              "threads_max": max((iv.get("threads") or 0 for iv in ivs), default=None),
              "db_conns_peak": max((iv.get("db_peak") or 0 for iv in ivs), default=None),
              "db_opened": sum(iv.get("db_new") or 0 for iv in ivs),
              "rss_max_mb": max((iv["rss_mb"] for iv in ivs), default=None)}
    ctx.metric("stall", {**stall, **detail})
    if len(cpu) < RECOVER_WINDOW_S // 2 or not req:
        ctx.check(name, None, **detail)
        return
    ctx.check(name, detail["cpu_max_pct"] <= STORM_CPU_MAX_PCT and detail["req_p95_ms"] <= STORM_REQ_P95_MS,
              budget=True, **detail)


async def assess(ctx, w, paced, chatters, listeners, markers, stages, tab_takes, final_rx, quiet,
                 seeded_unread, owner_of, ui_models, big, lag_samples, ui_read, tabs) -> None:
    dms = paced.sent + [m for m in markers if m["status"] < 300]  # every inbound chat message injected
    sent_ids = {d["message_id"] for d in dms}
    ctx.metric("load", {"dms": len(paced.sent), "tips": sum(d["kind"] == "tip" for d in paced.sent),
                        "purchases": len(paced.purchases), "typing": paced.typing, "markers": len(markers),
                        "failed": paced.failed, "shed": paced.shed, "chatter_actions": chatters.actions,
                        "threads_touched": len(chatters.touched),
                        "driver_loop_lag_p95_ms": pct(lag_samples), "driver_loop_lag_max_ms":
                            round(max(lag_samples), 1) if lag_samples else None})
    ctx.metric("relay_stats", quiet)

    # ── nothing dropped ──────────────────────────────────────────────
    ctx.check("every injected frame accepted, none shed", paced.failed == 0 and paced.shed == 0
              and all(m["status"] < 300 for m in markers), failed=paced.failed, shed=paced.shed)
    ctx.check("relay quiesced (all frames transcoded)", not quiet.get("timed_out"), stats=quiet)
    ctx.check("zero persist-queue drops", quiet.get("persist_drops") == 0, drops=quiet.get("persist_drops"))
    con = w.sql()
    try:
        # The frame's id is nested ({"api2_chat_message": {"id": ...}}), so event_inbox's
        # provider_event_id (top-level id/messageId/eventId) is NULL for it: read the payload.
        inbox_ids = {int(r[0]) for r in con.execute(
            "SELECT json_extract(payload_json, '$.api2_chat_message.id') FROM event_inbox "
            "WHERE event_type='api2_chat_message'") if r[0] is not None}
        inbox_purchases = con.execute("SELECT COUNT(*) FROM event_inbox WHERE event_type='purchase'").fetchone()[0]
        msg_rows = {(a, f, m) for a, f, m in con.execute(
            "SELECT account_id, fan_id, message_id FROM messages WHERE message_id >= ? AND direction='in'",
            (fan_dm.PACED_ID_BASE,))}
        unread_db = {(a, f): u for a, f, u in con.execute("SELECT account_id, fan_id, unread_count FROM chats")}
        tx = {(k, m) for k, m in con.execute(
            "SELECT kind, message_id FROM transactions WHERE message_id >= ?", (fan_dm.PACED_ID_BASE,))}
        replies = con.execute("SELECT COUNT(*) FROM messages WHERE direction='out' AND message_id >= ?",
                              (9_700_000_000_000,)).fetchone()[0]
    finally:
        con.close()
    miss_inbox = sent_ids - inbox_ids
    ctx.check("every DM is in event_inbox", not miss_inbox, missing=len(miss_inbox), of=len(sent_ids))
    ctx.check("every PPV purchase frame is in event_inbox", inbox_purchases == len(paced.purchases),
              rows=inbox_purchases, sent=len(paced.purchases))
    miss_msg = {(d["account_id"], d["fan_id"], d["message_id"]) for d in dms} - msg_rows
    ctx.check("every DM is a `messages` row in its thread", not miss_msg, missing=len(miss_msg),
              sample=sorted(miss_msg)[:3])
    tips = {d["message_id"] for d in paced.sent if d["kind"] == "tip"}
    ppv = {p["message_id"] for p in paced.purchases}
    ctx.check("every tip and PPV purchase is one ledger row",
              tips == {m for k, m in tx if k == "tip"} and ppv == {m for k, m in tx if k == "ppv"},
              tips=len(tips), tip_rows=sum(k == "tip" for k, _ in tx),
              ppv=len(ppv), ppv_rows=sum(k == "ppv" for k, _ in tx))
    ok_replies = chatters.actions["reply"]
    ctx.check("every chatter reply is one outbound `messages` row", replies == ok_replies,
              rows=replies, replies=ok_replies)

    # ── SSE: delivered, isolated, in order ───────────────────────────
    by_agency: dict[str, set[int]] = {}
    for d in dms:
        by_agency.setdefault(owner_of[d["account_id"]], set()).add(d["message_id"])
    missing = {u: len(ids - set(listeners[u].message_ids)) for u, ids in by_agency.items()}
    leaked = {u: len((set(li.message_ids) & sent_ids) - by_agency.get(u, set())) for u, li in listeners.items()}
    ctx.check("every DM reached its Agency's /events stream", not any(missing.values()), missing=missing)
    ctx.check("no DM reached another Agency's /events stream", not any(leaked.values()), leaked=leaked)
    thread_of = {d["message_id"]: (d["account_id"], d["fan_id"]) for d in dms}
    out_of_order, sample = 0, []
    for u, li in listeners.items():
        last: dict[tuple, int] = {}
        for mid in li.message_ids:
            key = thread_of.get(mid)
            if key is None:
                continue
            if mid < last.get(key, 0):
                out_of_order += 1
                if len(sample) < 3:
                    sample.append({"thread": key, "got": mid, "after": last[key]})
            last[key] = max(mid, last.get(key, 0))
    ctx.check("per-thread order preserved on every /events stream", out_of_order == 0,
              out_of_order=out_of_order, sample=sample)
    resyncs = {u[-6:]: li.events.get("resync", 0) for u, li in listeners.items()}
    ctx.check("no /events stream overflowed its 256-frame queue (resync)", not any(resyncs.values()),
              resync=resyncs)
    if "inbox" in final_rx:
        ui_ids = {d["message_id"] for d in dms if d["account_id"] in ui_models}
        got = {int(k) for k in final_rx["inbox"]}
        tab_resync = sum(t["resync"] for s in tab_takes.values() for t in s.values())
        ctx.check("the All Models tab received every DM of its 5 models, no resync",
                  not (ui_ids - got) and tab_resync == 0, missing=len(ui_ids - got), of=len(ui_ids),
                  resync=tab_resync)
        # A crashed or stalled tab is its own check; here, the tabs that could answer.
        sound = {n for n in TABS if live(tabs[n]) and not tabs[n].slop.get("stalls")}
        unseen = [m["text"] for m in markers if not all(m.get("seen", {}).get(n) for n in m["watchers"]
                                                        if n != "inbox" and n in sound)]
        ctx.check("every marker DM renders in each open tab showing its thread (popout, group)",
                  not unseen, unseen=unseen)
        in_list = sum(bool(m.get("seen", {}).get("inbox")) for m in markers)
        ctx.note(f"All Models list: {in_list}/{len(markers)} marker DMs rendered as list rows (measured).")
        if in_list < len(markers):
            ctx.note("  The list's pages come from OnlyFans' /chats (/api/of/v2/chats), held in a slop run; "
                     "an app build that only patches loaded pages leaves the list on its local seed.")

    # ── unread per thread ────────────────────────────────────────────
    inbound: dict[tuple, list[float]] = {}
    for d in dms:
        inbound.setdefault((d["account_id"], d["fan_id"]), []).append(d["t0"])
    exact_bad, bound_bad = [], []
    touched = set(chatters.touched) | ui_read
    for key, t0s in inbound.items():
        got_u = unread_db.get(key)
        seeded = seeded_unread.get(key, 0)
        if key not in touched:
            if got_u != seeded + len(t0s):
                exact_bad.append({"thread": key, "got": got_u, "want": seeded + len(t0s)})
        else:
            # A chatter's last read/reply time is known; a tab's mark-read time is not (lo 0).
            lo = 0 if key in ui_read else sum(t > chatters.last.get(key, float("inf")) for t in t0s)
            if got_u is None or not lo <= got_u <= seeded + len(t0s):
                bound_bad.append({"thread": key, "got": got_u, "lo": lo, "hi": seeded + len(t0s)})
    ctx.check("unread == seeded + injected for every thread no chatter or tab read", not exact_bad,
              wrong=len(exact_bad), threads=sum(k not in touched for k in inbound), sample=exact_bad[:3])
    ctx.check("unread within [DMs after the last chatter read/reply, seeded + injected] on read threads",
              not bound_bad, wrong=len(bound_bad), threads=sum(k in touched for k in inbound),
              ui_read=len(ui_read), sample=bound_bad[:3])
    api_bad = 0
    for aid in ui_models:
        rows = await manager.recent_chats(ctx.owner, aid, 100)
        for r in rows:
            key = (aid, r["withUser"]["id"])
            if key in inbound and key not in touched and \
                    r["unreadMessagesCount"] != seeded_unread.get(key, 0) + len(inbound[key]):
                api_bad += 1
    ctx.check("/admin/chats/recent head pages agree on unread (untouched threads)", api_bad == 0, wrong=api_bad)

    # ── per stage: budgets + the table ───────────────────────────────
    rows_out, worst = [], {}
    for st in stages:
        name = st["name"]
        http = ctx.rec.summary(name)
        sd = [d for d in paced.sent if d["stage"] == name]
        own = lambda d: listeners[owner_of[d["account_id"]]].received_at.get(d["message_id"])  # noqa: E731
        sse_lag = [own(d) - d["t0"] for d in sd if own(d) is not None]
        dropped = sum(own(d) is None for d in sd)
        rx = final_rx.get("inbox", {})
        tab_lag = [rx[str(d["message_id"])] - d["t0"] for d in sd
                   if d["account_id"] in ui_models and str(d["message_id"]) in rx]
        tk = tab_takes.get(name, {})
        minutes = (st["t1"] - st["t0"]) / 60000
        lt = {n: round(len(t["longTasks"]) / minutes, 1) for n, t in tk.items()}
        heap = {n: round((t["heap"] or 0) / 2**20, 1) for n, t in tk.items()}
        handler = [x for t in tk.values() for x in t["handler"]]
        row_upd = [v - m["t0"] for m in markers if m["stage"] == name
                   for n, v in (m.get("seen") or {}).items() if n != "inbox" and v]
        list_upd = [m["seen"]["inbox"] - m["t0"] for m in markers
                    if m["stage"] == name and (m.get("seen") or {}).get("inbox")]
        big_pm = round(sum(d["account_id"] in big for d in sd) / len(big) / minutes, 1)
        s = {"dms": len(sd), "dms_per_min_actual": round(len(sd) / minutes, 1), "dms_per_min_per_big": big_pm,
             "p95_ms": {r: http[r]["p95_ms"] for r in P95_BUDGET_MS if r in http},
             "n": {r: http[r]["n"] for r in P95_BUDGET_MS if r in http},
             "5xx": sum(v["5xx"] for v in http.values()),
             "sse_lag_p95_ms": pct(sse_lag), "sse_lag_max_ms": round(max(sse_lag), 1) if sse_lag else None,
             "dropped_sse": dropped, "tab_lag_p95_ms": pct(tab_lag),
             "handler_ms_p95": pct(handler), "handler_ms_max": round(max(handler), 1) if handler else None,
             "handler_events": len(handler), "long_tasks_per_min": lt, "heap_mb": heap,
             "inbox_rows": tk.get("inbox", {}).get("rows"), "row_update_ms": [round(x) for x in row_upd],
             "list_update_ms": [round(x) for x in list_upd],
             "persist_queue_depth_at_end": st["relay"].get("queue_depth")}
        st["m"] = s
        ctx.metric(f"stage {name}", s)
        rows_out.append(
            f"  {name:<9} {s['dms']:>5} {s['dms_per_min_actual']:>6} {big_pm:>6} "
            f"{s['p95_ms'].get('POST /__slop/of-ws-frame', '-'):>8} "
            f"{s['p95_ms'].get('GET /admin/chats/recent', '-'):>8} "
            f"{s['p95_ms'].get('POST /api/of/v2/chats/:id/messages', '-'):>8} "
            f"{s['sse_lag_p95_ms'] if s['sse_lag_p95_ms'] is not None else '-':>8} "
            f"{s['tab_lag_p95_ms'] if s['tab_lag_p95_ms'] is not None else '-':>8} "
            f"{round(max(row_upd)) if row_upd else '-':>8} {round(max(list_upd)) if list_upd else '-':>8} "
            f"{max(lt.values()) if lt else '-':>6} {s['dropped_sse']:>4} {s['5xx']:>4} "
            f"{s['inbox_rows'] if s['inbox_rows'] is not None else '-':>5} "
            f"{heap.get('inbox', '-'):>6}")
        for r, v in s["p95_ms"].items():
            worst.setdefault(r, {})[name] = v
    ctx.note("per stage (all measured; ms unless noted; lag = injection -> receipt):",
             "  stage       DMs  /min  /min/big ws-frame chats/recent send-reply sse-lag tab-lag thread-upd list-upd LT/min drop 5xx rows heapMB",
             *rows_out,
             "  (p95s; ws-frame = POST /__slop/of-ws-frame; thread-upd = max marker DM -> rendered in its open",
             "   popout/group thread; list-upd = max marker DM -> row in the All Models list; LT/min = max",
             "   over the tabs; rows/heap = inbox tab)")

    for route, budget in P95_BUDGET_MS.items():
        per = worst.get(route, {})
        if not per:
            continue
        over = {k: v for k, v in per.items() if v > budget}
        label = f"p95 {route} <= {budget}ms in every stage"
        known = KNOWN_DEFECT.get(route)
        if over and known:
            peak = max(over.values())
            label += (f" — KNOWN DEFECT (CLAUDE.md: ~{known}ms at 200 concurrent DMs)" if peak <= 1.5 * known
                      else f" — WORSE than the known ~{known}ms defect")
        ctx.check(label, not over, budget=True, budget_ms=budget, per_stage=per)
    for key, budget, label in (("sse_lag_p95_ms", SSE_LAG_BUDGET_MS, "SSE lag p95 (direct /events listener)"),
                               ("tab_lag_p95_ms", TAB_LAG_BUDGET_MS, "SSE lag p95 (All Models tab)")):
        per = {st["name"]: st["m"][key] for st in stages if st["m"][key] is not None}
        if per:
            ctx.check(f"{label} <= {budget}ms in every stage", all(v <= budget for v in per.values()),
                      budget=True, budget_ms=budget, per_stage=per)
    if tab_takes:
        per = {st["name"]: max(st["m"]["row_update_ms"] or [None]) for st in stages}
        ctx.check(f"marker DM -> rendered in its open thread <= {ROW_UPDATE_BUDGET_MS}ms in every stage",
                  all(v is not None and v <= ROW_UPDATE_BUDGET_MS for v in per.values()),
                  budget=True, budget_ms=ROW_UPDATE_BUDGET_MS, per_stage=per)
        per = {st["name"]: max(st["m"]["list_update_ms"] or [None]) for st in stages}
        ctx.check(f"marker DM -> row in the All Models list <= {ROW_UPDATE_BUDGET_MS}ms in every stage",
                  all(v is not None and v <= ROW_UPDATE_BUDGET_MS for v in per.values()),
                  budget=True, budget_ms=ROW_UPDATE_BUDGET_MS, per_stage=per)
        per = {st["name"]: st["m"]["long_tasks_per_min"] for st in stages}
        ctx.check(f"long tasks (>50ms) <= {LONG_TASKS_PER_MIN_BUDGET}/min on every tab in every stage",
                  all(v <= LONG_TASKS_PER_MIN_BUDGET for s in per.values() for v in s.values()),
                  budget=True, per_stage=per)
        per = {st["name"]: st["m"]["heap_mb"] for st in stages}
        ctx.check(f"JS heap <= {HEAP_BUDGET_MB}MB on every tab in every stage",
                  all(v <= HEAP_BUDGET_MB for s in per.values() for v in s.values()), budget=True, per_stage=per)
