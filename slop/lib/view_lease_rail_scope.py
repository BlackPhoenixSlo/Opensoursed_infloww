"""The view-lease scenario's `rail` leg (ticket 23, phase-01 1b; scenarios/2026-11-09-view-lease-purchases-tiers.py) and
the App-open warm's read set, which its `warm` leg counts too.

Read set (service/app_open_warm.py, server.app_open_warm_reads), per Creator at the fake-OF wire (`read_class`): the
purchases feed (`feed`, the poll's page), page 0 of the chats window (`chats`, roster-counts' recompute), the rail's
tip and purchases lists (`list:tip`, `list:purchases`: RAIL_LIMIT rows) and the bell's count (`count`). `pass_through`
reads them back through the pass-through routes, as a tab would after `creator_warmed` (the rail's two lists, the
bell's count, the Fan List's page 0 per Creator, then the strip's roster counts): the warm's entries answer, no OF call.

`run`, the purchases loop not running yet (so no feed read but the warm's and the Select refresh's): the earlier warm
ages past REUSE_S and its leases lapse, then the owner's Chromium opens Messages Pro with its saved scope one Creator
A (localStorage `chatterly:scope` = `model:A`; viewport VIS_VIEWPORT, the strip shows about 7 of 10; `through`: the
rail's and strip's reads let through), a document load whose `opened: true` post warms every Creator. An owner
`/events?scope=model:A` stream (actors/manager.SseListener) records each `creator_warmed` it gets. Settled: an owner
`scope=all` stream got every Creator's `creator_warmed`, then the wire quiet. Then an Idle Creator B (not A, not in the page's last
lease post, warmed above) gets one tip (`POST /__slop/of-ws-frame`, OF's `toasts` frame): RAIL_OUT_OF_SCOPE_LIVE:
the open answered `warm: started`, the A-scoped stream got `creator_warmed` for every Creator and B's tip, the rail
row (`/messages-pro/B/<fan>`) shows within RAIL_TIP_S, and the fake OF saw no call for B from the tip until
RAIL_QUIET_S after the row showed. Then, the page closed, the owner polls roster-counts ROSTER_POLLS times (the
strip's poll; returned as its p95 vs the last green). RAIL_LEASED_ONLY (tickets 24, 25): the relay's OF calls under
a `route:` Caller kind (lib/of_call_stats.py, the counter file settled before the open and after those polls) on the
money lists (POLL_ROUTE) or the count (COUNT_ROUTE), and roster-counts' (ROSTER_KIND) chats window reads, are only
for Creators the page's lease posts named (`account_ids` or `selected`) in that span: the rail, bell, counters and
strip badges of an unleased Creator read once it is warmed, from the warm (its `walk:app_open_warm` kind is not
counted). A roster-counts `bust` counts too: in this leg only a selection or a hover sends one.
Screenshots `rail-trigger-open` (just opened), `rail-settled` (rail and strip
after the warm), `rail-tip-b` (B's row in A's tab). Evidence `rail-scope.json`. Then the warm ages past REUSE_S again
(the tiers' Select refresh reads Creators the warm marked current). Fault `money-events-scope-only`
(lib/view_lease_faults.py): only RAIL_OUT_OF_SCOPE_LIVE.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from urllib.parse import parse_qs, urlsplit

from slop.actors import fan_dm
from slop.lib import of_call_stats
from slop.lib.view_lease_faults import RAIL_LEASED_ONLY, RAIL_OUT_OF_SCOPE_LIVE
from slop.lib.view_lease_feed import POLL_ROUTE, RAIL_LIMIT, is_feed, until
from slop.lib.view_lease_visible import VIS_VIEWPORT

READ_SET = ("feed", "chats", "list:tip", "list:purchases", "count")
COUNT_ROUTE = POLL_ROUTE + "/count"
CHATS_ROUTE = "GET /api2/v2/chats"
ROSTER_KIND = "route:GET /admin/accounts/roster-counts"
ROSTER_POLLS = 20        # P95_VS_LAST_MIN_N: fewer is a max, not a p95
RAIL_SETTLE_S = 60.0     # the open to every Creator's count read (groups of 4 at ~5 s a Creator)
RAIL_SSE_S = 5.0         # then every `creator_warmed` on the A-scoped stream
RAIL_TIP_S = 5.0         # the tip frame to its row in A's rail
RAIL_QUIET_S = 3.0       # past the row: still no call for B (the rail's re-reads, a lease-gain refresh)
TIP_FAN = 5              # B's seeded fan who tips (0-4 are other legs')
TIP_ID = 7_700_060_000


def read_class(c: dict) -> str | None:
    """Which read of the warm's read set a fake-OF call is, or None."""
    if is_feed(c):
        return "feed"
    if c["route"] == COUNT_ROUTE:
        return "count"
    if c["route"] == CHATS_ROUTE:
        return "chats"
    if c["route"] == POLL_ROUTE:
        q = parse_qs(c.get("query") or "")
        typ = (q.get("type") or [""])[0]
        if (q.get("limit") or [""])[0] == RAIL_LIMIT and typ in ("tip", "purchases"):
            return f"list:{typ}"
    return None


def read_set(fake, lo: float, hi: float = float("inf")) -> dict[str, dict[str, int]]:
    """Per Creator, its read-set calls by class with t0 in [lo, hi)."""
    out: dict[str, Counter] = {}
    with fake.lock:
        for c in fake.calls:
            k = read_class(c) if c["t0"] is not None and lo <= c["t0"] < hi else None
            if k:
                out.setdefault(c["account"], Counter())[k] += 1
    return {a: dict(v) for a, v in out.items()}


def read_calls(fake, lo: float, hi: float) -> dict[str, list[tuple[float, str]]]:
    """Per Creator, its read-set calls (t0 - lo, class) in [lo, hi): evidence."""
    out: dict[str, list[tuple[float, str]]] = {}
    with fake.lock:
        for c in fake.calls:
            k = read_class(c) if c["t0"] is not None and lo <= c["t0"] < hi else None
            if k:
                out.setdefault(c["account"], []).append((round(c["t0"] - lo, 2), k))
    return out


def _times(fake, aid: str, cls: str, lo: float) -> list[float]:
    with fake.lock:
        return sorted(c["t0"] for c in fake.calls
                      if c["account"] == aid and c["t0"] is not None and c["t0"] >= lo and read_class(c) == cls)


def warmed_on_wire(fake, creators: list[str], lo: float) -> bool:
    """Every Creator's count read (the warm's last) came after its first feed read since `lo`."""
    for a in creators:
        f, n = _times(fake, a, "feed", lo), _times(fake, a, "count", lo)
        if not f or not any(x > f[0] for x in n):
            return False
    return True


async def pass_through(ctx, creators: list[str]) -> dict:
    """A tab's reads of the warmed entries through the pass-through routes; their answers and the OF calls made."""
    fake = ctx.of_wire
    paths = (f"/api/of/v2/users/notifications?limit={RAIL_LIMIT}&offset=0&type=tip",
             f"/api/of/v2/users/notifications?limit={RAIL_LIMIT}&offset=0&type=purchases",
             "/api/of/v2/users/notifications/count", "/api/of/v2/chats?limit=25&offset=0&order=recent")
    statuses: Counter = Counter()

    async def one(aid: str) -> None:
        for p in paths:
            statuses[(await ctx.owner.get(p, headers={"X-Account-Id": aid})).status_code] += 1

    t0 = time.time()
    await asyncio.gather(*(one(a) for a in creators))
    statuses[(await ctx.owner.get("/admin/accounts/roster-counts")).status_code] += 1
    t1 = time.time()
    with fake.lock:
        calls = [{"account": c["account"], "route": c["route"], "query": c.get("query")} for c in fake.calls
                 if c["t0"] is not None and t0 <= c["t0"] <= t1]
    return {"reads": len(creators) * len(paths) + 1, "statuses": {str(k): n for k, n in statuses.items()},
            "of_calls": calls, "s": round(t1 - t0, 2)}


TAB_READ_KEYS = (POLL_ROUTE, COUNT_ROUTE)


def route_reads(raw: dict, keys: tuple[str, ...] = TAB_READ_KEYS) -> Counter:
    """(Creator, key) -> n: the counter file's OF calls a pass-through route made (Caller kind `route:…`) on `keys`,
    and roster-counts' chats window reads (key `roster-counts`)."""
    out: Counter = Counter()
    for kind, key, aid, _st, n in raw["rows"]:
        if kind == ROSTER_KIND and key == CHATS_ROUTE:
            out[(aid, "roster-counts")] += n
        elif kind.startswith("route:") and key in keys:
            out[(aid, key)] += n
    return out


async def _route_reads(ctx) -> Counter | None:
    try:
        raw, _, _ = await of_call_stats.settled(ctx.of_wire, of_call_stats.path(ctx))
    except (OSError, ValueError, KeyError):
        return None
    return route_reads(raw)


def leased_only(before: Counter | None, after: Counter | None, posts: list[dict]) -> dict:
    """RAIL_LEASED_ONLY's evidence: the span's tab reads by Creator and key, the Creators the posts leased, and the
    reads for any other Creator (`stray`, empty when it holds)."""
    leased = set()
    for p in posts:
        leased |= set(p["body"].get("account_ids") or [])
        if p["body"].get("selected"):
            leased.add(p["body"]["selected"])
    if before is None or after is None:
        return {"counter_file": "unreadable", "leased": sorted(leased), "stray": None}
    span = after - before
    reads = {f"{a} {k}": n for (a, k), n in sorted(span.items())}
    stray = {f"{a} {k}": n for (a, k), n in sorted(span.items()) if a not in leased}
    return {"leased": sorted(leased), "tab_reads": reads, "stray": stray}


def _last_read(fake) -> float:
    with fake.lock:
        return max((c["t0"] for c in fake.calls if c["t0"] is not None and read_class(c)), default=0.0)


async def age_out(fake, reuse_s: float, floor_s: float = 0.0) -> float:
    """Until the last read-set call is older than `reuse_s` + 1 s (the warm marks lapse), at least `floor_s`."""
    wait = max(floor_s, _last_read(fake) + reuse_s + 1.0 - time.time())
    await asyncio.sleep(wait)
    return round(wait, 2)


async def _roster_polls(ctx) -> dict:
    """ROSTER_POLLS owner roster-counts reads in a row: their statuses and p95 (ms)."""
    ms: list[float] = []
    statuses: Counter = Counter()
    for _ in range(ROSTER_POLLS):
        t0 = time.perf_counter()
        statuses[(await ctx.owner.get("/admin/accounts/roster-counts")).status_code] += 1
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return {"n": len(ms), "p95_ms": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 1),
            "statuses": {str(k): n for k, n in statuses.items()}}


async def run(ctx, creators: list[str], roles: dict[str, list[str]], through, *, ttl_s: float,
              reuse_s: float) -> dict | None:
    """The leg; returns the roster-counts polls' {n, p95_ms, statuses} (None under --no-ui)."""
    if not ctx.ui:
        ctx.skip(RAIL_OUT_OF_SCOPE_LIVE, "--no-ui: no browser")
        ctx.skip(RAIL_LEASED_ONLY, "--no-ui: no browser")
        return None
    from slop.actors import ui
    from slop.actors.manager import SseListener

    w, fake = ctx.world, ctx.of_wire
    hook = ctx.owner.share(limits=2)
    waited = await age_out(fake, reuse_s, ttl_s + 1.0)
    tab_reads0 = await _route_reads(ctx)
    a = roles["owner"][0]
    # `all` (not under test) settles the warm; `model:A` is A's tab's stream, the one under test.
    h_all, h_a = ctx.owner.share(limits=2), ctx.owner.share(limits=2)
    obs_all = SseListener(h_all, scope="all", states=("creator_warmed",))
    obs = SseListener(h_a, scope=f"model:{a}", states=("creator_warmed",))
    await obs_all.start()
    await obs.start()
    warmed_at: dict[str, float] = {}

    def all_warmed() -> bool:
        for e in obs_all.state_events:
            warmed_at.setdefault(e[2], time.time())
        return set(warmed_at) >= set(creators)

    def seen() -> set[str]:
        return {e[2] for e in obs.state_events if e[0] == "creator_warmed"}
    posts: list[dict] = []
    shots: list[str] = []
    t: dict[str, float] = {}
    out: dict = {"a": a, "aged_out_s": waited}
    async with ui.owner_browser(ctx, viewport=VIS_VIEWPORT, through=through) as page:
        async def answer(resp, post: dict) -> None:
            try:
                post["status"], post["answer"] = resp.status, await resp.json()
            except Exception as e:  # noqa: BLE001 — a post still in flight when the page closes
                post["status"], post["answer"] = None, {"error": type(e).__name__}

        def on_response(resp) -> None:
            req = resp.request
            if req.method == "POST" and urlsplit(req.url).path == "/admin/view-lease":
                try:
                    body = json.loads(req.post_data or "{}")
                except ValueError:
                    body = {}
                posts.append(post := {"t": time.time(), "body": body})
                asyncio.ensure_future(answer(resp, post))

        page.on("response", on_response)
        await page.add_init_script(f"try {{ localStorage.setItem('chatterly:scope', 'model:{a}'); }} catch (e) {{}}")
        t["open"] = time.time()
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        await until(lambda: any(p["body"].get("opened") for p in posts), 60)
        shots.append(await ui.shot(ctx, page, "rail-trigger-open"))
        settled = await until(all_warmed, RAIL_SETTLE_S, 0.1)
        await of_call_stats.quiet(fake, 1.5, 20)
        await until(lambda: seen() >= set(creators), RAIL_SSE_S)
        t["settled"] = time.time()
        shots.append(await ui.shot(ctx, page, "rail-settled"))
        last = next((p["body"] for p in reversed(posts)), {})
        leased_now = set(last.get("account_ids") or []) | {last.get("selected")}
        idle = [x for x in roles["idle"] if x != a and x not in leased_now] or roles["idle"]
        b = idle[-1]
        fans = w.data["fans"][b]
        fan = fans[min(TIP_FAN, len(fans) - 1)]
        frame = {"toasts": [{"id": TIP_ID, "type": "tip", "text": "tipped you $25", "createdAt": fan_dm._now_iso(),
                             "data": {"relatedUser": {"id": fan["id"], "name": fan["name"],
                                                      "username": fan["username"]}}}]}
        row = page.locator(f'.overscroll-contain a[href^="/messages-pro/{b}/"]').first
        b_events0 = obs.accounts.get(b, 0)
        t["tip"] = time.time()
        sent = (await hook.post("/__slop/of-ws-frame", json={"account_id": b, "frame": frame})).status_code
        try:
            await row.wait_for(state="visible", timeout=RAIL_TIP_S * 1000)
            t["visible"] = time.time()
        except Exception:  # noqa: BLE001 — Playwright's TimeoutError: the row never showed
            t["visible"] = None
        shots.append(await ui.shot(ctx, page, "rail-tip-b"))
        await asyncio.sleep(RAIL_QUIET_S)
        t["quiet_end"] = time.time()
    for o, h in ((obs, h_a), (obs_all, h_all)):
        await o.stop()
        await h.aclose()
    await hook.aclose()
    roster = await _roster_polls(ctx)
    leased_reads = leased_only(tab_reads0, await _route_reads(ctx), posts)
    hi = (t["visible"] or t["tip"] + RAIL_TIP_S) + RAIL_QUIET_S
    with fake.lock:
        b_calls = [{"t_rel_tip": round(c["t0"] - t["tip"], 2), "route": c["route"], "query": c.get("query")}
                   for c in fake.calls if c["account"] == b and c["t0"] is not None and t["tip"] <= c["t0"] <= hi]
    warmed_seen = seen()
    opened = next((p for p in posts if p["body"].get("opened")), None)
    out |= {"b": b, "fan": fan["id"], "frame_post": sent, "t": t, "settled": settled,
            "open_post": opened, "warm_answer": ((opened or {}).get("answer") or {}).get("warm"),
            "warmed_on_stream": sorted(warmed_seen), "missing_on_stream": sorted(set(creators) - warmed_seen),
            "stream_events": dict(obs.events), "stream_accounts": dict(obs.accounts),
            "b_tip_on_stream": obs.accounts.get(b, 0) - b_events0,
            "row_after_tip_s": round(t["visible"] - t["tip"], 2) if t["visible"] else None,
            "b_warm_age_at_tip_s": round(t["tip"] - warmed_at[b], 2) if b in warmed_at else None,
            "warmed_after_open_s": {k: round(v - t["open"], 2) for k, v in warmed_at.items()},
            "b_of_calls_tip_to_quiet": b_calls, "read_set_since_open": read_set(fake, t["open"], t["tip"]),
            "leased_only": leased_reads, "roster_polls": roster, "posts": posts, "screenshots": shots}
    ok = (out["warm_answer"] == "started" and settled and not out["missing_on_stream"] and sent == 200
          and out["b_tip_on_stream"] >= 1 and t["visible"] is not None and not b_calls)
    ctx.check(RAIL_OUT_OF_SCOPE_LIVE, ok, **{k: v for k, v in out.items()
                                             if k not in ("posts", "leased_only", "roster_polls")})
    ctx.check(RAIL_LEASED_ONLY, leased_reads["stray"] == {} and bool(leased_reads["leased"])
              and roster["statuses"] == {"200": ROSTER_POLLS}, **leased_reads, roster_polls=roster)
    (ctx.out / "rail-scope.json").write_text(json.dumps(out, indent=1, default=str))
    out["aged_out_after_s"] = await age_out(fake, reuse_s, ttl_s + 1.0)
    return roster
