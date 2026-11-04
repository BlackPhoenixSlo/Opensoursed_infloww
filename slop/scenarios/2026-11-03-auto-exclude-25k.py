"""A Creator's Auto_Exclude past OF's 20k paging backstop (service/audiences.py `ensure_exclude_list`,
service/auto_exclude_decide.py): every list-audience send still excludes its whole contact guard, but
syncs only the ids its mirror lacks; stale members go in a background refresh, single-flight per
Creator, one short `broadcast_lock` hold per batch. A list under the backstop keeps today's crawl +
adds + removes on every send.

World: `agency_inbox` plus seed/auto_exclude_guard.py: big Creators (SCALES
`auto_exclude_big_creators`) with a pre-made Auto_Exclude of `--ae_members` (SCALES
`auto_exclude_members`, past 20k) and one control Creator (the last; `--ae_control_members`, SCALES
`auto_exclude_control_members`, under it). Per Creator a guard (outbound 10-240 min ago, inside the 6 h
window), stale members (out of every window), open fans (never messaged) and, on a big Creator,
REFUSED guard ids OF will not list. OF's side (roster, lists, adds, sends) is lib/auto_exclude_relay.py
on the lane's offline client.

Drive: one cold send per Creator (`/__slop/run-automation`, payload: the warm-up); then `--users`
list-audience sends (`user_lists ["fans"]`, each naming CHURN pool ids in `excluded_users`, so the
guard moves) enqueued through the real `POST /admin/automation/enqueue` at seeded offsets over
LOAD_S, round-robin big..., control; one driver per Creator claims them (`/__slop/run-automation
{claim: true}`: the product's claim, run slot, `run_once`, per-(account, kind) lock and write gate).

Racing them, composer blasts: per Creator `max(MANUAL_PAIRS_MIN, users // MANUAL_USERS_PER_PAIR)` pairs at
seeded offsets, both of a pair at once (two chatters on one Creator). A chatter blasts again only once its
last blast answered; none begins past the drain deadline. Each is the composer's real `POST
/api/of/v2/messages/queue` (owner session, X-Account-Id): `user_lists ["fans"]`, the guard windows
(`exclude_replied_hours` / `exclude_inbound_hours` = GUARD_H, as the automations' guard) and MANUAL_K picks in
`excluded_users`. The picks come from the Creator's MANUAL_POOL lowest-id fans outside the guard (outside the
churn pools first), the two of a pair disjoint. The next send's sync (small list) or the next refresh batch (big
list, ascending removes) takes them off Auto_Exclude, so a blast not holding the lock through its POST loses them.

Once the first big Creator's first refresh ended (during the load; a slow one: after it, before the
settle), DROP_N of its guard members are dropped on OF's side (`/__slop/auto-exclude/drop`). After
the load drains, each big Creator settles: no refresh running,
REFRESH_EVERY_S + 1 s quiet, one send (run-automation, no churn) that schedules a refresh, that
refresh awaited, OF's list read.

Checks (names in lib/auto_exclude_faults.py):
  NO_EXCLUDED_SENT  per OF accept, no recipient was in the send's own `excluded_users` (the product's
                    guard), its churn, or the seeded contact guard at that time (DB oracle; within
                    EDGE_S of a window edge: either way), bar REFUSED ids and the dropped ids from the
                    drop until the end of the first refresh that began after it.
  SEND_LATENCY      budget: big Creators' enqueue -> OF accept p95 <= SEND_P95_S and <= control p95 x
                    VS_CONTROL[0] + VS_CONTROL[1] s; a send not accepted by the drain deadline counts
                    at the deadline.
  CONVERGES         per big Creator after its settle refresh: guard (DB, bar edge) - refused <= list;
                    list ∩ roster <= guard ∪ edge; no stale member past sorted index 20k left; that
                    refresh read > 20k.
  SINGLE_FLIGHT     refresh_begin / refresh_end alternate per Creator, >= 1 refresh per big Creator.
  EXTERNAL_READD    the first refresh that began after the drop re-adds every dropped id a send had
                    not re-added before it began (none re-added by a send after it began); all members
                    again at its end.
  SMALL_EXACT       the control's list at every automation accept == that send's `excluded_users` and
                    holds its DB guard and churn; no refresh for it.
  MANUAL_NO_EXCLUDED_SENT  NO_EXCLUDED_SENT's oracle over the composer blasts OF accepted (picks for
                    churn), >= 1 accepted per Creator. Its own check (NO_EXCLUDED_SENT and SMALL_EXACT
                    read automation sends only), so the composer route's fault reddens it alone. A blast
                    not begun or not answered 200 is info only (5xx / transport: the stock check).
P95_VS_LAST over the control's enqueue -> accept p95, `POST /admin/automation/enqueue` and the composer's
`POST /api/of/v2/messages/queue` (the big
Creators' p95 is SEND_LATENCY's, a fault's target).

Bypasses (declared): OF is faked at the lane's client (lib/auto_exclude_relay.py: PAGE_MS a list page,
ADD_MS an add / remove, ACCEPT_MS an accept: guesses); the 11 s per-Creator write gap compressed to
GAP_S and the refresh cadence to REFRESH_EVERY_S (the rules the product's); the supervisor's cadence
(a driver per Creator claims its next due job); the composer's client answers through the lane's
(lib/auto_exclude_relay.py wraps `server._load_client`: one OF account); the composer blast sets the guard windows (the
composer's default sends none: then the refresh would reconcile the big list to a blast's few picks); the warm-up and settle sends' queue claim (run-automation with a payload); the drop is
an operator edit on OF (no product call).
Break-it-once: `auto-exclude-refresh-blocks-send` (FAULT: the send runs the refresh inline):
SEND_LATENCY; `auto-exclude-remove-unlocked` (batches unlocked, against the guard read at refresh
start): NO_EXCLUDED_SENT; `auto-exclude-refresh-skips-readd`: EXTERNAL_READD;
`auto-exclude-readds-whole-guard` (a big send re-adds its whole guard): SEND_LATENCY;
`auto-exclude-manual-lock-early` (the composer releases `broadcast_lock` after the sync, pre-W24):
MANUAL_NO_EXCLUDED_SENT.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone

import httpx

from slop.lib.auto_exclude_faults import (CONVERGES, EXTERNAL_READD, MANUAL_NO_EXCLUDED_SENT, NO_EXCLUDED_SENT,
                                          SEND_LATENCY, SINGLE_FLIGHT, SMALL_EXACT)
from slop.lib.auto_exclude_relay import read_journal
from slop.seed import auto_exclude_guard as aeg

PROFILE = "agency_inbox"
UI = False
FAULT = "auto-exclude-refresh-blocks-send"
P95_VS_LAST = (1.5, 500)
PAGE_MS = 20                  # OF list page (guess)
ADD_MS = 3                    # OF add / remove one user (guess)
ACCEPT_MS = 400               # OF accepting a mass message (guess)
GAP_S = 0.3                   # the 11 s per-Creator write gap, compressed
REFRESH_EVERY_S = 8.0         # auto_exclude_decide.REFRESH_EVERY_S (600 s), compressed
SEND_P95_S = 5.0
VS_CONTROL = (1.5, 2.0)
LOAD_S_PER_SEND, LOAD_S_MIN = 0.75, 30.0   # under both kinds of Creator's send rate (no queue)
DRAIN_S = 240.0
SETTLE_S = 300.0
GUARD_H = {"out": 6, "in": 2}   # audiences.BROADCAST_DEFAULT_OUTBOUND_H / _INBOUND_H
EDGE_S = 120
BACKSTOP = 20_000             # of_paging.MAX_PAGES x LIST_PAGE
REFUSED = 4
POOL = {"stale": 300, "open": 60}
CHURN = {"stale": 30, "open": 5}
DROP_N = 5
TEXT = "slop ae {}"
MANUAL_PAIRS_MIN = 3          # composer blast pairs per Creator: max(MIN, users // USERS_PER_PAIR)
MANUAL_USERS_PER_PAIR = 20
MANUAL_K = 5                  # picks per composer blast
MANUAL_POOL = 40              # lowest-id fans outside the guard a blast picks from
MANUAL_TEXT = "slop ae manual {}"
QUEUE = "/api/of/v2/messages/queue"


def _epoch(s: str) -> float:
    return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc).timestamp()


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    return ys[max(0, math.ceil(0.95 * len(ys)) - 1)]


def _window(last: dict[str, dict[int, float]], f: int, t: float) -> str | None:
    """Fan `f` in the contact guard at `t`: "certain", "edge" (within EDGE_S of a window's edge in
    some window, certain in none) or None."""
    best = None
    for d, h in GUARD_H.items():
        at = last[d].get(f)
        if at is None:
            continue
        m = at - (t - h * 3600)
        if m >= EDGE_S:
            return "certain"
        if m > -EDGE_S:
            best = "edge"
    return best


def _p50(xs: list[float]) -> float | None:
    return sorted(xs)[len(xs) // 2] if xs else None


def _guard_at(last: dict[str, dict[int, float]], t: float) -> tuple[set[int], set[int]]:
    """The contact guard at `t`: (certain, edge), by `_window`."""
    out: dict[str | None, set[int]] = {"certain": set(), "edge": set(), None: set()}
    for f in set().union(*last.values()):
        out[_window(last, f, t)].add(f)
    return out["certain"], out["edge"]


def _drop_window(refreshes: list[dict], aid: str, t_drop: float | None) -> tuple[dict | None, dict | None]:
    """(begin, end) of `aid`'s first refresh that began at or after the drop; None where missing."""
    if t_drop is None:
        return None, None
    ev = [e for e in refreshes if e["account_id"] == aid]
    k = next((k for k, e in enumerate(ev) if e["ev"] == "refresh_begin" and e["t"] >= t_drop), None)
    if k is None:
        return None, None
    return ev[k], next((e for e in ev[k + 1:] if e["ev"] == "refresh_end"), None)


def _check_no_excluded_sent(sends, by_text, last, refused, drop) -> tuple[bool, dict]:
    """`drop`: (account, dropped ids, t_drop, window end) or None. Returns (ok, info) + tolerated."""
    bad, tolerated = [], 0
    for e in sends:
        aid, t = e["account_id"], e["t"]
        p = by_text.get(e["text"])
        churn = set(p["churn"]) if p else set()
        hit = set(e["leak_excl"]) | {f for f in e["leak"] if f in churn or _window(last[aid], f, t) == "certain"}
        hit -= refused[aid]
        if drop and aid == drop[0] and drop[2] <= t <= drop[3]:
            tolerated += len(hit & drop[1])
            hit -= drop[1]
        if hit:
            bad.append({"text": e["text"], "account": aid[-4:], "n": len(hit), "ids": sorted(hit)[:5],
                        "in_excl": len(hit & set(e["leak_excl"]))})
    ok = bool(sends) and {e["account_id"] for e in sends} >= set(last) and not bad
    return ok, {"sends": len(sends), "bad_sends": len(bad), "bad": bad[:10], "tolerated_dropped": tolerated,
                "bad_by_account": dict(Counter(b["account"] for b in bad))}


def _check_manual(manual, accepted, last, refused, drop) -> tuple[bool, dict]:
    """NO_EXCLUDED_SENT's oracle over the composer blasts OF accepted (their picks as churn), >= 1 per
    Creator (its coverage floor). Not begun / not 200: info only."""
    sends = [accepted[m["text"]] for m in manual if m["text"] in accepted]
    ok, info = _check_no_excluded_sent(sends, {m["text"]: {"churn": m["picks"]} for m in manual}, last, refused, drop)
    off = [m["text"] for m in manual if m["text"] not in accepted]
    return ok, {**info, "blasts": len(manual), "not_accepted": len(off), "not_accepted_texts": off[:5],
                "http": dict(Counter(str(m["http"]) for m in manual))}


def _latencies(plan, accepted, control, t_drained) -> tuple[dict[str, list[float]], list[str]]:
    """Enqueue -> OF accept per send, big vs control; an unaccepted send counts at `t_drained`."""
    lat: dict[str, list[float]] = {"big": [], "control": []}
    unaccepted = []
    for p in plan:
        e = accepted.get(p["text"])
        if e is None:
            unaccepted.append(p["text"])
        if "t_enq" in p:
            lat["control" if p["aid"] == control else "big"].append((e["t"] if e else t_drained) - p["t_enq"])
    return lat, unaccepted


def _check_send_latency(lat, unaccepted) -> tuple[bool, dict]:
    p95_big, p95_ctl = _p95(lat["big"]), _p95(lat["control"])
    limit = None if p95_ctl is None else p95_ctl * VS_CONTROL[0] + VS_CONTROL[1]
    ok = p95_big is not None and limit is not None and p95_big <= SEND_P95_S and p95_big <= limit
    r2 = (lambda x: None if x is None else round(x, 2))
    return ok, {"p95_big_s": r2(p95_big), "p95_control_s": r2(p95_ctl), "limit_s": r2(limit),
                "budget_s": SEND_P95_S, "n_big": len(lat["big"]), "n_control": len(lat["control"]),
                "unaccepted": len(unaccepted)}


def _check_converges(settled, last, ae) -> tuple[bool, dict]:
    conv, conv_ok = {}, True
    for aid, s in settled.items():
        mem, ref = s["members"], s["refresh"]
        certain, edge = _guard_at(last[aid], s["t"])
        missing = (certain - ae[aid]["refused"]) - mem
        extra = (mem & ae[aid]["roster"]) - certain - edge
        past = sorted(ae[aid]["members"])[BACKSTOP:]
        stale_left = [f for f in past if f in ae[aid]["stale"] and f in mem]
        crawled = ((ref or {}).get("stats") or {}).get("crawled", 0)
        ok = (s["send"]["http"] == 200 and ref is not None and not ref.get("err") and not missing and not extra
              and not stale_left and crawled > BACKSTOP)
        conv_ok &= ok
        conv[aid[-4:]] = {"members": len(mem), "guard": len(certain), "edge": len(edge), "missing": sorted(missing)[:5],
                          "n_missing": len(missing), "extra": sorted(extra)[:5], "n_extra": len(extra),
                          "stale_past_20k_left": len(stale_left), "refresh_crawled": crawled,
                          "settle_send": s["send"], "refresh_err": (ref or {}).get("err")}
    return conv_ok, conv


def _check_single_flight(accounts, control, refreshes) -> tuple[bool, dict]:
    sf, sf_ok = {}, True
    for aid in accounts:
        seq = [e["ev"] for e in refreshes if e["account_id"] == aid]
        alt = all(x == ("refresh_begin" if k % 2 == 0 else "refresh_end") for k, x in enumerate(seq))
        n_ref = seq.count("refresh_begin")
        sf[aid[-4:]] = {"refreshes": n_ref, "alternate": alt}
        sf_ok &= alt and (n_ref >= 1 or aid == control)
    return sf_ok, sf


def _check_external_readd(journal, aid, drop, drop_ids, window) -> tuple[bool, dict]:
    """Each dropped id is put back by the first refresh after the drop, unless a send had already put
    it back before that refresh began (nothing left for it then); a send putting it back after the
    refresh began means the refresh left it."""
    t_drop = drop.get("t")
    if t_drop is None:
        return False, {"why": "no drop: big[0]'s first refresh never ended during the load"}
    begin, end = window
    first_add: dict[int, dict] = {}
    for e in journal:
        if e["ev"] == "add" and e["ok"] and e["account_id"] == aid and e["t"] >= t_drop:
            first_add.setdefault(e["uid"], e)
    back = set((end or {}).get("dropped_back") or [])
    left = [f for f in drop_ids if begin is None or end is None or f not in first_add
            or first_add[f]["t"] > end["t"]
            or (first_add[f]["via"] != "refresh" and first_add[f]["t"] >= begin["t"])]
    ok = begin is not None and end is not None and drop.get("dropped") == drop_ids and not left and back >= set(drop_ids)
    return ok, {"dropped": drop.get("dropped"), "left_by_refresh": left, "members_again": sorted(back),
                "readded": {f: first_add[f]["via"] for f in drop_ids if f in first_add},
                "window_s": round(end["t"] - t_drop, 2) if end else None}


def _check_small_exact(sends, control, by_text, last_ctl, roster_ctl, refreshes) -> tuple[bool, dict]:
    ctl_sends = [e for e in sends if e["account_id"] == control]
    off = []
    for e in ctl_sends:
        mem = set(e.get("members") or [])
        p = by_text.get(e["text"])
        certain, _edge = _guard_at(last_ctl, e["t"])
        want_in = (certain & roster_ctl) | (set(p["churn"]) if p else set())
        if mem != set(e.get("excl") or []) or not want_in <= mem:
            off.append({"text": e["text"], "members": len(mem), "excl": len(e.get("excl") or []),
                        "missing": sorted(want_in - mem)[:5], "vs_excl": sorted(mem ^ set(e.get("excl") or []))[:5]})
    n_ref = sum(1 for e in refreshes if e["account_id"] == control)
    return bool(ctl_sends) and not off and n_ref == 0, {"sends": len(ctl_sends), "off": off[:5],
                                                         "n_off": len(off), "refreshes": n_ref}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    cs = [c["id"] for c in creators]
    big = cs[:int(w.size["auto_exclude_big_creators"])]
    control = cs[-1]
    n_big = ctx.param("ae_members", int(w.size["auto_exclude_members"]))
    n_ctl = ctx.param("ae_control_members", int(w.size["auto_exclude_control_members"]))
    sizes = {**{a: n_big for a in big}, control: n_ctl}
    ae = aeg.seed(w, creators, sizes, {a: REFUSED for a in big})
    rng = w.rng("scenario:auto-exclude")
    tmp = ctx.stack.tmp

    def q(sql: str, args=()) -> list[tuple]:
        con = w.sql()
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    last = {aid: {d: {int(f): _epoch(at) for f, at in q(
        "SELECT fan_id, MAX(created_at) FROM messages WHERE account_id=? AND direction=? GROUP BY fan_id", (aid, d))}
        for d in GUARD_H} for aid in sizes}
    pools = {aid: {k: rng.sample(sorted(ae[aid][k]), min(POOL[k], len(ae[aid][k]))) for k in POOL} for aid in sizes}
    watch = {aid: ae[aid]["guard"] | set(pools[aid]["stale"]) | set(pools[aid]["open"]) for aid in sizes}
    churned = {aid: set(pools[aid]["stale"]) | set(pools[aid]["open"]) for aid in sizes}
    mpool = {aid: sorted(ae[aid]["roster"] - ae[aid]["guard"], key=lambda f, a=aid: (f in churned[a], f))[:MANUAL_POOL]
             for aid in sizes}

    # OF's side: lib/automation_relay.py's lists (no per-call sleep: ours is PAGE_MS), our roster and sends.
    (tmp / "of-mass.json").write_text(json.dumps({"list_s": 0}))
    (tmp / "auto-exclude.json").write_text(json.dumps({
        "page_ms": PAGE_MS, "add_ms": ADD_MS, "accept_ms": ACCEPT_MS, "gap_s": GAP_S,
        "refresh_every_s": REFRESH_EVERY_S,
        "accounts": {aid: {"roster": sorted(ae[aid]["roster"]), "members": sorted(ae[aid]["members"]),
                           "refuse": sorted(ae[aid]["refused"]), "watch": sorted(watch[aid]),
                           "exact": aid == control} for aid in sizes}}))
    r = await ctx.owner.post("/__slop/auto-exclude/arm")
    r.raise_for_status()
    lids = {aid: int(v) for aid, v in r.json()["lists"].items()}
    ctx.metric("setup", {"big": {a[-4:]: n_big for a in big}, "control": n_ctl, "lists": len(lids),
                         "guard": {a[-4:]: len(ae[a]["guard"]) for a in sizes},
                         "stale": {a[-4:]: len(ae[a]["stale"]) for a in sizes}})

    def journal() -> list[dict]:
        return read_journal(tmp)

    async def counts() -> dict:
        r = await ctx.owner.get("/__slop/auto-exclude")
        r.raise_for_status()
        return r.json()["counts"]

    async def run_send(aid: str, text: str, churn: list[int]) -> dict:
        """A send through run_once with a payload; retried while the pair's run is in flight."""
        t0 = time.perf_counter()
        while True:
            r = await ctx.owner.post("/__slop/run-automation", timeout=900, json={
                "account_id": aid, "kind": "send_mass_message",
                "payload": {"text": text, "user_lists": ["fans"], "excluded_users": churn}})
            res = (r.json().get("result") or {}) if r.status_code == 200 else {"status": f"http {r.status_code}"}
            if res.get("reason") != "in_flight":
                return {"http": r.status_code, "status": res.get("status"), "reason": res.get("reason"),
                        "ms": round((time.perf_counter() - t0) * 1000)}
            await asyncio.sleep(0.2)

    # ── Warm-up: each Creator's first (cold) send ──────────────────────────────
    ctx.rec.stage = "warm"
    warm = dict(zip(sizes, await asyncio.gather(*(run_send(a, TEXT.format(f"warm {i}"), [])
                                                  for i, a in enumerate(sizes)))))
    c_warm = await counts()
    ctx.rec.stage = None
    cold = {a[-4:]: {"send_ms": warm[a]["ms"], "status": warm[a]["status"],
                     "pages": c_warm.get(a, {}).get("pages", 0),
                     "adds": c_warm.get(a, {}).get("adds_send", 0),
                     "refused": c_warm.get(a, {}).get("refused_send", 0)} for a in sizes}

    # ── Load ────────────────────────────────────────────────────────────────
    n = max(1, ctx.users)
    load_s = max(LOAD_S_MIN, LOAD_S_PER_SEND * n)
    order = [*big, control]
    plan = []
    for i in range(n):
        aid = order[i % len(order)]
        churn = sorted(rng.sample(pools[aid]["stale"], min(CHURN["stale"], len(pools[aid]["stale"])))
                       + rng.sample(pools[aid]["open"], min(CHURN["open"], len(pools[aid]["open"]))))
        plan.append({"aid": aid, "text": TEXT.format(i), "at": rng.uniform(0, load_s), "churn": churn})
    by_text = {p["text"]: p for p in plan}
    drop_ids = sorted(rng.sample(sorted(ae[big[0]]["members"] & ae[big[0]]["guard"]), DROP_N))
    mrng = w.rng("scenario:auto-exclude:manual")
    manual: list[dict] = []
    for aid in order:
        for _k in range(max(MANUAL_PAIRS_MIN, n // MANUAL_USERS_PER_PAIR)):
            at = mrng.uniform(0, load_s)
            a = mrng.sample(mpool[aid], MANUAL_K)
            b = mrng.sample([f for f in mpool[aid] if f not in a], MANUAL_K)
            for chatter, picks in enumerate((a, b)):
                manual.append({"aid": aid, "chatter": chatter, "text": MANUAL_TEXT.format(len(manual)), "at": at,
                               "picks": sorted(picks), "http": None})
    manual_texts = {m["text"] for m in manual}
    stop = asyncio.Event()
    drive_http = ctx.owner.share(limits=len(sizes) + 1)
    enq_http = ctx.owner.share(limits=64)
    man_http = ctx.owner.share(limits=64)
    drop: dict = {}

    async def driver(aid: str) -> None:
        """The supervisor's dispatch for one Creator: claim its earliest due send, run it, again."""
        while not stop.is_set():
            try:
                r = await drive_http.post("/__slop/run-automation", timeout=900, json={
                    "account_id": aid, "kind": "send_mass_message", "claim": True})
                res = (r.json().get("result") or {}) if r.status_code == 200 else {}
            except httpx.HTTPError:
                res = {}        # recorded (599): the stock transport check
            if res.get("status") in (None, "skipped", "no_job") or res.get("reason") in ("no_job", "in_flight"):
                await asyncio.sleep(0.1)

    async def enqueue(p: dict, t0: float) -> None:
        await asyncio.sleep(max(0.0, t0 + p["at"] - time.monotonic()))
        p["t_enq"] = time.time()
        r = await enq_http.post("/admin/automation/enqueue", json={
            "account_id": p["aid"], "kind": "send_mass_message",
            "payload": {"text": p["text"], "user_lists": ["fans"], "excluded_users": p["churn"]}})
        p["enq_http"] = r.status_code

    async def chatter(ms: list[dict], t0: float, deadline: float) -> None:
        """One chatter's composer blasts in `at` order, each once the last one answered (the composer
        waits on its send); none begun past the drain deadline."""
        for m in sorted(ms, key=lambda m: m["at"]):
            await asyncio.sleep(max(0.0, t0 + m["at"] - time.monotonic()))
            if time.monotonic() >= deadline:
                continue    # not begun: http stays None
            await blast(m, deadline)

    async def blast(m: dict, deadline: float) -> None:
        """One composer blast: the real route, its picks plus the guard windows."""
        try:
            r = await man_http.post(QUEUE, headers={"X-Account-Id": m["aid"]},
                                    timeout=max(1.0, deadline - time.monotonic()), json={
                                        "text": m["text"], "user_lists": ["fans"], "excluded_users": m["picks"],
                                        "exclude_replied_hours": GUARD_H["out"],
                                        "exclude_inbound_hours": GUARD_H["in"]})
            m["http"] = r.status_code
        except httpx.HTTPError:
            pass        # http stays None: the stock transport check records it

    async def dropper(t_load: float, deadline: float) -> None:
        aid = big[0]
        while time.monotonic() < deadline:
            if any(e["ev"] == "refresh_end" and e["account_id"] == aid and e["t"] >= t_load for e in journal()):
                r = await ctx.owner.post("/__slop/auto-exclude/drop", json={"account_id": aid, "ids": drop_ids})
                r.raise_for_status()
                drop.update(r.json())
                return
            await asyncio.sleep(0.2)

    ctx.rec.stage = "load"
    t_load, t0 = time.time(), time.monotonic()
    deadline = t0 + load_s + DRAIN_S
    drivers = [asyncio.create_task(driver(a)) for a in sizes]
    dropping = asyncio.create_task(dropper(t_load, deadline + SETTLE_S))   # a slow first refresh: after the load
    chatters: dict[tuple, list[dict]] = {}
    for m in manual:
        chatters.setdefault((m["aid"], m["chatter"]), []).append(m)
    blasts = [asyncio.create_task(chatter(ms, t0, deadline)) for ms in chatters.values()]
    await asyncio.gather(*(enqueue(p, t0) for p in plan))
    while time.monotonic() < deadline:
        done = {e["text"] for e in journal() if e["ev"] == "send"}
        if all(p["text"] in done for p in plan) and all(b.done() for b in blasts):
            break
        await asyncio.sleep(1.0)
    t_drained = time.time()
    stop.set()
    for b in blasts:
        b.cancel()
    await asyncio.gather(*blasts, return_exceptions=True)
    await asyncio.gather(*drivers)
    await dropping
    c_load = await counts()
    ctx.rec.stage = None

    # ── Settle: quiet, one send per big Creator, its refresh awaited ─────────
    async def settle(i: int, aid: str) -> dict:
        end = time.monotonic() + SETTLE_S

        def refreshes() -> list[dict]:
            return [e for e in journal() if e["account_id"] == aid and e["ev"] in ("refresh_begin", "refresh_end")]

        while time.monotonic() < end:
            ev = refreshes()
            if sum(e["ev"] == "refresh_begin" for e in ev) == sum(e["ev"] == "refresh_end" for e in ev):
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(REFRESH_EVERY_S + 1)
        t_s = time.time()
        res = await run_send(aid, TEXT.format(f"settle {i}"), [])
        out = {"t": t_s, "send": res, "refresh": None}
        while time.monotonic() < end:
            ev = refreshes()
            began = [k for k, e in enumerate(ev) if e["ev"] == "refresh_begin" and e["t"] >= t_s]
            ended = [e for e in ev[began[0]:] if e["ev"] == "refresh_end"] if began else []
            if ended:
                out["refresh"] = ended[0]
                break
            await asyncio.sleep(0.5)
        r = await ctx.owner.get(f"/__slop/auto-exclude/members?account_id={aid}")
        r.raise_for_status()
        out["members"] = set(r.json()["members"])
        return out

    ctx.rec.stage = "settle"
    settled = dict(zip(big, await asyncio.gather(*(settle(i, a) for i, a in enumerate(big)))))
    ctx.rec.stage = None
    c_end = await counts()
    for h in (drive_http, enq_http, man_http):
        await h.aclose()

    # ── Verdicts ──────────────────────────────────────────────────────────────
    J = journal()
    sends = [e for e in J if e["ev"] == "send"]
    accepted = {e["text"]: e for e in sends}
    refreshes = [e for e in J if e["ev"] in ("refresh_begin", "refresh_end")]
    t_drop = drop.get("t")
    window = _drop_window(refreshes, big[0], t_drop)
    w_end = window[1]["t"] if window[1] else math.inf
    refused = {a: ae[a]["refused"] for a in sizes}
    drop_w = (big[0], set(drop_ids), t_drop, w_end) if t_drop is not None else None
    auto_sends = [e for e in sends if e["text"] not in manual_texts]
    ok, info = _check_no_excluded_sent(auto_sends, by_text, last, refused, drop_w)
    ctx.check(NO_EXCLUDED_SENT, ok, **info)
    tolerated = info["tolerated_dropped"]
    lat, unaccepted = _latencies(plan, accepted, control, t_drained)
    ok, info = _check_send_latency(lat, unaccepted)
    ctx.check(SEND_LATENCY, ok, budget=True, **info)
    ok, info = _check_converges(settled, last, ae)
    ctx.check(CONVERGES, ok, **info)
    ok, info = _check_single_flight(sizes, control, refreshes)
    ctx.check(SINGLE_FLIGHT, ok, **info)
    ok, info = _check_external_readd(J, big[0], drop, drop_ids, window)
    ctx.check(EXTERNAL_READD, ok, **info)
    ok, info = _check_small_exact(auto_sends, control, by_text, last[control], ae[control]["roster"], refreshes)
    ctx.check(SMALL_EXACT, ok, **info)
    ok, info = _check_manual(manual, accepted, last, refused, drop_w)
    ctx.check(MANUAL_NO_EXCLUDED_SENT, ok, **info)
    p95_big, p95_ctl = _p95(lat["big"]), _p95(lat["control"])

    # ── Metrics ───────────────────────────────────────────────────────────────
    holds = [e["ms"] for e in J if e["ev"] == "hold"]
    big_load = [p for p in plan if p["aid"] != control and p["text"] in accepted]
    adds_load = sum(c_load.get(a, {}).get("adds_send", 0) - c_warm.get(a, {}).get("adds_send", 0) for a in big)
    ends = [e for e in refreshes if e["ev"] == "refresh_end"]
    ctx.metric("auto_exclude", {
        "cold": cold, "load_s": load_s, "sends": len(plan), "accepted": len(plan) - len(unaccepted),
        "unaccepted": unaccepted[:10],
        "adds_per_big_send": round(adds_load / len(big_load), 2) if big_load else None,
        "p95_s": {"big": p95_big, "control": p95_ctl},
        "max_s": {k: round(max(v), 2) if v else None for k, v in lat.items()},
        "readd_window_s": round(window[1]["t"] - t_drop, 2) if window[1] else None,
        "refresh_hold_ms": {"n": len(holds), "p50": _p50(holds), "p95": _p95(holds),
                            "max": max(holds) if holds else None},
        "refreshes": {a[-4:]: [e.get("stats") for e in ends if e["account_id"] == a] for a in big},
        "counts": {a[-4:]: c_end.get(a, {}) for a in sizes}, "tolerated_dropped": tolerated})
    p95s = {}
    if p95_ctl is not None:
        p95s["control send enqueue->accept ms"] = round(p95_ctl * 1000, 1)
    for route in ("POST /admin/automation/enqueue", f"POST {QUEUE}"):
        summ = ctx.rec.summary().get(route)
        if summ:
            p95s[route] = summ["p95_ms"]
    ctx.metric("p95_vs_last_green", p95s)
