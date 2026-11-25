from __future__ import annotations

import time

from slop.actors import ui

PROFILE = "agency_inbox"
UI = True
FAULT = "mobile-chat-no-history-entry"
PHONE = (390, 844)
DESKTOP = (1600, 1000)
JUMPING = "Jumping to latest"

C_SCROLL = "phone: a vertical drag on a dashboard page does not open the nav menu"
C_EDGE = "phone: a swipe right starting in the OS edge zone (x < 24px) does not open the nav menu"
C_TURN = "phone: a drag that starts sideways, turns vertical and ends sideways does not open the nav menu"
C_OPEN = "phone: a swipe right from mid-screen on a dashboard page opens the nav menu (URL unchanged)"
C_CLOSE = "phone: a swipe left on the open nav menu closes it"
C_SNAP60 = "phone: the nav menu dragged slowly to 60% of its width and let go springs back open"
C_DRAG80 = "phone: the nav menu dragged slowly to 80% of its width and let go closes, unmounted within budget of the release"
C_FLICK = "phone: a short quick flick (60px) on the nav menu closes it"
C_FLICK_BACK = "phone: the nav menu dragged to 85% then flicked back stays open"
C_TAP_THROUGH = ("phone: a tap during a swiped-away nav menu's slide lands on the page under it, and the menu "
                 "unmounts within budget of going off screen")
C_FOCUS_THROUGH = ("phone: a tap on a text field during a swiped-away nav menu's slide leaves the field focused "
                   "(the menu's focus trap let go)")
C_GHOST_ROLE = ("phone: the copy a backdrop tap leaves behind is not taken for an open dialog, so the open "
                "swipe made while it is there opens the menu")
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
CHECKS = (C_SCROLL, C_EDGE, C_TURN, C_OPEN, C_CLOSE, C_SNAP60, C_DRAG80, C_FLICK, C_FLICK_BACK, C_TAP_THROUGH,
          C_FOCUS_THROUGH, C_GHOST_ROLE, C_MP_NO_MENU, C_BACK, C_FORWARD, C_PIN, C_SWIPE_BACK, C_INSIGHTS, C_RELOAD,
          C_DESKTOP, C_5XX)

SHEET_UNMOUNT_BUDGET_MS = 350
TAP_THROUGH_BUDGET_MS = 50
GHOST_MS = 260
SHEET_IN_MS = 300
DRAWER = "#app-sidebar-drawer"
GRAB_IN_PX = 16
SWIPE_Y = 420
FIELD_TAP_IN_PX = 40
DRAWER_X_JS = ("() => { const e = document.querySelector('#app-sidebar-drawer'); if (!e) return null; "
               "const tf = getComputedStyle(e).transform; return tf === 'none' ? 0 : new DOMMatrixReadOnly(tf).m41; }")

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


async def _open_menu(page) -> bool:
    if await _menu(page).count() == 0:
        await page.get_by_role("button", name="Toggle sidebar").tap()
    ok = await _visible(_menu(page), 3000)
    await _settle(page, SHEET_IN_MS + 200)
    return ok


async def _sheet(ctx, page, shot) -> dict:
    m: dict = {}
    px, py = await page.evaluate("""() => { for (let y = 200; y < 800; y += 20) for (let x = 30; x < 230; x += 20) {
        const e = document.elementFromPoint(x, y);
        if (e && e.closest('main') && !e.closest('a, button, input, textarea, select, label, [role], [tabindex]')) return [x, y]; }
      const m = document.querySelector('main').getBoundingClientRect(); return [m.x + 40, m.y + m.height / 2]; }""")
    m["probe_point"] = [px, py]
    y = SWIPE_Y

    async def gesture(*a, closes: bool = False, **kw) -> dict:
        await ui.sheet_probe(page, DRAWER, (px, py))
        await ui.swipe(page, *a, **kw)
        if closes:
            await _hidden(_menu(page), 3000)
        await _settle(page, 700)
        return await ui.sheet_read(page)

    opened = await _open_menu(page)
    w = await page.evaluate("(s) => document.querySelector(s)?.offsetWidth || 0", DRAWER) if opened else 0
    m["drawer_width"] = w
    x0 = w - GRAB_IN_PX

    r = await gesture(x0, y, x0 - 0.6 * w, y, ms=600, steps=12, hold_ms=250,
                      mid=lambda: shot(page, "18-menu-drag-60-mid"))
    x_after = await page.evaluate(DRAWER_X_JS)
    await shot(page, "19-menu-sprung-back")
    ctx.check(C_SNAP60, opened and r["release_to_unmount_ms"] is None and await _menu(page).count() == 1
              and x_after is not None and abs(x_after) < 0.5, x_after=x_after, **r)

    opened = await _open_menu(page)
    r = await gesture(x0, y, x0 - 0.8 * w, y, ms=600, steps=12, hold_ms=250, closes=True,
                      mid=lambda: shot(page, "20-menu-drag-80-mid"))
    closed = await _menu(page).count() == 0
    await shot(page, "21-menu-closed-by-drag-80")
    m["drag80"] = r
    ctx.check(C_DRAG80, opened and closed and r["release_to_unmount_ms"] is not None
              and r["release_to_unmount_ms"] <= SHEET_UNMOUNT_BUDGET_MS, budget_ms=SHEET_UNMOUNT_BUDGET_MS, **r)

    opened = await _open_menu(page)
    r = await gesture(x0, y, x0 - 60, y, ms=40, steps=2, closes=True)
    m["flick"] = r
    await shot(page, "22-menu-closed-by-flick")
    ctx.check(C_FLICK, opened and await _menu(page).count() == 0 and r["release_to_unmount_ms"] is not None, **r)

    opened = await _open_menu(page)
    r = await gesture(x0, y, x0 - 0.85 * w + 50, y, via=((x0 - 0.85 * w, y),), legs=((600, 12), (40, 2)))
    x_after = await page.evaluate(DRAWER_X_JS)
    await shot(page, "23-menu-flicked-back-open")
    ctx.check(C_FLICK_BACK, opened and await _menu(page).count() == 1 and x_after is not None and abs(x_after) < 0.5,
              x_after=x_after, **r)

    opened = await _open_menu(page)
    r = await _throw_and_tap(page, x0, y, (px, py))
    await shot(page, "25-menu-tapped-through-mid-slide")
    m["tap_through"] = r
    tap = r["starts"][1] if len(r["starts"]) > 1 else None
    click = r["clicks"][0] if r["clicks"] else None
    off = r["off_to_unmount_ms"]
    ctx.check(C_TAP_THROUGH, opened and tap is not None and tap["mounted"] and click is not None and click["main"]
              and r["off_by"] == "rect" and off is not None and off <= TAP_THROUGH_BUDGET_MS,
              budget_ms=TAP_THROUGH_BUDGET_MS, tap_start=tap, tap_click=click, **r)

    opened = await _open_menu(page)
    await ui.sheet_probe(page, DRAWER, (px, py))
    await page.touchscreen.tap(PHONE[0] - 20, 600)
    gone = await _hidden(_menu(page), 1000)
    await ui.swipe(page, 120, 420, PHONE[0] - 60, 420, ms=150)
    reopened = await _visible(_menu(page), 2000)
    r = await ui.sheet_read(page)
    await shot(page, "24-menu-reopened-right-after-backdrop-tap")
    swipe_start = r["starts"][1] if len(r["starts"]) > 1 else None
    closed_ms = r["release_to_unmount_ms"]
    gap = swipe_start["ms"] - closed_ms if swipe_start and None not in (swipe_start["ms"], closed_ms) else None
    m["ghost_role_close_to_swipe_ms"] = gap
    if (opened and gone and swipe_start is not None and not swipe_start["mounted"] and not swipe_start["ghost"]
            and gap is not None and gap >= GHOST_MS and reopened):
        ctx.skip(C_GHOST_ROLE, f"inconclusive: the swipe started {gap}ms after the close, past the copy's {GHOST_MS}ms",
                 swipe_start=swipe_start, reopened=reopened)
    else:
        ctx.check(C_GHOST_ROLE, opened and gone and swipe_start is not None and not swipe_start["mounted"]
                  and swipe_start["ghost"] and reopened, swipe_start=swipe_start, reopened=reopened, close_to_swipe_ms=gap)
    if await _menu(page).count():
        await page.keyboard.press("Escape")
        await _hidden(_menu(page), 3000)
    return m


async def _throw_and_tap(page, x0: float, y: float, pt: tuple[float, float]) -> dict:
    await ui.sheet_probe(page, DRAWER, pt)
    await ui.swipe(page, x0, y, x0 - 50, y, ms=100, steps=5)
    await page.wait_for_timeout(40)
    await page.touchscreen.tap(*pt)
    await _hidden(_menu(page), 3000)
    await _settle(page, 300)
    return await ui.sheet_read(page)


async def _focus_through(ctx, page, shot) -> dict:
    await page.goto(f"{ctx.app}/growth/sensitive-words", wait_until="domcontentloaded")
    field = page.locator("main input[placeholder='Search']").first
    box = await field.bounding_box() if await _visible(field, 90_000) else None
    if box is None:
        ctx.report.infra = ctx.report.infra or "tap-through: Sensitive words' Search field never showed"
        return {}
    await _settle(page, 1000)
    pt = (box["x"] + min(FIELD_TAP_IN_PX, box["width"] / 2), box["y"] + box["height"] / 2)
    opened = await _open_menu(page)
    w = await page.evaluate("(s) => document.querySelector(s)?.offsetWidth || 0", DRAWER) if opened else 0
    await shot(page, "26-sensitive-words-menu-open-before-throw")
    if opened and pt[0] >= w:
        ctx.report.infra = ctx.report.infra or f"tap-through: the field's tap point {pt} is not under the {w}px drawer"
        return {}
    r = await _throw_and_tap(page, w - GRAB_IN_PX, SWIPE_Y, pt) if opened else {"starts": []}
    focus = await page.evaluate("() => { const a = document.activeElement; return { main: !!(a && a.closest('main')), "
                                "field: !!(a && a.matches('input[placeholder=Search]')), tag: a ? a.tagName : null }; }")
    await shot(page, "27-menu-tapped-field-mid-slide-focused")
    tap = r["starts"][1] if len(r["starts"]) > 1 else None
    ctx.check(C_FOCUS_THROUGH, opened and tap is not None and tap["mounted"] and focus["field"]
              and focus["main"], tap_point=pt, drawer_width=w, tap_start=tap, focus=focus, **r)
    return {"focus_through": r, "focus": focus}


def _back_btn(page):
    return page.get_by_role("button", name="Back", exact=True)


def _fan_list(page):
    return page.locator("[data-mp-pane='fan-list']")


async def _dashboard(ctx, page) -> None:
    await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
    await page.get_by_role("button", name="Toggle sidebar").wait_for(timeout=90_000)
    await _settle(page, 1500)


async def _messages_pro(ctx, page) -> None:
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

    await _dashboard(ctx, page)
    m["dialogs_at_start"] = await page.get_by_role("dialog").count()
    await ui.swipe(page, 200, 650, 214, 250, ms=300)
    await _settle(page)
    ctx.check(C_SCROLL, await _menu(page).count() == 0)
    await ui.swipe(page, 10, 420, 230, 420)
    await _settle(page)
    ctx.check(C_EDGE, await _menu(page).count() == 0)
    await ui.touch_log(page)
    # sideways, down, then right: ends ~25 deg off horizontal; Chromium holds back a touch's first ~15px of moves, so a shorter first leg is turned away by the 30 deg lock
    await ui.swipe(page, 120, 420, 330, 520, ms=450, via=((160, 421), (160, 520)))
    await _settle(page)
    await shot(page, "17-dashboard-turned-drag-no-menu")
    ctx.check(C_TURN, await _menu(page).count() == 0, touches=await ui.touches(page))

    await shot(page, "01-dashboard-before-swipe")
    url0 = page.url
    await ui.swipe(page, 120, 420, w - 60, 420, mid=lambda: shot(page, "02-dashboard-swipe-right-trigger"))
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
        await ui.swipe(page, 230, 420, 30, 420, mid=lambda: shot(page, "04-menu-swipe-left-trigger"))
        closed = await _hidden(_menu(page), 3000)
        await _settle(page, 300)
        await shot(page, "05-menu-closed")
    ctx.check(C_CLOSE, closed)
    m["sheet"] = await _sheet(ctx, page, shot)
    m["focus_through"] = await _focus_through(ctx, page, shot)

    await _messages_pro(ctx, page)
    await ui.swipe(page, 120, 420, w - 60, 420)
    await _settle(page)
    ctx.check(C_MP_NO_MENU, await _menu(page).count() == 0 and page.url.endswith("/messages-pro"), url=page.url)

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

    await _messages_pro(ctx, page)
    chat = await _open_chat(page)
    await _dashboard(ctx, page)
    await _back(page)
    await page.locator("[data-chat-row]").first.wait_for(timeout=90_000)
    await _settle(page, 1000)
    if await _back_btn(page).count() > 0:
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
    await _settle(page)
    ctx.check(C_PIN, chat and pinned0 and pinned1 and released, opened=chat, pinned_on_open=pinned0,
              pinned_after_cancelled_swipe=pinned1, released_by_vertical_drag=released)

    h1 = await page.evaluate(HIST_JS)
    await ui.touch_log(page)
    await ui.sheet_probe(page, "[data-mp-pane='thread']")
    await ui.swipe(page, 120, y, w - 60, y, mid=lambda: shot(page, "09-thread-swipe-right-trigger"))
    t0 = time.monotonic()
    back_ok = await _visible(_fan_list(page), 3000) and await _hidden(_back_btn(page), 3000)
    m["thread_swipe_back_ms"] = round((time.monotonic() - t0) * 1000)
    await _settle(page)
    h2 = await page.evaluate(HIST_JS)
    await shot(page, "10-thread-swiped-back-fan-list")
    ctx.check(C_SWIPE_BACK, chat and h1["marked"] and back_ok and h2["path"] == "/messages-pro" and not h2["marked"],
              open=h1, after=h2, touches=await ui.touches(page),
              release_to_unmount_ms=(await ui.sheet_read(page))["release_to_unmount_ms"])
    if await _back_btn(page).count():
        await _back_btn(page).first.tap()
        await _hidden(_back_btn(page), 3000)

    chat = await _open_chat(page)
    await page.get_by_role("button", name="Fan insights").first.tap()
    ins = page.get_by_role("dialog", name="Fan insights")
    shown = await _visible(ins, 5000)
    gone, touches = False, []
    if shown:
        await _settle(page, SHEET_IN_MS + 200)
        ib = await ins.first.bounding_box()
        iy = ib["y"] + 24 if ib else 120
        ix = (ib["x"] + 20) if ib else 80
        await ui.touch_log(page)
        await ui.swipe(page, ix, iy, min(ix + 220, w - 30), iy,
                       mid=lambda: shot(page, "11-insights-swipe-right-trigger"))
        touches = await ui.touches(page)
        gone = await _hidden(ins, 3000)
        await _settle(page)
        await shot(page, "12-insights-closed-chat-open")
    h = await page.evaluate(HIST_JS)
    still = await _back_btn(page).count() > 0
    ctx.check(C_INSIGHTS, chat and shown and gone and still and h["path"] == "/messages-pro", insights_shown=shown, closed=gone,
              chat_still_open=still, hist=h, touches=touches)

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
