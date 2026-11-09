"""Durable vault thumbs: the picker's tiles (`/admin/vault-ai/thumb?account_id&media_id`, vault_stills' permanent
per-media store) under a collected vault, as the background collector leaves it.

World: `flat_agency`, vault_thumbs_creators Creators (3 / 6 / 10), real OFClient sessions against lib/of_wire.py
(`OF_WIRE`) + lib/vault_wire.py (vault_thumbs_items media, 6 folders; `ip_bound`: every url signed for the egress
that listed it, as OF's `AWS:SourceIp`; `mp4`: videos carry a playable 240p clip), the mirror seeded by SQL as a finished
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
  stale IP  still on B, STALE_VIDS of its videos' mirror urls signed for A (what A's listing left: the AE bug of
            2026-11-06). Control: /img of an A-signed url without media_id is denied through B. Then each video's
            12 /img/scrub frames + its poster (/img), all with the A-signed url + media_id, at once: all 200
            (frames image/jpeg, poster the CDN's bytes), exactly 1 /vault/media/{id} per video and through B,
            every CDN call through B with at most one 403 per file, the mirror row re-signed for B.
                                                                     proxy_change_previews_resign.
UI (small, not --no-ui): one more Creator no HTTP phase touched. The owner's Messages Pro Vault picker on it:
open 1 cold (`vault-thumbs-trigger` as the dialog opens, `vault-thumbs-cold-settled`), open 2 in a fresh browser
(`vault-thumbs-settled`: tiles from the relay's disk, 0 CDN calls), a phone open with touch
(`phone-vault-thumbs-settled`, 0 CDN). Side effects: thumbs on disk, /cache/summary `complete`.
Then the Creator's video urls in the mirror are signed for a proxy it left (OLD_EGRESS); a fresh browser opens the
picker and hovers a video tile (`vault-hover-trigger`, then `vault-hover-frames-a` / `-b` a second apart: frames
cycling): every /img/scrub 200, >= 2 frame indices shown, the stale url re-signed by id (>= 1 by-id read, the
exact count is the HTTP phase's: a thumb re-fetch may add one; the CDN's 403 then 200).                                                ui_hover_scrub_after_proxy_change.
Gifs (42 UI Creator items are gifs: OF's .mp4 in `files.full`): a fresh browser opens the picker; up to four
on-screen gif tiles loop their clips (src on, playing, time moving a second apart, painted), those below the fold have
no src and cost 0 CDN calls; scrolling moves the attached clips and first-row gifs that left the view lose src;
prefers-reduced-motion: an on-screen gif has no src until hovered, then plays.   ui_gif_tiles_loop_while_on_screen.
Its ⓘ Media details loops the clip inline.                                         ui_gif_details_loops_inline.
Each fetched gif clip crosses the CDN once in the whole UI section (cold, second, phone opens, the gif open, Media
details, the reduced-motion reload): one 200/206, every later <video> Range off the relay's disk (img_api's small-clip
range cache), while the relay served the clips more often than that.             ui_gif_clip_crosses_cdn_once.
The thumb opens' "0 CDN" counts thumbs only; their gif clip calls are `cdn_gif`.
Load-sensitive (measured 2026-11-05, host load 25-45, red on origin/main too: evidence/control-main/README.md):
the picker fires /cache/summary and the live /vault/media together; when the live answer lands >~2 ms first,
the first page paints via /img (24 CDN hits) before the mirror switch. Rerun at low load (the `[budget]` p95
flips with it); the HTTP phases and --no-ui runs do not depend on it.
p95: cold / warm thumb and the picker listing, vs last green (P95_VS_LAST).

Bypasses (declared): OF at its wire (lib/of_wire.py + lib/vault_wire.py), OF's CDN in the relay process
(lib/img_relay.py, `pictures`: small PNGs; the egress it checks SourceIp against is the proxy curl was handed,
sent as a header; mp4s are one 12 s ffmpeg testsrc clip, a gif's too), the A-signed mirror urls written by SQL (what A's
listing would have left), stills dirs re-pointed by env (lib/vault_collect_relay.py), the mirror
seeded by SQL (rows in the collector's shape), OF's re-sign / expiry simulated by rewriting the mirror's urls
(SQL) + the fake's gen, the dead-link tiles fetched by id without a listing (the app's persisted tiles), the review
fields + 1:1 sends of six items by SQL (what the describe pass, a grade and a chat send write).
Break-it-once: thumb-keyed-by-signed-url (only thumbs_survive_rotation goes red); thumb-no-resign
(thumbs_dead_link_refreshed_once + both stale-IP checks: cdn_resign reads by id through vault_stills);
preview-no-resign (proxy_change_previews_resign + ui_hover_scrub_after_proxy_change); vault-chatter-folder-gate-off (thumbs_restricted_chatter_404 +
vault_pro_restricted_chatter_scoped); gif-shown-as-still (client: both gif checks); gif-range-cache-off
(ui_gif_clip_crosses_cdn_once).
"""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

from slop.lib.client import Http
from slop.lib.img_relay import arm_run, picture_bytes, policy_ip
from slop.lib.vault_collect_faults import (UI_TILES, GIF_PICKER, DEAD_LINK, GIF_CDN_ONCE, GIF_DETAILS, GIF_TILES, PROXY, RESTRICTED, ROTATION,
                                           SCOPED, SECOND_OPEN, STALE_IP, UI_HOVER)
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_ui import open_vault_picker, cdn_count, cdn_calls, proxy_bind, captured
from slop.lib.vault_wire import HOST, VaultWire, path as cdn_path
from slop.seed.vault_cache import grant_folder_access
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
# The UI Creator's gifs (vault_wire `gifs`): dense first page plus more below, preserving video tiles at 4, 7, 9
# for the existing hover scrub flow. The first page has off-screen gifs in the DOM at GIF_VIEWPORT.
GIF_KS = tuple(k for k in range(45) if k not in (4, 7, 9))  # 42 gifs, with video tiles kept for hover
GIF_VIEWPORT = (1440, 700)
STALE_VIDS = 3
OLD_EGRESS = "127.0.0.1:1"  # the UI Creator's earlier proxy, long gone
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
    vw = VaultWire(fake, seed=ctx.seed, items=n_items, ip_bound=True, mp4=True)
    # With UI one more Creator, untouched by the HTTP phases: its picker opens cold.
    w.data["flat_creators"] = int(ctx.param("creators", w.size["vault_thumbs_creators"])) + (1 if ctx.app else 0)
    await ctx.build(PROFILE)
    every = [c["id"] for c in w.data["creators"]]
    if ctx.app:
        assert not vw.has_vault(every[-1]), "the UI Creator's vault was made before its gifs were set"
        vw.gifs[every[-1]] = set(GIF_KS)
    vault_week.mirror(w, vw, every)
    assets = vw.assets(every)
    cs = every[:-1] if ctx.app else every
    await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S, pictures=True)
    owner = ctx.owner
    pool = owner.share(limits=max(10, ctx.users))
    sem = asyncio.Semaphore(max(1, ctx.users))

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
        n0, v0 = await cdn_count(ctx), len(fake.vault_calls)
        res = await asyncio.gather(*(thumb(pool, a, m) for a, ms in per.items() for m in ms))
        ctx.rec.stage = None
        calls = await cdn_calls(ctx, n0)
        by_key: dict[str, list] = {}
        for c in calls:
            by_key.setdefault(c["key"], []).append(c["status"])
        return {"n": len(res), "non200": [(m, s) for _, m, s, _ in res if s != 200],
                "bad_bytes": [m for a, m, s, b in res if s == 200 and b != want_bytes(a, m)],
                "cdn": len(calls), "by_key": by_key, "by_id": [c for c in fake.vault_calls[v0:] if c["route"] == "by_id"]}

    # ── proxy A on Creator 1 before anything reaches OF (its first open goes through A) ──
    paid = cs[1 % len(cs)]
    async with proxy_bind(owner, "slop-vault-a", notes="slop: vault-thumbs", account_id=paid) as pa, \
               proxy_bind(owner, "slop-vault-b", notes="slop: vault-thumbs") as pb:
        bind_a = pa.assign_status

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
            grant_folder_access(con, rec["chatter_id"], aid, f0["id"], f0["name"], w.now)
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
        await pb.assign(paid)
        bind_b = pb.assign_status
        v1 = len(fake.vault_calls)
        r2 = (await owner.get(f"{LISTS}?view=main&limit=50&offset=0", headers=hdr)).status_code
        fresh_calls = lists_calls(v1)
        ctx.check(PROXY, bind_a == 200 and bind_b == 200 and pa.bound and pb.bound
                  and r1 == 200 and r2 == 200 and warm_calls == 0
                  and fresh_calls >= 1 and a_conn >= 1 and len(pb.connects) >= 1, bind=(bind_a, bind_b), reopen_of_calls=warm_calls,
                  bound=(pa.bound, pb.bound), after_switch_of_calls=fresh_calls,
                  proxy_a_connects=a_conn, proxy_b_connects=len(pb.connects))

        # ── stale IP: the mirror's video urls signed for A, the account on B ──
        vids = [m["id"] for m in vw.vault(paid)["media"] if m["type"] == "video"][:STALE_VIDS]
        ok, detail = await _stale_ip(ctx, w, vw, fake, pool, paid, vids, f"127.0.0.1:{pa.port}",
                                     f"127.0.0.1:{pb.port}")
        ctx.check(STALE_IP, ok, **detail)
    # ── UI: the owner's picker (two screenshots) ──
    if ctx.app:
        await _ui(ctx, w, vw, every[-1])

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


def _mirror_media(w, aid: str, mids: list[int]) -> dict[int, dict]:
    con = w.sql()
    try:
        return {m: json.loads(raw) for m, raw in con.execute(
            f"SELECT media_id, raw_json FROM vault_items WHERE account_id=? AND media_id IN ({','.join('?' * len(mids))})",
            (aid, *mids))}
    finally:
        con.close()


def _ip(u: str) -> str | None:
    q = dict(p.split("=", 1) for p in urlsplit(u).query.split("&") if "=" in p)
    return policy_ip(q["Policy"]) if q.get("Policy") else None


async def _stale_ip(ctx, w, vw, fake, http, aid: str, vids: list[int], old: str, new: str):
    """The account on `new`, its videos' mirror urls signed for `old`: (ok, detail). Docstring: `stale IP`."""
    vault_week.set_urls(w, vw, aid, vids, egress=old)
    raw = _mirror_media(w, aid, vids)
    src = {m: raw[m]["videoSources"]["240"] for m in vids}
    thumb = {m: raw[m]["files"]["thumb"]["url"] for m in vids}
    n0, v0 = await cdn_count(ctx), len(fake.vault_calls)
    # Control: the route without a media id, as before the fix; the fake must deny an `old` url through `new`.
    ctrl = (await http.get("/img", params={"u": raw[vids[0]]["files"]["full"]["url"], "account_id": aid})).status_code
    n1 = await cdn_count(ctx)

    async def frame(m: int, i: int):
        r = await http.get("/img/scrub", params={"u": src[m], "account_id": aid, "i": i, "dur": 12,
                                                 "sid": f"slop-{m}", "media_id": m}, timeout=90)
        return m, i, r.status_code, r.headers.get("content-type", "")

    async def poster(m: int):
        r = await http.get("/img", params={"u": thumb[m], "account_id": aid, "media_id": m}, timeout=90)
        return m, r.status_code, r.content

    got = await asyncio.gather(*(frame(m, i) for m in vids for i in range(12)), *(poster(m) for m in vids))
    frames = [g for g in got if len(g) == 4]
    posters = [g for g in got if len(g) == 3]
    calls = await cdn_calls(ctx, n1)
    by_id = [c for c in fake.vault_calls[v0:] if c["route"] == "by_id" and c["account"] == aid]
    files = {f"{HOST}{cdn_path(aid, m, v)}" for m in vids for v in ("thumb", "240p")}
    per_file: dict[str, list] = {}
    for c in calls:
        if c["key"] in files:
            per_file.setdefault(c["key"], []).append(c["status"])
    now = _mirror_media(w, aid, vids)
    bad_frames = [(m, i, s, ct) for m, i, s, ct in frames if s != 200 or not ct.startswith("image/jpeg")]
    bad_posters = [(m, s) for m, s, b in posters
                   if s != 200 or b != picture_bytes(f"{HOST}{cdn_path(aid, m, 'thumb')}")]
    by_id_n = {m: sum(1 for c in by_id if c["query"]["id"] == m) for m in vids}
    wrong_egress = sorted({c["egress"] for c in calls if c["egress"] != new} | {c["egress"] for c in by_id} - {new})
    bad_files = {k: v for k, v in per_file.items() if not v or v[-1] != 200 or v.count(403) > 1}
    unsigned = [m for m in vids if _ip(now[m]["files"]["thumb"]["url"]) != new]
    ok = (len(vids) == STALE_VIDS and ctrl != 200 and await cdn_count(ctx) > n0 and not bad_frames and not bad_posters
          and set(by_id_n.values()) == {1} and not wrong_egress and set(per_file) == files and not bad_files
          and any(403 in v for v in per_file.values()) and not unsigned)
    return ok, {"videos": vids, "control_no_media_id": ctrl, "frames": len(frames), "bad_frames": bad_frames[:5],
                "posters": len(posters), "bad_posters": bad_posters[:5], "by_id_per_video": by_id_n,
                "wrong_egress": wrong_egress, "cdn_per_file": per_file, "mirror_not_resigned": unsigned}


async def _ui(ctx, w, vw, aid: str) -> None:
    """Owner's Messages Pro Vault picker on the UI-only Creator: open 1 cold (trigger shot as the dialog opens),
    settled; open 2 in a fresh browser (no HTTP cache: every tile from the relay's disk), settled shot, 0 CDN;
    then a phone (touch) open, settled shot, 0 CDN. Side effects recorded: thumbs on disk, cache/summary."""
    from slop.actors import ui

    fans = [t["fan_id"] for t in w.data.get("threads", []) if t["account_id"] == aid] or \
        [f["id"] for f in w.data["fans"][aid]]
    got: dict = {}

    async def open_picker(page, shot_open: str | None, shot_settled: str) -> dict:
        await open_vault_picker(page, ctx, aid, fans[0])
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
                "img_gif_n": sum(1 for _, u in st if urlsplit(u).path == "/img" and "gif.mp4" in u),
                "img_sample": [u for _, u in st if urlsplit(u).path == "/img"][:3]}

    steps = (("cold", VIEWPORT, False, "vault-thumbs-trigger", "vault-thumbs-cold-settled"),
             ("second", VIEWPORT, False, None, "vault-thumbs-settled"),
             ("phone", PHONE, True, None, "phone-vault-thumbs-settled"))
    n_ui0 = await cdn_count(ctx)
    for name, vp, touch, s_open, s_settled in steps:
        n0 = await cdn_count(ctx)
        async with ui.owner_browser(ctx, viewport=vp, through=(THUMB, LISTS, MEDIA), touch=touch) as page:
            got[name] = {}
            async with captured(ctx, page, got[name], f"failed-vault-thumbs-{name}"):
                got[name].update(await open_picker(page, s_open, s_settled))
        # Thumbs only: an on-screen gif's clip (`/img`, a <video> Range) is counted apart in `cdn_gif`.
        calls = await cdn_calls(ctx, n0)
        got[name]["cdn"] = sum(1 for c in calls if not c["key"].endswith("/gif.mp4"))
        got[name]["cdn_gif"] = len(calls) - got[name]["cdn"]
    got["thumbs_on_disk"] = len(list((stills_dir(ctx.stack.tmp) / "thumbs" / aid).glob("*.jpg")))
    summ = (await ctx.owner.get(f"/admin/vault-ai/cache/summary?account_id={aid}")).json()
    got["summary"] = {k: summ.get(k) for k in ("count", "complete")}
    ok = all("error" not in got[n] and got[n]["thumb"] == [200] and got[n]["thumb_n"] >= 24 for n in ("cold", "second", "phone"))
    ctx.check(UI_TILES,
              ok and got["cold"]["cdn"] >= 24 and got["second"]["cdn"] == 0 and got["phone"]["cdn"] == 0
              and got["thumbs_on_disk"] >= 24 and got["summary"]["complete"] is True, **got)
    ok, detail = await _ui_hover(ctx, w, vw, aid, fans[0])
    ctx.check(UI_HOVER, ok, **detail)
    await _ui_gif(ctx, vw, aid, fans[0], n_ui0,
                  relay_gif_n=sum(got[n].get("img_gif_n", 0) for n, *_ in steps))


async def _ui_hover(ctx, w, vw, aid: str, fan: int):
    """The mirror's video urls of `aid` signed for OLD_EGRESS (it is direct now); a fresh browser hovers the first
    video tile of the picker: (ok, detail). Docstring: UI."""
    from slop.actors import ui

    first = [m["id"] for m in vw.listing(aid)[:24] if m["type"] == "video"]
    if not first:
        return False, {"error": "no video on the picker's first page"}
    vault_week.set_urls(w, vw, aid, [m["id"] for m in vw.vault(aid)["media"] if m["type"] == "video"],
                        egress=OLD_EGRESS)
    mid = first[0]
    n0, v0 = await cdn_count(ctx), len(ctx.of_wire.vault_calls)
    d: dict = {"media_id": mid}
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(THUMB, LISTS, MEDIA)) as page:
        async with captured(ctx, page, d, "failed-vault-hover"):
            await open_vault_picker(page, ctx, aid, fan)
            tile = page.get_by_role("dialog", name="Vault picker").locator(f'[data-tile-id="{mid}"]')
            await tile.wait_for(timeout=60_000)
            await page.wait_for_timeout(1500)  # the mirror's page settles (docstring: load-sensitive)
            await tile.hover(timeout=30_000)
            d["trigger"] = await ui.shot(ctx, page, "vault-hover-trigger")
            t0 = time.time()
            scrub = lambda: [(s, u) for s, u in page.slop["statuses"] if urlsplit(u).path == "/img/scrub"]  # noqa: E731
            while time.time() - t0 < 60 and len(scrub()) < 12:
                await asyncio.sleep(0.2)
            await page.wait_for_timeout(800)
            d["frames_a"] = await ui.shot(ctx, page, "vault-hover-frames-a")
            await page.wait_for_timeout(1000)
            d["frames_b"] = await ui.shot(ctx, page, "vault-hover-frames-b")
            st = scrub()
            d["scrub_statuses"] = sorted({s for s, _ in st})
            d["scrub_n"] = len(st)
            d["scrub_media_ids"] = sorted({dict(p.split("=", 1) for p in urlsplit(u).query.split("&")
                                                if "=" in p).get("media_id") for _, u in st} - {None})
            d["frames_shown"] = await tile.evaluate(
                "t => [...t.querySelectorAll('img')].filter(i => i.src.includes('/img/scrub') && i.complete"
                " && i.naturalWidth > 0).length")

    calls = [c for c in await cdn_calls(ctx, n0) if c["key"] == f"{HOST}{cdn_path(aid, mid, '240p')}"]
    d["cdn_240p"] = [c["status"] for c in calls]
    d["by_id"] = sum(1 for c in ctx.of_wire.vault_calls[v0:] if c["route"] == "by_id" and c["query"]["id"] == mid)
    ok = ("error" not in d and d["scrub_statuses"] == [200] and d["scrub_n"] >= 12 and d["frames_shown"] >= 2
          and d["scrub_media_ids"] == [str(mid)] and d["by_id"] >= 1 and d["cdn_240p"][:1] == [403]
          and d["cdn_240p"][-1:] == [200])
    return ok, d


# One gif tile as the page sees it: inside the picker's scroller's view, and its loop <video> (VaultGifLoop).
GIF_JS = """t => {
  const v = t.querySelector('video[data-gif-loop]'), sc = t.closest('.overflow-y-auto');
  const r = t.getBoundingClientRect(), s = (sc || document.documentElement).getBoundingClientRect();
  return {in_view: r.bottom > s.top && r.top < s.bottom, video: !!v, src: v ? v.getAttribute('src') : null,
          preload: v ? v.getAttribute('preload') : null,
          paused: v ? v.paused : null, t: v ? Math.round(v.currentTime * 100) / 100 : null,
          ready: v ? v.readyState : null, opacity: v ? getComputedStyle(v).opacity : null};
}"""
VIDEO_JS = "v => ({paused: v.paused, t: Math.round(v.currentTime * 100) / 100, ready: v.readyState, src: v.getAttribute('src')})"


def _playing(a: dict, b: dict) -> bool:
    """Two reads of one video a second apart: it plays (not paused, time moved, painted)."""
    return bool(a.get("src")) and a["paused"] is False and b["paused"] is False and b["t"] != a["t"] \
        and b.get("opacity", "1") == "1"


async def _ui_gif(ctx, vw, aid: str, fan: int, n_ui0: int, relay_gif_n: int) -> None:
    """The owner's picker on the UI Creator's gifs (GIF_KS), desktop (GIF_VIEWPORT): up to four on-screen gif tiles
    loop their clips (src attached, playing, time moving, painted over the still) while gifs below the fold have
    no src and cost no CDN call; scrolling gives new visible gifs a slot and detaches those that left (GIF_TILES). Its ⓘ Media
    details loops the clip inline (GIF_DETAILS). Then prefers-reduced-motion: an on-screen gif has no src until
    hovered, then plays (GIF_TILES). Shots: vault-gif-trigger, -playing-a/-b (a second apart), -scrolled,
    -details-playing, -reduced-still, -reduced-hover. Side effect: the fake CDN's calls per gif clip.
    GIF_CDN_ONCE: since `n_ui0` (the UI section's first open) each clip's CDN calls are exactly one 200/206, while the
    relay answered the clips' /img more often than once each (`relay_gif_n`: the thumb opens', plus this browser's)."""
    from slop.actors import ui

    order = [m["id"] for m in vw.listing(aid)]
    gifs = [m["id"] for m in vw.listing(aid) if m["type"] == "gif"]
    key = {m: f"{HOST}{cdn_path(aid, m, 'gif')}" for m in gifs}
    d: dict = {"gifs": {m: order.index(m) for m in gifs}}
    t_ok = det_ok = False
    n0 = await cdn_count(ctx)

    async def states(dialog) -> dict:
        out = {}
        for m in gifs:
            t = dialog.locator(f'[data-tile-id="{m}"]')
            out[m] = await t.evaluate(GIF_JS) if await t.count() else None
        return out

    async def cdn_gif() -> dict:
        calls = await cdn_calls(ctx, n0)
        return {m: [c["status"] for c in calls if c["key"] == key[m]] for m in gifs}

    async with ui.owner_browser(ctx, viewport=GIF_VIEWPORT, through=(THUMB, LISTS, MEDIA)) as page:
        try:
            await open_vault_picker(page, ctx, aid, fan)
            dialog = page.get_by_role("dialog", name="Vault picker")
            await dialog.locator(f'[data-tile-id="{gifs[19]}"]').wait_for(state="attached", timeout=60_000)
            d["trigger"] = await ui.shot(ctx, page, "vault-gif-trigger")
            t0 = time.time()
            while time.time() - t0 < 30:
                st = await states(dialog)
                if sum(bool(s and s["src"] and not s["paused"] and s["t"]) for s in st.values()) >= 1:
                    break
                await asyncio.sleep(0.25)
            a = await states(dialog)
            video_a = await dialog.locator("video[src]").count()
            d["playing_a"] = await ui.shot(ctx, page, "vault-gif-playing-a")
            await page.wait_for_timeout(1000)
            b = await states(dialog)
            video_b = await dialog.locator("video[src]").count()
            d["playing_b"] = await ui.shot(ctx, page, "vault-gif-playing-b")
            d["open_a"], d["open_b"] = a, b
            seen = [m for m in gifs if a[m] and a[m]["in_view"]]
            below = [m for m in gifs if a[m] and not a[m]["in_view"]]
            d["cdn_before_scroll"] = await cdn_gif()
            open_ok = (len(seen) >= 1 and len(below) >= 1 and any(_playing(a[m], b[m]) for m in seen)
                       and all(a[m]["src"] is None and b[m]["src"] is None for m in below)
                       and all(d["cdn_before_scroll"][m] == [] for m in below))
            samples = [(a, video_a), (b, video_b)]
            # Move through the first page in steps while many gif tiles remain mounted.
            for m in (gifs[5], gifs[10], gifs[15], gifs[19]):
                await dialog.locator(f'[data-tile-id="{m}"]').scroll_into_view_if_needed(timeout=30_000)
                await page.wait_for_timeout(350)
                samples.append((await states(dialog), await dialog.locator("video[src]").count()))
            # Scroll the one below the fold into view: it attaches and plays; the first row leaves and pauses.
            if below:
                await dialog.locator(f'[data-tile-id="{below[0]}"]').scroll_into_view_if_needed(timeout=30_000)
            t0 = time.time()
            while below and time.time() - t0 < 30:
                c = await states(dialog)
                if c[below[0]]["src"] and not c[below[0]]["paused"] and c[below[0]]["t"]:
                    break
                await asyncio.sleep(0.25)
            c = await states(dialog)
            video_c = await dialog.locator("video[src]").count()
            await page.wait_for_timeout(1000)
            c2 = await states(dialog)
            video_c2 = await dialog.locator("video[src]").count()
            d["scrolled"] = await ui.shot(ctx, page, "vault-gif-scrolled")
            d["after_scroll"], d["after_scroll_b"] = c, c2
            left = [m for m in seen if not c2[m]["in_view"]]
            d["left_view"] = left
            samples.extend(((c, video_c), (c2, video_c2)))
            d["loop_samples"] = [{"picker_video_src": count,
                                  "attached": sum(bool(s and s["src"]) for s in sample.values()),
                                  "offscreen_attached": [m for m, s in sample.items() if s and s["src"] and not s["in_view"]],
                                  "unattached_preload": [m for m, s in sample.items() if s and not s["src"] and s["preload"] != "none"]}
                                 for sample, count in samples]
            cap_ok = len(gifs) >= 40 and any(s and s["src"] and s["in_view"] for sample, _ in samples
                                                  for s in sample.values()) \
                and all(x["picker_video_src"] <= 4 and x["attached"] <= 4 and not x["offscreen_attached"]
                                                and not x["unattached_preload"] for x in d["loop_samples"])
            scroll_ok = bool(below) and any(_playing(c[m], c2[m]) for m in gifs if c[m] and c2[m] and c[m]["in_view"]) and len(left) >= 1 \
                and all(c2[m]["src"] is None for m in left)
            d["img_statuses"] = sorted({s for s, u in page.slop["statuses"]
                                        if urlsplit(u).path == "/img" and "gif.mp4" in u})
            t_ok = open_ok and scroll_ok and set(d["img_statuses"]) <= {200, 206} and bool(d["img_statuses"])
            d["cap_ok"] = cap_ok
            # Media details on the gif now in view.
            tile = dialog.locator(f'[data-tile-id="{below[0] if below else gifs[0]}"]')
            await tile.get_by_label("Media details").click(timeout=30_000)
            panel = page.get_by_role("dialog", name="Media details")
            v = panel.locator("video[data-gif-loop]")
            await v.wait_for(timeout=30_000)
            t0 = time.time()
            while time.time() - t0 < 30:
                p1 = await v.evaluate(VIDEO_JS)
                if not p1["paused"] and p1["t"]:
                    break
                await asyncio.sleep(0.25)
            await page.wait_for_timeout(1000)
            p2 = await v.evaluate(VIDEO_JS)
            d["details_playing"] = await ui.shot(ctx, page, "vault-gif-details-playing")
            d["details"] = [p1, p2]
            det_ok = _playing(p1, p2) and "gif.mp4" in (p1["src"] or "")
            # prefers-reduced-motion: the still until hovered.
            await page.emulate_media(reduced_motion="reduce")
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
            dialog = await open_vault_picker(page, ctx, aid, fan, navigate=False)
            g0 = dialog.locator(f'[data-tile-id="{gifs[0]}"]')
            await g0.wait_for(timeout=60_000)
            await page.wait_for_timeout(2000)
            r0 = await g0.evaluate(GIF_JS)
            d["reduced_still"] = await ui.shot(ctx, page, "vault-gif-reduced-still")
            await g0.hover(timeout=30_000)
            t0 = time.time()
            while time.time() - t0 < 30:
                r1 = await g0.evaluate(GIF_JS)
                if r1["src"] and not r1["paused"] and r1["t"]:
                    break
                await asyncio.sleep(0.25)
            await page.wait_for_timeout(1000)
            r2 = await g0.evaluate(GIF_JS)
            d["reduced_hover"] = await ui.shot(ctx, page, "vault-gif-reduced-hover")
            d["reduced"] = [r0, r1, r2]
            d["reduced_ok"] = r0["in_view"] and r0["src"] is None and _playing(r1, r2)
            t_ok = t_ok and d["reduced_ok"]
        except Exception:  # noqa: BLE001 — a step that cannot complete is the check's FAIL
            async with captured(ctx, page, d, "failed-vault-gif"):
                raise
        d["relay_gif_img"] = sum(1 for _, u in page.slop["statuses"] if urlsplit(u).path == "/img" and "gif.mp4" in u)
    d["cdn_gif"] = await cdn_gif()
    ctx.check(GIF_TILES, t_ok and "error" not in d, **d)
    ctx.check(GIF_PICKER, d.get("cap_ok") is True and "error" not in d,
              gif_count=len(gifs), samples=d.get("loop_samples"), trigger=d.get("trigger"), settled=d.get("scrolled"))
    calls = await cdn_calls(ctx, n_ui0)
    per = {m: [[c["status"], c["range"]] for c in calls if c["key"] == key[m]] for m in gifs}
    relay_n = relay_gif_n + d["relay_gif_img"]
    fetched = [v for v in per.values() if v]
    ctx.check(GIF_CDN_ONCE, "error" not in d and len(fetched) >= 3
              and all(len(v) == 1 and v[0][0] in (200, 206) for v in fetched)
              and relay_n > len(fetched), cdn_per_gif=per, relay_gif_img=relay_n, shot=d.get("playing_b"))
    ctx.check(GIF_DETAILS, det_ok and "error" not in d, details=d.get("details"), shot=d.get("details_playing"),
              error=d.get("error"))
