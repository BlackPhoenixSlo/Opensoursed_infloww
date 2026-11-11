"""Help bot answers link the exact page or tab they name (2026-11-10). A live answer read "Settings has an
**Audit log** page" and its only link went to /settings, not the Audit log tab. Any page or tab the bot
names, by arrow path or in prose, must link to that exact page. A one-word label used as prose, or a list of
several pages, must not pull a head to the wrong place.

World: `agency_inbox`; one stored `assistant_turns` row for the owner (SQL: the shape POST
/admin/assistant/ask writes, with no LLM call; the bot's wire is a paid model we never reach). The answer is
the live answer plus the prose shapes the bot writes.

Bypass: no OF session in this world, so the Mass Messages tab's own OF refresh (503) is left out of the 5xx
check.

Invariants: GET /admin/assistant/history returns the row; on /help-center (its thread opened from Earlier
conversations) every link in
the answer has exactly the expected text → href; clicking "Audit log" lands on /settings/audit; no 5xx.
A link's inner tab and card (no route of their own) ride its `#go=` hash: clicking the Smart Messages path
selects the Priority mass messages child tab; the Mass Auto Unsend Messages path outlines the Auto-unsend card.
Screenshots: help-trigger (the answer with its links), help-settled (Audit log page after the click),
deep-priority (Priority mass messages selected), deep-unsend (Auto-unsend outlined), help-phone. --no-ui: the history check only.

Fault `help-links-prose-pages-unlinked` (answerLinks.ts without NAMED: prose page names stay plain) must
turn only the links check red.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from slop.actors import ui
from slop.seed import ts

PROFILE = "agency_inbox"
UI = True
FAULT = "help-links-prose-pages-unlinked"
DESKTOP = (1440, 900)
PHONE = (390, 844)
QUESTION = "where are logs in settings"
ANSWER = (
    "Settings has an **Audit log** page (owners only).\n\n"
    "- Open **Manage creators** and press **Add creator**.\n"
    "- In **Message dashboard**, open **Tips**.\n"
    "- **Growth** — Smart Messages, Smart lists and Auto-follow.\n"
    "- Keys live in Settings → **AI keys**; Scripts and Billing are just words here.\n"
    "- Queue: Growth → Smart Messages → Mass Messages → Priority mass messages.\n"
    "- Unsend: Growth → Smart Messages → Mass Auto Unsend Messages → Auto-unsend."
)
PRIORITY = "/growth/smart-messages?tab=mass#go=Priority+mass+messages"
DEEP = "/growth/smart-messages?tab=unsend#go=Auto-unsend"
# (link text, href) in answer order.
EXPECTED = [
    ["Settings", "/settings/audit"],
    ["Audit log", "/settings/audit"],
    ["Manage creators", "/creators"],
    ["Message dashboard", "/analytics/message-dashboard?tab=tips"],
    ["Tips", "/analytics/message-dashboard?tab=tips"],
    ["Smart Messages", "/growth/smart-messages"],
    ["Smart lists", "/growth/smart-lists"],
    ["Auto-follow", "/growth/auto-follow"],
    # One path across a bold span renders one link per span, same href (AnswerText).
    ["Settings →", "/settings/ai-keys"],
    ["AI keys", "/settings/ai-keys"],
    # The inner tab and the card ride the hash (lib/deepLink.ts); the link text stops at the last named step.
    # The last segment stays out of the link text (prose may run on in it) but rides the hash.
    ["Growth → Smart Messages → Mass Messages", PRIORITY],
    ["Growth → Smart Messages → Mass Auto Unsend Messages", DEEP],
]

C_HISTORY = "GET /admin/assistant/history returns the seeded answer to its owner"
C_LINKS = ("/help-center: every link in the answer has the expected text and exact href (prose page names "
           "link their page; a list sentence or one plain word does not borrow one)")
C_CLICK = "clicking Audit log in the answer lands on /settings/audit"
C_DEEP = ("clicking a Smart Messages path lands on the Mass Messages tab with the child tab it names selected "
          "(Priority mass messages, not the default OF), and the Mass Auto Unsend Messages path's Auto-unsend "
          "card scrolled into view and outlined")
C_5XX = "no 5xx from the relay in any browser session (bar the Mass Messages tab's own OF refresh, see OF_REFRESH)"
# BYPASS (declared): this world has no OF session, so the Mass Messages tab's live refresh against OnlyFans
# answers 503 bad_session. That is the page's own OF read, not this flow; links and tabs never call it.
OF_REFRESH = "/admin/mass-messages/refresh"
CHECKS = (C_HISTORY, C_LINKS, C_CLICK, C_DEEP, C_5XX)

# The answer bubble's links (AssistantWidget renderTurn), not the composer's focus line.
ANSWER_SEL = '[data-look="messenger"] .rounded-bl-md'
ANSWER_LINKS = f"{ANSWER_SEL} a"
THREAD = "slop-help-links"
_LINKS = """() => {
  const t = [...document.querySelectorAll(ANSWER_LINKS)];
  return t.map((a) => [a.textContent.replace(/\\s+/g, ' ').trim(), a.getAttribute('href')]);
}""".replace("ANSWER_LINKS", repr(ANSWER_LINKS))


_DEEP_STATE = """() => {
  const t = document.querySelector('[data-deeplink-target]');
  const r = t && t.getBoundingClientRect();
  return { url: location.pathname + location.search + location.hash,
           of: document.querySelector('#sm-child-of')?.getAttribute('aria-selected'),
           priority: document.querySelector('#sm-child-priority')?.getAttribute('aria-selected'),
           target: t ? t.textContent.trim() : null,
           inView: !!r && r.top >= 0 && r.bottom <= innerHeight };
}"""


async def _open_earlier(page) -> None:
    """Open the seeded thread: the Earlier conversations card, then its row in the list (ThreadList)."""
    card = page.get_by_role("button", name=re.compile("Earlier conversations")).last
    await card.wait_for(timeout=90_000)
    await card.click()
    await page.locator("[role=dialog][aria-label='Earlier conversations'] button", has_text=QUESTION).first.click()
    # The answer's own text, not one of its links: a fault that drops links must fail the links check, not this.
    await page.locator(ANSWER_SEL, has_text="Audit log").first.wait_for(timeout=30_000)
    await page.wait_for_timeout(300)  # the lazy AnswerText chunk


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    con = w.sql()
    with con:
        con.execute("INSERT INTO assistant_turns (ts, user_id, chatter_id, account_id, role, question, answer, "
                    "error, model, provider, cost_millicents, latency_ms, thread_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts(datetime.now(timezone.utc).replace(tzinfo=None)), w.user_id, None, None,
                     "an owner/admin", QUESTION, ANSWER, None, "claude-opus-5-5", "anthropic", 0, 1, THREAD))
    con.close()

    h = await ctx.owner.get("/admin/assistant/history?limit=50")
    rows = h.json().get("turns") or h.json().get("history") or [] if h.status_code == 200 else []
    ctx.check(C_HISTORY, h.status_code == 200 and any(r.get("answer") == ANSWER for r in rows),
              http_status=h.status_code, rows=len(rows), keys=sorted(h.json()) if h.status_code == 200 else None)

    if ctx.app is None:
        for c in (C_LINKS, C_CLICK, C_DEEP, C_5XX):
            ctx.skip(c, "--no-ui")
        return

    statuses = []
    async with ui.owner_browser(ctx, viewport=DESKTOP) as page:
        await page.goto(f"{ctx.app}/help-center", wait_until="domcontentloaded")
        await _open_earlier(page)
        await page.wait_for_timeout(300)
        got = await page.evaluate(_LINKS)
        await ui.shot(ctx, page, "help-trigger")
        ctx.check(C_LINKS, got == EXPECTED, got=got, expected=EXPECTED)
        ok = True
        try:
            # No link (a fault dropped it) fails this check, never crashes the run.
            await page.locator(ANSWER_LINKS, has_text="Audit log").first.click(
                timeout=5_000)
            await page.wait_for_url("**/settings/audit", timeout=60_000)
        except Exception as e:  # noqa: BLE001
            ok = False
            ctx.metric("click_error", str(e)[:200])
        await page.wait_for_timeout(1_000)
        await ui.shot(ctx, page, "help-settled")
        ctx.check(C_CLICK, ok, url=page.url)
        statuses += page.slop["statuses"]

        # The inner tab and card: client state with no route, opened by DeepLinkTarget from the hash.
        got_deep = {}
        for name, href, tab in (("priority", PRIORITY, "mass"), ("unsend", DEEP, "unsend")):
            await page.goto(f"{ctx.app}/help-center", wait_until="domcontentloaded")
            await _open_earlier(page)
            try:
                await page.locator(f"{ANSWER_LINKS}[href='{href}']").first.click(
                    timeout=5_000)
                await page.wait_for_url(f"**/growth/smart-messages?tab={tab}*", timeout=60_000)
                await page.locator("[data-deeplink-target]").first.wait_for(timeout=30_000)
                await page.wait_for_timeout(800)  # the smooth scroll
                got_deep[name] = await page.evaluate(_DEEP_STATE)
            except Exception as e:  # noqa: BLE001
                got_deep[name] = {"error": str(e)[:200]}
            await ui.shot(ctx, page, f"deep-{name}")
        pr, un = got_deep.get("priority", {}), got_deep.get("unsend", {})
        ctx.check(C_DEEP, pr.get("priority") == "true" and pr.get("of") == "false"
                  and (pr.get("target") or "").startswith("Priority mass messages")
                  and (un.get("url") or "").startswith("/growth/smart-messages?tab=unsend")
                  and (un.get("target") or "").startswith("Auto-unsend")
                  and un.get("inView") is True, **got_deep)
        statuses += page.slop["statuses"]

    async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
        await page.goto(f"{ctx.app}/help-center", wait_until="domcontentloaded")
        await _open_earlier(page)
        await page.wait_for_timeout(300)
        await ui.shot(ctx, page, "help-phone")
        statuses += page.slop["statuses"]

    bad = [u for s, u in statuses if s >= 500 and "/api/of/" not in u and OF_REFRESH not in u]
    ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
