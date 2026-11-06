"""Vault Refresh: Vault Pro's Refresh shows what was made on OnlyFans since the page loaded, and the chat Vault
picker reloads itself when its top thumbnails come back broken (expired signed urls).

World: `agency_pool` (7 Creators small, 10 medium); OnlyFans' vaults are lib/vault_wire.py's (deterministic from
--seed; `N_MIRROR` media per UI mirror Creator, `N_LIVE` per picker Creator, `N_LOAD` per load Creator) and
`seed/vault_live` writes what the relay holds of them by SQL: Creators 0, 1 and the load Creators (4+) have a
collected mirror and the relay's folder list cached 2 h ago; Creators 2, 3 have no mirror and the relay's cached
page 1 of the picker's listing (fetched 2 h ago) whose thumb urls expired 1 h ago. OnlyFans is lib/of_wire.py +
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
     (DB) refetched after the open, every thumb's Policy in the future.

Load (stage `sync`, also --no-ui): K_LOAD new media in a new folder made on OnlyFans for each load Creator, then
`--users` owner sessions press Refresh at once (POST /admin/vault-ai/sync, round-robin over the load Creators, a
seeded 0-SYNC_JITTER_S start). SYNC_LOAD: every POST 200 with mirror; each load Creator's live mirror == OF's media,
id for id, with OF's folder membership. SYNC_COALESCED: per load Creator, OF media reads < presses. Budget: p95 POST
/admin/vault-ai/sync <= SYNC_P95_MS, and vs the last green run.

Bypasses (declared): the mirror, the relay's cached listings and the run row are SQL (no Collect ran); OnlyFans
is lib/of_wire.py + lib/vault_wire.py (each vault call waits vault_live.LATENCY_S, a guess; the listing signs its
thumbs per answer) and its CDN a fake in the relay process (lib/img_relay.py: PNGs, CDN_LATENCY_S, a guess); "made on
OnlyFans" is the wire's state changed (VaultWire.add). The Creator is
pre-picked in localStorage (`vault.accountId`, a returning owner) and Vault Pro's tours marked seen. Only
/api/of/v2/vault/lists and /media are let through in the browser; every other /api/of/ read stays held. The picker's
invalidate is held in the page for the trigger screenshot (milliseconds otherwise). The load's sessions share one
owner login (`ctx.owner.share`).
Break-it-once: vault-refresh-cache-only (FAULT, client: the pre-fix Refresh; REFRESH_FOLDER, REFRESH_MEDIA,
REFRESH_WIRE), vault-refresh-fail-silent (client: a failed sync reads as ok; REFRESH_FAIL_SHOWN),
vault-thumbs-no-auto-refresh (client; THUMBS_RELOAD), vault-sync-no-coalesce (relay; SYNC_COALESCED; run with
--no-ui).
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import arm_run, policy_exp
from slop.lib.vault_wire import HOST, VaultWire, path as cdn_path
from slop.lib.vault_refresh_faults import (REFRESH_FAIL_SHOWN, REFRESH_FOLDER, REFRESH_MEDIA, REFRESH_WIRE,
                                           SYNC_COALESCED, SYNC_LOAD, THUMBS_RELOAD)
from slop.seed import of_sessions, vault_live

PROFILE = "agency_pool"
UI = True
OF_WIRE = True  # the vault's OnlyFans reads go to lib/of_wire.py through the relay's real OFClient
# lib/vault_collect_relay.py: the vault still stores in the run's temp dir; the background collector stays off (it
# would walk these vaults and change the mirror under the checks).
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
FAULT = "vault-refresh-cache-only"
N_MIRROR = 40          # media per UI mirror Creator
N_LIVE = 40            # media per picker Creator (page 1 = 24 cached, page 2 live)
N_LOAD = 200           # media per load Creator before the change
K_NEW = 5              # media made on OF during a UI refresh
K_LOAD = 150           # media made on OF per load Creator: a sync reads 2 pages new + 1 page known
TOP = 6                # the picker's top tiles checked (two rows on a phone)
CDN_LATENCY_S = 0.05
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
DESKTOP, PHONE = (1440, 900), (390, 844)
WAIT_MS = 120_000
SETTLE_MS = 25_000
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")


def _of_mark(ctx) -> int:
    with ctx.of_wire.lock:
        return len(ctx.of_wire.vault_calls)


def _of_calls(ctx, since: int = 0) -> list[dict]:
    """OnlyFans' vault listing calls since `since` (vault_wire's record), in arrival order: {account, op, status,
    offset, sort, list}."""
    with ctx.of_wire.lock:
        calls = list(ctx.of_wire.vault_calls[since:])
    return [{"account": c["account"], "op": c["route"], "status": c["status"],
             "offset": int(c["query"].get("offset") or 0), "sort": c["query"].get("sort"), "list": c["query"].get("list")}
            for c in calls if c["route"] in ("lists", "media")]


async def _cdn_calls(ctx, since: int = 0) -> list[dict]:
    return (await ctx.owner.get(f"/__slop/img/calls?since={since}")).json()["calls"]


def _exp(url: str) -> float:
    q = parse_qs(urlsplit(url).query)
    return policy_exp(q["Policy"][0])


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    mirror_ui, live_ui, load = aids[:2], aids[2:4], aids[4:]
    n = {**{a: N_MIRROR for a in mirror_ui}, **{a: N_LIVE for a in live_ui}, **{a: N_LOAD for a in load}}
    of_sessions.seed(w, creators)  # a real OFClient per Creator, talking to lib/of_wire.py
    vw = VaultWire(ctx.of_wire, seed=ctx.seed, items=N_LOAD, sizes=n)
    vault_live.seed(w, vw, [*mirror_ui, *load], live_ui)
    await arm_run(ctx.owner, ctx.stack.tmp, vw.assets(aids), CDN_LATENCY_S, pictures=True)

    async def made_on_of(aid: str, k: int, name: str):
        folder, news = vw.add(aid, name, k)
        await arm_run(ctx.owner, ctx.stack.tmp, vw.assets(aids), CDN_LATENCY_S, pictures=True)
        return folder, news

    ctx.rec.stage = "ui"
    if ctx.app is None:
        for c in (REFRESH_FOLDER, REFRESH_MEDIA, REFRESH_WIRE, REFRESH_FAIL_SHOWN, THUMBS_RELOAD):
            ctx.skip(c, "--no-ui")
    else:
        a = [await _refresh_ui(ctx, w, vw, aid, dev, made_on_of)
             for aid, dev in zip(mirror_ui, ("desktop", "phone"))]
        _check_refresh(ctx, w, a)
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
        with recorded(page, "POST", SYNC_PATH) as sent:
            try:
                await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
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
            except Exception as e:  # noqa: BLE001 — the check reports it
                got["error"] = f"{type(e).__name__}: {e}"[:600]
                try:
                    got["failed_shot"] = await ui.shot(ctx, page, f"failed-vault-refresh-{dev}")
                except Exception:  # noqa: BLE001
                    pass
            got["sent"] = [{"url": s["url"], "status": s["status"]} for s in sent]
        try:  # its own step: a Refresh that failed above still has to say so here
            got["fail"] = await _refresh_fails(ctx, page, aid, dev, tiles)
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["fail"] = {"error": f"{type(e).__name__}: {e}"[:600]}
        got["held_of_reads"] = len(page.slop["held_of_reads"])
    con = w.sql()
    try:
        ids = got.get("news") or []
        got["db"] = {m: of for m, of, rm in con.execute(
            f"SELECT media_id, of_folder_ids, removed_at FROM vault_items WHERE account_id=? AND media_id IN "
            f"({','.join('?' * len(ids))})", (aid, *ids)) if rm is None} if ids else {}
        row = con.execute("SELECT fetched_at FROM vault_response_cache WHERE account_id=? AND query_key=?",
                          (aid, vault_live.LISTS_KEY)).fetchone()
        got["lists_cached_after_click"] = bool(row and "clicked_at" in got and datetime.strptime(
            row[0][:19], "%Y-%m-%d %H:%M:%S").timestamp() >= _utc_epoch_floor(got["clicked_at"]))
    finally:
        con.close()
    (ctx.out / f"vault-refresh-{dev}.json").write_text(json.dumps(got, indent=2, default=str))
    return got


async def _refresh_fails(ctx, page, aid: str, dev: str, tiles) -> dict:
    """OF's vault listing answers 500 (of_wire `fail`) while Refresh is pressed again: what the owner sees."""
    out: dict = {}
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
    fail_ok = ["error" not in f and f.get("note", 0) >= 1 and f.get("tiles_kept", 0) >= 1 for f in fails]
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
    page1 = vw.listing(aid)[:vault_live.PICKER_PAGE]
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
            try:
                await page.goto(f"{ctx.app}/messages-pro/{aid}/{fan}", wait_until="domcontentloaded",
                                timeout=WAIT_MS)
                vault = page.get_by_role("button", name="Vault", exact=True).first
                await vault.click(timeout=WAIT_MS)
                await page.get_by_role("dialog", name="Vault picker").wait_for(timeout=60_000)
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
            except Exception as e:  # noqa: BLE001 — the check reports it
                got["error"] = f"{type(e).__name__}: {e}"[:600]
                release.set()
                try:
                    got["failed_shot"] = await ui.shot(ctx, page, f"failed-picker-thumbs-{dev}")
                except Exception:  # noqa: BLE001
                    pass
            got["media_reads"] = [{"offset": parse_qs(urlsplit(r["url"]).query).get("offset"), "status": r["status"]}
                                  for r in reads]
        got["invalidates"] = len(inv)
    keys = {f"{HOST}{cdn_path(aid, m, 'thumb')}": m for m in top}
    got["cdn"] = {}
    for c in await _cdn_calls(ctx, cdn0):
        if c["key"] in keys:
            got["cdn"].setdefault(str(keys[c["key"]]), []).append(c["status"])
    con = w.sql()
    try:
        row = con.execute("SELECT response_json, fetched_at FROM vault_response_cache WHERE account_id=? AND "
                          "query_key=?", (aid, vault_live.PICKER_KEY)).fetchone()
    finally:
        con.close()
    if row:
        body = json.loads(row[0])
        fetched = datetime.strptime(row[1][:19], "%Y-%m-%d %H:%M:%S")
        got["db"] = {"fetched_after_open": fetched.timestamp() >= _utc_epoch_floor(t_open),
                     "min_exp_ahead_s": round(min(_exp(m["files"]["thumb"]["url"]) for m in body["list"])
                                              - time.time())}
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
    plan = [(load[i % len(load)], rng.uniform(0, SYNC_JITTER_S)) for i in range(ctx.users)]
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
    reads = {a: sum(1 for c in calls if c["account"] == a and c["op"] == "media") for a in load}
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
    ctx.check(SYNC_COALESCED, all(reads[a] < presses[a] for a in load), presses=presses, of_media_reads=reads)
    s = ctx.rec.summary(SYNC_ROUTE[0]).get(SYNC_ROUTE[1])
    if not s:
        ctx.skip(SYNC_BUDGET, "no samples")
    else:
        ctx.check(SYNC_BUDGET, s["p95_ms"] <= SYNC_P95_MS, p95=s["p95_ms"], n=s["n"], budget_ms=SYNC_P95_MS)
        ctx.metric("p95_vs_last_green", {SYNC_ROUTE[1]: s["p95_ms"]})
        ctx.metric("p95_vs_last_green_n", {SYNC_ROUTE[1]: s["n"]})
    ctx.metric("load", {"creators": len(load), "users": ctx.users, "presses": presses, "of_media_reads": reads,
                        "of_calls": len(calls), "new_per_creator": K_LOAD})
