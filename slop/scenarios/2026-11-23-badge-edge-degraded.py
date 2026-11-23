"""Creator badges scenario 4 (docs/spec/creator-badges/phase-0E-slop-and-fake-of-realism.md stories 22, 22a, 23, 23a;
phase-0C story 36): on a degraded stack a Creator whose value is unknown is served grey, never 0; dead-session and
proxy-down Creators cost no `filter=unread` read; a 429 exit hold is honoured; a visible Creator whose socket is down
gets an Unread-list poll about every 15 s; red is back to truth within 30 s of a fault ending; the Focus walk
completes; after a Relay restart a quiet Creator stays grey until a value can reach it, with no read storm.

World: `flat_agency` with the tier's Creators (TIERS: small 6, `--set tier=full` 50), each a captured session (the
relay's REAL OFClient against lib/of_wire.py, `OF_WIRE`) whose OF is lib/badge_wire.py (counter frames on), each OF
chat list CHATS plain chats, UNREAD of them unread. Roles (`roles`, in Creator order): `at_429` Creators bound to one
live custom proxy (lib/proxy_wire.py, through `POST /admin/proxies` + `/admin/proxies/assign`: their own exit, so
their 429 hold never holds the direct Creators); one `held` Creator; `dead` Creators; `proxy_down` Creators bound to a
second custom proxy; the rest healthy, the last of them `quiet`. One headless tab per Creator (actors/badge_tab.py:
`/events?lease=1` + View lease, so every Creator is open and visible); every Live connection up first
(`/__slop/pump-supervise`).

Timeline (seconds from the start of the main phase, `main_s`): a DM driver (DMS_PER_MIN per Creator, `push_dm`) and an
elsewhere driver (every ELSEWHERE_S an unread chat read in OF web, `read_elsewhere`: an unexplained counter frame,
so an Attribution read; `at_429` Creators get theirs MEET_429_S into each pulse instead, so a read meets the 429)
run throughout. DEAD_AT_S: `set_otp` on `dead` and their sockets dropped (the pump's
reconnect meets OF's code 101). PROXY_AT_S: the second proxy killed and DOWN_AFTER sends per `proxy_down` Creator fail
through it (counted: its watcher confirms it bad). From PULSE_AT_S: `at_429` Creators' chats route answers 429
(Retry-After RETRY_AFTER_S) PULSE_ON_S of every PULSE_PERIOD_S (20 %, `pulses`). HELD_AT_S: `held`'s socket dropped
every DROP_EVERY_S for HELD_S, its `/users/me` answering 500 meanwhile (`fail`: the pump reconnects through it, so
a reconnect in between, which would restart the 15 s grace, cannot land; reconnects are counted). FLAP_AT_S: one
`drop_ws` each on `flaps`. WALK_AT_S: one Employee (own login) walks Focus (actors/focus.py `cycle` over the owed
rows, `open_fan` each). Then the restart leg: the elsewhere driver
stops, the Relay is stopped and started (`stop_relay` / `start_relay`, same DB and env), pumps supervised, every tab
renews its lease and refetches; the DM driver keeps going for `restart_s` on the healthy Creators but `quiet`.

Checks: GREY_NOT_ZERO (`dead` from DEAD_GREY_S after the otp, `proxy_down` from PROXY_GREY_S after the kill, to the
restart: every Red circle the tab draws is grey, `judge_grey`); NO_READS_DEAD / NO_READS_PROXY_DOWN (same windows:
no `filter=unread` call at OF and no `badge_read` / `badge_read_failed` line in relay.log for them; through a dead
proxy a read never reaches OF, so the relay's own line is the evidence, `judge_no_reads`); READS_HOLD_ON_429 (no
`filter=unread` call to an `at_429` Creator before RETRY_AFTER_S after any of its chats reads, Attribution or window,
answered 429: the hold is the exit's, `judge_hold`);
SOCKET_DOWN_POLL_15S (`held`'s `filter=unread` read starts while held: >= 2, gaps POLL_S +- POLL_TOL_S,
`judge_polls`); RECOVERY_UNDER_30S (from each hold end, the held socket's end and each flap to the first instant the
tab draws red = `truth_red`, `judge_recovery`; an event with under RECOVERY_S left before the restart is not judged);
FOCUS_WALK_COMPLETES (every planned step answered, each within STEP_S, `judge_walk`); GREY_AFTER_RESTART (`quiet`
drawn grey from the post-restart refetch until `known_at`, and `filter=unread` read starts in the RESTART_WINDOW_S
after the restart <= Creators with a delivered counter frame, `judge_restart`; a Creator's starts before its socket
is back are its socket-down polls, judged only for a gap under POLL_S - POLL_TOL_S). A failed proxy setup, pumps not
all up, a failed Employee login, `held` with no socket to drop, no flap dropping a socket or no 429 met is INFRA. Every
check `ctx.skip`s while Phase C's grey causes (service/unread_total_decide.py DEAD / PROXY_DOWN) are absent. Evidence
`degraded.json`.

Bypasses (declared): OF at its wire (lib/badge_wire.py on lib/of_wire.py); proxies are SOCKS5 on loopback
(lib/proxy_wire.py); `PROXY_RECHECK_S=2` (RELAY_ENV) compresses proxy_health's cadence tenfold, as
2026-10-28-proxy-failover does; tabs are API tabs (the app's reducer and redCircle in node); the restart's lease and
refetch are the harness's, standing in for the app's reconnect.
ASSUMPTIONs: the proxy-down Creators sit on a custom proxy (never failed over; a pool proxy's Creators move off it in
~17 s here and stop being proxy-down); "429 on 20 %" is 20 % of the time in pulses; DEAD_GREY_S / PROXY_GREY_S are
the time the relay may take to learn the fault; a 200 `/users/me` or chats answer is the earliest a restarted relay
can know a Creator's value.
"""
from __future__ import annotations

import ast
import asyncio
import json
import re
import threading
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import parse_qs

from slop.actors.badge_tab import BadgeTab, classify, open_ts
from slop.actors.focus import Chatter, cycle
from slop.lib.badge_metrics import group_reads, _unread_calls
from slop.lib.badge_wire import BadgeWire, chat_plan
from slop.lib.client import Recorder, actor_call
from slop.lib.proxy_wire import ProxyWire
from slop.lib.service_constant import service_number
from slop.seed import chatters as chatters_seed

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = None
TIMEOUT_S = 900
EXPECTED_TRACEBACKS = (("roster-counts: OF read failed", "cannot complete SOCKS5 connection"),)
RELAY_ENV = {"INGEST_FAST_BOOT_GRACE_S": "0", "SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1", "PROXY_RECHECK_S": "2"}
TIERS = {"small": {"creators": 6, "at_429": 1, "dead": 2, "proxy_down": 1, "flaps": 5, "main_s": 240.0,
                   "restart_s": 60.0},
         "full": {"creators": 50, "at_429": 10, "dead": 2, "proxy_down": 2, "flaps": 5, "main_s": 300.0,
                  "restart_s": 60.0}}
GREY_NOT_ZERO = "GREY_NOT_ZERO"
NO_READS_DEAD = "NO_READS_DEAD"
NO_READS_PROXY_DOWN = "NO_READS_PROXY_DOWN"
READS_HOLD_ON_429 = "READS_HOLD_ON_429"
SOCKET_DOWN_POLL_15S = "SOCKET_DOWN_POLL_15S"
RECOVERY_UNDER_30S = "RECOVERY_UNDER_30S"
FOCUS_WALK_COMPLETES = "FOCUS_WALK_COMPLETES"
GREY_AFTER_RESTART = "GREY_AFTER_RESTART"
CHECKS = (GREY_NOT_ZERO, NO_READS_DEAD, NO_READS_PROXY_DOWN, READS_HOLD_ON_429, SOCKET_DOWN_POLL_15S,
          RECOVERY_UNDER_30S, FOCUS_WALK_COMPLETES, GREY_AFTER_RESTART)
CHATS = 20
UNREAD = 5
DMS_PER_MIN = 10.0
ELSEWHERE_S = 6.0
DEAD_AT_S = 10.0
PROXY_AT_S = 10.0
PULSE_AT_S = 20.0
PULSE_ON_S = 6.0
PULSE_PERIOD_S = 30.0
RETRY_AFTER_S = 20
MEET_429_S = 0.5
HOLD_JITTER_S = 0.5
PACED_RETRY_S = sum(service_number("of_pacing", n, as_float=True)
                    for n in ("RETRY_DEFAULT_S", "PAGE_GAP_S", "JITTER_S")) + HOLD_JITTER_S
HELD_AT_S = 60.0
HELD_S = 45.0
DROP_EVERY_S = 1.0
FLAP_AT_S = (120.0, 135.0, 150.0, 165.0, 180.0)
WALK_AT_S = 30.0
STEP_S = 15.0
DEAD_GREY_S = 30.0
PROXY_GREY_S = 30.0
RECOVERY_S = 30.0
POLL_S = 15.0           # badge_reads.POLL_MS
POLL_TOL_S = 5.0
RESTART_WINDOW_S = 60.0
PUMP_UP_S = 30.0
SLOT_WAIT_S = 45.0
SAMPLE_S = 0.05
CHATS_ROUTE = "GET /api2/v2/chats"
ME_ROUTE = "GET /api2/v2/users/me"
LIVE_PROXY, DOWN_PROXY = "slop-badge-429", "slop-badge-down"
DOWN_AFTER = service_number("proxy_health_decide", "DOWN_AFTER")
ROOT = Path(__file__).resolve().parents[2]
_LOG_READ = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) .*?\b(?:badge_read|badge_read_failed) "
                       r"account=(\S+)(.*)$", re.M)


def plan(fans: list[dict]) -> list[dict]:
    return chat_plan(fans, [("plain", UNREAD, True), ("plain", CHATS - UNREAD, False)])


def roles(creators: list[str], tier: dict) -> dict:
    it = iter(creators)
    at_429 = [next(it) for _ in range(tier["at_429"])]
    held = next(it)
    dead = [next(it) for _ in range(tier["dead"])]
    proxy_down = [next(it) for _ in range(tier["proxy_down"])]
    healthy = list(it)
    pool = healthy + at_429
    return {"at_429": at_429, "held": held, "dead": dead, "proxy_down": proxy_down, "healthy": healthy,
            "quiet": healthy[-1], "flaps": [pool[i % len(pool)] for i in range(tier["flaps"])]}


def pulses(start: float, end: float) -> list[tuple[float, float]]:
    out, a = [], start
    while a + PULSE_ON_S <= end:
        out.append((a, a + PULSE_ON_S))
        a += PULSE_PERIOD_S
    return out


def phase_c() -> bool:
    tree = ast.parse((ROOT / "service" / "unread_total_decide.py").read_text())
    names = set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                names |= {e.id for e in (t.elts if isinstance(t, ast.Tuple) else [t]) if isinstance(e, ast.Name)}
    return {"DEAD", "PROXY_DOWN"} <= names


def _state(series: list[tuple[float, object]], t: float):
    last = None
    for ts, v in series:
        if ts > t:
            break
        last = v
    return last


def _is_unread(c: dict) -> bool:
    return c.get("route") == CHATS_ROUTE and (parse_qs(c.get("query") or "").get("filter") or [""])[0] == "unread"


def _is_429(c: dict) -> bool:
    return c.get("route") == CHATS_ROUTE and c.get("status") == 429


def log_reads(text: str) -> list[tuple[float, str]]:
    """(epoch s, Creator) of every Attribution read attempt relay.log logged (`badge_read`, `badge_read_failed`;
    hover reads are window reads, left out)."""
    return [(time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + int(m.group(2)) / 1000, m.group(3))
            for m in _LOG_READ.finditer(text) if "kind=hover" not in m.group(4)]


def judge_grey(drawn: dict[str, list[tuple[float, object]]], windows: dict[str, tuple[float, float]]) -> tuple:
    """Every Red circle drawn inside each Creator's window (the one held at its start included) is grey."""
    judged, bad = 0, {}
    for aid, (lo, hi) in windows.items():
        series = sorted(drawn.get(aid) or [], key=lambda x: x[0])
        at_lo = _state(series, lo)
        pts = ([(lo, at_lo)] if at_lo is not None else []) + [(t, v) for t, v in series if lo < t <= hi]
        if not pts:
            continue
        judged += 1
        wrong = [(round(t, 3), v) for t, v in pts if v != "grey"]
        if wrong:
            bad[aid] = wrong[:5]
    return (None if not judged else not bad), {"judged": judged, "numbers": bad}


def judge_no_reads(calls: list[dict], logs: list[tuple[float, str]],
                   windows: dict[str, tuple[float, float]]) -> tuple:
    if not windows:
        return None, {"creators": 0}
    unread = _unread_calls(calls)
    per = {}
    for aid, (lo, hi) in windows.items():
        of = sum(1 for t0, _t, a, _o in unread if a == aid and lo <= t0 <= hi)
        rl = sum(1 for t, a in logs if a == aid and lo <= t <= hi)
        per[aid] = {"of_calls": of, "relay_log": rl}
    return not any(v["of_calls"] or v["relay_log"] for v in per.values()), {"per_creator": per}


def judge_hold(calls: list[dict], aids: list[str], retry_after_s: float) -> tuple:
    """The exit hold starts at a terminal 429: of_pacing.paced retries a 429 once, the same call PACED_RETRY_S after
    it (the spec's "a terminal 429 -> hold"), and that retry is no early read."""
    chats = sorted((c for c in calls if c.get("route") == CHATS_ROUTE and str(c["account"]) in aids),
                   key=lambda c: c["t0"])
    retries: set[int] = set()
    holds = []
    for i, c in enumerate(chats):
        if c.get("status") != 429:
            continue
        nxt = None if id(c) in retries else next(
            (x for x in chats[i + 1:] if x["account"] == c["account"] and x.get("query") == c.get("query")), None)
        if nxt is not None and nxt["t0"] - c["t"] <= PACED_RETRY_S:
            retries.add(id(nxt))
        else:
            holds.append((c["t"], str(c["account"])))
    if not holds:
        return None, {"holds": 0}
    unread = [c for c in chats if _is_unread(c) and id(c) not in retries]
    early = [{"creator": aid, "held_at": round(t, 3), "read_at": round(c["t0"], 3),
              "early_s": round(t + retry_after_s - c["t0"], 3)}
             for t, aid in holds for c in unread
             if str(c["account"]) == aid and t < c["t0"] < t + retry_after_s - HOLD_JITTER_S]
    return not early, {"holds": len(holds), "paced_retries": len(retries), "early": early[:10],
                       "retry_after_s": retry_after_s}


def judge_polls(calls: list[dict], aid: str, lo: float, hi: float) -> tuple:
    starts = sorted(r.start for r in group_reads(calls) if r.account == aid and lo <= r.start <= hi)
    gaps = [round(b - a, 3) for a, b in zip(starts, starts[1:])]
    ok = len(starts) >= 2 and all(POLL_S - POLL_TOL_S <= g <= POLL_S + POLL_TOL_S for g in gaps)
    return ok, {"polls": len(starts), "gaps_s": gaps, "window_s": round(hi - lo, 1)}


def recovery(truth: list[tuple[float, int]], drawn: list[tuple[float, object]], end: float,
             judge_end: float) -> float | None:
    """Seconds from `end` to the first instant the drawn Red circle equals truth (never grey), None when not by
    `judge_end`."""
    truth, drawn = sorted(truth, key=lambda x: x[0]), sorted(drawn, key=lambda x: x[0])
    for c in sorted({end} | {t for t, _ in truth + drawn if end < t <= judge_end}):
        d = _state(drawn, c)
        if d is not None and d != "grey" and d == _state(truth, c):
            return c - end
    return None


def judge_recovery(events: list[tuple[str, str, float, float, list, list]]) -> tuple:
    """`events`: (Creator, kind, fault end, judge end, truth series, drawn series)."""
    out, judged, slow = [], 0, []
    for aid, kind, end, judge_end, truth, drawn in events:
        if judge_end - end < RECOVERY_S:
            out.append({"creator": aid, "kind": kind, "judged": False})
            continue
        judged += 1
        rec = recovery(truth, drawn, end, judge_end)
        row = {"creator": aid, "kind": kind, "recovery_s": None if rec is None else round(rec, 3)}
        out.append(row)
        if rec is None or rec >= RECOVERY_S:
            slow.append(row)
    return (None if not judged else not slow), {"judged": judged, "slow": slow[:10], "events": out[:40],
                                                "budget_s": RECOVERY_S}


def judge_walk(planned: int, steps: list[tuple[float, float | None]]) -> tuple:
    if not planned:
        return None, {"planned": 0}
    slow = [{"step": i, "s": None if e is None else round(e - s, 3)} for i, (s, e) in enumerate(steps)
            if e is None or e - s > STEP_S]
    return len(steps) == planned and not slow, {"planned": planned, "done": len(steps), "slow": slow[:10],
                                                "step_s": STEP_S}


def known_at(calls: list[dict], frames: list[dict], aid: str, t_ready: float, t_end: float) -> float:
    """The earliest a restarted relay could know `aid`'s value: its first counter frame, or 200 `/users/me` or chats
    answer, after `t_ready`; `t_end` when none."""
    ts = [f["t"] for f in frames if str(f["account"]) == aid and f["kind"] == "counter" and f["t"] >= t_ready]
    ts += [c["t"] for c in calls if str(c["account"]) == aid and c.get("route") in (ME_ROUTE, CHATS_ROUTE)
           and c.get("status") == 200 and c["t0"] >= t_ready]
    return min(ts, default=t_end)


def judge_restart(calls: list[dict], frames: list[dict], quiet: str, drawn: list[tuple[float, object]],
                  t_ready: float, t_seeded: float, t_end: float, back: dict[str, float]) -> tuple:
    """`frames`: the counter frames delivered after the restart (the caller drops those sent to no socket).
    `back`: each Creator's first socket connect after the restart; its read starts before that are its socket-down
    polls (SOCKET_DOWN_POLL_15S's cadence, not a storm), the rest are bounded by the Creators with a frame."""
    t_known = known_at(calls, frames, quiet, t_ready, t_end)
    grey_ok, grey = judge_grey({quiet: drawn}, {quiet: (t_seeded, t_known)})
    hi = min(t_ready + RESTART_WINDOW_S, t_end)
    starts = [r for r in group_reads(calls) if t_ready <= r.start <= hi]
    polls = [r for r in starts if r.start < back.get(r.account, float("inf"))]
    reads = [r for r in starts if r not in polls]
    by: dict[str, list[float]] = {}
    for r in polls:
        by.setdefault(r.account, []).append(r.start)
    fast = {a: [round(y - x, 3) for x, y in zip(ts, ts[1:]) if y - x < POLL_S - POLL_TOL_S] for a, ts in by.items()}
    fast = {a: g for a, g in fast.items() if g}
    with_frame = {str(f["account"]) for f in frames if f["kind"] == "counter" and t_ready <= f["t"] <= hi}
    storm_ok = len(reads) <= len(with_frame) and not fast
    return storm_ok and grey_ok is not False, {
        "quiet_grey": grey_ok, "quiet": grey, "known_after_s": round(t_known - t_ready, 3),
        "read_starts": len(reads), "creators_with_frame": len(with_frame),
        "per_creator": dict(Counter(r.account for r in reads)),
        "socket_down_polls": dict(Counter(r.account for r in polls)), "fast_polls": fast}


class Truth:
    """`truth_red` per Creator every SAMPLE_S on its own thread: `red[aid]` is `(t, value)` per change."""

    def __init__(self, wire: BadgeWire, aids: list[str]) -> None:
        self.wire, self.aids = wire, aids
        self.red: dict[str, list[tuple[float, int]]] = {a: [] for a in aids}
        self._halt = threading.Event()
        self._t = threading.Thread(target=self._run, name="badge-truth", daemon=True)
        self._t.start()

    def _run(self) -> None:
        while not self._halt.is_set():
            t = time.time()
            for a in self.aids:
                v = self.wire.truth_red(a)
                if not self.red[a] or self.red[a][-1][1] != v:
                    self.red[a].append((t, v))
            self._halt.wait(SAMPLE_S)

    def stop(self) -> None:
        self._halt.set()
        self._t.join(5)


def _owed(fake, aid: str) -> list[dict]:
    with fake.lock:
        return [json.loads(json.dumps(r)) for r in fake.chats.get(aid, ())
                if r.get("unreadMessagesCount") and ((r.get("lastMessage") or {}).get("fromUser") or {}).get("id")
                == r["withUser"]["id"]]


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = tier["creators"]
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    seeds = {aid: plan(w.data["fans"][aid]) for aid in creators}
    assert all(len(s) == CHATS for s in seeds.values()), f"each Creator needs {CHATS} fans"
    r = roles(creators, tier)
    ctx.metric("world", {"tier": tier_name, **tier, "roles": r, "chats_per_creator": CHATS, "unread": UNREAD,
                         "phase_c": phase_c()})
    if not phase_c():
        for name in CHECKS:
            ctx.skip(name, "Phase C's grey causes (service/unread_total_decide.py DEAD / PROXY_DOWN) are absent")
        return
    wire = BadgeWire(fake).install()
    for aid, fans in seeds.items():
        wire.seed(aid, fans)
    truth = Truth(wire, creators)
    tabs: list[BadgeTab] = []
    sessions = await open_ts(ctx, 1)
    try:
        with ExitStack() as stack:
            live_px, down_px = stack.enter_context(ProxyWire()), stack.enter_context(ProxyWire())
            await _degraded(ctx, tier, fake, wire, truth, tabs, sessions[0], creators, seeds, r, live_px, down_px)
    finally:
        await asyncio.gather(*(t.stop() for t in tabs), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)
        truth.stop()
        wire.close()


async def _degraded(ctx, tier: dict, fake, wire: BadgeWire, truth: Truth, tabs: list[BadgeTab], ts,
                    creators: list[str], seeds: dict, r: dict, live_px: ProxyWire, down_px: ProxyWire) -> None:
    owner, w = ctx.owner, ctx.world
    rng = w.rng("scenario:badge-edge-degraded")
    infra: list[str] = []
    setup = {}
    for label, px, aids in ((LIVE_PROXY, live_px, r["at_429"]), (DOWN_PROXY, down_px, r["proxy_down"])):
        made = (await owner.post("/admin/proxies", json={"label": label, "scheme": "socks5", "host": "127.0.0.1",
                                                         "port": px.port})).status_code
        bound = [(await owner.post("/admin/proxies/assign", json={"label": label, "account_id": a})).status_code
                 for a in aids]
        setup[label] = {"create": made, "assign": bound}
        if made != 200 or any(b != 200 for b in bound):
            infra.append(f"proxy {label} setup {setup[label]}")
    t_pumps = time.time()
    (await owner.post("/__slop/pump-supervise")).raise_for_status()
    up: set = set()
    while time.time() - t_pumps < PUMP_UP_S and len(up) < len(creators):
        await asyncio.sleep(0.25)
        with fake.lock:
            up = {c["account"] for c in fake.ws_connects if c["t"] >= t_pumps}
    ctx.metric("pumps_up", {"connected": len(up), "creators": len(creators), "proxies": setup,
                            "seconds": round(time.time() - t_pumps, 1)})
    if len(up) < len(creators):
        infra.append(f"pumps up {len(up)} of {len(creators)}")
    tabs += [BadgeTab(ctx, f"{a}-t0", [a], ts) for a in creators]
    await asyncio.gather(*(t.start() for t in tabs))
    by = {t.aids[0]: t for t in tabs}
    t_slot = time.time()
    while time.time() - t_slot < SLOT_WAIT_S:
        held = [by[a].held(a) for a in creators]
        if all(isinstance(s, dict) and isinstance(s.get("n"), int) and s.get("grey") is None for s in held):
            break
        await asyncio.sleep(1.0)
        await asyncio.gather(*(by[a].refetch() for a in creators))
    ctx.metric("slot_ready", {"seconds": round(time.time() - t_slot, 1),
                              "held": {a: by[a].held(a) for a in creators}})
    recs = await chatters_seed.seed(w, owner, w.user_id, [f"{w.user_prefix}walk0"], account_ids=[creators])
    chatter = Chatter(recs[0], creators[0])
    login = await chatter.login(str(owner.c.base_url), owner.rec)
    if login != 200:
        infra.append(f"Employee login {login}")

    plain = {aid: [f["id"] for f in fans] for aid, fans in seeds.items()}
    no_dm: set[str] = set()
    halt_dm, halt_else = asyncio.Event(), asyncio.Event()
    log: dict = {"drops": [], "flaps": [], "pulses": [], "walk": [], "planned": 0}
    main_s, t0 = tier["main_s"], time.time()

    async def at(s: float) -> None:
        await asyncio.sleep(max(0.0, t0 + s - time.time()))

    async def every(period: float, halt: asyncio.Event, fn) -> None:
        await asyncio.sleep(rng.uniform(0, period))
        while not halt.is_set():
            fn()
            try:
                await asyncio.wait_for(halt.wait(), period)
            except asyncio.TimeoutError:
                pass

    def dm(aid: str):
        return lambda: None if aid in no_dm else wire.push_dm(aid, {"id": rng.choice(plain[aid])})

    def elsewhere(aid: str):
        def go() -> None:
            unread = sorted(wire.truth_unread(aid))
            if unread:
                wire.read_elsewhere(aid, rng.choice(unread))
        return go

    async def dead() -> None:
        await at(DEAD_AT_S)
        log["t_otp"] = fake.set_otp(r["dead"])
        log["dead_dropped"] = await asyncio.to_thread(fake.drop_ws, r["dead"])

    async def proxy_down() -> None:
        await at(PROXY_AT_S)
        http = owner.share(rec=Recorder(), limits=2 * DOWN_AFTER + 4)   # declared: these sends 502 on purpose
        log["t_kill"] = down_px.kill()
        sends = await asyncio.gather(*(
            actor_call(http, "send", a, f"/api/of/v2/chats/{plain[a][i % CHATS]}/messages", "POST",
                       {"text": f"slop badge-edge-degraded {i} {a}"})
            for a in r["proxy_down"] for i in range(DOWN_AFTER)))
        log["down_sends"] = dict(Counter(s["status"] for s in sends))
        await http.aclose()

    async def at_429() -> None:
        for a, b in pulses(PULSE_AT_S, main_s - RETRY_AFTER_S - RECOVERY_S):
            await at(a)
            on = time.time()
            for aid in r["at_429"]:
                fake.status[(aid, CHATS_ROUTE)] = (429, RETRY_AFTER_S)
            await asyncio.sleep(MEET_429_S)
            for aid in r["at_429"]:
                elsewhere(aid)()
            await at(b)
            for aid in r["at_429"]:
                fake.status.pop((aid, CHATS_ROUTE), None)
            log["pulses"].append((on, time.time()))

    async def held() -> None:
        await at(HELD_AT_S)
        log["t_held"] = time.time()
        fake.fail.add((r["held"], ME_ROUTE))
        while time.time() - log["t_held"] < HELD_S:
            log["drops"].append((time.time(), await asyncio.to_thread(fake.drop_ws, [r["held"]])))
            await asyncio.sleep(DROP_EVERY_S)
        fake.fail.discard((r["held"], ME_ROUTE))
        log["t_held_end"] = log["drops"][-1][0]

    async def flaps() -> None:
        for s, aid in zip(FLAP_AT_S, r["flaps"]):
            await at(s)
            log["flaps"].append((aid, time.time(), await asyncio.to_thread(fake.drop_ws, [aid])))

    async def walk() -> None:
        await at(WALK_AT_S)
        if login != 200:
            return
        order = cycle({a: _owed(fake, a) for a in creators}, await chatter.tabs() or creators)
        log["planned"] = len(order)
        for aid, fan in order:
            s = time.time()
            try:
                await asyncio.wait_for(chatter.open_fan(aid, fan), 2 * STEP_S)
                log["walk"].append((s, time.time()))
            except asyncio.TimeoutError:
                log["walk"].append((s, None))

    readers = [a for a in creators if a not in r["dead"] + r["proxy_down"] + r["at_429"]]
    drivers = [asyncio.create_task(every(60.0 / DMS_PER_MIN, halt_dm, dm(a))) for a in creators]
    drivers += [asyncio.create_task(every(ELSEWHERE_S, halt_else, elsewhere(a))) for a in readers]
    try:
        await asyncio.gather(dead(), proxy_down(), at_429(), held(), flaps(), walk(), at(main_s))
        halt_else.set()
        t_stop = time.time()
        no_dm.update([r["quiet"], *r["dead"], *r["proxy_down"]])
        await asyncio.to_thread(ctx.stack.stop_relay)
        await asyncio.to_thread(ctx.stack.start_relay)
        t_ready = time.time()
        (await owner.post("/__slop/pump-supervise")).raise_for_status()
        await asyncio.gather(*(t._lease() for t in tabs))
        await asyncio.gather(*(t.refetch() for t in tabs))
        t_seeded = time.time()
        await asyncio.sleep(max(0.0, t_ready + tier["restart_s"] - time.time()))
        t_end = time.time()
    finally:
        halt_dm.set()
        halt_else.set()
        await asyncio.gather(*drivers, return_exceptions=True)
        await chatter.close()
    await classify(tabs, ts)

    with fake.lock:
        calls = list(fake.calls)
        connects = list(fake.ws_connects)
    frames = list(wire.frames)
    text = (ctx.out / "relay.log").read_text(errors="replace") if (ctx.out / "relay.log").exists() else ""
    logs = log_reads(text)
    drawn = {a: by[a].red(a) for a in creators}
    if not any(n for _, n in log["drops"]):
        infra.append("the held Creator had no socket to drop")
    flapped = [(aid, t) for aid, t, n in log["flaps"] if n]
    if not flapped:
        infra.append("no flap dropped a socket")

    dead_w = {a: (log["t_otp"] + DEAD_GREY_S, t_stop) for a in r["dead"]}
    down_w = {a: (log["t_kill"] + PROXY_GREY_S, t_stop) for a in r["proxy_down"]}
    verdict = {GREY_NOT_ZERO: judge_grey(drawn, {**dead_w, **down_w}),
               NO_READS_DEAD: judge_no_reads(calls, logs, dead_w),
               NO_READS_PROXY_DOWN: judge_no_reads(calls, logs, down_w),
               READS_HOLD_ON_429: judge_hold(calls, r["at_429"], RETRY_AFTER_S),
               SOCKET_DOWN_POLL_15S: judge_polls(calls, r["held"], log["t_held"], log["t_held_end"])}
    if verdict[READS_HOLD_ON_429][0] is None:
        infra.append("no 429 met a chats read")

    events = [(aid, "flap", t, t_stop, truth.red[aid], drawn[aid]) for aid, t in flapped]
    events.append((r["held"], "held", log["t_held_end"], t_stop, truth.red[r["held"]], drawn[r["held"]]))
    for a, b in log["pulses"]:
        for aid in r["at_429"]:
            met = [c["t"] for c in calls
                   if _is_429(c) and str(c["account"]) == aid and a <= c["t"] <= b + RETRY_AFTER_S]
            end = max([b, *(t + RETRY_AFTER_S for t in met)])
            events.append((aid, "hold", end, t_stop, truth.red[aid], drawn[aid]))
    verdict[RECOVERY_UNDER_30S] = judge_recovery(events)
    verdict[FOCUS_WALK_COMPLETES] = judge_walk(log["planned"], log["walk"])

    back = {}
    for c in connects:
        if c["t"] >= t_ready:
            back.setdefault(str(c["account"]), c["t"])
    delivered = [f for f in frames if f["t"] >= t_ready and str(f["account"]) in back
                 and f["t"] >= back[str(f["account"])]]
    restart_calls = [c for c in calls if c["t0"] >= t_ready]
    verdict[GREY_AFTER_RESTART] = judge_restart(restart_calls, delivered, r["quiet"], drawn[r["quiet"]],
                                                t_ready, t_seeded, t_end, back)

    ctx.metric("faults", {"t_otp": log["t_otp"] - t0, "dead_dropped": log.get("dead_dropped"),
                          "t_kill": log["t_kill"] - t0, "down_sends": log.get("down_sends"),
                          "pulses": [(round(a - t0, 1), round(b - t0, 1)) for a, b in log["pulses"]],
                          "held_drops": sum(1 for _, n in log["drops"] if n), "drops": len(log["drops"]),
                          "held_reconnects": sum(1 for c in connects if str(c["account"]) == r["held"]
                                                 and log["t_held"] <= c["t"] <= log["t_held_end"]),
                          "flaps": [(aid, round(t - t0, 1), n) for aid, t, n in log["flaps"]],
                          "restart": {"stop": round(t_stop - t0, 1), "ready": round(t_ready - t0, 1),
                                      "seconds": round(t_ready - t_stop, 1)}})
    reads = group_reads(calls)
    ctx.metric("attribution_reads", {"reads": len(reads), "per_creator": dict(Counter(x.account for x in reads)),
                                     "relay_log_attempts": len(logs)})
    ctx.metric("tabs", {t.name: {"pings": t.pings, "refetches": t.refetches, "errors": t.errors[:10]} for t in tabs})
    if infra:
        ctx.report.infra = ctx.report.infra or "badge-edge-degraded inconclusive: " + "; ".join(infra)
    for name in CHECKS:
        ok, detail = verdict[name]
        ctx.check(name, ok, **detail)
    (ctx.out / "degraded.json").write_text(json.dumps({
        "t0": t0, "t_stop": t_stop, "t_ready": t_ready, "t_seeded": t_seeded, "t_end": t_end, "roles": r,
        "truth_red": truth.red, "drawn": drawn, "log": log, "relay_log_reads": logs,
    }, default=str))
