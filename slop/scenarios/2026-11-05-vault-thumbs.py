"""Durable vault thumbs: the picker's tiles (`/admin/vault-ai/thumb?account_id&media_id`, vault_stills' permanent
per-media store) under a collected vault, as the background collector leaves it.

World: `flat_agency`, vault_thumbs_creators Creators (3 / 6 / 10), real OFClient sessions against lib/of_wire.py
(`OF_WIRE`) + lib/vault_wire.py (vault_thumbs_items media, 6 folders), the mirror seeded by SQL as a finished
collector run leaves it (seed/vault_week.py: vault_items + one `auto:done` run, urls fresh). OF's CDN is
lib/img_relay.py's fake (`pictures`: small PNGs a browser draws), stills dirs in the run's temp dir.
The collector is off (VAULT_COLLECT_ENABLED=0): every OF / CDN call here is the picker's.

Per Creator, `--users` tile fetches in flight:
  cold      picker open (folder list, All pages 0 + 24), then every listed tile's thumb: 200, the CDN's bytes,
            one CDN fetch per tile.
  second    the same open again.                                     thumbs_second_open_zero_cdn: 0 CDN, 200s.
  rotation  OF re-signs (fake gen bump; the mirror's urls rewritten, seed/vault_week.set_urls), same open.
                                                                     thumbs_survive_rotation: 0 CDN, 200s.
  dead link the mirror's urls of All[48:72] (never fetched) expire; each tile fetched by id (the app's
            persisted tiles), twice.                                 thumbs_dead_link_refreshed_once: first
            fetch CDN 403 then exactly 1 /vault/media/{id} then CDN 200, the mirror row re-signed; the second
            fetch costs no OF API call; both 200.
  restricted Creator 0's chatter with access to one folder (chatter_folder_access, as PUT
            /admin/chatters/{id}/folder-access writes it), signed in (POST /chatter/login): an in-folder tile
            (already on disk) 200, an outside one 404 (disk hits included), All's listing soft-denied
            (empty list), its folder's listing 200.                  thumbs_restricted_chatter_404.
  scoped    the same chatter, given the built-in Admin by the owner's Role Settings save (PUT /admin/settings/roles:
            role enforcement is on by default and the built-in Chatter role has no Vault Pro page, so its review
            routes 403 — measured 20261105T183026Z-...-59d4; every pre-enforcement login holds Admin), on Vault
            Pro's review routes and the picker's stats (pack-candidates, disputes, flags-review, flags-accuracy,
            media-stats; 3 in-folder + 3 outside items seeded as reviewed and sent, by SQL): the owner lists every
            seeded id, the chatter only in-folder ids and counts; disputes/resolve, flags-review/grade and
            pack-triage on an outside item 404 for the chatter, 200 in-folder, 200 for the owner.
                                                                     vault_pro_restricted_chatter_scoped.
  proxy     Creator 1 on proxy A (POST /admin/proxies + /assign, lib/proxy_wire.py); the folder list reopened
            twice (0 OF calls the second time), then moved to proxy B: the next open reaches OF.
                                                                     proxy_change_invalidates.
UI (small, not --no-ui): one more Creator no HTTP phase touched. The owner's Messages Pro Vault picker on it:
open 1 cold (`vault-thumbs-trigger` as the dialog opens, `vault-thumbs-cold-settled`), open 2 in a fresh browser
(`vault-thumbs-settled`: tiles from the relay's disk, 0 CDN calls), a phone open with touch
(`phone-vault-thumbs-settled`, 0 CDN). Side effects: thumbs on disk, /cache/summary `complete`.
Load-sensitive (measured 2026-11-05, host load 25-45, red on origin/main too: evidence/control-main/README.md):
the picker fires /cache/summary and the live /vault/media together; when the live answer lands >~2 ms first,
the first page paints via /img (24 CDN hits) before the mirror switch. Rerun at low load (the `[budget]` p95
flips with it); the HTTP phases and --no-ui runs do not depend on it.
p95: cold / warm thumb and the picker listing, vs last green (P95_VS_LAST).

Bypasses (declared): OF at its wire (lib/of_wire.py + lib/vault_wire.py), OF's CDN in the relay process
(lib/img_relay.py, `pictures`: small PNGs), stills dirs re-pointed by env (lib/vault_collect_relay.py), the mirror
seeded by SQL (rows in the collector's shape), OF's re-sign / expiry simulated by rewriting the mirror's urls
(SQL) + the fake's gen, the dead-link tiles fetched by id without a listing (the app's persisted tiles), the review
fields + 1:1 sends of six items by SQL (what the describe pass, a grade and a chat send write).
Break-it-once: thumb-keyed-by-signed-url (only thumbs_survive_rotation goes red); thumb-no-resign
(thumbs_dead_link_refreshed_once); vault-chatter-folder-gate-off (thumbs_restricted_chatter_404 +
vault_pro_restricted_chatter_scoped).
"""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

from slop.lib.client import Http
from slop.lib.img_relay import arm_run, picture_bytes
from slop.lib.proxy_wire import ProxyWire
from slop.lib.vault_collect_faults import DEAD_LINK, PROXY, RESTRICTED, ROTATION, SCOPED, SECOND_OPEN
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_wire import HOST, VaultWire, path as cdn_path
from slop.seed import chatters, ts, vault_week

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = "thumb-keyed-by-signed-url"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
# Widened from (1.10, 25): the small warm thumb (~130 ms p95, a disk read under 20 users at once) went 191.7 ms
# (20261105T170141Z-...-90e4) and 1179.7 ms (inside run all, ...-504e) on the same sha that read 114-133 ms
# alone, both while other stacks loaded the machine (1-min load 53). Twice flaked -> widened, per slop/README.
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20
CDN_LATENCY_S = 0.05
VIEWPORT = (1440, 900)
PHONE = (390, 844)
THUMB = "/admin/vault-ai/thumb"
LISTS = "/api/of/v2/vault/lists"
MEDIA = "/api/of/v2/vault/media"
DEAD = (48, 72)
# Vault Pro's review routes (GET, the key of their media rows) and the picker's stats, every one a chatter session
# reaches (service/permissions.py: the Vault Pro page's prefixes; media-stats is every composer's).
REVIEW_GETS = {"/admin/vault-ai/pack-candidates": ("candidates", "&category=feet"),
               "/admin/vault-ai/disputes": ("disputes", ""),
               "/admin/vault-ai/flags-review": ("items", "&limit=1000")}
ACCURACY = "/admin/vault-ai/flags-accuracy"
STATS = "/admin/vault/media-stats"
FLAGS_VERSION = 3  # service/vault_ai_vision._FLAGS_VERSION: a grade at the current prompt


def _review_fields() -> dict:
    """An item both passes answered, contradicting each other (fully_nude + a garment: a dispute, so flags-review
    lists it), tagged "feet" (a pack candidate), graded at the current prompt (flags-accuracy counts it)."""
    return {"description": "lying on her back", "explicitness": "explicit", "clothing_state": "fully_nude",
            "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "bare", "anus_vis": "not_in_frame",
            "over_vulva": "black lace thong", "tags": ["feet"],
            "_graded": {"v": FLAGS_VERSION, "corrected": [],
                        "confirmed": {"vulva_vis": "covered", "breasts_vis": "bare", "anus_vis": "not_in_frame"}}}


def seed_review(w, aid: str, mids: list[int]) -> None:
    """By SQL: the review fields on these mirror rows and one priced, bought 1:1 send each (a fan per item)."""
    con = w.sql()
    with con:
        for i, m in enumerate(mids):
            con.execute("UPDATE vault_items SET ai_fields_json=? WHERE account_id=? AND media_id=?",
                        (json.dumps(_review_fields()), aid, m))
            con.execute("INSERT INTO vault_sends(account_id, fan_id, media_id, message_id, price_cents, sent_at, "
                        "was_purchased) VALUES (?,?,?,?,?,?,1)", (aid, 7_000_000 + i, m, m * 10, 500, ts(w.now)))
    con.close()


async def grant_admin(owner, chatter_id: str) -> int:
    """The owner gives the chatter's login the built-in Admin (every page) through Role Settings' save, the role
    every pre-enforcement login holds: the roles blob read back with one assignment changed. The status."""
    emps = (await owner.get("/admin/employees")).json().get("employees") or []
    emp = next((e["id"] for e in emps if e.get("chatter_id") == chatter_id), None)
    if emp is None:
        return 0
    cfg = (await owner.get("/admin/settings/roles")).json().get("config") or {}
    cfg["assignments"] = {**(cfg.get("assignments") or {}), str(emp): "admin"}
    return (await owner.put("/admin/settings/roles", json=cfg)).status_code


async def _scoped(owner, ch, aid: str, seeded_in: list[int], seeded_out: list[int], in_all: set[int]):
    """The owner and the restricted chatter on the review routes: (ok, detail). Owner: every seeded id listed (its
    output is the ungated one). Chatter: a non-empty list within `in_all` (the Creator's in-folder ids) holding the
    seeded in-folder ids; the accuracy's graded count = its seeded items; a write on an outside item 404."""
    async def ids(http, path, key, extra=""):
        r = await http.get(f"{path}?account_id={aid}{extra}")
        rows = r.json().get(key) if r.status_code == 200 else None
        return r.status_code, None if rows is None else sorted(int(x["media_id"]) for x in rows)

    def pair(so, o, sc, c) -> tuple[bool, dict]:
        o, c = o or [], c or []
        good = (so == 200 and sc == 200 and set(seeded_in + seeded_out) <= set(o)
                and bool(c) and set(c) <= in_all and set(seeded_in) <= set(c))
        return good, {"owner": (so, len(o)), "chatter": (sc, len(c)), "leak": sorted(set(c) - in_all)[:5]}

    ok, detail = True, {}
    for path, (key, extra) in REVIEW_GETS.items():
        good, d = pair(*await ids(owner, path, key, extra), *await ids(ch, path, key, extra))
        ok &= good
        detail[path.rsplit("/", 1)[1].replace("-", "_")] = d
    ro, rc = await owner.get(f"{STATS}?account_id={aid}"), await ch.get(f"{STATS}?account_id={aid}")
    good, d = pair(ro.status_code, [int(k) for k in ro.json().get("by_media", {})] if ro.status_code == 200 else None,
                   rc.status_code, [int(k) for k in rc.json().get("by_media", {})] if rc.status_code == 200 else None)
    ok &= good
    detail["media_stats"] = d
    ao, ac = await owner.get(f"{ACCURACY}?account_id={aid}"), await ch.get(f"{ACCURACY}?account_id={aid}")
    graded = (ao.json().get("graded_items") if ao.status_code == 200 else None,
              ac.json().get("graded_items") if ac.status_code == 200 else None)
    ok &= graded == (len(seeded_in) + len(seeded_out), len(seeded_in))
    detail["accuracy_graded"] = graded
    posts = (("resolve", "/admin/vault-ai/disputes/resolve",
              lambda m: {"account_id": aid, "media_id": m, "values": {"vulva_vis": "bare"}}),
             ("grade", "/admin/vault-ai/flags-review/grade",
              lambda m: {"account_id": aid, "media_id": m, "corrections": {}}),
             ("triage", "/admin/vault-ai/pack-triage",
              lambda m: {"account_id": aid, "category": "feet", "verdicts": [{"media_id": m, "rung": "tease"}]}))
    writes = {}
    for name, path, body in posts:
        got = ((await ch.post(path, json=body(seeded_out[0]))).status_code,
               (await ch.post(path, json=body(seeded_in[0]))).status_code,
               (await owner.post(path, json=body(seeded_out[0]))).status_code)
        ok &= got == (404, 200, 200)
        writes[name] = got
    detail["writes_chatter_out_in_owner_out"] = writes
    return ok, detail


async def run(ctx):
    w, fake = ctx.world, ctx.of_wire
    n_items = int(ctx.param("items", w.size["vault_thumbs_items"]))
    vw = VaultWire(fake, seed=ctx.seed, items=n_items)
    # With UI one more Creator, untouched by the HTTP phases: its picker opens cold.
    w.data["flat_creators"] = int(ctx.param("creators", w.size["vault_thumbs_creators"])) + (1 if ctx.app else 0)
    await ctx.build(PROFILE)
    every = [c["id"] for c in w.data["creators"]]
    vault_week.mirror(w, vw, every)
    assets = vw.assets(every)
    cs = every[:-1] if ctx.app else every
    await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S, pictures=True)
    owner = ctx.owner
    pool = owner.share(limits=max(10, ctx.users))
    sem = asyncio.Semaphore(max(1, ctx.users))

    async def cdn_since(n: int) -> list[dict]:
        return (await owner.get(f"/__slop/img/calls?since={n}")).json()["calls"]

    async def cdn_n() -> int:
        return (await owner.get("/__slop/img/stats")).json()["n"]

    async def open_picker(http, aid: str) -> list[int]:
        """The picker's reads: folder list, All page 0 + its prefetch (useVaultMedia.ts); the tiles' ids."""
        hdr = {"X-Account-Id": aid}
        await http.get(f"{LISTS}?view=main&limit=50&offset=0", headers=hdr)
        ids = []
        for off in (0, 24):
            r = await http.get(f"{MEDIA}?limit=24&offset={off}&type=all&sort=desc", headers=hdr)
            ids += [m["id"] for m in (r.json().get("list") or [])] if r.status_code == 200 else []
        return ids

    async def thumb(http, aid: str, mid: int) -> tuple[str, int, int, bytes]:
        async with sem:
            r = await http.get(f"{THUMB}?account_id={aid}&media_id={mid}")
            return aid, mid, r.status_code, r.content

    def want_bytes(aid: str, mid: int) -> bytes:
        key = f"{HOST}{cdn_path(aid, mid, 'thumb')}"
        return picture_bytes(key)

    async def tiles(stage: str, per: dict[str, list[int]]) -> dict:
        ctx.rec.stage = stage
        n0, v0 = await cdn_n(), len(fake.vault_calls)
        res = await asyncio.gather(*(thumb(pool, a, m) for a, ms in per.items() for m in ms))
        ctx.rec.stage = None
        calls = await cdn_since(n0)
        by_key: dict[str, list] = {}
        for c in calls:
            by_key.setdefault(c["key"], []).append(c["status"])
        return {"n": len(res), "non200": [(m, s) for _, m, s, _ in res if s != 200],
                "bad_bytes": [m for a, m, s, b in res if s == 200 and b != want_bytes(a, m)],
                "cdn": len(calls), "by_key": by_key, "by_id": [c for c in fake.vault_calls[v0:] if c["route"] == "by_id"]}

    # ── proxy A on Creator 1 before anything reaches OF (its first open goes through A) ──
    pa, pb = ProxyWire().__enter__(), ProxyWire().__enter__()
    try:
        paid = cs[1 % len(cs)]
        for label, p in (("slop-vault-a", pa), ("slop-vault-b", pb)):
            await owner.post("/admin/proxies", json={"label": label, "scheme": "socks5", "host": "127.0.0.1",
                                                     "port": p.port, "notes": "slop: vault-thumbs"})
            await asyncio.sleep(1.0)  # proxies.json writes apart (dead-proxy scenario's measured race)
        bind_a = (await owner.post("/admin/proxies/assign", json={"label": "slop-vault-a", "account_id": paid})).status_code
        await asyncio.sleep(1.0)

        # ── cold + second ──
        ctx.rec.stage = "listing"
        per = {a: await open_picker(pool, a) for a in cs}
        ctx.rec.stage = None
        cold = await tiles("cold", per)
        dup = {k: v for k, v in cold["by_key"].items() if len(v) != 1}
        want_keys = {f"{HOST}{cdn_path(a, m, 'thumb')}" for a, ms in per.items() for m in ms}
        cold_ok = (not cold["non200"] and not cold["bad_bytes"] and not dup and set(cold["by_key"]) == want_keys)
        ctx.note(f"cold: {cold['n']} tiles, {cold['cdn']} CDN calls, ok={cold_ok}")
        second = await tiles("warm", per)
        ctx.check(SECOND_OPEN, cold_ok and second["cdn"] == 0 and not second["non200"] and not second["bad_bytes"],
                  tiles=second["n"], cdn=second["cdn"], non200=second["non200"][:5], cold_ok=cold_ok,
                  cold_cdn=cold["cdn"], cold_dup=list(dup)[:3], cold_non200=cold["non200"][:5])

        # ── rotation ──
        for a in cs:
            vw.rotate(a)
            vault_week.set_urls(w, vw, a, [m["id"] for m in vw.vault(a)["media"]], gen=vw.gen[a])
        rot = await tiles("warm", per)
        ctx.check(ROTATION, rot["cdn"] == 0 and not rot["non200"] and not rot["bad_bytes"], tiles=rot["n"],
                  cdn=rot["cdn"], non200=rot["non200"][:5])

        # ── dead link ──
        dead = {a: [m["id"] for m in vw.listing(a)[DEAD[0]:DEAD[1]]] for a in cs}
        for a, ms in dead.items():
            vault_week.set_urls(w, vw, a, ms, exp=vault_week.expired_exp())

        def mirror_urls() -> dict:
            con = w.sql()
            try:
                return {(a, m): u for a, ms in dead.items() for m, u in con.execute(
                    f"SELECT media_id, thumb_url FROM vault_items WHERE account_id=? AND media_id IN "
                    f"({','.join('?' * len(ms))})", (a, *ms))}
            finally:
                con.close()

        expired_urls = mirror_urls()
        first = await tiles("cold", dead)
        again = await tiles("warm", dead)
        bad = {}
        for a, ms in dead.items():
            for m in ms:
                key = f"{HOST}{cdn_path(a, m, 'thumb')}"
                ids = [c for c in first["by_id"] if c["account"] == a and c["query"]["id"] == m]
                if first["by_key"].get(key) != [403, 200] or len(ids) != 1:
                    bad[m] = {"cdn": first["by_key"].get(key), "by_id": len(ids)}
        now_urls = mirror_urls()
        stale = sum(1 for k, u in expired_urls.items() if now_urls.get(k) == u)  # the re-sign writes the mirror
        ctx.check(DEAD_LINK, not bad and not first["non200"] and not again["non200"] and not again["by_id"]
                  and not first["bad_bytes"] and stale == 0, tiles=first["n"], bad=dict(list(bad.items())[:5]),
                  non200=first["non200"][:5], second_by_id=len(again["by_id"]), second_cdn=again["cdn"],
                  mirror_rows_still_expired=stale)

        # ── restricted chatter ──
        aid = cs[0]
        f0 = vw.vault(aid)["folders"][0]
        inside = [m for m in per[aid] if f0["id"] in vw.vault(aid)["by_id"][m]["folders"]]
        outside = [m for m in per[aid] if m not in inside]
        rec = (await chatters.seed(w, owner, w.user_id, ["vaultthumbs"], account_ids=[[aid]]))[0]
        con = w.sql()
        with con:
            con.execute("INSERT INTO chatter_folder_access (chatter_id, account_id, folder_id, folder_name, created_at)"
                        " VALUES (?, ?, ?, ?, ?)", (rec["chatter_id"], aid, f0["id"], f0["name"], ts(w.now)))
        con.close()
        ch = Http(str(owner.c.base_url), ctx.rec)
        try:
            login = (await ch.post("/chatter/login", json={"username": rec["username"],
                                                            "password": rec["password"]})).status_code
            ins = [(await thumb(ch, aid, m))[2] for m in inside[:5]]
            outs = [(await thumb(ch, aid, m))[2] for m in outside[:5]]
            hdr = {"X-Account-Id": aid}
            all_r = await ch.get(f"{MEDIA}?limit=24&offset=0&type=all&sort=desc", headers=hdr)
            fol_r = await ch.get(f"{MEDIA}?limit=24&offset=0&type=all&sort=desc&list_id={f0['id']}", headers=hdr)
            all_list = all_r.json().get("list") if all_r.status_code == 200 else None
            fol_ids = [m["id"] for m in (fol_r.json().get("list") or [])] if fol_r.status_code == 200 else []
            # ── scoped: the same chatter, as Admin, on Vault Pro's review routes + the picker's stats ──
            role = await grant_admin(owner, rec["chatter_id"])
            in_all = {m for m, it in vw.vault(aid)["by_id"].items() if f0["id"] in it["folders"]}
            seed_review(w, aid, inside[:3] + outside[:3])
            scoped_ok, scoped = await _scoped(owner, ch, aid, inside[:3], outside[:3], in_all)
        finally:
            await ch.aclose()
        fol_ok = bool(fol_ids) and all(f0["id"] in vw.vault(aid)["by_id"][m]["folders"] for m in fol_ids)
        ctx.check(RESTRICTED, login == 200 and bool(ins) and set(ins) == {200} and bool(outs) and set(outs) == {404}
                  and all_list == [] and fol_ok, login=login, inside=ins, outside=outs,
                  all_status=all_r.status_code, all_len=None if all_list is None else len(all_list),
                  folder_status=fol_r.status_code, folder_items=len(fol_ids), folder_ok=fol_ok)
        ctx.check(SCOPED, scoped_ok and role == 200, role_save=role, seeded_in=inside[:3], seeded_out=outside[:3],
                  **scoped)

        # ── proxy change ──
        hdr = {"X-Account-Id": paid}

        def lists_calls(v0: int) -> int:
            return sum(1 for c in fake.vault_calls[v0:] if c["account"] == paid and c["route"] == "lists")

        v0 = len(fake.vault_calls)
        r1 = (await owner.get(f"{LISTS}?view=main&limit=50&offset=0", headers=hdr)).status_code
        warm_calls = lists_calls(v0)
        a_conn = len(pa.connects)
        bind_b = (await owner.post("/admin/proxies/assign", json={"label": "slop-vault-b", "account_id": paid})).status_code
        await asyncio.sleep(1.0)
        v1 = len(fake.vault_calls)
        r2 = (await owner.get(f"{LISTS}?view=main&limit=50&offset=0", headers=hdr)).status_code
        fresh_calls = lists_calls(v1)
        ctx.check(PROXY, bind_a == 200 and bind_b == 200 and r1 == 200 and r2 == 200 and warm_calls == 0
                  and fresh_calls >= 1 and len(pb.connects) >= 1, bind=(bind_a, bind_b), reopen_of_calls=warm_calls,
                  after_switch_of_calls=fresh_calls, proxy_a_connects=a_conn, proxy_b_connects=len(pb.connects))
    finally:
        # Back to direct egress before the wires close: a Creator left on a dead proxy makes the UI's roster
        # counts (and anything else reading OF for it) log tracebacks.
        for label in ("slop-vault-a", "slop-vault-b"):
            await owner.post(f"/admin/proxies/{label}/unbind", json={"account_id": paid})
        await asyncio.sleep(1.0)
        pa.__exit__(None, None, None)
        pb.__exit__(None, None, None)

    # ── UI: the owner's picker (two screenshots) ──
    if ctx.app:
        await _ui(ctx, w, every[-1], cdn_n)

    keys = {"cold thumb": ("cold", f"GET {THUMB}"), "warm thumb": ("warm", f"GET {THUMB}"),
            "listing media": ("listing", f"GET {MEDIA}")}
    p95, nn = {}, {}
    for k, (stage, route) in keys.items():
        s = ctx.rec.summary(stage).get(route)
        if s:
            p95[k], nn[k] = s["p95_ms"], s["n"]
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", nn)
    await pool.aclose()


async def _ui(ctx, w, aid: str, cdn_n) -> None:
    """Owner's Messages Pro Vault picker on the UI-only Creator: open 1 cold (trigger shot as the dialog opens),
    settled; open 2 in a fresh browser (no HTTP cache: every tile from the relay's disk), settled shot, 0 CDN;
    then a phone (touch) open, settled shot, 0 CDN. Side effects recorded: thumbs on disk, cache/summary."""
    from slop.actors import ui

    fans = [t["fan_id"] for t in w.data.get("threads", []) if t["account_id"] == aid] or \
        [f["id"] for f in w.data["fans"][aid]]
    got: dict = {}

    async def open_picker(page, shot_open: str | None, shot_settled: str) -> dict:
        await page.goto(f"{ctx.app}/messages-pro/{aid}/{fans[0]}", wait_until="domcontentloaded", timeout=60_000)
        vault = page.get_by_role("button", name="Vault", exact=True).first
        await vault.wait_for(timeout=60_000)
        await vault.click(timeout=60_000)
        dialog = page.get_by_role("dialog", name="Vault picker")
        await dialog.wait_for(timeout=60_000)
        if shot_open:
            got[shot_open] = await ui.shot(ctx, page, shot_open)
        t0 = time.time()
        while time.time() - t0 < 60:
            tiles = [s for s, u in page.slop["statuses"] if urlsplit(u).path in (THUMB, "/img")]
            if len(tiles) >= 24:
                break
            await asyncio.sleep(0.2)
        await page.wait_for_timeout(1000)
        got[shot_settled] = await ui.shot(ctx, page, shot_settled)
        st = page.slop["statuses"]
        return {"thumb": sorted({s for s, u in st if urlsplit(u).path == THUMB}),
                "thumb_n": sum(1 for _, u in st if urlsplit(u).path == THUMB),
                "img_n": sum(1 for _, u in st if urlsplit(u).path == "/img"),
                "img_sample": [u for _, u in st if urlsplit(u).path == "/img"][:3]}

    steps = (("cold", VIEWPORT, False, "vault-thumbs-trigger", "vault-thumbs-cold-settled"),
             ("second", VIEWPORT, False, None, "vault-thumbs-settled"),
             ("phone", PHONE, True, None, "phone-vault-thumbs-settled"))
    for name, vp, touch, s_open, s_settled in steps:
        n0 = await cdn_n()
        async with ui.owner_browser(ctx, viewport=vp, through=(THUMB, LISTS, MEDIA), touch=touch) as page:
            try:
                got[name] = await open_picker(page, s_open, s_settled)
            except Exception as e:  # noqa: BLE001 — a step that cannot complete is the check's FAIL
                got[name] = {"error": f"{type(e).__name__}: {e}"}
                await ui.shot(ctx, page, f"failed-vault-thumbs-{name}")
        got[name]["cdn"] = await cdn_n() - n0
    got["thumbs_on_disk"] = len(list((stills_dir(ctx.stack.tmp) / "thumbs" / aid).glob("*.jpg")))
    summ = (await ctx.owner.get(f"/admin/vault-ai/cache/summary?account_id={aid}")).json()
    got["summary"] = {k: summ.get(k) for k in ("count", "complete")}
    ok = all("error" not in got[n] and got[n]["thumb"] == [200] and got[n]["thumb_n"] >= 24 for n in ("cold", "second", "phone"))
    ctx.check("ui: picker tiles are /admin/vault-ai/thumb (all 200, cold fills disk, second + phone open 0 CDN)",
              ok and got["cold"]["cdn"] >= 24 and got["second"]["cdn"] == 0 and got["phone"]["cdn"] == 0
              and got["thumbs_on_disk"] >= 24 and got["summary"]["complete"] is True, **got)
