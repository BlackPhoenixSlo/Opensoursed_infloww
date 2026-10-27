"""Phone gestures: the owner on a phone (390x844, touch input) swipes through the
dashboard's nav menu and Messages Pro, and uses the platform's back.

Flow: the inbox world (`agency_inbox`). On a dashboard page (`/`): a vertical
drag, a swipe right from the OS's edge zone, a drag that starts sideways, turns
vertical and ends sideways, then a swipe right from mid-screen
(opens the nav menu) and a swipe left on the menu (closes it). On Messages Pro:
a mid-screen swipe on the Fan List (no menu there); a chat opened by a tap,
then back twice (history.back(), what iOS's edge swipe and Android's back do);
a chat, then a later page, back to the Fan List and Forward twice;
a chat whose Thread gets a cancelled sideways swipe while it is still pinned to
the latest message, then a swipe right (back to the Fan List); Fan insights
closed by a swipe right; a reload with a chat open. Then the same gestures at
desktop width (1600px, touch input).

Invariants: phone: the menu opens only for the mid-screen swipe and closes on
the swipe left (not for the drag that turned vertical); Messages Pro never opens
it; opening a chat adds one same-URL history entry, back returns to the Fan List
still on Messages Pro and a second back leaves it; Forward onto that entry stays
there (no bounce back) and the next Forward reaches the later page; a cancelled sideways swipe leaves the Thread pinned ("Jumping
to latest" stays) and a vertical drag releases it; the Thread's swipe right
returns to the Fan List through that entry (Messages Pro kept, the entry
gone); Fan insights' swipe right closes only Fan insights; a reload with a chat
open lands on the Fan List with no chat entry left, so one back leaves.
Desktop: nothing opens or closes and no history entry. No 5xx from the relay
in either browser. There is no volume here, so no latency budget: the settle
times are metrics only.

Fault `mobile-chat-no-history-entry` (no pushState when a chat opens, as before
2026-10-26) must turn only the three checks of that entry red: back, Forward, and
the Thread swipe through it. `mobile-chat-forward-bounce` (Forward onto the entry
goes back again) turns only Forward red; `mobile-swipe-ignores-turn` (a swipe
locked sideways ignores a later vertical move and the scroll) only the turned drag.

Bypasses, declared: swipes are Chromium touch input through CDP
(Input.dispatchTouchEvent), not a phone's OS: iOS Safari's and Android's own
edge-back gestures are not in the loop, so "the OS edge zone" check only
proves the page ignores a touch starting there; history.back() stands in for
them. Every /api/of/* read stays held (actors/ui.py), so the Fan List and the
Thread show the relay's own seed.
"""
from __future__ import annotations

import time

from slop.actors import ui

PROFILE = "agency_inbox"
UI = True
FAULT = "mobile-chat-no-history-entry"
PHONE = (390, 844)  # iPhone 13
DESKTOP = (1600, 1000)
JUMPING = "Jumping to latest"

C_SCROLL = "phone: a vertical drag on a dashboard page does not open the nav menu"
C_EDGE = "phone: a swipe right starting in the OS edge zone (x < 24px) does not open the nav menu"
C_TURN = "phone: a drag that starts sideways, turns vertical and ends sideways does not open the nav menu"
C_OPEN = "phone: a swipe right from mid-screen on a dashboard page opens the nav menu (URL unchanged)"
C_CLOSE = "phone: a swipe left on the open nav menu closes it"
C_MP_NO_MENU = "phone: Messages Pro has no swipe-to-open menu"
C_BACK = ("phone: opening a chat adds one same-URL history entry; back returns to the Fan List on Messages Pro, "
          "and a second back leaves it")
C_FORWARD = ("phone: Forward onto an open chat's history entry stays on it (Fan List, entry unmarked, no bounce) "
             "and the next Forward reaches the later page")
C_PIN = ("phone: a cancelled sideways swipe on the Thread keeps it pinned to the latest message; "
         "a vertical drag releases it")
C_SWIPE_BACK = ("phone: a swipe right on an open chat returns to the Fan List through its history entry "
                "(Messages Pro kept, the entry popped, nothing else navigated)")
C_INSIGHTS = "phone: a swipe right on Fan insights closes it and only it (the chat stays open)"
C_RELOAD = "phone: a reload with a chat open shows the Fan List, and one back then leaves Messages Pro"
C_DESKTOP = "desktop (1600px, touch input): no swipe opens or closes anything, and opening a chat adds no history entry"
C_5XX = "no 5xx from the relay in either browser session"
CHECKS = (C_SCROLL, C_EDGE, C_TURN, C_OPEN, C_CLOSE, C_MP_NO_MENU, C_BACK, C_FORWARD, C_PIN, C_SWIPE_BACK, C_INSIGHTS, C_RELOAD,
          C_DESKTOP, C_5XX)

HIST_JS = ("() => ({ len: history.length, marked: !!(history.state && history.state.__mpChat), path: location.pathname, "
           "idx: window.navigation && navigation.currentEntry ? navigation.currentEntry.index : -1 })")


async def _settle(page, ms: int = 600) -> None:
    await page.wait_for_timeout(ms)


async def _visible(loc, timeout_ms: int = 5000) -> bool:
    try:
        await loc.first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001 — a timeout is the answer
        return False


async def _hidden(loc, timeout_ms: int = 5000) -> bool:
    try:
        await loc.first.wait_for(state="hidden", timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def _menu(page):
    return page.get_by_role("dialog", name="Menu")


def _back_btn(page):
    return page.get_by_role("button", name="Back", exact=True)


def _fan_list(page):
    return page.locator("[data-mp-pane='fan-list']")


async def _dashboard(ctx, page) -> None:
    await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
    await page.get_by_role("button", name="Toggle sidebar").wait_for(timeout=90_000)
    await _settle(page, 1500)


async def _messages_pro(ctx, page) -> None:
    """A fresh `/` then `/messages-pro`: two history entries, the Fan List's rows in."""
    await _dashboard(ctx, page)
    await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
    await page.locator("[data-chat-row]").first.wait_for(timeout=90_000)
    await _settle(page, 1000)


async def _open_chat(page) -> bool:
    await page.locator("[data-chat-row]").first.tap()
    return await _visible(_back_btn(page), 15_000)


async def _back(page) -> None:
    await page.evaluate("() => history.back()")
    await _settle(page, 800)


async def _phone(ctx, page, shot) -> dict:
    m: dict = {}
    w = PHONE[0]

    # Dashboard: the nav menu.
    await _dashboard(ctx, page)
    m["dialogs_at_start"] = await page.get_by_role("dialog").count()
    await ui.swipe(page, 200, 650, 214, 250, ms=300)
    await _settle(page)
    ctx.check(C_SCROLL, await _menu(page).count() == 0)
    await ui.swipe(page, 10, 420, 230, 420)
    await _settle(page)
    ctx.check(C_EDGE, await _menu(page).count() == 0)
    # Sideways past the lock, then 100px down (a scroll), then 200px right: ends ~25 deg off horizontal.
    await ui.swipe(page, 120, 420, 330, 520, ms=450, via=((132, 421), (132, 520)))
    await _settle(page)
    await shot(page, "17-dashboard-turned-drag-no-menu")
    ctx.check(C_TURN, await _menu(page).count() == 0)

    await shot(page, "01-dashboard-before-swipe")
    url0 = page.url
    await ui.swipe(page, 120, 420, w - 60, 420, before_end=lambda: shot(page, "02-dashboard-swipe-right-trigger"))
    t0 = time.monotonic()
    opened = await _visible(_menu(page), 3000)
    m["menu_open_ms"] = round((time.monotonic() - t0) * 1000)
    expanded = await page.get_by_role("button", name="Toggle sidebar", include_hidden=True).get_attribute("aria-expanded")
    await _settle(page, 300)
    await shot(page, "03-dashboard-menu-open")
    ctx.check(C_OPEN, opened and expanded == "true" and page.url == url0, dialogs_at_start=m["dialogs_at_start"],
              aria_expanded=expanded, url=page.url)

    closed = False
    if opened:
        await ui.swipe(page, 230, 420, 30, 420, before_end=lambda: shot(page, "04-menu-swipe-left-trigger"))
        closed = await _hidden(_menu(page), 3000)
        await _settle(page, 300)
        await shot(page, "05-menu-closed")
    ctx.check(C_CLOSE, closed)

    # Messages Pro: no menu swipe.
    await _messages_pro(ctx, page)
    await ui.swipe(page, 120, 420, w - 60, 420)
    await _settle(page)
    ctx.check(C_MP_NO_MENU, await _menu(page).count() == 0 and page.url.endswith("/messages-pro"), url=page.url)

    # Back from an open chat.
    h0 = await page.evaluate(HIST_JS)
    chat = await _open_chat(page)
    h1 = await page.evaluate(HIST_JS)
    await shot(page, "06-chat-open")
    await _back(page)
    list_back = await _visible(_fan_list(page), 3000) and await _back_btn(page).count() == 0
    h2 = await page.evaluate(HIST_JS)
    await shot(page, "07-after-back-fan-list")
    await _back(page)
    h3 = await page.evaluate(HIST_JS)
    await shot(page, "08-second-back-left-messages-pro")
    ctx.check(C_BACK, chat and h1["len"] == h0["len"] + 1 and h1["marked"] and h1["path"] == h0["path"]
              and list_back and h2["path"] == "/messages-pro" and not h2["marked"] and h3["path"] == "/",
              opened=chat, before=h0, open=h1, after_back=h2, after_second_back=h3, list_after_back=list_back)

    # Forward after a back: no bounce, and the entries after the chat's stay reachable.
    await _messages_pro(ctx, page)
    chat = await _open_chat(page)
    await _dashboard(ctx, page)  # a later page: [.., /messages-pro, its chat's entry, /]
    await _back(page)  # onto the chat's entry: a fresh load pops it to the Fan List's
    await page.locator("[data-chat-row]").first.wait_for(timeout=90_000)
    await _settle(page, 1000)
    if await _back_btn(page).count() > 0:  # restored from the back/forward cache, chat open
        await _back(page)
    h0 = await page.evaluate(HIST_JS)
    await page.evaluate("() => history.forward()")
    await _settle(page, 1500)
    h1 = await page.evaluate(HIST_JS)
    list_ok = await _fan_list(page).first.is_visible() and await _back_btn(page).count() == 0
    await shot(page, "16-forward-onto-chat-entry-no-bounce")
    await page.evaluate("() => history.forward()")
    try:
        await page.wait_for_url(f"{ctx.app}/", timeout=30_000)
    except Exception:
        pass
    h2 = await page.evaluate(HIST_JS)
    ctx.check(C_FORWARD, chat and h0["path"] == "/messages-pro" and not h0["marked"] and h0["idx"] >= 0
              and h1["idx"] == h0["idx"] + 1 and h1["path"] == "/messages-pro" and not h1["marked"] and list_ok
              and h2["path"] == "/" and h2["idx"] == h1["idx"] + 1,
              opened=chat, on_fan_list=h0, after_forward=h1, list_after_forward=list_ok, after_second_forward=h2)

    # The Thread's pin, then its swipe right.
    await _messages_pro(ctx, page)
    chat = await _open_chat(page)
    pinned0 = await _visible(page.get_by_text(JUMPING), 4000)
    thread = page.locator("[data-mp-pane='thread']").first
    box = await thread.bounding_box()
    y = (box["y"] + box["height"] * 0.4) if box else 400
    await ui.swipe(page, 120, y, 300, y, ms=150, cancel=True)
    pinned1 = await page.get_by_text(JUMPING).count() > 0
    await ui.swipe(page, 200, y - 60, 204, y + 140, ms=150)
    released = await _hidden(page.get_by_text(JUMPING), 1500)
    ctx.check(C_PIN, chat and pinned0 and pinned1 and released, opened=chat, pinned_on_open=pinned0,
              pinned_after_cancelled_swipe=pinned1, released_by_vertical_drag=released)

    h1 = await page.evaluate(HIST_JS)
    await ui.swipe(page, 120, y, w - 60, y, before_end=lambda: shot(page, "09-thread-swipe-right-trigger"))
    t0 = time.monotonic()
    back_ok = await _visible(_fan_list(page), 3000) and await _hidden(_back_btn(page), 3000)
    m["thread_swipe_back_ms"] = round((time.monotonic() - t0) * 1000)
    await _settle(page)
    h2 = await page.evaluate(HIST_JS)
    await shot(page, "10-thread-swiped-back-fan-list")
    ctx.check(C_SWIPE_BACK, chat and h1["marked"] and back_ok and h2["path"] == "/messages-pro" and not h2["marked"],
              open=h1, after=h2)

    # Fan insights.
    chat = await _open_chat(page)
    await page.get_by_role("button", name="Fan insights").first.tap()
    ins = page.get_by_role("dialog", name="Fan insights")
    shown = await _visible(ins, 5000)
    gone = False
    if shown:
        ib = await ins.first.bounding_box()
        iy = ib["y"] + 24 if ib else 120
        ix = (ib["x"] + 20) if ib else 80
        await ui.swipe(page, ix, iy, min(ix + 220, w - 30), iy,
                       before_end=lambda: shot(page, "11-insights-swipe-right-trigger"))
        gone = await _hidden(ins, 3000)
        await _settle(page)
        await shot(page, "12-insights-closed-chat-open")
    h = await page.evaluate(HIST_JS)
    still = await _back_btn(page).count() > 0
    ctx.check(C_INSIGHTS, chat and shown and gone and still and h["path"] == "/messages-pro", insights_shown=shown, closed=gone,
              chat_still_open=still, hist=h)

    # Reload with a chat open.
    await _messages_pro(ctx, page)
    chat = await _open_chat(page)
    await page.reload(wait_until="domcontentloaded")
    rows_back = await _visible(page.locator("[data-chat-row]"), 30_000)
    await _settle(page, 1200)
    h1 = await page.evaluate(HIST_JS)
    list_ok = await _fan_list(page).first.is_visible() and await _back_btn(page).count() == 0
    await shot(page, "13-reloaded-fan-list")
    await _back(page)
    h2 = await page.evaluate(HIST_JS)
    ctx.check(C_RELOAD, chat and rows_back and list_ok and h1["path"] == "/messages-pro" and not h1["marked"] and h2["path"] == "/",
              after_reload=h1, after_back=h2)
    return m


async def _desktop(ctx, page, shot) -> None:
    await _dashboard(ctx, page)
    toggle = page.get_by_role("button", name="Toggle sidebar")
    e0 = await toggle.get_attribute("aria-expanded")
    await ui.swipe(page, 400, 500, 900, 500)
    await _settle(page)
    e1 = await toggle.get_attribute("aria-expanded")
    menu = await _menu(page).count()
    await shot(page, "14-desktop-dashboard-after-swipe")

    await _messages_pro(ctx, page)
    h0 = await page.evaluate(HIST_JS)
    await page.locator("[data-chat-row]").first.click()
    await _settle(page, 1500)
    h1 = await page.evaluate(HIST_JS)
    thread = page.locator("[data-mp-pane='thread']").first
    box = await thread.bounding_box()
    y = (box["y"] + box["height"] * 0.4) if box else 500
    x = (box["x"] + 60) if box else 700
    await ui.swipe(page, x, y, x + 400, y)
    await _settle(page)
    rows = await page.locator("[data-chat-row]").count()
    composer = await page.locator("[data-composer-area]").count()
    await shot(page, "15-desktop-messages-pro-after-swipe")
    ctx.check(C_DESKTOP, e0 == e1 and menu == 0 and h1["len"] == h0["len"] and not h1["marked"]
              and rows > 0 and composer > 0, aria_expanded=[e0, e1], menu_dialogs=menu, before=h0, after_open=h1,
              thread_still_open=composer > 0)


async def run(ctx) -> None:
    await ctx.build(PROFILE)
    if not ctx.app:
        for n in CHECKS:
            ctx.skip(n, "--no-ui")
        return

    async def shot(page, name):
        return await ui.shot(ctx, page, name)

    statuses = []
    async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
        try:
            ctx.metric("phone", await _phone(ctx, page, shot))
        finally:
            statuses += page.slop["statuses"]
    async with ui.owner_browser(ctx, viewport=DESKTOP, touch=True) as page:
        try:
            await _desktop(ctx, page, shot)
        finally:
            statuses += page.slop["statuses"]
    bad = [u for s, u in statuses if s >= 500 and "/api/of/" not in u]
    ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
