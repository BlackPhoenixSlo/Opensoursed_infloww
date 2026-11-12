"""The Settings walk: every non-legacy Settings tab, headless, against a Next dev server.

    cd app && npx next dev --webpack -p 3091
    python3 -I scripts/settings-check/walk.py

Env:
  PORT             the dev server's port (default 3091).
  No flags: every tab must be built (Phase 5 removed Phase 0's --allow-unbuilt).

Mocks (Playwright routes on the browser context, no relay; synthetic data only):
  GET  /auth/me                        the owner "tester"
  POST /auth/logout                    200 {"ok": true}
  /chatter/me/accounts                 []
  /chatter/me                          {"chatter": null, "owners": []}
  /events                              an empty text/event-stream
  /admin/employees                     "Alpha One", "Beta Two", "Gamma Three" (each with a login)
  GET  /admin/settings/{tab}           {tab, config} from an in-memory dict ({} when unset)
  PUT  /admin/settings/{tab}           stores the body, returns {tab, config}
  any other /auth/**, /chatter/**, /admin/**, /api/** request   []
  A request to a host other than localhost/127.0.0.1 is aborted and fails the run.
  Pages, scripts and styles go to the dev server. Before every load the first synthetic employee is
  picked and the app's perf telemetry is switched off by its own flag (window.__perfLogNoIngest), so
  POST /admin/perflog/ingest never reaches the Write list.

Walk: the tabs are read from app/lib/nav.ts (the SETTINGS_TABS entries `href: "/settings/<tab>"` without
`legacy: true` or `masterOnly: true`), each opened at 1440x900, then each at 390x844, in the default (dark) theme.
Every non-GET request is recorded on the Write list as [method, path, json body]; the plain walk must
add nothing to it. Then SCENARIOS run at 1440: (tab, name, run(page), want_writes) tuples that later
Phases append to; each checks only the slice of the Write list its run caused. All run in one context;
`security-personal` signs out (a hard navigation to /) as its last action; a later scenario still
opens its own tab, the mocked /auth/me answering as before.

Checks (one {"check","want","got"} JSON line each), on every tab and viewport:
  - no "is not built yet." placeholder;
  - the page is not a 404 (HTTP status, or Next's not-found fallback, which the dev server can serve
    with 200) and renders the Panel header ([data-settings="panel-header"]); a tab failing this gets
    no further checks;
  - no console error and no uncaught page error;
  - no horizontal overflow (document scrollWidth <= clientWidth);
  at 1440 only:
  - the Settings header ([data-settings="header"]) is 48px tall and equal to --if-header-h;
  - its title's font-size equals --if-fs-lg;
  - every tab row ([data-settings="tab"]) is 64px tall and equal to --if-tab-h;
  - the active row ([aria-current="page"]) has color/background-color equal to --if-accent/--if-accent-bg
    (resolved through a probe element);
  - the Panel header ([data-settings="panel-header"]) is 48px tall;
  - independent scroll: the Tab list ([data-settings="tab-list"]) and the Panel body
    ([data-settings="panel-body"]) have overflow-y auto, the Tab area ([data-settings="tab-area"])
    ends at the viewport's bottom (+-1px), the document does not scroll;
  - the Tab list is 18.75% of the Tab area (+-1px): Settings locks the app Sidebar to the 60px rail, so
    the Tab area is 1380px (>= 1200px);
  at 390 only:
  - the strip's rows share one top.
  Once, on /settings/account at 1440: "Toggle sidebar" is disabled (the rail is locked). Once, on
  /settings/time-tracking at 1440 in the dark theme: the live-measured Infloww palette (page-parity ticket
  20), header and Panel rgb(21, 21, 21), Tab list rgb(38, 38, 38), Settings header rule rgb(68, 68, 68)
  and running the full width, the first card 24px under the Panel header (+-1px), the Edit button 32px.
  Once, on /settings/account at 1440 in the light theme
  (chatterly:theme=light): the measured literals, active row rgb(52, 103, 255) on rgb(239, 244, 255),
  Tab list background rgb(245, 245, 245), Settings header rule rgb(230, 230, 230).
  And once: the Write list of the plain walk is [].

Outputs, in /tmp/settings-shots/: settings-<tab>.png (1440x900), settings-<tab>-390.png (390x844), and
settings-report.json {"tabs": {tab: {"1440"|"390": {geometry...}}}, "writes": [...], "failures": [...]}.
Exits 1 on any failure.
"""
import argparse, json, os, re, sys
from urllib.parse import urlparse
from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/settings-shots"
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAV=open(os.path.join(ROOT, "app/lib/nav.ts")).read()
_SETTINGS_TABS=re.search(r"^export const SETTINGS_TABS\b.*?^\];", NAV, re.S|re.M)
TABS=re.findall(r'href: "/settings/([^"]+)"(?![^}\n]*(?:legacy|masterOnly): true)', _SETTINGS_TABS.group(0) if _SETTINGS_TABS else "")
VIEWPORTS=[(1440, 900, ""), (390, 844, "-390")]
UNBUILT="is not built yet."
LOCAL=("localhost", "127.0.0.1")
RELAY=("/auth/", "/chatter/", "/admin/", "/api/")
JSON="application/json"
# Before every load: the first synthetic employee picked, and the app's perf telemetry kept off the
# wire through its own bypass flag (app/lib/perfLog.ts, `__perfLogNoIngest`), so the Write list holds
# only what a Settings control sends.
INIT="window.__perfLogNoIngest = true; localStorage.setItem('chatterly:employee_id', '1');"

USER={"user_id":"u1","username":"tester","is_admin":False}
EMPLOYEES={"employees":[
    {"id":1,"display_name":"Alpha One","color":"#a78bfa","is_active":True,"chatter_id":"c1","created_at":"2026-01-01T00:00:00Z"},
    {"id":2,"display_name":"Beta Two","color":"#60a5fa","is_active":True,"chatter_id":"c2","created_at":"2026-01-01T00:00:00Z"},
    {"id":3,"display_name":"Gamma Three","color":"#34d399","is_active":True,"chatter_id":"c3","created_at":"2026-01-01T00:00:00Z"},
]}
SETTINGS={}  # the in-memory Settings blob store: tab -> config

# (tab, name, run(page), want_writes): later Phases append; each checks the writes its run caused.
SCENARIOS=[]

def save_agency_name(pg):
    """Your Account: type an Agency Name and Save (docs/spec/settings-tabs/phase-01-account-preferences.md)."""
    pg.get_by_label("Agency Name").fill("Synthetic Agency")
    pg.get_by_role("button", name="Save").click()

SCENARIOS.append(("account", "save Agency Name", save_agency_name,
                  [["PUT", "/admin/settings/account", {"agency_name":"Synthetic Agency"}]]))

def save_week_start(pg):
    """Your Preferences: choose Sunday and Save (docs/spec/settings-tabs/phase-01-account-preferences.md)."""
    pg.get_by_role("combobox", name="Week start day").click()
    pg.get_by_role("option", name="Sunday", exact=True).click()
    pg.get_by_role("button", name="Save").click()

SCENARIOS.append(("preferences", "choose Sunday and Save", save_week_start,
                  [["PUT", "/admin/settings/preferences",
                    {"report_tz":"Asia/Tokyo","tz":"Asia/Tokyo","week_start":"sunday","language":"en"}]]))

def security_org(pg):
    """Security (organization): the roster's names show, a force-click on the 2FA switch writes nothing, no
    "Reset" shows (no mock login has 2FA on; Reset renders only where it is), and at 390x844 the table scrolls
    in its own box (docs/spec/settings-tabs/phase-02-security.md, Seam 3)."""
    for name in ("Alpha One", "Beta Two", "Gamma Three"):
        check(f"scenario security-org: {name} shown", pg.get_by_role("cell", name=name).count(), 1)
    pg.get_by_role("switch", name="Two-factor authentication").click(force=True)
    check("scenario security-org: no Reset without 2FA", pg.get_by_role("button", name="Reset").count(), 0)
    pg.set_viewport_size({"width":390,"height":844})
    pg.wait_for_timeout(500)
    got=pg.evaluate("""() => ({
      box_overflow_x: getComputedStyle(document.querySelector('table').parentElement).overflowX,
    })""")
    check("scenario security-org@390: table box overflow-x", got["box_overflow_x"], "auto")
    pg.set_viewport_size({"width":1440,"height":900})

SCENARIOS.append(("security-org", "names shown, 2FA switch writes nothing, no Reset without 2FA", security_org, []))

def security_personal(pg):
    """Security (personal): a force-click on "Enable 2FA" writes
    nothing, then "Sign out" posts {} to /auth/logout (docs/spec/settings-tabs/phase-02-security.md,
    Seam 3). Sign out is a hard navigation, so it is this scenario's last action."""
    pg.get_by_role("button", name="Enable 2FA").click(force=True)
    with pg.expect_navigation(url=f"{BASE}/"):
        pg.get_by_role("button", name="Sign out").click()

SCENARIOS.append(("security-personal", "Enable 2FA writes nothing, Sign out posts /auth/logout {}", security_personal,
                  [["POST", "/auth/logout", {}]]))

def add_role(pg):
    """Role Settings: "+ Add Role", fill "Synthetic Role", Submit, then reload and require the row from
    the mock's stored body, the not-enforced sentence in place of the generic not-applied one (ticket 23 of
    infloww-parity-next-steps applies Roles only once "Enforce role permissions" is on, and the mock's blob has no
    `enforce`; RoleSettingsTab.tsx), and no horizontal overflow at 390x844
    (docs/spec/settings-tabs/phase-03-roles-sales.md, Testing Decisions)."""
    pg.get_by_role("button", name="+ Add Role").click()
    dialog=pg.get_by_role("dialog", name="Add Role")
    dialog.get_by_label("Role Name").fill("Synthetic Role")
    pg.clock.set_fixed_time(ROLE_CLOCK_MS/1000)  # seconds in Python; the id is `role-` + Date.now() in base 36
    dialog.get_by_role("button", name="Submit").click()
    dialog.wait_for(state="hidden")
    open_tab(pg, "roles")
    check("scenario roles: Synthetic Role row after reload", pg.get_by_role("cell", name="Synthetic Role", exact=True).count(), 1)
    check("scenario roles: not-applied sentence", pg.get_by_text("Saved for your organization; not applied yet.").count(), 0)
    check("scenario roles: not-enforced sentence",
          pg.get_by_text("Saved for your organization; not enforced until Enforce role permissions is on.").count(), 1)
    no_overflow_at_390(pg, "roles")

def no_overflow_at_390(pg, tab):
    """At 390x844 the page does not scroll sideways; the viewport goes back to 1440x900 after."""
    pg.set_viewport_size({"width":390,"height":844})
    pg.wait_for_timeout(500)
    check(f"scenario {tab}@390: no horizontal overflow",
          pg.evaluate("() => document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth"), True)
    pg.set_viewport_size({"width":1440,"height":900})

ROLE_CLOCK_MS=1760000000000  # "mgj6k3cw" in base 36
# Every page a role is keyed by: SIDEBAR's hrefs in nav.ts (links and group children, `legacy` skipped);
# SIDEBAR is ONLYFANS_NAV then COMMON_NAV.
# Today this is the same set as `permissionTabs` in app/components/settings/PermissionEditor.tsx, but the
# walk filters line by line: a `legacy: true` group header would drop only that line and keep its children,
# while `permissionTabs` drops the whole group.
SIDEBAR_SRC="".join(NAV.split(f"const {name}: NavNode[] = [", 1)[1].split("\n];", 1)[0] for name in ("ONLYFANS_NAV", "COMMON_NAV"))
PAGES=[h for line in SIDEBAR_SRC.splitlines() if "legacy: true" not in line
       for h in re.findall(r'(?:href:\s*|nb\("[^"]*",\s*)"(/[^"]*)"', line)]
def role(id, name, allowed, scope):
    return {"id":id, "name":name, "description":"", "permissions":{h: allowed for h in PAGES}, "scope":scope}

def roles_put_summary(ws):
    """One PUT to the roles blob: the role ids in order (the built-ins lib/roles.ts seeds, then the new one) and
    the new role exactly as Add Role writes it. The built-ins' own permission defaults are lib/roles.ts's."""
    if len(ws)!=1 or ws[0][:2]!=["PUT", "/admin/settings/roles"]: return ws
    roles=ws[0][2]["roles"]
    return [[r["id"] for r in roles], roles[-1]]

SCENARIOS.append(("roles", "add Synthetic Role, reload, row shown", add_role,
                  (roles_put_summary, [["owner", "admin", "team-leader", "chatter", "creator", "role-mgj6k3cw"],
                                       role("role-mgj6k3cw", "Synthetic Role", False, "self")])))

def sales_message_sender(pg):
    """Sales Settings: require no not-applied sentence (applied since infloww-parity-next-steps tickets 25-26), click "Message sender" and Save, and no horizontal
    overflow at 390x844 (docs/spec/settings-tabs/phase-03-roles-sales.md, Testing Decisions)."""
    check("scenario sales: not-applied sentence", pg.get_by_text("Saved for your organization; not applied yet.").count(), 0)
    pg.get_by_role("radio", name="Message sender").click()
    pg.get_by_role("button", name="Save").click()
    no_overflow_at_390(pg, "sales")

SCENARIOS.append(("sales", "click Message sender and Save", sales_message_sender,
                  [["PUT", "/admin/settings/sales",
                    {"exclude_welcome":False, "exclude_of_fee":False, "multi_employee_shift":False,
                     "attribution":{"messages":"sender", "posts_tips":"shift", "subscriptions_chatter_opt_in":False}}]]))

def time_tracking_save(pg):
    """Time tracking: require no not-applied sentence (applied since infloww-parity-next-steps Phase 2), Edit,
    switch tracking on (Auto clock out shows only then, as live Infloww), type 30; at 390x844 the edit view does
    not overflow; then Save (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md, Acceptance)."""
    check("scenario time-tracking: not-applied sentence", pg.get_by_text("Saved for your organization; not applied yet.").count(), 0)
    pg.get_by_role("button", name="Edit").click()
    pg.get_by_role("switch", name="Enable time tracking").click()
    pg.get_by_label("Auto clock out time").fill("30")
    no_overflow_at_390(pg, "time-tracking")
    pg.get_by_role("button", name="Save").click()

SCENARIOS.append(("time-tracking", "Edit, 30, Save", time_tracking_save,
                  [["PUT", "/admin/settings/time-tracking",
                    {"enabled":True, "auto_clock_out_minutes":30, "clock_in_reminder":False, "role_ids":[]}]]))

def time_tracking_cancel(pg):
    """Time tracking: Edit, type 15, Cancel; the field shows the stored 30 again and nothing is sent
    (Cross-spec decision (d))."""
    pg.get_by_role("button", name="Edit").click()
    pg.get_by_label("Auto clock out time").fill("15")
    pg.get_by_role("button", name="Cancel").click()
    check("scenario time-tracking: Cancel restores the stored minutes", pg.get_by_label("Auto clock out time").input_value(), "30")

SCENARIOS.append(("time-tracking", "Edit, 15, Cancel", time_tracking_cancel, []))

def messaging_switch(pg):
    """Messaging settings: no AI Translator prompt (removed: Google's free translate takes no instructions); at
    390x844 no overflow; turning AI translation off saves at once, the stored prompt key kept."""
    check("scenario messaging: no prompt editor", pg.get_by_label("AI Translator prompt").count(), 0)
    no_overflow_at_390(pg, "messaging")
    pg.get_by_role("switch").first.click()

SCENARIOS.append(("messaging", "AI translation off saves at once", messaging_switch,
                  [["PUT", "/admin/settings/messaging", {"ai_translation":False, "prompt":""}]]))

def billing(pg):
    """Billing: one line, self-hosted and free; no payment actions, no invoice table."""
    check("scenario billing: free line shown", pg.get_by_text("Inflowwww is self-hosted and free", exact=False).count(), 1)
    check("scenario billing: no buttons in the Panel body", pg.locator('[data-settings="panel-body"] button').count(), 0)

SCENARIOS.append(("billing", "one self-hosted, free line", billing, []))

def about(pg):
    """About: in its Panel, "Version " plus the app's version, the desktop-app box's "Download" link to /download and the
    "MIT License" link opening in a new tab, which nothing here follows
    (docs/spec/settings-tabs/phase-05-billing-balance-about.md)."""
    panel=pg.locator('[data-settings="panel"]')
    check("scenario about: Version line shown", panel.get_by_text(re.compile(r"^Version \S+$")).count(), 1)
    check("scenario about: Download link", panel.get_by_role("link", name="Download", exact=True).get_attribute("href"), "/download")
    lic=panel.get_by_role("link", name="MIT License", exact=True)
    check("scenario about: MIT License link", [lic.get_attribute("href").endswith("/blob/main/LICENSE"),
          lic.get_attribute("target"), lic.get_attribute("rel")], [True, "_blank", "noopener noreferrer"])

SCENARIOS.append(("about", "Version line, Download and MIT License links write nothing", about, []))

failures=[]
writes=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")

def reply(route, body, status=200):
    route.fulfill(status=status, content_type=JSON, body=json.dumps(body))

def body_of(req):
    if not req.post_data: return None
    try: return req.post_data_json
    except Exception: return req.post_data

def handle(route):
    req=route.request; u=urlparse(req.url); path=u.path
    if u.hostname not in LOCAL:
        failures.append(f"request to a non-localhost host: {req.url[:120]}")
        return route.abort()
    if req.method!="GET": writes.append([req.method, path, body_of(req)])
    # The shell's live-events stream (lib/events): an empty stream, so it never reaches a relay.
    if path=="/events": return route.fulfill(status=200, content_type="text/event-stream", body="")
    if req.resource_type=="document" or not path.startswith(RELAY): return route.continue_()
    m=re.fullmatch(r"/admin/settings/([^/]+)", path)
    if m:
        tab=m.group(1)
        if req.method=="PUT": SETTINGS[tab]=body_of(req)
        return reply(route, {"tab":tab,"config":SETTINGS.get(tab, {})})
    if path=="/auth/me": return reply(route, USER)
    if path=="/auth/logout": return reply(route, {"ok":True})
    if path=="/chatter/me/accounts": return reply(route, [])
    if path.startswith("/chatter/me"): return reply(route, {"chatter":None,"owners":[]})
    if path=="/admin/employees": return reply(route, EMPLOYEES)
    return reply(route, [])

# The resolved value of a custom property on <html>.
TOKEN="(name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()"
GEOMETRY="""() => {
  const q = (s) => document.querySelector(s);
  const h = q('[data-settings="header"]');
  const t = h && h.querySelector('h1');
  const d = document.scrollingElement;
  const list = q('[data-settings="tab-list"]'), area = q('[data-settings="tab-area"]');
  const ph = q('[data-settings="panel-header"]'), pb = q('[data-settings="panel-body"]');
  const rows = Array.from(document.querySelectorAll('[data-settings="tab"]'));
  const active = q('[data-settings="tab"][aria-current="page"]');
  // The tokens as computed colours: a probe painted with them, then removed.
  const probe = document.createElement('div');
  probe.style.color = 'var(--if-accent)'; probe.style.backgroundColor = 'var(--if-accent-bg)';
  document.body.appendChild(probe);
  const accent = getComputedStyle(probe).color, accent_bg = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return {
    header_h: h ? h.getBoundingClientRect().height : null,
    header_rule: h ? getComputedStyle(h).borderBottomColor : null,
    title_fs: t ? getComputedStyle(t).fontSize : null,
    scroll_w: d.scrollWidth, client_w: d.clientWidth,
    scroll_h: d.scrollHeight, inner_h: innerHeight,
    row_h: rows.map((r) => r.getBoundingClientRect().height),
    row_top: rows.map((r) => Math.round(r.getBoundingClientRect().top)),
    active: active ? [getComputedStyle(active).color, getComputedStyle(active).backgroundColor] : null,
    accent: [accent, accent_bg],
    list_w: list ? list.getBoundingClientRect().width : null,
    list_bg: list ? getComputedStyle(list).backgroundColor : null,
    list_overflow_y: list ? getComputedStyle(list).overflowY : null,
    panel_header_h: ph ? ph.getBoundingClientRect().height : null,
    panel_body_overflow_y: pb ? getComputedStyle(pb).overflowY : null,
    area_w: area ? area.getBoundingClientRect().width : null,
    area_bottom: area ? area.getBoundingClientRect().bottom : null,
    unbuilt: document.body.innerText.includes(%s),
    // Next's not-found fallback; the dev server can answer it with HTTP 200 (streamed).
    not_found: !!q('.next-error-h1') || document.body.innerText.includes('This page could not be found'),
  };
}""" % json.dumps(UNBUILT)

DARK_FRAME="""() => {
  const q = (s) => document.querySelector(s), bg = (e) => e ? getComputedStyle(e).backgroundColor : null;
  const h = q('[data-settings="header"]'), area = q('[data-settings="tab-area"]');
  const ph = q('[data-settings="panel-header"]'), card = q('[data-settings="panel-body"] > *');
  const edit = [...document.querySelectorAll('[data-settings="panel-header"] button')].find((b) => b.textContent.trim() === 'Edit');
  let shell = h; while (shell && bg(shell) === 'rgba(0, 0, 0, 0)') shell = shell.parentElement;
  return {
    header_bg: bg(shell), rule: h ? getComputedStyle(h).borderBottomColor : null,
    header_w: h ? h.getBoundingClientRect().width : null, area_w: area ? area.getBoundingClientRect().width : null,
    list_bg: bg(q('[data-settings="tab-list"]')), panel_bg: bg(shell),
    card_gap: card && ph ? card.getBoundingClientRect().top - ph.getBoundingClientRect().bottom : null,
    edit_h: edit ? edit.getBoundingClientRect().height : null,
  };
}"""

def width_ok(g, fraction):
    """The Tab list's width is `fraction` of the Tab area's, within 1px."""
    return g["list_w"] is not None and g["area_w"] is not None and abs(g["list_w"]-g["area_w"]*fraction)<=1

def open_tab(pg, tab):
    """Load the tab; returns the HTTP status. A page without the Settings header (a 404) is not an
    exception here: the per-tab checks report it."""
    r=pg.goto(f"{BASE}/settings/{tab}", wait_until="load", timeout=90000)
    try: pg.wait_for_selector('[data-settings="header"]', timeout=30000)
    except PlaywrightTimeout: pass
    pg.wait_for_timeout(1500)
    return r.status if r else None

def open_context(b, w, h, init="", timezone_id=None):
    """A fresh browser context at w x h (in `timezone_id` when given) with the init script (plus `init`)
    and the one route handler, and its page."""
    ctx=b.new_context(viewport={"width":w,"height":h}, timezone_id=timezone_id)
    ctx.add_init_script(INIT+init)
    ctx.route("**/*", handle)
    return ctx, ctx.new_page()


def main():
    ap=argparse.ArgumentParser(description="The Settings walk (see the module docstring).")
    ap.parse_args()
    if len(TABS)!=12: failures.append(f"nav.ts: expected 12 Settings tabs, read {TABS}")
    os.makedirs(SHOTS, exist_ok=True)
    report={"tabs":{t:{} for t in TABS}}
    with sync_playwright() as p:
        b=p.chromium.launch()
        for w, h, suffix in VIEWPORTS:
            ctx, pg=open_context(b, w, h)
            errs=[]
            pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
            pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
            for tab in TABS:
                at=f"{tab}@{w}"; errs.clear()
                status=open_tab(pg, tab)
                g=pg.evaluate(GEOMETRY)
                report["tabs"][tab][str(w)]=g
                served=status!=404 and not g["not_found"]
                has_panel=g["panel_header_h"] is not None
                check(f"{at}: not a 404", served, True)
                check(f"{at}: Panel header rendered", has_panel, True)
                if not (served and has_panel):
                    pg.screenshot(path=f"{SHOTS}/settings-{tab}{suffix}.png"); continue  # no Panel to measure
                check(f"{at}: no unbuilt placeholder", g["unbuilt"], False)
                check(f"{at}: console and page errors", [e[:200] for e in errs], [])
                check(f"{at}: no horizontal overflow", g["scroll_w"]<=g["client_w"], True)
                if w==1440:
                    check(f"{at}: Settings header height", g["header_h"], 48)
                    check(f"{at}: Settings header height = --if-header-h", f"{g['header_h']:g}px", pg.evaluate(TOKEN, "--if-header-h"))
                    check(f"{at}: Settings header title size = --if-fs-lg", g["title_fs"], pg.evaluate(TOKEN, "--if-fs-lg"))
                    tab_h=pg.evaluate(TOKEN, "--if-tab-h")
                    check(f"{at}: tab rows 64px", [x for x in g["row_h"] if x!=64], [])
                    check(f"{at}: tab rows = --if-tab-h", [x for x in g["row_h"] if f"{x:g}px"!=tab_h], [])
                    check(f"{at}: active row colours = --if-accent on --if-accent-bg", g["active"], g["accent"])
                    check(f"{at}: Panel header height", g["panel_header_h"], 48)
                    check(f"{at}: Tab list overflow-y", g["list_overflow_y"], "auto")
                    check(f"{at}: Panel body overflow-y", g["panel_body_overflow_y"], "auto")
                    check(f"{at}: Tab area bottom = viewport height +-1px", abs(g["area_bottom"]-h)<=1, True)
                    check(f"{at}: document does not scroll", g["scroll_h"]<=g["inner_h"], True)
                    check(f"{at}: Tab list 18.75% of the Tab area +-1px (rail locked)", width_ok(g, 0.1875), True)
                else:
                    check(f"{at}: strip rows share one top", len(set(g["row_top"])), 1)
                pg.screenshot(path=f"{SHOTS}/settings-{tab}{suffix}.png")
            ctx.close()
        # Settings locks the app Sidebar to the rail, as OF Manager does.
        ctx, pg=open_context(b, 1440, 900)
        open_tab(pg, "account")
        check("account@1440: Toggle sidebar disabled", pg.get_by_role("button", name="Toggle sidebar").is_disabled(), True)
        # The dark frame as measured on Infloww's live Time tracking capture.
        open_tab(pg, "time-tracking")
        d=pg.evaluate(DARK_FRAME)
        report["dark_frame"]=d
        check("time-tracking@1440 dark: header / list / panel / rule colours", [d["header_bg"], d["list_bg"], d["panel_bg"], d["rule"]],
              ["rgb(21, 21, 21)", "rgb(38, 38, 38)", "rgb(21, 21, 21)", "rgb(68, 68, 68)"])
        check("time-tracking@1440 dark: header rule runs the full width", d["header_w"]==d["area_w"], True)
        check("time-tracking@1440 dark: first card 24px under the Panel header +-1px", abs(d["card_gap"]-24)<=1, True)
        check("time-tracking@1440 dark: Edit 32px", d["edit_h"], 32)
        ctx.close()
        # The light pass: the measured Infloww literals (docs/spec/settings-tabs/phase-00-shell-tokens-blob.md).
        ctx, pg=open_context(b, 1440, 900, "localStorage.setItem('chatterly:theme', 'light');")
        open_tab(pg, "account")
        g=pg.evaluate(GEOMETRY)
        report["light"]=g
        check("account@1440 light: active row colours", g["active"], ["rgb(52, 103, 255)", "rgb(239, 244, 255)"])
        check("account@1440 light: Tab list background", g["list_bg"], "rgb(245, 245, 245)")
        check("account@1440 light: Settings header rule", g["header_rule"], "rgb(230, 230, 230)")
        ctx.close()
        check("plain walk: Write list", writes, [])
        if SCENARIOS:
            # Asia/Tokyo, so the Your Preferences zones the browser defaults to are a known value.
            ctx, pg=open_context(b, 1440, 900, timezone_id="Asia/Tokyo")
            for tab, name, run, want in SCENARIOS:
                open_tab(pg, tab)
                start=len(writes)
                run(pg)
                pg.wait_for_timeout(1000)
                # A (summary, want) pair compares a summary of the writes rather than the raw list.
                got=want[0](writes[start:]) if isinstance(want, tuple) else writes[start:]
                check(f"scenario {tab}: {name}: writes", got, want[1] if isinstance(want, tuple) else want)
            ctx.close()
        b.close()
    report["writes"]=writes; report["failures"]=failures
    with open(f"{SHOTS}/settings-report.json", "w") as f: json.dump(report, f, indent=1)
    if failures:
        print("FAIL:", *failures, sep="\n  "); sys.exit(1)
    print(f"settings walk ok: {len(TABS)} tabs x {len(VIEWPORTS)} viewports, {len(writes)} writes")

if __name__=="__main__":
    main()
