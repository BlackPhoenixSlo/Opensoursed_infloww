"""The view-lease scenario's `visible` leg (ticket 20; scenarios/2026-11-09-view-lease-purchases-tiers.py): only
on-screen Creators hold a View lease. The owner's pages in Chromium in the All view (scope `all`, nothing selected), against the
page's own `POST /admin/view-lease` bodies and its on-screen set (the strip's tabs, the Money Rail's rows, OF Manager's
Creator column's rows, each box against its scroller's clip and the viewport, sampled every VIS_SAMPLE_S; plus the open
chat's Creator):

  strip    Messages Pro at scrollLeft 0: a post equal to the on-screen set (within VIS_MATCH_S: a loss waits for the
           app's 20 s tick); scrolled to the end: a post naming every tab that came on screen within VIS_GAIN_S (a gain
           posts at once) and one equal to the new set within VIS_MATCH_S; both sets differ and hold fewer than every
           Creator. Screenshots `visible-strip-start`, `visible-strip-end`.
  hidden   the page hidden for VIS_HIDDEN_S (> the app's 20 s renewal): no post, and the Relay's registry drops those
           Creators within TTL_S + VIS_LAPSE_SLACK_S of the last post; shown again, a post within VIS_RETURN_S equal to
           the on-screen set.
  chat     OF's chat list holds each Creator's first Fan (at the wire); a chat-list row clicked (the All view keeps no
           selection) whose Creator the strip can scroll off and the rail does not show; the strip scrolled so its tab
           is off: a post equal to strip + rail + that Creator, with no `selected` (the open chat's lease). Screenshot
           `visible-chat`.
  column   OF Manager (`/of-manager/home`, viewport VIS_COLUMN_VIEWPORT so the column overflows): a post equal to the
           column's on-screen rows (+ any other on-screen source); the column scrolled to the end: the gain within
           VIS_GAIN_S and a post equal to the new set within VIS_MATCH_S, both fewer than every Creator. Screenshots
           `visible-column-start`, `visible-column-end`.

`through`: the /api/of/ reads let through (the chat list's). At most VIS_MAX_POSTS posts per page (no post storm).
Bypasses (declared): OF's chat list at the wire (`chats[uid]`); the hidden tab: `document.visibilityState` / `hidden`
overridden to "hidden" and a `visibilitychange` dispatched (Chromium headless keeps every page visible), restored the
same way. The app's renewal (VIEW_LEASE_RENEW_MS 20 s) is not scaled (a front constant), so with the scaled TTL a shown
tab's lease also lapses between its posts: the leg reads the posts, and the registry only for the hidden lapse.
Fault `strip-leases-all-tabs` (lib/view_lease_faults.py): only UI_LEASE_VISIBLE.
"""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

from slop.lib.view_lease_faults import UI_LEASE_VISIBLE

APP_RENEW_S = 20.0
VIS_SAMPLE_S = 0.25
VIS_MATCH_S = APP_RENEW_S + 4.0    # a post equal to the on-screen set: a loss waits for the next tick
VIS_GAIN_S = 3.0                   # a gain posts at once
VIS_HIDDEN_S = APP_RENEW_S + 4.0   # hidden past one renewal: no post
VIS_LAPSE_SLACK_S = 1.5            # the registry read every VIS_SAMPLE_S, plus the post's own trip
VIS_RETURN_S = 3.0                 # shown again: a post at once
VIS_VIEWPORT = (1280, 900)         # the strip (58vw) shows about 7 of the 10 small-scale tabs
VIS_COLUMN_VIEWPORT = (1280, 500)  # OF Manager's column shows about 5 of its 10 rows
VIS_MAX_POSTS = 30                 # per page: opening, layout, gains, a few ticks, the return; never a storm

_ON_SCREEN_JS = r"""
() => {
  const vis = (el, clip) => {
    const q = el.getBoundingClientRect();
    const c = clip ? clip.getBoundingClientRect() : {left: 0, top: 0, right: innerWidth, bottom: innerHeight};
    const w = Math.min(q.right, c.right, innerWidth) - Math.max(q.left, c.left, 0);
    const h = Math.min(q.bottom, c.bottom, innerHeight) - Math.max(q.top, c.top, 0);
    return w > 0 && h > 0;
  };
  const list = document.querySelector('[role="tablist"][aria-label="Creator tabs"]');
  const strip = [];
  for (const b of list ? list.querySelectorAll('[role="tab"]') : []) {
    if (vis(b.parentElement || b, list)) strip.push((b.getAttribute("title") || "").split(" — ")[0]);
  }
  // The Money Rail's rows: each links /messages-pro/<Creator>/<fan>.
  const rail = [];
  for (const a of document.querySelectorAll('.overscroll-contain a[href^="/messages-pro/"]')) {
    if (vis(a, a.closest('.overscroll-contain'))) rail.push(decodeURIComponent(a.getAttribute("href").split("/")[2]));
  }
  // OF Manager's Creator column (a watcher row is no Creator).
  const column = [];
  const rows = document.querySelectorAll('[data-testid="of-creator-row"]:not([data-watcher])');
  for (const r of rows) {
    if (vis(r, r.closest('.overflow-y-auto'))) column.push((r.getAttribute("title") || "").split(" · ")[0]);
  }
  const col = rows.length ? rows[0].closest('.overflow-y-auto') : null;
  return {strip, rail, column, scroll_w: list ? list.scrollWidth : 0, client_w: list ? list.clientWidth : 0,
          scroll_left: list ? list.scrollLeft : 0, col_scroll_h: col ? col.scrollHeight : 0,
          col_client_h: col ? col.clientHeight : 0};
}
"""
_HIDE_JS = r"""
(hide) => {
  if (hide) {
    Object.defineProperty(document, "visibilityState", {configurable: true, get: () => "hidden"});
    Object.defineProperty(document, "hidden", {configurable: true, get: () => true});
  } else {
    delete document.visibilityState;
    delete document.hidden;
  }
  document.dispatchEvent(new Event("visibilitychange", {bubbles: true}));
  return document.visibilityState;
}
"""
_STRIP_TO = ("(left) => { const l = document.querySelector('[role=\"tablist\"][aria-label=\"Creator tabs\"]');"
             " l.scrollLeft = left ? 0 : l.scrollWidth; }")
_COLUMN_TO_END = ("() => { const r = document.querySelector('[data-testid=\"of-creator-row\"]');"
                  " const l = r.closest('.overflow-y-auto'); l.scrollTop = l.scrollHeight; }")
_CHAT_ROWS_JS = "() => [...document.querySelectorAll('[data-chat-row]')].map((r) => r.innerText || '')"


def _pick(d: dict | None, key: str) -> list[str]:
    return list((d or {}).get(key) or [])


async def run(ctx, creators: list[str], ttl_s: float, through=()) -> None:
    if not ctx.ui:
        ctx.skip(UI_LEASE_VISIBLE, "--no-ui: no browser")
        return
    from slop.actors import ui

    w = ctx.world
    id_of = {c["nickname"]: c["id"] for c in w.data["creators"]}
    # OF's chat list: each Creator's first Fan (at the wire, `chats[uid]`), so the All view lists one chat per Creator.
    fake = ctx.of_wire
    head = {aid: w.data["fans"][aid][0] for aid in creators}
    with fake.lock:
        for i, aid in enumerate(creators):
            f = head[aid]
            rows = fake.chats.setdefault(aid, [])
            if not any(c["withUser"]["id"] == f["id"] for c in rows):
                rows.append({"withUser": {"id": f["id"], "name": f["name"], "username": f["username"], "_view": "s"},
                             "unreadMessagesCount": 0,
                             "lastMessage": {"id": 7_100_000 + i, "text": "hey", "fromUser": {"id": f["id"]},
                                             "isFree": True, "price": 0,
                                             "createdAt": f"2026-11-09T{10 + i % 10}:{i // 10:02d}:00+00:00"}})
    hook = ctx.owner.share(limits=2)
    await asyncio.sleep(ttl_s + 1.0)          # the earlier legs' httpx tabs lapse
    reg0 = (await hook.get("/__slop/view-lease")).json().get("leased", [])
    posts: list[dict] = []
    samples: list[dict] = []
    registry: list[dict] = []
    t: dict[str, float] = {}
    shots: list[str] = []
    chat: dict = {"aid": None}
    stop = asyncio.Event()

    async with ui.owner_browser(ctx, viewport=VIS_VIEWPORT, through=through) as page:
        def on_request(req) -> None:
            if req.method == "POST" and urlsplit(req.url).path == "/admin/view-lease":
                try:
                    body = json.loads(req.post_data or "{}")
                except ValueError:
                    body = {}
                posts.append({"t": time.time(), "page": urlsplit(page.url).path, "body": body})

        page.on("request", on_request)
        await page.add_init_script("try { localStorage.setItem('chatterly:scope', 'all'); } catch (e) {}")

        async def on_screen() -> dict | None:
            try:
                d = await page.evaluate(_ON_SCREEN_JS)
            except Exception:  # noqa: BLE001 — a navigation in flight
                return None
            d["strip"] = sorted(id_of.get(n, f"?{n}") for n in d["strip"])
            d["column"] = sorted(id_of.get(n, f"?{n}") for n in d["column"])
            d["chat"] = [chat["aid"]] if chat["aid"] else []
            d["ids"] = sorted(set(d["strip"]) | set(d["rail"]) | set(d["column"]) | set(d["chat"]))
            d["t"] = time.time()
            samples.append(d)
            return d

        async def sampler() -> None:
            while not stop.is_set():
                await on_screen()
                r = await hook.get("/__slop/view-lease")
                registry.append({"t": time.time(), "leased": r.json().get("leased", [])})
                try:
                    await asyncio.wait_for(stop.wait(), VIS_SAMPLE_S)
                except asyncio.TimeoutError:
                    pass

        async def matched(since: float, timeout_s: float) -> dict | None:
            """The first moment a post made after `since` names exactly the on-screen set."""
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                d = await on_screen()
                last = next((p for p in reversed(posts) if p["t"] >= since), None)
                if d and d["ids"] and last and sorted(last["body"].get("account_ids") or []) == d["ids"]:
                    return {"t": last["t"], "ids": d["ids"], "body": last["body"], "dom": d}
                await asyncio.sleep(VIS_SAMPLE_S)
            return None

        async def gained(since: float, before: list[str], timeout_s: float) -> dict | None:
            """The first post after `since` naming every row that came on screen."""
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                d = await on_screen()
                new = set(d["ids"]) - set(before) if d else set()
                p = next((p for p in posts if p["t"] >= since and new <= set(p["body"].get("account_ids") or [])),
                         None) if new else None
                if p is not None:
                    return {"t": p["t"], "new": sorted(new), "ids": sorted(p["body"].get("account_ids") or [])}
                await asyncio.sleep(VIS_SAMPLE_S)
            return None

        # ── strip ──
        t["open"] = time.time()
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        await page.get_by_role("tablist", name="Creator tabs").wait_for(timeout=90_000)
        smp = asyncio.create_task(sampler())
        pos1 = await matched(t["open"], VIS_MATCH_S)
        shots.append(await ui.shot(ctx, page, "visible-strip-start"))
        t["scroll"] = time.time()
        await page.evaluate(_STRIP_TO, False)
        gain = await gained(t["scroll"], (pos1 or {}).get("ids") or [], VIS_GAIN_S)
        pos2 = await matched(t["scroll"], VIS_MATCH_S)
        shots.append(await ui.shot(ctx, page, "visible-strip-end"))
        # ── hidden ──
        t["hide"] = time.time()
        state_hidden = await page.evaluate(_HIDE_JS, True)
        await asyncio.sleep(VIS_HIDDEN_S)
        t["show"] = time.time()
        state_shown = await page.evaluate(_HIDE_JS, False)
        back = await matched(t["show"], VIS_RETURN_S)
        # ── chat: a Creator the strip can scroll off (on one end, not the other) and the rail does not show ──
        d0 = await on_screen()
        movable = set(_pick((pos1 or {}).get("dom"), "strip")) ^ set(_pick((pos2 or {}).get("dom"), "strip"))
        texts = await page.evaluate(_CHAT_ROWS_JS)
        want = movable - set(_pick(d0, "rail"))
        row = next(((i, a) for i, x in enumerate(texts) for a in want if head[a]["username"] in x), None)
        chat_out: dict = {"rows_listed": len(texts), "movable": sorted(movable), "row": row}
        chat_pos = None
        if row:
            aid = row[1]
            n0 = len(posts)
            await page.locator("[data-chat-row]").nth(row[0]).click()
            chat["aid"] = aid
            t["chat"] = time.time()
            await page.evaluate(_STRIP_TO, aid not in _pick((pos1 or {}).get("dom"), "strip"))
            chat_pos = await matched(t["chat"], VIS_MATCH_S)
            shots.append(await ui.shot(ctx, page, "visible-chat"))
            dom = (chat_pos or {}).get("dom") or {}
            chat_out |= {"aid": aid, "pos": chat_pos and {"t": chat_pos["t"], "ids": chat_pos["ids"]},
                         "off_strip": aid not in _pick(dom, "strip"), "off_rail": aid not in _pick(dom, "rail"),
                         "selected": sorted({str(p["body"].get("selected")) for p in posts[n0:]
                                             if p["body"].get("selected") is not None})}
            chat["aid"] = None
        # ── column: OF Manager, a new document load ──
        await page.set_viewport_size({"width": VIS_COLUMN_VIEWPORT[0], "height": VIS_COLUMN_VIEWPORT[1]})
        t["column"] = time.time()
        await page.goto(f"{ctx.app}/of-manager/home", wait_until="domcontentloaded")
        await page.locator('[data-testid="of-creator-row"]').first.wait_for(timeout=90_000)
        col1 = await matched(t["column"], VIS_MATCH_S)
        shots.append(await ui.shot(ctx, page, "visible-column-start"))
        t["column_scroll"] = time.time()
        await page.evaluate(_COLUMN_TO_END)
        col_gain = await gained(t["column_scroll"], (col1 or {}).get("ids") or [], VIS_GAIN_S)
        col2 = await matched(t["column_scroll"], VIS_MATCH_S)
        shots.append(await ui.shot(ctx, page, "visible-column-end"))
        stop.set()
        await smp

    strip_posts = [p for p in posts if p["t"] < t.get("column", float("inf"))]
    last_before_hide = max((p["t"] for p in posts if p["t"] < t["hide"]), default=None)
    hidden_posts = [p for p in posts if t["hide"] <= p["t"] < t["show"]]
    held = set((pos2 or {}).get("ids") or ())
    # The lapse: the first registry read without those Creators after one that held them (the last post's).
    after_last = [r for r in registry if last_before_hide and r["t"] >= last_before_hide]
    held_at = next((i for i, r in enumerate(after_last) if held and held <= set(r["leased"])), None)
    lapsed_at = next((r["t"] for r in after_last[held_at or 0:] if not set(r["leased"]) & held), None) \
        if held_at is not None else None
    lapse_s = round(lapsed_at - last_before_hide, 2) if lapsed_at and last_before_hide else None
    selected = sorted({str(p["body"].get("selected")) for p in posts if p["body"].get("selected") is not None})
    overflow = any(d["scroll_w"] > d["client_w"] for d in samples)
    col_overflow = any(d["col_scroll_h"] > d["col_client_h"] for d in samples)
    since = lambda x, k: x and round(x["t"] - t[k], 2)  # noqa: E731
    out = {
        "registry_before": reg0, "creators": len(creators), "viewport": VIS_VIEWPORT, "max_posts": VIS_MAX_POSTS,
        "posts_n": {"messages_pro": len(strip_posts), "of_manager": len(posts) - len(strip_posts)},
        "strip": {"overflow": overflow, "pos1": pos1 and {"t": pos1["t"], "ids": pos1["ids"]},
                  "gain": gain and {**gain, "after_scroll_s": since(gain, "scroll")}, "gain_within_s": VIS_GAIN_S,
                  "pos2": pos2 and {"t": pos2["t"], "ids": pos2["ids"], "after_scroll_s": since(pos2, "scroll")}},
        "hidden": {"state": state_hidden, "for_s": VIS_HIDDEN_S, "posts": len(hidden_posts),
                   "last_post_before_s": round(t["hide"] - last_before_hide, 2) if last_before_hide else None,
                   "lapse_after_last_post_s": lapse_s, "ttl_s": ttl_s, "slack_s": VIS_LAPSE_SLACK_S},
        "shown": {"state": state_shown, "post_after_s": since(back, "show"), "ids": back and back["ids"]},
        "chat": chat_out, "selected_posted": selected,
        "column": {"viewport": VIS_COLUMN_VIEWPORT, "overflow": col_overflow,
                   "pos1": col1 and {"t": col1["t"], "ids": col1["ids"], "column": _pick(col1["dom"], "column")},
                   "gain": col_gain and {**col_gain, "after_scroll_s": since(col_gain, "column_scroll")},
                   "pos2": col2 and {"t": col2["t"], "ids": col2["ids"], "column": _pick(col2["dom"], "column"),
                                     "after_scroll_s": since(col2, "column_scroll")}},
        "screenshots": shots,
    }
    few = lambda x: x is not None and 0 < len(x["ids"]) < len(creators)  # noqa: E731
    ok_strip = (not reg0 and overflow and few(pos1) and gain is not None and few(pos2)
                and pos1["ids"] != pos2["ids"])
    ok_hidden = (state_hidden == "hidden" and not hidden_posts and lapse_s is not None
                 and lapse_s <= ttl_s + VIS_LAPSE_SLACK_S and state_shown == "visible" and back is not None)
    ok_chat = (chat_pos is not None and chat_out["aid"] in chat_pos["ids"] and chat_out["off_strip"]
               and chat_out["off_rail"] and not chat_out["selected"])
    ok_column = (col_overflow and few(col1) and col_gain is not None and few(col2) and col1["ids"] != col2["ids"]
                 and bool(_pick(col1["dom"], "column")))
    ok = (ok_strip and ok_hidden and ok_chat and ok_column and not selected
          and max(len(strip_posts), len(posts) - len(strip_posts)) <= VIS_MAX_POSTS)
    out["parts_ok"] = {"strip": ok_strip, "hidden": ok_hidden, "chat": ok_chat, "column": ok_column}
    (ctx.out / "ui-lease-visible.json").write_text(json.dumps({
        **out, "t": t, "posts": posts, "samples": samples, "registry": registry}, indent=1, default=str))
    ctx.check(UI_LEASE_VISIBLE, ok, **out)
