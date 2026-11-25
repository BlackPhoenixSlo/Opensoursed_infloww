from __future__ import annotations

import ast
import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

from slop.lib.all_models_wire import unread
from slop.lib.badge_metrics import counter_moves, relay_marks
from slop.lib.badge_wire import BadgeWire, chat_plan, restrict_in_relay
from slop.lib.client import Recorder
from slop.seed import ts

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = None
TIMEOUT_S = 900
TIERS = {"small": {"creators": 5}, "full": {"creators": 50}}
ZERO_RELAY_MARKS = "ZERO_RELAY_MARKS"
COUNTER_UNCHANGED_BY_SWEEP = "COUNTER_UNCHANGED_BY_SWEEP"
CHECKS = (ZERO_RELAY_MARKS, COUNTER_UNCHANGED_BY_SWEEP)
CHATS = 30
ONLY_FRIENDS = 2
DEEP = 4
DEEP_MSGS = 150
DEEP_ID_BASE = 7_200_000_000_000
ISO = "%Y-%m-%dT%H:%M:%S+00:00"
MSG_ROUTE = "GET /api2/v2/chats/{id}/messages"
SWEEP_ROUNDS = 60
SWEEP_DEADLINE_S = 720.0
# past badge_wire's first-page counter delay (0.9 s)
FRAME_TAIL_S = 2.0
ROOT = Path(__file__).resolve().parents[2]


def phase_a() -> bool:
    try:
        tree = ast.parse((ROOT / "service" / "of_reads.py").read_text())
    except (OSError, SyntaxError):
        return False
    return any(isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "PEEK_CURSOR" for t in n.targets)
               for n in tree.body)


def plan(fans: list[dict]) -> list[dict]:
    return chat_plan(fans, [("only_friends", ONLY_FRIENDS, True), ("restricted", 1, True), ("muted", 1, True),
                            ("deep", DEEP, True), ("plain", CHATS - ONLY_FRIENDS - 2 - DEEP, True)])


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = tier["creators"]
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    seeds = {aid: plan(w.data["fans"][aid]) for aid in creators}
    assert all(len(s) == CHATS for s in seeds.values()), f"each Creator needs {CHATS} fans"
    ctx.metric("world", {"tier": tier_name, "creators": len(creators), "chats_per_creator": CHATS,
                         "kinds": dict(Counter(f["kind"] for f in next(iter(seeds.values())))), "phase_a": phase_a()})
    if not phase_a():
        for name in CHECKS:
            ctx.skip(name, "Phase A (service/of_reads.py PEEK_CURSOR) is not merged")
        return

    wire = BadgeWire(fake).install()
    try:
        await _sweep(ctx, w, fake, wire, creators, seeds)
    finally:
        wire.close()


async def _sweep(ctx, w, fake, wire: BadgeWire, creators: list[str], seeds: dict[str, list[dict]]) -> None:
    deep: dict[tuple[str, int], list[dict]] = {}
    for aid, fans in seeds.items():
        wire.seed(aid, fans)
        for f in fans:
            if f["kind"] == "deep":
                base = DEEP_ID_BASE + (f["id"] % 1_000_000) * 1_000
                rows = [{"id": base + i, "text": f"talk {i}", "fromUser": {"id": int(aid)}, "isFree": True,
                         "price": 0, "media": [], "mediaCount": 0,
                         "createdAt": (datetime(2026, 11, 1) + timedelta(minutes=i)).strftime(ISO)}
                        for i in range(DEEP_MSGS, 0, -1)]
                rows[0] = {**rows[0], "text": "hey you there", "fromUser": {"id": f["id"]}}
                deep[(aid, f["id"])] = rows

    def deep_route(h, method, u, uid, route, _raw) -> bool:
        if method != "GET" or route != MSG_ROUTE:
            return False
        rows = deep.get((uid, int(u.path.rsplit("/", 2)[-2])))
        if rows is None:
            return False
        q = parse_qs(u.query)
        lim = int((q.get("limit") or ["10"])[0])
        if (q.get("order") or ["desc"])[0] == "asc":
            off = int((q.get("offset") or ["0"])[0])
            page, more = rows[::-1][off:off + lim], off + lim < len(rows)
        else:
            before = (q.get("id") or [None])[0]
            pool = [r for r in rows if before is None or r["id"] < int(before)]
            page, more = pool[:lim], len(pool) > lim
        h._record(uid, route, 200, {"list": page, "hasMore": more})
        return True

    with fake.lock:
        fake.extra_routes.append(deep_route)

    now = datetime.utcnow()
    con = w.sql()
    with con:
        restrict_in_relay(con, seeds)
        for aid in seeds:
            con.execute("INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts,"
                        " created_at) VALUES (?, 'scrape_chats', '{}', ?, 'pending', 0, ?)",
                        (aid, ts(now - timedelta(minutes=1)), ts(now)))
    con.close()

    def unread_set(aid: str) -> list[int]:
        with fake.lock:
            return sorted(r["withUser"]["id"] for r in fake.chats.get(aid, ()) if unread(r))

    def open_sweeps() -> Counter:
        con = w.sql()
        try:
            return Counter(r[0] for r in con.execute(
                "SELECT account_id FROM scheduled_jobs WHERE kind='scrape_chats' AND payload_json='{}'"
                " AND status IN ('pending', 'running')"))
        finally:
            con.close()

    raw_before = {aid: wire.raw_counter(aid) for aid in creators}
    unread_before = {aid: unread_set(aid) for aid in creators}
    with fake.lock:
        n_reads, n_frames, n_calls = len(wire.reads), len(wire.frames), len(fake.calls)
    hook = ctx.owner.share(rec=Recorder(), limits=2)
    ticks: list[dict] = []
    t0 = time.time()
    for k in range(SWEEP_ROUNDS):
        r = await hook.post("/__slop/automation-tick", timeout=600)
        r.raise_for_status()
        ticks.append({"round": k, **r.json()})
        if not open_sweeps() or time.time() - t0 > SWEEP_DEADLINE_S:
            break
    sweep_s = round(time.time() - t0, 1)
    left_open = dict(open_sweeps())
    await asyncio.sleep(FRAME_TAIL_S)

    with fake.lock:
        reads, frames, calls = list(wire.reads[n_reads:]), list(wire.frames[n_frames:]), list(fake.calls[n_calls:])
    raw_after = {aid: wire.raw_counter(aid) for aid in creators}
    unread_after = {aid: unread_set(aid) for aid in creators}
    thread_gets = [c for c in calls if c["route"] == MSG_ROUTE]
    pages = Counter(("asc" if (parse_qs(c["query"]).get("order") or ["desc"])[0] == "asc" else
                     "peek" if parse_qs(c["query"]).get("id") else "plain") for c in thread_gets)
    con = w.sql()
    try:
        runs = Counter(r[0] for r in con.execute(
            "SELECT status FROM automation_runs WHERE kind='scrape_chats'"))
    finally:
        con.close()
    marks = relay_marks(reads)
    moves = counter_moves(frames, raw_before)
    kind_of = {(aid, f["id"]): f["kind"] for aid, fans in seeds.items() for f in fans}
    unread_lost = {aid: [{"fan": fan, "kind": kind_of.get((aid, fan))}
                         for fan in sorted(set(unread_before[aid]) - set(unread_after[aid]))]
                   for aid in creators if unread_before[aid] != unread_after[aid]}
    raw_moved = {aid: (raw_before[aid], raw_after[aid]) for aid in creators if raw_before[aid] != raw_after[aid]}

    (ctx.out / "sweep-safety.json").write_text(json.dumps({
        "creators": creators, "ticks": ticks, "sweep_s": sweep_s, "left_open": left_open, "runs": dict(runs),
        "thread_gets": len(thread_gets), "thread_pages": dict(pages),
        "relay_marks": marks, "counter_frames": [f for f in frames if f["kind"] == "counter"],
        "raw_before": raw_before, "raw_after": raw_after, "unread_lost": unread_lost,
    }, indent=1, default=str))
    ctx.metric("sweep", {"seconds": sweep_s, "rounds": len(ticks), "left_open": left_open, "runs": dict(runs),
                         "thread_gets": len(thread_gets), "thread_pages": dict(pages),
                         "reads_logged": len(reads), "frames": len(frames)})
    if not thread_gets:
        ctx.report.infra = ctx.report.infra or "the sweep read no thread: nothing judged"
        for name in CHECKS:
            ctx.skip(name, "the sweep read no thread")
        return
    ctx.check(ZERO_RELAY_MARKS, not marks, relay_marks=len(marks), first=marks[:10], thread_gets=len(thread_gets),
              thread_pages=dict(pages), left_open=left_open)
    ctx.check(COUNTER_UNCHANGED_BY_SWEEP, not moves and not raw_moved and not unread_lost,
              raw_moved=raw_moved, counter_moves=moves[:10], unread_lost=dict(list(unread_lost.items())[:10]),
              raw_before_total=sum(raw_before.values()), unread_chats=sum(len(v) for v in unread_before.values()))
