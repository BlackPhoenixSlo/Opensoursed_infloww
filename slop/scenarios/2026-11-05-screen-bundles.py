from __future__ import annotations

import asyncio
import time
from collections import Counter

from slop.lib.client import Http, label
from slop.lib.screen_bundle import bundle_view, late_reads
from slop.lib.screens_faults import C_NO_SKIP, C_PRIORITY, C_SCOPE, C_SLOW
from slop.seed import chatters as chatters_seed
from slop.seed import of_sessions

PROFILE = "one_agency"
UI = False
OF_WIRE = True
FAULT = "screen-bundle-waits-slowest"
# measured inbox-light p95 on one code, host load 5-14: 175-413 ms (2.4x spread); BUDGET_MS is the hard line
P95_VS_LAST = (2.0, 150)
P95_VS_LAST_MIN_N = 100
OF_MS = 400
CHATS = 30
CHATTERS = 10
PER_CHATTER = 5
ROUNDS = 3
LIGHT = 10
LIGHT_ROUNDS = 10
SETTLE_S = 3.0
# one owner bundle refreshes every cache (counts/users_me 60 s, bell 30 s, no serve-stale) so a light round never waits an OF trip on a TTL edge
PRIME_DEADLINE_MS = 15000
SLOW_S = 10.0
SLOW_USERS = 20
SLOW_DEADLINE_MS = 4000
SLACK_MS = 750
LANES_DEADLINE_MS = 300
TAP_AFTER_S = 0.15
DRAIN_S = 60.0
WINDOW = {"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"}
DASH, INBOX = "/admin/screens/dashboard", "/admin/screens/inbox"
PER_MODEL_CARD = "/#card-per-model"
BUDGET_MS = {"dash-light": 350, "inbox-light": 450}

OF_ROUTES = {"profile": "GET /api2/v2/users/me", "subscriberCounts": "GET /api2/v2/subscriptions/count/all",
             "newFans": "GET /api2/v2/subscriptions/subscribers/chart",
             "notificationCounts": "GET /api2/v2/users/notifications/count", "chats": "GET /api2/v2/chats"}
C_DASH_COLD = "dash-cold: every bundle 200, exactly the caller's Creators, each complete or stale with 504 bundle_deadline"
C_DASH_WARM = "dash-warm (all clients at once): every bundle 200, each Creator complete or stale with 504 bundle_deadline, no other error"
C_DASH_LIGHT = "dash-light (LIGHT at once, warm): every bundle complete (settings, accounts, perModel, every Creator's 3 reads), none stale"
C_ONE_DASH = "dash-cold: OnlyFans saw at most one call per Creator per read (users/me, count/all, chart: single-flight)"
C_INBOX_COLD = "inbox-cold: every bundle 200, exactly the caller's Creators, each complete or stale with 504 bundle_deadline"
C_INBOX_WARM = "inbox-warm (all clients at once): every bundle 200, each Creator complete or stale with 504 bundle_deadline, no other error"
C_INBOX_LIGHT = "inbox-light (LIGHT at once, warm): every Creator's bell + 25-chat page + next cursor, none stale"
C_ONE_INBOX = "inbox-cold: OnlyFans saw at most one notifications/count call per Creator (single-flight)"
C_PARITY = "parity: each bundle value equals its per-Creator route's body (profile, counts, chart, bell, chats page)"
C_WARMED = "slow Creator's late reads kept running and warmed the cache: the next bundle has it complete"
C_WIRE = "lib/of_wire.py saw only signed calls it models"
C_BUDGET = "light-stage bundle p95 within BUDGET_MS"


DASH_READS = ("profile", "subscriberCounts", "newFans")


def _creators(body: dict) -> set[str]:
    return ({a for r in DASH_READS for a in body.get(r, {})}
            | {e["accountId"] for e in body["errors"] if e["accountId"] and e["read"] != "*"})


async def _get(http, path: str, **params) -> tuple[int, dict | None, float]:
    t0 = time.perf_counter()
    try:
        r = await http.get(path, params=params)
        body = bundle_view(r.json()) if r.status_code == 200 else None
        return r.status_code, body, (time.perf_counter() - t0) * 1000
    except Exception:  # noqa: BLE001  transport error: recorded as 599 by the client too
        return 599, None, (time.perf_counter() - t0) * 1000


def _envelope_problem(status, body, *, cold: bool) -> str | None:
    if status != 200 or body is None:
        return f"status {status}"
    if body["duplicates"]:
        return f"duplicate answers {body['duplicates'][:3]}"
    late = late_reads(body)
    other = [e for e in body["errors"] if (e["accountId"], e["read"]) not in late]
    if other:
        return f"errors {other[:2]}"
    if late and not cold:
        return f"late in a warm round {sorted(map(str, late))[:3]}"
    return None


def _dash_problem(status, body, want: set[str], *, owner: bool, cold: bool) -> str | None:
    if problem := _envelope_problem(status, body, cold=cold):
        return problem
    if not body.get("settings") or bool(body.get("accounts")) != owner:
        return "no settings/accounts" if owner else "a chatter got an accounts answer"
    ids = _creators(body)
    if ids != want:
        return f"creators {sorted(ids ^ want)[:5]} off"
    late = late_reads(body)
    card = PER_MODEL_CARD not in ((body["settings"].get("permissions") or {}).get("denied_cards") or ())
    if card and owner and body.get("perModel") is None and (None, "perModel") not in late:
        return "no perModel"
    fields = DASH_READS if card else ("profile",)
    answered = {(e["accountId"], e["read"]) for e in body["errors"]}
    for aid in sorted(ids):
        if not card and any(aid in body.get(f, {}) or (aid, f) in answered for f in ("subscriberCounts", "newFans")):
            return f"creator {aid}: hidden card but counts read"
        missing = [f for f in fields if body.get(f, {}).get(aid) is None]
        stale = any(a == aid for a, _ in late)
        if stale != bool(missing) or any((aid, f) not in late for f in missing):
            return f"creator {aid} missing {missing} stale={stale}"
        profile = body.get("profile", {}).get(aid)
        if profile is not None and str(profile.get("id")) != aid:
            return f"creator {aid} got profile {profile.get('id')}"
    return None


def _inbox_problem(status, body, want: set[str], n_chats: dict[str, int], cursor: int, *, cold: bool) -> str | None:
    if problem := _envelope_problem(status, body, cold=cold):
        return problem
    late = late_reads(body)
    chats, bells = body.get("chats", {}), body.get("notificationCounts", {})
    for aid in want:
        page, bell = chats.get(aid), bells.get(aid)
        if page is None and (aid, "chats") not in late:
            return f"{aid} no page"
        if bell is None and (aid, "notificationCounts") not in late:
            return f"{aid} no bell"
        if page is not None:
            n = n_chats[aid]
            if len(page.get("list") or []) != max(0, min(25, n - cursor)):
                return f"{aid} page {len(page.get('list') or [])} rows, want {max(0, min(25, n - cursor))}"
            if page.get("hasMore") != (cursor + 25 < n):
                return f"{aid} hasMore {page.get('hasMore')}"
    extra = (set(chats) | set(bells)) - want
    return f"extra Creators {sorted(extra)[:3]}" if extra else None


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    neighbour = next(c["id"] for c in w.data["creators"] if c["owner"] != main)
    fake = ctx.of_wire
    fake.latency_s = float(ctx.param("of_ms", OF_MS)) / 1000
    n_chats: dict[str, int] = {}
    for c in w.data["creators"]:
        fs = w.data["fans"].get(c["id"], [])[:CHATS]
        fake.chats[c["id"]] = [
            {"withUser": {"id": f["id"], "_view": "s"}, "unreadMessagesCount": 0,
             "lastMessage": {"id": 7_000_000 + i, "text": "hey", "fromUser": {"id": f["id"]}, "isFree": True,
                             "price": 0, "createdAt": f"2026-11-05T1{i % 10}:{i % 60:02d}:00+00:00"}}
            for i, f in enumerate(fs)]
        n_chats[c["id"]] = len(fs)

    n_chat = max(1, min(int(ctx.param("chatters", CHATTERS)), ctx.users // 20 or 1))
    mine = [aids[(PER_CHATTER * k) % len(aids):][:PER_CHATTER] for k in range(n_chat)]
    seeded = await chatters_seed.seed(w, ctx.owner, main, [f"slop-screens-{k}" for k in range(n_chat)],
                                      account_ids=mine)
    chat_http = []
    for s in seeded:
        h = Http(ctx.relay, ctx.rec)
        (await h.post("/chatter/login", json={"username": s["username"], "password": s["password"]})).raise_for_status()
        chat_http.append(h)
    n_owner = max(1, ctx.users - n_chat)
    owners = [ctx.owner.share(limits=4) for _ in range(n_owner)]
    clients = [(h, set(aids), True) for h in owners] + [(h, set(m), False) for h, m in zip(chat_http, mine)]
    ctx.metric("world", {"creators": len(aids), "owners": n_owner, "chatters": n_chat, "of_ms": OF_MS,
                         "chats_per_creator": dict(Counter(n_chats.values())),
                         "per_creator_calls_replaced": {"dashboard": 2 + 1 + 3 * len(aids), "inbox": 1 + 2 * len(aids)}})

    def of_calls_since(n0: int) -> list[dict]:
        with fake.lock:
            return list(fake.calls[n0:])

    def one_per(calls, reads) -> dict:
        per = Counter((c["account"], c["route"]) for c in calls)
        return {f"{a} {r}": per.get((a, OF_ROUTES[r]), 0) for a in aids for r in reads
                if per.get((a, OF_ROUTES[r]), 0) > 1}

    light = clients[:LIGHT - 1] + clients[-1:]

    async def prime(path: str, params: list[dict]) -> None:
        await asyncio.sleep(SETTLE_S)
        for p in params:
            st, body, _ = await _get(owners[0], path, deadline_ms=PRIME_DEADLINE_MS, **p)
            if st != 200 or body is None or body["errors"]:
                ctx.note(f"prime {path} {p}: status {st}, errors {(body or {}).get('errors', [])[:3]}")

    async def dash_round(stage: str, cold: bool, who=None) -> tuple[list[str], list[tuple]]:
        who = who or clients
        ctx.rec.stage = stage
        res = await asyncio.gather(*(_get(h, DASH, **WINDOW) for h, _, _ in who))
        ctx.rec.stage = None
        return [p for (st, b, _), (_, want, owner) in zip(res, who)
                if (p := _dash_problem(st, b, want, owner=owner, cold=cold))], res

    n0 = len(fake.calls)
    bad, res = await dash_round("dash-cold", cold=True)
    calls = of_calls_since(n0)
    stale_cold = sum(len({a for a, _ in late_reads(b) if a}) for _, b, _ in res)
    ctx.check(C_DASH_COLD, not bad, bundles=len(res), bad=len(bad), first=bad[:3], stale_creators=stale_cold)
    off = one_per(calls, ("profile", "subscriberCounts", "newFans"))
    ctx.check(C_ONE_DASH, not off, n_off=len(off), off=dict(list(off.items())[:6]), of_calls=len(calls))
    warm_bad, stale_warm = [], 0
    for k in range(ROUNDS):
        b, r = await dash_round("dash-warm", cold=True)
        warm_bad += b
        stale_warm += sum(len({a for a, _ in late_reads(x) if a}) for _, x, _ in r)
    ctx.check(C_DASH_WARM, not warm_bad, rounds=ROUNDS, bundles=ROUNDS * len(clients), bad=len(warm_bad),
              first=warm_bad[:3], stale_creators=stale_warm, creators_listed=ROUNDS * sum(len(w) for _, w, _ in clients))
    light_bad = []
    await prime(DASH, [WINDOW])
    for k in range(LIGHT_ROUNDS):
        light_bad += (await dash_round("dash-light", cold=False, who=light))[0]
    ctx.check(C_DASH_LIGHT, not light_bad, rounds=LIGHT_ROUNDS, bundles=LIGHT_ROUNDS * len(light), bad=len(light_bad),
              first=light_bad[:3])

    ch, ch_mine = chat_http[0], set(mine[0])
    others = [a for a in aids if a not in ch_mine][:5] + [neighbour]
    n0 = len(fake.calls)
    ctx.rec.stage = "scope"
    sd = await _get(ch, DASH, accounts=",".join(others), **WINDOW)
    si = await _get(ch, INBOX, accounts=",".join(others))
    ctx.rec.stage = None
    leaks = []
    for name, (st, body, _) in (("dashboard", sd), ("inbox", si)):
        if st != 200 or body is None:
            leaks.append(f"{name} status {st}")
            continue
        got = (sorted({a for f in DASH_READS for a, x in body.get(f, {}).items() if x is not None})
               if name == "dashboard" else sorted(set(body.get("chats", {})) | set(body.get("notificationCounts", {}))))
        if got:
            leaks.append(f"{name} values for {got[:3]}")
        refused = {e["accountId"] for e in body["errors"] if e["status"] == 404 and e["read"] == "*"}
        if refused != set(others):
            leaks.append(f"{name} 404s {sorted(refused)[:3]} != asked")
    own_lists = [sorted(_creators(b)) for (_, b, _), (h, _, owner) in zip(res, clients) if not owner and b]
    if any(set(x) - set(aids) for x in own_lists):
        leaks.append("a chatter bundle listed a Creator outside the Agency")
    nb = [c for c in of_calls_since(n0) if c["account"] == neighbour]
    nh = w.data["agencies"][1]["http"]
    ctx.rec.stage = "scope"
    _, nwarm, _ = await _get(nh, DASH, **WINDOW)
    n1 = len(fake.calls)
    so = await _get(ctx.owner, DASH, accounts=neighbour, **WINDOW)
    ctx.rec.stage = None
    warmed = bool(nwarm) and bool(nwarm.get("subscriberCounts", {}).get(neighbour))
    st, body, _ = so
    if not warmed:
        leaks.append("neighbour owner's bundle did not warm its Creator")
    if st != 200 or body is None or _creators(body) or {e["accountId"] for e in body["errors"]
                                                        if e["status"] == 404 and e["read"] == "*"} != {neighbour}:
        leaks.append(f"owner naming the neighbour's Creator: {st} {sorted(_creators(body)) if body else None}")
    nb += [c for c in of_calls_since(n1) if c["account"] == neighbour]
    ctx.check(C_SCOPE, not leaks and not nb, asked=len(others), leaks=leaks, neighbour_of_calls=len(nb))

    async def inbox_round(stage: str, cursor: int, cold: bool, who=None) -> list[str]:
        who = who or clients
        ctx.rec.stage = stage
        res = await asyncio.gather(*(_get(h, INBOX, cursor=cursor) for h, _, _ in who))
        ctx.rec.stage = None
        return [p for (st, b, _), (_, want, _) in zip(res, who)
                if (p := _inbox_problem(st, b, want, n_chats, cursor, cold=cold))]

    n0 = len(fake.calls)
    bad = await inbox_round("inbox-cold", 0, cold=True)
    ctx.check(C_INBOX_COLD, not bad, bundles=len(clients), bad=len(bad), first=bad[:3])
    calls = of_calls_since(n0)
    off = one_per(calls, ("notificationCounts",))
    ctx.check(C_ONE_INBOX, not off, n_off=len(off), off=dict(list(off.items())[:6]),
              chats_of_calls=sum(c["route"] == OF_ROUTES["chats"] for c in calls))
    bad = []
    for _ in range(ROUNDS):
        bad += await inbox_round("inbox-warm", 0, cold=True)
        bad += await inbox_round("inbox-warm", 25, cold=True)
    ctx.check(C_INBOX_WARM, not bad, rounds=ROUNDS, bundles=2 * ROUNDS * len(clients), bad=len(bad), first=bad[:3])
    bad = []
    await prime(INBOX, [{"cursor": 0}, {"cursor": 25}])
    for _ in range(LIGHT_ROUNDS):
        bad += await inbox_round("inbox-light", 0, cold=False, who=light)
        bad += await inbox_round("inbox-light", 25, cold=False, who=light)
    ctx.check(C_INBOX_LIGHT, not bad, rounds=LIGHT_ROUNDS, bundles=2 * LIGHT_ROUNDS * len(light), bad=len(bad), first=bad[:3])
    one = ctx.owner.share(limits=16)
    ctx.rec.stage = "parity"
    _, bd, _ = await _get(one, DASH, **WINDOW)
    _, bi, _ = await _get(one, INBOX)
    diffs = []

    async def per_route(aid: str) -> None:
        hdr = {"X-Account-Id": aid}
        pairs = [("profile", "/api/of/v2/users/me", {}, bd.get("profile", {}).get(aid)),
                 ("subscriberCounts", "/api/of/v2/subscriptions/count/all", {}, bd.get("subscriberCounts", {}).get(aid)),
                 ("newFans", "/api/of/v2/subscriptions/subscribers/chart",
                  {"start": WINDOW["from"], "end": WINDOW["to"]}, bd.get("newFans", {}).get(aid)),
                 ("notificationCounts", "/api/of/v2/users/notifications/count", {},
                  bi.get("notificationCounts", {}).get(aid)),
                 ("chats", "/api/of/v2/chats", {"limit": 25, "offset": 0, "order": "recent"}, bi.get("chats", {}).get(aid))]
        for name, path, q, got in pairs:
            r = await one.get(path, params=q, headers=hdr)
            if r.status_code != 200 or r.json() != got:
                diffs.append(f"{aid} {name}: route {r.status_code}")

    await asyncio.gather(*(per_route(a) for a in aids))
    ctx.rec.stage = None
    await one.aclose()
    ctx.check(C_PARITY, bd is not None and bi is not None and not diffs, creators=len(aids),
              compared=5 * len(aids), diffs=diffs[:5], n_diffs=len(diffs))

    for h, _, _ in clients:
        await h.aclose()

    slow = aids[0]
    ctx.stack.crash_relay()
    await asyncio.to_thread(ctx.stack.start_relay)
    n0 = len(fake.calls)
    fake.extra_s[slow] = float(ctx.param("slow_s", SLOW_S))
    dl = int(ctx.param("slow_deadline_ms", SLOW_DEADLINE_MS))
    ss = [ctx.owner.share(limits=4) for _ in range(min(SLOW_USERS, n_owner))]
    ctx.rec.stage = "slow"
    sres = await asyncio.gather(*(_get(h, DASH, deadline_ms=dl, **WINDOW) for h in ss))
    ctx.rec.stage = None
    sbad = []
    for st, body, ms in sres:
        if st != 200 or body is None:
            sbad.append(f"status {st}")
            continue
        if ms > dl + SLACK_MS:
            sbad.append(f"took {ms:.0f} ms")
        if body["duplicates"]:
            sbad.append(f"duplicate answers {body['duplicates'][:3]}")
        lt = late_reads(body)
        late = sorted(r for a, r in lt if a == slow)
        rest = _creators(body) - {slow}
        if late != ["newFans", "profile", "subscriberCounts"]:
            sbad.append(f"slow Creator late={late}")
        if any(a in rest for a, _ in lt) or any(body.get("profile", {}).get(a) is None for a in rest) \
                or len(rest) != len(aids) - 1:
            sbad.append("another Creator incomplete")
    walls = sorted(ms for _, _, ms in sres)
    ctx.check(C_SLOW, not sbad, bundles=len(sres), deadline_ms=dl, slack_ms=SLACK_MS, bad=sbad[:4],
              wall_max_ms=round(walls[-1]), wall_p50_ms=round(walls[len(walls) // 2]))
    t_end = time.monotonic() + fake.extra_s[slow] + 15
    while time.monotonic() < t_end:
        done = Counter(c["route"] for c in of_calls_since(n0) if c["account"] == slow and c["status"] == 200)
        if all(done.get(OF_ROUTES[r], 0) >= 1 for r in ("profile", "subscriberCounts", "newFans")):
            break
        await asyncio.sleep(0.25)
    fake.extra_s.pop(slow, None)
    n1 = len(fake.calls)
    ctx.rec.stage = "slow-after"
    st, body, ms = await _get(ss[0], DASH, **WINDOW)
    ctx.rec.stage = None
    again = [c for c in of_calls_since(n1) if c["account"] == slow]
    ctx.check(C_WARMED, st == 200 and body is not None and not any(a == slow for a, _ in late_reads(body))
              and body.get("subscriberCounts", {}).get(slow) is not None
              and not body["duplicates"] and not again, http_status=st, ms=round(ms), slow_of_calls_after=len(again),
              duplicates=(body or {}).get("duplicates", [])[:3])
    for h in ss:
        await h.aclose()
    for h in chat_http:
        await h.aclose()

    focus, tapped = aids[1], aids[2]
    ctx.stack.crash_relay()
    await asyncio.to_thread(ctx.stack.start_relay)
    lh, th = ctx.owner.share(limits=4), ctx.owner.share(limits=4)

    async def lanes() -> dict:
        r = await lh.get("/admin/priority-lanes/stats")
        r.raise_for_status()
        return r.json()["accounts"]

    l0 = await lanes()
    n0 = len(fake.calls)
    ctx.rec.stage = "lanes"
    first = asyncio.create_task(_get(lh, INBOX, focus=focus, deadline_ms=LANES_DEADLINE_MS))
    await asyncio.sleep(TAP_AFTER_S)
    t0 = time.perf_counter()
    tap = await th.get("/api/of/v2/chats", params={"limit": 10, "offset": 0, "order": "recent"},
                       headers={"X-Account-Id": tapped})
    tap_ms = (time.perf_counter() - t0) * 1000
    fst, fbody, _ = await first
    ctx.rec.stage = None
    want = {(a, r) for a in aids for r in ("notificationCounts", "chats")}
    t_end = time.monotonic() + DRAIN_S
    while time.monotonic() < t_end:
        seen = {(c["account"], r) for c in of_calls_since(n0) for r, route in OF_ROUTES.items()
                if c["route"] == route and c["status"] == 200}
        if want <= seen:
            break
        await asyncio.sleep(0.25)
    missing = sorted(want - seen)
    l1 = await lanes()
    n1 = len(fake.calls)
    ctx.rec.stage = "lanes"
    sst, sbody, _ = await _get(lh, INBOX, focus=focus)
    ctx.rec.stage = None
    second_calls = len(of_calls_since(n1))
    zero = dict.fromkeys(("calls_user", "calls_background", "blocked_total"), 0)
    delta = {a: {k: (l1.get(a) or zero)[k] - (l0.get(a) or zero)[k] for k in zero} for a in aids}
    user_active = sorted(a for a in aids if delta[a]["calls_user"] and a != tapped)
    ctx.check(C_PRIORITY, fst == 200 and tap.status_code == 200 and user_active == [focus]
              and delta[tapped]["blocked_total"] == 0 and delta[tapped]["calls_background"] > 0,
              first_status=fst, tap_status=tap.status_code, tap_ms=round(tap_ms), user_active=user_active[:5],
              n_user_active=len(user_active), focus=delta[focus], tapped=delta[tapped])
    late_first = len({a for a, _ in late_reads(fbody) if a})
    sprob = _inbox_problem(sst, sbody, set(aids), n_chats, 0, cold=False)
    ctx.check(C_NO_SKIP, fst == 200 and not fbody["duplicates"] and not missing and sprob is None
              and second_calls == 0, first_duplicates=(fbody or {}).get("duplicates", [])[:3],
              reads=2 * len(aids), deadline_ms=LANES_DEADLINE_MS, stale_after_first=late_first,
              never_reached_of=len(missing), first_missing=missing[:4], second=sprob, second_of_calls=second_calls)
    await lh.aclose()
    await th.aclose()
    ctx.check(C_WIRE, fake.unsigned == 0 and not fake.unmodelled, unsigned=fake.unsigned,
              unmodelled=dict(fake.unmodelled))

    stages = ("dash-cold", "dash-warm", "dash-light", "inbox-cold", "inbox-warm", "inbox-light", "slow", "scope",
              "parity", "slow-after", "lanes")
    http = {s: ctx.rec.summary(s) for s in stages}
    ctx.metric("http_by_stage", http)
    row = {"dash-cold": http["dash-cold"].get(label("GET", DASH)), "dash-warm": http["dash-warm"].get(label("GET", DASH)),
           "inbox-cold": http["inbox-cold"].get(label("GET", INBOX)),
           "inbox-warm": http["inbox-warm"].get(label("GET", INBOX)),
           "dash-light": http["dash-light"].get(label("GET", DASH)), "inbox-light": http["inbox-light"].get(label("GET", INBOX))}
    ctx.metric("bundle_ms", {k: {"n": v["n"], "p50": v["p50_ms"], "p95": v["p95_ms"]} for k, v in row.items() if v})
    ctx.metric("slow_bundle_ms", {"deadline_ms": dl, "p50": walls[len(walls) // 2], "max": walls[-1]})
    over = {k: (row[k]["p95_ms"], b) for k, b in BUDGET_MS.items() if b and row[k] and row[k]["p95_ms"] > b}
    if ctx.report.params.get("map"):
        ctx.skip(C_BUDGET, "coverage run: timings not comparable")
    else:
        ctx.check(C_BUDGET, not over, budget_ms=BUDGET_MS, p95={k: row[k]["p95_ms"] for k in BUDGET_MS}, over=over)
    ctx.metric("p95_vs_last_green", {k: row[k]["p95_ms"] for k in BUDGET_MS})
    ctx.metric("p95_vs_last_green_n", {k: row[k]["n"] for k in BUDGET_MS})
    ctx.note("bundle p50/p95 ms: " + ", ".join(f"{k} {v['p50_ms']}/{v['p95_ms']} (n {v['n']})"
                                               for k, v in row.items() if v)
             + f"; slow Creator (+{SLOW_S:.0f} s): bundle p50 {walls[len(walls) // 2]:.0f} / max {walls[-1]:.0f} ms"
             f" at deadline_ms {dl}")
