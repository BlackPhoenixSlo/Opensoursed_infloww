"""Creator badges scenario 1 (docs/spec/creator-badges/phase-0E-slop-and-fake-of-realism.md, stories 14, 15, 25):
under a fan DM storm, headless Creator tabs show the Red circle within 2 s of the fake's truth, the operator's reads
and sends stay within 10 % of a baseline, and OF's raw Unread counter never reaches anything the app renders.

World: `flat_agency` with the tier's Creators (TIERS: small 5 Creators x 3 tabs each, 15 streams; `--set tier=full`
50 x 30, 1500, run alone), each a captured session (the relay's REAL OFClient against lib/of_wire.py, `OF_WIRE`)
whose OF is lib/badge_wire.py (counter frames, DM frames, Creator echoes at the measured delays; a first-page GET
marks read).
Each Creator's OF chat list: CHATS of its Fans, ONLY_FRIENDS unread `only_friends` chats and RESTRICTED unread
registry-restricted chats (OF's restrict + the Relay's `skip_list` row `of_restricted`): OF counts them, the Red
circle does not, and nothing touches them, so raw = red + GAP throughout; one Muted unread chat; PLAIN plain chats,
PLAIN_UNREAD of them unread. Red moves only within [0, PLAIN] and GAP > PLAIN (asserted at seed), so no Red value,
however stale, equals raw at any instant.
Every Creator's Live connection up (`/__slop/pump-supervise`).

Actors: the tier's headless tabs, `tabs` per Creator (actors/badge_tab.py: the owner's session, `/events?lease=1`, a
View lease on its one Creator, roster-counts every 60 s, an accounts refetch on a behind ping); the tier's operators
(each loops on a random plain chat: thread open, mark read or reply through the relay's /api/of/ routes, OP_THINK_S
apart); the DM driver (DMS_PER_MIN per Creator to plain chats, open loop on fixed deadlines, `BadgeWire.push_dm`).
One Chromium tab on /messages-pro (UI runs): screenshots `badge-storm-trigger` (storm start) and
`badge-storm-settled` (end), its Creator tabs' titles sampled every DOM_EVERY_S.

Phases: baseline (counter frames off), storm (on), both at the same offered DM rate; then SETTLE_S with nothing
moving. A truth sampler reads `truth_red` / `raw_counter` every SAMPLE_S.

Checks: RED_P95_UNDER_2S / RED_MAX_UNDER_5S (lib/badge_metrics `lag` per tab and Creator, on storm truth changes
after the Creator's first storm counter frame, to the settle end); FINAL_EQUALS_TRUTH (every tab's last Red circle =
`truth_red` after the settle, never `raw_counter`); OPERATOR_P95_WITHIN_10PCT (storm p95 <= 1.1 x baseline p95;
fewer than OPERATOR_MIN_N samples in a phase or a DM driver below DRIVER_MIN of its offered rate is INFRA, never
PASS); RAW_COUNTER_NEVER_RENDERED (`raw_leak` over every served slot `n`, roster-counts `unread`, SSE slot and tab
title, each judged at its own time: the slot's `at`, roster-counts' `as_of`, the title's sample).
Metric: Attribution reads (`group_reads` over the fake's `filter=unread` calls). Every check `ctx.skip`s while
Phase B's slot (`values.unread_total` with `v` and `grey`) is absent.

Bypasses (declared): OF at its wire (lib/badge_wire.py on lib/of_wire.py); 15 or 1500 tabs (per Creator) are API tabs (one Chromium
tab: the machine gate); the tab's store, behind decision and display rule run in node (lib/badge_tab_ts.mjs: the
app's creatorFreshnessReducer, badgeBehind, redCircle).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
import time
from collections import Counter

from slop.actors import ui
from slop.actors.badge_tab import BadgeTab, classify, open_ts
from slop.lib.badge_metrics import group_reads, lag, p95, raw_attempts, raw_leak
from slop.lib.badge_wire import BadgeWire, chat_plan, restrict_in_relay

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = None
TIMEOUT_S = 900
RELAY_ENV = {"INGEST_FAST_BOOT_GRACE_S": "0", "SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1"}
TIERS = {"small": {"creators": 5, "tabs": 3, "operators": 3, "baseline_s": 60.0, "storm_s": 120.0},
         "full": {"creators": 50, "tabs": 30, "operators": 6, "baseline_s": 120.0, "storm_s": 300.0}}
RED_P95_UNDER_2S = "RED_P95_UNDER_2S"
RED_MAX_UNDER_5S = "RED_MAX_UNDER_5S"
FINAL_EQUALS_TRUTH = "FINAL_EQUALS_TRUTH"
OPERATOR_P95_WITHIN_10PCT = "OPERATOR_P95_WITHIN_10PCT"
RAW_COUNTER_NEVER_RENDERED = "RAW_COUNTER_NEVER_RENDERED"
CHECKS = (RED_P95_UNDER_2S, RED_MAX_UNDER_5S, FINAL_EQUALS_TRUTH, OPERATOR_P95_WITHIN_10PCT,
          RAW_COUNTER_NEVER_RENDERED)
RED_P95_S = 2.0
RED_MAX_S = 5.0
OPERATOR_MARGIN = 0.10
OPERATOR_MIN_N = 200
DRIVER_MIN = 0.9
DMS_PER_MIN = 20.0
CHATS = 20            # inside roster-counts' 25-row window: every Restricted unread is folded
ONLY_FRIENDS = 6
RESTRICTED = 6
GAP = ONLY_FRIENDS + RESTRICTED
PLAIN = CHATS - GAP - 1
PLAIN_UNREAD = 4
TS_SESSIONS = {"small": 1, "full": 8}
OP_THINK_S = (0.2, 0.6)
OPS = ("thread", "mark_read", "reply")
PUMP_UP_S = 30.0
SLOT_WAIT_S = 45.0
ROWS_TIMEOUT_S = 180.0
SETTLE_S = 10.0
SAMPLE_S = 0.02
DOM_EVERY_S = 1.0
VIEWPORT = (1440, 900)
TITLES_JS = """() => [...document.querySelectorAll('[role="tablist"][aria-label="Creator tabs"] [role="tab"]')]
  .map((b) => b.getAttribute('title') || '')"""
_COUNT = re.compile(r"(\d+) unread")


def plan(fans: list[dict]) -> list[dict]:
    return chat_plan(fans, [("only_friends", ONLY_FRIENDS, True), ("restricted", RESTRICTED, True),
                            ("muted", 1, True), ("plain", PLAIN_UNREAD, True), ("plain", PLAIN - PLAIN_UNREAD, False)])



def phase_b(slot) -> bool:
    return isinstance(slot, dict) and "v" in slot and "grey" in slot


def title_count(title: str) -> tuple[str, int | None] | None:
    """(Creator name, the number its tab title shows; None for grey or 9+), from CreatorTabs' title."""
    parts = title.split(" — ")
    if len(parts) < 2:
        return None
    m = _COUNT.fullmatch(parts[1].strip())
    return parts[0], int(m.group(1)) if m else None


class Truth:
    """`truth_red` and `raw_counter` per Creator every SAMPLE_S, on its own thread: `red[aid]` / `raw[aid]` are
    `(t, value)` per change."""

    def __init__(self, wire: BadgeWire, aids: list[str]) -> None:
        self.wire, self.aids = wire, aids
        self.red: dict[str, list[tuple[float, int]]] = {a: [] for a in aids}
        self.raw: dict[str, list[tuple[float, int]]] = {a: [] for a in aids}
        self._halt = threading.Event()
        self._t = threading.Thread(target=self._run, name="badge-truth", daemon=True)
        self._t.start()

    def _run(self) -> None:
        while not self._halt.is_set():
            t = time.time()
            for a in self.aids:
                for xs, v in ((self.red[a], self.wire.truth_red(a)), (self.raw[a], self.wire.raw_counter(a))):
                    if not xs or xs[-1][1] != v:
                        xs.append((t, v))
            self._halt.wait(SAMPLE_S)

    def stop(self) -> None:
        self._halt.set()
        self._t.join(5)


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = tier["creators"]
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    seeds = {aid: plan(w.data["fans"][aid]) for aid in creators}
    assert all(len(s) == CHATS for s in seeds.values()), f"each Creator needs {CHATS} fans"
    wire = BadgeWire(fake, counter_frames=False).install()
    for aid, fans in seeds.items():
        wire.seed(aid, fans)
    gaps = {aid: wire.raw_counter(aid) - wire.truth_red(aid) for aid in creators}
    assert GAP > PLAIN and set(gaps.values()) == {GAP}, f"seed gap {gaps} must be {GAP} > Red's range {PLAIN}"
    con = w.sql()
    with con:
        restrict_in_relay(con, seeds)
    con.close()
    ctx.metric("world", {"tier": tier_name, **tier, "chats_per_creator": CHATS, "dms_per_creator_min": DMS_PER_MIN,
                         "kinds": dict(Counter(f["kind"] for f in next(iter(seeds.values())))),
                         "raw": {a: wire.raw_counter(a) for a in creators},
                         "red": {a: wire.truth_red(a) for a in creators}})
    truth = Truth(wire, creators)
    tabs: list[BadgeTab] = []
    sessions = await open_ts(ctx, TS_SESSIONS[tier_name])
    try:
        t_pumps = time.time()
        (await ctx.owner.post("/__slop/pump-supervise")).raise_for_status()
        up: set = set()
        while time.time() - t_pumps < PUMP_UP_S and len(up) < len(creators):
            await asyncio.sleep(0.25)
            with fake.lock:
                up = {c["account"] for c in fake.ws_connects if c["t"] >= t_pumps}
        ctx.metric("pumps_up", {"connected": len(up), "creators": len(creators),
                                "seconds": round(time.time() - t_pumps, 1)})
        tabs = [BadgeTab(ctx, f"{a}-t{i}", [a], sessions[i % len(sessions)])
                for a in creators for i in range(tier["tabs"])]
        await asyncio.gather(*(t.start() for t in tabs))
        lead = {t.aids[0]: t for t in reversed(tabs)}
        t_slot = time.time()
        while True:
            held = [lead[a].held(a) for a in creators]
            if all(phase_b(s) and isinstance(s.get("n"), int) and s.get("grey") is None for s in held):
                break
            if time.time() - t_slot > SLOT_WAIT_S:
                break
            await asyncio.sleep(1.0)
            await asyncio.gather(*(lead[a].refetch() for a in creators))
        present = any(phase_b(s) for s in held)
        ctx.metric("slot_ready", {"present": present, "seconds": round(time.time() - t_slot, 1),
                                  "held": dict(zip(creators, held))})
        if not present:
            for name in CHECKS:
                ctx.skip(name, "Phase B's slot (values.unread_total with v and grey) is absent")
            return
        await _storm(ctx, tier, fake, wire, truth, tabs, creators, seeds, sessions[0])
    finally:
        await asyncio.gather(*(t.stop() for t in tabs), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)
        truth.stop()
        wire.close()


async def _storm(ctx, tier: dict, fake, wire: BadgeWire, truth: Truth, tabs: list[BadgeTab], creators: list[str],
                 seeds: dict[str, list[dict]], ts) -> None:
    rng = ctx.world.rng("scenario:badge-storm")
    plain = {aid: [f["id"] for f in fans if f["kind"] == "plain"] for aid, fans in seeds.items()}
    names = {}
    r = await ctx.owner.get("/admin/accounts")
    for a in (r.json().get("accounts") or []) if r.status_code == 200 else []:
        names[a.get("nickname") or a["id"]] = a["id"]
    shots: dict[str, str] = {}
    dom: list[tuple[float, str, int, str]] = []
    dom_titles = Counter()
    halt = asyncio.Event()

    async with contextlib.AsyncExitStack() as stack:
        page = None
        if ctx.ui and ctx.app:
            try:
                page = await stack.enter_async_context(ui.owner_browser(ctx, viewport=VIEWPORT))
                await page.goto(f"{ctx.app}/messages-pro", timeout=ROWS_TIMEOUT_S * 1000)
                await page.wait_for_selector('[role="tablist"][aria-label="Creator tabs"] [role="tab"]',
                                             timeout=ROWS_TIMEOUT_S * 1000)
            except Exception as e:  # noqa: BLE001 — the API tabs still judge; the screenshots record why
                ctx.metric("chromium_error", f"{type(e).__name__}: {e}"[:300])

        async def shot(name: str) -> None:
            if page is None:
                return
            try:
                shots[name] = await ui.shot(ctx, page, name)
            except Exception as e:  # noqa: BLE001
                ctx.metric(f"shot_{name}_error", f"{type(e).__name__}: {e}"[:300])

        async def dom_sampler() -> None:
            while page is not None and not halt.is_set():
                try:
                    titles = await page.evaluate(TITLES_JS)
                except Exception:  # noqa: BLE001 — mid-navigation: the next sample reads again
                    titles = []
                t = time.time()
                for title in titles:
                    got = title_count(title)
                    dom_titles["tabs" if got else "unparsed"] += 1
                    if got and got[0] in names and got[1] is not None:
                        dom.append((t, names[got[0]], got[1], "dom"))
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(halt.wait(), DOM_EVERY_S)

        t_base = time.time()
        t_storm = t_base + tier["baseline_s"]
        t_end = t_storm + tier["storm_s"]
        sent: list[tuple[float, float, str]] = []
        ops: list[dict] = []
        interval = 60.0 / DMS_PER_MIN

        async def driver(aid: str) -> None:
            k, offset = 0, rng.uniform(0, interval)
            while (due := t_base + offset + k * interval) < t_end:
                await asyncio.sleep(max(0.0, due - time.time()))
                wire.push_dm(aid, {"id": rng.choice(plain[aid])})
                sent.append((due, time.time(), aid))
                k += 1

        async def operator(i: int) -> None:
            http = ctx.owner.share(limits=4)
            while time.time() < t_end:
                aid, kind = rng.choice(creators), rng.choice(OPS)
                fan, hdr = rng.choice(plain[aid]), {"X-Account-Id": aid}
                t0 = time.time()
                try:
                    if kind == "thread":
                        r = await http.get(f"/api/of/v2/chats/{fan}/messages?limit=10", headers=hdr)
                    elif kind == "mark_read":
                        r = await http.post(f"/api/of/v2/chats/{fan}/mark-as-read", headers=hdr)
                    else:
                        r = await http.post(f"/api/of/v2/chats/{fan}/messages", headers=hdr,
                                            json={"text": f"slop badge-storm reply {i}"})
                    status = r.status_code
                except Exception:  # noqa: BLE001 — counted as an error sample
                    status = 599
                ops.append({"t0": t0, "ms": (time.time() - t0) * 1000, "kind": kind, "status": status,
                            "phase": "baseline" if t0 < t_storm else "storm"})
                await asyncio.sleep(rng.uniform(*OP_THINK_S))

        async def flip() -> None:
            await asyncio.sleep(max(0.0, t_storm - time.time()))
            wire.counter_frames = True
            await shot("badge-storm-trigger")

        sampler = asyncio.create_task(dom_sampler())
        await asyncio.gather(*(driver(a) for a in creators), *(operator(i) for i in range(tier["operators"])), flip())
        await asyncio.sleep(SETTLE_S)
        t_settled = time.time()
        final = {a: wire.truth_red(a) for a in creators}
        final_raw = {a: wire.raw_counter(a) for a in creators}
        await shot("badge-storm-settled")
        halt.set()
        await sampler

    await classify(tabs, ts)
    ctx.metric("screenshots", shots)
    ctx.metric("tabs", {t.name: {"pings": t.pings, "behind_pings": t.behind_pings, "refetches": t.refetches,
                                 "slot_changes": sum(len(v) for v in t.slots.values()), "served": len(t.served),
                                 "errors": t.errors[:10], "ended": t.ended} for t in tabs})
    ctx.metric("dom", {"samples": len(dom), "titles": dict(dom_titles)})
    with fake.lock:
        calls = list(fake.calls)
        frames = list(wire.frames)
    reads = group_reads(calls)
    ctx.metric("attribution_reads", {"reads": len(reads), "per_creator": dict(Counter(r.account for r in reads)),
                                     "raw_attempts": raw_attempts(calls)})

    first = {a: min((f["t"] for f in frames if f["account"] == a and f["kind"] == "counter" and f["t"] >= t_storm),
                    default=None) for a in creators}
    lags: list[float] = []
    worst: list[dict] = []
    for tab in tabs:
        for a in tab.aids:
            if first[a] is None:
                continue
            series = [(t, v) for t, v in truth.red[a] if first[a] <= t < t_end]
            for (t, v), x in zip(series, lag(series, tab.red(a), t_settled)):
                lags.append(x)
                worst.append({"tab": tab.name, "creator": a, "t": round(t - t_storm, 3), "truth": v,
                              "lag_s": round(x, 3)})
    worst.sort(key=lambda d: -d["lag_s"])
    lp95, lmax = p95(lags), max(lags) if lags else None
    ctx.metric("red_lag_s", {"n": len(lags), "p95": lp95, "max": lmax, "worst": worst[:10],
                             "no_storm_frame": [a for a in creators if first[a] is None]})
    ctx.check(RED_P95_UNDER_2S, None if lp95 is None else lp95 < RED_P95_S, budget=True, p95_s=lp95, n=len(lags),
              budget_s=RED_P95_S)
    ctx.check(RED_MAX_UNDER_5S, None if lmax is None else lmax < RED_MAX_S, budget=True, max_s=lmax, n=len(lags),
              worst=worst[:5], budget_s=RED_MAX_S)

    wrong = []
    for tab in tabs:
        for a in tab.aids:
            shown = tab.red(a)
            last = shown[-1][1] if shown else None
            if last != final[a]:
                wrong.append({"tab": tab.name, "creator": a, "shown": last, "truth_red": final[a],
                              "raw_counter": final_raw[a]})
    ctx.check(FINAL_EQUALS_TRUTH, not wrong, wrong=wrong[:10], tabs=len(tabs), creators=len(creators),
              truth_red=final, raw_counter=final_raw)

    _operator(ctx, ops, sent, t_base, t_storm, t_end, len(creators))

    served = [(t, a, n) for tab in tabs for t, a, n, _ in tab.served] + [(t, a, n) for t, a, n, _ in dom]
    sources = {(t, a, n): s for tab in tabs for t, a, n, s in tab.served} | {(t, a, n): s for t, a, n, s in dom}
    raw = [(t, a, v) for a, xs in truth.raw.items() for t, v in xs]
    red = [(t, a, v) for a, xs in truth.red.items() for t, v in xs]
    leaks = raw_leak(served, raw, red)
    judged = sum(1 for t, a, _ in served if truth.red[a] and truth.red[a][0][0] <= t)
    ctx.check(RAW_COUNTER_NEVER_RENDERED, None if not judged else not leaks, judged=judged,
              served=len(served), by_source=dict(Counter(sources.values())), gap=GAP,
              leaks=[{"t": round(t - t_base, 3), "creator": a, "n": n, "source": sources.get((t, a, n))}
                     for t, a, n in leaks[:10]])
    (ctx.out / "badge-storm.json").write_text(json.dumps({
        "t_base": t_base, "t_storm": t_storm, "t_end": t_end, "t_settled": t_settled,
        "truth_red": truth.red, "raw_counter": truth.raw, "first_storm_frame": first,
        "observed": {t.name: t.observed for t in tabs}, "dm_sent": len(sent), "ops": len(ops),
    }, default=str))


def _operator(ctx, ops: list[dict], sent: list[tuple[float, float, str]], t_base: float, t_storm: float, t_end: float,
              n_creators: int) -> None:
    per = {}
    infra = []
    for phase, lo, hi in (("baseline", t_base, t_storm), ("storm", t_storm, t_end)):
        ok_ms = [o["ms"] for o in ops if o["phase"] == phase and o["status"] < 400]
        offered = DMS_PER_MIN / 60.0 * (hi - lo) * n_creators
        achieved = sum(1 for due, t, _ in sent if lo <= t < hi)
        late = max((t - due for due, t, _ in sent if lo <= t < hi), default=0.0)
        per[phase] = {"n": len(ok_ms), "errors": sum(1 for o in ops if o["phase"] == phase and o["status"] >= 400),
                      "p95_ms": p95(ok_ms), "by_kind": dict(Counter(o["kind"] for o in ops if o["phase"] == phase)),
                      "dm_offered": round(offered, 1), "dm_achieved": achieved, "dm_max_late_s": round(late, 3)}
        if len(ok_ms) < OPERATOR_MIN_N:
            infra.append(f"{phase}: {len(ok_ms)} operator samples < {OPERATOR_MIN_N}")
        if achieved < DRIVER_MIN * offered:
            infra.append(f"{phase}: DM driver {achieved} of {offered:.0f} offered")
    ctx.metric("operator", per)
    if infra:
        ctx.report.infra = ctx.report.infra or "OPERATOR_P95_WITHIN_10PCT inconclusive: " + "; ".join(infra)
        ctx.skip(OPERATOR_P95_WITHIN_10PCT, "; ".join(infra), **per)
        return
    base, storm = per["baseline"]["p95_ms"], per["storm"]["p95_ms"]
    ctx.check(OPERATOR_P95_WITHIN_10PCT, storm <= (1 + OPERATOR_MARGIN) * base, budget=True, baseline_p95_ms=base,
              storm_p95_ms=storm, margin=OPERATOR_MARGIN, **per)
