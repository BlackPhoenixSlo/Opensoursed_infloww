"""Share for Share requests under racing owners (service/s4s_requests_api.py, s4s_schedule_api.py, s4s_api.py's
Discovery and blocks). Owners of BOTH sides act at once through the real routes; nothing posts to OnlyFans.

World (no seed/profiles shape fits, so the scenario composes seeders itself and records metric `seed` with profile
`s4s_requests`): `agency` n = `agencies`, `creators` spread evenly (`creators_per_agency`),
`seed/s4s_profiles.py`: an S4S profile per Creator (10% opted out, Daily limit 1-3, 1-3 posts with a Primary),
`blocks` Agency blocks on other Agencies' Creators. Every size is in seed.SCALES as `s4s_requests_<key>` (`--set key=N`).

Load, every plan drawn from the seed (never from an answer). Days are UTC offsets from today, one per group so no
group fills another's Daily limit, except FULL_DAY (the first limit group) and UI_DAY (the UI request):
  sends     POST /admin/s4s/requests for every group below by the sender's owner, at most `--users` at once.
  race      `race_groups` requests, each answered by `racers` simultaneous calls: receiver's accept/decline/skip
            ("answer"), or accept/decline vs the sender's cancel ("vs_cancel", no skip: skip then cancel is two
            legal moves). `--users // racers` groups in flight.
  limit     `limit_targets` Creators each get limit+2 requests for one day from distinct senders; the target's
            owner accepts all of them at once (each group's accepts together, all groups together).
  booking   `bookings` requests accepted once (at most `--users` at once); then per booking the sender's owner
            cancels its own slot twice at once while the receiver's owner tries the same slot (not its own).
  blocks    each seeded block: send and proposal both ways (404), Discovery and /blocks of the blocking Agency.
  cap       Creator S1 sends CAP requests today (send + cancel, so the pair frees), then CAP+1 and CAP+2; Creator S2
            sends CAP - burst/2 the same way, then `burst` concurrent sends to distinct partners.
  readers   `--users` owners (agency i % n), each `read_rounds` x four page visits: Requests (GET /requests
            ?box=received + ?box=sent together), the proposal, Schedule, Discover (GET /discover + /blocks
            together), THINK_S apart, first visit staggered over 0-3 s, while all of the above runs (stage `load`).
  idle      SETTLE_S after the last write (stage `settle`), each of the `--users` owners opens Requests once (both
            boxes), staggered over CALM_SPREAD_S (stage `calm`): GET /requests on an idle relay.
  UI (UI run only): agency 0's owner opens /share-for-share/requests on its Creator U (which nothing else touches),
            shot `requests-trigger` (U's one pending request), clicks Accept, shot `requests-settled` (the
            "Share for Share Scheduled!" modal); then `schedule` (the new slot), `discover-creators`, `settings`.
            Side effect: the request row accepted with its 2 slots + 2 pending s4s_post jobs, and GET /requests.

Checks: lib/s4s_faults.py (names) — one winner per race, 2 slots + 2 pending jobs per accept else none, Daily limit
per Creator per day, the CAP/day cap sequential and racing, blocks, one `actions` row per transition, racing slot
cancels, boxes / schedule / Discovery / proposal against the DB (proposals go to the FULL_DAY target, so the right
answer is a later day). Budgets: p95 GET /requests <= P95_MS under load (P95_LOAD) and idle (P95_IDLE), load-stage
p95s <= LOAD_CEILING_MS, P95_VS_LAST over the load-stage routes in VS_LAST_LOAD and the idle GET /requests.
KNOWN_RED checks are SKIPped with their open finding while they measure red, and FAIL once they measure green.

Bypasses (declared): Agencies through the real POST /auth/register; Creators, S4S profiles, posts and blocks are SQL
(seed/s4s_profiles.py: the rows the Settings save, the posts routes and POST /blocks write; display fields as an OF
/users/me read stores them). No OnlyFans: the relay runs no executor (CHATTERLY_TEST_MODE), so the s4s_post jobs
Accept queues stay pending and are only counted, never run. The UI's GET /admin/s4s/profiles reads each Creator's OF
/users/me, which fails offline and keeps the stored copy (the product's own fallback). Assertions read the temp DB
(sqlite, read-only). Guesses: readers' think time (THINK_S; with none, 200 back-to-back readers saturate the relay's
event loop: loop 84%, GET /requests p95 1525 ms, run 20261101T105220Z-2026-11-01-s4s-requests-race-f18a, measured),
the idle stage's SETTLE_S and CALM_SPREAD_S. Calls wait CALL_TIMEOUT_S, not the harness's 30 s (the UI's fetch has
none). A run that crosses 00:00 UTC would shift the CAP/day count (not guarded).

Faults: `s4s-accept-unguarded-update` (the scenario's FAULT) drops `_transition`'s status guard, so racing answers
both win: one-winner and slots/jobs go red. `s4s-daily-limit-skipped` makes Accept's and the proposal's limit test
always pass: the Daily-limit and proposal checks go red.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from slop.lib.s4s_faults import (AUDIT, BLOCKED, BOXES, CAP, CAP_RACE, CAP_SEQ, DAILY_LIMIT, DISCOVER, ONE_WINNER,
                                 PROPOSAL, SCHEDULE, SENDS, SLOT_CANCEL, SLOTS_JOBS, UI_ACCEPT, UI_PAGES)
from slop.seed import agency as agency_seed
from slop.seed import creators as creators_seed
from slop.seed import s4s_profiles

UI = True
FAULT = "s4s-accept-unguarded-update"
WORLD = "s4s_requests"
FULL_DAY, UI_DAY, UI_HOUR = 1, 2, 9    # day offsets from today (UTC); the UI request's hour
HOURS = (7, 22)                        # a planned slot's UTC hour range
PLAN_HEADROOM = 5                      # planned sends stay <= CAP - this per Creator; the cap senders top up
WINDOW_DAYS = 41                       # GET /schedule's window (the route allows at most 42 days)
PROPOSAL_DAYS, PROPOSAL_HOUR = 60, 6   # mirror service/s4s_requests_api.py
WAIT_MS, MODAL_MS, FADE_MS = 120_000, 30_000, 800  # UI waits; FADE_MS: the modal's fade-in before the shot
# Past the service's worst answer (busy_timeout 30 s + pool wait), as the UI's fetch (no timeout): at the harness's
# 30 s a slow write's answer was lost though the server applied it (runs 20261101T111242Z-...-b4a4 and
# 20261101T111411Z-...-77a7: 3 ReadTimeouts whose transitions are in `actions`; measured). Slowness stays measured
# by the budgets below; a server 500 still fails the stock no-5xx check.
CALL_TIMEOUT_S = 120.0
SETTLE_S = 5.0        # guess; without it run 20261101T111822Z-...-b3a7's first ~3 s after the burst had all 8 pool
                      # connections out at 4-12 requests/s and CPU 14-17% (measured; cause unknown)
CALM_SPREAD_S = 10.0  # guess: --users owners open Requests within 10 s of each other (200 -> 40 reads/s)
THINK_S = (1.0, 3.0)  # guess: a human owner's think time between page visits, seconds
P95_MS = 400
LOAD_CEILING_MS = 30_000  # the service's busy_timeout: past it a write answers 500 'database is locked'
# Wide: the load stage's GET /requests p95 moved 1078-17833 ms with the host's load over 15 medium/200 runs
# (measured), so only order-of-magnitude regressions are caught; the idle key also has P95_IDLE's absolute 400 ms.
P95_VS_LAST = (5.0, 3000)
P95_VS_LAST_MIN_N = 30
REQUESTS = "GET /admin/s4s/requests"
VS_LAST_LOAD = (REQUESTS, "POST /admin/s4s/requests", "POST /admin/s4s/requests/:id/accept",
                "POST /admin/s4s/slots/:id/cancel")
NOTE_ROUTES = (REQUESTS, "GET /admin/s4s/requests/proposal", "GET /admin/s4s/schedule", "GET /admin/s4s/discover",
               "GET /admin/s4s/blocks", *VS_LAST_LOAD[1:])
P95_LOAD = f"p95 {REQUESTS} <= {P95_MS}ms under load (--users owners reading while the racing writes run)"
P95_IDLE = (f"p95 {REQUESTS} <= {P95_MS}ms on an idle relay ({REQUESTS} only: --users owners open Requests "
            f"{SETTLE_S:g} s after the last write, over {CALM_SPREAD_S:g} s)")
LOAD_CEIL = f"load-stage p95 of {', '.join(VS_LAST_LOAD)} <= {LOAD_CEILING_MS} ms"
# check name -> "open finding: ..." (SKIPped while it measures red; FAILs once it measures green).
KNOWN_RED: dict[str, str] = {
    P95_LOAD: ("open finding: at medium/200 the load stage's GET /admin/s4s/requests p95 was 1078-17833 ms over 15 "
               "runs (20261101T113142Z-...-ce12 1078 ms; 20261101T110617Z-...-78c4 17833 ms at host load 76, with 17 "
               "'database is locked' tracebacks). Reads alone also missed it: run 20261101T110426Z-...-a093's "
               "write-free stage (Requests, proposal, Schedule, Blocks) 1268 ms; GET /requests alone 5 s after the "
               "last write 24-59 ms over 5 runs. Cause unproven; suspects: GET /discover runs s4s_api._fill_primary's UPDATE "
               "(78c4 write telemetry: discover held SQLite's write lock 20.1 s of 60 s), the proposal's up to "
               "2 x 60 _booked reads a call, the relay's 8-connection pool"),
    CAP_RACE: (f"open finding: concurrent sends from one Creator pass the {CAP}/day cap: S2's burst stored 51-55 "
               "requests in each of 31 runs, never 50 (20261101T113142Z-...-ce12: 12 sends from 44 -> 9 x 201 + "
               "3 x 409, 53 stored; 20261101T104822Z-...-0c29: 8 from 46 -> 8 x 201, 54 stored). "
               "service/s4s_requests_api.py send_request counts _sent_today before the INSERT's write transaction"),
}
# A KNOWN_RED entry measured red only at these scales: P95_LOAD passes at small (20 users, load p95 78-147 ms).
KNOWN_RED_SCALES = {P95_LOAD: ("medium", "huge")}
NEW = {"accept": "accepted", "decline": "declined", "skip": "skipped", "cancel": "cancelled"}


def _size(ctx, key: str) -> int:
    return ctx.param(key, ctx.world.size[f"s4s_requests_{key}"])


def _wire(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _call(http, method: str, path: str, **kw) -> tuple[int, object]:
    kw.setdefault("timeout", CALL_TIMEOUT_S)
    try:
        r = await http.request(method, path, **kw)
    except httpx.HTTPError:
        return 599, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


async def _open_requests(h) -> list:
    """The Requests page's reads: both boxes, together (as the browser does)."""
    return await asyncio.gather(*(_call(h, "GET", "/admin/s4s/requests", params={"box": box})
                                  for box in ("received", "sent")))


async def _propose(h, frm: str, to_pid: int) -> tuple[int, object]:
    return await _call(h, "GET", "/admin/s4s/requests/proposal",
                       params={"from_account_id": frm, "to_profile_id": to_pid})


class _Plan:
    """Who sends to whom on which day, drawn only from the seed (w.rng("s4s_race_plan")); read-only once built."""

    def __init__(self, ctx, w):
        rng = w.rng("s4s_race_plan")
        d = w.data["s4s_profiles"]
        self.profs, self.blocks = d["profiles"], d["blocks"]
        self.owner_of = {aid: p["owner"] for aid, p in self.profs.items()}
        self.ags = [a["user_id"] for a in w.data["agencies"]]
        self.listed = sorted(aid for aid, p in self.profs.items() if p["opted_in"])
        self.blocked_by: dict[str, set] = defaultdict(set)  # Agency -> account ids it blocked
        for b in self.blocks:
            self.blocked_by[b["agency_user_id"]].add(b["account_id"])
        self.by_ag: dict[str, list] = defaultdict(list)
        for aid in self.listed:
            self.by_ag[self.owner_of[aid]].append(aid)
        # U: the UI's receiver (agency 0's); X: its sender. S1 / S2: the cap senders.
        self.u = self.by_ag[self.ags[0]][0]
        self.x = self.partners(self.u)[0]
        others = [a for a in self.listed if a not in (self.u, self.x) and self.owner_of[a] != self.ags[0]]
        self.s1, self.s2 = others[0], others[-1]
        self.cap_partners = {s: [b for b in self.partners(s) if b != self.u] for s in (self.s1, self.s2)}
        self.sent: Counter = Counter()  # planned sends per Creator
        self._pool = [(a, b) for a in self.listed if a not in (self.u, self.s1, self.s2)
                      for b in self.partners(a) if b != self.u]
        rng.shuffle(self._pool)
        self._day = UI_DAY
        self.racers = _size(ctx, "racers")
        self.groups = self._race_groups(rng, _size(ctx, "race_groups"))
        self.limits = self._limit_groups(rng, _size(ctx, "limit_targets"))
        self.bookings = []
        for _ in range(_size(ctx, "bookings")):
            pair = self._take()
            if pair is None:
                break
            self.bookings.append({"from": pair[0], "to": pair[1], "day": self._next_day(),
                                  "hour": rng.randint(*HOURS)})
        self.probes = []  # (a Creator of the blocking Agency, the blocked Creator)
        for b in self.blocks:
            mine = [a for a in self.by_ag[b["agency_user_id"]] if a != self.u] or self.by_ag[b["agency_user_id"]]
            if mine:
                self.probes.append((mine[0], b["account_id"]))
        # Proposals to the FULL_DAY target, one per other Agency: tomorrow is full for it, so the answer is later.
        full = self.limits[0]["to"] if self.limits else None
        self.proposals = []
        for ag in self.ags:
            frm = next((a for a in self.by_ag[ag] if full in self.partners(a)), None) if full else None
            if frm:
                self.proposals.append((frm, full))
        self.burst = min(_size(ctx, "burst"), len(self.cap_partners[self.s2]))
        self.far = self._next_day() + 100

    def partners(self, a: str) -> list[str]:
        """Listed Creators of other Agencies `a` may send to: neither Agency blocked the other's Creator."""
        ag = self.owner_of[a]
        return [b for b in self.listed if self.owner_of[b] != ag
                and b not in self.blocked_by[ag] and a not in self.blocked_by[self.owner_of[b]]]

    def _next_day(self) -> int:
        self._day += 1
        return self._day

    def _take(self, pred=lambda a, b: True) -> tuple[str, str] | None:
        for i, (a, b) in enumerate(self._pool):
            if self.sent[a] < CAP - PLAN_HEADROOM and pred(a, b):
                del self._pool[i]
                self.sent[a] += 1
                return a, b
        return None

    def _race_groups(self, rng, n: int) -> list[dict]:
        groups = []
        for _ in range(n):
            pair = self._take()
            if pair is None:
                break
            kind = rng.choice(("answer", "vs_cancel"))
            if kind == "answer":
                verbs = ["accept"] + [rng.choice(("accept", "decline", "skip")) for _ in range(self.racers - 1)]
                if set(verbs) == {"accept"}:
                    verbs[-1] = rng.choice(("decline", "skip"))
            else:
                verbs = ["accept", "cancel"] + [rng.choice(("accept", "decline", "cancel"))
                                                for _ in range(self.racers - 2)]
            rng.shuffle(verbs)
            groups.append({"kind": kind, "from": pair[0], "to": pair[1], "day": self._next_day(),
                           "hour": rng.randint(*HOURS), "verbs": verbs})
        return groups

    def _limit_groups(self, rng, n: int) -> list[dict]:
        limits = []
        targets = [a for a in self.listed if a != self.u]
        rng.shuffle(targets)
        for t in targets[:n]:
            senders: list[str] = []
            for _ in range(self.profs[t]["daily_limit"] + 2):
                pair = self._take(lambda a, b: b == t and a not in senders)  # noqa: B023 — called right here
                if pair is None:
                    break
                senders.append(pair[0])
            if len(senders) > self.profs[t]["daily_limit"]:
                limits.append({"to": t, "senders": senders, "day": self._next_day() if limits else FULL_DAY,
                               "hours": [rng.randint(*HOURS) for _ in senders]})
        return limits


class _Run:
    """Drives the load through the real routes; every answer lands in a field initialised here."""

    def __init__(self, ctx, w, plan: _Plan):
        self.ctx, self.w, self.p = ctx, w, plan
        n = max(100, ctx.users)
        self.writer = {a["user_id"]: a["http"].share(limits=n) for a in w.data["agencies"]}
        self.reader = {a["user_id"]: a["http"].share(limits=n) for a in w.data["agencies"]}
        self.sem = asyncio.Semaphore(max(1, ctx.users))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.day0 = datetime(now.year, now.month, now.day)
        self.window = (self.day0, self.day0 + timedelta(days=WINDOW_DAYS))
        self.ids: dict[tuple, int] = {}  # ("race", i) / ("limit", i, sender) / ("booking", i) / ("ui",) -> request id
        self.send_fail: list[dict] = []
        self.race_statuses: dict[int, list[int]] = {}          # race group -> statuses in verb order
        self.limit_statuses: dict[int, dict[int, int]] = {}    # limit group -> request id -> accept status
        self.booking_accept: dict[int, int] = {}
        self.booking_slots: dict[int, dict[str, int]] = {}     # booking -> poster -> slot id
        self.booking_cancel: dict[int, dict] = {}              # booking -> {"own": [st, st], "partner": st}
        self.probe_statuses: dict[int, list[int]] = {}         # probe -> [send c->y, send y->c, prop c->y, prop y->c]
        self.cap_s1: dict = {"fail": [], "extra": []}
        self.cap_s2: dict = {"fail": [], "burst": Counter()}
        self.seen: dict[int, Counter] = defaultdict(Counter)    # request id -> action names of the 2xx seen
        self.slot_cancels: Counter = Counter()                  # slot id -> 200 cancels seen

    def at(self, day: int, hour: int, minute: int = 0) -> datetime:
        return self.day0 + timedelta(days=day, hours=hour, minutes=minute)

    def schedule_params(self) -> dict:
        return {"from": _wire(self.window[0]), "to": _wire(self.window[1])}

    def w_of(self, aid: str):
        return self.writer[self.p.owner_of[aid]]

    async def send(self, frm: str, to: str, when: datetime) -> tuple[int, object]:
        body = {"from_account_id": frm, "to_profile_id": self.p.profs[to]["profile_id"], "slot_at": _wire(when)}
        st, out = await _call(self.w_of(frm), "POST", "/admin/s4s/requests", json=body)
        if st == 201:
            self.seen[out["id"]]["s4s.request_send"] += 1
        return st, out

    async def act(self, rid: int, verb: str, who: str) -> int:
        st, _ = await _call(self.w_of(who), "POST", f"/admin/s4s/requests/{rid}/{verb}")
        if 200 <= st < 300:
            self.seen[rid][f"s4s.request_{verb}"] += 1
        return st

    async def sends(self) -> None:
        p = self.p

        async def one(key: tuple, frm: str, to: str, when: datetime) -> None:
            async with self.sem:
                st, out = await self.send(frm, to, when)
            if st == 201:
                self.ids[key] = out["id"]
            else:
                self.send_fail.append({"key": list(key), "from": frm, "to": to, "status": st, "body": out})
        jobs = [one(("race", i), g["from"], g["to"], self.at(g["day"], g["hour"])) for i, g in enumerate(p.groups)]
        jobs += [one(("limit", i, s), s, g["to"], self.at(g["day"], g["hours"][k], k))
                 for i, g in enumerate(p.limits) for k, s in enumerate(g["senders"])]
        jobs += [one(("booking", i), b["from"], b["to"], self.at(b["day"], b["hour"])) for i, b in enumerate(p.bookings)]
        jobs.append(one(("ui",), p.x, p.u, self.at(UI_DAY, UI_HOUR)))
        await asyncio.gather(*jobs)

    async def race(self) -> None:
        gsem = asyncio.Semaphore(max(1, self.ctx.users // self.p.racers))

        async def group(i: int, g: dict) -> None:
            rid = self.ids.get(("race", i))
            if rid is None:
                return  # SENDS reports it
            who = {"cancel": g["from"]}
            async with gsem:
                self.race_statuses[i] = list(await asyncio.gather(
                    *(self.act(rid, v, who.get(v, g["to"])) for v in g["verbs"])))
        await asyncio.gather(*(group(i, g) for i, g in enumerate(self.p.groups)))

    async def limit(self) -> None:
        async def group(i: int, g: dict) -> None:
            ids = [self.ids[k] for k in (("limit", i, s) for s in g["senders"]) if k in self.ids]
            self.limit_statuses[i] = dict(zip(ids, await asyncio.gather(*(self.act(r, "accept", g["to"])
                                                                           for r in ids))))
        await asyncio.gather(*(group(i, g) for i, g in enumerate(self.p.limits)))

    async def booking(self) -> None:
        bs = {i: self.ids[("booking", i)] for i in range(len(self.p.bookings)) if ("booking", i) in self.ids}

        async def accept(i: int, rid: int) -> None:
            async with self.sem:
                self.booking_accept[i] = await self.act(rid, "accept", self.p.bookings[i]["to"])
        await asyncio.gather(*(accept(i, rid) for i, rid in bs.items()))
        con = self.w.sql()
        try:
            for i, rid in bs.items():
                self.booking_slots[i] = {poster: sid for sid, poster in con.execute(
                    "SELECT id, poster_account_id FROM s4s_schedule WHERE request_id=?", (rid,))}
        finally:
            con.close()

        async def cancel(sid: int, who: str) -> int:
            st, _ = await _call(self.w_of(who), "POST", f"/admin/s4s/slots/{sid}/cancel")
            if st == 200:
                self.slot_cancels[sid] += 1
            return st

        async def race(i: int) -> None:
            b = self.p.bookings[i]
            sid = self.booking_slots[i].get(b["from"])
            if sid is None:
                return  # SLOT_CANCEL reports it
            async with self.sem:
                own1, own2, other = await asyncio.gather(cancel(sid, b["from"]), cancel(sid, b["from"]),
                                                         cancel(sid, b["to"]))
            self.booking_cancel[i] = {"own": sorted([own1, own2]), "partner": other}
        await asyncio.gather(*(race(i) for i in bs))

    async def probes(self) -> None:
        pf, far = self.p.profs, self.p.far

        async def probe(i: int, c: str, y: str) -> None:
            async with self.sem:
                self.probe_statuses[i] = [
                    (await self.send(c, y, self.at(far, 8)))[0], (await self.send(y, c, self.at(far, 9)))[0],
                    (await _propose(self.w_of(c), c, pf[y]["profile_id"]))[0],
                    (await _propose(self.w_of(y), y, pf[c]["profile_id"]))[0]]
        await asyncio.gather(*(probe(i, c, y) for i, (c, y) in enumerate(self.p.probes)))

    async def cap(self) -> None:
        p = self.p

        async def cycle(s: str, n: int, rec: dict, day: int) -> None:
            partners = p.cap_partners[s]
            for i in range(n):
                st, body = await self.send(s, partners[i % len(partners)], self.at(day, 6, i))
                if st != 201:
                    rec["fail"].append({"i": i, "status": st, "body": body})
                    continue
                cst = await self.act(body["id"], "cancel", s)
                if cst != 200:
                    rec["fail"].append({"i": i, "cancel": cst})

        async def s1() -> None:
            await cycle(p.s1, CAP - p.sent[p.s1], self.cap_s1, p.far + 1)
            for k in range(2):
                st, body = await self.send(p.s1, p.cap_partners[p.s1][k], self.at(p.far + 1, 20, k))
                self.cap_s1["extra"].append({"status": st,
                                             "detail": body.get("detail") if isinstance(body, dict) else None})

        async def s2() -> None:
            await cycle(p.s2, CAP - p.burst // 2 - p.sent[p.s2], self.cap_s2, p.far + 2)
            res = await asyncio.gather(*(self.send(p.s2, b, self.at(p.far + 2, 21, i))
                                         for i, b in enumerate(p.cap_partners[p.s2][:p.burst])))
            self.cap_s2["burst"].update(st for st, _ in res)
        await asyncio.gather(s1(), s2())

    async def readers(self) -> None:
        rounds = _size(self.ctx, "read_rounds")
        rng = self.w.rng("s4s_race_readers")
        plans = []
        for i in range(self.ctx.users):
            ag = self.p.ags[i % len(self.p.ags)]
            frm = rng.choice(self.p.by_ag.get(ag) or [None])
            to = rng.choice((self.p.partners(frm) if frm else None) or [None])
            plans.append((ag, frm, to, rng.uniform(0, THINK_S[1]),
                          [rng.uniform(*THINK_S) for _ in range(rounds * 4)]))

        async def reader(ag, frm, to, start, thinks) -> None:
            h, th = self.reader[ag], iter(thinks)
            await asyncio.sleep(start)
            for _ in range(rounds):
                await _open_requests(h)
                await asyncio.sleep(next(th))
                if to:
                    await _propose(h, frm, self.p.profs[to]["profile_id"])
                await asyncio.sleep(next(th))
                await _call(h, "GET", "/admin/s4s/schedule", params=self.schedule_params())
                await asyncio.sleep(next(th))
                await asyncio.gather(_call(h, "GET", "/admin/s4s/discover"), _call(h, "GET", "/admin/s4s/blocks"))
                await asyncio.sleep(next(th))
        await asyncio.gather(*(reader(*pl) for pl in plans))

    async def calm(self) -> None:
        """Each of the --users owners opens Requests once (both boxes), staggered over CALM_SPREAD_S."""
        rng = self.w.rng("s4s_race_calm")
        starts = [rng.uniform(0, CALM_SPREAD_S) for _ in range(self.ctx.users)]

        async def visit(i: int) -> None:
            await asyncio.sleep(starts[i])
            await _open_requests(self.reader[self.p.ags[i % len(self.p.ags)]])
        await asyncio.gather(*(visit(i) for i in range(self.ctx.users)))

    async def close(self) -> None:
        for h in (*self.writer.values(), *self.reader.values()):
            await h.aclose()


def _db(w) -> dict:
    con = w.sql()
    try:
        q = lambda sql, *a: con.execute(sql, a).fetchall()
        return {
            "requests": {r[0]: {"id": r[0], "from": r[1], "to": r[2], "slot_at": r[3], "status": r[4],
                                "created_at": r[5]}
                         for r in q("SELECT id, from_account_id, to_account_id, slot_at, status, created_at "
                                    "FROM s4s_requests")},
            "slots": [{"id": r[0], "request_id": r[1], "poster": r[2], "partner": r[3], "slot_at": r[4],
                       "status": r[5], "job_id": r[6]}
                      for r in q("SELECT id, request_id, poster_account_id, partner_account_id, slot_at, status, "
                                 "job_id FROM s4s_schedule")],
            "jobs": {r[0]: {"id": r[0], "account_id": r[1], "kind": r[2], "payload": json.loads(r[3] or "{}"),
                            "run_at": r[4], "status": r[5]}
                     for r in q("SELECT id, account_id, kind, payload_json, run_at, status FROM scheduled_jobs "
                                "WHERE kind='s4s_post'")},
            "actions": q("SELECT target_type, target_id, action FROM actions WHERE action LIKE 's4s.%'"),
        }
    finally:
        con.close()


def _booked(db: dict) -> Counter:
    """(poster, UTC day) -> slots not canceled: the product's Daily-limit count (s4s_requests_api._booked)."""
    return Counter((s["poster"], s["slot_at"][:10]) for s in db["slots"] if s["status"] != "canceled")


def _first_room_day(booked: Counter, profs: dict, a: str, b: str, day0: datetime) -> str | None:
    for n in range(1, PROPOSAL_DAYS + 1):
        at = day0 + timedelta(days=n, hours=PROPOSAL_HOUR)
        d = at.strftime("%Y-%m-%d")
        if booked[(a, d)] < profs[a]["daily_limit"] and booked[(b, d)] < profs[b]["daily_limit"]:
            return _wire(at)
    return None


async def _final_reads(run: _Run) -> dict:
    """Each Agency's boxes, schedule, Discovery and blocks, and every planned proposal, at rest."""
    p, out = run.p, {"agencies": {}, "proposals": []}
    for ag in p.ags:
        h = run.writer[ag]
        received, sent = await _open_requests(h)
        out["agencies"][ag] = {"received": received, "sent": sent,
                               "schedule": await _call(h, "GET", "/admin/s4s/schedule", params=run.schedule_params()),
                               "discover": await _call(h, "GET", "/admin/s4s/discover"),
                               "blocks": await _call(h, "GET", "/admin/s4s/blocks")}
    for frm, to in p.proposals:
        out["proposals"].append(await _propose(run.w_of(frm), frm, p.profs[to]["profile_id"]))
    return out


def _owned(p: _Plan) -> dict[str, set]:
    return {ag: {a for a, o in p.owner_of.items() if o == ag} for ag in p.ags}


def _check_boxes(run: _Run, reads: dict, db: dict, chk) -> None:
    own = _owned(run.p)
    reqs = sorted(db["requests"].values(), key=lambda r: (r["created_at"], r["id"]), reverse=True)
    bad = []
    for ag in run.p.ags:
        for box, side in (("received", "to"), ("sent", "from")):
            st, got = reads["agencies"][ag][box]
            want = [(r["id"], "pending" if box == "sent" and r["status"] == "skipped" else r["status"])
                    for r in reqs if r[side] in own[ag] and not (box == "received" and r["status"] == "skipped")]
            have = [(x["id"], x["status"]) for x in got] if st == 200 and isinstance(got, list) else None
            if have != want:
                bad.append({"agency": ag, "box": box, "status": st, "n_want": len(want),
                            "n_have": None if have is None else len(have),
                            "first_diff": next(([w_, h_] for w_, h_ in zip(want, have or []) if w_ != h_), None)})
    chk(BOXES, not bad, bad=bad[:6], requests=len(reqs))


def _check_schedule(run: _Run, reads: dict, db: dict, chk) -> None:
    own, (lo, hi) = _owned(run.p), run.window
    bad = []
    for ag in run.p.ags:
        st, got = reads["agencies"][ag]["schedule"]
        want = [s["id"] for s in sorted(db["slots"], key=lambda s: (s["slot_at"], s["id"]))
                if s["poster"] in own[ag] and lo <= datetime.fromisoformat(s["slot_at"]) < hi]
        have = [x["id"] for x in got] if st == 200 and isinstance(got, list) else None
        if have != want:
            bad.append({"agency": ag, "status": st, "want": want[:10], "have": (have or [])[:10]})
    chk(SCHEDULE, not bad, bad=bad[:6], slots=len(db["slots"]))


def _check_discover(run: _Run, reads: dict, chk) -> None:
    p = run.p
    listed = {p.profs[a]["profile_id"] for a in p.listed}
    bad = []
    for ag in p.ags:
        st, got = reads["agencies"][ag]["discover"]
        want = {p.profs[a]["profile_id"] for a in p.listed if a not in p.blocked_by[ag]}
        have = {x["profile_id"] for x in got} if st == 200 and isinstance(got, list) else set()
        if st != 200 or want - have or have - listed:
            bad.append({"agency": ag, "status": st, "missing": sorted(want - have)[:10],
                        "not_listed": sorted(have - listed)[:10]})
    chk(DISCOVER, not bad, bad=bad[:6])


def _check_proposal(run: _Run, reads: dict, db: dict, chk) -> None:
    booked, tomorrow = _booked(db), _wire(run.at(1, PROPOSAL_HOUR))
    rows = []
    for (frm, to), (st, ans) in zip(run.p.proposals, reads["proposals"]):
        got = ans.get("slot_at") if st == 200 and isinstance(ans, dict) else None
        rows.append({"from": frm, "to": to, "status": st, "got": got,
                     "want": _first_room_day(booked, run.p.profs, frm, to, run.day0)})
    bad = [r for r in rows if r["status"] != 200 or r["got"] != r["want"]]
    later = sum(1 for r in rows if r["want"] != tomorrow)
    chk(PROPOSAL, bool(rows) and later > 0 and not bad, probes=len(rows), want_later_than_tomorrow=later,
        bad=bad[:6])


def _check_blocked(run: _Run, reads: dict, chk) -> None:
    p = run.p
    bad_probes = [{"c": c, "y": y, "statuses": run.probe_statuses.get(i)} for i, (c, y) in enumerate(p.probes)
                  if run.probe_statuses.get(i) != [404] * 4]
    bad_lists = []
    for ag in p.ags:
        blocked = {p.profs[a]["profile_id"] for a in p.blocked_by[ag]}
        dst, disc = reads["agencies"][ag]["discover"]
        bst, blk = reads["agencies"][ag]["blocks"]
        shown = {x["profile_id"] for x in disc} & blocked if dst == 200 and isinstance(disc, list) else None
        lists = {x["profile_id"] for x in blk} if bst == 200 and isinstance(blk, list) else None
        if shown != set() or lists != blocked:
            bad_lists.append({"agency": ag, "discover_status": dst, "blocked_shown": sorted(shown or []),
                              "blocks_status": bst, "blocks_want": sorted(blocked), "blocks_have": sorted(lists or [])})
    chk(BLOCKED, bool(p.probes) and not bad_probes and not bad_lists, probes=len(p.probes), bad=bad_probes[:6],
        lists_bad=bad_lists[:6])


def _check_sends(run: _Run, chk) -> None:
    p = run.p
    chk(SENDS, not run.send_fail, failed=run.send_fail[:10],
        planned=len(p.groups) + sum(len(g["senders"]) for g in p.limits) + len(p.bookings) + 1)


def _check_races(run: _Run, db: dict, chk) -> None:
    status = {rid: r["status"] for rid, r in db["requests"].items()}
    bad = []
    for i, sts in run.race_statuses.items():
        g, rid = run.p.groups[i], run.ids[("race", i)]
        wins = [v for v, st in zip(g["verbs"], sts) if 200 <= st < 300]
        if (len(wins) != 1 or any(st != 409 for st in sts if not 200 <= st < 300)
                or status.get(rid) != NEW[wins[0]]):
            bad.append({"id": rid, "kind": g["kind"], "verbs": g["verbs"], "statuses": sts, "final": status.get(rid)})
    chk(ONE_WINNER, bool(run.race_statuses) and not bad, groups=len(run.race_statuses), bad=len(bad), first=bad[:6],
        winners=dict(Counter(status.get(run.ids[("race", i)]) for i in run.race_statuses)))


def _check_slots_jobs(db: dict, chk) -> int:
    by_req = defaultdict(list)
    for s in db["slots"]:
        by_req[s["request_id"]].append(s)
    bad, accepted = [], 0
    for r in db["requests"].values():
        ss = by_req[r["id"]]
        if r["status"] == "accepted":
            accepted += 1
            jobs = [db["jobs"].get(s["job_id"]) for s in ss]
            ok = (len(ss) == 2 and {s["poster"] for s in ss} == {r["from"], r["to"]}
                  and all(s["partner"] == (r["to"] if s["poster"] == r["from"] else r["from"]) for s in ss)
                  and all(s["slot_at"] == r["slot_at"] for s in ss)
                  and all(j is not None and j["status"] == "pending" and j["payload"].get("slot_id") == s["id"]
                          and j["account_id"] == s["poster"] and j["run_at"] == s["slot_at"]
                          for s, j in zip(ss, jobs)))
        else:
            ok = not ss
        if not ok:
            bad.append({"id": r["id"], "status": r["status"], "slots": len(ss)})
    chk(SLOTS_JOBS, not bad and len(db["jobs"]) == 2 * accepted
        and all(j["status"] == "pending" for j in db["jobs"].values()),
        accepted=accepted, slots=len(db["slots"]), s4s_post_jobs=len(db["jobs"]),
        job_status=dict(Counter(j["status"] for j in db["jobs"].values())), bad=len(bad), first=bad[:6])
    return accepted


def _check_daily_limit(run: _Run, db: dict, chk) -> None:
    profs, booked = run.p.profs, _booked(db)
    over = [{"creator": a, "day": d, "booked": n, "limit": profs[a]["daily_limit"]}
            for (a, d), n in booked.items() if n > profs[a]["daily_limit"]]
    grp = []
    for i, g in enumerate(run.p.limits):
        sts = list(run.limit_statuses[i].values())
        lim = profs[g["to"]]["daily_limit"]
        if sts.count(200) != min(len(sts), lim) or any(st not in (200, 409) for st in sts):
            grp.append({"to": g["to"], "limit": lim, "senders": len(sts), "accepted": sts.count(200),
                        "statuses": sorted(sts)})
    chk(DAILY_LIMIT, bool(run.p.limits) and not over and not grp, groups=len(run.p.limits), over=over[:8],
        bad_groups=grp[:8], max_booked=max(booked.values(), default=0))


def _check_cap(run: _Run, db: dict, chk) -> dict:
    p, today = run.p, run.day0.strftime("%Y-%m-%d")
    sent_today = Counter(r["from"] for r in db["requests"].values() if r["created_at"][:10] == today)
    s1, s2 = run.cap_s1, run.cap_s2
    chk(CAP_SEQ, not s1["fail"] and [e["status"] for e in s1["extra"]] == [409, 409]
        and all(str(CAP) in (e["detail"] or "") for e in s1["extra"]) and sent_today[p.s1] == CAP,
        stored=sent_today[p.s1], extra=s1["extra"], fail=s1["fail"][:5])
    chk(CAP_RACE, not s2["fail"] and sent_today[p.s2] == CAP, stored=sent_today[p.s2], burst=p.burst,
        burst_statuses=dict(s2["burst"]), fail=s2["fail"][:5])
    return {"s1": sent_today[p.s1], "s2": sent_today[p.s2]}


def _check_slot_cancel(run: _Run, db: dict, chk) -> None:
    slots = {s["id"]: s for s in db["slots"]}
    bad = []
    for i, b in enumerate(run.p.bookings):
        mine = run.booking_slots.get(i, {})
        c = run.booking_cancel.get(i)
        if (run.booking_accept.get(i) != 200 or c is None or c["own"] != [200, 409] or c["partner"] != 404
                or slots.get(mine.get(b["from"]), {}).get("status") != "canceled"
                or slots.get(mine.get(b["to"]), {}).get("status") != "scheduled"):
            bad.append({"id": run.ids.get(("booking", i)), "accept": run.booking_accept.get(i), "cancel": c})
    chk(SLOT_CANCEL, bool(run.p.bookings) and not bad, bookings=len(run.p.bookings), bad=bad[:6])


def _check_audit(run: _Run, db: dict, ui_seen: Counter, chk) -> None:
    rows_req, rows_slot, other_rows = defaultdict(Counter), Counter(), Counter()
    for tt, tid, action in db["actions"]:
        if tt == "s4s_request":
            rows_req[int(tid)][action] += 1
        elif tt == "s4s_slot" and action == "s4s.slot_cancel":
            rows_slot[int(tid)] += 1
        else:
            other_rows[f"{tt}:{action}"] += 1
    seen = defaultdict(Counter, {k: Counter(v) for k, v in run.seen.items()})
    for rid, n in ui_seen.items():
        seen[rid]["s4s.request_accept"] += n
    ids = set(seen) | set(rows_req)
    bad = [{"id": i, "seen": dict(seen[i]), "rows": dict(rows_req[i])} for i in sorted(ids) if seen[i] != rows_req[i]]
    bad_slot = [{"slot": s, "seen": run.slot_cancels[s], "rows": rows_slot[s]}
                for s in sorted(set(rows_slot) | set(run.slot_cancels)) if run.slot_cancels[s] != rows_slot[s]]
    chk(AUDIT, not bad and not bad_slot and not other_rows, requests=len(ids), bad=bad[:6], bad_slots=bad_slot[:6],
        other_rows=dict(other_rows), rows=sum(sum(c.values()) for c in rows_req.values()) + sum(rows_slot.values()))


async def _visible(loc, timeout_ms: int = WAIT_MS) -> bool:
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    try:
        await loc.wait_for(timeout=timeout_ms)
        return True
    except PlaywrightTimeout:
        return False


async def _ui(ctx, run: _Run, chk) -> Counter:
    """Agency 0's owner accepts U's one pending request in the browser, then opens the other sections."""
    from slop.actors import ui

    p, rid = run.p, run.ids.get(("ui",))
    seen: Counter = Counter()
    if rid is None:
        chk(UI_ACCEPT, False, reason="the UI request was never sent")
        ctx.skip(UI_PAGES, "the UI request was never sent")
        return seen
    x_name = p.profs[p.x]["display_name"]
    shown = {}
    async with ui.owner_browser(ctx, viewport=(1440, 900)) as page:
        answers: list = []
        page.on("response", lambda r: answers.append((r.request.method, urlsplit(r.url).path, r.status)))
        await page.goto(f"{ctx.app}/share-for-share/requests?creator={p.u}", wait_until="domcontentloaded")
        card = page.locator(f'article[aria-label="Request from {x_name}"]')
        await card.wait_for(timeout=WAIT_MS)
        await ui.shot(ctx, page, "requests-trigger")
        await card.get_by_role("button", name="Accept", exact=True).click()
        shown["modal"] = (await _visible(page.get_by_text("Share for Share Scheduled!").first, MODAL_MS)
                          and await _visible(page.get_by_role("button", name="Got It"), MODAL_MS))
        if shown["modal"]:
            await page.wait_for_timeout(FADE_MS)  # the modal's fade-in, so the shot is the settled state
        await ui.shot(ctx, page, "requests-settled")
        acc = [st for m, path, st in answers if m == "POST" and path.endswith(f"/admin/s4s/requests/{rid}/accept")]
        seen[rid] += sum(1 for st in acc if 200 <= st < 300)
        await page.goto(f"{ctx.app}/share-for-share/schedule?creator={p.u}", wait_until="domcontentloaded")
        day = run.at(UI_DAY, 0)
        if day.month != run.day0.month:
            await page.get_by_role("button", name="Next month").click(timeout=WAIT_MS)
        # The list shows the picked calendar day (today by default): pick the slot's day.
        await page.get_by_role("button", name=f"{day:%B %d, %Y}", exact=True).click(timeout=WAIT_MS)
        shown["schedule"] = await _visible(page.locator(f'article[aria-label="S4S slot with {x_name}"]').first)
        await ui.shot(ctx, page, "schedule")
        await page.goto(f"{ctx.app}/share-for-share/discover-creators?creator={p.u}", wait_until="domcontentloaded")
        card_of = lambda a: page.locator(f'article[aria-label="{p.profs[a]["display_name"]}"]')
        shown["discover"] = await _visible(card_of(p.x).first)
        shown["discover_blocked_shown"] = [p.profs[a]["display_name"] for a in sorted(p.blocked_by[p.ags[0]])
                                           if await card_of(a).count()]
        await ui.shot(ctx, page, "discover-creators")
        await page.goto(f"{ctx.app}/share-for-share/settings?creator={p.u}", wait_until="domcontentloaded")
        shown["settings"] = await _visible(page.locator('section[aria-label^="S4S settings for"]').first)
        await ui.shot(ctx, page, "settings")
    db = _db(run.w)
    r = db["requests"].get(rid, {})
    ss = [s for s in db["slots"] if s["request_id"] == rid]
    jobs = [db["jobs"].get(s["job_id"]) for s in ss]
    st, box = await _call(run.writer[p.ags[0]], "GET", "/admin/s4s/requests", params={"box": "received"})
    api = next((x["status"] for x in box if x["id"] == rid), None) if st == 200 and isinstance(box, list) else None
    side = {"request": rid, "db_status": r.get("status"), "slots": len(ss),
            "jobs": [j and j["status"] for j in jobs], "api_status": api, "accept_answers": acc}
    (ctx.out / "ui-side-effect.json").write_text(json.dumps(side, indent=2))
    chk(UI_ACCEPT, shown["modal"] and acc and all(200 <= s < 300 for s in acc) and r.get("status") == "accepted"
        and len(ss) == 2 and jobs and all(j and j["status"] == "pending" for j in jobs) and api == "accepted", **side)
    chk(UI_PAGES, shown["schedule"] and shown["discover"] and not shown["discover_blocked_shown"]
        and shown["settings"], **shown)
    return seen


def _checker(ctx):
    """ctx.check, except a KNOWN_RED check (at its scales): SKIP with its finding while it measures red, FAIL as
    'finding closed' once it measures green, so a stale entry cannot hide a fixed or regressed check."""
    known = {k: v for k, v in KNOWN_RED.items() if ctx.scale in KNOWN_RED_SCALES.get(k, (ctx.scale,))}

    def chk(name: str, ok, **detail) -> None:
        if name not in known:
            ctx.check(name, bool(ok), **detail)
        elif ok:
            ctx.check(name, False, finding_closed=f"measured green: remove its KNOWN_RED entry ({known[name]})",
                      **detail)
        else:
            ctx.skip(name, known[name], measured_ok=False, **detail)
    return chk


def _budgets(ctx, chk) -> None:
    load, calm = ctx.rec.summary("load"), ctx.rec.summary("calm")
    for name, got in ((P95_LOAD, load.get(REQUESTS)), (P95_IDLE, calm.get(REQUESTS))):
        if got:
            chk(name, got["p95_ms"] <= P95_MS, budget=True, p95=got["p95_ms"], n=got["n"])
        else:
            ctx.skip(name, "no samples")
    ceil = {k: load[k]["p95_ms"] for k in VS_LAST_LOAD if k in load}
    chk(LOAD_CEIL, bool(ceil) and max(ceil.values()) <= LOAD_CEILING_MS, budget=True, p95=ceil)
    # Load-stage keys keep the plain route names (the runs before the idle stage measured their whole run, which
    # was the load); the idle stage's key is prefixed.
    vs = {k: load[k] for k in VS_LAST_LOAD if k in load} | ({f"calm {REQUESTS}": calm[REQUESTS]}
                                                              if REQUESTS in calm else {})
    ctx.metric("p95_vs_last_green", {k: v["p95_ms"] for k, v in vs.items()})
    ctx.metric("p95_vs_last_green_n", {k: v["n"] for k, v in vs.items()})
    for st, sm in (("load", load), ("calm", calm)):
        ctx.note("", f"S4S routes, stage {st} (measured): " + ", ".join(
            f"{k} p95 {sm[k]['p95_ms']}ms p50 {sm[k]['p50_ms']}ms n={sm[k]['n']}" for k in NOTE_ROUTES if k in sm))


async def run(ctx) -> None:
    w = ctx.world
    t0 = asyncio.get_running_loop().time()
    n_ag, per = _size(ctx, "agencies"), _size(ctx, "creators_per_agency")
    await agency_seed.seed(w, n=n_ag)
    ags = [a["user_id"] for a in w.data["agencies"]]
    cs = creators_seed.seed(w, n_ag * per, owners=[ags[i % n_ag] for i in range(n_ag * per)])
    s4s_profiles.seed(w, cs, opted_out_frac=0.1, blocks=_size(ctx, "blocks"))
    ctx.metric("seed", {"profile": WORLD, "seconds": round(asyncio.get_running_loop().time() - t0, 2),
                        "agencies": n_ag, "creators": len(cs),
                        "opted_in": sum(1 for p in w.data["s4s_profiles"]["profiles"].values() if p["opted_in"]),
                        "blocks": len(w.data["s4s_profiles"]["blocks"])})
    chk = _checker(ctx)
    plan = _Plan(ctx, w)
    r = _Run(ctx, w, plan)
    ctx.metric("plan", {"race_groups": len(plan.groups), "racers": plan.racers, "limit_groups": len(plan.limits),
                        "bookings": len(plan.bookings), "block_probes": len(plan.probes),
                        "proposals": len(plan.proposals), "burst": plan.burst,
                        "max_planned_sends_per_creator": max(plan.sent.values(), default=0)})
    try:
        t_load = asyncio.get_running_loop().time()

        async def writers() -> None:
            await r.sends()
            await asyncio.gather(r.race(), r.limit())
            await r.booking()
            await r.probes()
            await r.cap()
        ctx.rec.stage = "load"
        await asyncio.gather(writers(), r.readers())
        ctx.metric("load_s", round(asyncio.get_running_loop().time() - t_load, 2))
        ctx.rec.stage = "settle"
        await asyncio.sleep(SETTLE_S)
        ctx.rec.stage = "calm"
        await r.calm()
        ctx.rec.stage = None
        reads = await _final_reads(r)
        db = _db(w)
        _check_boxes(r, reads, db, chk)
        _check_schedule(r, reads, db, chk)
        _check_discover(r, reads, chk)
        _check_proposal(r, reads, db, chk)
        _check_blocked(r, reads, chk)
        ui_seen: Counter = Counter()
        if ctx.app is None:
            ctx.skip(UI_ACCEPT, "--no-ui")
            ctx.skip(UI_PAGES, "--no-ui")
        else:
            ui_seen = await _ui(ctx, r, chk)
        db = _db(w)
        _check_sends(r, chk)
        _check_races(r, db, chk)
        accepted = _check_slots_jobs(db, chk)
        _check_daily_limit(r, db, chk)
        sent_today = _check_cap(r, db, chk)
        _check_slot_cancel(r, db, chk)
        _check_audit(r, db, ui_seen, chk)
        ctx.metric("s4s", {"accepted": accepted, "sent_today": sent_today, "slots": len(db["slots"]),
                           "statuses": dict(Counter(x["status"] for x in db["requests"].values())),
                           "s4s_post_jobs": len(db["jobs"])})
    finally:
        await r.close()
    _budgets(ctx, chk)
