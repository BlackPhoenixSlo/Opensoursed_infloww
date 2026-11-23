"""Creator badges scenario 3 (docs/spec/creator-badges/phase-0E-slop-and-fake-of-realism.md story 21; phase-0C story
36): 30 chatters hovering 10 Creators for 2 min cost at most one page-0 `list_chats` window read per Creator per 30 s
(the shared Hover cooldown), and every hover answers the fold of the newest read, never an older one.

World: `flat_agency` with CREATORS Creators, each a captured session (the relay's REAL OFClient against
lib/of_wire.py, `OF_WIRE`) whose OF is lib/badge_wire.py (counter frames off: nothing here moves the counter), each
OF chat list CHATS chats, UNREAD of them unread. Every window page answers WINDOW_PAGE_S late (`route_s`), so a
read is in flight long enough for other hovers to land inside it. CHATTERS Employees (real invite + register), each
working every Creator, each signed in with its own login.

Actors: each chatter loops for HOVER_S: `GET /admin/accounts/roster-counts?bust=<random Creator>` (the hover
warm-up / All Models pick), then HOVER_EVERY_S. No chatter opens `/events` or a View lease, so no Creator has an
Open tab: the Shared refresher and Attribution read nothing, and every page-0 window call is a bust's.

Checks: HOVER_ONE_READ_PER_30S (page-0 window calls, `lib/badge_metrics.window_reads`, per Creator at least
COOLDOWN_S - JITTER_S apart, `gap_ok`); HOVER_ANSWERS_FRESH (every bust answer's `as_of` is no older than the newest
window read of its Creator that started before the bust was sent: a bust landing while a read is in flight waits
for it, `stale_answers`). Fewer than MIN_BUSTS answers, a failed chatter login, more than ERROR_MAX of busts
failing, or no bust landing inside a read (the follower path unexercised) is INFRA. Every check `ctx.skip`s while
Phase C's Hover cooldown (service/badge_reads_decide.py `hover`) is absent. Evidence `shared-hover.json`.

Bypasses (declared): OF at its wire (lib/badge_wire.py on lib/of_wire.py); hovers are API calls, no browser (the
app's hover chain is one `?bust=` then a list refetch the warm entry answers; the refetch is Phase D's subject).
"""
from __future__ import annotations

import ast
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from slop.lib.badge_metrics import gap_ok, stale_answers, window_reads
from slop.lib.badge_wire import BadgeWire, chat_plan
from slop.lib.client import Http
from slop.lib.service_constant import service_number
from slop.seed import chatters as chatters_seed

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = None
TIMEOUT_S = 900
RELAY_ENV = {"INGEST_FAST_BOOT_GRACE_S": "0", "SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1"}
TIERS = {"small": {"creators": 10, "chatters": 30, "hover_s": 120.0},
         "full": {"creators": 10, "chatters": 30, "hover_s": 120.0}}
HOVER_ONE_READ_PER_30S = "HOVER_ONE_READ_PER_30S"
HOVER_ANSWERS_FRESH = "HOVER_ANSWERS_FRESH"
CHECKS = (HOVER_ONE_READ_PER_30S, HOVER_ANSWERS_FRESH)
COOLDOWN_S = 30.0       # badge_reads_decide.HOVER_COOLDOWN_MS
JITTER_S = 1.0          # ASSUMPTION: the relay stamps the bust, its page-0 call starts a lane wait later
HOVER_EVERY_S = (2.0, 5.0)
WINDOW_PAGE_S = 0.5
WINDOW_ROUTE = "GET /api2/v2/chats"
CHATS = 20
UNREAD = 5
MIN_BUSTS = 300
ERROR_MAX = 0.05
ROOT = Path(__file__).resolve().parents[2]
# One loopback address: past login_throttle's per-IP bucket at once, logins 429 before any right password refunds.
LOGINS_AT_ONCE = service_number("login_throttle", "IP_CAPACITY")


def plan(fans: list[dict]) -> list[dict]:
    return chat_plan(fans, [("plain", UNREAD, True), ("plain", CHATS - UNREAD, False)])


def phase_c() -> bool:
    tree = ast.parse((ROOT / "service" / "badge_reads_decide.py").read_text())
    return any(isinstance(n, ast.FunctionDef) and n.name == "hover" for n in tree.body)


def judge(calls: list[dict], answers: list[tuple[float, float, str, float]], creators: list[str]) -> dict:
    """{check: (ok | None, detail)} over the fake's calls and the bust answers (sent, answered, Creator, as_of s)."""
    reads = window_reads(calls)
    per, worst = {}, {}
    for aid in creators:
        ok, gap = gap_ok([t0 for t0, _t, a in reads if a == aid], COOLDOWN_S - JITTER_S)
        per[aid] = sum(1 for r in reads if r[2] == aid)
        if not ok:
            worst[aid] = round(gap, 3)
    judged, stale = stale_answers(answers, reads)
    return {
        HOVER_ONE_READ_PER_30S: (None if not reads else not worst,
                                 {"reads": per, "too_close": worst, "min_gap_s": COOLDOWN_S - JITTER_S}),
        HOVER_ANSWERS_FRESH: (None if not judged else not stale,
                              {"judged": judged, "stale": len(stale), "samples": [list(a) for a in stale[:10]]}),
    }


def joined(answers: list[tuple[float, float, str, float]], calls: list[dict]) -> int:
    """Busts sent while a window read of their Creator was in flight."""
    reads = window_reads(calls)
    return sum(1 for s, _a, aid, _o in answers if any(a == aid and t0 <= s < t for t0, t, a in reads))


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = tier["creators"]
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    seeds = {aid: plan(w.data["fans"][aid]) for aid in creators}
    assert all(len(s) == CHATS for s in seeds.values()), f"each Creator needs {CHATS} fans"
    ctx.metric("world", {"tier": tier_name, **tier, "chats_per_creator": CHATS, "unread": UNREAD,
                         "window_page_s": WINDOW_PAGE_S, "phase_c": phase_c()})
    if not phase_c():
        for name in CHECKS:
            ctx.skip(name, "Phase C's Hover cooldown (service/badge_reads_decide.py hover) is absent")
        return
    wire = BadgeWire(fake, counter_frames=False).install()
    try:
        for aid, fans in seeds.items():
            wire.seed(aid, fans)
        fake.route_s[WINDOW_ROUTE] = WINDOW_PAGE_S
        await _hover(ctx, w, fake, tier, creators)
    finally:
        wire.close()


async def sign_in(sem: asyncio.Semaphore, http, rec: dict) -> int:
    async with sem:
        r = await http.post("/chatter/login", json={"username": rec["username"], "password": rec["password"]})
    return r.status_code


async def _hover(ctx, w, fake, tier: dict, creators: list[str]) -> None:
    rng = ctx.world.rng("scenario:badge-edge-shared-hover")
    names = [f"{w.user_prefix}hov{i}" for i in range(tier["chatters"])]
    recs = await chatters_seed.seed(w, ctx.owner, w.user_id, names, account_ids=[creators] * len(names))
    base = str(ctx.owner.c.base_url)
    answers: list[tuple[float, float, str, float]] = []
    busts, failed, logins = Counter(), Counter(), Counter()
    sem = asyncio.Semaphore(LOGINS_AT_ONCE)
    with fake.lock:
        n_calls = len(fake.calls)
    t_start = time.time()
    t_end = t_start + tier["hover_s"]

    async def chatter(rec: dict) -> None:
        http = Http(base, ctx.owner.rec, limits=4)
        try:
            status = await sign_in(sem, http, rec)
            logins[status] += 1
            if status != 200:
                return
            await asyncio.sleep(rng.uniform(*HOVER_EVERY_S))
            while time.time() < t_end:
                aid = rng.choice(creators)
                sent = time.time()
                try:
                    r = await http.get(f"/admin/accounts/roster-counts?bust={aid}")
                    entry = (r.json().get("counts") or {}).get(aid) if r.status_code == 200 else None
                except Exception:  # noqa: BLE001 — counted as a failed bust
                    entry = None
                busts[aid] += 1
                if isinstance(entry, dict) and entry.get("as_of"):
                    answers.append((sent, time.time(), aid, entry["as_of"] / 1000))
                else:
                    failed[aid] += 1
                await asyncio.sleep(rng.uniform(*HOVER_EVERY_S))
        finally:
            await http.aclose()

    await asyncio.gather(*(chatter(r) for r in recs))
    with fake.lock:
        calls = [c for c in fake.calls[n_calls:]]
    verdict = judge(calls, answers, creators)
    n_joined = joined(answers, calls)
    total = sum(busts.values())
    ctx.metric("hovers", {"logins": dict(logins), "busts": total, "answered": len(answers), "failed": sum(failed.values()),
                          "per_creator": dict(busts), "joined_in_flight": n_joined,
                          "window_reads": len(window_reads(calls)), "seconds": round(time.time() - t_start, 1)})
    infra = []
    if logins.get(200, 0) != len(recs):
        infra.append(f"chatter logins {dict(logins)} of {len(recs)}")
    if total < MIN_BUSTS:
        infra.append(f"{total} busts < {MIN_BUSTS}")
    if total and sum(failed.values()) > ERROR_MAX * total:
        infra.append(f"{sum(failed.values())} of {total} busts failed")
    if not n_joined:
        infra.append("no bust landed while a window read was in flight (the follower path unexercised)")
    if infra:
        ctx.report.infra = ctx.report.infra or "badge-edge-shared-hover inconclusive: " + "; ".join(infra)
    for name in CHECKS:
        ok, detail = verdict[name]
        ctx.check(name, ok, **detail)
    (ctx.out / "shared-hover.json").write_text(json.dumps({
        "t_start": t_start, "t_end": t_end, "answers": answers, "window_reads": window_reads(calls),
    }, default=str))
