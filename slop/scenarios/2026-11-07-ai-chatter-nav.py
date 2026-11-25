from __future__ import annotations

import json

from slop.actors import ui
from slop.lib import navs
from slop.lib.client import Http
from slop.seed import chatters

PROFILE = "agency_inbox"
UI = True
FAULT = "full-ai-chatter-shown-to-chatter"
PHONE = (390, 844)
DESKTOP = (1440, 900)
ROLE_ID = "slop-ai-chatter-role"
AUTO_REPLY = "/growth/auto-reply"
GTKF = "/growth/get-to-know-fans"
FULL = "/full-ai-chatter"
RULES = "/ai-rules"

_AUTOMATIONS = (*navs.extras("MY_AUTOMATIONS"), "Auto Mass", "Auto Post", "Auto Story", "Auto Funnel", "Gen-Info")
MY_AUTOMATIONS = "My Automations: " + " / ".join(_AUTOMATIONS)
GONE = ("My AI Chatter", "Auto-reply", "Get to know fans", "AI rules")
SHADOW = "Live: replies to the fans on its Fans list on OnlyFans. Off: sends nothing."
ENTRIES = ["Messages Pro", "Vault Pro", "Growth", "Share for Share", "My Automations", "Full AI Chat"]

C_ROLE = "PUT /admin/settings/roles (enforced, a role ticking Auto-reply of the opt-in pages) is stored and read back"
C_APPLIED = ("chatter's GET /admin/settings/applied: opt_in is exactly Auto-reply; pages hold Auto-reply, "
             "Get to know fans and Full AI Chatter")
C_PHONE_DRAWER = ("phone (390x844): the nav drawer's entries run Messages Pro, Vault Pro, Growth, Share for "
                  "Share, My Automations, Full AI Chat (no Focus, no My AI Chatter, Auto-reply, Get to know fans or "
                  "AI rules); Vault Pro is not in Growth")
C_ACCORDION = (f"phone: opening Growth, then My Automations ({len(_AUTOMATIONS)} pages) leaves only My Automations "
               "open, Full AI Chat the link after it")
C_PHONE_PAGE = "phone: tapping Full AI Chat in the drawer closes it on /full-ai-chatter showing its Off / Live settings"
C_RULES_POPUP = ("phone: Full AI Chat's header AI rules opens the diagram in a popup on /full-ai-chatter; "
                 "Close shuts it on the same page")
C_DESKTOP = ("desktop (1440px): Auto-reply opened by URL renders with no sidebar entry current, My Automations "
             "then Full AI Chat the last entries; /ai-rules lights Full AI Chat")
C_CHATTER = ("chatter (role ticks Auto-reply only): Auto-reply opens by URL; the sidebar shows no My AI Chatter, "
             "Auto-reply, Get to know fans, My Automations, Full AI Chat or AI rules")
C_5XX = "no 5xx from the relay in any browser session"
CHECKS = (C_ROLE, C_APPLIED, C_PHONE_DRAWER, C_ACCORDION, C_PHONE_PAGE, C_RULES_POPUP, C_DESKTOP, C_CHATTER, C_5XX)

_OUTLINE = """(sel) => {
  const nav = document.querySelector(sel + ' nav[aria-label="Main"]');
  if (!nav) return null;
  return [...nav.children].map((el) => {
    const b = el.querySelector(':scope > button[aria-expanded]');
    if (b) return b.textContent.trim() + ': ' + [...el.querySelectorAll(':scope > div a')]
      .map((a) => a.textContent.trim()).join(' / ');
    const a = el.tagName === 'A' ? el : el.querySelector(':scope > a');
    return a ? a.textContent.trim() : '—';
  });
}"""


async def _expand(page, scope: str, groups: tuple[str, ...]) -> None:
    for g in groups:
        b = page.locator(f"{scope} nav[aria-label='Main'] button[aria-expanded='false']", has_text=g)
        if await b.count():
            await b.first.click()
            await page.locator(f"{scope} nav[aria-label='Main'] button[aria-expanded='true']",
                               has_text=g).first.wait_for(timeout=10_000)


def _gone(lines: list[str]) -> list[str]:
    return [g for g in GONE for line in lines if g in (line.split(": ")[0], *line.split(": ", 1)[-1].split(" / "))]


def _window(lines: list[str] | None) -> list[str]:
    lines = lines or []
    start = next((i for i, l in enumerate(lines) if l.startswith("My Automations")), None)
    if start is None:
        return []
    end = lines.index("—", start) if "—" in lines[start:] else len(lines)
    return lines[start:end]


async def _role_setup(ctx, w) -> tuple[Http, dict]:
    name = f"{w.user_prefix}{w.seed}ai"
    got = (await chatters.seed(w, ctx.owner, w.user_id, [name],
                               account_ids=[[w.data["creators"][0]["id"]]]))[0]
    emps = (await ctx.owner.get("/admin/employees")).json()["employees"]
    emp = next(e for e in emps if e.get("username") == name)
    cfg = (await ctx.owner.get("/admin/settings/roles")).json().get("config") or {}
    role = {"id": ROLE_ID, "name": "Slop AI chatter", "description": "",
            "permissions": {"/": True, "/messages-pro": True, AUTO_REPLY: True, GTKF: True, FULL: True},
            "scope": "self"}
    blob = {**cfg, "enforce": True, "roles": [*(r for r in cfg.get("roles") or [] if r.get("id") != ROLE_ID), role],
            "assignments": {**(cfg.get("assignments") or {}), str(emp["id"]): ROLE_ID}}
    put = await ctx.owner.put("/admin/settings/roles", json=blob)
    back = (await ctx.owner.get("/admin/settings/roles")).json().get("config") or {}
    stored = next((r for r in back.get("roles") or [] if r.get("id") == ROLE_ID), {})
    ctx.check(C_ROLE, put.status_code == 200 and back.get("enforce") is True
              and (back.get("assignments") or {}).get(str(emp["id"])) == ROLE_ID
              and stored.get("permissions", {}).get(AUTO_REPLY) is True,
              http_status=put.status_code, stored=stored, employee_id=emp["id"])
    http = Http(ctx.relay, ctx.rec)
    r = await http.post("/chatter/login", json={"username": name, "password": got["password"]})
    r.raise_for_status()
    applied = (await http.get("/admin/settings/applied")).json().get("permissions") or {}
    (ctx.out / "chatter-applied-permissions.json").write_text(json.dumps(applied, indent=2))
    pages = set(applied.get("pages") or [])
    ctx.check(C_APPLIED, applied.get("opt_in") == [AUTO_REPLY] and {AUTO_REPLY, GTKF, FULL} <= pages,
              opt_in=applied.get("opt_in"), enforced=applied.get("enforced"), pages=sorted(pages))
    return http, {"username": name, "employee_id": emp["id"]}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    http, who = await _role_setup(ctx, w)
    ctx.metric("chatter", who)
    try:
        if ctx.app is None:
            for c in (C_PHONE_DRAWER, C_ACCORDION, C_PHONE_PAGE, C_RULES_POPUP, C_DESKTOP, C_CHATTER, C_5XX):
                ctx.skip(c, "--no-ui")
            return
        statuses = []
        drawer = "#app-sidebar-drawer"
        async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
            await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
            toggle = page.get_by_role("button", name="Toggle sidebar")
            await toggle.wait_for(timeout=90_000)
            await toggle.tap()
            await page.locator(f"{drawer} nav[aria-label='Main']").wait_for(timeout=30_000)
            await page.wait_for_timeout(400)
            lines = await page.evaluate(_OUTLINE, drawer) or []
            await ui.shot(ctx, page, "phone-drawer")
            labels = [l.split(":")[0] for l in lines]
            got = labels[labels.index("Messages Pro"):labels.index("—")] if {"Messages Pro", "—"} <= set(labels) else labels
            growth = await page.locator(f"{drawer} nav[aria-label='Main'] > div a[href='/growth/vault-pro']").count()
            hidden_links = await page.locator(
                f"{drawer} a[href='{AUTO_REPLY}'], {drawer} a[href='{GTKF}'], {drawer} a[href='{RULES}']").count()
            ctx.check(C_PHONE_DRAWER, got == ENTRIES and growth == 0 and not _gone(lines) and hidden_links == 0,
                      got=got, vault_pro_in_a_group=growth, gone=_gone(lines), hidden_links=hidden_links)

            expanded = page.locator(f"{drawer} nav[aria-label='Main'] button[aria-expanded='true']")
            await _expand(page, drawer, ("Growth",))
            await page.wait_for_timeout(300)
            first = [t.strip() for t in await expanded.all_text_contents()]
            await ui.shot(ctx, page, "phone-accordion-trigger")
            await _expand(page, drawer, ("My Automations",))
            full = page.locator(f"{drawer} a[href='{FULL}']")
            await full.scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            then = _window(await page.evaluate(_OUTLINE, drawer))
            open_ = [t.strip() for t in await expanded.all_text_contents()]
            await ui.shot(ctx, page, "phone-accordion")
            ctx.check(C_ACCORDION, first == ["Growth"] and then == [MY_AUTOMATIONS, "Full AI Chat"]
                      and open_ == ["My Automations"], first=first, then=then, open=open_)
            await full.tap()
            ok = True
            try:
                await page.wait_for_url(f"**{FULL}", timeout=60_000)
                await page.get_by_text(SHADOW, exact=True).wait_for(timeout=60_000)
                await page.locator(drawer).wait_for(state="detached", timeout=10_000)
            except Exception as e:  # noqa: BLE001
                ok = False
                ctx.metric("phone_page_error", str(e)[:200])
            await page.wait_for_timeout(300)
            await ui.shot(ctx, page, "phone-full-ai-chatter")
            await page.evaluate("() => { localStorage.setItem('chatterly:theme', 'dark'); "
                                "document.documentElement.removeAttribute('data-theme'); }")
            await page.wait_for_timeout(300)
            await ui.shot(ctx, page, "phone-full-ai-chatter-dark")
            ctx.check(C_PHONE_PAGE, ok, url=page.url)

            popup = page.get_by_role("dialog", name="AI rules")
            shown = closed = False
            try:
                await page.get_by_role("button", name="AI rules", exact=True).tap()
                await popup.get_by_label("AI rules diagram").wait_for(timeout=30_000)
                shown = True
                await page.wait_for_timeout(1_000)
                await ui.shot(ctx, page, "phone-ai-rules-popup")
                await popup.get_by_role("button", name="Close", exact=True).first.tap()
                await popup.wait_for(state="detached", timeout=10_000)
                closed = True
            except Exception as e:  # noqa: BLE001
                ctx.metric("rules_popup_error", str(e)[:200])
            ctx.check(C_RULES_POPUP, shown and closed and page.url.endswith(FULL), shown=shown, closed=closed,
                      url=page.url)
            statuses += page.slop["statuses"]

        async with ui.owner_browser(ctx, viewport=DESKTOP) as page:
            await page.goto(f"{ctx.app}{AUTO_REPLY}", wait_until="domcontentloaded")
            await page.locator("h1", has_text="Auto-reply").first.wait_for(timeout=90_000)
            await page.locator(f"#app-sidebar a[href='{FULL}']").scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            lines = await page.evaluate(_OUTLINE, "#app-sidebar") or []
            got = _window(lines)
            current = await page.locator("#app-sidebar a[aria-current='page']").count()
            await ui.shot(ctx, page, "desktop-sidebar")
            await page.goto(f"{ctx.app}{RULES}", wait_until="domcontentloaded")
            lit = page.locator(f"#app-sidebar a[aria-current='page'][href='{FULL}']")
            try:
                await lit.wait_for(timeout=60_000)
            except Exception as e:  # noqa: BLE001
                ctx.metric("ai_rules_lit_error", str(e)[:200])
            ctx.check(C_DESKTOP, got == ["My Automations: ", "Full AI Chat"] and current == 0 and not _gone(lines)
                      and await lit.count() == 1, got=got, current=current, gone=_gone(lines))
            statuses += page.slop["statuses"]

        async with ui.chatter_tab(ctx, http, ctx.app, viewport=DESKTOP) as page:
            await page.goto(f"{ctx.app}{AUTO_REPLY}", wait_until="domcontentloaded")
            opened = True
            try:
                await page.locator("h1", has_text="Auto-reply").first.wait_for(timeout=90_000)
            except Exception as e:  # noqa: BLE001
                opened = False
                ctx.metric("chatter_auto_reply_error", str(e)[:200])
            await page.wait_for_timeout(1_000)
            lines = await page.evaluate(_OUTLINE, "#app-sidebar") or []
            await ui.shot(ctx, page, "chatter-auto-reply")
            ctx.check(C_CHATTER, opened and not _gone(lines)
                      and not any(l.startswith("My Automations") or "Full AI Chat" in l for l in lines),
                      lines=lines, opened=opened)
            statuses += page.slop["statuses"]
        bad = [u for s, u in statuses if s >= 500 and "/api/of/" not in u]
        ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
    finally:
        await http.aclose()
