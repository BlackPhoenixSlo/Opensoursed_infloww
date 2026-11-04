"""A mass message's optimistic placeholders fold into OnlyFans' echo exactly once: the
composer's broadcast to explicit fans writes one placeholder-band stub per recipient
(`attribution.write_mass_optimistic_rows`: OF's queue answer carries no per-fan ids), and
when the inbox poll reads OF's chat list with that send as a chat's last message
(`reconcile_chats_from_of`) the real row adopts its stub (`adopt_thread_placeholders` ->
`attribution_pair.pair_placeholders`: nearest-first, `<br />` == `\\n`, the 6 h bound).

World: `agency_inbox` (small 3 Creators x 50 fans, medium 10 x 500), each Creator with a
captured session (seed/of_sessions) so the relay builds its REAL OFClient against
lib/of_wire.py (`OF_WIRE`). Per Creator, before any send, `seed/mass_placeholders`: a closed
run from 2 days ago whose echo never came (prod's 90% case), its stubs on STALE fans plus
BOTH fans, carrying run 0's caption.

Load: per Creator (all at once, each Creator's sends in turn) RUNS broadcasts through the
real `POST /api/of/v2/messages/queue` (owner session, X-Account-Id, `user_ids`), each a
multi-line caption to its own `--per_run` fans (run 0's include the BOTH fans), the last
`--set excluded=` (FLOW_SIZES, 2) of them also named in the body's `excluded_users` (so each run
SENDS to per_run - excluded). Then OF's chat list (`FakeOF.chats`) shows every sent recipient's
copy of its run as the last message, its text
as OF echoes it (`\\n` -> `<br />\\n`, created a second after the send), and every STALE fan a
Creator's own OF-web send of run 0's caption, now. `--users` open inboxes, as the app's
`useChatList` drives them: each has scrolled to one (Creator, page) and loads it once
(`GET /api/of/v2/chats?limit=50&offset=..`, a relay-cache miss, so a fresh OF read and one
reconcile), then head-polls page 0 every POLL_S without `refresh` (`useHeadPagePoll`: 90 s,
`refresh=false`, rides the relay cache), until every fresh stub is gone or SETTLE_S passes.

Checks: every send answered 200 and left one stub per sent recipient and none on any other
non-excluded fan (SENT); EXCL (skipped at `--set excluded=0`)
(lib/mass_queue_faults.py), right after the sends: per excluded fan no row of its run and no out row
with its caption (stub or real), no OF wire `userIds` naming it (RUNS wire bodies per Creator, so
the read is never blind), and each run's `mass_runs.recipient_count` == its sent ids; PH_ONCE
(lib/attribution_pair_faults.py): per sent recipient its stub is gone, OF's row carries its run,
one out row and one thread bubble (`GET /admin/messages/{aid}/{fan}`) hold that caption; per
BOTH fan the 2-day-old stub is still there; per STALE fan the 2-day-old stub is still there
and OF's row carries no run. Budgets: echo visible -> every stub adopted (E2E_SETTLE_MS),
route p95s, p95 vs the last green run.

Dry-run tail (O3, after every check above is recorded, so it can redden none of them): per Creator,
seed/mass_dry_run.py puts `--set dry_fence=` fans on MASSdmEXCLUDE and as many outside an enforce-mode
include list (AUTOFENCE), and the scenario gives FakeOF a custom list (`lists` / `list_users`) whose
roster = `--set dry_fresh=` fans no message touched in 12 h, `--set dry_guard=` fans the broadcasts above
reached (inside the 6 h contact guard), and both fences. max(`--users`, 2 per Creator) concurrent
`POST /admin/automation/enqueue` `send_mass_message` dry runs, alternating per Creator explicit (the
roster as `included_users`, `--set dry_excluded=` fresh fans as `excluded_users`, one payload per
Creator) and list (`user_lists: [that list]`, its own excluded fresh fans), drained by
`/__slop/automation-tick`; then ONE real enqueue per Creator of the explicit payload. DRY_NO_SEND
(lib/mass_dry_run_faults.py), the dry phase only: of_wire `queue` frames per Creator unchanged, no OF
list POST / DELETE, no new mass_runs / out messages row, every job done and every run's stats
(`GET /admin/stats/automation-runs`) dry_run, sent 0. DRY_LIST: the list runs' would_send are, as a
multiset, roster - guard - fences - their excluded_users (each non-empty); every explicit run's
would_send is that, in roster order, and the real send's wire `userIds`.

Bypasses (declared): lib/of_wire.py is OnlyFans (its own declared bypasses; the queue answer
`{id, text, createdAt}` is a guess, which is what makes every recipient a placeholder; no 10 s
broadcast throttle); OF's chat list is set by the scenario, one item per recipient, its
`<br />` echo shape the one test_placeholder_adopt pins; the inbox clients are httpx pools, not
browsers, and model only the page-load + head poll (no SSE, no manual Refresh); the stale run is SQL in the product's shape (no actor can send 2 days ago);
the tail's fences are SQL rows (seed/mass_dry_run.py), its OF list is set on FakeOF directly (OF's
side: no route makes a custom list with members in one step), its runs are drained by tick passes,
not the supervisor's cadence.
Break-it-once: placeholder-pair-ignores-window (the 6 h bound dropped: only PH_ONCE);
`--fault=mass-queue-excluded-kept` (only EXCL); `--fault=mass-dry-run-ignored` (a dry run sends:
DRY_NO_SEND + DRY_LIST); `--fault=mass-dry-run-skips-guard` (the list dry run's in-memory excludes
dropped: only DRY_LIST).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from slop.lib.attribution_pair_faults import PH_ONCE
from slop.lib.client import Recorder
from slop.lib.mass_dry_run_faults import DRY_LIST, DRY_NO_SEND
from slop.lib.mass_queue_faults import EXCL
from slop.seed import mass_dry_run, mass_placeholders, of_sessions, ts

sys.path.append(str(Path(__file__).resolve().parents[2] / "service"))   # the pairing key, pure
from attribution_pair import _norm_body  # noqa: E402

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "placeholder-pair-ignores-window"
RUNS = 3
STALE_AGE = timedelta(days=2)
PAGE = 50                                            # the relay's /chats limit cap
# useHeadPagePoll's 90 s, 2x compressed with jitter (declared). Not `refresh=1` on every page
# every tick (this scenario's first cut): every fresh read reconciles its page in ONE write
# transaction (reconcile_chats_from_of), measured 122 ms p50 / 825 ms p95 of SQLite write lock per
# 50-chat page, and ~5-27 such reads/s at --users=200 oversubscribe the lock: reconciles waited out
# the 30 s busy_timeout and rolled back "database is locked"
# (20261031T085043Z-2026-10-31-mass-placeholder-echo-0480, 98 of 251;
# 20261031T085400Z-2026-10-31-mass-placeholder-echo-baseline-ae29, 32 at 30-45 s). The app never
# sends that load (only a manual Refresh forwards ?refresh=1); an open product limit, not this flow's.
POLL_S = (30.0, 45.0)
SETTLE_S = 240
ECHO_ID_BASE = 9_760_000_000_000                     # OF ids for the chat list's copies
E2E_SETTLE_MS = 2 * 45_000   # each page's first load lands within one compressed poll; 2x slack
# The enqueue budget is the composer's: every dry run is enqueued at once, one SQLite write each, so the
# burst queues on the write lock (measured --scale=medium --users=200: p50 755 / p95 1143 ms,
# 20261103T045033Z-2026-10-31-mass-placeholder-echo-9023).
P95_MS = {"GET /api/of/v2/chats": 2000, "POST /api/of/v2/messages/queue": 3000,
          "GET /admin/messages/:id/:id": 1000, "POST /admin/automation/enqueue": 3000}
P95_VS_LAST = (1.5, 500)

SENT = "every broadcast answered 200 and left one placeholder per recipient"
DRY_LIST_ID_BASE = 7_900_000                         # the tail's OF custom list, one per Creator
DRY_SETTLE_S = 300
_LIST_WRITES = ("POST /api2/v2/lists", "POST /api2/v2/lists/{id}/users/{id}",
                "DELETE /api2/v2/lists/{id}/users/{id}")


def caption(aid: str, k: int) -> str:
    return f"slop mass {k} for {aid}\n\nmiss u, open this one"


def of_echo(text: str) -> str:
    return text.replace("\n", "<br />\n")


def _utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    aids = [c["id"] for c in w.data["creators"]]
    n_run, n_stale, n_both, n_excl = (ctx.param(k, w.size[f"mass_placeholder_{k}"])
                                      for k in ("per_run", "stale", "both", "excluded"))
    assert 0 <= n_excl and n_run - n_excl >= max(n_both, 1), (n_run, n_excl, n_both)
    rng = w.rng("scenario:mass-placeholder-echo")

    # Who gets what, per Creator: runs[k] (fresh recipients), stale, both (also in runs[0]).
    plan: dict[str, dict] = {}
    for aid in aids:
        fans = [f["id"] for f in w.data["fans"][aid]]
        rng.shuffle(fans)
        need = RUNS * n_run + n_stale
        assert len(fans) >= need, (aid, len(fans), need)
        runs = [fans[k * n_run:(k + 1) * n_run] for k in range(RUNS)]
        stale = fans[RUNS * n_run:need]
        plan[aid] = {"runs": runs, "stale": stale, "both": runs[0][:n_both], "run_ids": [None] * RUNS,
                     "sent": [r[:n_run - n_excl] for r in runs], "excl": [r[n_run - n_excl:] for r in runs]}
    old = w.now - STALE_AGE
    stale_runs = mass_placeholders.seed(w, {aid: plan[aid]["stale"] + plan[aid]["both"] for aid in aids},
                                        lambda aid: caption(aid, 0), old)

    # ── the broadcasts, through the composer's route ────────────────────────
    owner = ctx.owner.share(limits=len(aids) + 4)
    send_bad: list = []

    async def creator_sends(aid: str) -> None:
        for k, fans in enumerate(plan[aid]["runs"]):
            r = await owner.post("/api/of/v2/messages/queue", headers={"X-Account-Id": aid},
                                 json={"text": caption(aid, k), "user_ids": fans,
                                       "excluded_users": plan[aid]["excl"][k]})
            body = r.json() if r.status_code == 200 else {}
            plan[aid]["run_ids"][k] = body.get("_mass_run_id")
            if r.status_code != 200 or body.get("_mass_run_id") is None:
                send_bad.append({"aid": aid, "run": k, "status": r.status_code, "body": r.text[:200]})

    t_send = time.perf_counter()
    await asyncio.gather(*(creator_sends(a) for a in aids))
    send_s = time.perf_counter() - t_send

    excl_of = {(aid, int(rid)): set(plan[aid]["excl"][k]) for aid in aids
               for k, rid in enumerate(plan[aid]["run_ids"]) if rid is not None}

    def stub_fans() -> dict[tuple[str, int], list[int]]:
        """Per (Creator, fresh run) the fans of ALL its stubs but that run's excluded fans (theirs are
        EXCL's): a phantom stub on any other fan, or a second one, still shows."""
        con = w.sql()
        try:
            out: dict[tuple[str, int], list[int]] = {}
            for a, r, f in con.execute(
                    "SELECT account_id, mass_run_id, fan_id FROM messages WHERE message_id >= ? AND message_id < ?",
                    (mass_placeholders.PLACEHOLDER_BASE, mass_placeholders.PLACEHOLDER_CEIL)):
                key = (str(a), int(r))
                if key in excl_of and int(f) not in excl_of[key]:
                    out.setdefault(key, []).append(int(f))
            return out
        finally:
            con.close()

    # EXCL: what the excluded fans got from the sends (the DB rows and OF's wire), and the runs' counts.
    con = w.sql()
    try:
        rids = [rid for aid in aids for rid in plan[aid]["run_ids"] if rid is not None]
        counts_db = dict(con.execute("SELECT id, recipient_count FROM mass_runs WHERE id IN (%s)"
                                     % ",".join("?" * len(rids)), rids).fetchall()) if rids else {}
        excl_bad: dict[str, list] = {"row_of_run": [], "out_row": [], "wire_user_id": [], "wire_blind": [],
                                     "recipient_count": []}
        for aid in aids:
            p = plan[aid]
            fans = sorted({f for ex in p["excl"] for f in ex})
            if not fans:
                continue
            got_rows = con.execute(
                "SELECT fan_id, message_id, body, mass_run_id FROM messages WHERE direction = 'out' "
                "AND account_id = ? AND fan_id IN (%s)" % ",".join("?" * len(fans)), [aid, *fans]).fetchall()
            for k, ex in enumerate(p["excl"]):
                rid, key = p["run_ids"][k], _norm_body(caption(aid, k))
                for fid, mid, body, run in got_rows:
                    if int(fid) not in ex:
                        continue
                    if rid is not None and run == int(rid):
                        excl_bad["row_of_run"].append((aid, fid, k, mid))
                    elif _norm_body(body) == key:
                        excl_bad["out_row"].append((aid, fid, k, mid))
        for aid in aids:
            ex_all = {f for ex in plan[aid]["excl"] for f in ex}
            with ctx.of_wire.lock:
                wire = [list(b.get("userIds") or []) for b in ctx.of_wire.queue.get(aid, [])]
            if len(wire) != RUNS:
                excl_bad["wire_blind"].append((aid, len(wire)))
            for i, ids in enumerate(wire):
                hit = sorted(ex_all & {int(u) for u in ids})
                if hit:
                    excl_bad["wire_user_id"].append((aid, i, hit[:5]))
            for k, rid in enumerate(plan[aid]["run_ids"]):
                if rid is not None and counts_db.get(int(rid)) != len(plan[aid]["sent"][k]):
                    excl_bad["recipient_count"].append((aid, k, counts_db.get(int(rid)), len(plan[aid]["sent"][k])))
    finally:
        con.close()
    n_excluded = sum(len(ex) for a in aids for ex in plan[a]["excl"])
    if n_excluded:
        ctx.check(EXCL, not any(excl_bad.values()), counts={k: len(v) for k, v in excl_bad.items()},
                  excluded=n_excluded, wire_bodies=sum(len(ctx.of_wire.queue.get(a, [])) for a in aids),
                  sample={k: v[:3] for k, v in excl_bad.items() if v})
    else:
        ctx.skip(EXCL, "no excluded fans (--set excluded=0)")

    stubs = stub_fans()
    short = {}
    for aid in aids:
        for k, rid in enumerate(plan[aid]["run_ids"]):
            if rid is None:
                continue
            got = sorted(stubs.get((aid, int(rid)), []))
            if got != sorted(plan[aid]["sent"][k]):   # n_run - n_excl stubs, one per sent fan, no other fan
                short[f"{aid}:{k}"] = {"n": len(got), "want": n_run - n_excl,
                                       "off": sorted(set(got) ^ set(plan[aid]["sent"][k]))[:5]}
    ctx.check(SENT, not send_bad and not short, sends=RUNS * len(aids), bad=send_bad[:5], stubs_off=short,
              seconds=round(send_s, 2))
    if send_bad or short:
        ctx.skip(PH_ONCE, "the broadcasts did not leave their placeholders (SENT)")
        for c in (DRY_NO_SEND, DRY_LIST):
            ctx.skip(c, "the broadcasts did not leave their placeholders (SENT)")
        await owner.aclose()
        return

    # ── OF's chat list: every recipient's copy, every stale fan's OF-web send ──
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) + timedelta(seconds=1)
    echo: dict[tuple[str, int], dict] = {}   # (aid, fan) -> {id, text, run k or None}
    n = 0
    for aid in aids:
        items = []
        groups = [(k, f) for k, fans in enumerate(plan[aid]["sent"]) for f in fans] + \
                 [(None, f) for f in plan[aid]["stale"]]
        for k, fid in groups:
            n += 1
            text = caption(aid, 0 if k is None else k)
            echo[(aid, fid)] = {"id": ECHO_ID_BASE + n, "text": text, "k": k}
            items.append({"withUser": {"id": fid, "username": f"u{fid}", "name": f"Fan {fid}"},
                          "lastMessage": {"id": ECHO_ID_BASE + n, "text": of_echo(text), "createdAt": _utc(now),
                                          "fromUser": {"id": int(aid)}, "isFree": True, "price": 0,
                                          "mediaCount": 0, "media": []},
                          "unreadMessagesCount": 0, "hasUnread": False, "canSendMessage": True})
        items.reverse()   # newest first, as OF orders `recent`
        with ctx.of_wire.lock:
            ctx.of_wire.chats[aid] = items

    fresh_ids = [(aid, int(rid)) for aid in aids for rid in plan[aid]["run_ids"]]

    def settled() -> bool:
        con = w.sql()
        try:
            left = sum(len(v) for k, v in stub_fans().items() if k in fresh_ids)
            have = con.execute(f"SELECT COUNT(*) FROM messages WHERE message_id BETWEEN {ECHO_ID_BASE + 1} "
                               f"AND {ECHO_ID_BASE + n}").fetchone()[0]
        finally:
            con.close()
        return left == 0 and have == n

    # ── the inbox clients: page the chat list until every stub folded in ────
    t_echo = time.perf_counter()
    done = asyncio.Event()
    deadline = t_echo + SETTLE_S
    clients = [ctx.owner.share(limits=2) for _ in range(ctx.users)]
    slots = [(aid, off) for aid in aids for off in range(0, len(ctx.of_wire.chats[aid]), PAGE)]
    reads = [0]

    async def inbox(i: int, http) -> None:
        """One open inbox: loads its (Creator, page) once from a random phase, then head-polls
        page 0 every POLL_S, both without `refresh` (the relay cache decides what is fresh)."""
        aid, off = slots[i % len(slots)]
        r = w.rng(f"scenario:mass-placeholder-echo:inbox:{i}")
        await asyncio.sleep(r.uniform(0, POLL_S[1]))
        while not done.is_set() and time.perf_counter() < deadline:
            await http.get(f"/api/of/v2/chats?limit={PAGE}&offset={off}&order=recent",
                           headers={"X-Account-Id": aid})
            reads[0] += 1
            off = 0
            await asyncio.sleep(r.uniform(*POLL_S))

    async def watch() -> float | None:
        while time.perf_counter() < deadline:
            if await asyncio.to_thread(settled):
                done.set()
                return (time.perf_counter() - t_echo) * 1000
            await asyncio.sleep(0.5)
        done.set()
        return None

    settle_ms, *_ = await asyncio.gather(watch(), *(inbox(i, h) for i, h in enumerate(clients)))
    for h in clients:
        await h.aclose()
    await asyncio.sleep(1.0)   # the last reads' reconcile tasks (fire-and-forget) land

    # ── verdict: SQL for the stub band (no route serves a stub past 1 h), the thread route for bubbles ──
    con = w.sql()
    try:
        rows = con.execute(
            "SELECT account_id, fan_id, message_id, body, mass_run_id FROM messages WHERE direction = 'out' "
            "AND account_id IN (%s)" % ",".join("?" * len(aids)), aids).fetchall()
    finally:
        con.close()
    thread: dict[tuple[str, int], list] = {}
    for aid, fid, mid, body, run in rows:
        thread.setdefault((str(aid), int(fid)), []).append((int(mid), _norm_body(body), run))

    reader = ctx.owner.share(limits=20)
    sem = asyncio.Semaphore(20)

    async def bubbles(aid: str, fid: int) -> list[str]:
        async with sem:
            r = await reader.get(f"/admin/messages/{aid}/{fid}?limit=50")
        return [_norm_body(m.get("text") or m.get("body")) for m in r.json().get("messages", [])] \
            if r.status_code == 200 else ["<http %d>" % r.status_code]

    keys = [(aid, fid) for aid in aids for fid in [f for fans in plan[aid]["sent"] for f in fans]]
    seen = dict(zip(keys, await asyncio.gather(*(bubbles(a, f) for a, f in keys))))
    await reader.aclose()

    bad: dict[str, list] = {"stub_left": [], "echo_not_stamped": [], "dup_rows": [], "dup_bubbles": [],
                            "old_stub_adopted": [], "stale_send_stamped": []}
    for aid in aids:
        p, old_ph = plan[aid], mass_placeholders.PLACEHOLDER_BASE + stale_runs[aid]
        for k, fans in enumerate(p["sent"]):
            rid, key = int(p["run_ids"][k]), _norm_body(caption(aid, k))
            for fid in fans:
                t = thread.get((aid, fid), [])
                e = echo[(aid, fid)]["id"]
                if any(m == mass_placeholders.PLACEHOLDER_BASE + rid for m, _, _ in t):
                    bad["stub_left"].append((aid, fid, k))
                if not any(m == e and run == rid for m, _, run in t):
                    bad["echo_not_stamped"].append((aid, fid, k, [(m, run) for m, _, run in t if m == e]))
                if sum(1 for m, b, _ in t if b == key and m < mass_placeholders.PLACEHOLDER_BASE) != 1:
                    bad["dup_rows"].append((aid, fid, k))
                if seen[(aid, fid)].count(key) != 1:
                    bad["dup_bubbles"].append((aid, fid, k, seen[(aid, fid)].count(key)))
        for fid in p["both"]:
            if not any(m == old_ph for m, _, _ in thread.get((aid, fid), [])):
                bad["old_stub_adopted"].append((aid, fid, "both"))
        for fid in p["stale"]:
            t = thread.get((aid, fid), [])
            e = echo[(aid, fid)]["id"]
            if not any(m == old_ph for m, _, _ in t):
                bad["old_stub_adopted"].append((aid, fid, "stale"))
            if not any(m == e and run is None for m, _, run in t):
                bad["stale_send_stamped"].append((aid, fid, [(m, run) for m, _, run in t if m == e]))
    counts = {k: len(v) for k, v in bad.items()}
    ctx.check(PH_ONCE, not any(counts.values()), counts=counts,
              recipients=len(keys), stale=sum(len(plan[a]["stale"]) for a in aids),
              both=sum(len(plan[a]["both"]) for a in aids),
              sample={k: v[:3] for k, v in bad.items() if v})

    if settle_ms is None:
        ctx.check(f"echo visible -> every placeholder adopted <= {E2E_SETTLE_MS} ms", False, budget=True,
                  settle_ms=None, timeout_s=SETTLE_S, reads=reads[0])
    else:
        ctx.check(f"echo visible -> every placeholder adopted <= {E2E_SETTLE_MS} ms", settle_ms <= E2E_SETTLE_MS,
                  budget=True, settle_ms=round(settle_ms), reads=reads[0])
    await dry_tail(ctx, w, aids, plan, rng)

    routes = ctx.rec.summary()
    for route, budget in P95_MS.items():
        if route in routes:
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"])
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")
    ctx.metric("load", {"creators": len(aids), "runs": RUNS, "per_run": n_run, "excluded": n_excl,
                        "stale": n_stale, "both": n_both,
                        "inbox_clients": len(clients), "chat_reads": reads[0], "send_s": round(send_s, 2),
                        "settle_ms": round(settle_ms) if settle_ms is not None else None})
    ctx.metric("p95_vs_last_green", {**{r: routes[r]["p95_ms"] for r in P95_MS if r in routes},
                                     **({"echo -> adopted": round(settle_ms)} if settle_ms is not None else {})})
    await owner.aclose()


async def dry_tail(ctx, w, aids: list[str], plan: dict, rng) -> None:
    """The dry-run tail (module docstring): fences + an OF list per Creator, concurrent dry runs, one
    real send per Creator, DRY_NO_SEND and DRY_LIST."""
    sizes = {k: ctx.param(f"dry_{k}", w.size[f"mass_dry_run_{k}"]) for k in ("fresh", "guard", "fence", "excluded")}
    lists = _dry_world(ctx, w, aids, plan, rng, sizes)
    jobs = _dry_jobs(ctx, aids, lists, rng)
    http = ctx.owner.share(limits=len(jobs))
    tick_http = ctx.owner.share(rec=Recorder(), limits=2)
    before = _dry_counts(ctx, w, aids)
    t_dry = time.perf_counter()
    enq_bad = await _enqueue(http, jobs)
    status = await _drain(w, tick_http, [j["job_id"] for j in jobs if j["job_id"] is not None])
    dry_s = time.perf_counter() - t_dry
    after = _dry_counts(ctx, w, aids)
    with ctx.of_wire.lock:
        new_calls = ctx.of_wire.calls[before["calls"]:after["calls"]]
    list_writes = [c for c in new_calls if c["route"] in _LIST_WRITES]
    stats: dict[str, list[dict]] = {}
    for aid in aids:
        r = await http.get(f"/admin/stats/automation-runs?kind=send_mass_message&account_id={aid}&limit=500")
        stats[aid] = [{"status": x["status"], **json.loads(x["stats_json"] or "{}")}
                      for x in (r.json().get("runs", []) if r.status_code == 200 else [])]
    _check_no_send(ctx, aids, jobs, stats, status, before, after,
                   enq_bad=enq_bad, list_writes=list_writes, seconds=dry_s)

    # One real send per Creator of the explicit payload: what OF is told is what the dry runs said.
    real_before = _dry_counts(ctx, w, aids)["queue"]
    reals = [{"aid": aid, "payload": _explicit(lists, aid)} for aid in aids]
    await _enqueue(http, reals)
    await _drain(w, tick_http, [j["job_id"] for j in reals if j["job_id"] is not None])
    wire: dict[str, tuple[list[int], int]] = {}
    with ctx.of_wire.lock:
        for aid in aids:
            new = ctx.of_wire.queue.get(aid, [])[real_before[aid]:]
            last_body = new[-1] if new else {}
            wire[aid] = ([int(u) for u in last_body.get("userIds") or []], len(new))
    _check_list(ctx, aids, lists, jobs, stats, wire)
    ctx.metric("dry_run", {"dry_runs": len(jobs), "seconds": round(dry_s, 2), "creators": len(aids), **sizes})
    await http.aclose()
    await tick_http.aclose()


def _dry_world(ctx, w, aids: list[str], plan: dict, rng, sizes: dict) -> dict[str, dict]:
    """Per Creator: the OF list roster (fresh ∪ guard ∪ both fences), its fences seeded, the list set on
    FakeOF. -> {aid: {id, roster, fresh, guard, massdm, autofence, ex_exp}}."""
    n_fresh, n_guard, n_fence, n_dx = (sizes[k] for k in ("fresh", "guard", "fence", "excluded"))
    assert n_fresh > n_dx >= 0, (n_fresh, n_dx)
    con = w.sql()
    try:
        cut = ts(datetime.utcnow() - timedelta(hours=12))
        busy = {(str(a), int(f)) for a, f in con.execute(
            "SELECT DISTINCT account_id, fan_id FROM messages WHERE created_at >= ?", (cut,))}
        massdm_had = {(str(a), int(f)) for a, f in con.execute(
            "SELECT l.account_id, m.fan_id FROM list_members m JOIN lists l ON l.id = m.list_id "
            "WHERE l.kind = 'exclude'")}
    finally:
        con.close()
    lists: dict[str, dict] = {}
    for ci, aid in enumerate(aids):
        p = plan[aid]
        used = {f for r in p["runs"] for f in r} | set(p["stale"])
        pool = [f["id"] for f in w.data["fans"][aid]
                if f["id"] not in used and (aid, f["id"]) not in busy and (aid, f["id"]) not in massdm_had]
        rng.shuffle(pool)
        need = n_fresh + 2 * n_fence
        assert len(pool) >= need, (aid, len(pool), need)
        fresh, massdm, autof = pool[:n_fresh], pool[n_fresh:n_fresh + n_fence], pool[n_fresh + n_fence:need]
        sent = [f for r in p["sent"] for f in r]
        guard = rng.sample(sent, min(n_guard, len(sent)))
        roster = fresh + guard + massdm + autof
        rng.shuffle(roster)
        lists[aid] = {"id": DRY_LIST_ID_BASE + ci, "roster": roster, "fresh": fresh, "guard": guard,
                      "massdm": massdm, "autofence": autof, "ex_exp": rng.sample(fresh, n_dx)}
    mass_dry_run.seed(w, {aid: {"massdm": v["massdm"], "autofence": v["autofence"]} for aid, v in lists.items()},
                      of_list_id_base=DRY_LIST_ID_BASE + 1000)
    with ctx.of_wire.lock:
        for aid, v in lists.items():
            ctx.of_wire.lists.setdefault(aid, []).append(
                {"id": v["id"], "type": "custom", "name": "slop dry vip", "usersCount": len(v["roster"])})
            ctx.of_wire.list_users[v["id"]] = list(v["roster"])
    return lists


def _explicit(lists: dict, aid: str) -> dict:
    v = lists[aid]
    return {"text": f"slop dry run for {aid}", "included_users": v["roster"], "excluded_users": v["ex_exp"]}


def _want(lists: dict, aid: str, ex) -> list[int]:
    """Who a run with excluded_users `ex` reaches: the roster's fresh fans minus `ex`, in roster order."""
    v, ex = lists[aid], set(ex)
    return [f for f in v["roster"] if f in set(v["fresh"]) and f not in ex]


def _dry_jobs(ctx, aids: list[str], lists: dict, rng) -> list[dict]:
    """max(--users, 2 per Creator) dry payloads, alternating per Creator explicit / list.
    -> [{aid, kind, payload}] (`job_id` set by _enqueue)."""
    jobs: list[dict] = []
    for u in range(max(ctx.users, 2 * len(aids))):
        aid = aids[u % len(aids)]
        if (u // len(aids)) % 2 == 0:
            jobs.append({"aid": aid, "kind": "explicit", "payload": {**_explicit(lists, aid), "dry_run": True}})
        else:
            jobs.append({"aid": aid, "kind": "list", "payload": {
                "text": f"slop dry run for {aid}", "user_lists": [lists[aid]["id"]],
                "excluded_users": rng.sample(lists[aid]["fresh"], len(lists[aid]["ex_exp"])),
                "dry_run": True}})
    return jobs


def _dry_counts(ctx, w, aids: list[str]) -> dict:
    con = w.sql()
    try:
        q = ",".join("?" * len(aids))
        runs = con.execute(f"SELECT COUNT(*) FROM mass_runs WHERE account_id IN ({q})", aids).fetchone()[0]
        outs = con.execute(f"SELECT COUNT(*) FROM messages WHERE direction = 'out' AND account_id IN ({q})",
                           aids).fetchone()[0]
    finally:
        con.close()
    with ctx.of_wire.lock:
        return {"mass_runs": runs, "out_rows": outs, "calls": len(ctx.of_wire.calls),
                "queue": {a: len(ctx.of_wire.queue.get(a, [])) for a in aids}}


async def _enqueue(http, jobs: list[dict]) -> list[dict]:
    """POST every job at once; sets each `job_id` (None on a failed enqueue). -> the failures."""
    bad: list[dict] = []

    async def one(j: dict) -> None:
        r = await http.post("/admin/automation/enqueue",
                            json={"account_id": j["aid"], "kind": "send_mass_message", "payload": j["payload"]})
        j["job_id"] = r.json().get("enqueued_job_id") if r.status_code == 200 else None
        if j["job_id"] is None:
            bad.append({"aid": j["aid"], "status": r.status_code, "body": r.text[:200]})

    await asyncio.gather(*(one(j) for j in jobs))
    return bad


async def _drain(w, tick_http, ids: list[int]) -> dict[int, str]:
    """Tick the automation worker until every job in `ids` is final (or DRY_SETTLE_S). -> {id: status}."""
    t0 = time.monotonic()
    st: dict[int, str] = {}
    while time.monotonic() - t0 < DRY_SETTLE_S:
        con = w.sql()
        try:
            st = dict(con.execute("SELECT id, status FROM scheduled_jobs WHERE id IN (%s)"
                                  % ",".join("?" * len(ids)), ids).fetchall()) if ids else {}
        finally:
            con.close()
        if all(x in ("done", "error", "cancelled") for x in st.values()) and len(st) == len(ids):
            break
        await tick_http.post("/__slop/automation-tick", timeout=600)
    return st


def _check_no_send(ctx, aids, jobs, stats, status, before, after, *, enq_bad, list_writes, seconds) -> None:
    bad: dict[str, list] = {"enqueue": enq_bad, "job_not_done": [], "queue_frame": [], "runs": [],
                            "not_dry": [], "list_write": list_writes[:5]}
    for jid, st in status.items():
        if st != "done":
            bad["job_not_done"].append((jid, st))
    for aid in aids:
        if after["queue"][aid] != before["queue"][aid]:
            bad["queue_frame"].append((aid, before["queue"][aid], after["queue"][aid]))
        n_jobs = sum(1 for j in jobs if j["aid"] == aid)
        if len(stats[aid]) != n_jobs:
            bad["runs"].append((aid, len(stats[aid]), n_jobs))
        for x in stats[aid]:
            if x.get("dry_run") is not True or x.get("sent") != 0 or x["status"] != "ok":
                bad["not_dry"].append((aid, {k: x.get(k) for k in ("status", "dry_run", "sent", "reason")}))
    ctx.check(DRY_NO_SEND, not any(bad.values()) and after["mass_runs"] == before["mass_runs"]
              and after["out_rows"] == before["out_rows"],
              dry_runs=len(jobs), seconds=round(seconds, 2), list_writes=len(list_writes),
              mass_runs=(before["mass_runs"], after["mass_runs"]), out_rows=(before["out_rows"], after["out_rows"]),
              counts={k: len(v) for k, v in bad.items()}, sample={k: v[:3] for k, v in bad.items() if v})


def _check_list(ctx, aids, lists, jobs, stats, wire) -> None:
    """`wire`: {aid: (the real send's userIds, its queue frames)}."""
    bad: dict[str, list] = {"list": [], "list_empty": [], "explicit": [], "explicit_runs": [],
                            "explicit_vs_wire": [], "wire": []}
    for aid in aids:
        runs, (wire_ids, wire_n) = stats[aid], wire[aid]
        got = sorted(tuple(x.get("would_send") or ()) for x in runs if x.get("audience") == "list")
        exp = sorted(tuple(sorted(_want(lists, aid, j["payload"]["excluded_users"]))) for j in jobs
                     if j["aid"] == aid and j["kind"] == "list")
        if got != exp:
            bad["list"].append((aid, [list(g)[:6] for g in got[:2]], [list(e)[:6] for e in exp[:2]]))
        if any(not e for e in exp):
            bad["list_empty"].append(aid)
        w_exp = _want(lists, aid, lists[aid]["ex_exp"])
        n_exp = sum(1 for j in jobs if j["aid"] == aid and j["kind"] == "explicit")
        if sum(1 for x in runs if x.get("audience") == "explicit") != n_exp:
            bad["explicit_runs"].append((aid, n_exp))
        for x in runs:
            if x.get("audience") == "explicit" and x.get("would_send") != w_exp:
                bad["explicit"].append((aid, (x.get("would_send") or [])[:6], w_exp[:6]))
            if x.get("audience") == "explicit" and x.get("would_send") != wire_ids:
                bad["explicit_vs_wire"].append((aid, (x.get("would_send") or [])[:6], wire_ids[:6]))
        if wire_n != 1:
            bad["wire"].append((aid, wire_n))
    ctx.check(DRY_LIST, not any(bad.values()),
              list_runs=sum(1 for j in jobs if j["kind"] == "list"),
              explicit_runs=sum(1 for j in jobs if j["kind"] == "explicit"),
              roster=len(next(iter(lists.values()))["roster"]) if lists else 0,
              counts={k: len(v) for k, v in bad.items()}, sample={k: v[:3] for k, v in bad.items() if v})
