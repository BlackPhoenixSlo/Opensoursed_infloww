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
from slop.lib.vault_ui import TOURS_SEEN, open_vault_picker, open_vault_pro, captured
from slop.lib.vault_faults import DB_ROWS, OF_BYTES, PROTOCOL, RUN_ITEMS, SENT_FILES, SETTLED_UI
from slop.seed.vault_cache import LISTS_KEY, cache_row, grant_folder_access
from slop.seed import chatters, vault_week

PROFILE = "agency_inbox"
UI = True
FAULT = "import-sends-unselected"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
CHECKS = (SENT_FILES, PROTOCOL, RUN_ITEMS, OF_BYTES, DB_ROWS, SETTLED_UI)
BATCH, APPEND, STATUS = "/api/of/v2/vault/upload/batch", "/api/of/v2/vault/upload/batch/append", \
    "/api/of/v2/vault/upload/status"
ROW_BOXES = "input[type=checkbox][aria-label^='Select ']:not([aria-label='Select all media'])"
SEED_MEDIA = 9001
FILES = {
    "a.jpg": ["-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1"],
    "b.png": ["-f", "lavfi", "-i", "color=c=green:s=32x32", "-frames:v", "1"],
    "c.mp4": ["-f", "lavfi", "-i", "testsrc=s=64x64:d=1:r=10", "-pix_fmt", "yuv420p", "-c:v", "libx264"],
    "d.jpg": ["-f", "lavfi", "-i", "color=c=blue:s=32x32", "-frames:v", "1"],
}
EDITS = {
    "a.jpg": {"Hashtags": "#slopa, beach", "Suggested price": "12.50"},
    "b.png": {"Notes": "b is deselected"},
    "c.mp4": {"Notes": "clip c notes"},
    "d.jpg": {"Notes": "d is removed"},
}
SENT = ["a.jpg", "c.mp4"]
WANT_META = {"a.jpg": {"hashtags": ["slopa", "beach"], "price_cents": 1250}, "c.mp4": {"notes": "clip c notes"}}
PICKER_TS = Path(__file__).resolve().parents[1] / "lib" / "picker_ts.mjs"
LISTS = "/api/of/v2/vault/lists"
LISTS_PAGE = 50
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


async def _restricted_picker(ctx, w, creator: dict) -> None:
    aid = creator["id"]
    body = {"list": [{"id": fid, "type": "custom", "name": name, "hasMedia": bool(p + v), "canUpdate": True,
                      "canDelete": True, "photosCount": p, "videosCount": v, "gifsCount": 0, "audiosCount": 0,
                      "medias": []} for fid, name, p, v in PICKER_FOLDERS], "hasMore": False}
    rec = (await chatters.seed(w, ctx.owner, w.user_id, ["pickerchatter"], account_ids=[[aid]]))[0]
    con = w.sql()
    with con:
        cache_row(con, aid, LISTS_KEY, body, w.now, replace=True)
        grant_folder_access(con, rec["chatter_id"], aid, ALLOWED[0], ALLOWED[1], w.now)
    con.close()
    http = Http(str(ctx.owner.c.base_url), ctx.rec)
    shown = None
    try:
        login = await http.post("/chatter/login", json={"username": rec["username"], "password": rec["password"]})
        access = await http.get(f"/chatter/me/folder-access?account_id={aid}")
        lists, statuses, offset = [], [], 0
        for _ in range(20):
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
    ui_ok = shown is None or shown.get("options") == [[str(ALLOWED[0]), ALLOWED[1]]]
    ctx.check(RESTRICTED_MENU, login.status_code == 200 and access.status_code == 200 and set(statuses) == {200}
              and out["restricted"] and [i["id"] for i in items] == [ALLOWED[0]]
              and all(i["name"] == ALLOWED[1] and i["label"] == ALLOWED[1] for i in items) and ui_ok,
              login=login.status_code, access_status=access.status_code, lists_statuses=statuses,
              restricted=out["restricted"], menu=items, want=[{"id": ALLOWED[0], "name": ALLOWED[1]}],
              absent=others, lists_ids=[l.get("id") for l in lists], ui=shown)


async def _restricted_picker_ui(ctx, w, http, aid: str) -> dict:
    fans = [t["fan_id"] for t in w.data.get("threads", []) if t["account_id"] == aid] or \
        [f["id"] for f in w.data["fans"][aid]]
    got: dict = {"fan": fans[0]}
    async with ui.chatter_tab(ctx, http, ctx.app, viewport=VIEWPORT) as page:
        async def lists_through(route):
            await route.continue_()  # page routes run before the context's hold

        await page.route(lambda u: urlsplit(u).path == LISTS, lists_through)
        async with captured(ctx, page, got, "failed-restricted-picker"):
            dialog = await open_vault_picker(page, ctx, aid, fans[0], timeout=WAIT_MS)
            for _ in range(300):
                seen = [s for s, u in page.slop["statuses"] if urlsplit(u).path in (LISTS, "/chatter/me/folder-access")]
                if len(seen) >= 2:
                    break
                await asyncio.sleep(0.1)
            await page.wait_for_timeout(1000)
            got["trigger_shot"] = await ui.shot(ctx, page, "restricted-picker-trigger")
            menu = dialog.locator("select[title='Filter by folder']")
            got["options"] = []
            if await menu.count():
                await menu.click(timeout=10_000)
                got["options"] = await menu.evaluate(
                    "s => [...s.options].map(o => [o.value, o.textContent.trim()])")
                # Headless Chromium draws no native <select> popup: size = option count renders the list in place.
                await menu.evaluate("s => { s.size = Math.max(2, s.options.length); s.focus(); }")
                await page.wait_for_timeout(300)
            got["menu_shot"] = await ui.shot(ctx, page, "restricted-picker-menu")
            got["reads"] = [[s, urlsplit(u).path] for s, u in page.slop["statuses"]
                            if urlsplit(u).path in (LISTS, "/chatter/me/folder-access")]
    return got


def _parts(req) -> dict:
    body = req.post_data_buffer or b""
    ctype = req.headers.get("content-type", "")
    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    out: dict = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True) or b""
        fn = part.get_filename()
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
    await open_vault_pro(page, ctx)
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

    names = [f["filename"] for r in sent for f in r["fields"].get("files", [])]
    metas = {f["filename"]: m for r in sent for f, m in zip(r["fields"].get("files", []),
                                                            json.loads((r["fields"].get("meta") or ["[]"])[0]))}
    chk(SENT_FILES, names == SENT and metas == WANT_META, sent=names, want=SENT, metas=metas,
        want_metas=WANT_META, listed_before_start=listed_before)
    shape = [(r["path"], r["fields"].get("keep_open"), r["fields"].get("last"), r["account"]) for r in sent]
    chk(PROTOCOL, shape == [(BATCH, ["1"], None, creator["id"]), (APPEND, None, ["1"], creator["id"])]
        and all(r["fields"].get("run_id", [run_id])[0] == run_id for r in sent[1:]), requests=shape, run_id=run_id)

    items = [(i.get("name"), i.get("status")) for i in status.get("items") or []]
    chk(RUN_ITEMS, items == [(n, "done") for n in SENT] and status.get("status") == "done"
        and (status.get("details_saved") or {}).get("applied") == len(SENT), items=items,
        run_status=status.get("status"), details_saved=status.get("details_saved"))

    fake = (await ctx.owner.get("/__slop/vault/fake")).json()
    (ctx.out / "of-fake.json").write_text(json.dumps(fake, indent=2))
    got = [(c["name"], c["sha256"]) for c in fake["claims"]]
    want = [(n, files[n]["sha256"]) for n in SENT]
    remuxed = [n for n, _ in got if n not in files]
    chk(OF_BYTES, sorted(got) == sorted(want) and all(c["deleted"] for c in fake["carriers"]), claims=got,
        want=want, remuxed=remuxed, carriers=[(c["post_id"], c["media_ids"], c["deleted"]) for c in fake["carriers"]])

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
    vault_week.import_stub(w, creator["id"], SEED_MEDIA)
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
