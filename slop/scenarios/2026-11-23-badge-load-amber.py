"""Creator badges scenario 2b (docs/spec/creator-badges/phase-0E-slop-and-fake-of-realism.md row 2b, stories 20 and
27a; Phase F: phase-0F-amber-awaiting-reply.md): under 2a's elsewhere load plus replies with echoes, chatter replies
and mass sends, the Amber circle follows awaiting-reply truth within 8 s at p95 (30 s max), no Fan sits in both
circles, and it ends on truth.

World: 2a's (`flat_agency`, the tier's Creators on lib/badge_wire.py, lib/badge_load.py `plan` of CHATS chats inside
the 25-row window) with AWAITING of its read plain chats Fan-last, so amber starts above 0. One headless tab per
Creator (lib/badge_load.py DotTab: actors/badge_tab.py plus every `chat_read_changed` and DM its stream carried).

Load, per Creator for the tier's seconds: 2a's Driver and PATTERN (lib/badge_load.py: 10 silent reads, 10 replies
elsewhere, 5 mark-unreads, 15 refill DMs per Creator-min), except a reply elsewhere sends its Creator echo (the
fake's default) and goes to an awaiting Fan while REPLY_AMBER_MIN are awaiting; a chatter reply through the Relay's
send route every CHAT_EVERY_S to an awaiting Fan (else an unread one); a mass every QUEUE_EVERY_S to QUEUE_TO read
plain Fans, awaiting first (`BadgeWire.queue_elsewhere`: no per-Fan echo, then `chat_queue_finish`). Chat sends land
between DM windows (CHAT_AT_S). Then SETTLE_S of nothing moving.

Checks (pure `judge`): AMBER_P95_UNDER_8S / AMBER_MAX_UNDER_30S (lib/badge_metrics `lag` from each amber truth change
in the load to the tab's Amber circle); NO_FAN_IN_BOTH (`in_both`: the Amber circle never counts more Fans than are
outside the Relay's per-Fan Red view and held Fan-last); FINAL_EQUALS_TRUTH (each Amber circle = `truth_amber`
after the settle); READS_CAP_120 (Attribution read starts plus relay.log's `badge_read kind=queue` re-reads per
Creator-hour). Every check goes through `badge_metrics.amber_gate`: SKIP while Phase F's `amber` is absent from the
accounts answer, FAIL then and when unjudged under `--set require_amber=1`. The raw OF counter is never asserted.

Bypasses (declared): OF at its wire (lib/badge_wire.py on lib/of_wire.py); tabs are API tabs; masses are sent
elsewhere (the fake), not through the Relay's mass route.
"""
from __future__ import annotations

import asyncio
import bisect
import contextlib
import json
import time
from collections import Counter, defaultdict

from slop.actors.badge_tab import open_ts
from slop.lib import badge_load
from slop.lib.badge_load import CHATS, SLOT_S, close_tabs, dot_tabs, phase_b, pumps
from slop.lib.badge_metrics import (amber_gate, cap_rates, group_reads, held_at, lag, p95, queue_reads,
                                    window_reads)
from slop.lib.badge_wire import BadgeWire, restrict_in_relay

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = None
TIMEOUT_S = 900
RELAY_ENV = {"INGEST_FAST_BOOT_GRACE_S": "0", "SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1", "BADGE_READS": "full"}
TIERS = {"small": {"creators": 3, "seconds": 180.0}, "full": {"creators": 10, "seconds": 300.0}}
AMBER_P95_UNDER_8S = "AMBER_P95_UNDER_8S"
AMBER_MAX_UNDER_30S = "AMBER_MAX_UNDER_30S"
NO_FAN_IN_BOTH = "NO_FAN_IN_BOTH"
FINAL_EQUALS_TRUTH = "FINAL_EQUALS_TRUTH"
READS_CAP_120 = "READS_CAP_120"
CHECKS = (AMBER_P95_UNDER_8S, AMBER_MAX_UNDER_30S, NO_FAN_IN_BOTH, FINAL_EQUALS_TRUTH, READS_CAP_120)
BUDGETED = (AMBER_P95_UNDER_8S, AMBER_MAX_UNDER_30S)
AMBER_P95_S = 8.0
AMBER_MAX_S = 30.0
CAP_PER_HOUR = 120
BOTH_SLACK_S = 2.0
AWAITING = 6
REPLY_AMBER_MIN = 2
CHAT_AT_S = 10.9
CHAT_EVERY_S = 12.0
QUEUE_AT_S = 30.6
QUEUE_EVERY_S = 60.0
QUEUE_TO = 5
SAMPLE_S = 0.02
SLOT_WAIT_S = 45.0
SETTLE_S = 15.0


def plan(fans: list[dict]) -> list[dict]:
    out = badge_load.plan(fans)
    for f in [f for f in out if f["kind"] == "plain" and not f["unread"]][:AWAITING]:
        f["awaiting"] = True
    return out


class Driver(badge_load.Driver):
    """2a's Driver with echoed replies elsewhere, chatter replies through the Relay and masses elsewhere."""

    def __init__(self, wire: BadgeWire, plain: dict[str, list[int]], http) -> None:
        super().__init__(wire, plain)
        self.http = http
        self.sends: list[asyncio.Future] = []
        self.failed: Counter = Counter()

    def amber(self, aid: str) -> list[int]:
        a = self.wire.truth_amber_fans(aid)
        return sorted((f for f in self.plain[aid] if f in a), key=lambda f: self.moved[(aid, f)])

    def recipients(self, aid: str) -> list[int]:
        unread, amber = set(self.unread(aid)), self.amber(aid)
        rest = sorted((f for f in self.plain[aid] if f not in unread and f not in amber),
                      key=lambda f: self.moved[(aid, f)])
        return (amber + rest)[:QUEUE_TO]

    def act(self, aid: str, kind: str) -> int | None:
        if kind == "queue":
            fans = self.recipients(aid)
            if len(fans) < QUEUE_TO:
                self.skipped[kind] += 1
                return None
            self.wire.queue_elsewhere(aid, fans)
            t = time.time()
            for f in fans:
                self.moved[(aid, f)] = t
            self.done[kind] += 1
            return fans[0]
        if kind in ("reply", "chat"):
            amber = self.amber(aid)
            use = amber and (kind == "chat" or len(amber) >= REPLY_AMBER_MIN)
            fan = amber[0] if use else self.pick(aid, True)
            if fan is None:
                self.skipped[kind] += 1
                return None
            self.apply(aid, kind, fan, kind)
            return fan
        return super().act(aid, kind)

    def apply(self, aid: str, kind: str, fan: int, cause: str) -> float:
        if kind not in ("reply", "chat"):
            return super().apply(aid, kind, fan, cause)
        if kind == "reply":
            self.wire.reply_elsewhere(aid, fan)
        else:
            self.sends.append(asyncio.ensure_future(self._chat(aid, fan)))
        t = time.time()
        self.moved[(aid, fan)] = t
        self.done[kind] += 1
        return t

    async def _chat(self, aid: str, fan: int) -> None:
        try:
            r = await self.http.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                     json={"text": "slop badge-load-amber reply"})
            if r.status_code != 200:
                self.failed[f"chat {r.status_code}"] += 1
        except Exception as e:  # noqa: BLE001 — a failed send is a metric; truth only moves when OF took it
            self.failed[f"chat {type(e).__name__}"] += 1

    async def _every(self, aid: str, kind: str, start: float, t1: float, every: float) -> None:
        k = 0
        while (due := start + k * every) < t1:
            await asyncio.sleep(max(0.0, due - time.time()))
            self.act(aid, kind)
            k += 1

    async def run(self, aid: str, t0: float, t1: float) -> None:
        await asyncio.gather(super().run(aid, t0, t1),
                             self._every(aid, "chat", t0 + CHAT_AT_S, t1, CHAT_EVERY_S),
                             self._every(aid, "queue", t0 + QUEUE_AT_S, t1, QUEUE_EVERY_S))

    async def drain(self) -> None:
        await asyncio.gather(*self.sends, return_exceptions=True)


def _any_in(keys: list[float], vals: list, v0, a: float, b: float, want) -> bool:
    i = bisect.bisect_right(keys, a)
    if (vals[i - 1] if i else v0) == want:
        return True
    j = bisect.bisect_right(keys, b)
    return want in vals[i:j]


def in_both(drawn: list[tuple[float, int]], pool: list[int], dots0: dict[int, int],
            dots: dict[int, list[tuple[float, int]]], last0: dict[int, bool], last: dict[int, list[tuple[float, bool]]],
            syncs: dict[int, list[float]], windows: list[float], lo: float, hi: float,
            eps: float = BOTH_SLACK_S) -> tuple[int, list[tuple[float, int, int]]]:
    """The Relay publishes amber as a count, so a Fan in both circles shows as the Amber circle `drawn` counting more
    Fans of `pool` than can be amber outside the Red circle: Fans whose dot (`dots`, the Relay's own per-Fan Red view)
    is read and whose chat the Relay holds as Fan-last, both at some moment within `eps`. The Relay holds a chat's
    last message as truth (`last`) stood at its newest sync: a DM or echo frame for that Fan (`syncs`) or a page-0
    window read's start (`windows`, the Relay's mass re-read included; a mass has no per-Fan frame); before any
    sync, Fan-last. Judged at every Amber change and
    `eps` after every dot change or sync in [lo, hi]. -> (judged, [(t, amber, candidates)])."""
    drawn = sorted(drawn, key=lambda x: x[0])
    dot_s, rel_s = {}, {}
    for f in pool:
        xs = sorted(dots.get(f, ()), key=lambda x: x[0])
        dot_s[f] = ([t for t, _ in xs], [int(u) for _, u in xs], int(dots0.get(f, 0)))
        lt = sorted(last.get(f, ()), key=lambda x: x[0])
        pts = sorted(set(syncs.get(f, ())) | set(windows))
        rel_s[f] = (pts, [bool(held_at(lt, p, last0.get(f, True))) for p in pts], True)
    points = {t for t, _ in drawn if lo <= t <= hi}
    for f in pool:
        points |= {t + eps + 1e-6 for t in dot_s[f][0] + rel_s[f][0] if lo <= t + eps <= hi}
    judged, bad = 0, []
    for t in sorted(points):
        n = held_at(drawn, t)
        if not isinstance(n, int):
            continue
        judged += 1
        cand = sum(1 for f in pool if _any_in(*dot_s[f], t - eps, t + eps, 0)
                   and _any_in(*rel_s[f], t - eps, t + eps, True))
        if n > cand:
            bad.append((round(t, 3), n, cand))
    return judged, bad


def judge(truth: dict[str, list[tuple[float, int]]], drawn: dict[str, list[tuple[float, int]]],
          legs: tuple[float, float, float], final: dict[str, int], calls: list[dict],
          queue: list[tuple[float, str]], both: dict[str, dict]) -> dict[str, tuple[bool | None, dict]]:
    """Every check's (ok | None, detail). `truth[aid]` the amber truth changes (t, n); `drawn[aid]` the tab's Amber
    circle (t, n); `legs` (load start, load end, settled); `final[aid]` amber truth when settled; `calls` the fake's;
    `queue` relay.log's kind=queue re-reads (t, aid); `both[aid]` `in_both`'s keyword inputs past `drawn`."""
    out: dict[str, tuple[bool | None, dict]] = {}
    t0, t1, te = legs
    lags, worst = [], []
    for aid, xs in truth.items():
        xs = sorted((x for x in xs if x[0] < te), key=lambda x: x[0])
        obs = [x for x in drawn.get(aid, ()) if x[0] <= te]
        for (t, n), x in zip(xs, lag(xs, obs, te)):
            if t0 <= t < t1:
                lags.append(x)
                worst.append({"creator": aid, "t": round(t - t0, 3), "amber": n, "lag_s": round(x, 3)})
    worst.sort(key=lambda d: -d["lag_s"])
    lp95, lmax = p95(lags), max(lags, default=None)
    out[AMBER_P95_UNDER_8S] = (None if lp95 is None else lp95 < AMBER_P95_S,
                               {"p95_s": lp95, "n": len(lags), "budget_s": AMBER_P95_S})
    out[AMBER_MAX_UNDER_30S] = (None if lmax is None else lmax < AMBER_MAX_S,
                                {"max_s": lmax, "n": len(lags), "worst": worst[:5], "budget_s": AMBER_MAX_S})

    judged, bad = 0, {}
    for aid, kw in both.items():
        n, b = in_both(drawn.get(aid, []), lo=t0, hi=te, **kw)
        judged += n
        if b:
            bad[aid] = {"instants": len(b), "first": b[:5]}
    out[NO_FAN_IN_BOTH] = (None if not judged else not bad, {"judged": judged, "excess": bad,
                                                              "slack_s": BOTH_SLACK_S})

    wrong = {}
    for aid, n in final.items():
        shown = held_at(sorted(drawn.get(aid, ()), key=lambda x: x[0]), te)
        if shown != n:
            wrong[aid] = {"amber": shown, "truth_amber": n}
    out[FINAL_EQUALS_TRUTH] = (None if not final else not wrong, {"judged": len(final), "wrong": wrong})

    rates = cap_rates(group_reads(calls), queue, CAP_PER_HOUR)
    out[READS_CAP_120] = (None if not rates else all(ok for ok, _ in rates.values()),
                          {"max_per_hour": {a: n for a, (_, n) in rates.items()}, "queue_reads": len(queue),
                           "cap": CAP_PER_HOUR})
    return out


def report(ctx, verdicts: dict[str, tuple[bool | None, dict]], present: bool, require: bool) -> None:
    for name in CHECKS:
        ok, detail = verdicts.get(name, (None, {}))
        ok, why = amber_gate(present, require, ok)
        ctx.check(name, ok, budget=name in BUDGETED, **({"reason": why} if why else {}), **detail)


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    require = ctx.param("require_amber", 0) == 1
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
    ctx.metric("world", {"tier": tier_name, **tier, "require_amber": require, "chats_per_creator": CHATS,
                         "awaiting": AWAITING, "amber": {a: wire.truth_amber(a) for a in creators}})
    driver = Driver(wire, plain, ctx.owner.share(limits=4))
    truth: dict[str, list[tuple[float, int]]] = {a: [] for a in creators}
    last: dict[str, dict[int, list[tuple[float, bool]]]] = {a: defaultdict(list) for a in creators}
    last0 = {a: {f: f in wire.fan_last(a) for f in plain[a]} for a in creators}
    halt = asyncio.Event()
    sampler = asyncio.create_task(_sample(wire, plain, truth, last, last0, halt))
    sessions = await open_ts(ctx, 1)
    tabs: list = []
    live: list = []
    legs, final, present = None, {}, False
    try:
        await pumps(ctx, fake, creators, "amber")
        tabs = live = await dot_tabs(ctx, creators, sessions[0], "amber")
        tab = {t.aids[0]: t for t in tabs}
        t_slot = time.time()
        while True:
            held = [tab[a].held(a) for a in creators]
            if all(phase_b(s) and isinstance(s.get("n"), int) and s.get("grey") is None
                   and isinstance(s.get("amber"), int) for s in held):
                break
            if time.time() - t_slot > SLOT_WAIT_S:
                break
            await asyncio.sleep(1.0)
            await asyncio.gather(*(tab[a].refetch() for a in creators))
        present = any(isinstance(s, dict) and "amber" in s for s in held)
        ctx.metric("slot_ready", {"present": present, "seconds": round(time.time() - t_slot, 1), "held": held})
        if present:
            legs = await _leg(driver, creators, tier["seconds"], SETTLE_S)
            final = {a: wire.truth_amber(a) for a in creators}
        await close_tabs(live, sessions[0])
        live = []
    finally:
        await asyncio.gather(*(t.stop() for t in live), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)
        halt.set()
        await asyncio.gather(sampler, return_exceptions=True)
        wire.close()
    if not present:
        report(ctx, {}, False, require)
        return

    with fake.lock:
        calls = list(fake.calls)
    frames = list(wire.frames)
    text = (ctx.out / "relay.log").read_text(errors="replace") if (ctx.out / "relay.log").exists() else ""
    queue = [(t, a) for t, a in queue_reads(text) if a in truth]
    drawn = {a: [(t, n) for t, kind, n in tab[a].observed.get(a, ()) if kind == "amber"] for a in creators}
    windows: dict[str, list[float]] = defaultdict(list)
    for t0, _t, aid in window_reads(calls):
        windows[aid].append(t0)
    both = {}
    for a in creators:
        syncs: dict[int, list[float]] = defaultdict(list)
        for f in frames:
            if f["account"] == a and f["kind"] in ("dm", "echo") and f["value"] is not None:
                syncs[int(f["value"])].append(f["t"])
        dots: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for t, fan, u in tab[a].dots.get(a, ()):
            dots[fan].append((t, u))
        both[a] = {"pool": plain[a], "dots0": {f["id"]: int(f["unread"]) for f in seeds[a] if f["kind"] == "plain"},
                   "dots": dict(dots), "last0": last0[a], "last": dict(last[a]), "syncs": dict(syncs),
                   "windows": windows.get(a, [])}
    reads = group_reads(calls)
    ctx.metric("driver", {"done": dict(driver.done), "skipped": dict(driver.skipped), "failed": dict(driver.failed)})
    ctx.metric("reads", {"attribution": dict(Counter(r.account for r in reads)),
                         "queue": dict(Counter(a for _, a in queue)),
                         "window": {a: len(v) for a, v in windows.items()}})
    ctx.metric("tabs", {t.name: {"amber_changes": len(drawn.get(t.aids[0], ())), "dots": len(t.dots[t.aids[0]]),
                                 "reconnects": t.reconnects, "errors": t.errors[:5], "ended": t.ended} for t in tabs})
    report(ctx, judge(truth, drawn, legs, final, calls, queue, both), True, require)
    (ctx.out / "badge-load-amber.json").write_text(json.dumps({
        "legs": legs, "final": final, "truth": truth, "drawn": drawn, "queue": queue, "both": both,
    }, default=str))


async def _sample(wire: BadgeWire, plain: dict[str, list[int]], truth: dict, last: dict, last0: dict,
                  halt: asyncio.Event) -> None:
    held = {a: dict(v) for a, v in last0.items()}
    while not halt.is_set():
        t = time.time()
        for a, fans in plain.items():
            n = wire.truth_amber(a)
            if not truth[a] or truth[a][-1][1] != n:
                truth[a].append((t, n))
            fl = wire.fan_last(a)
            for f in fans:
                if (f in fl) != held[a][f]:
                    held[a][f] = f in fl
                    last[a][f].append((t, f in fl))
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(halt.wait(), SAMPLE_S)


async def _leg(driver: Driver, creators: list[str], seconds: float, settle: float) -> tuple[float, float, float]:
    t0 = time.time()
    t1 = t0 + seconds
    await asyncio.gather(*(driver.run(a, t0 + i * SLOT_S / len(creators), t1) for i, a in enumerate(creators)))
    await driver.drain()
    await asyncio.sleep(settle)
    return t0, t1, time.time()
