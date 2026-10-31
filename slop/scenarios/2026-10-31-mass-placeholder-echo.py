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
multi-line caption to its own PER_RUN fans (run 0's include the BOTH fans). Then OF's chat
list (`FakeOF.chats`) shows every recipient's copy of its run as the last message, its text
as OF echoes it (`\\n` -> `<br />\\n`, created a second after the send), and every STALE fan a
Creator's own OF-web send of run 0's caption, now. `--users` open inboxes, as the app's
`useChatList` drives them: each has scrolled to one (Creator, page) and loads it once
(`GET /api/of/v2/chats?limit=50&offset=..`, a relay-cache miss, so a fresh OF read and one
reconcile), then head-polls page 0 every POLL_S without `refresh` (`useHeadPagePoll`: 90 s,
`refresh=false`, rides the relay cache), until every fresh stub is gone or SETTLE_S passes.

Checks: every send answered 200 and left one stub per recipient (SENT); PH_ONCE
(lib/attribution_pair_faults.py): per recipient its stub is gone, OF's row carries its run,
one out row and one thread bubble (`GET /admin/messages/{aid}/{fan}`) hold that caption; per
BOTH fan the 2-day-old stub is still there; per STALE fan the 2-day-old stub is still there
and OF's row carries no run. Budgets: echo visible -> every stub adopted (E2E_SETTLE_MS),
route p95s, p95 vs the last green run.

Bypasses (declared): lib/of_wire.py is OnlyFans (its own declared bypasses; the queue answer
`{id, text, createdAt}` is a guess, which is what makes every recipient a placeholder; no 10 s
broadcast throttle); OF's chat list is set by the scenario, one item per recipient, its
`<br />` echo shape the one test_placeholder_adopt pins; the inbox clients are httpx pools, not
browsers, and model only the page-load + head poll (no SSE, no manual Refresh); the stale run is SQL in the product's shape (no actor can send 2 days ago).
Break-it-once: placeholder-pair-ignores-window (the 6 h bound dropped: only PH_ONCE).
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from slop.lib.attribution_pair_faults import PH_ONCE
from slop.seed import mass_placeholders, of_sessions

sys.path.append(str(Path(__file__).resolve().parents[2] / "service"))   # the pairing key, pure
from attribution_pair import _norm_body  # noqa: E402

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "placeholder-pair-ignores-window"
RUNS = 3
PER_RUN = {"small": 10, "medium": 60, "huge": 150}   # fresh recipients per run, per Creator
STALE = {"small": 4, "medium": 20, "huge": 40}       # 2-day-old stub, OF-web send of its caption now
BOTH = {"small": 2, "medium": 10, "huge": 20}        # 2-day-old stub AND in run 0
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
P95_MS = {"GET /api/of/v2/chats": 2000, "POST /api/of/v2/messages/queue": 3000,
          "GET /admin/messages/:id/:id": 1000}
P95_VS_LAST = (1.5, 500)

SENT = "every broadcast answered 200 and left one placeholder per recipient"


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
    n_run, n_stale, n_both = PER_RUN[ctx.scale], STALE[ctx.scale], BOTH[ctx.scale]
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
        plan[aid] = {"runs": runs, "stale": stale, "both": runs[0][:n_both], "run_ids": [None] * RUNS}
    old = w.now - STALE_AGE
    stale_runs = mass_placeholders.seed(w, {aid: plan[aid]["stale"] + plan[aid]["both"] for aid in aids},
                                        lambda aid: caption(aid, 0), old)

    # ── the broadcasts, through the composer's route ────────────────────────
    owner = ctx.owner.share(limits=len(aids) + 4)
    send_bad: list = []

    async def creator_sends(aid: str) -> None:
        for k, fans in enumerate(plan[aid]["runs"]):
            r = await owner.post("/api/of/v2/messages/queue", headers={"X-Account-Id": aid},
                                 json={"text": caption(aid, k), "user_ids": fans})
            body = r.json() if r.status_code == 200 else {}
            plan[aid]["run_ids"][k] = body.get("_mass_run_id")
            if r.status_code != 200 or body.get("_mass_run_id") is None:
                send_bad.append({"aid": aid, "run": k, "status": r.status_code, "body": r.text[:200]})

    t_send = time.perf_counter()
    await asyncio.gather(*(creator_sends(a) for a in aids))
    send_s = time.perf_counter() - t_send

    def stub_counts() -> dict[tuple[str, int], int]:
        con = w.sql()
        try:
            return {(str(a), int(r)): n for a, r, n in con.execute(
                "SELECT account_id, mass_run_id, COUNT(*) FROM messages WHERE message_id >= ? AND message_id < ? "
                "GROUP BY account_id, mass_run_id", (mass_placeholders.PLACEHOLDER_BASE, mass_placeholders.PLACEHOLDER_CEIL))}
        finally:
            con.close()

    stubs = stub_counts()
    got = {f"{aid}:{k}": stubs.get((aid, int(rid)), 0) for aid in aids
           for k, rid in enumerate(plan[aid]["run_ids"]) if rid is not None}
    short = {k: v for k, v in got.items() if v != n_run}
    ctx.check(SENT, not send_bad and not short, sends=RUNS * len(aids), bad=send_bad[:5], stubs_off=short,
              seconds=round(send_s, 2))
    if send_bad or short:
        ctx.skip(PH_ONCE, "the broadcasts did not leave their placeholders (SENT)")
        await owner.aclose()
        return

    # ── OF's chat list: every recipient's copy, every stale fan's OF-web send ──
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) + timedelta(seconds=1)
    echo: dict[tuple[str, int], dict] = {}   # (aid, fan) -> {id, text, run k or None}
    n = 0
    for aid in aids:
        items = []
        groups = [(k, f) for k, fans in enumerate(plan[aid]["runs"]) for f in fans] + \
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
            left = sum(stub_counts().get(k, 0) for k in fresh_ids)
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

    keys = [(aid, fid) for aid in aids for fid in [f for fans in plan[aid]["runs"] for f in fans]]
    seen = dict(zip(keys, await asyncio.gather(*(bubbles(a, f) for a, f in keys))))
    await reader.aclose()

    bad: dict[str, list] = {"stub_left": [], "echo_not_stamped": [], "dup_rows": [], "dup_bubbles": [],
                            "old_stub_adopted": [], "stale_send_stamped": []}
    for aid in aids:
        p, old_ph = plan[aid], mass_placeholders.PLACEHOLDER_BASE + stale_runs[aid]
        for k, fans in enumerate(p["runs"]):
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
    routes = ctx.rec.summary()
    for route, budget in P95_MS.items():
        if route in routes:
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"])
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")
    ctx.metric("load", {"creators": len(aids), "runs": RUNS, "per_run": n_run, "stale": n_stale, "both": n_both,
                        "inbox_clients": len(clients), "chat_reads": reads[0], "send_s": round(send_s, 2),
                        "settle_ms": round(settle_ms) if settle_ms is not None else None})
    ctx.metric("p95_vs_last_green", {**{r: routes[r]["p95_ms"] for r in P95_MS if r in routes},
                                     **({"echo -> adopted": round(settle_ms)} if settle_ms is not None else {})})
    await owner.aclose()
