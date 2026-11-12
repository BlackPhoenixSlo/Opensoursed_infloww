"""Bio pages, owner editor (PR2a: the relay's /admin/bio-pages API; the bio process on BIO_PORT serves what it
writes): while visitors storm the public pages, owners edit theirs and every edit shows on the bio port at once, link
order is what the last reorder said, no other Agency's page is reachable, the list's 30-day stats match bio_daily,
uploads are served as bounded WebP and every replaced or deleted file leaves the disk, and a mid-load `docker stop` of
the bio process loses no count; every URL the editor shows serves its page on the bio port with that URL's Host.

World: `agency_inbox` plus seed/bio_pages.py (the Agency's Profiles with Links and past bio_daily) plus, by SQL, one
bio_daily view row per profile 29 days back (inside the list's 30-day window) and one 30 days back (outside). A second
Agency signs up through the real POST /auth/register and makes its own page, two links and an avatar through the
admin API (the tenancy oracle). One chatter of the first Agency (seed/chatters.py: invite + register) signs in.

Load (stage `load`): `editors` (`--set editors=3`) owner actors on the owner's session, each with its own seeded
Profiles (every editors-th) and its own new pages, `rounds` rounds each: on a new page create, patch, add 3 links (one
with a stock icon), reorder, stock icon, avatar upload (a generated 1600x900 JPEG with EXIF orientation 6) twice,
background upload (a 2000x1200 PNG with alpha), pings on the bio port, delete a link, delete the page (its buffered
counts become orphan keys); on a seeded Profile patch, reorder (a seeded shuffle, the first link last), retitle a link,
add and delete a link (seeded Links' destinations stay: the visitors' Reveal oracle holds). After every admin write
the editor reads the bio port's Profile JSON. `--users` visitors (actors/bio_visitor.py) run `visits` visits at `rate`
visits/s over the seeded Profiles; each read Profile JSON must hold every seeded Link of its Profile once. Halfway
through the visits the bio process gets SIGTERM (Stack.stop_sidecar, as `docker stop`), with new calls held and none in
flight, and is started again; calls resume on fresh connections.

Checks (lib/bio_faults.py): BIO_ADMIN_EDITS, BIO_ADMIN_ORDER, BIO_ADMIN_TENANCY (before and after the load: every admin
route on the other Agency's page and link, a link of another page under one's own, and its files), BIO_ADMIN_STATS,
BIO_ADMIN_FILES, BIO_DRAIN (the persisted counts right after the SIGTERM exit == seeded + every ping 204 / Reveal 200
answered before it, and again after the load; no `drain lost`, no `counter flush dropped` but orphans, no `batch full`
in bio.log), BIO_PUBLIC_URLS (after the load: every list and P `public_url` == a live domain's `https://<d>/`, else
BIO_PUBLIC_URL/<username>, never a pending domain; it and `<public_url>/<code>` fetched on the bio port with the URL's
Host answer the page's bootstrap), BIO_PAGE / BIO_REVEAL (the visitors' page and Reveal oracle), BIO_NO_LEAK,
BIO_NO_5XX; plus the stock checks.

UI (stage `ui`, after the load; PR2b, skipped under --no-ui): Growth > Tracking links?tab=bio lists every page with
the API's 30-day counts (UI_LIST, shot bio-list); "New bio page" makes one (bio-create-dialog; UI_CREATE: API +
bio_profiles) and opens its editor; a Display name edit + Save (UI_PROFILE: API, SQL, bio port); two links through the
link dialog, the second moved up (UI_LINKS: the PUT's ids, cards == preview == API == bio_links == bio port order;
bio-editor-desktop); on a 390 x 844 phone the editor, the link dialog and Preview (UI_PHONE: no sideways scroll,
full-height dialog, the preview's order; bio-editor-phone, bio-link-dialog-phone, bio-preview). Its bio-port reads
count in BIO_ADMIN_EDITS and BIO_NO_5XX; its reorder in BIO_ADMIN_ORDER (the fault's target; UI_LINKS checks agreement
only, so it stays green).

Budgets [g] (stage `load`): p95 list <= LIST_P95_MS, P <= P_P95_MS, every write <= WRITE_P95_MS, uploads <=
UPLOAD_P95_MS, PR1's visitor budgets; every p95 vs the last green run (P95_VS_LAST: tagged volume).

Bypasses (declared): no Traefik/Caddy in front of either port (the visitors send X-Forwarded-For and CF-* headers
themselves); CHATTERLY_TEST_MODE neuters the relay's pumps and ingest; the past bio_daily rows are seeded by SQL; the
images are generated in-process (Pillow), not picked in a browser (the UI leg uploads none). The relay-side `serving`
probe is real (BIO_HEALTH_URL at the bio port). BIO_PUBLIC_URLS sends each URL's Host straight to the bio port (the
box's Traefik route is not run; the runbook installs its static file on each box).

Break-it-once: FAULT bio-admin-reorder-drops-last (a reorder skips the last id's sort_order) -> BIO_ADMIN_ORDER;
`--fault=bio-admin-no-owner-filter` -> BIO_ADMIN_TENANCY; `--fault=bio-admin-delete-keeps-files` -> BIO_ADMIN_FILES;
`--fault=bio-admin-url-ignores-status` (a pending custom domain becomes the page's URL) -> BIO_PUBLIC_URLS.
"""
from __future__ import annotations

import asyncio
import io
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from PIL import Image

from slop.actors import bio_visitor, ui
from slop.actors.bio_visitor import L_JSON, L_PAGE, L_PING, L_REVEAL, SAME, block
from slop.lib.bio_faults import (BIO_ADMIN_EDITS, BIO_ADMIN_FILES, BIO_ADMIN_ORDER, BIO_ADMIN_STATS,
                                 BIO_ADMIN_TENANCY, BIO_DRAIN, BIO_NO_5XX, BIO_NO_LEAK, BIO_PAGE, BIO_PUBLIC_URLS,
                                 BIO_REVEAL)
from slop.lib.client import Http
from slop.seed import bio_pages, chatters

PROFILE = "agency_inbox"
UI = True
FAULT = "bio-admin-reorder-drops-last"
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20
SIDECARS = {"bio": ("slop/lib/bio.py", "BIO_PORT", "/internal/healthz")}
RELAY_ENV = {"BIO_FLUSH_SECONDS": "0.5", "BIO_ESCAPE_TAP": "1", "BIO_PRIMARY_HOSTS": "127.0.0.1,localhost,bio.slop.test",
             "BIO_PUBLIC_URL": "http://127.0.0.1:{BIO_PORT}",
             "BIO_HEALTH_URL": "http://127.0.0.1:{BIO_PORT}/internal/healthz"}
LIST_P95_MS, P_P95_MS, WRITE_P95_MS, UPLOAD_P95_MS = 150, 100, 200, 1500   # [g]
PAGE_P95_MS, JSON_P95_MS, VISIT_WRITE_P95_MS = 60, 80, 150                  # PR1's
MODES = ("direct", "escape_ig")
ADMIN = "/admin/bio-pages"
AVATAR_SIDE, BACKGROUND_SIDE = 512, 1080
L_ED_JSON, L_ED_FILE = "bio editor GET /api/profiles/:u.json", "bio editor GET /api/files"
L_ED_PING, L_ED_REVEAL = "bio editor ping", "bio editor reveal"
L_URL = "bio editor GET public url"
L_LIST, L_P = f"admin GET {ADMIN}", f"admin GET {ADMIN}/:pid"
WRITES = (f"admin POST {ADMIN}", f"admin PATCH {ADMIN}/:pid", f"admin DELETE {ADMIN}/:pid",
          f"admin POST {ADMIN}/:pid/links", f"admin PUT {ADMIN}/:pid/links/order",
          f"admin PATCH {ADMIN}/:pid/links/:lid", f"admin DELETE {ADMIN}/:pid/links/:lid",
          f"admin DELETE {ADMIN}/:pid/avatar")
UPLOADS = (f"admin POST {ADMIN}/:pid/avatar", f"admin POST {ADMIN}/:pid/links/:lid/background")
BAD_BIO_LOG = re.compile(r"drain lost|counter flush dropped (?!orphan)|batch full")


def public_of(P: dict) -> dict:
    """The Profile JSON the bio port must answer for admin answer P (v2's public-profile.js shape; built here from
    P's fields, as seed/bio_pages.py builds its oracle, not by service code)."""
    p = P["profile"]
    pmode = p["mode"] if p["mode"] in MODES else "escape_ig"
    links = []
    for lk in P["links"]:
        item = {"id": lk["link_id"], "title": lk["title"], "isAdult": lk["is_adult"], "tracking": lk["tracking"]}
        if lk["default_tracking_code"]:
            item["default_tracknumber"] = lk["default_tracking_code"]
        item["mode"] = lk["mode"] if lk["mode"] in MODES else pmode
        item["icon"] = f"/api/files/links/{lk['id']}/{lk['icon']}" if lk["icon"] else ""
        item["backgroundImage"] = (f"/api/files/links/{lk['id']}/{lk['background_image']}"
                                   if lk["background_image"] else "")
        links.append(item)
    return {"profile": {"id": p["id"], "username": p["username"], "displayName": p["display_name"], "bio": p["bio"],
                        "avatarUrl": f"/api/files/profiles/{p['id']}/{p['avatar']}" if p["avatar"] else "",
                        "verified": p["verified"], "mode": pmode},
            "links": links}


def stats_off(listed: list[dict], sql: dict[str, tuple[int, int]]) -> dict:
    """List rows whose (views_30d, clicks_30d) differ from SQL's sums: {pid: {list, sql}}."""
    return {row["id"]: {"list": (row["views_30d"], row["clicks_30d"]), "sql": sql.get(row["id"], (0, 0))}
            for row in listed if (row["views_30d"], row["clicks_30d"]) != sql.get(row["id"], (0, 0))}


def json_links_bad(stable: list[str], body) -> str | None:
    """A visitor-read Profile JSON drops or duplicates a link: why, else None."""
    if not isinstance(body, dict):
        return "unreadable"
    ids = [lk.get("id") for lk in body.get("links", [])]
    if len(ids) != len(set(ids)):
        return "duplicate link"
    missing = set(stable) - set(ids)
    return f"dropped {len(missing)} link(s)" if missing else None


def bio_log_bad(text: str) -> list[str]:
    return [ln[:200] for ln in text.splitlines() if BAD_BIO_LOG.search(ln)]


def jpeg_exif() -> bytes:
    """1600x900 landscape pixels with EXIF orientation 6: shown portrait (the encoder must apply it)."""
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    Image.new("RGB", (1600, 900), (200, 40, 40)).save(buf, "JPEG", exif=exif, quality=80)
    return buf.getvalue()


def png_alpha() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (2000, 1200), (0, 120, 255, 90)).save(buf, "PNG")
    return buf.getvalue()


class Gate:
    """Bio calls wait while the bio process restarts; `close()` returns once none is in flight."""

    def __init__(self):
        self.open = asyncio.Event()
        self.open.set()
        self.flying = 0
        self.idle = asyncio.Event()
        self.idle.set()

    async def __aenter__(self):
        await self.open.wait()
        self.flying += 1
        self.idle.clear()

    async def __aexit__(self, *_):
        self.flying -= 1
        if self.flying == 0:
            self.idle.set()

    async def close(self):
        self.open.clear()
        await self.idle.wait()


async def admin_call(client: Http, method: str, template: str, path: str, *, route: str | None = None, **kw):
    try:
        return await client.request(method, ADMIN + path, route=route or f"admin {method} {ADMIN}{template}", **kw)
    except httpx.HTTPError:
        return None


def tenancy_probes(b_pid: str, b_lid: str, a_pid: str, av: str, bg: str, before: dict):
    return [
        ("GET", "/:pid", f"/{b_pid}", {}), ("PATCH", "/:pid", f"/{b_pid}", {"json": {"display_name": "x"}}),
        ("DELETE", "/:pid", f"/{b_pid}", {}),
        ("POST", "/:pid/avatar", f"/{b_pid}/avatar", {"files": {"file": ("a.png", png_alpha())}}),
        ("DELETE", "/:pid/avatar", f"/{b_pid}/avatar", {}),
        ("POST", "/:pid/links", f"/{b_pid}/links", {"json": {"title": "x", "destination": "https://x.test"}}),
        ("PUT", "/:pid/links/order", f"/{b_pid}/links/order",
         {"json": {"ids": [lk["id"] for lk in before["links"]]}}),
        ("PATCH", "/:pid/links/:lid", f"/{b_pid}/links/{b_lid}", {"json": {"title": "x"}}),
        ("DELETE", "/:pid/links/:lid", f"/{b_pid}/links/{b_lid}", {}),
        ("POST", "/:pid/links/:lid/background", f"/{b_pid}/links/{b_lid}/background",
         {"files": {"file": ("b.png", png_alpha())}}),
        ("DELETE", "/:pid/links/:lid/background", f"/{b_pid}/links/{b_lid}/background", {}),
        ("PATCH", "/:pid/links/:lid", f"/{a_pid}/links/{b_lid}", {"json": {"title": "x"}}),   # B's link, A's page
        ("DELETE", "/:pid/links/:lid", f"/{a_pid}/links/{b_lid}", {}),
        ("GET", "/files", f"/files/profiles/{b_pid}/{av}", {}),
    ] + ([("GET", "/files", f"/files/links/{b_lid}/{bg}", {})] if bg else [])


async def tenancy_check(clients: tuple[Http, Http, Http], ids: tuple[str, str, str, str],
                        stage: str, probes=tenancy_probes) -> list[dict]:
    owner, other, chatter = clients
    b_pid, b_lid, a_pid, a_lid = ids
    bad: list[dict] = []
    before_response = await admin_call(other, "GET", "/:pid", f"/{b_pid}")
    before = before_response.json() if before_response is not None and before_response.status_code == 200 else None
    if not isinstance(before, dict) or "links" not in before:
        bad.append({"stage": stage, "other Agency's page gone": True})
        return bad
    av, bg = before["profile"]["avatar"], before["links"][0]["background_image"]
    for method, tpl, path, kw in probes(b_pid, b_lid, a_pid, av, bg, before):
        r = await admin_call(owner, method, tpl, path, route=f"tenancy {method} {ADMIN}{tpl}",
                             expect=(404,), **kw)
        if r is None or r.status_code != 404:
            bad.append({"stage": stage, "owner on other": f"{method} {path}",
                        "status": getattr(r, "status_code", None)})
    listed = (await admin_call(owner, "GET", "", "", route=f"tenancy GET {ADMIN}")).json()["profiles"]
    if b_pid in {row["id"] for row in listed}:
        bad.append({"stage": stage, "owner list": "holds the other Agency's page"})
    for method, tpl, path, kw in (("GET", "", "", {}), ("GET", "/:pid", f"/{a_pid}", {}),
                                  ("POST", "", "", {"json": {"username": "slopbiochatx", "display_name": "x"}}),
                                  ("PATCH", "/:pid/links/:lid", f"/{a_pid}/links/{a_lid}",
                                   {"json": {"title": "x"}})):
        r = await admin_call(chatter, method, tpl, path, route=f"tenancy chatter {method} {ADMIN}{tpl}",
                             expect=(403,), **kw)
        if r is None or r.status_code != 403:
            bad.append({"stage": stage, "chatter": f"{method} {path}",
                        "status": getattr(r, "status_code", None)})
    after_response = await admin_call(other, "GET", "/:pid", f"/{b_pid}")
    after = after_response.json() if after_response is not None and after_response.status_code == 200 else None
    if after != before:
        bad.append({"stage": stage, "other Agency's page changed": True})
    r = await admin_call(other, "GET", "/files", f"/files/profiles/{b_pid}/{av}")
    if r is None or r.status_code != 200:
        bad.append({"stage": stage, "other Agency's avatar": getattr(r, "status_code", None)})
    return bad


def want_public_url(row: dict, base: str) -> str:
    """The public_url the owner API should report: a live custom domain, else the configured base + /<u>."""
    dom = row["custom_domain"]
    if dom and dom["status"] == "live":
        return f"https://{dom['domain']}/"
    return f"{base}/{row['username']}"


async def public_urls_check(owner: Http, bio, rng, expected_base: str) -> tuple[list[dict], Counter]:
    """BIO_PUBLIC_URLS: every list row's and its P's `public_url` is the expected one, and that URL and its tracking
    URL serve the page (bootstrap username, code, profilePath) on the bio port with the URL's Host."""
    bad: list[dict] = []
    n: Counter = Counter()
    r = await admin_call(owner, "GET", "", "", route=f"urls GET {ADMIN}")
    body = r.json() if r is not None and r.status_code == 200 else {}
    if body.get("public_base") != expected_base:
        bad.append({"public_base": body.get("public_base"), "want": expected_base})
    for row in body.get("profiles", []):
        dom = row["custom_domain"]
        n[dom["status"] if dom else "no domain"] += 1
        rp = await admin_call(owner, "GET", "/:pid", f"/{row['id']}", route=f"urls GET {ADMIN}/:pid")
        pbody = rp.json() if rp is not None and rp.status_code == 200 else {}
        P = pbody.get("profile") if isinstance(pbody, dict) else None
        if P is None:
            bad.append({"user": row["username"], "P": "unreadable"})
        want = want_public_url(row, expected_base)
        for src, url in (("list", row["public_url"]), ("P", P["public_url"] if P else "unreadable")):
            if url != want:
                bad.append({"user": row["username"], "from": src, "public_url": url, "want": want, "domain": dom})
        url = row["public_url"]
        if not url:
            bad.append({"user": row["username"], "public_url": "missing"})
            continue
        for code in (None, str(rng.randint(1, 99_999))):
            target = urlsplit(want.rstrip("/") + (f"/{code}" if code else ""))
            host, path = target.netloc, target.path or "/"
            ppath = urlsplit(want).path or "/"
            n["fetched"] += 1
            resp = await bio(L_URL, "GET", path, headers={"Host": host})
            got = (block(resp.text) if resp is not None and resp.status_code == 200
                   else getattr(resp, "status_code", None))
            exp = {"username": row["username"], "trackingCode": code, "profilePath": ppath}
            if got != exp:
                bad.append({"url": url, "code": code, "host": host, "path": path, "got": got, "want": exp})
    return bad, n


# ── UI: Growth > Tracking links > Bio pages and the editor (PR2b) ────────
UI_LIST = "UI: the Bio pages tab lists every page of the API's list with its 30-day views and clicks (== API)"
UI_CREATE = "UI: New bio page creates the page (API + bio_profiles row of the owner) and opens its editor"
UI_PROFILE = "UI: a Display name edit + Save lands in the API, bio_profiles and the bio port's Profile JSON"
UI_LINKS = ("UI: two links added in the link dialog, the second moved up: the UI sends that order, and the cards, the "
            "preview, the API, bio_links and the bio port's Profile JSON agree on the order the API kept")
UI_PHONE = ("UI: on a 390 x 844 phone the editor and the link dialog (full height) scroll no sideways, and Preview "
            "draws the page's links in the API's order")
UI_PUBLIC = "UI: Open shows the saved name and links on the bio port"
UI_CHECKS = (UI_LIST, UI_CREATE, UI_PROFILE, UI_LINKS, UI_PHONE, UI_PUBLIC)
UI_TITLES = ("Slop UI first", "Slop UI second")
ROWS_JS = """() => Object.fromEntries([...document.querySelectorAll('[data-bio-page]')].map((li) => [
  li.dataset.bioPage, ['[data-views]', '[data-clicks]'].map((s) => {
    const t = (li.querySelector(s)?.textContent ?? '').replace(/[^0-9]/g, '');
    return t === '' ? null : Number(t);
  })]))"""
TITLES_JS = "(sel) => [...document.querySelectorAll(sel)].map((e) => e.getAttribute(sel.slice(1, -1)))"
# Manual break probe: append a 600px-wide child to the dialog body; _fits(await page.evaluate(FITS_JS)) must turn false.
SETTLED_JS = """() => document.getAnimations().filter((a) => a.playState === 'running'
  && a.effect && a.effect.getComputedTiming().iterations !== Infinity).length === 0"""
FITS_JS = """() => ({vw: innerWidth,
  overflow: [...document.querySelectorAll('main *, [role=dialog] *')].filter((e) =>
    e.getBoundingClientRect().right > innerWidth + 1).map((e) => e.tagName),
  dialogs: [...document.querySelectorAll('[role=dialog]')].map((d) => ({
    right: d.getBoundingClientRect().right,
    sw: d.querySelector('.overflow-y-auto')?.scrollWidth,
    cw: d.querySelector('.overflow-y-auto')?.clientWidth}))})"""


async def _shot(ctx, page, name: str) -> str:
    """Screenshot once finite animations (a dialog's fade in / out) are done, so a shot never catches a half-faded modal."""
    await page.wait_for_function(SETTLED_JS, timeout=15_000)
    return await ui.shot(ctx, page, name)


def _fits(f: dict) -> bool:
    return not f["overflow"] and all(d["right"] <= f["vw"] + 1 and d["sw"] <= d["cw"] + 1
                                      for d in f["dialogs"])


async def _ui(ctx, w, owner: Http, user: str, *, bio, shows, order_note, counts, done: set) -> None:
    """The editor's flow in the browser, every step's side effect read back through the API, SQL and the bio port.
    `bio`/`shows`: the scenario's bio-port reads (BIO_NO_5XX, BIO_ADMIN_EDITS); `order_note`: a UI reorder the API
    did not keep (BIO_ADMIN_ORDER, the fault's target; UI_LINKS checks agreement, so the fault leaves it green)."""
    from playwright.async_api import expect

    def check(name, ok, **detail):
        done.add(name)
        ctx.check(name, ok, **detail)

    async def api_page(pid: str) -> dict | None:
        r = await admin_call(owner, "GET", "/:pid", f"/{pid}", route=f"ui GET {ADMIN}/:pid")
        return r.json() if r is not None and r.status_code == 200 else None

    def sql(q: str, *a):
        con = w.sql()
        try:
            return con.execute(q, a).fetchall()
        finally:
            con.close()

    name0, name1 = "Slop UI page", "Slop UI page edited"
    async with ui.owner_browser(ctx) as page:
        await page.goto(f"{ctx.app}/growth/tracking-links?tab=bio", wait_until="domcontentloaded", timeout=90_000)
        await page.locator("[data-bio-page]").first.wait_for(timeout=90_000)
        rows = await page.evaluate(ROWS_JS)
        await _shot(ctx, page, "bio-list")
        r = await admin_call(owner, "GET", "", "", route=f"ui GET {ADMIN}")
        listed = r.json()["profiles"] if r is not None and r.status_code == 200 else []
        want = {p["username"]: [p["views_30d"], p["clicks_30d"]] for p in listed}
        check(UI_LIST, bool(want) and rows == want, rows=len(rows), api_rows=len(want),
              off={u: {"ui": rows.get(u), "api": v} for u, v in want.items() if rows.get(u) != v} | {
                  u: {"ui": v, "api": None} for u, v in rows.items() if u not in want})

        await page.get_by_role("button", name="New bio page").click()
        dlg = page.get_by_role("dialog", name="New bio page")
        await dlg.get_by_label("Username").fill(user)
        await dlg.get_by_label("Display name").fill(name0)
        await _shot(ctx, page, "bio-create-dialog")
        await dlg.get_by_role("button", name="Create").click()
        await page.wait_for_url(re.compile(r".*/growth/tracking-links/bio/[a-z0-9]+$"), timeout=90_000)
        pid = page.url.rstrip("/").rsplit("/", 1)[1]
        P = await api_page(pid)
        db = sql("SELECT owner_user_id, username, display_name FROM bio_profiles WHERE id = ?", pid)
        check(UI_CREATE, P is not None and P["profile"]["username"] == user and P["profile"]["display_name"] == name0
              and db == [(w.user_id, user, name0)], pid=pid, url=page.url, api=P and P["profile"], db=db)

        name_in = page.get_by_label("Display name")
        await expect(name_in).to_have_value(name0, timeout=90_000)
        await name_in.fill(name1)
        await page.get_by_role("button", name="Save", exact=True).click()
        await page.get_by_text("Saved", exact=True).wait_for(timeout=30_000)
        P = await api_page(pid)
        (db_name,) = sql("SELECT display_name FROM bio_profiles WHERE id = ?", pid) or [(None,)]
        rj = await bio(L_ED_JSON, "GET", f"/api/profiles/{user}.json")
        shown = rj.json()["profile"]["displayName"] if rj is not None and rj.status_code == 200 else None
        if P:
            await shows(P, "ui profile", 0)
        check(UI_PROFILE, P is not None and P["profile"]["display_name"] == db_name[0] == shown == name1,
              api=P and P["profile"]["display_name"], db=db_name[0], bio_json=shown)

        for n, title in enumerate(UI_TITLES):
            await page.get_by_role("button", name="Add link").click()
            dlg = page.get_by_role("dialog", name="Add link")
            await dlg.get_by_label("Title").fill(title)
            await dlg.get_by_label("Destination").fill(f"https://dest.slop.test/slopdest-ui-{n}")
            await dlg.get_by_role("button", name="Save link").click()
            await dlg.wait_for(state="hidden", timeout=30_000)
            await page.locator(f'[data-bio-link="{title}"]').wait_for(timeout=30_000)
        added = await api_page(pid) or {"links": []}
        intended = [lk["id"] for lk in added["links"]][::-1]   # the second moved up: [second, first]
        async with page.expect_response(lambda x: x.url.endswith("/links/order") and x.request.method == "PUT") as got:
            await page.get_by_role("button", name=f"Move {UI_TITLES[1]} up").click()
        resp = await got.value
        sent = (resp.request.post_data_json or {}).get("ids")
        kept = [lk["title"] for lk in (await resp.json()).get("links", [])] if resp.ok else []
        await page.wait_for_function(f"(want) => JSON.stringify(({TITLES_JS})('[data-bio-link]')) === "
                                     "JSON.stringify(want)", arg=kept, timeout=30_000)
        cards = await page.evaluate(TITLES_JS, "[data-bio-link]")
        preview = await page.evaluate(TITLES_JS, "[data-preview-link]")
        await _shot(ctx, page, "bio-editor-desktop")
        P = await api_page(pid) or {"profile": {}, "links": []}
        api_ids = [lk["id"] for lk in P["links"]]
        db_ids = [x for (x,) in sql("SELECT id FROM bio_links WHERE profile_id = ? ORDER BY sort_order, id", pid)]
        rj = await bio(L_ED_JSON, "GET", f"/api/profiles/{user}.json")
        by_link = {lk["link_id"]: lk["id"] for lk in P["links"]}
        json_ids = ([by_link.get(lk.get("id")) for lk in rj.json().get("links", [])]
                    if rj is not None and rj.status_code == 200 else None)
        counts["reorders"] += 1
        if api_ids != intended:
            order_note({"reorder": "ui move up", "sent": intended, "got": api_ids})
        if P["links"]:
            await shows(P, "ui reorder", 0)
        titles = [lk["title"] for lk in P["links"]]
        dests = sorted(lk["destination"] for lk in P["links"])
        check(UI_LINKS, resp.ok and sent == intended and len(intended) == 2 and sorted(titles) == sorted(UI_TITLES)
              and cards == preview == titles == kept and api_ids == db_ids == json_ids
              and dests == [f"https://dest.slop.test/slopdest-ui-{n}" for n in range(2)],
              put_status=resp.status, sent=sent, intended=intended, cards=cards, preview=preview, api=titles,
              api_ids=api_ids, db_ids=db_ids, bio_json_ids=json_ids, destinations=dests)

    async with ui.owner_browser(ctx, viewport=(390, 844), touch=True) as page:
        await page.goto(f"{ctx.app}/growth/tracking-links/bio/{pid}", wait_until="domcontentloaded", timeout=90_000)
        await page.locator("[data-bio-link]").first.wait_for(timeout=90_000)
        await page.wait_for_function(SETTLED_JS, timeout=15_000)
        wide_editor = await page.evaluate(FITS_JS)
        await _shot(ctx, page, "bio-editor-phone")
        await page.get_by_role("button", name="Add link").click()
        dlg = page.get_by_role("dialog", name="Add link")
        await dlg.wait_for(timeout=30_000)
        await page.wait_for_function(SETTLED_JS, timeout=15_000)
        box = await dlg.bounding_box() or {}
        wide_dialog = await page.evaluate(FITS_JS)
        await _shot(ctx, page, "bio-link-dialog-phone")
        await dlg.get_by_role("button", name="Cancel").click()
        await dlg.wait_for(state="hidden", timeout=30_000)
        await page.get_by_role("radio", name="Preview").click()
        pv = page.locator("[data-bio-preview]")
        await pv.wait_for(state="visible", timeout=30_000)
        await page.wait_for_function(SETTLED_JS, timeout=15_000)
        phone_preview = await page.evaluate(TITLES_JS, "[data-preview-link]")
        wide_preview = await page.evaluate(FITS_JS)
        await _shot(ctx, page, "bio-preview")
        check(UI_PHONE, _fits(wide_editor) and _fits(wide_dialog) and _fits(wide_preview)
              and box.get("height", 0) >= 844 - 40 and phone_preview == titles,
              fit={"editor": wide_editor, "dialog": wide_dialog, "preview": wide_preview},
              dialog_height=box.get("height"), preview=phone_preview, api=titles)

        # Follow the editor's Open action to the real bio sidecar.
        await page.get_by_role("radio", name="Edit").click()
        async with page.expect_popup() as opened:
            await page.get_by_role("link", name="Open the page").click()
        public = await opened.value
        await public.wait_for_load_state("domcontentloaded")
        await expect(public.locator("#displayName")).to_have_text(name1, timeout=30_000)
        public_titles = await public.locator(".link-title").all_text_contents()
        await _shot(ctx, public, "bio-editor-public")
        check(UI_PUBLIC, public_titles == titles,
              url=public.url, display_name=name1, links=public_titles, api=titles)
        await public.close()


async def run(ctx) -> None:
    if ctx.stack.shards > 1:
        raise RuntimeError("bio-pages-editor runs on one shard only (one bio sidecar uses shard 0)")
    port = ctx.stack.extra_ports["BIO_PORT"]
    files_dir = ctx.stack.shard_svc[0] / "bio_files"
    w = await ctx.build(PROFILE)
    bp = bio_pages.seed(w, w.data["creators"], profiles=ctx.param("profiles", w.size["bio_pages_profiles"]),
                        links=ctx.param("links", w.size["bio_pages_links"]))
    profiles = bp["profiles"]
    n_editors = max(1, min(ctx.param("editors", 3), len(profiles)))
    rounds = ctx.param("rounds", {"small": 3, "medium": 6, "huge": 10}[ctx.scale])
    n_visits = ctx.param("visits", w.size["bio_pages_visits"] // 2)
    rate = ctx.param("rate", {"small": 40.0, "medium": 120.0, "huge": 200.0}[ctx.scale])
    rng = w.rng("scenario:bio-pages-editor")
    rngs = [w.rng(f"scenario:bio-pages-editor:e{e}") for e in range(n_editors)]

    # 30-day window edges: one view 29 days back (counted), one 30 days back (not)
    today = datetime.now(timezone.utc).date()
    past = dict(bp["past"])
    edge_rows = []
    for p in profiles:
        for back, views in ((29, 7), (30, 1000)):
            d = (today - timedelta(days=back)).isoformat()
            edge_rows.append((d, p["id"], "", "ZZ", "", "", views, 0))
            prev = past.get((p["id"], "", d), (0, 0))
            past[(p["id"], "", d)] = (prev[0] + views, prev[1])
    con = w.sql()
    try:
        with con:
            con.executemany("INSERT INTO bio_daily(day, profile_id, link_id, country, in_app, code, views, clicks)"
                            " VALUES (?,?,?,?,?,?,?,?)", edge_rows)
    finally:
        con.close()

    # ── sessions: the owner (A), a second Agency (B), A's chatter ────────
    owner = ctx.owner.share(ctx.rec, limits=8)
    b_http = Http(ctx.relay, ctx.rec, limits=4)
    r = await b_http.post("/auth/register", json={"username": f"slopbiob{w.seed}", "password": "slop-throwaway-pw"})
    r.raise_for_status()
    other = b_http.share(ctx.rec, limits=8)
    chat_rec = await chatters.seed(w, ctx.owner, w.user_id, [f"slopbiochat{w.seed}"])
    chat_http = Http(ctx.relay, ctx.rec, limits=4)
    r = await chat_http.post("/chatter/login", json={"username": chat_rec[0]["username"],
                                                     "password": chat_rec[0]["password"]})
    r.raise_for_status()
    chatter = chat_http.share(ctx.rec, limits=8)

    ctx.rec.stage = "setup"
    r = await admin_call(other, "POST", "", "", json={"username": f"slopbiob{w.seed}", "display_name": "Other Agency"})
    r.raise_for_status()
    b_pid = r.json()["profile"]["id"]
    for k in range(2):
        r = await admin_call(other, "POST", "/:pid/links", f"/{b_pid}/links",
                             json={"title": f"B {k}", "destination": f"https://dest.slop.test/slopdest-b-{k}"})
        r.raise_for_status()
    r = await admin_call(other, "POST", "/:pid/avatar", f"/{b_pid}/avatar", files={"file": ("a.jpg", jpeg_exif())})
    r.raise_for_status()
    b_page = r.json()
    b_lid = b_page["links"][0]["id"]

    # ── bookkeeping ──────────────────────────────────────────────────────
    gate = Gate()
    vis = bio_visitor.Visitors(ctx.rec, f"http://127.0.0.1:{port}", ctx.users)
    edits_bad, order_bad, files_bad, tenancy_bad = [], [], [], []
    counts = Counter()
    stable = {p["username"]: [lk["link_id"] for lk in p["links"]] for p in profiles}

    def note(bad: list, item) -> None:
        if len(bad) < 10:
            bad.append(item)

    def on_json(p, r):
        counts["visitor_json"] += 1
        if r is None or r.status_code != 200:
            note(order_bad, {"visitor": p["username"], "status": getattr(r, "status_code", None)})
            return
        why = json_links_bad(stable[p["username"]], r.json())
        if why:
            note(order_bad, {"visitor": p["username"], "why": why})

    vis.on_json = on_json

    async def bio(lbl, method, path, k=0, **kw):
        async with gate:
            return await vis.call(vis.clients[k % len(vis.clients)], lbl, method, path, **kw)

    async def shows(P: dict, what: str, k: int) -> None:
        """BIO_ADMIN_EDITS: the bio port answers P's public view right after the write."""
        counts["edits"] += 1
        r = await bio(L_ED_JSON, "GET", f"/api/profiles/{P['profile']['username']}.json", k)
        got = r.json() if r is not None and r.status_code == 200 else getattr(r, "status_code", None)
        if got != public_of(P):
            note(edits_bad, {"after": what, "user": P["profile"]["username"], "got": got, "want": public_of(P)})

    async def served(url: str, side: int, k: int, *, portrait=False, alpha=False, what="") -> None:
        counts["files_served"] += 1
        r = await bio(L_ED_FILE, "GET", url, k)
        if r is None or r.status_code != 200 or r.headers.get("content-type") != "image/webp":
            note(files_bad, {"what": what, "url": url, "status": getattr(r, "status_code", None),
                             "type": r.headers.get("content-type") if r is not None else None})
            return
        im = Image.open(io.BytesIO(r.content))
        if im.format != "WEBP" or max(im.size) > side or (portrait and im.size[1] <= im.size[0]) or \
                (alpha and im.mode != "RGBA"):
            note(files_bad, {"what": what, "url": url, "format": im.format, "size": im.size, "mode": im.mode})

    def gone(what: str, collection: str, rid: str, name: str | None = None) -> None:
        counts["files_gone"] += 1
        path = files_dir / collection / rid / (name or "")
        if (path.exists() if name else path.is_dir() and any(path.iterdir())):
            note(files_bad, {"what": what, "still on disk": str(path.relative_to(files_dir))})

    def on_disk(what: str, collection: str, rid: str, name: str) -> None:
        path = files_dir / collection / rid / name
        if not path.is_file():
            note(files_bad, {"what": what, "missing on disk": str(path.relative_to(files_dir))})

    async def ok(r, what: str, want=(200, 201)):
        if r is None or r.status_code not in want:
            note(edits_bad, {"write": what, "status": getattr(r, "status_code", None),
                             "body": r.text[:200] if r is not None else None})
            return None
        return r.json() if r.status_code != 204 else {}

    async def reorder(e: int, P: dict, what: str) -> dict | None:
        ids = [lk["id"] for lk in P["links"]]
        new = ids[1:]
        rngs[e].shuffle(new)   # the first link goes last: a reorder that skips the last id cannot come out right
        new.append(ids[0])
        got = await ok(await admin_call(owner, "PUT", "/:pid/links/order", f"/{P['profile']['id']}/links/order",
                                        json={"ids": new}), what)
        if got is None:
            return None
        counts["reorders"] += 1
        if [lk["id"] for lk in got["links"]] != new:
            note(order_bad, {"reorder": what, "sent": new, "got": [lk["id"] for lk in got["links"]]})
        await shows(got, what, e)
        return got

    # ── tenancy probes ───────────────────────────────────────────────────
    ctx.rec.stage = "probe"
    r = await admin_call(owner, "GET", "", "", route=f"probe GET {ADMIN}")
    serving_before = r is not None and r.status_code == 200 and r.json().get("serving") is True
    tenancy_bad.extend(await tenancy_check((owner, other, chatter), (b_pid, b_lid, profiles[0]["id"],
                                                            profiles[0]["links"][0]["id"]), "before"))

    # ── editors ──────────────────────────────────────────────────────────
    jpeg, png = jpeg_exif(), png_alpha()
    load_done = asyncio.Event()

    async def editor(e: int) -> None:
        mine = profiles[e::n_editors]
        for rd in range(rounds):
            tag = f"e{e} r{rd}"
            # a new page, the whole lifecycle
            got = await ok(await admin_call(owner, "POST", "", "", json={"username": f"slopbioed{w.seed}_{e}_{rd}",
                                                                  "display_name": f"Ed {e}.{rd}"}), f"{tag} create")
            if got is None:
                continue
            pid, user = got["profile"]["id"], got["profile"]["username"]
            await shows(got, f"{tag} create", e)
            got = await ok(await admin_call(owner, "PATCH", "/:pid", f"/{pid}", json={
                "display_name": f"Ed {e}.{rd} — café", "bio": "<b>hi</b> & bye", "mode": "direct",
                "verified": rd % 2 == 0}), f"{tag} patch") or got
            await shows(got, f"{tag} patch", e)
            for k in range(3):
                body = {"title": f"L{k}", "destination": f"https://dest.slop.test/slopdest-ed-{e}-{rd}-{k}",
                        "tracking": k % 2 == 0, "is_adult": k == 1, "default_tracking_code": "7" if k == 2 else ""}
                if k < 2:
                    body["icon"] = ("onlyicon", "linkicon")[k]
                got = await ok(await admin_call(owner, "POST", "/:pid/links", f"/{pid}/links", json=body),
                               f"{tag} link {k}") or got
                await shows(got, f"{tag} link {k}", e)
            got = await reorder(e, got, f"{tag} reorder new") or got
            lid = got["links"][-1]["id"]
            old_icon = next(lk["icon"] for lk in got["links"] if lk["id"] == lid)
            got = await ok(await admin_call(owner, "PATCH", "/:pid/links/:lid", f"/{pid}/links/{lid}",
                                            json={"icon": "igicon"}), f"{tag} icon") or got
            await shows(got, f"{tag} icon", e)
            lk = next(lk for lk in got["links"] if lk["id"] == lid)
            if lk["icon_stock"] != "igicon":
                note(files_bad, {"what": f"{tag} icon", "icon_stock": lk["icon_stock"]})
            else:
                await served(f"/api/files/links/{lid}/{lk['icon']}", 10_000, e, what=f"{tag} stock icon")
            if old_icon:
                gone(f"{tag} replaced icon", "links", lid, old_icon)
            prev = None
            for n in range(2):
                got = await ok(await admin_call(owner, "POST", "/:pid/avatar", f"/{pid}/avatar",
                                                files={"file": ("me.jpg", jpeg)}), f"{tag} avatar {n}") or got
                av = got["profile"]["avatar"]
                await shows(got, f"{tag} avatar {n}", e)
                await served(f"/api/files/profiles/{pid}/{av}", AVATAR_SIDE, e, portrait=True, what=f"{tag} avatar")
                if prev:
                    gone(f"{tag} replaced avatar", "profiles", pid, prev)
                prev = av
            got = await ok(await admin_call(owner, "POST", "/:pid/links/:lid/background", f"/{pid}/links/{lid}/background",
                                            files={"file": ("bg.png", png)}), f"{tag} background") or got
            bg = next(lk["background_image"] for lk in got["links"] if lk["id"] == lid)
            await shows(got, f"{tag} background", e)
            await served(f"/api/files/links/{lid}/{bg}", BACKGROUND_SIDE, e, alpha=True, what=f"{tag} background")
            on_disk(f"{tag} background", "links", lid, bg)
            got = await ok(await admin_call(owner, "DELETE", "/:pid/avatar", f"/{pid}/avatar"), f"{tag} avatar off") or got
            await shows(got, f"{tag} avatar off", e)
            gone(f"{tag} removed avatar", "profiles", pid, prev)
            for _ in range(3):   # counts buffered for a page about to go: orphan keys at the next flush
                await bio(L_ED_PING, "POST", f"/v/{user}", e, headers={"X-Forwarded-For": f"100.126.{e}.{rd}"})
            dead = next(lk for lk in got["links"] if lk["id"] == lid)
            got = await ok(await admin_call(owner, "DELETE", "/:pid/links/:lid", f"/{pid}/links/{lid}"), f"{tag} unlink") \
                or got
            await shows(got, f"{tag} unlink", e)
            gone(f"{tag} deleted link", "links", lid)
            r = await bio(L_ED_REVEAL, "GET", f"/.netlify/functions/reveal?id={dead['link_id']}&user={user}", e,
                          headers=SAME, expect=(404,))
            if r is None or r.status_code != 404:
                note(files_bad, {"what": f"{tag} deleted link's Reveal", "status": getattr(r, "status_code", None)})
            left = [lk["id"] for lk in got["links"]]
            await ok(await admin_call(owner, "GET", "/:pid", f"/{pid}"), f"{tag} get")
            await ok(await admin_call(owner, "DELETE", "/:pid", f"/{pid}"), f"{tag} delete", want=(204,))
            gone(f"{tag} deleted page", "profiles", pid)
            for x in left:
                gone(f"{tag} deleted page's link", "links", x)
            r = await bio(L_ED_JSON, "GET", f"/api/profiles/{user}.json", e, expect=(404,))
            if r is None or r.status_code != 404:
                note(edits_bad, {"after": f"{tag} delete", "bio JSON status": getattr(r, "status_code", None)})
            # one of the editor's seeded Profiles: edits under the visitors' reads
            sp = mine[rd % len(mine)]
            got = await ok(await admin_call(owner, "PATCH", "/:pid", f"/{sp['id']}",
                                            json={"display_name": f"Slop Bio {sp['gp']} ({tag})"}), f"{tag} s-patch")
            if got is None:
                continue
            await shows(got, f"{tag} s-patch", e)
            got = await reorder(e, got, f"{tag} s-reorder") or got
            first = got["links"][0]["id"]
            got = await ok(await admin_call(owner, "PATCH", "/:pid/links/:lid", f"/{sp['id']}/links/{first}",
                                            json={"title": f"Retitled {tag}"}), f"{tag} s-retitle") or got
            await shows(got, f"{tag} s-retitle", e)
            got = await ok(await admin_call(owner, "POST", "/:pid/links", f"/{sp['id']}/links", json={
                "title": "Temp", "destination": f"https://dest.slop.test/slopdest-tmp-{e}-{rd}"}), f"{tag} s-link")
            if got:
                await shows(got, f"{tag} s-link", e)
                tmp = next(lk["id"] for lk in got["links"] if lk["title"] == "Temp")
                got = await ok(await admin_call(owner, "DELETE", "/:pid/links/:lid", f"/{sp['id']}/links/{tmp}"),
                               f"{tag} s-unlink")
                if got:
                    await shows(got, f"{tag} s-unlink", e)
            r = await admin_call(owner, "GET", "", "")
            if r is None or r.status_code != 200:
                note(edits_bad, {"list": getattr(r, "status_code", None)})
        if not load_done.is_set():   # keep editing seeded pages while the visitors run (reorders under reads)
            while not load_done.is_set():
                sp = mine[counts["extra"] % len(mine)]
                counts["extra"] += 1
                got = await ok(await admin_call(owner, "GET", "/:pid", f"/{sp['id']}"), "extra get")
                if got:
                    await reorder(e, got, "extra s-reorder")
                await asyncio.sleep(0.2)

    # ── visitors + the drain ─────────────────────────────────────────────
    plan = bio_visitor.plan(rng, profiles, n_visits, 0.4)
    drain: dict = {}

    async def drain_once() -> None:
        await gate.close()
        snap_v, snap_c = len(vis.views_ok), len(vis.clicks_ok)
        t, took = await asyncio.to_thread(ctx.stack.stop_sidecar, "bio")
        con = w.sql()
        try:
            tv, tc = con.execute("SELECT COALESCE(SUM(views),0), COALESCE(SUM(clicks),0) FROM bio_daily "
                                 "WHERE profile_id IN (%s)" % ",".join("?" * len(profiles)),
                                 [p["id"] for p in profiles]).fetchone()
        finally:
            con.close()
        await asyncio.to_thread(ctx.stack.start_sidecar, "bio")
        await vis.reopen()
        gate.open.set()
        pv, pc = sum(v for v, _ in past.values()), sum(c for _, c in past.values())
        drain.update(exit_s=None if took is None else round(took, 2), answered=(snap_v, snap_c),
                     persisted=(tv - pv, tc - pc), restarted_at=round(t, 1))

    async def visitors() -> None:
        t0 = time.perf_counter()
        half = len(plan) // 2
        tasks = []
        for k, v in enumerate(plan):
            if k == half:
                await asyncio.gather(*tasks)
                d0 = time.perf_counter()
                await drain_once()
                t0 += time.perf_counter() - d0
            delay = t0 + k / rate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(gated_visit(k, v)))
        await asyncio.gather(*tasks)
        load_done.set()

    async def gated_visit(k, v):
        async with gate:
            await vis.visit(k, v)

    ctx.rec.stage = "load"
    t_load = time.perf_counter()
    await asyncio.gather(visitors(), *(editor(e) for e in range(n_editors)))
    load_s = time.perf_counter() - t_load
    ctx.rec.stage = "after"

    # ── counts landed, then stats ────────────────────────────────────────
    ids = [p["id"] for p in profiles]
    want_v, want_c = len(vis.views_ok), len(vis.clicks_ok)
    pv, pc = sum(v for v, _ in past.values()), sum(c for _, c in past.values())
    con = w.sql()
    q_in = ",".join("?" * len(ids))
    try:
        deadline = time.monotonic() + 8
        while True:
            tv, tc = con.execute(f"SELECT COALESCE(SUM(views),0), COALESCE(SUM(clicks),0) FROM bio_daily "
                                 f"WHERE profile_id IN ({q_in})", ids).fetchone()
            if (tv, tc) == (pv + want_v, pc + want_c) or time.monotonic() > deadline:
                break
            await asyncio.sleep(0.2)
        rows = con.execute(f"SELECT profile_id, link_id, day, SUM(views), SUM(clicks) FROM bio_daily "
                           f"WHERE profile_id IN ({q_in}) GROUP BY 1, 2, 3", ids).fetchall()
        since = (datetime.now(timezone.utc).date() - timedelta(days=29)).isoformat()
        sql_stats = {pid: (v, c) for pid, v, c in con.execute(
            "SELECT profile_id, SUM(views), SUM(clicks) FROM bio_daily WHERE day >= ? GROUP BY 1", (since,))}
    finally:
        con.close()
    got = {(pid, lid, day): (v, c) for pid, lid, day, v, c in rows}
    off = bio_visitor.count_bounds(past, vis.views_ok, vis.clicks_ok, got)
    log = ctx.out / "bio.log"
    bad_lines = bio_log_bad(log.read_text(errors="replace")) if log.exists() else ["bio.log missing"]
    orphans = sum("dropped orphan" in ln for ln in (log.read_text(errors="replace").splitlines()
                                                     if log.exists() else []))
    ctx.check(BIO_DRAIN, bool(drain) and drain["exit_s"] is not None and drain["answered"] == drain["persisted"]
              and drain["answered"][0] > 0 and not off and (tv - pv, tc - pc) == (want_v, want_c) and not bad_lines,
              drain=drain, pings_204=want_v, reveals_200=want_c, stored=(tv - pv, tc - pc), off=len(off),
              sample=dict(list(off.items())[:5]), bio_log=bad_lines[:5], orphan_drop_lines=orphans)

    r = await admin_call(owner, "GET", "", "", route=f"stats GET {ADMIN}")
    body = r.json() if r is not None and r.status_code == 200 else {}
    listed = body.get("profiles", [])
    soff = stats_off(listed, sql_stats)
    ctx.check(BIO_ADMIN_STATS, bool(listed) and len(listed) == len(profiles) and not soff and serving_before,
              listed=len(listed), seeded=len(profiles), off=dict(list(soff.items())[:5]), serving_before=serving_before)

    ctx.rec.stage = "probe"
    tenancy_bad.extend(await tenancy_check((owner, other, chatter), (b_pid, b_lid, profiles[0]["id"],
                                                            profiles[0]["links"][0]["id"]), "after"))
    ctx.check(BIO_ADMIN_TENANCY, not tenancy_bad, bad=tenancy_bad)
    expected_base = ctx.stack.relay_env[0]["BIO_PUBLIC_URL"]
    urls_bad, urls_n = await public_urls_check(owner, bio, w.rng("scenario:bio-pages-editor:urls"), expected_base)
    ctx.check(BIO_PUBLIC_URLS, urls_n["live"] > 0 and urls_n["pending"] > 0 and urls_n["fetched"] > 0 and not urls_bad,
              counts=dict(urls_n), bad=urls_bad[:10])

    # ── UI: the tab, a page made and edited in the editor (its writes fold into EDITS / ORDER / NO_5XX) ──
    if ctx.app:
        ctx.rec.stage = "ui"
        done: set = set()
        try:
            await _ui(ctx, w, owner, f"slopbioui{w.seed}", bio=bio, shows=shows,
                      order_note=lambda item: note(order_bad, item), counts=counts, done=done)
        except Exception as e:  # noqa: BLE001  a step that never came: the UI checks not yet decided fail
            for name in UI_CHECKS:
                if name not in done:
                    ctx.check(name, False, error=f"{type(e).__name__}: {e}"[:400])
    else:
        for name in UI_CHECKS:
            ctx.skip(name, "--no-ui")
    ctx.check(BIO_ADMIN_EDITS, counts["edits"] > 0 and not edits_bad, compared=counts["edits"], bad=edits_bad)
    ctx.check(BIO_ADMIN_ORDER, counts["reorders"] > 0 and counts["visitor_json"] > 0 and not order_bad,
              reorders=counts["reorders"], visitor_json=counts["visitor_json"], bad=order_bad)
    ctx.check(BIO_ADMIN_FILES, counts["files_served"] > 0 and counts["files_gone"] > 0 and not files_bad,
              served=counts["files_served"], gone_checked=counts["files_gone"], bad=files_bad)
    ctx.check(BIO_PAGE, not vis.page_bad, visits=n_visits, bad=vis.page_bad[:10])
    ctx.check(BIO_REVEAL, bool(vis.clicks_ok) and not vis.reveal_bad, reveal_ok=want_c, bad=vis.reveal_bad[:10])
    log_hits = [ln[:200] for name in ("bio.log", "relay.log") for f in (ctx.out / name,)
                for ln in (f.read_text(errors="replace").splitlines() if f.exists() else []) if "slopdest-" in ln]
    ctx.check(BIO_NO_LEAK, not vis.leaks and not log_hits, answers=vis.leaks[:10], log_lines=log_hits[:5])
    fives = sum(n for s, n in vis.status.items() if s >= 500)
    ctx.check(BIO_NO_5XX, fives == 0, count=fives, statuses=dict(vis.status))

    # ── budgets ──────────────────────────────────────────────────────────
    routes = ctx.rec.summary("load")
    budgets = [(L_LIST, LIST_P95_MS), (L_P, P_P95_MS), *((r, WRITE_P95_MS) for r in WRITES),
               *((r, UPLOAD_P95_MS) for r in UPLOADS), (L_PAGE, PAGE_P95_MS), (L_JSON, JSON_P95_MS),
               (L_PING, VISIT_WRITE_P95_MS), (L_REVEAL, VISIT_WRITE_P95_MS)]
    for route, budget in budgets:
        name = f"p95 {route} <= {budget} ms under the load"
        if route in routes:
            ctx.check(name, routes[route]["p95_ms"] <= budget, budget=True, p95=routes[route]["p95_ms"],
                      n=routes[route]["n"])
        else:
            ctx.skip(name, "no samples")
    vs_last = [r for r, _ in budgets if r in routes]
    ctx.metric("p95_vs_last_green", {r: routes[r]["p95_ms"] for r in vs_last})
    ctx.metric("p95_vs_last_green_n", {r: routes[r]["n"] for r in vs_last})
    ctx.metric("load", {"editors": n_editors, "rounds": rounds, "visits": n_visits, "clients": len(vis.clients),
                        "rate": rate, "load_s": round(load_s, 2), "profiles": len(profiles), **counts})
    await vis.aclose()
    for a in (owner, other, chatter):
        await a.aclose()
    for h in (b_http, chat_http):
        await h.aclose()
