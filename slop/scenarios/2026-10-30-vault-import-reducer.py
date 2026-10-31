"""Vault import's pick list (app/components/vault/importPickReducer.ts) on the real UI and the real relay
route: one owner, one browser (1440x900), `agency_inbox` (3 Creators), Creator 0's vault mirror seeded by
SQL (one `vault_items` row, as a collect leaves it, so the import's details have a mirror to land on).
A layout flow, not a volume one: `--users` and `--scale` change nothing, so no latency budget.

Vault Pro > Add media: pick 4 tiny files (a.jpg, b.png, c.mp4, d.jpg, made by ffmpeg in the run's temp
dir); Hashtags + price on a.jpg, Notes on b.png, c.mp4 and d.jpg; deselect b.png; Delete d.jpg; then
Start import. Expected (VaultImportCard: only `chosenOf` is sent, each file with its own `details`;
each file leaves the list once the relay has it):
  - the browser sends a.jpg in `POST .../vault/upload/batch` (keep_open=1) and c.mp4 in one
    `POST .../batch/append` (last=1), each with its own meta, nothing for b.png or d.jpg;
  - the relay's run (`GET .../upload/status?run_id=`) lists exactly a.jpg + c.mp4, both done;
  - OnlyFans (lib/vault_relay.py) received exactly those two files' bytes (sha256);
  - their `vault_items` rows carry the typed hashtags, price and notes; no row for b or d;
  - the card settles with b.png still listed, unchecked, and the run summary "2 in vault".
Screenshots import-trigger (the list just before Start) and import-settled.

Bypasses (declared): the browser-side capture (requests.json) has each file part's name, not its bytes
(Chromium's DevTools request body omits Blob parts); the bytes are checked at OnlyFans' side. OnlyFans' side of the import is lib/vault_relay.py (its docstring: the upload claim
in-process, the carrier post at OF's REST shape, the product's own `materialize_to_vault`). Every other
`/api/of/*` read stays held (ui.py), so the folder picker is empty. Vault Pro's onboarding tours are
marked seen in localStorage (a returning owner). The vault spool is in the run's temp dir.

Fault (client side, `lib/vault_faults.py`): `import-sends-unselected` (`chosenOf` returns every picked
file, the selection ignored): the deselected b.png is sent too, so every check of the flow goes red.

Restricted chatter's picker folder menu (also `--no-ui`): one chatter (seed/chatters: invite + register, Creator 1
only) holds one `chatter_folder_access` row (as PUT /admin/chatters/{id}/folder-access writes it) to 1 of Creator
1's 3 OnlyFans folders, the one OF lists empty (hasMedia false: emptied on OF since the grant, a case the picker
keeps by design). Signed in with its own cookie (POST /chatter/login), it reads GET /chatter/me/folder-access and
every GET /api/of/v2/vault/lists page (fetchAllVaultLists' walk, limit 50); both answers go to the app's own
`components/chat/vaultPickerFolders.ts` `folderSelectItems` in node (lib/app_ts.py + lib/picker_ts.mjs). Check: the
menu is exactly the allowed folder, named as granted (`picker-folders.json`); with UI, also the chatter's real
picker in Chromium (a Creator 1 Fan's chat, the composer's Vault button, the folder menu's options read from the DOM;
screenshots restricted-picker-trigger, restricted-picker-menu; `_restricted_picker_ui` declares its bypasses).
The relay already filters vault/lists to
the allowed set (server.of_vault_lists), so the 2 others' absence is recorded as evidence (`absent`), not a pass
condition of its own; the menu's own allowlist is what keeps a granted folder the lists leave out. Bypasses (declared): Creator 1's OF folder list is the relay's own cache row
(`vault_response_cache`, as vault_cache.put stores OF's answer), seeded by SQL (the relay never reaches OnlyFans; the
import's upload invalidates Creator 0's rows only); the lists page walk and useVaultLists' select are copies
(Python here, lib/picker_ts.mjs), the hook being React. Fault (client side, `lib/picker_faults.py`):
`picker-ignores-folder-access` (the restricted branch off: the menu is OF's lists) turns that check red only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from email.parser import BytesParser
from email.policy import default as email_default
from pathlib import Path
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib import app_ts
from slop.lib.client import Http
from slop.lib.picker_faults import RESTRICTED_MENU
from slop.lib.vault_faults import DB_ROWS, OF_BYTES, PROTOCOL, RUN_ITEMS, SENT_FILES, SETTLED_UI
from slop.seed import chatters, ts

PROFILE = "agency_inbox"
UI = True
FAULT = "import-sends-unselected"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
CHECKS = (SENT_FILES, PROTOCOL, RUN_ITEMS, OF_BYTES, DB_ROWS, SETTLED_UI)
BATCH, APPEND, STATUS = "/api/of/v2/vault/upload/batch", "/api/of/v2/vault/upload/batch/append", \
    "/api/of/v2/vault/upload/status"
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")
ROW_BOXES = "input[type=checkbox][aria-label^='Select ']:not([aria-label='Select all media'])"
SEED_MEDIA = 9001  # the mirror's one pre-existing row
FILES = {  # name -> ffmpeg lavfi source (distinct bytes each)
    "a.jpg": ["-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1"],
    "b.png": ["-f", "lavfi", "-i", "color=c=green:s=32x32", "-frames:v", "1"],
    "c.mp4": ["-f", "lavfi", "-i", "testsrc=s=64x64:d=1:r=10", "-pix_fmt", "yuv420p", "-c:v", "libx264"],
    "d.jpg": ["-f", "lavfi", "-i", "color=c=blue:s=32x32", "-frames:v", "1"],
}
EDITS = {  # name -> {column header: typed value}
    "a.jpg": {"Hashtags": "#slopa, beach", "Suggested price": "12.50"},
    "b.png": {"Notes": "b is deselected"},
    "c.mp4": {"Notes": "clip c notes"},
    "d.jpg": {"Notes": "d is removed"},
}
SENT = ["a.jpg", "c.mp4"]
WANT_META = {"a.jpg": {"hashtags": ["slopa", "beach"], "price_cents": 1250}, "c.mp4": {"notes": "clip c notes"}}
PICKER_TS = Path(__file__).resolve().parents[1] / "lib" / "picker_ts.mjs"
LISTS = "/api/of/v2/vault/lists"
LISTS_PAGE = 50  # fetchAllVaultLists' page
LISTS_KEY = f"lists:view=main|limit={LISTS_PAGE}|offset=0"  # server.vault_lists_cache_key of its first page
# Creator 1's OF folders: (id, name, photos, videos); the granted one is empty on OF (hasMedia false).
PICKER_FOLDERS = ((7101, "Slop picker customs", 0, 0), (7102, "Slop picker teasers", 4, 1),
                  (7103, "Slop picker vip", 2, 3))
ALLOWED = PICKER_FOLDERS[0]


def _make_files(ctx) -> dict:
    d = ctx.stack.tmp / "media"
    d.mkdir(exist_ok=True)
    out = {}
    for name, src in FILES.items():
        p = d / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, str(p)], check=True, timeout=60)
        out[name] = {"path": str(p), "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    (ctx.out / "media-files.json").write_text(json.dumps(out, indent=2))
    return out


def _seed_mirror(w, aid: str) -> None:
    con = w.sql()
    with con:
        con.execute("INSERT INTO vault_items (account_id, media_id, kind, tags, send_count, created_at, updated_at)"
                    " VALUES (?, ?, 'photo', '[]', 0, ?, ?)", (aid, SEED_MEDIA, ts(w.now), ts(w.now)))
    con.close()


async def _restricted_picker(ctx, w, creator: dict) -> None:
    """A folder-restricted chatter's picker folder menu (module docstring), also --no-ui."""
    aid = creator["id"]
    body = {"list": [{"id": fid, "type": "custom", "name": name, "hasMedia": bool(p + v), "canUpdate": True,
                      "canDelete": True, "photosCount": p, "videosCount": v, "gifsCount": 0, "audiosCount": 0,
                      "medias": []} for fid, name, p, v in PICKER_FOLDERS], "hasMore": False}
    rec = (await chatters.seed(w, ctx.owner, w.user_id, ["pickerchatter"], account_ids=[[aid]]))[0]
    con = w.sql()
    with con:
        con.execute("INSERT OR REPLACE INTO vault_response_cache (account_id, query_key, response_json, fetched_at)"
                    " VALUES (?, ?, ?, ?)", (aid, LISTS_KEY, json.dumps(body), ts(w.now)))
        con.execute("INSERT INTO chatter_folder_access (chatter_id, account_id, folder_id, folder_name, created_at)"
                    " VALUES (?, ?, ?, ?, ?)", (rec["chatter_id"], aid, ALLOWED[0], ALLOWED[1], ts(w.now)))
    con.close()
    http = Http(str(ctx.owner.c.base_url), ctx.rec)
    shown = None
    try:
        login = await http.post("/chatter/login", json={"username": rec["username"], "password": rec["password"]})
        access = await http.get(f"/chatter/me/folder-access?account_id={aid}")
        lists, statuses, offset = [], [], 0
        for _ in range(20):  # fetchAllVaultLists' walk
            r = await http.get(f"{LISTS}?view=main&limit={LISTS_PAGE}&offset={offset}", headers={"X-Account-Id": aid})
            statuses.append(r.status_code)
            page = r.json() if r.status_code == 200 else {}
            rows = page.get("list") or []
            lists += rows
            if not page.get("hasMore") or not rows:
                break
            offset += LISTS_PAGE
        if ctx.app is not None:
            shown = await _restricted_picker_ui(ctx, w, http, aid)
    finally:
        await http.aclose()
    acc = access.json() if access.status_code == 200 else {}
    out = await app_ts.run(ctx, PICKER_TS, {"access": acc, "lists": lists})
    (ctx.out / "picker-folders.json").write_text(json.dumps(
        {"access": acc, "lists": lists, "menu": out, "of_folders": body["list"], "ui": shown}, indent=2,
        ensure_ascii=False))
    items = out["items"]
    others = [f[0] for f in PICKER_FOLDERS if f is not ALLOWED]
    # With UI: the chatter's real picker shows exactly that menu (option value = folder id, text = label).
    ui_ok = shown is None or shown.get("options") == [[str(ALLOWED[0]), ALLOWED[1]]]
    ctx.check(RESTRICTED_MENU, login.status_code == 200 and access.status_code == 200 and set(statuses) == {200}
              and out["restricted"] and [i["id"] for i in items] == [ALLOWED[0]]
              and all(i["name"] == ALLOWED[1] and i["label"] == ALLOWED[1] for i in items) and ui_ok,
              login=login.status_code, access_status=access.status_code, lists_statuses=statuses,
              restricted=out["restricted"], menu=items, want=[{"id": ALLOWED[0], "name": ALLOWED[1]}],
              absent=others, lists_ids=[l.get("id") for l in lists], ui=shown)


async def _restricted_picker_ui(ctx, w, http, aid: str) -> dict:
    """The restricted chatter in Chromium (its own login cookie): a Creator 1 Fan's chat (deep link), the
    composer's Vault button (screenshot restricted-picker-trigger), the folder menu clicked open and its options
    read from the DOM (screenshot restricted-picker-menu). Bypass (declared): headless Chromium draws no native
    <select> popup, so for the end shot the opened select is given `size` = its option count (rendered as a
    list in place); the options are the app's own. GET vault/lists is let through (the relay answers it from
    its cache row); every other /api/of/ read stays held. Returns {fan, options: [[value, text]], ...} or
    {error}: a step that cannot complete is the check's FAIL."""
    fans = [t["fan_id"] for t in w.data.get("threads", []) if t["account_id"] == aid] or \
        [f["id"] for f in w.data["fans"][aid]]
    got: dict = {"fan": fans[0]}
    async with ui.chatter_tab(ctx, http, ctx.app, viewport=VIEWPORT) as page:
        async def lists_through(route):
            await route.continue_()  # page routes run before the context's hold

        await page.route(lambda u: urlsplit(u).path == LISTS, lists_through)
        try:
            await page.goto(f"{ctx.app}/messages-pro/{aid}/{fans[0]}", wait_until="domcontentloaded",
                            timeout=WAIT_MS)
            vault = page.get_by_role("button", name="Vault", exact=True).first
            await vault.wait_for(timeout=WAIT_MS)
            await vault.click(timeout=WAIT_MS)
            dialog = page.get_by_role("dialog", name="Vault picker")
            await dialog.wait_for(timeout=60_000)
            for _ in range(300):  # settled: both the access and the lists reads answered
                seen = [s for s, u in page.slop["statuses"] if urlsplit(u).path in (LISTS, "/chatter/me/folder-access")]
                if len(seen) >= 2:
                    break
                await asyncio.sleep(0.1)
            await page.wait_for_timeout(1000)
            got["trigger_shot"] = await ui.shot(ctx, page, "restricted-picker-trigger")
            menu = dialog.locator("select[title='Filter by folder']")
            got["options"] = []  # no folder menu rendered: no items
            if await menu.count():
                await menu.click(timeout=10_000)
                got["options"] = await menu.evaluate(
                    "s => [...s.options].map(o => [o.value, o.textContent.trim()])")
                await menu.evaluate("s => { s.size = Math.max(2, s.options.length); s.focus(); }")
                await page.wait_for_timeout(300)
            got["menu_shot"] = await ui.shot(ctx, page, "restricted-picker-menu")
            got["reads"] = [[s, urlsplit(u).path] for s, u in page.slop["statuses"]
                            if urlsplit(u).path in (LISTS, "/chatter/me/folder-access")]
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["error"] = f"{type(e).__name__}: {e}"[:600]
            try:
                await ui.shot(ctx, page, "failed-restricted-picker")
            except Exception:  # noqa: BLE001
                pass
    return got


def _parts(req) -> dict:
    """A multipart request's fields: {name: [value | {"filename", "size", "sha256"}]}."""
    body = req.post_data_buffer or b""
    ctype = req.headers.get("content-type", "")
    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    out: dict = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True) or b""
        fn = part.get_filename()
        # A file part's bytes: Chromium's DevTools request body leaves Blob parts out (measured: 0 bytes), so
        # only its name is kept here; the bytes are checked where they land (lib/vault_relay.py's claims).
        val = {"filename": fn} if fn else data.decode("utf-8", "replace")
        out.setdefault(name, []).append(val)
    return out


async def _flow(ctx, page, chk, files: dict, creator: dict) -> None:
    sent: list[dict] = []

    def on_request(req):
        p = urlsplit(req.url).path
        if req.method == "POST" and p in (BATCH, APPEND):
            sent.append({"path": p, "account": req.headers.get("x-account-id"), "fields": _parts(req)})

    page.on("request", on_request)
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded")
    await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r"Add media")).first.click(timeout=WAIT_MS)
    picker = page.locator("input[type=file][accept^='image/']")
    await picker.set_input_files([files[n]["path"] for n in FILES])
    for name in FILES:
        await page.get_by_label(f"Select {name}", exact=True).wait_for(timeout=30_000)
    for name, edits in EDITS.items():
        for header, value in edits.items():
            await page.get_by_label(f"{header} for {name}", exact=True).fill(value)
    await page.get_by_label("Select b.png", exact=True).uncheck()
    await page.get_by_label("Delete d.jpg", exact=True).click()
    await page.get_by_label("Select d.jpg", exact=True).wait_for(state="detached", timeout=10_000)
    start = page.get_by_role("button", name=re.compile(r"^Start import"))
    await start.scroll_into_view_if_needed()
    await ui.shot(ctx, page, "import-trigger")
    listed_before = [await r.get_attribute("aria-label") for r in await page.locator(ROW_BOXES).all()]
    await start.click(timeout=10_000)

    # The relay's run, by the id the batch route answered.
    run_id = None
    for _ in range(600):  # up to 5 min: each carrier is two paced OF writes (~11 s apart)
        await asyncio.sleep(0.5)
        if not sent:
            continue
        q = await ctx.owner.get(STATUS, headers={"X-Account-Id": creator["id"]})
        st = q.json() if q.status_code == 200 else {}
        run_id = st.get("run_id")
        if run_id and not st.get("running") and st.get("status") in ("done", "failed", "interrupted"):
            break
    status = (await ctx.owner.get(f"{STATUS}?run_id={run_id}", headers={"X-Account-Id": creator["id"]})).json() \
        if run_id else {}
    (ctx.out / "relay-run-status.json").write_text(json.dumps(status, indent=2))
    await page.get_by_text(re.compile(r"^\d+ in vault")).first.wait_for(timeout=60_000)
    await page.wait_for_timeout(1000)
    await ui.shot(ctx, page, "import-settled")
    (ctx.out / "requests.json").write_text(json.dumps(sent, indent=2))

    # 1. what the browser sent
    names = [f["filename"] for r in sent for f in r["fields"].get("files", [])]
    metas = {f["filename"]: m for r in sent for f, m in zip(r["fields"].get("files", []),
                                                            json.loads((r["fields"].get("meta") or ["[]"])[0]))}
    chk(SENT_FILES, names == SENT and metas == WANT_META, sent=names, want=SENT, metas=metas,
        want_metas=WANT_META, listed_before_start=listed_before)
    shape = [(r["path"], r["fields"].get("keep_open"), r["fields"].get("last"), r["account"]) for r in sent]
    chk(PROTOCOL, shape == [(BATCH, ["1"], None, creator["id"]), (APPEND, None, ["1"], creator["id"])]
        and all(r["fields"].get("run_id", [run_id])[0] == run_id for r in sent[1:]), requests=shape, run_id=run_id)

    # 2. the relay's run
    items = [(i.get("name"), i.get("status")) for i in status.get("items") or []]
    chk(RUN_ITEMS, items == [(n, "done") for n in SENT] and status.get("status") == "done"
        and (status.get("details_saved") or {}).get("applied") == len(SENT), items=items,
        run_status=status.get("status"), details_saved=status.get("details_saved"))

    # 3. OnlyFans' side
    fake = (await ctx.owner.get("/__slop/vault/fake")).json()
    (ctx.out / "of-fake.json").write_text(json.dumps(fake, indent=2))
    got = [(c["name"], c["sha256"]) for c in fake["claims"]]
    want = [(n, files[n]["sha256"]) for n in SENT]
    remuxed = [n for n, _ in got if n not in files]
    chk(OF_BYTES, sorted(got) == sorted(want) and all(c["deleted"] for c in fake["carriers"]), claims=got,
        want=want, remuxed=remuxed, carriers=[(c["post_id"], c["media_ids"], c["deleted"]) for c in fake["carriers"]])

    # 4. the mirror rows
    con = ctx.world.sql()
    rows = con.execute("SELECT media_id, kind, tags, notes, suggested_price_cents FROM vault_items "
                       "WHERE account_id=? ORDER BY media_id", (creator["id"],)).fetchall()
    con.close()
    by_vid = {int(v): m for v, m in fake["minted"].items()}
    db = [{"media_id": r[0], "file": (by_vid.get(r[0]) or {}).get("name"), "kind": r[1], "tags": json.loads(r[2]),
           "notes": r[3], "price_cents": r[4]} for r in rows]
    (ctx.out / "db-vault-items.json").write_text(json.dumps(db, indent=2))
    new = {d["file"]: {k: d[k] for k in ("tags", "notes", "price_cents")} for d in db if d["media_id"] != SEED_MEDIA}
    want_rows = {"a.jpg": {"tags": ["slopa", "beach"], "notes": None, "price_cents": 1250},
                 "c.mp4": {"tags": [], "notes": "clip c notes", "price_cents": None}}
    chk(DB_ROWS, new == want_rows, rows=new, want=want_rows)

    # 5. the card after the run
    left = [await r.get_attribute("aria-label") for r in await page.locator(ROW_BOXES).all()]
    b_box = page.get_by_label("Select b.png", exact=True)
    b_checked = await b_box.is_checked() if await b_box.count() else None
    b_notes = await page.get_by_label("Notes for b.png", exact=True).input_value() \
        if await page.get_by_label("Notes for b.png", exact=True).count() else None
    summary = await page.get_by_text(re.compile(r"^\d+ in vault")).first.inner_text()
    chk(SETTLED_UI, left == ["Select b.png"] and b_checked is False and b_notes == "b is deselected"
        and summary.startswith("2 in vault"), listed=left, b_checked=b_checked, b_notes=b_notes, summary=summary)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creator = w.data["creators"][0]
    _seed_mirror(w, creator["id"])
    (ctx.stack.tmp / "of-vault.json").write_text("{}")
    await _restricted_picker(ctx, w, w.data["creators"][1])
    if ctx.app is None:
        for c in CHECKS:
            ctx.skip(c, "--no-ui")
        return
    files = _make_files(ctx)
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(BATCH, APPEND, STATUS)) as page:
        await page.context.add_init_script(TOURS_SEEN)
        done: set[str] = set()

        def chk(name: str, ok: bool, **detail) -> None:
            done.add(name)
            ctx.check(name, ok, **detail)

        try:
            await _flow(ctx, page, chk, files, creator)
        except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its checks' FAIL
            try:
                await ui.shot(ctx, page, "failed-import")
            except Exception:  # noqa: BLE001
                pass
            for c in CHECKS:
                if c not in done:
                    ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:600])
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
