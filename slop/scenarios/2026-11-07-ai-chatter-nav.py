"""Sidebar: My Automations split in two plus Full AI Chatter (2026-11-07). The owner on a phone opens
the nav drawer and finds My Automations (Auto Post, Auto Story, Auto Mass, Gen-Info, Client masses),
then My AI Chatter (Auto-reply, Auto Funnel, Get to know fans), then Full AI Chatter, and taps it: the
drawer closes on the coming-soon page. At desktop width the sidebar on Auto-reply holds My AI Chatter
open with Auto-reply current. A chatter whose enforced role ticks Auto-reply only sees My AI Chatter
(Auto-reply and Get to know fans, the not-opt-in page), no My Automations, no Full AI Chatter
(owner-only). A nav flow, not a volume one: one owner, one chatter, real routes on the slop temp DB.

World: `agency_inbox`; the chatter through the real invite + register (`seed/chatters`), the role
through `PUT /admin/settings/roles`.

Invariants: the stored role and the chatter's Applied read (`opt_in` exactly Auto-reply), the three
sidebars' outlines, the coming-soon page after the tap, no 5xx from the relay in any browser.
Screenshots: phone-drawer (trigger), phone-full-ai-chatter (settled; -dark too), desktop-sidebar,
chatter-sidebar. --no-ui: the route checks only.

Fault `full-ai-chatter-shown-to-chatter` (nav.ts's Full AI Chatter without `chatterHidden`) must turn
only the chatter-sidebar check red.
"""
from __future__ import annotations

import json

from slop.actors import ui
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

MY_AUTOMATIONS = "My Automations: Auto Post / Auto Story / Auto Mass / Gen-Info / Client masses"
MY_AI_CHATTER = "My AI Chatter: Auto-reply / Auto Funnel / Get to know fans"

C_ROLE = "PUT /admin/settings/roles (enforced, a role ticking Auto-reply of the opt-in pages) is stored and read back"
C_APPLIED = ("chatter's GET /admin/settings/applied: opt_in is exactly Auto-reply; pages hold Auto-reply, "
             "Get to know fans and Full AI Chatter")
C_PHONE_DRAWER = ("phone (390x844): the nav drawer lists My Automations (5 pages), then My AI Chatter "
                  "(Auto-reply, Auto Funnel, Get to know fans), then Full AI Chatter")
C_PHONE_PAGE = "phone: tapping Full AI Chatter in the drawer closes it on /full-ai-chatter showing Coming soon"
C_DESKTOP = ("desktop (1440px): on Auto-reply the sidebar holds My Automations, then My AI Chatter with "
             "Auto-reply current, then Full AI Chatter")
C_CHATTER = ("chatter (role ticks Auto-reply only): the sidebar shows My AI Chatter with Auto-reply and "
             "Get to know fans, no My Automations, no Full AI Chatter")
C_5XX = "no 5xx from the relay in any browser session"
CHECKS = (C_ROLE, C_APPLIED, C_PHONE_DRAWER, C_PHONE_PAGE, C_DESKTOP, C_CHATTER, C_5XX)

# The sidebar under `sel` as lines: "Label" for a link, "Group: Child / Child" for a group (its open
# children only), "—" for the divider.
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


def _window(lines: list[str] | None) -> list[str]:
    """The lines from My Automations on, up to the divider."""
    lines = lines or []
    start = next((i for i, l in enumerate(lines) if l.startswith("My Automations")), None)
    if start is None:
        return []
    end = lines.index("—", start) if "—" in lines[start:] else len(lines)
    return lines[start:end]


async def _role_setup(ctx, w) -> tuple[Http, dict]:
    """A chatter (real invite + register), assigned a role ticking Auto-reply, Get to know fans, Full AI
    Chatter, the Dashboard and Messages Pro, on an Agency enforcing role permissions."""
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
            for c in (C_PHONE_DRAWER, C_PHONE_PAGE, C_DESKTOP, C_CHATTER, C_5XX):
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
            await _expand(page, drawer, ("My Automations", "My AI Chatter"))
            full = page.locator(f"{drawer} a[href='{FULL}']")
            await full.scroll_into_view_if_needed()
            await page.wait_for_timeout(400)  # the sheet's slide-in and the chevrons' turn
            lines = await page.evaluate(_OUTLINE, drawer)
            await ui.shot(ctx, page, "phone-drawer")
            got = _window(lines)
            ctx.check(C_PHONE_DRAWER, got == [MY_AUTOMATIONS, MY_AI_CHATTER, "Full AI Chatter"], got=got)
            await full.tap()
            ok = True
            try:
                await page.wait_for_url(f"**{FULL}", timeout=60_000)
                await page.get_by_text("Coming soon", exact=True).wait_for(timeout=60_000)
                await page.locator(drawer).wait_for(state="detached", timeout=10_000)
            except Exception as e:  # noqa: BLE001
                ok = False
                ctx.metric("phone_page_error", str(e)[:200])
            await page.wait_for_timeout(300)
            await ui.shot(ctx, page, "phone-full-ai-chatter")
            # The app's default theme (the harness browser runs light): the same page, dark.
            await page.evaluate("() => { localStorage.setItem('chatterly:theme', 'dark'); "
                                "document.documentElement.removeAttribute('data-theme'); }")
            await page.wait_for_timeout(300)
            await ui.shot(ctx, page, "phone-full-ai-chatter-dark")
            ctx.check(C_PHONE_PAGE, ok, url=page.url)
            statuses += page.slop["statuses"]

        async with ui.owner_browser(ctx, viewport=DESKTOP) as page:
            await page.goto(f"{ctx.app}{AUTO_REPLY}", wait_until="domcontentloaded")
            cur = page.locator(f"#app-sidebar a[aria-current='page'][href='{AUTO_REPLY}']")
            await cur.wait_for(timeout=90_000)
            await _expand(page, "#app-sidebar", ("My Automations",))
            await page.locator(f"#app-sidebar a[href='{FULL}']").scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            got = _window(await page.evaluate(_OUTLINE, "#app-sidebar"))
            await ui.shot(ctx, page, "desktop-sidebar")
            ctx.check(C_DESKTOP, got == [MY_AUTOMATIONS, MY_AI_CHATTER, "Full AI Chatter"] and await cur.count() == 1,
                      got=got)
            statuses += page.slop["statuses"]

        async with ui.chatter_tab(ctx, http, ctx.app, viewport=DESKTOP) as page:
            await page.goto(f"{ctx.app}{AUTO_REPLY}", wait_until="domcontentloaded")
            # Auto-reply current = the role's grant has landed (an opt-in page stays hidden until it does).
            await page.locator(f"#app-sidebar a[aria-current='page'][href='{AUTO_REPLY}']").wait_for(timeout=90_000)
            await page.wait_for_timeout(1_000)
            lines = await page.evaluate(_OUTLINE, "#app-sidebar") or []
            await ui.shot(ctx, page, "chatter-sidebar")
            ctx.check(C_CHATTER, "My AI Chatter: Auto-reply / Get to know fans" in lines
                      and not any(l.startswith("My Automations") for l in lines) and "Full AI Chatter" not in lines,
                      lines=lines)
            statuses += page.slop["statuses"]
        bad = [u for s, u in statuses if s >= 500 and "/api/of/" not in u]
        ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
    finally:
        await http.aclose()
