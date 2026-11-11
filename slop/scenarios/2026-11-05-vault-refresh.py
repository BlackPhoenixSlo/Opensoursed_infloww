"""Vault Refresh: Vault Pro's Refresh shows what was made on OnlyFans since the page loaded, and the chat Vault
picker reloads itself when its top thumbnails come back broken (expired signed urls).

World: `agency_pool` (7 Creators small, 10 medium); OnlyFans' vaults are lib/vault_wire.py's (deterministic from
--seed; `N_MIRROR` media per UI mirror Creator, `N_LIVE` per picker Creator, `N_LOAD` per load Creator) and
`seed/vault_week` + `seed/vault_cache` write what the relay holds of them by SQL: Creators 0, 1 and the load
Creators (4+) have a collected mirror (`vault_week.mirror`, an `auto:done` run) and the relay's folder list cached
2 h ago. Creators 2, 3 have the background collector's walk paused after its hot set (`vault_week.hot_paused`,
fetched SIGN_TTL_S + 1 h ago, so every thumb url in it expired 1 h ago): the folder list, every folder's page 0 and
All's pages 0 and 24 cached under the picker's keys, those media in the mirror, the run `running` at `auto:all:0`.
That mirror is live but not `complete`, so the picker reads the live listing (VaultPicker's vaultWholeSource) and
gets the cached page 1, while POST /admin/vault-ai/sync (vault_ingest.has_live_mirror) pages OF. OnlyFans is lib/of_wire.py +
lib/vault_wire.py (`OF_WIRE`: every Creator's session from seed/of_sessions, so the relay's real OFClient reads the
vault there); its CDN is lib/img_relay.py armed with every thumb, serving real pictures.

UI (small run, Chromium):
  A. Vault Pro's Refresh, desktop on Creator 0 and phone portrait (390x844, touch) on Creator 1: /growth/vault-pro
     settles on the mirror's grid and the cached rail; then a folder and K_NEW media in it are made on OnlyFans (the
     wire's state); screenshot vault-refresh-<dev>-trigger; Refresh; the rail shows the new folder and the grid's
     first tiles are the new media; screenshot vault-refresh-<dev>-settled. Checks REFRESH_FOLDER, REFRESH_MEDIA,
     REFRESH_WIRE (one POST /admin/vault-ai/sync per click, 200 with mirror and new == K_NEW; OF got a folder list
     and an offset-0 newest-first media read after the click; the relay's cached folder list (LISTS_KEY) fetched
     after the click). Then OF's vault listing fails (of_wire `fail`, 500) and Refresh again: REFRESH_FAIL_SHOWN, the
     sync's statuses kept (`sent`), Vault Pro's status line says "Couldn't reach OnlyFans, showing saved vault" and the grid keeps
     its tiles; screenshot vault-refresh-<dev>-fail.
  B. The picker, desktop on Creator 2 and phone on Creator 3: a Fan's chat in Messages Pro, Vault; page 1 comes from
     the relay's cache, its thumbs 403 at the CDN. The picker's cache invalidate (its reload) is held in the page
     until screenshot picker-thumbs-<dev>-trigger (the broken top tiles), then let through; once the top tiles drew,
     picker-thumbs-<dev>-settled. THUMBS_RELOAD: before, every top tile unloaded; one invalidate; after, every top
     tile drawn (naturalWidth > 0); the CDN answered each top tile's path 403 then 200; the relay's cached page 1
     (DB) refetched after the open, every thumb's Policy in the future. Then the picker's Refresh POST is held in
     the page: its button becomes disabled and aria-busy, five more clicks produce no POST; let through, the button
     settles. Then OF's vault media read fails (of_wire `fail`, 500) and Refresh again: the sync reaches OF, OF
     answers 500 (fake.calls), the relay answers 502 and the picker shows "Couldn't reach OnlyFans, showing saved
     vault". Screenshots picker-refresh-<dev>-trigger, -settled, -failure-settled.
     PICKER_FAILURE: pending (disabled + aria-busy), one POST for the burst, settled; one failure POST answered
     502, OF's 500 on that Creator's media read recorded, the note shown.

  C. "All media", after A's Refresh (desktop and phone, same pages): ALL_COUNTS: the row's per-type counts == OF's
     `all` (lib/vault_wire.py: the whole vault, the new media included) == what the browser's GET
     /api/of/v2/vault/lists got, and under All media exactly the zero types' chips are off. ALL_TAP: a folder tapped
     (grid == that folder's newest), then "All media" (grid == the vault's newest, first tile in the viewport), then
     "All media" again (unchanged). Screenshots vault-allmedia-<dev>-trigger (folder picked, All media's counts),
     -settled (All media's grid), -again.
  D. Search, after C (desktop and phone, same pages): K_SEARCH old media get a PPV caption on OnlyFans holding
     SEARCH_TERM (VaultWire.caption), a term the mirror's text lacks; the term is typed in the Caption search with
     POST /admin/vault-ai/search-of held in the page (Playwright route, continued unchanged). SEARCH_PENDING: while
     held the empty grid spins "Searching OnlyFans…", and from typing to the filled grid "No data" never shows in
     the grid (a MutationObserver: the grid's EmptyState). Screenshot vault-search-<dev>-trigger; let through; SEARCH_FILLS: search-of
     200 with exactly those ids, the grid then exactly them newest first, the spinner gone, of_terms holds the term
     on each (DB). Screenshot vault-search-<dev>-settled.

Load (stage `sync`, also --no-ui): K_LOAD new media in a new folder made on OnlyFans for each load Creator, then
`--users` owner sessions press Refresh at once (POST /admin/vault-ai/sync, round-robin over the load Creators, a
seeded 0-SYNC_JITTER_S start). SYNC_LOAD: every POST 200 with mirror; each load Creator's live mirror == OF's media,
id for id, with OF's folder membership. SYNC_COALESCED: at least five concurrent presses per load Creator start at most two OF media walks. Budget: p95 POST
/admin/vault-ai/sync <= SYNC_P95_MS, and vs the last green run.

Bypasses (declared): the mirror, the relay's cached listings and the run rows are SQL (no Collect or collector
walk ran); OnlyFans is lib/of_wire.py + lib/vault_wire.py (each vault call waits OF_VAULT_LATENCY_S, a guess; the listing signs its
thumbs per answer) and its CDN a fake in the relay process (lib/img_relay.py: PNGs, CDN_LATENCY_S, a guess); "made on
OnlyFans" is the wire's state changed (VaultWire.add). The Creator is
pre-picked in localStorage (`vault.accountId`, a returning owner) and Vault Pro's tours marked seen. Only
/api/of/v2/vault/lists and /media are let through in the browser; every other /api/of/ read stays held. The picker's
invalidate and its first Refresh POST are held in the page (Playwright route, then continued unchanged) for the
trigger screenshots and the click burst (milliseconds otherwise). The load's sessions share one
owner login (`ctx.owner.share`).
Break-it-once: vault-refresh-cache-only (FAULT, client: the pre-fix Refresh; REFRESH_FOLDER, REFRESH_MEDIA,
REFRESH_WIRE, REFRESH_FAIL_SHOWN, PICKER_FAILURE), vault-search-no-spinner (client: "No data" while OF's search
runs; SEARCH_PENDING), vault-refresh-fail-silent (client: a failed sync reads as ok; REFRESH_FAIL_SHOWN),
vault-thumbs-no-auto-refresh (client; THUMBS_RELOAD), vault-all-media-no-counts (client: the list's `all`
dropped; ALL_COUNTS), vault-sync-no-coalesce (relay; SYNC_COALESCED; run with
--no-ui).
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import arm_run, policy_exp
from slop.lib.vault_ui import TOURS_SEEN, open_vault_picker, open_vault_pro, cdn_calls as _cdn_calls, captured
from slop.lib.vault_wire import HOST, SIGN_TTL_S, VaultWire, path as cdn_path
from slop.lib.vault_refresh_faults import (ALL_COUNTS, ALL_TAP, PICKER_FAILURE, REFRESH_FAIL_SHOWN, REFRESH_FOLDER,
                                           REFRESH_MEDIA, REFRESH_WIRE, SEARCH_FILLS, SEARCH_PENDING,
                                           SYNC_COALESCED, SYNC_LOAD, THUMBS_RELOAD)
from slop.seed import of_sessions, vault_cache, vault_week

PROFILE = "agency_pool"
UI = True
OF_WIRE = True  # the vault's OnlyFans reads go to lib/of_wire.py through the relay's real OFClient
# lib/vault_collect_relay.py: the vault still stores in the run's temp dir; the background collector stays off (it
# would walk these vaults and change the mirror under the checks).
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
FAULT = "vault-refresh-cache-only"
N_MIRROR = 40          # media per UI mirror Creator
N_LIVE = 40            # media per picker Creator (pages 1 and 2 cached by the hot set)
N_LOAD = 200           # media per load Creator before the change
K_NEW = 5              # media made on OF during a UI refresh
K_LOAD = 150           # media made on OF per load Creator: a sync reads 2 pages new + 1 page known
TOP = 6                # the picker's top tiles checked (two rows on a phone)
CDN_LATENCY_S = 0.05
OF_VAULT_LATENCY_S = 0.15   # each OF vault call (a guess)
SYNC_JITTER_S = 0.3
SYNC_TIMEOUT_S = 120
SYNC_P95_MS = 5000
P95_VS_LAST = (1.5, 500)
P95_VS_LAST_MIN_N = 5
SYNC_PATH = "/admin/vault-ai/sync"
SYNC_ROUTE = ("sync", f"POST {SYNC_PATH}")
SYNC_BUDGET = f"p95 {SYNC_ROUTE[1]} <= {SYNC_P95_MS} ms (stage {SYNC_ROUTE[0]})"
LISTS_PATH = "/api/of/v2/vault/lists"
MEDIA_PATH = "/api/of/v2/vault/media"
INVALIDATE_PATH = "/admin/vault/cache/invalidate"
OF_MEDIA_ROUTE = "GET /api2/v2/vault/media"
FAIL_NOTE = "Couldn't reach OnlyFans, showing saved vault"   # VaultManagePanel's refreshNote
SEARCH_PATH = "/admin/vault-ai/search-of"
SEARCH_TERM = "zebra leggings"   # only OF's search knows it (a PPV caption); no mirror text holds it
SEARCHING = "Searching OnlyFans…"   # VaultManagePanel's empty grid while OF's own search runs
K_SEARCH = 3
DESKTOP, PHONE = (1440, 900), (390, 844)
WAIT_MS = 120_000
SETTLE_MS = 25_000


def _of_mark(ctx) -> int:
    with ctx.of_wire.lock:
        return len(ctx.of_wire.vault_calls)


def _failed_of_media(ctx, aid: str, since: int) -> int:
    """OF's vault media reads of `aid` answered 500 since `since` (an index into fake.calls, which records the
    `fail` answers; vault_calls never sees them)."""
    with ctx.of_wire.lock:
        calls = list(ctx.of_wire.calls[since:])
    return sum(1 for c in calls if c["account"] == aid and c["route"] == OF_MEDIA_ROUTE and c["status"] == 500)


def _of_calls(ctx, since: int = 0) -> list[dict]:
    """OnlyFans' vault listing calls since `since` (vault_wire's record), in arrival order: {account, op, status,
    offset, sort, list}."""
    with ctx.of_wire.lock:
        calls = list(ctx.of_wire.vault_calls[since:])
    return [{"account": c["account"], "op": c["route"], "status": c["status"],
             "offset": int(c["query"].get("offset") or 0), "sort": c["query"].get("sort"), "list": c["query"].get("list")}
            for c in calls if c["route"] in ("lists", "media")]


def _exp(url: str) -> float:
    q = parse_qs(urlsplit(url).query)
    return policy_exp(q["Policy"][0])


def _seed_world(w, wire, mirror: list[str], live: list[str]) -> None:
    fake = wire.fake
    with fake.lock:
        for aid in (*mirror, *live):
            fake.extra_s[aid] = max(0.0, OF_VAULT_LATENCY_S - fake.latency_s)
    vault_week.mirror(w, wire, mirror)
    fetched = w.now - timedelta(hours=2)
    con = w.sql()
    with con:
        for aid in mirror:
            vault_cache.cache_row(con, aid, vault_cache.LISTS_KEY,
                                  {"list": wire.vault(aid)["folders"], "hasMore": False,
                                   "all": wire.all_counts(aid)}, fetched)
    con.close()
    # The picker Creators: the hot set OF signed SIGN_TTL_S + 1 h ago, so its thumbs expired an hour ago.
    hot_at = w.now - timedelta(seconds=SIGN_TTL_S + 3600)
    vault_week.hot_paused(w, wire, live, at=hot_at,
                          exp=int(hot_at.replace(tzinfo=timezone.utc).timestamp()) + SIGN_TTL_S)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    mirror_ui, live_ui, load = aids[:2], aids[2:4], aids[4:]
    n = {**{a: N_MIRROR for a in mirror_ui}, **{a: N_LIVE for a in live_ui}, **{a: N_LOAD for a in load}}
    of_sessions.seed(w, creators)  # a real OFClient per Creator, talking to lib/of_wire.py
    vw = VaultWire(ctx.of_wire, seed=ctx.seed, items=N_LOAD, sizes=n)
    _seed_world(w, vw, [*mirror_ui, *load], live_ui)
    await arm_run(ctx.owner, ctx.stack.tmp, vw.assets(aids), CDN_LATENCY_S, pictures=True)

    async def made_on_of(aid: str, k: int, name: str):
        folder, news = vw.add(aid, name, k)
        await arm_run(ctx.owner, ctx.stack.tmp, vw.assets(aids), CDN_LATENCY_S, pictures=True)
        return folder, news

    ctx.rec.stage = "ui"
    if ctx.app is None:
        for c in (REFRESH_FOLDER, REFRESH_MEDIA, REFRESH_WIRE, REFRESH_FAIL_SHOWN, ALL_COUNTS, ALL_TAP, THUMBS_RELOAD,
                  PICKER_FAILURE, SEARCH_PENDING, SEARCH_FILLS):
            ctx.skip(c, "--no-ui")
    else:
        a = [await _refresh_ui(ctx, w, vw, aid, dev, made_on_of)
             for aid, dev in zip(mirror_ui, ("desktop", "phone"))]
        _check_refresh(ctx, w, a)
        _check_all_media(ctx, a)
        _check_search(ctx, a)
        b = [await _picker_ui(ctx, w, vw, aid, dev)
             for aid, dev in zip(live_ui, ("desktop", "phone"))]
        _check_picker(ctx, w, b)

    await _load(ctx, w, vw, load, made_on_of)


# ── A: Vault Pro's Refresh ─────────────────────────────────────────

async def _refresh_ui(ctx, w, vw, aid: str, dev: str, made_on_of) -> dict:
    name = f"Made on OF {dev}"
    got: dict = {"aid": aid, "dev": dev, "folder_name": name}
    vp, touch = (DESKTOP, False) if dev == "desktop" else (PHONE, True)
    async with ui.owner_browser(ctx, viewport=vp, through=(LISTS_PATH, MEDIA_PATH), touch=touch) as page:
        await page.context.add_init_script(TOURS_SEEN + f"localStorage.setItem('vault.accountId', '{aid}');")
        tiles = page.locator("section [title^='#']")
        lists_bodies: list[dict] = []

        async def on_lists(r) -> None:
            if urlsplit(r.url).path == LISTS_PATH and r.ok:
                try:
                    lists_bodies.append(await r.json())
                except Exception:  # noqa: BLE001 — a body the page dropped
                    pass

        page.on("response", lambda r: asyncio.ensure_future(on_lists(r)))
        with recorded(page, "POST", SYNC_PATH) as sent:
            async with captured(ctx, page, got, f"failed-vault-refresh-{dev}"):
                await open_vault_pro(page, ctx, timeout=WAIT_MS)
                await tiles.first.wait_for(timeout=WAIT_MS)
                await page.get_by_text(vw.vault(aid)["folders"][0]["name"], exact=True).first.wait_for(timeout=WAIT_MS)
                await page.wait_for_timeout(1500)
                got["before_folder"] = await page.get_by_text(name, exact=True).count()
                got["before_sync"] = len(sent)
                folder, news = await made_on_of(aid, K_NEW, name)
                got["folder"], got["news"] = folder, [m["id"] for m in news]
                c0 = _of_mark(ctx)
                got["clicked_at"] = time.time()
                got["trigger_shot"] = await ui.shot(ctx, page, f"vault-refresh-{dev}-trigger")
                async with page.expect_response(lambda r: urlsplit(r.url).path == SYNC_PATH
                                                and r.request.method == "POST", timeout=SETTLE_MS) as resp:
                    await page.get_by_role("button", name="Refresh", exact=True).click(timeout=10_000)
                r = await resp.value
                got["sync"] = {"status": r.status, "body": await r.json() if r.ok else (await r.text())[:300]}
                await page.get_by_text(name, exact=True).first.wait_for(timeout=SETTLE_MS)
                await page.locator(f"section [title^='#{news[-1]['id']} ']").first.wait_for(timeout=SETTLE_MS)
                await page.get_by_text(name, exact=True).first.scroll_into_view_if_needed(timeout=5000)  # phone: in view
                await page.wait_for_timeout(1500)
                got["grid"] = [int(t.split(" ", 1)[0][1:]) for t in
                               await tiles.evaluate_all("els => els.map(e => e.getAttribute('title'))")][:K_NEW + 3]
                got["settled_shot"] = await ui.shot(ctx, page, f"vault-refresh-{dev}-settled")
                got["of_calls"] = _of_calls(ctx, c0)
            got["sent"] = [{"url": s["url"], "status": s["status"]} for s in sent]
        try:  # its own step: after the Refresh, so OF's `all` includes the media made since
            got["all_media"] = await _all_media(ctx, page, vw, aid, dev, tiles, lists_bodies)
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["all_media"] = {"error": f"{type(e).__name__}: {e}"[:600]}
            try:
                got["all_media"]["failed_shot"] = await ui.shot(ctx, page, f"failed-vault-allmedia-{dev}")
            except Exception:  # noqa: BLE001
                pass
        try:  # its own step: a Refresh that failed above still has to say so here
            got["fail"] = await _refresh_fails(ctx, page, aid, dev, tiles)
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["fail"] = {"error": f"{type(e).__name__}: {e}"[:600]}
        try:  # its own step, on the grid as the owner left it
            got["search"] = await _search(ctx, page, vw, aid, dev, tiles)
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["search"] = {**got.get("search", {}), "error": f"{type(e).__name__}: {e}"[:600]}
            try:
                got["search"]["failed_shot"] = await ui.shot(ctx, page, f"failed-vault-search-{dev}")
            except Exception:  # noqa: BLE001
                pass
        got["held_of_reads"] = len(page.slop["held_of_reads"])
    con = w.sql()
    try:
        ids = got.get("news") or []
        got["db"] = {m: of for m, of, rm in con.execute(
            f"SELECT media_id, of_folder_ids, removed_at FROM vault_items WHERE account_id=? AND media_id IN "
            f"({','.join('?' * len(ids))})", (aid, *ids)) if rm is None} if ids else {}
        row = con.execute("SELECT fetched_at FROM vault_response_cache WHERE account_id=? AND query_key=?",
                          (aid, vault_cache.LISTS_KEY)).fetchone()
        got["lists_cached_after_click"] = bool(row and "clicked_at" in got and datetime.strptime(
            row[0][:19], "%Y-%m-%d %H:%M:%S").timestamp() >= _utc_epoch_floor(got["clicked_at"]))
        hits = (got.get("search") or {}).get("hits") or []
        if hits:
            got["search"]["db_terms"] = {m: json.loads(t or "[]") for m, t in con.execute(
                f"SELECT media_id, of_terms FROM vault_items WHERE account_id=? AND media_id IN "
                f"({','.join('?' * len(hits))})", (aid, *hits))}
    finally:
        con.close()
    (ctx.out / f"vault-refresh-{dev}.json").write_text(json.dumps(got, indent=2, default=str))
    return got


_GRID_STATE = """() => {
  const ts = [...document.querySelectorAll("section [title^='#']")];
  const r = ts[0] ? ts[0].getBoundingClientRect() : null;
  return {ids: ts.slice(0, 8).map(e => Number(e.getAttribute('title').split(' ')[0].slice(1))),
          first_top: r ? Math.round(r.top) : null, vh: innerHeight, scroll_y: Math.round(scrollY)};
}"""
_ROW_COUNTS = "b => Object.fromEntries([...b.querySelectorAll('[title]')].map(e => [e.getAttribute('title'), e.textContent]))"
CHIPS = {"photo": "Photo", "video": "Video", "gif": "GIF", "audio": "Audio"}


async def _grid_until(page, want: list[int]) -> dict:
    """The grid's state once its first tiles are `want` (or at SETTLE_MS, as it is)."""
    deadline = time.time() + SETTLE_MS / 1000
    while True:
        st = await page.evaluate(_GRID_STATE)
        if st["ids"][:len(want)] == want or time.time() > deadline:
            return st
        await asyncio.sleep(0.2)


async def _all_media(ctx, page, vw, aid: str, dev: str, tiles, lists_bodies: list[dict]) -> dict:
    """The "All media" row: its counts against OF's `all` (and what the browser got), the chips under it; then a
    folder tapped, "All media" tapped (the grid back to the whole vault, in view), and tapped again."""
    out: dict = {"want_all": vw.all_counts(aid)}
    press = (lambda loc: loc.tap(timeout=10_000)) if dev == "phone" else (lambda loc: loc.click(timeout=10_000))
    rail = page.locator("aside").filter(has_text="All media").first
    all_row = rail.locator("button").filter(has_text="All media").first
    await all_row.scroll_into_view_if_needed(timeout=5000)
    out["browser_all"] = (lists_bodies[-1] if lists_bodies else {}).get("all")
    out["lists_reads"] = len(lists_bodies)
    out["row_counts"] = await all_row.evaluate(_ROW_COUNTS)
    out["chips_off"] = sorted([k for k, name in CHIPS.items()
                               if await page.locator("section").get_by_role("button", name=name, exact=True)
                               .first.is_disabled()])
    f0 = vw.vault(aid)["folders"][0]
    want_f = [m["id"] for m in vw.listing(aid, list_id=f0["id"])][:4]
    want_all = vw.newest(aid, 6)
    out["want_folder"], out["want_grid"] = want_f, want_all
    row = rail.locator("[role=button]").filter(has_text=f0["name"]).first
    await row.scroll_into_view_if_needed(timeout=5000)
    await press(row)
    out["folder"] = await _grid_until(page, want_f)
    await all_row.scroll_into_view_if_needed(timeout=5000)
    out["trigger_shot"] = await ui.shot(ctx, page, f"vault-allmedia-{dev}-trigger")
    await press(all_row)
    out["all"] = await _grid_until(page, want_all)
    await page.wait_for_timeout(500)
    out["all"] = await page.evaluate(_GRID_STATE)
    out["settled_shot"] = await ui.shot(ctx, page, f"vault-allmedia-{dev}-settled")
    # Again, with All media already the pick.
    await all_row.scroll_into_view_if_needed(timeout=5000)
    await press(all_row)
    await page.wait_for_timeout(800)
    out["again"] = await page.evaluate(_GRID_STATE)
    out["again_shot"] = await ui.shot(ctx, page, f"vault-allmedia-{dev}-again")
    return out


def _check_all_media(ctx, runs: list[dict]) -> None:
    counts_ok, tap_ok = [], []
    for g in runs:
        a = g.get("all_media") or {}
        want = a.get("want_all") or {}
        shown = {k: int(v) for k, v in (a.get("row_counts") or {}).items() if str(v).isdigit()}
        want_shown = {k[:-len("sCount")]: v for k, v in want.items() if v}
        off_want = sorted(k for k in CHIPS if not want.get(f"{k}sCount"))
        counts_ok.append("error" not in a and want_shown and shown == want_shown and a.get("browser_all") == want
                         and a.get("chips_off") == off_want and 0 < len(off_want) < len(CHIPS))
        def ok(st, ids):
            return bool(st) and st["ids"][:len(ids)] == ids and st["first_top"] is not None \
                and 0 <= st["first_top"] < st["vh"]
        tap_ok.append("error" not in a and bool(a.get("want_folder")) and a["want_folder"] != a["want_grid"][:4]
                      and (a.get("folder") or {}).get("ids", [])[:4] == a["want_folder"]
                      and ok(a.get("all"), a["want_grid"]) and ok(a.get("again"), a["want_grid"]))
    devs = [g["dev"] for g in runs]
    am = [g.get("all_media") or {} for g in runs]
    ctx.check(ALL_COUNTS, all(counts_ok), per_dev=dict(zip(devs, counts_ok)),
              row_counts=[a.get("row_counts") for a in am], want=[a.get("want_all") for a in am],
              browser_all=[a.get("browser_all") for a in am], chips_off=[a.get("chips_off") for a in am],
              errors={d: a.get("error") for d, a in zip(devs, am) if "error" in a})
    ctx.check(ALL_TAP, all(tap_ok), per_dev=dict(zip(devs, tap_ok)),
              states=[{k: a.get(k) for k in ("want_folder", "folder", "want_grid", "all", "again")} for a in am],
              shots=[[a.get("trigger_shot"), a.get("settled_shot"), a.get("again_shot")] for a in am],
              errors={d: a.get("error") for d, a in zip(devs, am) if "error" in a})


async def _refresh_fails(ctx, page, aid: str, dev: str, tiles) -> dict:
    """OF's vault listing answers 500 (of_wire `fail`) while Refresh is pressed again: what the owner sees."""
    out: dict = {"tiles_before": await tiles.count()}
    with ctx.of_wire.lock:
        ctx.of_wire.fail.add((aid, OF_MEDIA_ROUTE))
    try:
        with recorded(page, "POST", SYNC_PATH) as sent:
            # Any vault-ai POST: the press's answer, so the note waited for below is this press's, not an earlier
            # failure's still on screen (the press hides it while pending).
            async with page.expect_response(lambda r: "/admin/vault-ai/" in r.url and r.request.method == "POST",
                                            timeout=SETTLE_MS):
                await page.get_by_role("button", name="Refresh", exact=True).click(timeout=10_000)
            note = page.get_by_role("status").filter(has_text=FAIL_NOTE)
            try:
                await note.first.wait_for(timeout=SETTLE_MS)
                out["note"] = await note.count()
            except Exception as e:  # noqa: BLE001 — the check reports it
                out["note"], out["note_error"] = 0, f"{type(e).__name__}"
            await page.wait_for_timeout(500)
        out["sent"] = [{"url": x["url"], "status": x["status"]} for x in sent]
        out["tiles_kept"] = await tiles.count()
        out["shot"] = await ui.shot(ctx, page, f"vault-refresh-{dev}-fail")
    finally:
        with ctx.of_wire.lock:
            ctx.of_wire.fail.discard((aid, OF_MEDIA_ROUTE))
    return out


# ── D: a caption search only OnlyFans answers ──────────────────────

_WATCH_NO_DATA = """() => {
  window.__slopNoData = 0;
  const seen = () => {
    if ([...document.querySelectorAll("section [data-empty-state]")].some(e => /No data/.test(e.textContent)))
      window.__slopNoData += 1;
  };
  window.__slopNoDataObs = new MutationObserver(seen);
  window.__slopNoDataObs.observe(document.body, {subtree: true, childList: true, characterData: true});
}"""
_STOP_NO_DATA = "() => { window.__slopNoDataObs && window.__slopNoDataObs.disconnect(); return window.__slopNoData; }"


async def _search(ctx, page, vw, aid: str, dev: str, tiles) -> dict:
    """SEARCH_TERM typed in the Caption search; OF's own search (POST search-of) held in the page, then let through."""
    hits = [m["id"] for m in vw.vault(aid)["media"][-K_SEARCH:]]   # old media, newest first; in the mirror
    out: dict = {"hits": hits}
    vw.caption(aid, hits, f"New {SEARCH_TERM} set, unlock it 💕")
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(route):
        entered.set()
        await release.wait()
        await route.continue_()

    match = lambda u: urlsplit(u).path == SEARCH_PATH  # noqa: E731
    box = page.get_by_placeholder("Search media by PPV caption")
    searching = page.get_by_role("status").filter(has_text=SEARCHING)
    await page.route(match, hold)
    try:
        await page.evaluate(_WATCH_NO_DATA)
        await box.fill(SEARCH_TERM, timeout=10_000)
        await asyncio.wait_for(entered.wait(), SETTLE_MS / 1000)
        try:
            await searching.first.wait_for(timeout=SETTLE_MS)
        except Exception as e:  # noqa: BLE001 — recorded below; the check reports it
            out["pending_error"] = type(e).__name__
        await page.wait_for_timeout(1500)   # held: the state stands
        out["pending_spinner"] = await searching.count()
        out["pending_tiles"] = await tiles.count()
        out["trigger_shot"] = await ui.shot(ctx, page, f"vault-search-{dev}-trigger")
        async with page.expect_response(lambda r: match(r.url) and r.request.method == "POST",
                                        timeout=SETTLE_MS) as resp:
            release.set()
        r = await resp.value
        out["search_of"] = {"status": r.status, "body": await r.json() if r.ok else (await r.text())[:300]}
        await page.locator(f"section [title^='#{hits[0]} ']").first.wait_for(timeout=SETTLE_MS)
        st = await _grid_until(page, hits)
        await page.wait_for_timeout(500)
        out["grid"] = st["ids"]
        out["tiles"] = await tiles.count()
        out["settled_spinner"] = await page.get_by_text("Searching OnlyFans", exact=False).count()
        out["no_data_seen"] = await page.evaluate(_STOP_NO_DATA)
        out["settled_shot"] = await ui.shot(ctx, page, f"vault-search-{dev}-settled")
    finally:
        release.set()
        await page.unroute(match, hold)
    return out


def _check_search(ctx, runs: list[dict]) -> None:
    ss = [g.get("search") or {"error": g.get("error", "not run")} for g in runs]
    pending_ok = ["error" not in s and s.get("pending_spinner", 0) >= 1 and s.get("pending_tiles") == 0
                  and s.get("no_data_seen") == 0 for s in ss]
    fills_ok = []
    for s in ss:
        body = (s.get("search_of") or {}).get("body")
        body = body if isinstance(body, dict) else {}
        hits = s.get("hits") or []
        fills_ok.append("error" not in s and (s.get("search_of") or {}).get("status") == 200
                        and sorted(body.get("ids") or []) == sorted(hits) and len(hits) == K_SEARCH
                        and s.get("grid") == hits and s.get("tiles") == K_SEARCH and s.get("settled_spinner") == 0
                        and all(SEARCH_TERM in (s.get("db_terms") or {}).get(m, []) for m in hits))
    devs = [g["dev"] for g in runs]
    shots = [[s.get("trigger_shot"), s.get("settled_shot") or s.get("failed_shot")] for s in ss]
    ctx.check(SEARCH_PENDING, all(pending_ok), per_dev=dict(zip(devs, pending_ok)),
              pending=[{k: s.get(k) for k in ("pending_spinner", "pending_tiles", "no_data_seen", "pending_error",
                                              "error")} for s in ss], shots=shots)
    ctx.check(SEARCH_FILLS, all(fills_ok), per_dev=dict(zip(devs, fills_ok)),
              want=[s.get("hits") for s in ss], grid=[s.get("grid") for s in ss], tiles=[s.get("tiles") for s in ss],
              search_of=[s.get("search_of") for s in ss], db_terms=[s.get("db_terms") for s in ss],
              errors=[s.get("error") for s in ss], shots=shots)


def _check_refresh(ctx, w, runs: list[dict]) -> None:
    folder_ok, media_ok, wire_ok = [], [], []
    for g in runs:
        err = "error" in g
        news = g.get("news") or []
        fid = (g.get("folder") or {}).get("id")
        folder_ok.append(not err and g.get("before_folder") == 0)
        want = list(reversed(news))
        media_ok.append(not err and g.get("grid", [])[:len(news)] == want and len(news) == K_NEW
                        and all(json.loads(g["db"].get(m, "null") or "null") == [fid] for m in news))
        sync = g.get("sync") or {}
        body = sync.get("body") if isinstance(sync.get("body"), dict) else {}
        calls = g.get("of_calls") or []
        mine = [c for c in calls if c["account"] == g["aid"]]
        wire_ok.append(not err and g.get("before_sync") == 0 and len(g.get("sent", [])) == 1
                       and sync.get("status") == 200 and body.get("mirror") is True and body.get("new") == K_NEW
                       and any(c["op"] == "lists" for c in mine)
                       and any(c["op"] == "media" and c["offset"] == 0 and c["sort"] == "desc" for c in mine)
                       and g.get("lists_cached_after_click") is True)
    shots = [[g.get("trigger_shot"), g.get("settled_shot") or g.get("failed_shot")] for g in runs]
    errors = {g["dev"]: g.get("error") for g in runs if "error" in g}
    ctx.check(REFRESH_FOLDER, all(folder_ok), per_dev=dict(zip([g["dev"] for g in runs], folder_ok)),
              before=[g.get("before_folder") for g in runs], errors=errors, shots=shots)
    ctx.check(REFRESH_MEDIA, all(media_ok), per_dev=dict(zip([g["dev"] for g in runs], media_ok)),
              grid=[g.get("grid") for g in runs], want=[list(reversed(g.get("news") or [])) for g in runs],
              db=[g.get("db") for g in runs], errors=errors)
    ctx.check(REFRESH_WIRE, all(wire_ok), per_dev=dict(zip([g["dev"] for g in runs], wire_ok)),
              sent=[g.get("sent") for g in runs], sync=[g.get("sync") for g in runs],
              of_ops=[[(c["op"], c.get("offset"), c.get("sort")) for c in g.get("of_calls") or []
                       if c["account"] == g["aid"]] for g in runs],
              lists_cached_after_click=[g.get("lists_cached_after_click") for g in runs], errors=errors)
    fails = [g.get("fail") or {} for g in runs]
    fail_ok = ["error" not in f and f.get("note", 0) >= 1 and f.get("tiles_before", 0) > 0
               and f.get("tiles_kept") == f.get("tiles_before")
               and any(isinstance(x["status"], int) and x["status"] >= 500
                       for x in f.get("sent", []) if SYNC_PATH in x["url"]) for f in fails]
    ctx.check(REFRESH_FAIL_SHOWN, all(fail_ok), per_dev=dict(zip([g["dev"] for g in runs], fail_ok)), fail=fails,
              shots=[f.get("shot") for f in fails])


# ── B: the picker's broken thumbs ──────────────────────────────────

_TILE_STATE = """([ids]) => ids.map(id => {
  const d = document.querySelector('[role=dialog][aria-label="Vault picker"]');
  const im = d ? [...d.querySelectorAll('img')].find(i => decodeURIComponent(i.getAttribute('src') || '')
    .includes('/' + id + '/thumb.jpg')) : null;
  return [id, !!im, !!(im && im.complete && im.naturalWidth > 0)];
})"""


async def _picker_ui(ctx, w, vw, aid: str, dev: str) -> dict:
    page1 = vw.listing(aid)[:vault_cache.PICKER_PAGE]
    top = [m["id"] for m in page1[:TOP]]
    fan = next(f["id"] for f in w.data["fans"][aid])
    got: dict = {"aid": aid, "dev": dev, "top": top, "fan": fan}
    vp, touch = (DESKTOP, False) if dev == "desktop" else (PHONE, True)
    t_open = time.time()
    cdn0 = len(await _cdn_calls(ctx))
    async with ui.owner_browser(ctx, viewport=vp, through=(LISTS_PATH, MEDIA_PATH), touch=touch) as page:
        held, release, inv = asyncio.Event(), asyncio.Event(), []

        async def hold_invalidate(route):
            inv.append(time.time())
            held.set()
            await release.wait()
            await route.continue_()

        await page.route(lambda u: urlsplit(u).path == INVALIDATE_PATH, hold_invalidate)
        with recorded(page, "GET", MEDIA_PATH) as reads:
            async with captured(ctx, page, got, f"failed-picker-thumbs-{dev}"):   # an error lands in got["error"]
                try:
                    await open_vault_picker(page, ctx, aid, fan, timeout=WAIT_MS)
                    await asyncio.wait_for(held.wait(), SETTLE_MS / 1000)
                    await page.wait_for_timeout(300)
                    got["before"] = await page.evaluate(_TILE_STATE, [top])
                    got["trigger_shot"] = await ui.shot(ctx, page, f"picker-thumbs-{dev}-trigger")
                    release.set()
                    deadline = time.time() + SETTLE_MS / 1000
                    while time.time() < deadline:
                        got["after"] = await page.evaluate(_TILE_STATE, [top])
                        if all(x[2] for x in got["after"]):
                            break
                        await asyncio.sleep(0.25)
                    await page.wait_for_timeout(3000)   # a loop would show a second invalidate here
                    got["after"] = await page.evaluate(_TILE_STATE, [top])
                    got["settled_shot"] = await ui.shot(ctx, page, f"picker-thumbs-{dev}-settled")
                finally:
                    release.set()
            got["media_reads"] = [{"offset": parse_qs(urlsplit(r["url"]).query).get("offset"), "status": r["status"]}
                                  for r in reads]
        if "error" not in got:
            con = w.sql()
            try:
                row = con.execute("SELECT response_json, fetched_at FROM vault_response_cache WHERE account_id=? AND "
                                  "query_key=?", (aid, vault_cache.PICKER_KEY)).fetchone()
            finally:
                con.close()
            if row:
                body = json.loads(row[0])
                fetched = datetime.strptime(row[1][:19], "%Y-%m-%d %H:%M:%S")
                got["db"] = {"fetched_after_open": fetched.timestamp() >= _utc_epoch_floor(t_open),
                             "min_exp_ahead_s": round(min(_exp(m["files"]["thumb"]["url"]) for m in body["list"])
                                                      - time.time())}
            got["refresh"] = await _picker_refresh(ctx, page, aid, dev)
        got["invalidates"] = len(inv)
    keys = {f"{HOST}{cdn_path(aid, m, 'thumb')}": m for m in top}
    got["cdn"] = {}
    for c in await _cdn_calls(ctx, cdn0):
        if c["key"] in keys:
            got["cdn"].setdefault(str(keys[c["key"]]), []).append(c["status"])
    (ctx.out / f"picker-thumbs-{dev}.json").write_text(json.dumps(got, indent=2, default=str))
    return got


def _utc_epoch_floor(t: float) -> float:
    """`t` (epoch) as the naive-UTC wall clock the DB stores, read back the way the check reads `fetched_at`."""
    return datetime.utcfromtimestamp(int(t) - 1).timestamp()


def _check_picker(ctx, w, runs: list[dict]) -> None:
    ok = []
    for g in runs:
        before = g.get("before") or []
        after = g.get("after") or []
        cdn = g.get("cdn") or {}
        db = g.get("db") or {}
        ok.append("error" not in g and len(before) == TOP and not any(x[2] for x in before)
                  and len(after) == TOP and all(x[2] for x in after) and g.get("invalidates") == 1
                  and all(cdn.get(str(m), [])[:1] == [403] and 200 in cdn.get(str(m), []) for m in g["top"])
                  and db.get("fetched_after_open") is True and db.get("min_exp_ahead_s", -1) > 0)
    ctx.check(THUMBS_RELOAD, all(ok), per_dev=dict(zip([g["dev"] for g in runs], ok)),
              before=[g.get("before") for g in runs], after=[g.get("after") for g in runs],
              invalidates=[g.get("invalidates") for g in runs], cdn=[g.get("cdn") for g in runs],
              media_reads=[g.get("media_reads") for g in runs], db=[g.get("db") for g in runs],
              errors={g["dev"]: g.get("error") for g in runs if "error" in g},
              shots=[[g.get("trigger_shot"), g.get("settled_shot") or g.get("failed_shot")] for g in runs])
    refresh = [g.get("refresh") or {} for g in runs]
    good = [r.get("pending") is True and r.get("burst_posts") == 1 and r.get("settled") is True
            and r.get("failure_posts") == 1 and r.get("failure_of_500") is True
            and r.get("failure_statuses") == [502] and r.get("failure_note") == FAIL_NOTE for r in refresh]
    ctx.check(PICKER_FAILURE, all(good),
              per_dev=dict(zip([g["dev"] for g in runs], good)), refresh=refresh)


async def _picker_refresh(ctx, page, aid: str, dev: str) -> dict:
    """The picker's Refresh: its first sync POST held in the page while the button is checked and clicked five more
    times, then let through; then a Refresh while OF's vault media read fails (of_wire `fail`, 500)."""
    out: dict = {}
    button = page.get_by_role("dialog", name="Vault picker").get_by_role("button", name="refresh", exact=True)
    entered, release = asyncio.Event(), asyncio.Event()
    posts = []

    async def hold_sync(route):
        posts.append(route.request.url)
        entered.set()
        await release.wait()
        await route.continue_()

    sync_match = lambda u: urlsplit(u).path == SYNC_PATH  # noqa: E731
    await page.route(sync_match, hold_sync)
    async with captured(ctx, page, out, f"failed-picker-refresh-{dev}"):   # an error lands in out["error"]
        try:
            await button.click(timeout=SETTLE_MS)
            await asyncio.wait_for(entered.wait(), SETTLE_MS / 1000)
            try:
                await page.wait_for_function("() => { const b = document.querySelector('[role=dialog][aria-label=\"Vault picker\"] button[aria-busy=\"true\"]'); return b && b.disabled; }",
                                             timeout=5000)
            except Exception:  # noqa: BLE001 — record the observed state below
                pass
            out["pending_disabled"] = await button.is_disabled()
            out["pending_busy"] = await button.get_attribute("aria-busy")
            out["pending"] = out["pending_disabled"] and out["pending_busy"] == "true"
            out["trigger"] = await ui.shot(ctx, page, f"picker-refresh-{dev}-trigger")
            await button.evaluate("b => { for (let i = 0; i < 5; i++) b.click(); }")
            await page.wait_for_timeout(300)
            out["burst_posts"] = len(posts)
        finally:
            release.set()
        await page.wait_for_function("() => document.querySelector('[role=dialog][aria-label=\"Vault picker\"] button[aria-busy=\"false\"]') !== null",
                                     timeout=SETTLE_MS)
        out["settled"] = not await button.is_disabled()
        out["settled_shot"] = await ui.shot(ctx, page, f"picker-refresh-{dev}-settled")
        await page.unroute(sync_match, hold_sync)
        # The sync reaches OF (the Creator's mirror is live); OF's media read answers 500 at the OF wire.
        with ctx.of_wire.lock:
            c_fail = len(ctx.of_wire.calls)
            ctx.of_wire.fail.add((aid, OF_MEDIA_ROUTE))
        try:
            with recorded(page, "POST", SYNC_PATH) as failed:
                await button.click(timeout=SETTLE_MS)
                note = page.get_by_role("dialog", name="Vault picker").get_by_role("status").filter(has_text=FAIL_NOTE)
                await note.first.wait_for(timeout=SETTLE_MS)
                out["failure_note"] = FAIL_NOTE
                out["failure_posts"] = len(failed)
                out["failure_statuses"] = [x["status"] for x in failed]
                out["failure_shot"] = await ui.shot(ctx, page, f"picker-refresh-{dev}-failure-settled")
        finally:
            with ctx.of_wire.lock:
                ctx.of_wire.fail.discard((aid, OF_MEDIA_ROUTE))
        out["failure_of_500s"] = _failed_of_media(ctx, aid, c_fail)
        out["failure_of_500"] = out["failure_of_500s"] > 0
    return out


# ── load: many owners pressing Refresh at once ─────────────────────

async def _load(ctx, w, vw, load: list[str], made_on_of) -> None:
    ctx.rec.stage = "sync"
    if not load:
        for c in (SYNC_LOAD, SYNC_COALESCED, SYNC_BUDGET):
            ctx.skip(c, "no load Creators")
        return
    for aid in load:
        await made_on_of(aid, K_LOAD, "Made on OF load")
    c0 = _of_mark(ctx)
    rng = w.rng("scenario:vault-refresh:sync")
    plan = [(load[i % len(load)], rng.uniform(0, SYNC_JITTER_S)) for i in range(max(ctx.users, len(load) * 5))]
    clients = [ctx.owner.share(limits=2) for _ in plan]

    async def press(http, aid: str, delay: float):
        await asyncio.sleep(delay)
        r = await http.post(f"{SYNC_PATH}?account_id={aid}", timeout=SYNC_TIMEOUT_S)
        try:
            body = r.json()
        except ValueError:
            body = r.text[:200]
        return aid, r.status_code, body

    try:
        res = await asyncio.gather(*(press(h, a, d) for h, (a, d) in zip(clients, plan)))
    finally:
        for h in clients:
            await h.aclose()
    calls = _of_calls(ctx, c0)
    presses = {a: sum(1 for x in res if x[0] == a) for a in load}
    media_pages = {a: sum(1 for c in calls if c["account"] == a and c["op"] == "media") for a in load}
    reads = {a: sum(1 for c in calls if c["account"] == a and c["op"] == "media"
                    and c["offset"] == 0) for a in load}  # one newest-first walk starts at offset zero
    con = w.sql()
    try:
        held = {a: {m: sorted(json.loads(of or "[]")) for m, of in con.execute(
            "SELECT media_id, of_folder_ids FROM vault_items WHERE account_id=? AND removed_at IS NULL", (a,))}
            for a in load}
    finally:
        con.close()
    want = {a: {m["id"]: sorted(m["folders"]) for m in vw.vault(a)["media"]} for a in load}
    bad = [x for x in res if x[1] != 200 or not isinstance(x[2], dict) or x[2].get("mirror") is not True]
    diff = {a: {"missing": len(set(want[a]) - set(held[a])), "extra": len(set(held[a]) - set(want[a])),
                "folders_off": sum(1 for m in want[a] if m in held[a] and held[a][m] != want[a][m])} for a in load}
    ctx.check(SYNC_LOAD, not bad and all(not any(d.values()) for d in diff.values()),
              presses=len(res), bad=len(bad), bad_sample=[list(x) for x in bad[:3]],
              statuses=sorted({x[1] for x in res}), diff=diff, rows={a: len(held[a]) for a in load},
              want_rows={a: len(want[a]) for a in load})
    ctx.check(SYNC_COALESCED, all(presses[a] >= 5 and reads[a] <= 2 for a in load), presses=presses, of_media_reads=reads, media_pages=media_pages)
    s = ctx.rec.summary(SYNC_ROUTE[0]).get(SYNC_ROUTE[1])
    if not s:
        ctx.skip(SYNC_BUDGET, "no samples")
    else:
        ctx.check(SYNC_BUDGET, s["p95_ms"] <= SYNC_P95_MS, budget=True, p95=s["p95_ms"], n=s["n"], budget_ms=SYNC_P95_MS)
        ctx.metric("p95_vs_last_green", {SYNC_ROUTE[1]: s["p95_ms"]})
        ctx.metric("p95_vs_last_green_n", {SYNC_ROUTE[1]: s["n"]})
    ctx.metric("load", {"creators": len(load), "users": ctx.users, "presses": presses, "of_media_reads": reads, "media_pages": media_pages,
                        "of_calls": len(calls), "new_per_creator": K_LOAD})
