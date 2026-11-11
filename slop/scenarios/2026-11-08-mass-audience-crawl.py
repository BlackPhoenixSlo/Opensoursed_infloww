"""A mass send records who received it (service/audience_crawl.py, docs/spec/phase-02-audience-crawl.md): after an
immediate list-audience send, from an automation or the Composer, the run answers as fast as today and the
Audience crawl reads OF's rosters in the background, through the Creator's shared background pacer, waiting out
OF's 429s on the Backoff ladder and resuming one page back; the record is complete or NULL.

World: `flat_agency` (CREATORS: small 10 / medium 20), each with a captured session: the relay's REAL OFClient
against lib/of_wire.py (`OF_WIRE`). OF's rosters are lib/audience_crawl_wire.py's: every Creator ROSTER fans and
following (FOLLOW_OVERLAP of them also fans), its Creator 0 BIG_FANS fans (past of_paging's 200-page x 50
backstop), Creator 1 a Dead session (its rosters 401 after the send), Creator 2 churning (each 429 subscribes
one fan and expires one), and a seeded 429 window (P429 per roster call outside one, RETRY_AFTER_S long, the
`Retry-After` header and the body's "Please allow N seconds") on every live Creator. OF's mass feed (the wire's
`/users/me/stats/messages/group`) counts each send its true audience at accept: the completeness gate's
denominator, one GET per crawl round. Fetch diet P2b's four (outside RECORDED_95 / EXACT_OR_NULL, two automation
sends each, SPACING_S apart, comparable to each other): Creator 3 `partial`, both rosters served short (the first
1 / PARTIAL_X, then hasMore false) while OF sends to and counts the whole roster, and an earlier comparable send's
`incomplete` verdict older than AUDIENCE_CRAWL_REPROBE_S (seed/audience_crawl_priors.py, mass_runs by SQL: its
Auto_Exclude list made on the wire up front so the seeded send excludes the same id the sends' sync finds by
name), so its first send re-probes; Creator 4 `broken`, its sends also excluding a custom list OF ignores the
offset of (of_wire `repeat_pages`); Creator 5 `twice`, its fans roster repeating its tail with hasMore true
past the end (the wire's `tail_repeat`: a page repeated twice in a row, synthetic); Creator 6 `bare`, rosters
that end normally, its sends missing from OF's feed (`unlisted`: as a send past the feed's newest page).
RELAY_ENV compresses the crawl's deadline (DEADLINE_S, prod 900) and ladder (1 s doubling to 4 s; prod 30 / 300);
lib/audience_crawl_relay.py sets of_pacing's PAGE_GAP_S / JITTER_S (prod 1.0 / 0.3).

Drive: `--users` mass sends (`user_lists ["fans", "following"]`, the Creator's GUARD_N guard ids in
`excluded_users`, which the send's Auto_Exclude sync puts on OF's list), round-robin over the Creators but the big,
dead and P2b ones (BIG_SENDS, DEAD_SENDS and P2B_SENDS of their own), every Creator's sends SPACING_S apart (past
of_write's 11 s per-Creator gap, so it never binds) from a seeded offset, but its second send CLOSE_S after its first
(close together: the other kind, so no write gap binds; it queues behind the first's crawl; not P2b's), alternately
(P2b's: the automation only) through the
real automation enqueue
(`POST /admin/automation/enqueue` send_mass_message, then `/__slop/run-automation {claim: true}`: the product's
claim, run slot and run_once) and the composer's real `POST /api/of/v2/messages/queue`. Then the crawls drain:
until every recordable send is stamped, or no roster call for QUIET_S, or DEADLINE_S past the last accept.

Checks (names in lib/audience_crawl_faults.py):
  RECORDED_95    >= 95 % of the recordable sends (OF accepted, not the Dead-session Creator's) stamped within
                 DEADLINE_S (+ the POLL_S the stamp was seen in) of OF's accept.
  EXACT_OR_NULL  every stamped send of a non-churn Creator: its recipients_json == OF's recipients at accept
                 (the wire journal); every Dead-session send NULL.
  PACED          per Creator, consecutive roster calls arrive >= PAGE_GAP_S - PACED_TOL_S apart (the pacer stamps
                 departures; loopback adds ms).
  SEND_UNSLOWED  enqueue (automation) / composer POST -> OF accept p95 <= SEND_P95_S.
  DETACHED       every automation send OF accepted: its mass run unstamped when its run returned.
  BIG_ROSTER     every recordable send of the big Creator stamped with > 10k ids.
  PAGE_BOUND     per Creator, its roster calls (the wire journal) <= the spec's per-round call bound: rounds x
                 sum over fans, following of (ceil(rows / 50) + 1), plus the resumes and failed attempts of its
                 audience_crawl_end lines, plus a round's one re-read of a repeated roster page (tail-repeat Creators) (a round's shared reads are charged to one line; a round of k sends
                 logs coalesced=k-1 on each, so rounds = sum of 1 / (coalesced + 1)); no crawl read of a verified
                 Auto_Exclude (its offset-0 list reads == its sends' syncs: one read each under broadcast_lock);
                 and the big Creator's sends queued behind its first crawl (> 30 s) served by fewer rounds than
                 sends.
  RESTART_RECOVERED  after every check above (so none of them sees it): the big Creator's two sends (auto, then the
                 composer CLOSE_S later), SIGTERM (`stack.stop_relay`: shutdown's drain cuts the crawl off past
                 audience_crawl.SHUTDOWN_DRAIN_S), start on the same temp dir; every recordable send NULL at the stop
                 whose crawl logged no end line and whose deadline is still ahead at the boot (>= 1 required) stamped
                 by the boot's re-crawl (audience_crawl.recover_at_boot) within its own deadline; both restart sends
                 (auto and composer: each audience_filter writer) among them, their rows carrying `online` and
                 `filters` false.
  INCOMPLETE_NULL  the partial Creator's first send (re-probed past the old verdict): NULL, line `incomplete`
                 with `sent_count=` its OF count and ratio < 1.0 (not complete by OF's count), crawl_outcome
                 `incomplete`.
  SKIP_NEXT      its second send: NULL, line `skipped_incomplete` pages=0, crawl_outcome stamped; its roster
                 calls (the wire journal) <= the first line's pages + failed less its feed reads (the skip read
                 nothing).
  EXCLUDE_FIRST  every broken-list send: NULL, line + crawl_outcome `truncated`, the list read, zero roster calls;
                 every repeat of the list proven short by a `GET /lists/{id}` answered 200 (its repeat line
                 `users_count=BROKEN_LIST_N -> truncated`, every such GET 200; a 404 count GET, no count, fails it).
  REPEAT_TWICE_NULL  every twice send NULL, line + crawl_outcome `truncated`, `sent_count=-` (no gate, nothing
                 recorded off a repeat); its repeat lines only `-> retry` / `-> truncated`, at least one retry per cut
                 (a 429 on the re-read resumes one page back, so a cut may log two retries), the tail repeat read
                 at least twice per cut.
  NO_COUNT_NULL  every bare send NULL, line + crawl_outcome `no_count`, `sent_count=- ratio=-` (the walk ended on
                 OF's own end with no repeat, OF's feed read, no count of the send in it).
  drift          (reported, not gated) the churn Creator's stamps vs OF at accept: extra and missing shares.
  no 5xx (stock), P95_VS_LAST over the send p95 and both routes.

Bypasses (declared): OF at its wire (lib/of_wire.py: 50 ms a call; the rosters, 429 schedule, 401 and churn
lib/audience_crawl_wire.py's guesses); the crawl Knobs and of_pacing's gap compressed (time compression, same
rules); the supervisor's cadence (a driver per Creator claims its send right after the enqueue); seeding by SQL
(flat_agency); guard ids picked from the roster (no seeded contact history: both kinds of send pass their windows
as 0 / none, so the Auto_Exclude list holds exactly the guard).
Break-it-once: audience-crawl-legacy (AUDIENCE_CRAWL_MODE=legacy: inline, unpaced, a 429 fails it, the 200-page
backstop, every exclude list read again, no shared round): RECORDED_95, PAGE_BOUND, PACED, DETACHED, BIG_ROSTER,
RESTART_RECOVERED (legacy stamps inline, so no crawl is in flight at the stop and nothing is cut off; legacy also
recovers nothing); SEND_UNSLOWED and EXACT_OR_NULL stay green (noise line clean); the five P2b checks go red too
(noise: legacy records no crawl line). no-boot-recovery (`--fault=`; recover_at_boot does nothing):
RESTART_RECOVERED only. crawl-p2b-off (`--fault=`; P2b reverted in audience_crawl_decide: no gate, no skip,
sources as first seen (rosters before lists)): INCOMPLETE_NULL, SKIP_NEXT, EXCLUDE_FIRST, NO_COUNT_NULL (no gate:
recorded) only; REPEAT_TWICE_NULL stays green (the repeat rule is #440's, not P2b's).
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import Counter
from datetime import timedelta
from urllib.parse import parse_qs

import httpx

from slop.lib.audience_crawl_faults import (BIG_ROSTER, DETACHED, EXACT_OR_NULL, EXCLUDE_FIRST, INCOMPLETE_NULL,
                                            NO_COUNT_NULL, PACED, PAGE_BOUND, RECORDED_95,
                                            REPEAT_TWICE_NULL, RESTART_RECOVERED, SEND_UNSLOWED, SKIP_NEXT)
from slop.lib.audience_crawl_wire import AudienceWire
from slop.seed import audience_crawl_priors

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "audience-crawl-legacy"
CREATORS = {"small": 10, "medium": 20, "huge": 20}
ROSTER = 300                  # fans per Creator (6 pages of 50)
FOLLOWING, FOLLOW_OVERLAP = 80, 10
BIG_FANS = 10_500             # > of_paging.MAX_PAGES (200) x ROSTER_PAGE (50)
GUARD_N = 5
BIG_SENDS, DEAD_SENDS = 3, 1   # the big Creator's 2nd and 3rd queue behind its first crawl (210+ pages)
P2B_SENDS = 2                 # each P2b Creator's automation sends, SPACING_S apart (the 2nd after the 1st's crawl)
PARTIAL_X = 10                # the partial Creator's rosters: OF serves 1 / PARTIAL_X of each (AE: ~10x short)
PRIOR_AGE_H = 25              # its seeded `incomplete` verdict's age: past AUDIENCE_CRAWL_REPROBE_S (24 h)
BROKEN_LIST_N = 150           # members of the broken Creator's custom exclude list: over one LIST_PAGE (100), so
#                               OF's page-1 echo is a real cut (100 read != usersCount 150); an echoed list holding
#                               its usersCount is complete (#440)
SPACING_S = 12.0              # > of_write._OF_WRITE_GAP_S (11)
CLOSE_S = 0.5                 # every Creator's 2nd send after its 1st (the other kind: no write gap between them)
ROSTER_PAGE = 50              # the crawl's page (AUDIENCE_CRAWL_ROSTER_PAGE default)
P429, RETRY_AFTER_S = 0.06, 2
PAGE_GAP_S, JITTER_S = 0.15, 0.03
PACED_TOL_S = 0.03
DEADLINE_S = 240
RELAY_ENV = {"AUDIENCE_CRAWL_DEADLINE_S": str(DEADLINE_S), "AUDIENCE_CRAWL_429_FIRST_S": "1",
             "AUDIENCE_CRAWL_429_MAX_S": "4"}
SEND_P95_S = 3.0
POLL_S = 0.25
QUIET_S = 12.0
P95_VS_LAST = (1.5, 300)
P95_VS_LAST_MIN_N = 8
TEXT = "slop audience crawl {}"
QUEUE = "/api/of/v2/messages/queue"
ENQUEUE = "/admin/automation/enqueue"
# Legacy (the fault) logs each failed inline read with its traceback; the dead Creator's 401 too.
EXPECTED_TRACEBACKS = (("resolve_recipients failed", "429 for http"), ("resolve_recipients failed", "401 for http"),
                       ("recipient record failed", "429 for http"), ("recipient record failed", "401 for http"))
_END = re.compile(r"audience_crawl_end account=(\S+) run=(\S+) outcome=(\S+) pages=(\d+) failed=(\d+) "
                  r"resumes=(\d+) waited_s=([\d.]+) reused=(\d+) coalesced=(\d+)"
                  r"(?: recipients=\S+)?(?: sent_count=(\S+) ratio=(\S+))?")
_LIST_USERS = re.compile(r"^/api2/v2/lists/(\d+)/users$")
_LIST = re.compile(r"^/api2/v2/lists/(\d+)$")
_REPEAT = re.compile(r"audience_crawl repeated page account=(\S+) src=(.+?) offset=\d+ .*?users_count=(\S+) -> (\S+)")


def _p95(xs: list[float]) -> float | None:
    ys = sorted(xs)
    return ys[max(0, math.ceil(0.95 * len(ys)) - 1)] if ys else None


def _q(w, sql: str, args=()) -> list[tuple]:
    con = w.sql()
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


async def run(ctx) -> None:
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = CREATORS.get(ctx.scale, CREATORS["small"])
    await ctx.build(PROFILE)
    cs = [c["id"] for c in w.data["creators"]]
    big, dead, churn, partial, broken, twice, bare = cs[:7]
    special = (partial, broken, twice, bare)  # P2b's: outside RECORDED_95 / EXACT_OR_NULL
    normal = [a for a in cs if a not in (big, dead, *special)]
    rng = w.rng("scenario:mass-audience-crawl")

    # ── OF's rosters (fan ids in each Creator's seeded block: seed/fans.py's FAN_ID_BASE + i x 1e6) ──
    fans, following, guard = {}, {}, {}
    for i, aid in enumerate(cs):
        base = 600_000_000 + i * 1_000_000
        fans[aid] = list(range(base, base + (BIG_FANS if aid == big else ROSTER)))
        following[aid] = sorted(fans[aid][:FOLLOW_OVERLAP] + list(range(base + 900_000,
                                                                         base + 900_000 + FOLLOWING - FOLLOW_OVERLAP)))
        guard[aid] = sorted(rng.sample(fans[aid], GUARD_N))
    aw = AudienceWire(fake, seed=ctx.seed, fans=fans, following=following, p429=P429,
                      retry_after_s=RETRY_AFTER_S, dead={dead}, churn={churn}, tail_repeat={twice},
                      short={partial: PARTIAL_X}, unlisted={bare})
    # P2b: OF's audience of a send = both rosters minus the guard (its Auto_Exclude list holds exactly the guard)
    audience_n = {a: len(set(fans[a]) | set(following[a])) - GUARD_N for a in (partial,)}
    with fake.lock:                    # the partial Creator's Auto_Exclude, made up front: the seeded send excludes it
        ae_lid = {partial: next(fake._ids)}
        fake.lists.setdefault(partial, []).append({"id": ae_lid[partial], "type": "custom", "name": "Auto_Exclude",
                                                   "usersCount": 0})
        fake.list_users[ae_lid[partial]] = []
    priors = audience_crawl_priors.seed(w, {partial: ("incomplete", timedelta(hours=PRIOR_AGE_H))},
                                        ["fans", "following"], {partial: [ae_lid[partial]]},
                                        {partial: guard[partial]})
    with fake.lock:                    # the broken Creator's custom exclude list: OF ignores its offset
        broken_lid = next(fake._ids)
        fake.lists.setdefault(broken, []).append({"id": broken_lid, "type": "custom", "name": "slop broken exclude",
                                                  "usersCount": BROKEN_LIST_N})
        fake.list_users[broken_lid] = sorted(w.rng("scenario:mass-audience-crawl:p2b").sample(fans[broken],
                                                                                           BROKEN_LIST_N))
        fake.repeat_pages.add(broken_lid)
    ctx.metric("p2b", {"partial": partial[-4:], "broken": broken[-4:], "twice": twice[-4:], "bare": bare[-4:],
                       "prior_runs": {a[-4:]: v for a, v in priors.items()}, "audience_n": {a[-4:]: v for a, v in
                                                                                          audience_n.items()},
                       "broken_list": broken_lid, "auto_exclude": {a[-4:]: v for a, v in ae_lid.items()}})
    r = await ctx.owner.post("/__slop/audience-crawl/pacing", json={"PAGE_GAP_S": PAGE_GAP_S, "JITTER_S": JITTER_S})
    r.raise_for_status()
    ctx.metric("pacing", r.json())

    # ── the plan: per Creator, its sends SPACING_S apart from a seeded offset, kinds alternating ──
    n = max(1, ctx.users)
    per: dict[str, list[dict]] = {a: [] for a in cs}
    for k in range(n):
        per[normal[k % len(normal)]].append({})
    per[big] = [{} for _ in range(BIG_SENDS)]
    per[dead] = [{} for _ in range(DEAD_SENDS)]
    per[partial] = [{} for _ in range(P2B_SENDS)]
    per[twice] = [{} for _ in range(P2B_SENDS)]
    per[bare] = [{} for _ in range(P2B_SENDS)]
    per[broken] = [{"xlists": [str(broken_lid)]} for _ in range(P2B_SENDS)]
    plan: list[dict] = []
    for ci, aid in enumerate(cs):
        off = rng.uniform(0, SPACING_S)
        for k, p in enumerate(per[aid]):
            at = off + (CLOSE_S if k == 1 and aid not in (big, *special) else k * SPACING_S)
            kind = "auto" if aid in special or (k + ci) % 2 == 0 else "composer"   # P2b's: the seeded prior's kind
            p.update(aid=aid, kind=kind, at=at, text=TEXT.format(len(plan)))
            plan.append(p)
    load_s = max(p["at"] for p in plan)
    ctx.metric("plan", {"sends": len(plan), "creators": len(cs), "load_s": round(load_s, 1),
                        "kinds": dict(Counter(p["kind"] for p in plan)), "big": big[-4:], "dead": dead[-4:],
                        "churn": churn[-4:]})

    # ── the stamp poller: first time each mass run is seen stamped ──
    seen: dict[int, float] = {}
    stop_poll = asyncio.Event()

    async def poller() -> None:
        while not stop_poll.is_set():
            t = time.time()
            for (mid,) in await asyncio.to_thread(_q, w, "SELECT id FROM mass_runs WHERE recipients_json IS NOT NULL"):
                seen.setdefault(int(mid), t)
            try:
                await asyncio.wait_for(stop_poll.wait(), POLL_S)
            except asyncio.TimeoutError:
                pass

    send_http = ctx.owner.share(limits=min(200, len(cs) * 2 + 8))

    async def auto_send(p: dict) -> None:
        p["t_enq"] = time.time()
        r = await send_http.post(ENQUEUE, json={"account_id": p["aid"], "kind": "send_mass_message", "payload": {
            "text": p["text"], "user_lists": ["fans", "following"], "excluded_users": guard[p["aid"]],
            **({"excluded_user_lists": p["xlists"]} if p.get("xlists") else {}),
            "exclude_replied_hours": 0, "exclude_inbound_hours": 0}})
        p["http"] = r.status_code
        if r.status_code != 200:
            return
        for _ in range(600):
            r = await send_http.post("/__slop/run-automation", timeout=900, json={
                "account_id": p["aid"], "kind": "send_mass_message", "claim": True})
            res = (r.json().get("result") or {}) if r.status_code == 200 else {}
            if res.get("reason") not in ("in_flight", "no_job"):
                break
            await asyncio.sleep(0.1)
        p["t_ret"] = time.time()
        p["result"] = {k: res.get(k) for k in ("status", "reason", "mass_run_id")}
        mid = res.get("mass_run_id")
        if mid:
            p["mass_run_id"] = int(mid)
            row = await asyncio.to_thread(_q, w, "SELECT recipients_json IS NULL FROM mass_runs WHERE id = ?", (mid,))
            p["null_at_return"] = bool(row and row[0][0])

    async def composer_send(p: dict) -> None:
        p["t_enq"] = time.time()
        r = await send_http.post(QUEUE, headers={"X-Account-Id": p["aid"]}, json={
            "text": p["text"], "user_lists": ["fans", "following"], "excluded_users": guard[p["aid"]],
            **({"excluded_user_lists": p["xlists"]} if p.get("xlists") else {})})
        p["t_ret"] = time.time()
        p["http"] = r.status_code
        if r.status_code == 200 and r.json().get("_mass_run_id"):
            p["mass_run_id"] = int(r.json()["_mass_run_id"])

    async def creator(aid: str, t0: float) -> None:
        for p in per[aid]:
            await asyncio.sleep(max(0.0, t0 + p["at"] - time.monotonic()))
            try:
                await (auto_send(p) if p["kind"] == "auto" else composer_send(p))
            except httpx.HTTPError as e:      # recorded (599): the stock transport check
                p["error"] = repr(e)[:200]

    ctx.rec.stage = "load"
    polling = asyncio.create_task(poller())
    t0 = time.monotonic()
    await asyncio.gather(*(creator(a, t0) for a in cs))
    ctx.rec.stage = None
    t_sent = time.time()

    # ── drain: every recordable send stamped, or no roster call for QUIET_S, or the deadline ──
    def mass_run(p):
        return p.get("mass_run_id")

    recordable = [p for p in plan if mass_run(p) and p["aid"] not in (dead, *special)]
    p2b_sends = [p for p in plan if mass_run(p) and p["aid"] in special]
    while True:
        await asyncio.sleep(1.0)
        ids = ",".join(str(mass_run(p)) for p in p2b_sends) or "0"
        judged = {int(i) for (i,) in await asyncio.to_thread(
            _q, w, f"SELECT id FROM mass_runs WHERE crawl_outcome IS NOT NULL AND id IN ({ids})")}
        if all(mass_run(p) in seen for p in recordable) and all(mass_run(p) in judged for p in p2b_sends):
            break
        snap = aw.snapshot()
        last_page = max((x["t"] for x in snap["pages"]), default=t_sent)
        if time.time() - max(last_page, t_sent) > QUIET_S or time.time() - t_sent > DEADLINE_S + 30:
            break
    await asyncio.sleep(2 * POLL_S)
    stop_poll.set()
    await polling
    await send_http.aclose()
    t_drained = time.time()

    # ── read back: runs, the wire's accepts and pages, the crawl lines ──
    snap = aw.snapshot()
    by_text = {a["text"]: a for a in snap["accepts"]}
    with fake.lock:
        qid_text = {int(e["id"]): (a, e.get("text") or "") for a, es in fake.queue.items() for e in es}
    rows = {int(i): {"aid": a, "queue_id": q, "rec": None if rj is None else json.loads(rj), "kind": k, "crawl": co,
                     "af": af}
            for i, a, q, rj, k, co, af in _q(w, "SELECT id, account_id, queue_id, recipients_json, automation_kind, "
                                                "crawl_outcome, audience_filter FROM mass_runs")}
    for p in plan:
        row = rows.get(mass_run(p)) if mass_run(p) else None
        p["row"] = row
        wire_text = qid_text.get(int(row["queue_id"]))[1] if row and row["queue_id"] and int(row["queue_id"]) in qid_text else None
        p["accept"] = by_text.get(wire_text) if wire_text is not None else None
    lines, repeats = [], []
    for log in sorted(ctx.out.glob("relay*.log")):
        text = log.read_text(errors="replace")
        repeats += [{"account": m[1], "src": m[2], "users_count": m[3], "verdict": m[4]} for m in _REPEAT.finditer(text)]
        for m in _END.finditer(text):
            lines.append({"account": m[1], "run": m[2], "outcome": m[3], "pages": int(m[4]), "failed": int(m[5]),
                          "resumes": int(m[6]), "waited_s": float(m[7]), "reused": int(m[8]),
                          "coalesced": int(m[9]), "sent_count": m[10], "ratio": m[11]})
    ctx.metric("audience_crawl_end", {"lines": len(lines), "outcomes": dict(Counter(x["outcome"] for x in lines)),
                                      "pages": sum(x["pages"] for x in lines), "failed": sum(x["failed"] for x in lines),
                                      "resumes": sum(x["resumes"] for x in lines),
                                      "waited_s": round(sum(x["waited_s"] for x in lines), 1),
                                      "reused": sum(x["reused"] for x in lines),
                                      "coalesced_lines": sum(1 for x in lines if x["coalesced"])})

    def stamped_in_time(p) -> bool:
        mid, acc = mass_run(p), p["accept"]
        return bool(mid in seen and acc and seen[mid] - acc["t"] <= DEADLINE_S + POLL_S + 1)

    # RECORDED_95
    rec_ok = [p for p in recordable if stamped_in_time(p)]
    rate = len(rec_ok) / len(recordable) if recordable else 0.0
    ctx.check(RECORDED_95, bool(recordable) and rate >= 0.95, recordable=len(recordable), stamped=len(rec_ok),
              rate=round(rate, 3), by_creator={a[-4:]: f"{sum(1 for p in rec_ok if p['aid'] == a)}/"
                                                     f"{sum(1 for p in recordable if p['aid'] == a)}" for a in cs},
              unstamped=[{"text": p["text"], "aid": p["aid"][-4:], "kind": p["kind"]}
                         for p in recordable if p not in rec_ok][:10],
              not_accepted=[{"text": p["text"], "http": p.get("http"), "result": p.get("result"),
                             "error": p.get("error")} for p in plan if not mass_run(p)][:10])

    # EXACT_OR_NULL
    wrong, compared = [], 0
    for p in plan:
        row = p["row"]
        if not row or row["rec"] is None or p["aid"] in (churn, dead, *special):
            continue
        compared += 1
        truth = set((p["accept"] or {}).get("truth") or ())
        got = set(row["rec"])
        if p["accept"] is None or got != truth:
            wrong.append({"text": p["text"], "aid": p["aid"][-4:], "n": len(got), "truth": len(truth),
                          "extra": sorted(got - truth)[:5], "missing": sorted(truth - got)[:5]})
    dead_stamped = [p["text"] for p in plan if p["aid"] == dead and p["row"] and p["row"]["rec"] is not None]
    dead_sent = [p for p in plan if p["aid"] == dead and p["row"]]
    ctx.check(EXACT_OR_NULL, compared > 0 and not wrong and not dead_stamped and bool(dead_sent),
              compared=compared, wrong=wrong[:10], n_wrong=len(wrong), dead_sent=len(dead_sent),
              dead_stamped=dead_stamped)

    # PACED
    by_c: dict[str, list[float]] = {}
    for x in snap["pages"]:
        if x["t0"] is not None:
            by_c.setdefault(x["account"], []).append(x["t0"])
    gaps, short = {}, {}
    for aid, ts in by_c.items():
        ts.sort()
        d = [b - a for a, b in zip(ts, ts[1:])]
        gaps[aid[-4:]] = round(min(d), 3) if d else None
        k = sum(1 for g in d if g < PAGE_GAP_S - PACED_TOL_S)
        if k:
            short[aid[-4:]] = k
    live = [a for a in cs if a not in (dead, broken)]   # the broken-list Creator reads no roster (EXCLUDE_FIRST)
    ctx.check(PACED, all(len(by_c.get(a, ())) >= 2 for a in live) and not short,
              floor_s=round(PAGE_GAP_S - PACED_TOL_S, 3), min_gap_s=gaps, short_gaps=short,
              pages=sum(len(v) for v in by_c.values()),
              statuses=dict(Counter(str(x["status"]) for x in snap["pages"])))

    # SEND_UNSLOWED
    lat = {"auto": [], "composer": []}
    for p in plan:
        if p["accept"] is not None and "t_enq" in p:
            lat[p["kind"]].append(p["accept"]["t"] - p["t_enq"])
    p95_all = _p95(lat["auto"] + lat["composer"])
    r2 = (lambda x: None if x is None else round(x, 3))
    ctx.check(SEND_UNSLOWED, p95_all is not None and p95_all <= SEND_P95_S, p95_s=r2(p95_all),
              p95_auto_s=r2(_p95(lat["auto"])), p95_composer_s=r2(_p95(lat["composer"])), budget_s=SEND_P95_S,
              n={k: len(v) for k, v in lat.items()})

    # DETACHED
    autos = [p for p in plan if p["kind"] == "auto" and mass_run(p)]
    attached = [p["text"] for p in autos if not p.get("null_at_return")]
    ctx.check(DETACHED, bool(autos) and not attached, automation_sends=len(autos), stamped_before_return=attached[:10],
              n_attached=len(attached))

    # BIG_ROSTER
    bigs = [p for p in recordable if p["aid"] == big]
    big_ok = [p for p in bigs if stamped_in_time(p) and p["row"]["rec"] is not None and len(p["row"]["rec"]) > 10_000]
    ctx.check(BIG_ROSTER, bool(bigs) and len(big_ok) == len(bigs), sends=len(bigs), recorded=len(big_ok),
              sizes=[None if not p["row"] or p["row"]["rec"] is None else len(p["row"]["rec"]) for p in bigs])

    # PAGE_BOUND: roster calls vs the per-round call bound; no crawl read of a verified list; the big Creator shares
    roster_calls = Counter(x["account"] for x in snap["pages"])
    per_read = {a: sum(math.ceil(len(r[a]) / ROSTER_PAGE) + 1 for r in (fans, following)) for a in cs}
    # ASSUMPTION: every send of a Creator needs both rosters, so a k-way round logs coalesced=k-1 on
    # each line and rounds = sum 1/(coalesced+1). Only the big Creator's sharing is gated.
    rounds, extra = Counter(), Counter()
    for x in lines:
        rounds[x["account"]] += 1 / (x["coalesced"] + 1)
        extra[x["account"]] += x["resumes"] + x["failed"]
    # a tail-repeat roster re-reads its repeated page once before the repeat ends it (_page): one more call a round
    reread = {a: round(rounds[a]) if a == twice else 0 for a in cs}
    bound = {a: round(rounds[a]) * per_read[a] + extra[a] + reread[a] for a in cs}
    over = {a[-4:]: {"calls": roster_calls[a], "bound": bound[a]} for a in cs if roster_calls[a] > bound[a]}
    ae_lists = {a: set() for a in cs}
    for acc in snap["accepts"]:
        if acc["account"] in ae_lists:
            ae_lists[acc["account"]].update(x for x in acc.get("excluded_lists") or () if x != broken_lid)
    with fake.lock:
        calls = list(fake.calls)
    list_reads = Counter()
    for c in calls:
        m = _LIST_USERS.match(c["path"])
        if (m and c["route"].startswith("GET ") and c["account"] in ae_lists and int(m[1]) in ae_lists[c["account"]]
                and int((parse_qs(c.get("query") or "").get("offset") or ["0"])[0]) == 0):
            list_reads[c["account"]] += 1
    syncs = Counter(p["aid"] for p in plan if mass_run(p))     # each minted send synced its Auto_Exclude once
    verified_reads = {a[-4:]: list_reads[a] - syncs[a] for a in cs if list_reads[a] != syncs[a]}
    big_rounds = round(rounds[big])
    shared = len([p for p in plan if p["aid"] == big and mass_run(p)]) > big_rounds >= 1
    ctx.check(PAGE_BOUND, bool(lines) and not over and not verified_reads and shared,
              over_bound=over, crawl_reads_of_verified_lists=verified_reads, big_rounds=big_rounds,
              big_sends=len([p for p in plan if p["aid"] == big]),
              rounds={a[-4:]: round(rounds[a], 2) for a in cs},
              calls={a[-4:]: f"{roster_calls[a]}/{bound[a]}" for a in cs},
              reused=sum(x["reused"] for x in lines), coalesced_lines=sum(1 for x in lines if x["coalesced"]),
              roster_calls_per_send=round(sum(roster_calls.values()) / max(1, len([p for p in plan if mass_run(p)])), 1))

    # ── fetch diet P2b ──
    line_of = {}
    for x in lines:
        line_of[x["run"]] = x                  # the last line of a run wins (as the watch reads it)

    def p2b(aid):
        out = []
        for p in sorted((p for p in plan if p["aid"] == aid), key=lambda p: p["at"]):
            mid = mass_run(p)
            row, ln = p["row"] or {}, line_of.get(str(mid)) or {}
            try:                                   # what makes it comparable (or not) to the seeded send
                xl = (json.loads(row.get("af") or "{}") or {}).get("excluded_user_lists")
            except ValueError:
                xl = None
            out.append({"text": p["text"], "kind": p["kind"], "mass_run_id": mid, "rec": row.get("rec"),
                        "automation_kind": row.get("kind"), "excluded_user_lists": xl,
                        "n": None if row.get("rec") is None else len(row["rec"]), "crawl_outcome": row.get("crawl"),
                        "outcome": ln.get("outcome"), "pages": ln.get("pages"), "failed": ln.get("failed"),
                        "sent_count": ln.get("sent_count"), "ratio": ln.get("ratio"), "accept": p["accept"]})
        return out

    def ratio_of(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def feed_reads(aid):
        return sum(1 for x in snap["feeds"] if x["account"] == aid and x["status"] == 200)

    show = lambda xs: [{k: v for k, v in x.items() if k not in ("rec", "accept")} for x in xs]
    ps = p2b(partial)
    first, second = (ps + [{}, {}])[:2]
    r1 = ratio_of(first.get("ratio"))
    ctx.check(INCOMPLETE_NULL, bool(first.get("mass_run_id")) and first.get("rec") is None
              and first.get("outcome") == "incomplete" and first.get("crawl_outcome") == "incomplete"
              and first.get("sent_count") == str(audience_n[partial]) and r1 is not None and r1 < 1.0, sends=show(ps),
              audience_n=audience_n[partial], prior_run=priors.get(partial))
    first_calls = (first.get("pages") or 0) + (first.get("failed") or 0) - feed_reads(partial)
    ctx.check(SKIP_NEXT, bool(second.get("mass_run_id")) and second.get("rec") is None
              and second.get("outcome") == "skipped_incomplete" and second.get("pages") == 0
              and second.get("crawl_outcome") == "skipped_incomplete" and roster_calls[partial] <= first_calls,
              roster_calls=roster_calls[partial], first_line_roster_calls=first_calls,
              feed_reads=feed_reads(partial), sends=show(ps))
    bs = p2b(broken)
    broken_reads = sum(1 for c in calls if c["account"] == broken and c["route"].startswith("GET ")
                       and (m := _LIST_USERS.match(c["path"])) and int(m[1]) == broken_lid)
    count_gets = Counter(c["status"] for c in calls if c["account"] == broken and c["route"].startswith("GET ")
                         and (m := _LIST.match(c["path"])) and int(m[1]) == broken_lid)
    list_repeats = [x for x in repeats if x["account"] == broken and x["src"] == f"('list', {broken_lid})"]
    ctx.check(EXCLUDE_FIRST, len(bs) == P2B_SENDS and all(
        x["mass_run_id"] and x["rec"] is None and x["outcome"] == "truncated" and x["crawl_outcome"] == "truncated"
        for x in bs) and roster_calls[broken] == 0 and broken_reads >= len(bs)
        and list_repeats and all(x["users_count"] == str(BROKEN_LIST_N) and x["verdict"] == "truncated"
                                 for x in list_repeats)
        and set(count_gets) == {200} and count_gets[200] >= len(list_repeats),   # a 404 reads users_count=-
              roster_calls=roster_calls[broken], list_reads=broken_reads, list_id=broken_lid,
              count_gets=dict(count_gets), repeat_lines=list_repeats, sends=show(bs))
    def tail_reads(aid):
        return sum(1 for x in snap["pages"] if x["account"] == aid and x["route"].endswith("/subscribers")
                   and x["status"] == 200 and x["offset"] >= len(fans[aid]))

    rs = p2b(twice)
    verdicts = Counter(x["verdict"] for x in repeats if x["account"] == twice)
    cuts = verdicts["truncated"]
    ctx.check(REPEAT_TWICE_NULL, len(rs) == P2B_SENDS and all(
        x["mass_run_id"] and x["rec"] is None and x["outcome"] == "truncated" and x["crawl_outcome"] == "truncated"
        and x["sent_count"] == "-" for x in rs)
        and cuts >= 1 and set(verdicts) == {"retry", "truncated"} and verdicts["retry"] >= cuts
        and tail_reads(twice) >= 2 * cuts,
              repeat_verdicts=dict(verdicts), tail_repeats_read=tail_reads(twice), roster=len(fans[twice]),
              sends=show(rs))
    bs2 = p2b(bare)
    bare_repeats = sum(1 for x in repeats if x["account"] == bare)
    ctx.check(NO_COUNT_NULL, len(bs2) == P2B_SENDS and all(
        x["mass_run_id"] and x["rec"] is None and x["outcome"] == "no_count" and x["crawl_outcome"] == "no_count"
        and x["sent_count"] == "-" and x["ratio"] == "-" for x in bs2)
              and feed_reads(bare) >= 1 and bare_repeats == 0,
              feed_reads=feed_reads(bare), repeat_lines=bare_repeats, sends=show(bs2))

    # drift (reported, not gated): the churn Creator's stamps vs OF at accept
    extra = missing = n_stamp = n_truth = 0
    for p in plan:
        if p["aid"] == churn and p["row"] and p["row"]["rec"] is not None and p["accept"]:
            got, truth = set(p["row"]["rec"]), set(p["accept"]["truth"])
            extra, missing = extra + len(got - truth), missing + len(truth - got)
            n_stamp, n_truth = n_stamp + len(got), n_truth + len(truth)
    drift = {"extra_share": round(extra / n_stamp, 4) if n_stamp else None,
             "missing_share": round(missing / n_truth, 4) if n_truth else None,
             "churned": snap["churned"].get(churn, 0)}
    ctx.metric("drift", drift)
    ctx.note(f"drift (churn Creator, not gated): {drift}")

    # ── RESTART_RECOVERED: after every check above, the big Creator's two sends (its crawl outlives shutdown's
    #    bounded drain), then SIGTERM with that crawl in flight, start on the same temp dir, await the stamps ──
    ctx.rec.stage = "restart"
    send_http = ctx.owner.share(limits=8)   # auto_send / composer_send read it at call time
    rplan = [{"aid": big, "kind": kind, "text": TEXT.format(f"restart {i}")} for i, kind in enumerate(("auto", "composer"))]
    for i, p in enumerate(rplan):
        if i:
            await asyncio.sleep(CLOSE_S)
        try:
            await (auto_send(p) if p["kind"] == "auto" else composer_send(p))
        except httpx.HTTPError as e:
            p["error"] = repr(e)[:200]
    await send_http.aclose()
    t_stop, stop_s = await asyncio.to_thread(ctx.stack.stop_relay, 0, 75.0)
    null_at_stop = {int(i) for (i,) in _q(w, "SELECT id FROM mass_runs WHERE recipients_json IS NULL")}
    log_at_stop = "".join(f.read_text(errors="replace") for f in sorted(ctx.out.glob("relay*.log")))
    ended = {m[2] for m in _END.finditer(log_at_stop)}
    cancelled = [r for m in re.finditer(r"audience_crawl_cancelled account=\S+ runs=(\S+)", log_at_stop)
                 for r in m[1].split(",")]
    await asyncio.to_thread(ctx.stack.start_relay)
    t_boot = time.time()
    r = await ctx.owner.post("/__slop/audience-crawl/pacing", json={"PAGE_GAP_S": PAGE_GAP_S, "JITTER_S": JITTER_S})
    r.raise_for_status()
    snap2 = aw.snapshot()
    by_text2 = {a["text"]: a for a in snap2["accepts"]}
    with fake.lock:
        qid_text2 = {int(e["id"]): e.get("text") or "" for es in fake.queue.values() for e in es}
    qid_of = {int(i): q for i, q in _q(w, "SELECT id, queue_id FROM mass_runs")}

    def accept_t(p):
        q = qid_of.get(mass_run(p))
        acc = by_text2.get(qid_text2.get(int(q))) if q is not None else None
        return acc["t"] if acc else None

    # cut off = a recordable send (OF accepted, not the Dead session) NULL at the stop whose crawl logged no end
    # line (it never finished), its deadline still ahead at the boot
    # ASSUMPTION: a send whose crawl ended NULL with an outcome (deadline, truncated) is not "cut off" and not
    # gated here (RECORDED_95 owns it); the restart runs after every other check so none of them sees it. Rung 4.
    cut = {}
    for p in plan + rplan:
        mid, t_acc = mass_run(p), accept_t(p)
        if (mid and p["aid"] != dead and mid in null_at_stop and str(mid) not in ended and t_acc is not None
                and t_acc + DEADLINE_S > t_boot):
            cut[mid] = t_acc + DEADLINE_S
    got: dict[int, float] = {}
    while cut:
        await asyncio.sleep(1.0)
        now = time.time()
        ids = ",".join(str(m) for m in cut)
        for (mid,) in await asyncio.to_thread(
                _q, w, f"SELECT id FROM mass_runs WHERE recipients_json IS NOT NULL AND id IN ({ids})"):
            got.setdefault(int(mid), now)
        if len(got) == len(cut):
            break
        last_page = max((x["t"] for x in aw.snapshot()["pages"]), default=t_boot)
        if now - max(last_page, t_boot) > QUIET_S or now > max(cut.values()) + 5:
            break
    late = sorted(m for m in cut if m not in got or got[m] > cut[m] + 2.0)   # + the 1 s poll
    recover = re.findall(r"audience_crawl_recover runs=(\d+) skipped=(\d+)",
                         "".join(f.read_text(errors="replace") for f in sorted(ctx.out.glob("relay*.log"))))
    # both restart sends (the automation's writer AND the composer's, mass_queue_api._open_mass_run) cut off and
    # stamped, each audience_filter carrying the `online` / `filters` keys recover_at_boot keys on
    rmids = [mass_run(p) for p in rplan]
    rkeys = {}
    for mid in rmids:
        raw = (_q(w, "SELECT audience_filter FROM mass_runs WHERE id = ?", (mid,)) or [(None,)])[0][0] if mid else None
        try:
            af = json.loads(raw) if raw else {}
        except ValueError:
            af = {}
        rkeys[mid] = {k: af.get(k) for k in ("online", "filters")} if isinstance(af, dict) else {}
    r_missing = [p["kind"] for p, mid in zip(rplan, rmids) if not mid or mid not in cut or mid not in got]
    r_keys_bad = [p["kind"] for p, mid in zip(rplan, rmids)
                  if rkeys.get(mid) != {"online": False, "filters": False}]
    ctx.check(RESTART_RECOVERED, bool(cut) and not late and not r_missing and not r_keys_bad,
              restart_not_cut_or_stamped=r_missing, restart_filter_keys=rkeys, restart_keys_bad=r_keys_bad,
              cut_off=sorted(cut), stamped=len(got), late_or_missing=late,
              cancelled_at_stop=cancelled, stop_s=None if stop_s is None else round(stop_s, 1),
              boot_s=round(t_boot - t_stop, 1), recover_lines=recover,
              recovered_in_s={m: round(got[m] - t_boot, 1) for m in got},
              sends=[{"text": p["text"], "kind": p["kind"], "http": p.get("http"), "mass_run_id": mass_run(p),
                      "error": p.get("error")} for p in rplan])
    ctx.rec.stage = None

    # P95_VS_LAST
    summ = ctx.rec.summary("load")
    p95 = {"send -> OF accept ms": None if p95_all is None else round(p95_all * 1000, 1)}
    p95_n = {"send -> OF accept ms": len(lat["auto"]) + len(lat["composer"])}
    for route in (f"POST {ENQUEUE}", f"POST {QUEUE}"):
        if route in summ:
            p95[route], p95_n[route] = summ[route]["p95_ms"], summ[route]["n"]
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", p95_n)
    ctx.metric("drain_s", round(t_drained - t_sent, 1))
    (ctx.out / "mass-audience-crawl.json").write_text(json.dumps({
        "plan": [{k: v for k, v in p.items() if k not in ("row",)} | {"stamped_at": seen.get(mass_run(p))}
                 for p in plan],
        "pages": snap["pages"], "lines": lines,
        "restart": [{k: v for k, v in p.items() if k not in ("row",)} for p in rplan]}, default=str))
