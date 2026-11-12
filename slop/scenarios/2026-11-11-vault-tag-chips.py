"""Vault Pro's tag chips, "Save as folder" and the saved row's Publish (app/components/vault/VaultTagChips.tsx,
tagFolderForm.ts; service/vault_tags.py, GET /admin/vault-ai/tag-facets, the items listing's `tags`, POST
/admin/vault-ai/folders/from-tags, POST /admin/vault-ai/folders/{id}/publish): tap "feet" then "lace", the grid
narrows to items carrying both (AND, any of the three tag sources), "Save as folder" makes a local operator folder
holding exactly those items, the row "Saved locally · <name> · N items" stays, its Publish asks (stating N items)
and sends exactly those items to one new OnlyFans vault list.

World: `agency_inbox`; Creator 0's vault by SQL (seed/vault_tag_chips.py, `vault_tag_items` 80 / 2,000 / 12,000):
photos planted per class so "feet" AND "lace" has an exact oracle: tags in the column, in ai_fields_json.tags only
(mixed case, padded), split across both, via ai primary_folder, beside malformed ai JSON; decoys (feet_only,
lace_only, feet_soles / laced substrings), removed items. Each item's 300px thumb is a small PNG in the run's still
store, so the grid draws pictures. OnlyFans' list side is lib/vault_relay.py (`of-vault.json` written).

Stages:
  api   (also --no-ui) by the owner: GET /tag-facets (unfiltered, and with both chips); the items listing with
        tags=feet&tags=lace walked to the end; 10 timed reads of each for the p95 metric.
  desktop (UI) 1440x900: Vault Pro, pick Creator 0, tap "feet" then "lace"; once the grid shows only matches,
        screenshot `vault-tag-chips-trigger`; Save as folder (name left at its default), Save; the saved row shows,
        screenshot `vault-tag-chips-settled`; Publish: the confirm (`vault-tag-chips-publish-confirm`), "Publish N
        items"; the row says "Published to OnlyFans", screenshot `vault-tag-chips-published`.
  phone (UI) 390x844 touch: Vault Pro on Creator 0 (last pick, localStorage), the same taps; screenshot
        `vault-tag-chips-phone-trigger`; Save as folder, Save; the saved row, screenshot
        `vault-tag-chips-phone-settled`; Publish opens the confirm (`vault-tag-chips-phone-confirm`), Cancel (one
        publish per run: the desktop's).
  --no-ui: POST /folders/from-tags {tags: feet, lace}, then POST /folders/{id}/publish, instead of the UI.

Checks (lib/vault_tag_chips_faults.py names):
  tag_facets_counts               unfiltered facets == the seeder's oracle (per live item its tags from all three
                                  sources, lowercased, count desc then name); total == live items.
  tag_filter_and_three_sources    the items walk with both chips == the match set exactly, newest first (no decoy,
                                  removed or one-tag item); facets with both chips: total == |match|, feet == lace ==
                                  |match|.
  tag_chips_desktop               the chip row shows "feet" with the oracle's count; after two taps both chips are
                                  pressed and lead the row; every grid tile is a match; Save as folder shown.
  tag_chips_phone_fit             phone: the same taps work; the chip row, Save as folder, the form's Save, the saved
                                  row and its Publish, and the confirm's Publish lie inside the 390px viewport; the
                                  page never scrolls sideways.
  tag_folder_saved_from_ui        one POST from-tags per device, 200, body tags [feet, lace] and the default name,
                                  of_folder_id null; the Save button read "Save <|match|> items"; the saved row reads
                                  "Saved locally · <name> · <|match|> items", names "feet + lace" then "feet + lace 2".
  tag_folder_published            the confirm states "<|match|> items"; one POST publish (desktop's folder), 200,
                                  after the confirm; OnlyFans got one new list named "feet + lace" holding exactly
                                  the match set; the DB folder's of_list_id == that list; the row says "Published to
                                  OnlyFans · <|match|> items"; the phone's Cancel sent nothing.
  tag_folder_members_exact        DB: each saved folder (created_by 'operator', live) holds exactly the match set.
  tag_chips_no_5xx                no 5xx answered to either browser.

Bypasses (declared): the vault is SQL as Collect + describe leave it (no OF, no LLM); thumbs written by the harness
into the run's temp still store; OnlyFans' vault list calls (create list, add media, list read-back) are
lib/vault_relay.py's in-process OF client, not OF's HTTP; the background collector off (VAULT_COLLECT_ENABLED=0).
The 5,000-item cap (400 `too_many_items`) is covered by service/tests/test_vault_tag_chips.py, not here (no scale
reaches it). No volume gate: --scale only resizes the vault (huge = 12k, the per-Creator target).
Break-it-once: tag-filter-ignores-ai-tags (default; server: the filter skips ai_fields_json.tags): the filter, saved,
published and folder-membership checks go red; facets (unfiltered) and the chip-row checks stay green.
"""
from __future__ import annotations

import json
import math
import re
import time

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import picture_bytes
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_tag_chips_faults import (
    CHIPS_DESK, CHIPS_PHONE, FACETS, FILTER, MEMBERS, NO_5XX, PUBLISHED, SAVED,
)
from slop.lib.vault_ui import TOURS_SEEN
from slop.seed import vault_tag_chips

PROFILE = "agency_inbox"
UI = True
FAULT = "tag-filter-ignores-ai-tags"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
VIEWPORT, PHONE = (1440, 900), (390, 844)
WAIT_MS = 120_000
FACETS_PATH, ITEMS_PATH, SAVE_PATH = "/admin/vault-ai/tag-facets", "/admin/vault-ai/items", "/admin/vault-ai/folders/from-tags"
PUBLISH_PATH = re.compile(r"^/admin/vault-ai/folders/\d+/publish$")
TAGS = list(vault_tag_chips.TAGS)
NAMES = ("feet + lace", "feet + lace 2")   # desktop, then phone (unique_name)
SAVE_N = re.compile(r"^Save (\d+) items?$")
PUBLISH_N = re.compile(r"^Publish (\d+) items?$")
TIMED = 10

# Every grid tile's media id (VaultMediaGrid's `title="#<id> ..."`).
_TILE_IDS = "() => [...document.querySelectorAll(\"section [title^='#']\")].map(e => e.getAttribute('title').slice(1).split(' ')[0])"
_GRID_ONLY = """(ids) => { const ok = new Set(ids);
  const ts = [...document.querySelectorAll("section [title^='#']")].map(e => e.getAttribute('title').slice(1).split(' ')[0]);
  return ts.length > 0 && ts.every(t => ok.has(t)); }"""


def _chip(group, tag: str):
    return group.get_by_role("button", name=re.compile(rf"^{re.escape(tag)}\s*\d+$"))


async def _press(loc, touch: bool) -> None:
    await (loc.tap if touch else loc.click)(timeout=10_000)


async def _taps(page, match: list[int], got: dict, *, touch: bool) -> None:
    """The chip row: reads "feet"'s count, taps feet then lace, waits until the grid shows only matches."""
    group = page.get_by_role("group", name="Tags")
    feet = _chip(group, TAGS[0])
    await feet.first.wait_for(timeout=WAIT_MS)
    got["feet_count"] = int(await feet.first.locator("span").inner_text())
    for t in TAGS:
        chip = _chip(group, t).first
        await chip.wait_for(timeout=WAIT_MS)
        await _press(chip, touch)
        await group.locator("button[aria-pressed='true']", has_text=t).wait_for(timeout=WAIT_MS)
    pressed = group.locator("button[aria-pressed='true']")
    got["pressed"] = [re.sub(r"\d+$", "", s).strip() for s in await pressed.all_inner_texts()]
    got["row"] = [re.sub(r"\s*\d+$", "", s).strip() for s in await group.locator("button[aria-pressed]").all_inner_texts()]
    await page.wait_for_function(_GRID_ONLY, arg=[str(m) for m in match], timeout=WAIT_MS)
    await page.wait_for_timeout(800)   # thumbs drawn
    got["tiles"] = await page.evaluate(_TILE_IDS)
    save = page.get_by_role("button", name="Save as folder", exact=True)
    got["save_visible"] = await save.is_visible()
    got["row_box"] = await group.bounding_box()
    got["save_box"] = await save.bounding_box()


async def _save(page, got: dict, *, touch: bool):
    """Save as folder: default name, Save; waits for the saved row and returns it."""
    await _press(page.get_by_role("button", name="Save as folder", exact=True), touch)
    form = page.get_by_role("form", name="Save as folder")
    await form.wait_for(timeout=WAIT_MS)
    got["name"] = await form.get_by_role("textbox", name="Folder name").input_value()
    got["of_switch"] = await form.get_by_role("switch").count()   # gone: saving is local only
    submit = form.get_by_role("button", name=SAVE_N)
    got["submit_label"] = (await submit.inner_text()).strip()
    got["submit_box"] = await submit.bounding_box()
    await _press(submit, touch)
    row = page.get_by_role("status", name="Saved folder")
    await row.wait_for(timeout=WAIT_MS)
    got["saved_row"] = (await row.inner_text()).strip()
    got["saved_box"] = await row.bounding_box()
    got["publish_box"] = await row.get_by_role("button", name="Publish", exact=True).bounding_box()
    return row


async def _confirm(ctx, page, row, got: dict, shot: str, *, touch: bool):
    """The saved row's Publish: the confirm opens; records its text and its Publish button; screenshot `shot`."""
    await _press(row.get_by_role("button", name="Publish", exact=True), touch)
    dlg = page.get_by_role("dialog", name="Publish to OnlyFans?")
    await dlg.wait_for(timeout=WAIT_MS)
    go = dlg.get_by_role("button", name=PUBLISH_N)
    got["confirm_text"] = (await dlg.inner_text()).strip()
    got["confirm_label"] = (await go.inner_text()).strip()
    got["confirm_box"] = await go.bounding_box()
    await page.wait_for_timeout(300)   # the pop-in settled
    got["confirm_shot"] = await ui.shot(ctx, page, shot)
    return dlg, go


def _inside(box: dict | None, width: int) -> bool:
    return bool(box) and box["x"] >= 0 and box["x"] + box["width"] <= width + 0.5


def _p95(xs: list[float]) -> float:
    s = sorted(xs)
    return round(s[max(0, math.ceil(0.95 * len(s)) - 1)], 1)


async def _timed(owner, path: str, params: dict) -> tuple[float, object]:
    t = time.perf_counter()
    r = await owner.get(path, params=params)
    return (time.perf_counter() - t) * 1000, r


async def _walk(owner, aid: str) -> tuple[list[int], list[int]]:
    ids, statuses, off = [], [], 0
    while True:
        r = await owner.get(ITEMS_PATH, params={"account_id": aid, "tags": TAGS, "limit": 1000, "offset": off})
        statuses.append(r.status_code)
        if r.status_code != 200:
            return ids, statuses
        body = r.json()
        ids += [int(m["id"]) for m in body.get("list") or []]
        if not body.get("hasMore"):
            return ids, statuses
        off += 1000


def _recorded_publish(page):
    """Every POST /admin/vault-ai/folders/<id>/publish the page sends (hold.recorded matches one exact path)."""
    sent: list[dict] = []

    def on_request(r) -> None:
        from urllib.parse import urlsplit
        if r.method == "POST" and PUBLISH_PATH.match(urlsplit(r.url).path):
            sent.append({"url": r.url, "body": r.post_data_json, "status": None, "_r": r})

    def on_response(resp) -> None:
        for x in sent:
            if x["_r"] is resp.request:
                x["status"] = resp.status

    page.on("request", on_request)
    page.on("response", on_response)
    return sent


async def run(ctx):
    w = ctx.world
    await ctx.build(PROFILE)
    (ctx.stack.tmp / "of-vault.json").write_text("{}")   # lib/vault_relay.py answers OF's vault list calls
    creator = w.data["creators"][0]
    aid = creator["id"]
    truth = vault_tag_chips.seed(w, creator, int(ctx.param("items", w.size["vault_tag_items"])))
    thumbs = stills_dir(ctx.stack.tmp) / "thumbs" / aid
    thumbs.mkdir(parents=True, exist_ok=True)
    for cls, mids in truth["classes"].items():
        for mid in mids:
            (thumbs / f"{mid}.jpg").write_bytes(picture_bytes(f"{cls}/{mid}"))
    match, live = truth["match"], truth["live"]
    n = len(match)
    ctx.note(f"Creator {aid}: {len(live)} live items, {n} carry feet AND lace; "
             + ", ".join(f"{c} {len(v)}" for c, v in truth["classes"].items()))

    # ── api ──
    r = await ctx.owner.get(FACETS_PATH, params={"account_id": aid})
    fac = r.json() if r.status_code == 200 else {}
    ctx.check(FACETS, r.status_code == 200 and fac.get("tags") == truth["facets"] and fac.get("total") == len(live),
              http=r.status_code, total=fac.get("total"), want_total=len(live), got=(fac.get("tags") or [])[:12],
              want=truth["facets"][:12])
    walked, st = await _walk(ctx.owner, aid)
    r2 = await ctx.owner.get(FACETS_PATH, params={"account_id": aid, "tags": TAGS})
    fac2 = r2.json() if r2.status_code == 200 else {}
    by = {t["tag"]: t["count"] for t in fac2.get("tags") or []}
    ctx.check(FILTER, all(s == 200 for s in st) and walked == match and r2.status_code == 200
              and fac2.get("total") == n and by.get(TAGS[0]) == by.get(TAGS[1]) == n
              and fac2.get("selected") == TAGS,
              http=st + [r2.status_code], got=len(walked), want=n,
              missing=sorted(set(match) - set(walked))[:8], stray=sorted(set(walked) - set(match))[:8],
              order_ok=walked == match, facets_total=fac2.get("total"), facets_counts={t: by.get(t) for t in TAGS})
    ms_f, ms_i = [], []
    for _ in range(TIMED):
        ms_f.append((await _timed(ctx.owner, FACETS_PATH, {"account_id": aid, "tags": TAGS}))[0])
        ms_i.append((await _timed(ctx.owner, ITEMS_PATH, {"account_id": aid, "tags": TAGS, "limit": 40}))[0])
    ctx.metric("p95_vs_last_green", {"tag facets": _p95(ms_f), "items tags page 40": _p95(ms_i)})
    ctx.metric("p95_vs_last_green_n", {"tag facets": TIMED, "items tags page 40": TIMED})

    # ── UI ──
    saves: list[tuple[str, list[dict], dict]] = []
    publishes: list[dict] = []
    statuses: list[list] = []
    if ctx.app:
        desk: dict = {}
        async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
            await page.context.add_init_script(TOURS_SEEN)
            pubs = _recorded_publish(page)
            with recorded(page, "POST", SAVE_PATH) as sent:
                try:
                    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
                    await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
                    await _taps(page, match, desk, touch=False)
                    desk["trigger_shot"] = await ui.shot(ctx, page, "vault-tag-chips-trigger")
                    row = await _save(page, desk, touch=False)
                    await page.wait_for_timeout(500)
                    desk["settled_shot"] = await ui.shot(ctx, page, "vault-tag-chips-settled")
                    desk["posts_before_confirm"] = len(pubs)
                    _dlg, go = await _confirm(ctx, page, row, desk, "vault-tag-chips-publish-confirm", touch=False)
                    desk["posts_at_confirm"] = len(pubs)
                    await go.click(timeout=10_000)
                    done = row.get_by_text(re.compile(r"^Published to OnlyFans"))
                    await done.wait_for(timeout=WAIT_MS)
                    desk["published_text"] = (await done.inner_text()).strip()
                    await page.wait_for_timeout(500)
                    desk["published_shot"] = await ui.shot(ctx, page, "vault-tag-chips-published")
                except Exception as e:  # noqa: BLE001 — the check reports it
                    desk["error"] = f"{type(e).__name__}: {e}"[:600]
                    desk["failed_shot"] = await ui.shot(ctx, page, "failed-vault-tag-chips")
                saves.append(("desktop", list(sent), desk))
            publishes += [{k: v for k, v in x.items() if k != "_r"} for x in pubs]
            statuses += page.slop["statuses"]
        mset = {str(m) for m in match}
        ctx.check(CHIPS_DESK, "error" not in desk and desk.get("feet_count") == next(
                      (t["count"] for t in truth["facets"] if t["tag"] == TAGS[0]), None)
                  and desk.get("pressed") == TAGS and desk.get("row", [])[:2] == TAGS
                  and bool(desk.get("tiles")) and set(desk["tiles"]) <= mset and desk.get("save_visible") is True,
                  ui={k: v for k, v in desk.items() if k != "tiles"}, tiles=len(desk.get("tiles") or []),
                  stray=sorted(set(desk.get("tiles") or []) - mset)[:5])

        phone: dict = {}
        async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
            await page.context.add_init_script(TOURS_SEEN + f"localStorage.setItem('vault.accountId', '{aid}');")
            phone_pubs = _recorded_publish(page)
            with recorded(page, "POST", SAVE_PATH) as sent:
                try:
                    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
                    await _taps(page, match, phone, touch=True)
                    phone["trigger_shot"] = await ui.shot(ctx, page, "vault-tag-chips-phone-trigger")
                    row = await _save(page, phone, touch=True)
                    await page.wait_for_timeout(500)
                    phone["scroll_width"] = await page.evaluate("document.documentElement.scrollWidth")
                    phone["settled_shot"] = await ui.shot(ctx, page, "vault-tag-chips-phone-settled")
                    dlg, _go = await _confirm(ctx, page, row, phone, "vault-tag-chips-phone-confirm", touch=True)
                    await dlg.get_by_role("button", name="Cancel", exact=True).tap(timeout=10_000)
                    await dlg.wait_for(state="detached", timeout=WAIT_MS)
                    phone["row_after_cancel"] = (await row.inner_text()).strip()
                except Exception as e:  # noqa: BLE001 — the check reports it
                    phone["error"] = f"{type(e).__name__}: {e}"[:600]
                    phone["failed_shot"] = await ui.shot(ctx, page, "failed-vault-tag-chips-phone")
                saves.append(("phone", list(sent), phone))
            phone["publish_posts"] = len(phone_pubs)
            statuses += page.slop["statuses"]
        width = PHONE[0]
        boxes = ("row_box", "save_box", "submit_box", "saved_box", "publish_box", "confirm_box")
        ctx.check(CHIPS_PHONE, "error" not in phone and phone.get("pressed") == TAGS
                  and bool(phone.get("tiles")) and set(phone["tiles"]) <= mset
                  and all(_inside(phone.get(b), width) for b in boxes)
                  and (phone.get("scroll_width") or 10**6) <= width,
                  ui={k: v for k, v in phone.items() if k != "tiles"}, tiles=len(phone.get("tiles") or []),
                  outside=[b for b in boxes if not _inside(phone.get(b), width)])

        def one_ok(posts: list[dict], got: dict, name: str) -> bool:
            body = (posts[0]["body"] or {}) if posts else {}
            m = SAVE_N.match(got.get("submit_label") or "")
            return ("error" not in got and len(posts) == 1 and posts[0]["status"] == 200 and body.get("tags") == TAGS
                    and body.get("of_folder_id") is None and body.get("name") == NAMES[0] and got.get("name") == NAMES[0]
                    and got.get("of_switch") == 0 and bool(m) and int(m.group(1)) == n
                    and (got.get("saved_row") or "").startswith(f"Saved locally · {name} · {n} item"))

        ctx.check(SAVED, len(saves) == 2 and all(one_ok(posts, got, name) for (_d, posts, got), name in zip(saves, NAMES)),
                  want_items=n, names=NAMES,
                  saves=[{"dev": dev, "posts": posts, **{k: got.get(k) for k in
                          ("name", "of_switch", "submit_label", "saved_row", "error", "trigger_shot", "settled_shot")}}
                         for dev, posts, got in saves])
        bad = [[s, u] for s, u in statuses if s >= 500][:10]
        ctx.check(NO_5XX, not bad, five_xx=bad, responses=len(statuses))
        want_names = set(NAMES)
        pub_ui = {k: desk.get(k) for k in ("confirm_text", "confirm_label", "posts_before_confirm", "posts_at_confirm",
                                           "published_text", "confirm_shot", "published_shot", "error")}
        pub_ui["phone_publish_posts"] = phone.get("publish_posts")
        cm = PUBLISH_N.match(desk.get("confirm_label") or "")
        pub_ui_ok = ("error" not in desk and f"{n} item" in (desk.get("confirm_text") or "") and bool(cm)
                     and int(cm.group(1)) == n and desk.get("posts_before_confirm") == 0
                     and desk.get("posts_at_confirm") == 0 and len(publishes) == 1 and publishes[0]["status"] == 200
                     and desk.get("published_text") == f"Published to OnlyFans · {n} item{'' if n == 1 else 's'}"
                     and phone.get("publish_posts") == 0)
    else:
        r = await ctx.owner.post(SAVE_PATH, json={"account_id": aid, "name": NAMES[0], "tags": TAGS, "type": "all",
                                                  "query": "", "of_folder_id": None})
        body = r.json() if r.status_code == 200 else {"body": r.text[:300]}
        saves.append(("api", [{"status": r.status_code, "body": body}], {}))
        ctx.check(SAVED, r.status_code == 200 and body.get("items") == n and body.get("name") == NAMES[0],
                  http=r.status_code, got=body, want_items=n)
        rp = await ctx.owner.post(f"/admin/vault-ai/folders/{body.get('folder_id')}/publish", json={"account_id": aid})
        publishes.append({"status": rp.status_code, "body": rp.json() if rp.status_code == 200 else rp.text[:300]})
        for name in (CHIPS_DESK, CHIPS_PHONE, NO_5XX):
            ctx.skip(name, "--no-ui")
        want_names = {NAMES[0]}
        pub_ui, pub_ui_ok = {"api": publishes}, len(publishes) == 1 and publishes[0]["status"] == 200

    # ── side effects: the saved folders, OnlyFans' list ──
    con = w.sql()
    try:
        folders = con.execute("SELECT id, name, created_by, of_list_id FROM vault_folders "
                              "WHERE account_id=? AND deleted_at IS NULL AND name LIKE 'feet + lace%'", (aid,)).fetchall()
        members = {fid: {int(m) for (m,) in con.execute(
            "SELECT media_id FROM vault_folder_items WHERE folder_id=?", (fid,))} for fid, *_ in folders}
    finally:
        con.close()
    made = {name: {"created_by": by, "of_list_id": of, "items": members[fid]} for fid, name, by, of in folders}
    want = set(match)
    ctx.check(MEMBERS, set(made) == want_names and all(
                  f["created_by"] == "operator" and f["items"] == want for f in made.values()),
              folders={k: {"created_by": f["created_by"], "of_list_id": f["of_list_id"], "items": len(f["items"])}
                       for k, f in made.items()},
              want_names=sorted(want_names), want_items=len(want),
              missing={k: sorted(want - f["items"])[:5] for k, f in made.items()},
              stray={k: sorted(f["items"] - want)[:5] for k, f in made.items()})

    of = (await ctx.owner.get("/__slop/vault/fake")).json()
    lists = [m for m in of.get("made") or [] if str(m.get("account")) == str(aid)]
    lid = lists[0]["id"] if len(lists) == 1 else None
    on_of = {int(x) for c in of.get("lists") or [] if c["list_id"] == lid for x in c["media_ids"]}
    first = made.get(NAMES[0]) or {}
    others_unpublished = all(f["of_list_id"] is None for k, f in made.items() if k != NAMES[0])
    ctx.check(PUBLISHED, pub_ui_ok and len(lists) == 1 and lists[0]["name"] == NAMES[0] and on_of == want
              and first.get("of_list_id") == lid and others_unpublished,
              ui=pub_ui, of_lists=lists, on_of=len(on_of), want=len(want),
              missing=sorted(want - on_of)[:5], stray=sorted(on_of - want)[:5],
              folder_of_list_id=first.get("of_list_id"), others_unpublished=others_unpublished)
    (ctx.out / "tag-chips.json").write_text(json.dumps(
        {"truth": truth, "facets": fac, "facets_both": fac2, "walked": walked,
         "made": {k: {**f, "items": sorted(f["items"])} for k, f in made.items()},
         "of": {"made": lists, "items": sorted(on_of)}, "publishes": publishes,
         "saves": [{"dev": d, "posts": p, "ui": {k: v for k, v in g.items() if k != "tiles"}} for d, p, g in saves]},
        default=str, indent=1))
