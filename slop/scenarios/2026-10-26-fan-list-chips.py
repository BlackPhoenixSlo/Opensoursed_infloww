from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from slop.actors import fan_dm, manager, ui
from slop.actors.notif_click import _Console
from slop.lib import app_ts
from slop.lib import fan_list_faults as F

PROFILE = "agency_inbox"
UI = True
FAULT = "fan-list-owe-reply-last-sort-never-active"
VIEWPORT = (1470, 915)
NARROW = (320, 700)
PHONE = (390, 844)
SORT_MENU = ["Sort by", "Newest first", "Amount spent", "Spend + unread on top", "Spend + recency"]
OWE_DOT = "Read · awaiting your reply"
EXTRA_SORT = "Spend + unread on top"
SORT_KEY = "chatterly:chat-sort-mode"
CHIPS = ["All", "Owe reply", "Pinned", "Unread", "With Tips", "Priority"]
PINNED = "VIP whales"
PIN_LISTS = "Pin lists as chips"
PLUS = re.compile(r" extras$")
SEARCH_KEY_MS = 100
TS = Path(__file__).resolve().parents[1] / "lib" / "fan_list_ts.mjs"
ALL = "all-models"
SPEND_ZERO = 0.25
HALF_LIFE_H = {"unread": 3, "owed": 2, "idle": 1}
TIER = {"unread": 2, "owed": 1, "idle": 0}
LOW_SCORE_CENTS = 300
OWNER_THREADS = 5
OWNER_RATE = 10.0
OWNER_THINK_S = (0.5, 1.5)
RECENT, MESSAGES = "GET /admin/chats/recent", "GET /admin/messages/:id/:id"
RECENT_P95_MS, MESSAGES_P95_MS = 750, 500
P95_VS_LAST = (2.0, 100)
P95_VS_LAST_MIN_N = 20

C_ORDER = "chips on screen: All, Owe reply, Pinned, Unread, With Tips, the pinned lists, Priority"
C_NO_PLUS = 'no "+" Extras overflow and no "✎ Lists" chip in the Fan List (All Models and one Creator with lists)'
C_UNREAD = F.C_UNREAD
C_OWE = F.C_OWE
C_OWE_ROWS = "Owe reply lists exactly the owed chats (by Fan)"
C_DOTS = "owe dots only while Owe reply is on"
C_SORT = "an extra sort turns the sort button active (blue), named by it, with its ✓, and puts unread rows first"
C_SORT_STORED = "the sort choice is in localStorage and survives a reload"
C_PENCIL = "the pencil shows only for one Creator with an OF list, and opens the folder picker"
C_PIN = "pinning a list in the pencil's picker is one pin write and adds its chip"
C_ONE_LINE = "the filter row keeps one line at the 400px pane (All Models and one Creator)"
C_MENU_ORDER = ("the sort menu lists Sort by, then Newest first, Amount spent, Spend + unread on top, Spend + recency,"
                " with no divider (1470px and a 390px phone)")
C_PHONE_PICK = "on a 390px phone, picking Amount spent in the sort menu names the sort button by it and stores it"
C_MENU_PLACE = "the sort menu opens inside the Fan List pane, under the sort button (All Models and one Creator)"
C_CONSOLE = "no console error in the browser session"
C_5XX = "no 5xx from the app or relay in the browser session (OF's /api/of/* is faked or held)"
FL_SORT_KEEPS_ALL, FL_SORT_TIERS, FL_COUNTS = F.FL_SORT_KEEPS_ALL, F.FL_SORT_TIERS, F.FL_COUNTS
CK_RECENT_P95 = (f"p95 {RECENT} <= {RECENT_P95_MS} ms, no non-2xx and no owner error, --users owners arriving "
                 f"open loop to read the Fan List view")
CK_MESSAGES_P95 = (f"p95 {MESSAGES} <= {MESSAGES_P95_MS} ms, no non-2xx and no owner error, --users owners arriving "
                   f"open loop to read the Fan List view")
C_SEARCH = "a Fan's name typed fast is one search, for the box's text, and the rows are its matches (one Creator)"
UI_CHECKS = (C_ORDER, C_NO_PLUS, C_UNREAD, C_OWE, C_OWE_ROWS, C_DOTS, C_SORT, C_SORT_STORED, C_PENCIL, C_PIN,
             C_ONE_LINE, C_MENU_PLACE, C_MENU_ORDER, C_PHONE_PICK, C_SEARCH, C_CONSOLE, C_5XX)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators, fans = w.data["creators"], w.data["fans"]
    rng = w.rng("scenario:fan-list-chips")
    n_fresh, n_tip, n_open = ctx.param("fresh", 3), ctx.param("tippers", 4), ctx.param("opened", 4)
    threaded = {(t["account_id"], t["fan_id"]) for t in w.data["threads"]}
    unread0 = {(t["account_id"], t["fan_id"]) for t in w.data["threads"] if t["unread"]}
    fresh, tippers = [], []
    for c in creators:
        pool = [f for f in fans[c["id"]] if (c["id"], f["id"]) in threaded]
        picks = rng.sample(pool, n_fresh + n_tip)
        fresh += picks[:n_fresh]
        tippers += picks[n_fresh:]

    ids = iter(range(9_700_000_000_000, 9_800_000_000_000))
    frames = [(f, fan_dm.frame(next(ids), f, "slop chips: new dm")) for f in fresh]
    frames += [(f, fan_dm.frame(next(ids), f, "slop chips: tip", tip_dollars=rng.choice([5, 10, 20, 50])))
               for f in tippers]
    statuses = []

    async def pump(aid):
        for f, fr in frames:
            if f["account_id"] == aid:
                statuses.append((await fan_dm.inject(ctx.owner, aid, fr)).status_code)

    await asyncio.gather(*(pump(c["id"]) for c in creators))
    stats = await manager.quiesce(ctx.owner)
    ctx.check("every frame accepted (2xx)", all(s < 300 for s in statuses) and len(statuses) == len(frames),
              sent=len(statuses), want=len(frames))
    ctx.check("relay quiesced", not stats.get("timed_out"), stats=stats)

    hit = {(f["account_id"], f["id"]) for f in fresh + tippers}
    opened = []
    for c in creators:
        shown = {(c["id"], r["withUser"]["id"]) for r in await manager.recent_chats(ctx.owner, c["id"], 100)}
        cand = sorted(k for k in unread0 | hit if k[0] == c["id"] and k in shown)
        opened += rng.sample(cand, min(n_open, len(cand)))
    reads = [(await ctx.owner.post(f"/admin/messages/{a}/{f}/mark-read")).status_code for a, f in opened]
    ctx.check("every mark-read 2xx", all(s < 300 for s in reads), n=len(reads))

    view = await _view(ctx, creators)
    rows = [r for v in view.values() for r in v]
    by_key = {(r["__accountId"], r["withUser"]["id"]): r for r in rows}
    opened_set = set(opened)
    tally = {**_tally(rows), "with_tips": sum(r["_tipped"] for r in rows)}
    ctx.metric("view", tally)
    ctx.note(f"view: {json.dumps(tally)}")
    bad = [k for k in (hit - opened_set) if not by_key.get(k, {}).get("hasUnread")]
    ctx.check("each fresh / tipper chat not opened is unread", not bad, wrong=len(bad))
    bad = [k for k in opened_set if by_key.get(k, {}).get("hasUnread") or not by_key.get(k, {}).get("_fanLast")]
    ctx.check("each opened chat is read and owed", not bad, wrong=len(bad), sample=bad[:3])
    await _ranked(ctx, w, view, creators)
    await _owners(ctx, w, view, creators)

    if not ctx.app:
        for n in UI_CHECKS:
            ctx.skip(n, "--no-ui")
        return
    await _screens(ctx, view, creators)


async def _view(ctx, creators) -> dict[str, list[dict]]:
    sem = asyncio.Semaphore(16)
    out = {}
    for c in creators:
        base = await manager.recent_chats(ctx.owner, c["id"], 100)

        async def one(r, aid=c["id"]):
            async with sem:
                ms = await manager.thread_messages(ctx.owner, aid, r["withUser"]["id"], 200)
            last = max(ms, key=lambda m: m["message_id"]) if ms else None
            fan_last = bool(last) and last["direction"] == "in"
            lm = dict(r.get("lastMessage") or {})
            lm["fromUser"] = {"id": r["withUser"]["id"] if fan_last else int(aid)}
            lm["isTip"] = bool(last and last.get("is_tip"))
            return {**r, "lastMessage": lm, "canSendMessage": True, "isMutedNotifications": False,
                    "_fanLast": fan_last, "_tipped": any(m.get("is_tip") for m in ms)}

        out[c["id"]] = list(await asyncio.gather(*(one(r) for r in base)))
    return out


def _key(r) -> str:
    return f"{r['__accountId']}:{r['withUser']['id']}"


def _state(r) -> str:
    if r["hasUnread"] or (r.get("unreadMessagesCount") or 0) > 0:
        return "unread"
    return "owed" if r["_fanLast"] else "idle"


def _score(r, cents: int, now_ms: int) -> float:
    if not cents:
        return 0.0
    iso = (r.get("lastMessage") or {}).get("createdAt")
    if not iso:
        return float(cents)
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return float(cents)
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now_ms - t.timestamp() * 1000) / 3_600_000)
    return cents * 0.5 ** (hours / HALF_LIFE_H[_state(r)])


def _desc(xs) -> int | None:
    for i in range(len(xs) - 1):
        a, b = xs[i], xs[i + 1]
        a, b = (a, b) if isinstance(a, tuple) else ((a,), (b,))
        for x, y in zip(a, b):
            if abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y)):
                continue
            if y > x:
                return i
            break
    return None


def _slim(r) -> dict:
    return {"__accountId": r["__accountId"], "hasUnread": r["hasUnread"],
            "unreadMessagesCount": r.get("unreadMessagesCount") or 0,
            "withUser": {"id": r["withUser"]["id"], "isRestricted": bool(r["withUser"].get("isRestricted"))},
            "lastMessage": {k: (r.get("lastMessage") or {}).get(k) for k in ("createdAt", "fromUser")}}


async def _ranked(ctx, w, view, creators) -> None:
    rng = w.rng("scenario:fan-list-chips:spend")
    rows_all = sorted((r for c in creators for r in view[c["id"]]), key=_key)
    spend = {_key(r): 0 if rng.random() < SPEND_ZERO else int(10 ** rng.uniform(2, 5)) for r in rows_all}
    union = sorted((r for c in creators for r in view[c["id"]]),
                   key=lambda r: (r.get("lastMessage") or {}).get("createdAt") or "", reverse=True)
    groups = {c["id"]: view[c["id"]] for c in creators} | {ALL: union}
    now = int(time.time() * 1000)
    t0 = time.perf_counter()
    out = await app_ts.run(ctx, TS, {"now": now, "spend": spend,
                                     "groups": [{"name": n, "rows": [_slim(r) for r in rs]} for n, rs in groups.items()]})
    node_ms = round((time.perf_counter() - t0) * 1000)
    keeps, tiers, counts, shape = {}, {}, {}, {}
    for name, rs in groups.items():
        got, by = out[name], {_key(r): r for r in rs}
        want_keys = [_key(r) for r in rs]
        bad = {m: {"n": len(o), "missing": sorted((Counter(want_keys) - Counter(o)).keys())[:3],
                   "extra": sorted((Counter(o) - Counter(want_keys)).keys())[:3]}
               for m, o in got["orders"].items() if Counter(o) != Counter(want_keys)}
        if got["orders"]["recent"] != want_keys or not got["same_recent"]:
            bad["recent"] = {"same_array": got["same_recent"], "in_view_order": got["orders"]["recent"] == want_keys}
        if bad:
            keeps[name] = bad
        st = {k: _state(by[k]) for k in want_keys}
        sc = {k: _score(by[k], spend[k], now) for k in want_keys}
        o, pos = got["orders"], {k: i for i, k in enumerate(want_keys)}
        hy = o["hybrid"]
        high = [k for k in hy if sc[k] >= LOW_SCORE_CENTS]
        low = [k for k in hy if sc[k] < LOW_SCORE_CENTS]
        checks = {
            "spend": (o["spend"], [(spend[k], -pos[k]) for k in o["spend"]]),
            "spend-unread": (o["spend-unread"], [(TIER[st[k]], spend[k], -pos[k]) for k in o["spend-unread"]]),
            "hybrid high first": (hy, [int(sc[k] >= LOW_SCORE_CENTS) for k in hy]),
            "hybrid high by score": (high, [(sc[k], -pos[k]) for k in high]),
            "hybrid low unread first": (low, [(int(st[k] == "unread"), spend[k], sc[k], -pos[k]) for k in low]),
        }
        wrong = {m: (keys, i) for m, (keys, vals) in checks.items() if (i := _desc(vals)) is not None}
        if wrong:
            keys, i = next(iter(wrong.values()))
            tiers[name] = {"modes": {m: i for m, (_, i) in wrong.items()},
                           "at": [{"key": k, "view_pos": pos[k], "state": st[k], "spend": spend[k],
                                   "score": round(sc[k], 3)} for k in keys[i:i + 2]]}
        kept = [r for r in rs if not r["withUser"].get("isRestricted")]
        t = _tally(kept)
        want = {"allCount": sum(1 for r in kept if r["hasUnread"] or r["_fanLast"]), "unreadCount": t["unread"],
                "oweReplyCount": t["owe_reply"]}
        if got["counts"] != want:
            counts[name] = {"app": got["counts"], "view": want}
        shape[name] = {"chats": len(rs), **Counter(st.values()), "zero_spend": sum(not spend[k] for k in want_keys),
                       "hybrid_high": len(high), "restricted": len(rs) - len(kept), "counts": got["counts"]}
    ctx.metric("ranked", {"node_ms": node_ms, "now_ms": now, "groups": shape})
    ctx.note(f"ranked inbox (node, {node_ms} ms): {json.dumps(shape[ALL])} over {len(groups) - 1} Creators + All Models")
    n = len(groups)
    ctx.check(FL_SORT_KEEPS_ALL, not keeps, groups=n, wrong=len(keeps), sample=dict(list(keeps.items())[:2]))
    ctx.check(FL_SORT_TIERS, not tiers, groups=n, wrong=len(tiers), sample=dict(list(tiers.items())[:2]))
    ctx.check(FL_COUNTS, not counts, groups=n, wrong=len(counts), sample=dict(list(counts.items())[:2]),
              all_models=shape[ALL]["counts"])


async def _owners(ctx, w, view, creators) -> None:
    rng = w.rng("scenario:fan-list-chips:owners")
    k = ctx.param("owner_threads", OWNER_THREADS)
    rate = ctx.param("owner_rate", OWNER_RATE)
    plans, at = [], 0.0
    for i in range(ctx.users):
        aid = creators[i % len(creators)]["id"]
        rows = view[aid]
        fans = [r["withUser"]["id"] for r in rng.sample(rows, min(k, len(rows)))]
        plans.append((at, aid, fans, [rng.uniform(*OWNER_THINK_S) for _ in fans]))
        at += rng.expovariate(rate)

    loop = asyncio.get_running_loop()
    t0 = loop.time()

    async def owner(start, aid, fans, thinks):
        await asyncio.sleep(max(0.0, t0 + start - loop.time()))
        http = ctx.owner.share(limits=2)
        try:
            await manager.recent_chats(http, aid, 100)
            for f, think in zip(fans, thinks):
                await asyncio.sleep(think)
                await manager.thread_messages(http, aid, f, 200)
        finally:
            await http.aclose()

    prev, ctx.rec.stage = ctx.rec.stage, "owners"
    try:
        res = await asyncio.gather(*(owner(*p) for p in plans), return_exceptions=True)
    finally:
        ctx.rec.stage = prev
    wall_s = round(loop.time() - t0, 1)
    errs = [repr(e)[:200] for e in res if isinstance(e, BaseException)]
    summ = ctx.rec.summary("owners")
    p95, n = {}, {}
    for route, budget, name in ((RECENT, RECENT_P95_MS, CK_RECENT_P95), (MESSAGES, MESSAGES_P95_MS, CK_MESSAGES_P95)):
        s = summ.get(route)
        if not s:
            ctx.skip(name, "no samples")
            continue
        p95[route], n[route] = s["p95_ms"], s["n"]
        non2xx = s["4xx"] + s["5xx"]
        ctx.check(name, s["p95_ms"] <= budget and not non2xx and not errs, budget=True, p95_ms=s["p95_ms"],
                  p50_ms=s["p50_ms"], n=s["n"], non_2xx=non2xx, owners=len(plans), errors=len(errs),
                  sample=errs[:3])
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", n)
    ctx.metric("owners", {"owners": len(plans), "threads_each": k, "rate_per_s": rate, "think_s": OWNER_THINK_S,
                          "arrivals_s": round(plans[-1][0], 1) if plans else 0, "wall_s": wall_s,
                          "errors": len(errs), "p95_ms": p95, "n": n})


def _chats_answer(view, url: str, account: str | None, loaded: dict) -> dict:
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    rows = list(view.get(account or "", []))
    f = q.get("filter")
    if q.get("list_id") or f in ("pinned", "priority", "unread_tips"):
        rows = []
    elif f == "unread":
        rows = [r for r in rows if r["hasUnread"]]
    elif f == "who_tipped":
        rows = [r for r in rows if r["_tipped"]]
    if q.get("query") or q.get("search"):
        needle = (q.get("query") or q.get("search")).lower()
        rows = [r for r in rows if needle in (r["withUser"].get("name") or "").lower()]
    off, lim = int(q.get("offset") or 0), int(q.get("limit") or 10)
    if not (f or q.get("list_id") or q.get("query") or q.get("search")):
        loaded.update({(r["__accountId"], r["withUser"]["id"]): r for r in rows[off:off + lim]})
    page = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows[off:off + lim]]
    return {"list": page, "hasMore": off + lim < len(rows)}


def _lists_fixture(account_id: str) -> tuple[dict, list]:
    rows = {9001: {"id": 9001, "name": PINNED, "type": "custom", "usersCount": 14},
            9002: {"id": 9002, "name": "Big tippers", "type": "custom", "usersCount": 8},
            9003: {"id": 9003, "name": "Close friends", "type": "close_friends", "usersCount": 3}}
    for r in rows.values():
        r.update(isPinnedToChat=False, canPinnedToChat=True, canAddUsers=True, canManageUsers=True)
    return {account_id: rows}, []


async def _route_lists(page, lists: dict, pins: list) -> None:
    async def folders(route):
        aid = route.request.headers.get("x-account-id") or ""
        body = {"list": list(lists.get(aid, {}).values()), "hasMore": False}
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async def pin(route):
        req = route.request
        if req.method != "PATCH":
            return await route.fallback()
        lid = int(urlsplit(req.url).path.split("/")[-2])
        want = bool(json.loads(req.post_data or "{}").get("pinned"))
        aid = req.headers.get("x-account-id") or ""
        row = lists.get(aid, {}).get(lid)
        if row:
            row["isPinnedToChat"] = want
        pins.append({"account": aid, "list": lid, "pinned": want, "known": bool(row)})
        await route.fulfill(status=200 if row else 404, content_type="application/json",
                            body=json.dumps({"success": bool(row)}))

    await page.route(lambda u: urlsplit(u).path == "/api/of/v2/chats/folders", folders)
    await page.route(lambda u: re.fullmatch(r"/api/of/v2/lists/\d+/pin-chat", urlsplit(u).path) is not None, pin)


async def _open(ctx, page, view, lists, pins):
    served, loaded = [], {}
    await _route_lists(page, lists, pins)

    async def chats(route):
        req = route.request
        if req.method != "GET":
            return await route.fallback()
        served.append(req.url)
        body = _chats_answer(view, req.url, req.headers.get("x-account-id"), loaded)
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    await page.route(lambda u: urlsplit(u).path == "/api/of/v2/chats", chats)
    await _goto(ctx, page)
    return served, loaded


async def _goto(ctx, page) -> None:
    await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
    await page.locator("[data-chat-row]").first.wait_for(timeout=90_000)
    await page.wait_for_timeout(2500)


def _tally(rows) -> dict:
    owed = [r for r in rows if r["_fanLast"]]
    return {"chats": len(rows), "unread": sum(r["hasUnread"] for r in rows), "owe_reply": len(owed),
            "owe_reply_read": sum(1 for r in owed if not r["hasUnread"])}


def _chip_row(page):
    return page.get_by_role("group", name="Fan List filters")


def _filter_row(page):
    return page.get_by_role("group", name="Inbox, settings and sort")


def _sort_button(page):
    return _filter_row(page).get_by_role("button", name=re.compile(r"^Sort: "))


async def _chips_on_screen(page) -> list[str]:
    return await _chip_row(page).evaluate(
        """g => [...g.querySelectorAll('button')].filter(b => b.getBoundingClientRect().width > 0)
             .map(b => ({ x: b.getBoundingClientRect().left, name: [...b.childNodes]
               .filter(n => !(n.nodeType === 1 && n.classList.contains('absolute')))
               .map(n => n.textContent).join('').trim() }))
             .sort((a, b) => a.x - b.x).map(c => c.name)""")


async def _badge(page, name: str) -> dict:
    return await _chip_row(page).evaluate(
        """(g, name) => { const b = [...g.querySelectorAll('button')]
             .find(b => (b.childNodes[0]?.textContent || '').trim() === name);
           const s = b && b.querySelector('span.absolute');
           return { n: s && /^\\d+$/.test(s.textContent.trim()) ? +s.textContent : null,
                    amber: !!s && s.classList.contains('bg-warn'),
                    pressed: b ? b.getAttribute('aria-pressed') : null }; }""", name)


async def _sort_look(page) -> dict:
    return await page.evaluate(
        """() => { const s = [...document.querySelectorAll('button')].find(b =>
               (b.getAttribute('aria-label') || '').startsWith('Sort: '));
             const chip = document.querySelector('[role=group][aria-label="Fan List filters"] button[aria-pressed=true]');
             const bg = e => e ? getComputedStyle(e).backgroundColor : null;
             return { label: s && s.getAttribute('aria-label'), title: s && s.title,
                      pressed: s && s.getAttribute('aria-pressed'), bg: bg(s), active_chip_bg: bg(chip),
                      w: s && s.getBoundingClientRect().width, h: s && s.getBoundingClientRect().height }; }""")


async def _menu_marks(page) -> dict:
    return await page.locator("section[aria-label=Sort]").evaluate(
        """m => { const rows = [...m.querySelectorAll('button')].map(b => ({
               text: b.textContent.trim(), pressed: b.getAttribute('aria-pressed') }));
             const items = [...m.children].map(e => e.getAttribute('role') === 'separator' ? '|'
               : e.tagName === 'BUTTON' ? [...e.querySelectorAll('span')].find(x => !x.children.length
                   && x.textContent.trim() && x.textContent.trim() !== '✓')?.textContent.trim()
               : e.textContent.trim());
             return { rows, items, marked: rows.filter(r => r.text.startsWith('✓')).map(r => r.text.slice(1)) }; }""")


async def _menu_place(page) -> dict:
    return await page.evaluate(
        """() => { const box = e => { const r = e.getBoundingClientRect();
               return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom) }; };
             const m = box(document.querySelector('section[aria-label=Sort]'));
             const s = box([...document.querySelectorAll('button')].find(b =>
               (b.getAttribute('aria-label') || '').startsWith('Sort: ')));
             const p = box(document.querySelector('[data-mp-pane="fan-list"]'));
             return { menu: m, trigger: s, pane: p, inside: m.l >= p.l && m.r <= p.r,
                      under: m.t >= s.b && m.l < s.r && m.r > s.l }; }""")


async def _rows(page) -> list[dict]:
    return await page.evaluate(
        """() => [...document.querySelectorAll('[data-chat-row]')].map(r => ({
             key: ([...r.querySelectorAll('span')].find(s => /^@\\S+$/.test(s.textContent || '')) || {}).textContent
               || null,
             unread: !!r.querySelector('[role=img][aria-label^="Unread"]') }))""")


async def _row_handles(page) -> list[str]:
    return await page.evaluate(
        """() => [...document.querySelectorAll('[data-chat-row]')].map(r => {
             const h = [...r.querySelectorAll('span')].find(s => /^@\\S+$/.test(s.textContent || ''));
             return h ? h.textContent.slice(1) : null; })""")


async def _no_plus(page) -> dict:
    chips = await _chips_on_screen(page)
    return {"plus_triggers": await page.locator('[data-mp-pane="fan-list"]').get_by_role("button", name=PLUS).count(),
            "lists_chips": await _chip_row(page).get_by_role("button", name=re.compile(r"✎|^Lists$")).count(),
            "plus_chips": sum(c == "+" for c in chips)}


async def _filter_lines(page) -> dict:
    return await _filter_row(page).evaluate(
        """g => { const items = [...g.children].filter(e => e.getBoundingClientRect().width > 0 &&
               e.childElementCount > 0);
             const mids = items.map(e => { const r = e.getBoundingClientRect(); return (r.top + r.bottom) / 2; });
             const lines = mids.filter((m, i) => mids.slice(0, i).every(o => Math.abs(o - m) > 6)).length;
             return { lines, row_width: Math.round(g.getBoundingClientRect().width),
                      items: items.map(e => { const r = e.getBoundingClientRect();
                        const b = e.querySelector('button') || e;
                        return (b.getAttribute('aria-label') || b.textContent || '').trim().slice(0, 24)
                          + ' @' + Math.round(r.left) + '-' + Math.round(r.right) + ',' + Math.round(r.top); }) }; }""")


async def _crop(ctx, page, name: str) -> str:
    box = await page.evaluate(
        """() => { const a = document.querySelector('[role=group][aria-label="Inbox, settings and sort"]');
             const b = document.querySelector('[role=group][aria-label="Fan List filters"]');
             const r = [a, b].map(e => e.getBoundingClientRect());
             const pane = b.parentElement.getBoundingClientRect();
             return { x: pane.left, y: Math.min(r[0].top, r[1].top) - 6,
                      w: pane.width, h: Math.max(r[0].bottom, r[1].bottom) - Math.min(r[0].top, r[1].top) + 12 }; }""")
    path = ctx.out / "screenshots" / f"{name}.png"
    await page.screenshot(path=str(path), clip={"x": box["x"], "y": max(0, box["y"]), "width": box["w"],
                                                "height": box["h"]})
    return str(path)


async def _creator_tab(page, creator) -> None:
    tab = page.get_by_role("tab", name=creator["nickname"])
    if await tab.count() and await tab.first.is_visible():
        await tab.first.click()
    else:
        await page.get_by_role("combobox", name="Creator").click()
        await page.get_by_role("option", name=creator["nickname"]).first.click()
    await page.get_by_role("button", name="All inboxes").wait_for(timeout=30_000)
    await page.wait_for_timeout(1500)


async def _pencil_shown(page, timeout_ms: int) -> bool:
    try:
        await _filter_row(page).get_by_role("button", name=PIN_LISTS).wait_for(timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001 — absent
        return False


def _console_errors(ctx, aborted: list[str]) -> list[dict]:
    path = ctx.out / "console-fan-list.jsonl"
    rows = [json.loads(ln) for ln in path.read_text().splitlines()] if path.exists() else []
    off = set(aborted)
    return [r for r in rows if r["type"] in ("error", "pageerror")
            and not (r["text"].startswith("Failed to load resource") and r.get("at", "").rsplit(":", 2)[0] in off)]


async def _search(ctx, page, served: list[str], view, creator, shots: dict) -> dict:
    rows = view[creator["id"]]
    name = next(r["withUser"]["name"] for r in rows if r["withUser"].get("name"))
    want = sorted(r["withUser"]["username"] for r in rows if name.lower() in (r["withUser"].get("name") or "").lower())
    start = len(served)
    await page.get_by_role("group", name="Fan List header").get_by_role("button", name="Search").click()
    box = page.get_by_placeholder("Search…")
    t0 = asyncio.get_running_loop().time()
    await box.press_sequentially(name, delay=SEARCH_KEY_MS)
    typed_s = asyncio.get_running_loop().time() - t0
    shots["p"] = await ui.shot(ctx, page, "p-search-name-typed")
    settled = True
    try:
        await page.wait_for_function("n => document.querySelectorAll('[data-chat-row]').length === n",
                                     arg=len(want), timeout=15_000)
    except Exception:  # noqa: BLE001 — judged below
        settled = False
    await page.wait_for_timeout(1500)
    handles = sorted(h or "" for h in await _row_handles(page))
    shots["q"] = await ui.shot(ctx, page, "q-search-settled")
    sent = [{k: v[0] for k, v in parse_qs(urlsplit(u).query).items()} for u in served[start:]]
    searches = [q["query"] for q in sent if q.get("query")]
    await page.keyboard.press("Escape")
    out = {"typed": name, "keys": len(name), "typed_s": round(typed_s, 2), "searches": searches,
           "rows": handles, "want": want, "settled": settled}
    ctx.check(C_SEARCH, searches == [name] and handles == want and settled, **out)
    return out


async def _screens(ctx, view, creators) -> None:
    c0, c1 = creators[0], creators[1]
    lists, pins = _lists_fixture(c0["id"])
    shots: dict[str, str] = {}
    console = _Console(ctx, "fan-list")
    aborted: list[str] = []
    statuses: list[tuple[int, str]] = []
    shot = lambda page, n: ui.shot(ctx, page, n)  # noqa: E731

    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        console.watch(page.context)
        served, loaded = await _open(ctx, page, view, lists, pins)
        lt = _tally(loaded.values())
        shots["a"] = await shot(page, "a-all-models-400px-pane")
        chips_all = await _chips_on_screen(page)
        no_plus_all = await _no_plus(page)
        unread = await _badge(page, "Unread")
        ctx.check(C_UNREAD, unread["n"] == lt["unread"], ui=unread["n"], loaded=lt["unread"])
        owe_off = await _badge(page, "Owe reply")
        pencil_all_models = await _pencil_shown(page, 3000)
        lines_all = await _filter_lines(page)
        dots_all = await page.get_by_label(OWE_DOT, exact=True).count()

        await _chip_row(page).get_by_role("button", name=re.compile(r"^Owe reply\b")).click()
        await page.wait_for_timeout(1500)
        handles = await _row_handles(page)
        n_rows = len(handles)
        lt = _tally(loaded.values())
        owed = sorted(r["withUser"].get("username") or "" for r in loaded.values() if r["_fanLast"])
        owe_on = await _badge(page, "Owe reply")
        dots_on = await page.get_by_label(OWE_DOT, exact=True).count()
        shots["b"] = await shot(page, "b-owe-reply-active")
        ctx.check(C_OWE, owe_off["n"] == owe_on["n"] == lt["owe_reply"] and owe_off["amber"] and owe_on["amber"]
                  and owe_off["pressed"] == "false" and owe_on["pressed"] == "true",
                  off=owe_off, on=owe_on, loaded=lt["owe_reply"])
        ctx.check(C_OWE_ROWS, sorted(h or "" for h in handles) == owed and all(owed),
                  rows=n_rows, loaded=lt["owe_reply"], missing=sorted(set(owed) - set(handles))[:5],
                  extra=sorted(set(handles) - set(owed), key=str)[:5])
        ctx.check(C_DOTS, dots_all == 0 and dots_on == lt["owe_reply_read"],
                  in_all=dots_all, in_owe=dots_on, loaded_read_owed=lt["owe_reply_read"])
        await _chip_row(page).get_by_role("button", name="All", exact=True).click()
        await page.wait_for_timeout(800)

        rows_newest = await _rows(page)
        look_default = await _sort_look(page)
        await _sort_button(page).click()
        await page.locator("section[aria-label=Sort]").wait_for()
        marks_default = await _menu_marks(page)
        place_all = await _menu_place(page)
        shots["c"] = await shot(page, "c-sort-menu-newest-first-checked")
        await page.locator("section[aria-label=Sort]").get_by_role("button", name=re.compile(
            "^" + re.escape(EXTRA_SORT))).click()
        await _filter_row(page).get_by_role("button", name=f"Sort: {EXTRA_SORT}").wait_for(timeout=10_000)
        await page.wait_for_timeout(800)
        look = await _sort_look(page)
        rows_sorted = await _rows(page)
        shots["d"] = await shot(page, "d-extra-sort-active")
        await _sort_button(page).click()
        await page.locator("section[aria-label=Sort]").wait_for()
        marks = await _menu_marks(page)
        shots["e"] = await shot(page, "e-sort-menu-extra-checked")
        await page.keyboard.press("Escape")
        flags = [r["unread"] for r in rows_sorted]
        unread_first = flags == sorted(flags, reverse=True)
        reordered = ([r["key"] for r in rows_sorted] != [r["key"] for r in rows_newest]
                     and sorted(r["key"] or "" for r in rows_sorted) == sorted(r["key"] or "" for r in rows_newest)
                     and all(r["key"] for r in rows_sorted))
        ctx.check(C_SORT, look_default["pressed"] == "false" and look_default["bg"] != look["active_chip_bg"]
                  and marks_default["marked"] == ["Newest first"]
                  and look["label"] == look["title"] == f"Sort: {EXTRA_SORT}" and look["pressed"] == "true"
                  and look["bg"] == look["active_chip_bg"]
                  and len(marks["marked"]) == 1 and marks["marked"][0].startswith(EXTRA_SORT)
                  and unread_first and reordered,
                  default=look_default, chosen=look, menu_default=marks_default["marked"], menu=marks["marked"],
                  unread_first=unread_first, reordered=reordered, rows=len(rows_sorted),
                  unread_rows=sum(flags))

        stored = await page.evaluate(f"() => localStorage.getItem({json.dumps(SORT_KEY)})")
        await _goto(ctx, page)
        after_reload = await _sort_look(page)
        ctx.check(C_SORT_STORED, stored == "spend-unread" and after_reload["label"] == f"Sort: {EXTRA_SORT}",
                  stored=stored, after_reload=after_reload)
        await _sort_button(page).click()
        await page.locator("section[aria-label=Sort]").get_by_role("button", name="Newest first").click()

        await _creator_tab(page, c0)
        pencil_c0 = await _pencil_shown(page, 30_000)
        lines_one = await _filter_lines(page)
        no_plus_one = await _no_plus(page)
        ctx.check(C_NO_PLUS, not any(no_plus_all.values()) and not any(no_plus_one.values()) and pencil_c0,
                  all_models=no_plus_all, one_creator=no_plus_one, one_creator_has_lists=pencil_c0)
        shots["f"] = await shot(page, "f-one-creator-400px-pane")
        await _sort_button(page).click()
        await page.locator("section[aria-label=Sort]").wait_for()
        place_one = await _menu_place(page)
        shots["f2"] = await shot(page, "f2-sort-menu-one-creator")
        await page.keyboard.press("Escape")
        ctx.check(C_MENU_PLACE, all(p["inside"] and p["under"] for p in (place_all, place_one)),
                  all_models=place_all, one_creator=place_one)
        picker_open = False
        pinned_chip = False
        chips_pinned: list[str] = []
        if pencil_c0:
            await _filter_row(page).get_by_role("button", name=PIN_LISTS).click()
            try:
                await page.get_by_text("Pin folders to chat sidebar").wait_for(timeout=10_000)
                picker_open = True
            except Exception:  # noqa: BLE001 — the picker did not open
                pass
        if picker_open:
            await page.wait_for_timeout(300)
            shots["g"] = await shot(page, "g-pencil-picker-open")
            box = page.locator("label").filter(has_text=PINNED).get_by_role("checkbox")
            await box.click()
            await page.wait_for_function(
                "name => [...document.querySelectorAll('label')].some(l => l.textContent.includes(name)"
                " && l.querySelector('input').checked && !l.querySelector('input').disabled)", arg=PINNED,
                timeout=15_000)
            shots["g2"] = await shot(page, "g2-pencil-picker-one-pinned")
            await page.get_by_role("button", name="Done").click()
            try:
                await _chip_row(page).get_by_role("button", name=f"Folder {PINNED}").wait_for(timeout=15_000)
                pinned_chip = True
            except Exception:  # noqa: BLE001 — no chip
                pass
            await page.wait_for_timeout(500)
            chips_pinned = await _chips_on_screen(page)
            shots["h"] = await shot(page, "h-list-pinned-as-chip")
            shots["hc"] = await _crop(ctx, page, "h-list-pinned-as-chip-crop")
            await _chip_row(page).get_by_role("button", name=f"Folder {PINNED}").scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            shots["hs"] = await _crop(ctx, page, "h-list-pinned-chip-scrolled-into-view-crop")
        ctx.check(C_PIN, pinned_chip and pins == [{"account": c0["id"], "list": 9001, "pinned": True, "known": True}],
                  pins=pins, chip=pinned_chip, picker_open=picker_open)

        await _creator_tab(page, c1)
        pencil_c1 = await _pencil_shown(page, 5000)
        ctx.check(C_PENCIL, not pencil_all_models and pencil_c0 and picker_open and not pencil_c1,
                  all_models=pencil_all_models, with_lists=pencil_c0, picker_open=picker_open, no_lists=pencil_c1)
        ctx.check(C_ONE_LINE, lines_all["lines"] == 1 and lines_one["lines"] == 1,
                  all_models=lines_all, one_creator=lines_one)

        want_pinned = CHIPS[:5] + [f"Folder {PINNED}"] + CHIPS[5:]
        ctx.check(C_ORDER, chips_all == CHIPS and chips_pinned == want_pinned,
                  all_models=chips_all, one_creator_pinned=chips_pinned, want=CHIPS, want_pinned=want_pinned)
        search = await _search(ctx, page, served, view, c1, shots)
        ctx.metric("ui", {"chats_reads_answered": len(served), "loaded": lt, "owe_badge": owe_off, "owe_rows": n_rows,
                          "owe_dots": dots_on, "sort": look, "sort_menu": marks, "stored_sort": stored,
                          "pin_writes": pins, "filter_row_all_models": lines_all,
                          "filter_row_one_creator": lines_one, "search": search})
        aborted += page.slop["offhost_aborted"]
        statuses += page.slop["statuses"]

    async with ui.owner_browser(ctx, viewport=VIEWPORT, scale=2) as page:
        console.watch(page.context)
        await _open(ctx, page, view, lists, pins)
        shots["i"] = await _crop(ctx, page, "i-all-models-filter-and-chip-rows@2x")
        await _creator_tab(page, c0)
        await _pencil_shown(page, 30_000)
        shots["j"] = await _crop(ctx, page, "j-one-creator-filter-and-chip-rows@2x")
        await _chip_row(page).get_by_role("button", name=f"Folder {PINNED}").scroll_into_view_if_needed()
        await page.wait_for_timeout(300)
        shots["js"] = await _crop(ctx, page, "j-one-creator-chip-row-scrolled-to-pinned-list@2x")
        aborted += page.slop["offhost_aborted"]
        statuses += page.slop["statuses"]

    async with ui.owner_browser(ctx, viewport=NARROW, scale=2) as page:
        console.watch(page.context)
        await _open(ctx, page, view, lists, pins)
        shots["k"] = await shot(page, f"k-narrow-{NARROW[0]}")
        shots["kc"] = await _crop(ctx, page, f"k-narrow-{NARROW[0]}-crop@2x")
        narrow_all = await _filter_lines(page)
        await _creator_tab(page, c0)
        await _pencil_shown(page, 30_000)
        narrow_one = await _filter_lines(page)
        shots["l"] = await _crop(ctx, page, f"l-narrow-{NARROW[0]}-one-creator-crop@2x")
        ctx.metric("narrow", {"viewport": NARROW, "all_models": narrow_all, "one_creator": narrow_one})
        ctx.note(f"filter row at {NARROW[0]}px: All Models {narrow_all['lines']} line(s), "
                 f"one Creator {narrow_one['lines']} line(s)")
        aborted += page.slop["offhost_aborted"]
        statuses += page.slop["statuses"]

    async with ui.owner_browser(ctx, viewport=PHONE, scale=2) as page:
        console.watch(page.context)
        await _open(ctx, page, view, lists, pins)
        shots["m"] = await shot(page, f"m-phone-{PHONE[0]}-sort-trigger")
        await _sort_button(page).click()
        await page.locator("section[aria-label=Sort]").wait_for()
        marks_phone = await _menu_marks(page)
        shots["n"] = await shot(page, f"n-phone-{PHONE[0]}-sort-menu-open")
        await page.locator("section[aria-label=Sort]").get_by_role("button", name=re.compile("^Amount spent")).click()
        await _filter_row(page).get_by_role("button", name="Sort: Amount spent").wait_for(timeout=10_000)
        stored_phone = await page.evaluate(f"() => localStorage.getItem({json.dumps(SORT_KEY)})")
        look_phone = await _sort_look(page)
        shots["o"] = await shot(page, f"o-phone-{PHONE[0]}-amount-spent-settled")
        ctx.check(C_MENU_ORDER, marks_default["items"] == marks_phone["items"] == SORT_MENU,
                  desktop=marks_default["items"], phone=marks_phone["items"])
        ctx.check(C_PHONE_PICK, stored_phone == "spend" and look_phone["label"] == "Sort: Amount spent",
                  stored=stored_phone, label=look_phone["label"])
        ctx.metric("phone", {"viewport": PHONE, "sort_menu": marks_phone, "stored_sort": stored_phone})
        aborted += page.slop["offhost_aborted"]
        statuses += page.slop["statuses"]

    errors = _console_errors(ctx, aborted)
    ctx.check(C_CONSOLE, not errors, count=len(errors), sample=[e["text"][:300] for e in errors[:5]])
    relay_5xx = [u for s, u in statuses if s >= 500 and "/api/of/" not in u]
    ctx.check(C_5XX, not relay_5xx, count=len(relay_5xx), sample=relay_5xx[:5])
    ctx.metric("screenshots", shots)
