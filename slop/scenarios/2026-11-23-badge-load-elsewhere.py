from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict

from slop.actors.badge_tab import open_ts
from slop.lib.badge_load import CHATS, PATTERN, SLOT_S, DotTab, Driver, close_tabs, dot_tabs, phase_b, plan, pumps
from slop.lib.badge_load import PLAIN as PLAIN, ONLY_FRIENDS as ONLY_FRIENDS, PLAIN_HIGH as PLAIN_HIGH
from slop.lib.badge_load import PLAIN_UNREAD as PLAIN_UNREAD, RESTRICTED as RESTRICTED
from slop.lib.badge_metrics import (UNREAD_ROUTE, gap_ok, group_reads, held_at, lag, over_pages, p95, raw_attempts,
                                    single_flight_ok)
from slop.lib.badge_wire import BadgeWire, restrict_in_relay

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "badge-ordering-fence-off"
TIMEOUT_S = 900
RELAY_ENV = {"INGEST_FAST_BOOT_GRACE_S": "0", "SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1", "BADGE_READS": "full"}
TIERS = {"small": {"creators": 3, "full_s": 180.0, "race_s": 30.0, "deep_s": 60.0, "lean_s": 180.0, "off_s": 60.0},
         "full": {"creators": 10, "full_s": 300.0, "race_s": 30.0, "deep_s": 60.0, "lean_s": 300.0, "off_s": 60.0}}
DOT_FLIP_P95_UNDER_8S = "DOT_FLIP_P95_UNDER_8S"
DOT_FLIP_MAX_UNDER_30S = "DOT_FLIP_MAX_UNDER_30S"
FINAL_EQUALS_TRUTH = "FINAL_EQUALS_TRUTH"
READS_GAP_5S = "READS_GAP_5S"
READS_SINGLE_FLIGHT = "READS_SINGLE_FLIGHT"
READS_MAX_2_PAGES = "READS_MAX_2_PAGES"
STALE_READ_NEVER_CLEARS = "STALE_READ_NEVER_CLEARS"
LEAN_GAP_15S = "LEAN_GAP_15S"
LEAN_READS_HALVE = "LEAN_READS_HALVE"
OFF_ZERO_READS = "OFF_ZERO_READS"
CHECKS = (DOT_FLIP_P95_UNDER_8S, DOT_FLIP_MAX_UNDER_30S, FINAL_EQUALS_TRUTH, READS_GAP_5S, READS_SINGLE_FLIGHT,
          READS_MAX_2_PAGES, STALE_READ_NEVER_CLEARS, LEAN_GAP_15S, LEAN_READS_HALVE, OFF_ZERO_READS)
BUDGETED = (DOT_FLIP_P95_UNDER_8S, DOT_FLIP_MAX_UNDER_30S)
DOT_P95_S = 8.0
DOT_MAX_S = 30.0
GAP_S = 5.0
LEAN_GAP_S = 15.0
GAP_SLACK_S = 0.25
MAX_PAGES = 2
LEAN_RATIO = 0.6
DEEP_FILL = 10
DEEP_HIGH = 12
ELSEWHERE = ("read", "reply", "unread")
RACE_UNREAD = 4
RACE_QUIET_S = 10.0
RACE_SLOW_S = 4.0
RACE_DM_AT_S = 4.0
RACE_DM_COUNTER_S = 6.0
RACE_RELEASE_S = 14.0
SLOT_WAIT_S = 45.0
SETTLE_S = {"full": 10.0, "deep": 10.0, "lean": 20.0, "off": 5.0}


def judge(truth: list, seen: dict, init: dict, reds: dict, ends: dict, legs: dict, calls: list,
          race: dict) -> dict[str, tuple[bool | None, dict]]:
    out: dict[str, tuple[bool | None, dict]] = {}
    seen = {k: sorted(v) for k, v in seen.items()}
    reds = {k: sorted(v, key=lambda x: x[0]) for k, v in reds.items()}

    def dot(aid, fan, t):
        return held_at(seen.get((aid, fan), ()), t, init.get(aid, {}).get(fan))

    lags, worst = _leg_lags(truth, seen, legs.get("full"))
    lp95, lmax = p95(lags), max(lags, default=None)
    out[DOT_FLIP_P95_UNDER_8S] = (None if lp95 is None else lp95 < DOT_P95_S,
                                  {"p95_s": lp95, "n": len(lags), "budget_s": DOT_P95_S})
    out[DOT_FLIP_MAX_UNDER_30S] = (None if lmax is None else lmax < DOT_MAX_S,
                                   {"max_s": lmax, "n": len(lags), "worst": worst[:5], "budget_s": DOT_MAX_S})

    wrong, judged = [], 0
    for leg in ("full", "lean"):
        e = ends.get(leg)
        if not e:
            continue
        for aid, n in e["red"].items():
            judged += 1
            shown = held_at(reds.get(aid, ()), e["t"])
            if shown != n:
                wrong.append({"leg": leg, "creator": aid, "red": shown, "truth_red": n})
        for aid, fans in init.items():
            u = set(e["unread"].get(aid, ()))
            for fan in fans:
                judged += 1
                if dot(aid, fan, e["t"]) != int(fan in u):
                    wrong.append({"leg": leg, "creator": aid, "fan": fan, "dot": dot(aid, fan, e["t"]),
                                  "truth": int(fan in u)})
    out[FINAL_EQUALS_TRUTH] = (None if not judged else not wrong, {"judged": judged, "wrong": wrong[:10]})

    reads = group_reads(calls)
    by_aid = defaultdict(list)
    for r in reads:
        by_aid[r.account].append(r)

    def gaps(lo, hi, min_gap):
        worst_gap, ok, n = None, True, 0
        for aid, rs in by_aid.items():
            starts = [r.start for r in rs if lo <= r.start < hi]
            if len(starts) < 2:
                continue
            n += 1
            good, w = gap_ok(starts, min_gap - GAP_SLACK_S)
            ok = ok and good
            worst_gap = w if worst_gap is None else min(worst_gap, w)
        return (None if not n else ok), {"worst_gap_s": worst_gap, "creators": n, "min_gap_s": min_gap,
                                         "slack_s": GAP_SLACK_S}

    if "full" in legs:
        hi = legs["race"][2] if "race" in legs else legs["full"][2]
        out[READS_GAP_5S] = gaps(legs["full"][0], hi, GAP_S)
    else:
        out[READS_GAP_5S] = (None, {"reason": "no full leg"})
    flights = {aid: single_flight_ok([(r.start, r.end) for r in rs]) for aid, rs in by_aid.items()}
    out[READS_SINGLE_FLIGHT] = (None if not reads else all(ok for ok, _ in flights.values()),
                                {"reads": len(reads), "overlaps": {a: o[:3] for a, (ok, o) in flights.items() if not ok}})
    over = over_pages(reads, MAX_PAGES)
    out[READS_MAX_2_PAGES] = (None if not reads else not over,
                              {"reads": len(reads), "over": [vars(r) for r in over[:5]],
                               "pages": dict(Counter(r.pages for r in reads))})

    stale, spanned, unspanned = [], [], []
    if "race" in legs and "race" in ends:
        te = legs["race"][2]
        for aid, x in race.items():
            fan, dm_t = x["fan"], x["dm_t"]
            if not any(r.start <= dm_t <= r.end for r in by_aid.get(aid, ())):
                unspanned.append(aid)
                continue
            spanned.append(aid)
            clears = [round(t - dm_t, 3) for t, u in seen.get((aid, fan), ()) if u == 0 and dm_t <= t <= te]
            end_dot, end_truth = dot(aid, fan, te), int(fan in set(ends["race"]["unread"].get(aid, ())))
            if clears or end_dot != 1 or end_truth != 1:
                stale.append({"creator": aid, "fan": fan, "clears_after_dm_s": clears, "dot": end_dot,
                              "truth": end_truth})
    out[STALE_READ_NEVER_CLEARS] = (None if not spanned else not stale,
                                    {"spanned": spanned, "unspanned": unspanned, "stale": stale})

    if "lean" in legs:
        out[LEAN_GAP_15S] = gaps(legs["lean"][0], legs["lean"][2], LEAN_GAP_S)
    else:
        out[LEAN_GAP_15S] = (None, {"reason": "no lean leg"})

    def per_min(leg):
        t0, t1, _ = legs[leg]
        n = sum(1 for r in reads if t0 <= r.start < t1)
        return n / ((t1 - t0) / 60.0 * max(1, len(init)))

    if "full" in legs and "lean" in legs:
        full_rate, lean_rate = per_min("full"), per_min("lean")
        out[LEAN_READS_HALVE] = (None if not full_rate else lean_rate <= LEAN_RATIO * full_rate,
                                 {"full_per_creator_min": round(full_rate, 3),
                                  "lean_per_creator_min": round(lean_rate, 3), "ratio_max": LEAN_RATIO})
    else:
        out[LEAN_READS_HALVE] = (None, {"reason": "no full or lean leg"})

    if "off" in legs and "off" in ends:
        t0, _, te = legs["off"]
        attempts = raw_attempts([c for c in calls if t0 <= (c.get("t0") or c["t"]) <= te])
        e = ends["off"]
        red_wrong = [{"creator": aid, "red": held_at(reds.get(aid, ()), e["t"]), "truth_red": n}
                     for aid, n in e["red"].items() if held_at(reds.get(aid, ()), e["t"]) != n]
        out[OFF_ZERO_READS] = (attempts == 0 and not red_wrong, {"unread_calls": attempts, "red_wrong": red_wrong})
    else:
        out[OFF_ZERO_READS] = (None, {"reason": "no off leg"})
    return out


def _leg_lags(truth: list, seen: dict, leg: tuple | None, creators=None) -> tuple[list[float], list[dict]]:
    lags, worst = [], []
    if leg is None:
        return lags, worst
    t0, t1, te = leg
    by_fan = defaultdict(list)
    for t, aid, fan, u, cause in sorted(truth):
        if t < te and (creators is None or aid in creators):
            by_fan[(aid, fan)].append((t, u, cause))
    for key, xs in by_fan.items():
        obs = [(t, u) for t, u in seen.get(key, ()) if t <= te]
        for (t, u, cause), x in zip(xs, lag([(t, u) for t, u, _ in xs], obs, te)):
            if cause in ELSEWHERE and t0 <= t < t1:
                lags.append(x)
                worst.append({"creator": key[0], "fan": key[1], "cause": cause, "t": round(t - t0, 3),
                              "lag_s": round(x, 3)})
    worst.sort(key=lambda d: -d["lag_s"])
    return lags, worst


def two_page_report(truth: list, seen: dict, legs: dict, calls: list) -> dict | None:
    if "deep" not in legs:
        return None
    t0, _t1, te = legs["deep"]
    seen = {k: sorted(v) for k, v in seen.items()}
    two = Counter(r.account for r in group_reads(calls) if t0 <= r.start < te and r.pages >= 2)
    lags, worst = _leg_lags(truth, seen, legs["deep"], set(two))
    return {"creators": sorted(two), "two_page_reads": dict(two), "n": len(lags),
            "p95_s": p95(lags), "max_s": max(lags, default=None), "worst": worst[:5],
            "budget_s": DOT_P95_S, "gate": None}


def report(ctx, verdicts: dict[str, tuple[bool | None, dict]]) -> None:
    for name in CHECKS:
        ok, detail = verdicts[name]
        ctx.check(name, ok, budget=name in BUDGETED, **detail)


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = tier["creators"]
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    seeds = {aid: plan(w.data["fans"][aid]) for aid in creators}
    assert all(len(s) == CHATS for s in seeds.values()), f"each Creator needs {CHATS} fans"
    wire = BadgeWire(fake).install()
    for aid, fans in seeds.items():
        wire.seed(aid, fans)
    con = w.sql()
    with con:
        restrict_in_relay(con, seeds)
    con.close()
    plain = {aid: [f["id"] for f in fans if f["kind"] == "plain"] for aid, fans in seeds.items()}
    init = {aid: {f["id"]: int(f["unread"]) for f in fans if f["kind"] == "plain"} for aid, fans in seeds.items()}
    ctx.metric("world", {"tier": tier_name, **tier, "chats_per_creator": CHATS, "pattern": PATTERN,
                         "slot_s": SLOT_S, "raw": {a: wire.raw_counter(a) for a in creators},
                         "red": {a: wire.truth_red(a) for a in creators}})
    driver = Driver(wire, plain)
    gens: list[list[DotTab]] = []
    legs: dict[str, tuple[float, float, float]] = {}
    ends: dict[str, dict] = {}
    race: dict[str, dict] = {}
    restarts: list[dict] = []
    sessions = await open_ts(ctx, 1)
    live: list[DotTab] = []
    try:
        await pumps(ctx, fake, creators, "full")
        live = await dot_tabs(ctx, creators, sessions[0], "full")
        gens.append(live)
        lead = {t.aids[0]: t for t in gens[0]}
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
        ctx.metric("slot_ready", {"present": present, "seconds": round(time.time() - t_slot, 1)})
        if not present:
            for name in CHECKS:
                ctx.skip(name, "Phase B's slot (values.unread_total with v and grey) is absent")
            return

        legs["full"] = await _leg(driver, creators, tier["full_s"], SETTLE_S["full"])
        ends["full"] = _snapshot(wire, driver, creators)
        legs["race"] = await _race(ctx, fake, wire, driver, creators, tier["race_s"], race)
        ends["race"] = _snapshot(wire, driver, creators)
        legs["deep"] = await _deep(driver, creators, tier["deep_s"])
        for mode in ("lean", "off"):
            await close_tabs(live, sessions[0])
            live = []
            restarts.append(await _restart(ctx, mode))
            t_up = time.time()
            await pumps(ctx, fake, creators, mode)
            live = await dot_tabs(ctx, creators, sessions[0], mode)
            gens.append(live)
            t0, t1, te = await _leg(driver, creators, tier[f"{mode}_s"], SETTLE_S[mode])
            legs[mode] = (t_up if mode == "off" else t0, t1, te)
            ends[mode] = _snapshot(wire, driver, creators)
        await close_tabs(live, sessions[0])
        live = []
    finally:
        await asyncio.gather(*(t.stop() for t in live), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)
        wire.close()

    with fake.lock:
        calls = list(fake.calls)
    seen: dict[tuple[str, int], list[tuple[float, int]]] = defaultdict(list)
    reds: dict[str, list] = defaultdict(list)
    for g in gens:
        for tab in g:
            for aid, xs in tab.dots.items():
                for t, fan, u in xs:
                    seen[(aid, fan)].append((t, u))
            for aid in tab.aids:
                reds[aid] += tab.red(aid)
    reads = group_reads(calls)
    ctx.metric("driver", {"done": dict(driver.done), "skipped": dict(driver.skipped)})
    ctx.metric("restarts", restarts)
    ctx.metric("attribution_reads", {
        "per_leg": {leg: sum(1 for r in reads if t0 <= r.start < te) for leg, (t0, _, te) in legs.items()},
        "per_creator": dict(Counter(r.account for r in reads)), "raw_attempts": raw_attempts(calls)})
    ctx.metric("tabs", {t.name: {"dots": sum(len(v) for v in t.dots.values()), "reconnects": t.reconnects,
                                 "errors": t.errors[:5], "ended": t.ended} for g in gens for t in g})
    report(ctx, judge(driver.truth, seen, init, reds, ends, legs, calls, race))
    deep = two_page_report(driver.truth, seen, legs, calls)
    ctx.metric("two_page_leg", deep)
    if deep:
        line = (f"report-only, no gate: 2-page churn leg DOT_FLIP p95={deep['p95_s']} max={deep['max_s']} "
                f"n={deep['n']} creators={len(deep['creators'])}")
        print(f"  {line}")
        ctx.note(line)
    (ctx.out / "badge-load-elsewhere.json").write_text(json.dumps({
        "legs": legs, "ends": ends, "race": race, "truth": driver.truth, "init": init,
        "seen": {f"{a}:{f}": v for (a, f), v in seen.items()}, "reds": reds,
    }, default=str))


async def _restart(ctx, mode: str) -> dict:
    ctx.stack._relay_envs[0]["BADGE_READS"] = mode
    t = time.time()
    _, took = await asyncio.to_thread(ctx.stack.stop_relay, 0, 30.0)
    await asyncio.to_thread(ctx.stack.start_relay)
    return {"mode": mode, "stop_s": took, "seconds": round(time.time() - t, 1)}


async def _leg(driver: Driver, creators: list[str], seconds: float, settle: float) -> tuple[float, float, float]:
    t0 = time.time()
    t1 = t0 + seconds
    await asyncio.gather(*(driver.run(a, t0 + i * SLOT_S / len(creators), t1) for i, a in enumerate(creators)))
    await asyncio.sleep(settle)
    return t0, t1, time.time()


async def _deep(driver: Driver, creators: list[str], seconds: float) -> tuple[float, float, float]:
    driver.high = DEEP_HIGH
    try:
        for aid in creators:
            while len(driver.unread(aid)) < DEEP_FILL and (fan := driver.pick(aid, False)) is not None:
                driver.apply(aid, "unread", fan, "fill")
        leg = await _leg(driver, creators, seconds, SETTLE_S["deep"])
    finally:
        driver.high = PLAIN_HIGH
    for aid in creators:
        for fan in driver.unread(aid)[PLAIN_UNREAD:]:
            driver.apply(aid, "read", fan, "trim")
    return leg


def _snapshot(wire: BadgeWire, driver: Driver, creators: list[str]) -> dict:
    return {"t": time.time(), "unread": {a: driver.unread(a) for a in creators},
            "red": {a: wire.truth_red(a) for a in creators}}


async def _race(ctx, fake, wire: BadgeWire, driver: Driver, creators: list[str], seconds: float,
                race: dict) -> tuple[float, float, float]:
    t_trim = time.time()
    for aid in creators:
        for fan in driver.unread(aid)[RACE_UNREAD:]:
            driver.apply(aid, "read", fan, "trim")
        if not driver.unread(aid):
            driver.apply(aid, "unread", driver.pick(aid, False), "trim")
    await asyncio.sleep(RACE_QUIET_S)
    pairs = {aid: (driver.pick(aid, False), driver.pick(aid, True)) for aid in creators}
    dm_delay = wire.delays["dm_counter"]
    t0 = time.time()
    fake.route_s[UNREAD_ROUTE] = RACE_SLOW_S
    try:
        for aid, (_, y) in pairs.items():
            driver.apply(aid, "read", y, "race")
            wire.hold_unread_snapshot(aid)
        await asyncio.sleep(max(0.0, t0 + RACE_DM_AT_S - time.time()))
        wire.delays["dm_counter"] = RACE_DM_COUNTER_S
        for aid, (x, _) in pairs.items():
            race[aid] = {"fan": x, "dm_t": driver.apply(aid, "dm", x, "race")}
        wire.delays["dm_counter"] = dm_delay
        await asyncio.sleep(max(0.0, t0 + RACE_RELEASE_S - time.time()))
    finally:
        wire.delays["dm_counter"] = dm_delay
        fake.route_s.pop(UNREAD_ROUTE, None)
        for aid in creators:
            wire.release(aid)
    t1 = t0 + seconds
    await asyncio.sleep(max(0.0, t1 - time.time()))
    ctx.metric("race", {"trim_s": round(t0 - t_trim, 1), "pairs": {a: {"x": x, "y": y} for a, (x, y) in pairs.items()}})
    return t0, t1, time.time()
