"""Manage employees (/employees, the sidebar's Employees > Manage employees) on the real UI after the 2026-10-30
refactor: the five row/header modals as one `openModal` value, `buildEmployeeRequest` picking the save call per
sign-in mode, and the Access limits draft as a reducer seeded once. One owner, one browser (1440x900),
`agency_inbox` (3 Creators), the relay's own routes on the slop temp DB. A flow, not a volume one: `--users` and
`--scale` change nothing, so no latency budget.

Seeded through the real routes: two Employee groups (`POST /admin/employee-groups`), one login of this Agency
(`seed/chatters`: invite + register) and one login of a second Agency (registered through `POST /auth/register`,
its login through the same seeder), for "Existing login". By SQL: Creator 0's cached OnlyFans folder list (one
`vault_response_cache` row, as `GET /api/of/v2/vault/lists` writes it after an OnlyFans fetch: two custom folders).

1. Modals: "+ Add employee", the row's Edit, its role cell (Set role), More > Reset password, More > Access limits:
   each open shows exactly one dialog with its title, its close leaves none. Then Set role open + a click on the
   row's Edit (a DOM click: the backdrop covers the row) leaves one dialog, Edit employee. Screenshots
   modal-<kind>-trigger / modal-<kind>-open, modal-replace-open.
2. Add in each sign-in mode: Create login (role VA, group 1, Creator 1 only), Existing login (the other Agency's
   login, role Manager, group 2), Invite link (role VA, group 1; the link is shown). Each POST's path and body
   keys checked on the wire; GET /admin/employees, GET /admin/settings/roles and GET /admin/chatters/invites
   show the rows. Screenshots add-<mode>-trigger / add-<mode>-settled.
3. Edit the seeded login: name, role Manager, group 2, one PUT .../setup; the API shows them. Screenshots
   edit-trigger, edit-settled.
4. Access limits on the edited login: Limit models on, Creator 0 and 1 ticked, 1 unticked again, Creator 0's
   folder limit on with the first folder, Save access -> "Saved." (and still after the save's refetch); GET
   /admin/chatters/{id}/access: account_ids [Creator 0], folder_access {Creator 0: [first folder]}. Then Creator 2
   ticked, Save, and while its account-access PUT is held the second folder ticked: once the save's access refetch
   lands the draft keeps both edits and shows no "Saved." (the folder edit is not stored yet); the next Save
   stores them. Then a partial save: Creator 2 and the second folder unticked, Save, the account-access PUT lands and
   the first folder-access PUT is refused (400): the line says "Accounts saved; folders failed — <error>", no
   "Saved.", the access and the employee list are refetched, and GET …/access holds [Creator 0] with the folders it
   held before (the folder half did not land). Screenshots access-trigger, access-saved, access-edit-during-save,
   access-after-refetch, access-resaved, access-partial-trigger, access-partial-settled.
5. No 5xx on any response the browser got.

A UI step that cannot complete is FAIL for each check of its section not yet recorded, with a `failed-<section>`
picture. API side effects are written to `employees-api.json`, the browser's employee writes to `writes.json`.

Bypasses (declared): Creator 0's folder list comes from the relay's own cache row, seeded by SQL (the relay never
reaches OnlyFans); `/api/of/v2/vault/lists` is let through to the relay for that, every other `/api/of/*` read stays
held (actors/ui.py). The access-refetch check holds one account-access PUT at the browser's wire until the second
edit is typed (an owner typing while a slow save is in flight), then lets it through unchanged. The partial-save
check answers one folder-access PUT 400 at the browser's wire (the relay never sees it; a 4xx so the no-5xx check
keeps its meaning). The page is opened by URL, not through the sidebar.

Fault (client side, lib/employees_faults.py): `employee-access-drops-folders` (buildPayload sends `folders: []` in every
folder-access PUT): only the two stored checks go red, "Saved." and the draft checks stay green.
`--fault=employee-access-saved-beside-unsaved-edit` (saveOk's rev guard reverted): only the no-stale-"Saved." check.
`--fault=employee-access-partial-not-invalidated` (a save with a failed folders half refetches nothing, as before
the fix): only the partial-save check.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

from slop.actors import ui
from slop.lib.employees_faults import (EMP_ACCESS_PARTIAL, EMP_ACCESS_REFETCH, EMP_ACCESS_RESAVED,
                                       EMP_ACCESS_SAVED, EMP_ACCESS_SAVED_STALE, EMP_ACCESS_STORED,
                                       EMP_ADD_INVITE, EMP_ADD_LINK, EMP_ADD_LOGIN, EMP_EDIT, EMP_MODAL_REPLACE,
                                       EMP_MODALS_ONE, EMP_NO_5XX)
from slop.seed import chatters, ts

PROFILE = "agency_inbox"
UI = True
FAULT = "employee-access-drops-folders"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
ANIM_MS = 450  # the modal pop-in / exit ghost (globals.css .pop-modal, useExitGhost 260 ms)

SECTIONS = {
    "modals": (EMP_MODALS_ONE, EMP_MODAL_REPLACE),
    "add-login": (EMP_ADD_LOGIN,),
    "add-link": (EMP_ADD_LINK,),
    "add-invite": (EMP_ADD_INVITE,),
    "edit": (EMP_EDIT,),
    "access": (EMP_ACCESS_SAVED, EMP_ACCESS_STORED, EMP_ACCESS_REFETCH, EMP_ACCESS_SAVED_STALE, EMP_ACCESS_RESAVED,
               EMP_ACCESS_PARTIAL),
}
GROUPS = ("Slop night shift", "Slop day shift")
FOLDERS = ((501, "Slop VIP folder"), (502, "Slop teaser folder"))
REFUSED = "slop: folder write refused"
LISTS_KEY = "lists:view=main|limit=50|offset=0"  # server.vault_lists_cache_key for fetchAllVaultLists' first page
EDITED_NAME = "Slop Edited Emp"
WRITE_PATHS = re.compile(r"/admin/(employees(/\d+/setup|/login)?|chatters/(link|invite|[0-9a-f]+/(account|folder)-access))")

VISIBLE_DIALOGS = """() => [...document.querySelectorAll('[role=dialog]')].filter((d) => {
  const r = d.getBoundingClientRect(); const cs = getComputedStyle(d);
  return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
}).map((d) => { const id = d.getAttribute('aria-labelledby');
  return ((id && document.getElementById(id)) ? document.getElementById(id).textContent : d.getAttribute('aria-label')) || ''; })"""


def _seed_folders(w, aid: str) -> None:
    """Creator 0's folder list as the relay caches OnlyFans' answer (vault_cache.put)."""
    body = {"list": [{"id": fid, "type": "custom", "name": name, "hasMedia": True, "canUpdate": True,
                      "canDelete": True, "photosCount": 3, "videosCount": 0, "gifsCount": 0, "audiosCount": 0,
                      "medias": []} for fid, name in FOLDERS], "hasMore": False}
    con = w.sql()
    with con:
        con.execute("INSERT INTO vault_response_cache (account_id, query_key, response_json, fetched_at)"
                    " VALUES (?, ?, ?, ?)", (aid, LISTS_KEY, json.dumps(body), ts(w.now)))
    con.close()


async def _section(ctx, page, name: str, fn) -> None:
    """Run one section; a step that cannot complete fails every check of it not yet recorded."""
    done: set[str] = set()

    def chk(check_name: str, ok: bool, **detail) -> None:
        done.add(check_name)
        ctx.check(check_name, ok, **detail)

    try:
        await fn(chk)
    except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its checks' FAIL
        try:
            await ui.shot(ctx, page, f"failed-{name}")
        except Exception:  # noqa: BLE001
            pass
        for c in SECTIONS[name]:
            if c not in done:
                ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:600], section=name)


async def _dialogs(page) -> list[str]:
    return await page.evaluate(VISIBLE_DIALOGS)


async def _settle_dialogs(page, want: list[str], timeout_s: float = 5.0) -> list[str]:
    """The visible dialogs once they are `want` (or what they are after the timeout), then the pop / exit
    animation's time, so a screenshot after it shows the settled screen."""
    t_end = asyncio.get_event_loop().time() + timeout_s
    got = await _dialogs(page)
    while got != want and asyncio.get_event_loop().time() < t_end:
        await asyncio.sleep(0.1)
        got = await _dialogs(page)
    await page.wait_for_timeout(ANIM_MS)
    return got


def _row(page, name: str):
    return page.locator(f'tr[data-employee="{name}"]')


async def _menu(page, row, item: str):
    """The row's More menu opened, `item` (a menuitem in the portal) ready to click."""
    await row.get_by_role("button", name="More", exact=True).click(timeout=10_000)
    mi = page.get_by_role("menuitem", name=item, exact=True)
    await mi.wait_for(timeout=10_000)
    return mi


async def _api_employees(ctx) -> list[dict]:
    r = await ctx.owner.get("/admin/employees")
    r.raise_for_status()
    return r.json()["employees"]


async def _api_roles(ctx) -> dict:
    r = await ctx.owner.get("/admin/settings/roles")
    r.raise_for_status()
    return (r.json().get("config") or {}).get("assignments") or {}


async def _api_access(ctx, cid: str) -> dict:
    r = await ctx.owner.get(f"/admin/chatters/{cid}/access")
    r.raise_for_status()
    return r.json()


def _api_log(ctx, key: str, value) -> None:
    path = ctx.out / "employees-api.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2, default=str))


# ── 1. modals ────────────────────────────────────────────────────────────────

async def _modals(ctx, page, chk, s) -> None:
    row = _row(page, s["emp"]["username"])
    cases = []
    triggers = (
        ("add", "Add employee", lambda: page.get_by_role("button", name="+ Add employee", exact=True)),
        ("edit", "Edit employee", lambda: row.get_by_role("button", name="Edit", exact=True)),
        ("role", "Set role", lambda: row.locator('button[title^="Set role"]')),
        ("password", "Reset password", None),
        ("access", "Access limits", None),
    )
    for kind, title, trigger in triggers:
        btn = trigger() if trigger else await _menu(page, row, title)
        await btn.wait_for(timeout=WAIT_MS)
        await ui.shot(ctx, page, f"modal-{kind}-trigger")
        await btn.click(timeout=10_000)
        await page.get_by_role("dialog", name=title).wait_for(timeout=30_000)
        if kind == "access":
            await page.get_by_role("dialog", name=title).get_by_role("button", name="Save access").wait_for(
                timeout=WAIT_MS)
        opened = await _settle_dialogs(page, [title])
        await ui.shot(ctx, page, f"modal-{kind}-open")
        await page.get_by_role("dialog", name=title).get_by_role("button", name="Close", exact=True).click()
        closed = await _settle_dialogs(page, [])
        cases.append({"modal": kind, "open": opened, "after_close": closed})
    chk(EMP_MODALS_ONE, all(c["open"] == [t] and c["after_close"] == [] for c, (_, t, _x) in zip(cases, triggers)),
        cases=cases)

    await row.locator('button[title^="Set role"]').click(timeout=10_000)
    await page.get_by_role("dialog", name="Set role").wait_for(timeout=30_000)
    before = await _settle_dialogs(page, ["Set role"])
    await row.get_by_role("button", name="Edit", exact=True).evaluate("(b) => b.click()")
    await page.get_by_role("dialog", name="Edit employee").wait_for(timeout=30_000)
    after = await _settle_dialogs(page, ["Edit employee"])
    await ui.shot(ctx, page, "modal-replace-open")
    await page.get_by_role("dialog", name="Edit employee").get_by_role("button", name="Close", exact=True).click()
    closed = await _settle_dialogs(page, [])
    chk(EMP_MODAL_REPLACE, before == ["Set role"] and after == ["Edit employee"] and closed == [],
        role_open=before, after_edit_click=after, after_close=closed)


# ── 2. add, one per sign-in mode ─────────────────────────────────────────────

async def _fill_add(page, s, mode: str, name: str, role: str, group: str, username: str = "",
                    password: str = "", creators: list[str] | None = None):
    await page.get_by_role("button", name="+ Add employee", exact=True).click(timeout=10_000)
    dlg = page.get_by_role("dialog", name="Add employee")
    await dlg.wait_for(timeout=30_000)
    await dlg.get_by_role("radio", name=mode, exact=True).click()
    await dlg.locator("#emp-name").fill(name)
    if username:
        await dlg.locator("#emp-username").fill(username)
    if password:
        await dlg.locator("#emp-password").fill(password)
    await dlg.locator("#emp-role").select_option(label=role)
    await dlg.locator("#emp-group").select_option(label=group)
    if creators is not None:
        await dlg.get_by_label("All creators", exact=True).uncheck()
        for nick in creators:
            await dlg.get_by_label(nick, exact=True).check()
    return dlg


def _writes_to(s, path: str) -> list[dict]:
    return [w for w in s["writes"] if w["path"] == path]


async def _add_login(ctx, page, chk, s) -> None:
    username, c1 = f"{s['prefix']}login", s["creators"][1]
    dlg = await _fill_add(page, s, "Create login", "Slop Login Emp", "VA", GROUPS[0], username=username,
                          password="slop-login-pw", creators=[c1["nickname"]])
    await ui.shot(ctx, page, "add-login-trigger")
    async with page.expect_response(lambda r: urlsplit(r.url).path == "/admin/employees/login", timeout=30_000) as rr:
        await dlg.get_by_role("button", name="Add employee", exact=True).click()
    status = (await rr.value).status
    closed = await _settle_dialogs(page, [])
    await _row(page, "Slop Login Emp").wait_for(timeout=30_000)
    await ui.shot(ctx, page, "add-login-settled")
    emps, roles = await _api_employees(ctx), await _api_roles(ctx)
    e = next((x for x in emps if x.get("username") == username), None)
    got = e and {"display_name": e["display_name"], "group_id": e["group_id"], "account_ids": e["account_ids"],
                 "role": roles.get(str(e["id"])), "is_active": e["is_active"]}
    want = {"display_name": "Slop Login Emp", "group_id": s["groups"][GROUPS[0]], "account_ids": [c1["id"]],
            "role": "va", "is_active": True}
    wire = _writes_to(s, "/admin/employees/login")
    body = wire[0]["body"] if wire else {}
    _api_log(ctx, "add_login", got)
    chk(EMP_ADD_LOGIN, status == 200 and closed == [] and got == want and len(wire) == 1
        and wire[0]["method"] == "POST" and body.get("username") == username and body.get("password") == "slop-login-pw"
        and body.get("account_ids") == [c1["id"]], http=status, dialogs_after=closed, api=got, want=want,
        wire=[{**w, "body": {k: v for k, v in (w["body"] or {}).items() if k != "password"}} for w in wire])


async def _add_link(ctx, page, chk, s) -> None:
    username = s["ext"]["username"]
    dlg = await _fill_add(page, s, "Existing login", "Slop Linked Emp", "Manager", GROUPS[1], username=username)
    await ui.shot(ctx, page, "add-link-trigger")
    async with page.expect_response(lambda r: urlsplit(r.url).path == "/admin/chatters/link", timeout=30_000) as rr:
        await dlg.get_by_role("button", name="Add employee", exact=True).click()
    status = (await rr.value).status
    closed = await _settle_dialogs(page, [])
    emps, roles = await _api_employees(ctx), await _api_roles(ctx)
    e = next((x for x in emps if x.get("username") == username), None)
    if e:
        await _row(page, e["display_name"]).wait_for(timeout=30_000)
    await ui.shot(ctx, page, "add-link-settled")
    got = e and {"display_name": e["display_name"], "group_id": e["group_id"], "account_ids": e["account_ids"],
                 "role": roles.get(str(e["id"])), "is_active": e["is_active"]}
    want = {"display_name": "Slop Linked Emp", "group_id": s["groups"][GROUPS[1]], "account_ids": None,
            "role": "manager", "is_active": True}
    wire = _writes_to(s, "/admin/chatters/link")
    body = wire[0]["body"] if wire else {}
    _api_log(ctx, "add_link", got)
    chk(EMP_ADD_LINK, status == 200 and closed == [] and got == want and len(wire) == 1
        and body.get("username") == username and "password" not in body, http=status, dialogs_after=closed,
        api=got, want=want, wire=wire)


async def _add_invite(ctx, page, chk, s) -> None:
    dlg = await _fill_add(page, s, "Invite link", "Slop Invited Emp", "VA", GROUPS[0])
    await ui.shot(ctx, page, "add-invite-trigger")
    async with page.expect_response(lambda r: urlsplit(r.url).path == "/admin/chatters/invite", timeout=30_000) as rr:
        await dlg.get_by_role("button", name="Create invite link", exact=True).click()
    status = (await rr.value).status
    link = dlg.get_by_label("Invite link", exact=True)
    await link.wait_for(timeout=30_000)
    url = await link.input_value()
    shown = await _dialogs(page)
    await ui.shot(ctx, page, "add-invite-settled")
    token = (parse_qs(urlsplit(url).query).get("token") or [""])[0]
    await dlg.get_by_role("button", name="Done", exact=True).click()
    closed = await _settle_dialogs(page, [])
    r = await ctx.owner.get("/admin/chatters/invites")
    r.raise_for_status()
    inv = next((i for i in r.json() if i["token"] == token), None)
    got = inv and {"display_name": inv["display_name"], "group_id": inv["group_id"], "role_id": inv["role_id"],
                   "account_ids": inv["account_ids"]}
    want = {"display_name": "Slop Invited Emp", "group_id": s["groups"][GROUPS[0]], "role_id": "va", "account_ids": None}
    row_shown = await page.locator('tr[data-invite="Slop Invited Emp"]').count()
    wire = _writes_to(s, "/admin/chatters/invite")
    body = wire[0]["body"] if wire else {}
    _api_log(ctx, "add_invite", {"link": url, **(got or {})})
    chk(EMP_ADD_INVITE, status == 200 and shown == ["Add employee"] and "/chatter-login?token=" in url and bool(token)
        and got == want and closed == [] and row_shown == 1 and len(wire) == 1
        and "username" not in body and "password" not in body,
        http=status, link=url, dialogs_while_link_shown=shown, api=got, want=want, invite_row=row_shown, wire=wire)


# ── 3. edit ──────────────────────────────────────────────────────────────────

async def _edit(ctx, page, chk, s) -> None:
    emp = s["emp"]
    await _row(page, emp["username"]).get_by_role("button", name="Edit", exact=True).click(timeout=10_000)
    dlg = page.get_by_role("dialog", name="Edit employee")
    await dlg.wait_for(timeout=30_000)
    await dlg.locator("#emp-name").fill(EDITED_NAME)
    await dlg.locator("#emp-role").select_option(label="Manager")
    await dlg.locator("#emp-group").select_option(label=GROUPS[1])
    await ui.shot(ctx, page, "edit-trigger")
    path = f"/admin/employees/{emp['employee_id']}/setup"
    async with page.expect_response(lambda r: urlsplit(r.url).path == path, timeout=30_000) as rr:
        await dlg.get_by_role("button", name="Save", exact=True).click()
    status = (await rr.value).status
    closed = await _settle_dialogs(page, [])
    await _row(page, EDITED_NAME).wait_for(timeout=30_000)
    await ui.shot(ctx, page, "edit-settled")
    emps, roles = await _api_employees(ctx), await _api_roles(ctx)
    e = next((x for x in emps if x["id"] == emp["employee_id"]), None)
    got = e and {"display_name": e["display_name"], "group_id": e["group_id"], "role": roles.get(str(e["id"]))}
    want = {"display_name": EDITED_NAME, "group_id": s["groups"][GROUPS[1]], "role": "manager"}
    wire = _writes_to(s, path)
    _api_log(ctx, "edit", {"before": s["emp_before"], "after": got})
    chk(EMP_EDIT, status == 200 and closed == [] and got == want and s["emp_before"] != got and len(wire) == 1
        and wire[0]["method"] == "PUT", http=status, before=s["emp_before"], api=got, want=want, wire=wire)


# ── 4. access limits ─────────────────────────────────────────────────────────

async def _access(ctx, page, chk, s) -> None:
    cid = s["emp"]["chatter_id"]
    c0, c1, c2 = s["creators"][:3]
    acc_path = f"/admin/chatters/{cid}/access"
    is_refetch = lambda r: r.request.method == "GET" and urlsplit(r.url).path == acc_path  # noqa: E731
    mi = await _menu(page, _row(page, EDITED_NAME), "Access limits")
    await mi.click()
    dlg = page.get_by_role("dialog", name="Access limits")
    save = dlg.get_by_role("button", name="Save access")
    await save.wait_for(timeout=WAIT_MS)
    await dlg.get_by_label("Limit which models this employee sees").check()
    box = lambda c: dlg.get_by_label(c["nickname"], exact=True)  # noqa: E731
    await box(c0).check()
    await box(c1).check()
    await box(c1).uncheck()
    await dlg.get_by_label(re.compile(rf"^{re.escape(c0['nickname'])}\s*—\s*limit folders$")).check()
    folder = lambda i: dlg.get_by_label(FOLDERS[i][1], exact=True)  # noqa: E731
    await folder(0).check(timeout=30_000)
    await ui.shot(ctx, page, "access-trigger")
    saved = dlg.get_by_text("Saved.", exact=True)
    async with page.expect_response(is_refetch, timeout=30_000) as ref:
        await save.click()
    await ref.value
    await saved.wait_for(timeout=10_000)
    await page.wait_for_timeout(800)
    saved_after = await saved.count()
    await ui.shot(ctx, page, "access-saved")
    chk(EMP_ACCESS_SAVED, saved_after == 1, saved_shown_after_refetch=saved_after)
    got = await _api_access(ctx, cid)
    want = {"account_ids": [c0["id"]], "folder_access": {c0["id"]: [FOLDERS[0][0]]}}
    _api_log(ctx, "access_first_save", got)
    chk(EMP_ACCESS_STORED, got == want, api=got, want=want)

    # A refetch must not reseed the draft: Creator 2 ticked, Save held at the wire, folder 2 ticked meanwhile.
    hold = {"on": True, "seen": asyncio.Event(), "release": asyncio.Event()}

    async def put(route):
        if route.request.method == "PUT" and hold["on"]:
            hold["on"] = False
            hold["seen"].set()
            await hold["release"].wait()
        await route.fallback()

    put_path = f"/admin/chatters/{cid}/account-access"
    await page.route(lambda u: urlsplit(u).path == put_path, put)
    await box(c2).check()
    await save.click()
    await asyncio.wait_for(hold["seen"].wait(), 15)
    await folder(1).check()
    await ui.shot(ctx, page, "access-edit-during-save")
    async with page.expect_response(is_refetch, timeout=30_000) as ref:
        hold["release"].set()
    await ref.value
    await page.wait_for_timeout(1000)
    shown = {"c0": await box(c0).is_checked(), "c1": await box(c1).is_checked(), "c2": await box(c2).is_checked(),
             "folder1": await folder(0).is_checked(), "folder2": await folder(1).is_checked()}
    saved_with_unsaved_edit = await saved.count()
    await ui.shot(ctx, page, "access-after-refetch")
    chk(EMP_ACCESS_REFETCH, shown == {"c0": True, "c1": False, "c2": True, "folder1": True, "folder2": True},
        shown=shown)
    chk(EMP_ACCESS_SAVED_STALE, saved_with_unsaved_edit == 0, saved_shown_beside_unsaved_edit=saved_with_unsaved_edit)
    await page.unroute(lambda u: urlsplit(u).path == put_path)

    async with page.expect_response(is_refetch, timeout=30_000) as ref:
        await save.click()
    await ref.value
    await saved.wait_for(timeout=10_000)
    await ui.shot(ctx, page, "access-resaved")
    got = await _api_access(ctx, cid)
    got = {"account_ids": sorted(got["account_ids"]),
           "folder_access": {k: sorted(v) for k, v in got["folder_access"].items()}}
    want = {"account_ids": sorted([c0["id"], c2["id"]]), "folder_access": {c0["id"]: [FOLDERS[0][0], FOLDERS[1][0]]}}
    _api_log(ctx, "access_second_save", got)
    chk(EMP_ACCESS_RESAVED, got == want, api=got, want=want)

    # A partial save: account-access lands, the first folder-access PUT is refused at the browser's wire.
    folder_path = f"/admin/chatters/{cid}/folder-access"
    refused: list[str] = []
    refetched: list[str] = []

    async def refuse(route):
        if route.request.method == "PUT" and not refused:
            refused.append(route.request.url)
            return await route.fulfill(status=400, content_type="application/json",
                                       body=json.dumps({"detail": REFUSED}))
        await route.fallback()

    # Only the save's settle refetches the editor's access GET (no poll, no SSE key covers it), so that GET after the
    # refused PUT is the check's teeth. /admin/employees alone would not be: the account-access PUT's
    # `assignment_changed` event can refetch it too (useAccountStateEvents; not seen within the window, measured).
    def on_get(req) -> None:
        p = urlsplit(req.url).path
        if refused and req.method == "GET" and p in (acc_path, "/admin/employees"):
            refetched.append(p)

    def norm(a: dict) -> dict:
        return {"account_ids": sorted(a["account_ids"]),
                "folder_access": {k: sorted(v) for k, v in a["folder_access"].items()}}

    folders_before = norm(await _api_access(ctx, cid))["folder_access"]
    is_folder = lambda u: urlsplit(u).path == folder_path  # noqa: E731
    await page.route(is_folder, refuse)
    await box(c2).uncheck()
    await folder(1).uncheck()
    await ui.shot(ctx, page, "access-partial-trigger")
    page.on("request", on_get)
    try:
        await save.click()
        alert = dlg.get_by_role("alert").filter(has_text="folders failed")
        await alert.wait_for(timeout=15_000)
        await page.wait_for_timeout(1500)  # the refetches the settle fires
        line = await alert.inner_text()
        saved_n = await saved.count()
        await ui.shot(ctx, page, "access-partial-settled")
    finally:
        page.remove_listener("request", on_get)
        await page.unroute(is_folder)
    got = norm(await _api_access(ctx, cid))
    want = {"account_ids": [c0["id"]], "folder_access": folders_before}  # the folder half did not land
    _api_log(ctx, "access_partial_save", {"line": line, "refetched": refetched, "api": got})
    chk(EMP_ACCESS_PARTIAL, line == f"Accounts saved; folders failed — {REFUSED}" and saved_n == 0
        and len(refused) == 1 and acc_path in refetched and "/admin/employees" in refetched and got == want,
        line=line, saved_shown=saved_n, refused_puts=len(refused), refetched=refetched, api=got, want=want)


# ── run ──────────────────────────────────────────────────────────────────────

async def _seed(ctx, w) -> dict:
    from slop.lib.client import Http
    groups = {}
    for name in GROUPS:  # the real route, as the group tree's "Add group" does
        r = await ctx.owner.post("/admin/employee-groups", json={"name": name})
        r.raise_for_status()
        groups[name] = r.json()["id"]
    prefix = f"{w.user_prefix}{w.seed}e"
    emp = (await chatters.seed(w, ctx.owner, w.user_id, [f"{prefix}emp"]))[0]
    # Another Agency and its login: what "Existing login" links.
    other = Http(ctx.relay, ctx.rec)
    try:
        r = await other.post("/auth/register", json={"username": f"{w.user_prefix}{w.seed}r2",
                                                     "password": "slop-throwaway-password"})
        r.raise_for_status()
        ext = (await chatters.seed(w, other, "other-agency", [f"{prefix}ext"]))[0]
    finally:
        await other.aclose()
    _seed_folders(w, w.data["creators"][0]["id"])
    emps, roles = await _api_employees(ctx), await _api_roles(ctx)
    row = next(e for e in emps if e.get("username") == emp["username"])
    emp.update(employee_id=row["id"], chatter_id=row["chatter_id"])
    before = {"display_name": row["display_name"], "group_id": row["group_id"], "role": roles.get(str(row["id"]))}
    return {"groups": groups, "emp": emp, "ext": ext, "prefix": prefix, "creators": w.data["creators"],
            "emp_before": before, "writes": []}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    s = await _seed(ctx, w)
    if ctx.app is None:
        for checks in SECTIONS.values():
            for c in checks:
                ctx.skip(c, "--no-ui")
        ctx.skip(EMP_NO_5XX, "--no-ui")
        return

    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=("/api/of/v2/vault/lists",)) as page:
        def on_request(req) -> None:
            p = urlsplit(req.url).path
            if req.method in ("POST", "PUT") and WRITE_PATHS.fullmatch(p):
                try:
                    body = req.post_data_json
                except Exception:  # noqa: BLE001
                    body = req.post_data
                s["writes"].append({"method": req.method, "path": p, "body": body})

        page.on("request", on_request)
        await page.goto(f"{ctx.app}/employees", wait_until="domcontentloaded")
        await _row(page, s["emp"]["username"]).wait_for(timeout=WAIT_MS)
        for name, fn in (("modals", _modals), ("add-login", _add_login), ("add-link", _add_link),
                         ("add-invite", _add_invite), ("edit", _edit), ("access", _access)):
            await _section(ctx, page, name, lambda chk, fn=fn: fn(ctx, page, chk, s))
        bad = [(st, u) for st, u in page.slop["statuses"] if st >= 500]
        ctx.check(EMP_NO_5XX, not bad, responses=len(page.slop["statuses"]), five_xx=bad[:20])
        (ctx.out / "writes.json").write_text(json.dumps(
            [{**x, "body": {k: v for k, v in x["body"].items() if k != "password"} if isinstance(x["body"], dict)
              else x["body"]} for x in s["writes"]], indent=2))
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
