"""Nudge online's day picker and slot images (app/components/settings/NudgeSlotPools.tsx, nudgeDayBuckets.ts,
useNudgeImageUploads.ts, lib/vaultImport.ts `importAndWait`; the relay's per-field `_pick_pool` and the preview's
`weekday`) on the real UI and the real relay routes: one owner, one browser (1440x900), `agency_inbox` (3 Creators).
A layout flow, not a volume one: `--users` and `--scale` change nothing, so no latency budget.

Seeded by SQL (product-writable rows only): Creator 0's `account_ai_config.nudge_config_json` as PUT
/admin/nudge-config stores it, `{"slots": {"default": ...}}` with one line per time (two for Evening) and the vault
image 9001 on Night; its one `vault_items` row 9001 (seed/vault_week.import_stub, as a prior import left it). Night has
ONE line on purpose: the preview picks a random line and the image at that line's index, so with one line the image is
always the pool's first and the preview check is exact.

Flow (Smart Messages > New Message > Nudge > Next; the editor's account select set to Creator 0): the Day picker's
"Sat" (screenshot nudge-day-trigger); on "Night (21–5)" one image dropped (a DragEvent with the file) and one chosen
through its Upload button (the file chooser); while both import, "Edit for Saturdays" on "Evening (18–21)" and its
first line retyped; once Save is live again, Save (screenshot nudge-day-settled). Expected:
  - DAY_UPLOAD: each file goes through the vault import, one `POST .../vault/upload/batch` each (one file per run, so
    no append), the drop's first (`importAndWait` queues the second run behind the first); both runs done; OnlyFans
    (lib/vault_relay.py) received both files' bytes (sha256);
  - DAY_SAVED: the stored row's saturday = {night: {text: [], image: [drop's id, chooser's id]}, evening: {text: the
    every-day lines with the first edited, image: []}}; default = the seeded one; no other bucket;
  - DAY_HELD: Save read "Uploading images…" and was disabled from the drop until after the second upload was sent,
    never enabled under that label (an in-page 50 ms recorder of the footer button, `save-timeline` in day-flow.json);
  - DAY_PREVIEW: POST /admin/nudge-config/preview (owner cookie) on the stored config, hour 23: weekday saturday
    answers [{text: the every-day night line, media: [drop's id]}] (lines from Every day, image Saturday's own: the
    per-field fallback), weekday monday [{same line, media: [9001]}];
  - DAY_NO_5XX: no 5xx answered to the browser.

Bypasses (declared): the drop is a DragEvent dispatched on the Night card with a DataTransfer whose File is built in the
page from the run file's bytes (no OS drag); the chooser is Playwright's file chooser (no OS dialog). OnlyFans' side of
the import is lib/vault_relay.py (its docstring: the upload claim in-process, the carrier post at OF's REST shape, the
product's own `materialize_to_vault`). Every other `/api/of/*` read stays held (ui.py), so the slot thumbnails'
by-id reads (`useVaultMediaByIds`) never answer: the slots draw the dropped files' local previews and "#9001". The
browser-side capture has each file part's name, not its bytes (Chromium's DevTools request body omits Blob parts);
the bytes are checked at OnlyFans' side. The vault spool is in the run's temp dir.

Fault (client side, `lib/nudge_day_faults.py`): `nudge-upload-lands-every-day` (a landed upload's `addImages` goes to
the every-day bucket): Saturday's night stores no images and every day's night rotates 9001 first, so DAY_SAVED and
DAY_PREVIEW go red; the upload, the held Save and the 5xx check stay green.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import subprocess
import time
from email.parser import BytesParser
from email.policy import default as email_default
from pathlib import Path
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.nudge_day_faults import DAY_HELD, DAY_NO_5XX, DAY_PREVIEW, DAY_SAVED, DAY_UPLOAD
from slop.seed import vault_week

PROFILE = "agency_inbox"
UI = True
FAULT = "nudge-upload-lands-every-day"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
CHECKS = (DAY_UPLOAD, DAY_SAVED, DAY_HELD, DAY_PREVIEW, DAY_NO_5XX)
BATCH, APPEND, STATUS = "/api/of/v2/vault/upload/batch", "/api/of/v2/vault/upload/batch/append", \
    "/api/of/v2/vault/upload/status"
CONFIG, PREVIEW = "/admin/nudge-config", "/admin/nudge-config/preview"
SEED_MEDIA = 9001  # the vault's one pre-existing row, the every-day Night image
NIGHT_LINE = "slop every-day night line"
EVENING = ["slop every-day evening one", "slop every-day evening two"]
EDITED = "slop saturday evening edited"
DEFAULT_SLOTS = {
    "morning_1": {"text": ["slop every-day morning early"], "image": []},
    "morning_2": {"text": ["slop every-day morning late"], "image": []},
    "afternoon_1": {"text": ["slop every-day afternoon early"], "image": []},
    "afternoon_2": {"text": ["slop every-day afternoon late"], "image": []},
    "evening": {"text": EVENING, "image": []},
    "night": {"text": [NIGHT_LINE], "image": [SEED_MEDIA]},
}
FILES = {  # name -> (how it reaches the slot, ffmpeg lavfi source); distinct bytes each
    "sat-night-drop.jpg": ("drop", ["-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1"]),
    "sat-night-chooser.png": ("chooser", ["-f", "lavfi", "-i", "color=c=blue:s=32x32", "-frames:v", "1"]),
}
SENT = list(FILES)  # the drop first, then the chooser
SAVE_RX = re.compile(r"^(Create automation|Save changes|Saving…|Uploading images…)$")
# In-page recorder: every change of the footer's primary button (label | disabled), with its time.
SAVE_TIMELINE_JS = """() => {
  window.__slopSave = [];
  const rx = /^(Create automation|Save changes|Saving…|Uploading images…)$/;
  window.__slopSaveIv = setInterval(() => {
    const b = [...document.querySelectorAll('[role=dialog] button')].find((x) => rx.test(x.textContent.trim()));
    if (!b) return;
    const s = b.textContent.trim() + '|' + b.disabled;
    const l = window.__slopSave;
    if (!l.length || l[l.length - 1].s !== s) l.push({ t: Date.now(), s });
  }, 50);
}"""
DROP_JS = """([el, name, type, b64]) => {
  const bin = atob(b64);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  const dt = new DataTransfer();
  dt.items.add(new File([u], name, { type }));
  for (const t of ['dragenter', 'dragover', 'drop']) {
    el.dispatchEvent(new DragEvent(t, { bubbles: true, cancelable: true, composed: true, dataTransfer: dt }));
  }
}"""


def _make_files(ctx) -> dict:
    d = ctx.stack.tmp / "media"
    d.mkdir(exist_ok=True)
    out = {}
    for name, (how, src) in FILES.items():
        p = d / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, str(p)], check=True, timeout=60)
        out[name] = {"how": how, "path": str(p), "size": p.stat().st_size,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    (ctx.out / "media-files.json").write_text(json.dumps(out, indent=2))
    return out


def _seed(w, aid: str) -> None:
    """Creator 0's nudge config (as PUT /admin/nudge-config stores it) and its vault's one row."""
    vault_week.import_stub(w, aid, SEED_MEDIA)
    con = w.sql()
    with con:
        con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents)"
                    " VALUES (?, 0, 100)", (aid,))
        con.execute("UPDATE account_ai_config SET nudge_config_json=? WHERE account_id=?",
                    (json.dumps({"slots": {"default": DEFAULT_SLOTS}}), aid))
    con.close()


def _parts(req) -> tuple[list[str], list[str]]:
    """A multipart request's (field names, file parts' names); Chromium's DevTools body omits the Blob bytes."""
    body = req.post_data_buffer or b""
    ctype = req.headers.get("content-type", "")
    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    parts = list(msg.iter_parts())
    return [p.get_param("name", header="content-disposition") for p in parts], \
        [p.get_filename() for p in parts if p.get_filename()]


def _card(dialog, label: str):
    """A time slot's editor card: the parent of its label."""
    return dialog.get_by_text(label, exact=True).locator("xpath=..")


async def _stored(ctx, aid: str) -> dict:
    con = ctx.world.sql()
    row = con.execute("SELECT nudge_config_json FROM account_ai_config WHERE account_id=?", (aid,)).fetchone()
    con.close()
    return json.loads(row[0]) if row and row[0] else {}


async def _flow(ctx, page, chk, files: dict, aid: str) -> None:
    sent: list[dict] = []
    batch_resps: list = []

    def on_request(req):
        p = urlsplit(req.url).path
        if req.method == "POST" and p in (BATCH, APPEND):
            fields, names = _parts(req)
            sent.append({"t": time.time() * 1000, "path": p, "account": req.headers.get("x-account-id"),
                         "files": names, "fields": fields})

    def on_response(resp):
        if resp.request.method == "POST" and urlsplit(resp.url).path == BATCH:
            batch_resps.append(resp)

    page.on("request", on_request)
    page.on("response", on_response)
    await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded")
    await page.get_by_role("button", name="New Message").first.click(timeout=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r"^Nudge")).first.click(timeout=30_000)
    await page.get_by_role("button", name="Next", exact=True).click(timeout=10_000)
    dialog = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Nudge online", exact=True))
    await dialog.locator("select").filter(has=page.locator(f'option[value="{aid}"]')).first.select_option(
        aid, timeout=WAIT_MS)
    night = _card(dialog, "Night (21–5)")
    evening = _card(dialog, "Evening (18–21)")
    # Hydrated with the seeded config: Every day's Night line is in its field.
    await page.wait_for_function("(el) => el && el.value === " + json.dumps(NIGHT_LINE),
                                 arg=await night.get_by_placeholder("e.g. hey {name}").first.element_handle(
                                     timeout=WAIT_MS), timeout=WAIT_MS)
    save = dialog.get_by_role("button", name=SAVE_RX).first
    await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=WAIT_MS)

    sat = dialog.get_by_role("radiogroup", name="Day").get_by_role("radio", name="Sat", exact=True)
    await sat.click(timeout=10_000)
    await page.wait_for_function("(b) => b.getAttribute('aria-checked') === 'true'", arg=await sat.element_handle(),
                                 timeout=10_000)
    inherited_note = await evening.get_by_text(re.compile(r"^Uses Every day")).first.inner_text(timeout=10_000)
    await sat.scroll_into_view_if_needed()
    await ui.shot(ctx, page, "nudge-day-trigger")

    await page.evaluate(SAVE_TIMELINE_JS)
    await night.scroll_into_view_if_needed()
    drop_name, chooser_name = SENT
    drop_t = await page.evaluate("Date.now()")
    data = base64.b64encode(Path(files[drop_name]["path"]).read_bytes()).decode()
    await page.evaluate(DROP_JS, [await night.element_handle(), drop_name, "image/jpeg", data])
    async with page.expect_file_chooser(timeout=10_000) as fc:
        await night.get_by_role("button", name="Upload images").click(timeout=10_000)
    await (await fc.value).set_files(files[chooser_name]["path"])

    # While both import: Evening's lines made Saturday's own, the first retyped.
    await evening.get_by_role("button", name="Edit for Saturdays").click(timeout=10_000)
    first = evening.get_by_placeholder("e.g. hey {name}").first
    await first.fill(EDITED)

    for _ in range(1200):  # up to 10 min: each run is a carrier of two paced OF writes (~11 s apart), run after run
        if len(sent) >= 2 and await save.is_enabled() \
                and not re.match(r"^(Uploading|Saving)", await save.inner_text()):
            break
        await asyncio.sleep(0.5)
    async with page.expect_response(lambda r: r.request.method == "PUT" and urlsplit(r.url).path == CONFIG,
                                    timeout=30_000) as put:
        await save.click(timeout=10_000)
    put_status = (await put.value).status
    await page.wait_for_function("(b) => !/^Saving/.test(b.textContent.trim())", arg=await save.element_handle(),
                                 timeout=30_000)
    timeline = await page.evaluate("clearInterval(window.__slopSaveIv), window.__slopSave")
    await night.scroll_into_view_if_needed()
    await page.wait_for_timeout(500)
    await ui.shot(ctx, page, "nudge-day-settled")

    # The relay's runs, by the ids the batch route answered (in send order).
    run_ids = []
    for r in batch_resps:
        try:
            run_ids.append((await r.json()).get("run_id"))
        except Exception:  # noqa: BLE001 — no JSON body: no run
            run_ids.append(None)
    runs = []
    for rid in run_ids:
        q = await ctx.owner.get(f"{STATUS}?run_id={rid}", headers={"X-Account-Id": aid}) if rid else None
        runs.append(q.json() if q is not None and q.status_code == 200 else {})
    (ctx.out / "relay-runs.json").write_text(json.dumps(runs, indent=2))
    (ctx.out / "requests.json").write_text(json.dumps(sent, indent=2))
    ids = [((r.get("items") or [{}])[0]).get("vault_id") for r in runs]

    # 1. through the vault import
    fake = (await ctx.owner.get("/__slop/vault/fake")).json()
    (ctx.out / "of-fake.json").write_text(json.dumps(fake, indent=2))
    shape = [(r["path"], r["account"], r["files"], "keep_open" in r["fields"]) for r in sent]
    items = [[(i.get("name"), i.get("status")) for i in r.get("items") or []] for r in runs]
    got = [(c["name"], c["sha256"]) for c in fake["claims"]]
    want = [(n, files[n]["sha256"]) for n in SENT]
    chk(DAY_UPLOAD, shape == [(BATCH, aid, [n], False) for n in SENT]
        and items == [[(n, "done")] for n in SENT] and [r.get("status") for r in runs] == ["done", "done"]
        and sorted(got) == sorted(want) and all(isinstance(i, int) for i in ids),
        requests=shape, run_ids=run_ids, run_items=items, run_status=[r.get("status") for r in runs],
        claims=got, want_claims=want, vault_ids=ids)

    # 2. the stored config
    cfg = await _stored(ctx, aid)
    (ctx.out / "db-nudge-config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    slots = cfg.get("slots") or {}
    want_sat = {"night": {"text": [], "image": ids}, "evening": {"text": [EDITED, *EVENING[1:]], "image": []}}
    chk(DAY_SAVED, put_status == 200 and slots.get("saturday") == want_sat and slots.get("default") == DEFAULT_SLOTS
        and sorted(slots) == ["default", "saturday"], put=put_status, saturday=slots.get("saturday"),
        want_saturday=want_sat, default_unchanged=slots.get("default") == DEFAULT_SLOTS, buckets=sorted(slots),
        inherited_note=inherited_note)

    # 3. Save held while the uploads ran
    up = [i for i, e in enumerate(timeline) if e["s"].startswith("Uploading images…")]
    second_sent = sent[1]["t"] if len(sent) > 1 else None
    up_end = next((e["t"] for e in timeline[up[-1] + 1:]), None) if up else None
    chk(DAY_HELD, bool(up) and timeline[up[0]]["t"] >= drop_t
        and all(timeline[i]["s"] == "Uploading images…|true" for i in up)
        and second_sent is not None and up_end is not None and up_end > second_sent,
        drop_t=drop_t, second_upload_sent_t=second_sent, uploading_ended_t=up_end, save_timeline=timeline)

    # 4. the preview, by day, on the stored config
    pv = {}
    for day in ("saturday", "monday"):
        r = await ctx.owner.post(PREVIEW, json={"account_id": aid, "config": cfg, "hour": 23, "weekday": day})
        pv[day] = {"status": r.status_code, **(r.json() if r.status_code == 200 else {"body": r.text[:300]})}
    (ctx.out / "preview.json").write_text(json.dumps(pv, indent=2, ensure_ascii=False))
    msgs = {d: [{"text": m.get("text"), "media": m.get("media")} for m in v.get("messages") or []]
            for d, v in pv.items()}
    want_pv = {"saturday": [{"text": NIGHT_LINE, "media": ids[:1]}], "monday": [{"text": NIGHT_LINE,
                                                                               "media": [SEED_MEDIA]}]}
    chk(DAY_PREVIEW, msgs == want_pv and all(v.get("slot") == "night" for v in pv.values()), got=msgs,
        want=want_pv, slots=[v.get("slot") for v in pv.values()], statuses=[v["status"] for v in pv.values()])

    # 5. no 5xx
    bad = [[s, u] for s, u in page.slop["statuses"] if s >= 500][:10]
    chk(DAY_NO_5XX, not bad, five_xx=bad, responses=len(page.slop["statuses"]))
    (ctx.out / "day-flow.json").write_text(json.dumps(
        {"vault_ids": ids, "save-timeline": timeline, "drop_t": drop_t, "put": put_status}, indent=2))


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creator = w.data["creators"][0]
    _seed(w, creator["id"])
    (ctx.stack.tmp / "of-vault.json").write_text("{}")
    if ctx.app is None:
        for c in CHECKS:
            ctx.skip(c, "--no-ui")
        return
    files = _make_files(ctx)
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(BATCH, APPEND, STATUS)) as page:
        done: set[str] = set()

        def chk(name: str, ok: bool, **detail) -> None:
            done.add(name)
            ctx.check(name, ok, **detail)

        try:
            await _flow(ctx, page, chk, files, creator["id"])
        except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its checks' FAIL
            try:
                await ui.shot(ctx, page, "failed-nudge-day")
            except Exception:  # noqa: BLE001
                pass
            for c in CHECKS:
                if c not in done:
                    ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:600])
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
