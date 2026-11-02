"""Vault Pro at 20k: the vault mirror's reads, duplicate review and duplicate hide on a big vault, through the
real `/admin/vault-ai/*` routes, many owners at once.

World: `agency_inbox` (small 3 Creators, medium 10) and `seed/vault_items` (SQL, deterministic from --seed):
Creator 0 is the big vault (`--set vault_items=N`, SCALES `vault_pro_items`, clamped to COLLECT_CAP, the
most a Collect sweep mirrors, seed/vault_items.py), every other Creator a twentieth of it (at least 50). Rows as Collect sweeps +
describe + flags + harvest + sends + earlier hides leave them; about a fifth of the hashed media are planted
re-upload groups and a few flagged rows planted review suspects (seed docstring), 6 OF folders (listStates) and
3 AI folders per Creator, two finished sweep rows each.

Load (stage `read`): `--users` owner sessions (`ctx.owner.share`) take tasks off one shared list until it is
empty, 1-3 s think time after each (an owner looking at a 40-tile page before the grid loads the next):
every page (the app's PAGE, 40) of every items walk, per Creator: all newest / all oldest, each type, three
searches (a describe word, an OF-harvest term, a kind word), photo + a search, each OF folder, each AI folder;
plus per Creator 3x GET /cache/summary, 2x GET /of-folders, GET /flags-review (the modal's limit 200, all and
only_iffy). How many pages a walk has comes from the seed (SQL), never from a route's hasMore, so the load is
the same under a fault. Stage `dupes`: per Creator GET /duplicates at each strictness the modal offers
(0, 2, 4, 6; limit high enough for every set), all at once. Stage `hide`: per Creator but the UI's (Creator 1),
one POST /duplicates/hide (strictness 2) ticking up to 150 unsent copies, one keeper, two sent copies, a
media in no set and a media in a set only at strictness 6 (copy or original), from the oracle; then GET
/cache/summary again. Stage `hide-strict0`: one POST /duplicates/hide at strictness 0 for one small Creator
(Creator 0 if none has one), ticking an unsent copy that is one at 2 but not at 0 (kept out of the stage-hide
pick).

Checks (names in lib/vault_pro_faults.py): PAGING (every walk: each item exactly once, full pages + hasMore
until the last, the sort's order), FILTERS (every walk's set == SQL's), DUPES (each Creator x strictness ==
the seed's planted groups: a group's original keeps its copies that are its bytes or within the strictness on
both planted distances, never a decoy edit; no hashes are compared), HIDE (hidden_ids == the ticked unsent
copies in order; refused exactly keeper / not a duplicate / has_sends; OnlyFans got exactly those ids in chunks
of <= OF_HIDE_CHUNK; removed_at newly set on exactly those), HIDE_STRICT0 (that copy refused as
not_a_duplicate, hidden 0, removed_at unset, OnlyFans not called for that Creator), SUMMARY_BEFORE / SUMMARY_AFTER (count and last
sweep == SQL), OF_FOLDERS (== listStates counted from SQL), FLAGS (total / graded == SQL, iffy == the seed's
planted suspects, per item and in only_iffy). Non-vacuous: DUPES needs Creator 0's planted sets at 0 < 2 < 6
(strictly more, none empty), FLAGS needs Creator 0 to have planted live suspects. Budgets: GET items p95 <= 500 ms and GET duplicates p95 <= 3 s
(stages `read` / `dupes`), p95 vs the last green run (ROUTES; not GET /of-folders, see there). KNOWN_RED (open product findings): each listed check is
measured every run; a red one SKIPs with the reason and its numbers once the big vault is at least the
finding's size, a green one PASSes (a stale finding shows).

UI (small run): Creator 1 in Chromium on /growth/vault-pro, Extras > Duplicates; the modal settles on its
sets (screenshot vault-pro-dupes-trigger), Remove > Yes, remove them, until "Removed N copies"
(vault-pro-dupes-settled). UI_HIDE: the modal's set count == the API's, the ids the browser sent == the
oracle's copies at 2 in the modal's first MODAL_SETS sets, removed_at newly set and OnlyFans' hidden ids ==
those less the sent ones, no keeper.

Bypasses (declared): bulk rows are SQL (no Collect sweep, describe or flags pass ran; the hashes are planted,
not computed from thumbs). No thumb is cached, so each /duplicates call's `ensure_hashes` tries the unhashed
rows (audio + vault_items.UNHASHED_P of the rest), finds no thumb file and hashes none. OnlyFans' `PUT /vault/media/hidden`
is lib/vault_pro_relay.py (records the ids, answers success). OF is unreachable, so the grid's and the modal's
tiles answer 404 (no picture). The `--users` sessions are separate clients on one owner login (one cookie,
`ctx.owner.share`), not separate owners. The page tasks come from a shared pool, so a walk's pages are fetched
by many sessions, not one tab scrolling. The /duplicates and /hide calls wait up to DUPES_TIMEOUT_S per request
(the browser's fetch has no 30 s cap either). Every /api/of/ read stays held in the browser (ui.py), so the
folder rail lists no OF folders. Vault Pro's tours are marked seen (a returning owner). The page-overlap fault
swaps the route's endpoint (FastAPI internals), not a product attribute (lib/vault_pro_faults.py).
Break-it-once: vault-items-page-overlap (FAULT; PAGING only), vault-dupes-ignores-strictness (DUPES only); no fault
targets HIDE_STRICT0 (KNOWN_RED).
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import Counter
from urllib.parse import urlencode

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.vault_pro_faults import (DUPES, FILTERS, FLAGS, HIDE, HIDE_STRICT0, OF_FOLDERS, PAGING,
                                       SUMMARY_AFTER, SUMMARY_BEFORE, UI_HIDE)
from slop.lib.vault_pro_relay import FAKE_PATH
from slop.seed import vault_items
from slop.seed.vault_items import COLLECT_CAP, REGIONS, VIS

PROFILE = "agency_inbox"
UI = True
FAULT = "vault-items-page-overlap"
PAGE = 40                      # useVaultCache.ts PAGE
THRESHOLDS = (0, 2, 4, 6)      # VaultDuplicatesModal THRESHOLDS
MODAL_SETS = 200               # the modal's scan: GET /duplicates' default limit
DUPES_ALL_SETS = 1_000_000     # GET /duplicates' limit has no cap; more than any Creator's sets
OF_HIDE_CHUNK = 100            # vault_of_folders._OF_HIDE_CHUNK: ids per OF PUT
HIDE_T = 2
HIDE_K = 150
FLAGS_LIMIT = 200              # useFlagsReview's default
THINK_S = (1.0, 3.0)
DUPES_TIMEOUT_S = 900
SUMMARY_READS = 3              # GET /cache/summary per Creator in stage read
OF_FOLDERS_READS = 2           # GET /of-folders per Creator in stage read
PAGE_T, SUMMARY_T, OF_FOLDERS_T, FLAGS_T = "page", "summary", "of-folders", "flags"   # read task / result keys
ITEMS_PATH = "/admin/vault-ai/items"
SUMMARY_PATH = "/admin/vault-ai/cache/summary"
OF_FOLDERS_PATH = "/admin/vault-ai/of-folders"
FLAGS_PATH = "/admin/vault-ai/flags-review"
DUPES_PATH = "/admin/vault-ai/duplicates"
HIDE_PATH = "/admin/vault-ai/duplicates/hide"
ITEMS_ROUTE = ("read", f"GET {ITEMS_PATH}")
DUPES_ROUTE = ("dupes", f"GET {DUPES_PATH}")
# (stage, route) for p95 vs the last green run. Not GET /of-folders: its p95 is the big vault's 2 calls of 20
# (each parses every row's raw_json; the rest take ~10 ms), a max, not a percentile: 197 / 443 / 732 / 3508 ms on
# one world (5f40, 63f1, 5594, 5609). Its numbers stay in http.json / summary.txt.
ROUTES = (ITEMS_ROUTE, ("read", f"GET {SUMMARY_PATH}"), ("read", f"GET {FLAGS_PATH}"), DUPES_ROUTE,
          ("hide", f"POST {HIDE_PATH}"))
ITEMS_P95_MS = 500
DUPES_P95_MS = 3000
ITEMS_BUDGET = f"p95 {ITEMS_ROUTE[1]} <= {ITEMS_P95_MS} ms (stage {ITEMS_ROUTE[0]})"
DUPES_BUDGET = f"p95 {DUPES_ROUTE[1]} <= {DUPES_P95_MS} ms (stage {DUPES_ROUTE[0]})"
BUDGETS = ((ITEMS_BUDGET, ITEMS_ROUTE, ITEMS_P95_MS), (DUPES_BUDGET, DUPES_ROUTE, DUPES_P95_MS))
P95_VS_LAST = (1.5, 500)
P95_VS_LAST_MIN_N = 5
# Open product findings {check: (big-vault size from which it applies, reason)}: the check is measured every
# run; red at or above that size it SKIPs with the reason, otherwise it is an ordinary check.
KNOWN_RED: dict[str, tuple[int, str]] = {
    DUPES_BUDGET: (20_000, "open finding: service/vault_dupes.py:cluster is an all-pairs seed scan in pure Python "
                           "(O(n^2), holds the GIL in to_thread): with a 20k vault, p95 117-121 s for 40 scans at "
                           "once (10 Creators x 4 strictness; 20261101T130126Z-2026-11-01-vault-pro-20k-28ab, "
                           "20261101T130444Z-2026-11-01-vault-pro-20k-1ecd); POST /duplicates/hide re-runs it "
                           "(p95 29-36 s); 2k: green"),
    HIDE_STRICT0: (0, "open finding: service/vault_of_folders.py:hide_duplicates reads the strictness as "
                      "`int(payload.get('threshold') or DEFAULT_THRESHOLD)`, so 0 re-clusters at 2 and hides a copy "
                      "that is no duplicate at 0 (the modal's strictest setting): 1 copy at 2 only ticked -> hidden "
                      "1, removed_at set, OnlyFans PUT 1 id (small 20261101T124203Z-2026-11-01-vault-pro-20k-cdd5, "
                      "medium 20261101T130444Z-2026-11-01-vault-pro-20k-1ecd); want refused not_a_duplicate, 0 "
                      "hidden"),
}
VIEWPORT = (1440, 900)
WAIT_MS = 180_000
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")
BANDS = ((0, 0, "identical"), (1, 2, "near"), (3, 5, "similar"), (6, 8, "loose"))   # the modal's colour bands
SEARCHES = ("lingerie", "feet", "video")


def _band(d: int) -> str:
    return next((nm for lo, hi, nm in BANDS if lo <= d <= hi), "far")


# ── the truth, from SQL ─────────────────────────────────────────────

def _truth(w, aid: str) -> dict:
    con = w.sql()
    try:
        rows = con.execute(
            "SELECT media_id, kind, created_at, removed_at, search_text, description, tags, video_description, "
            "of_terms, of_folder_ids, raw_json, content_hash, send_count, ai_fields_json "
            "FROM vault_items WHERE account_id=? ORDER BY media_id", (aid,)).fetchall()
        members = con.execute("SELECT folder_id, media_id, manual_order FROM vault_folder_items WHERE account_id=?",
                              (aid,)).fetchall()
        run = con.execute("SELECT id, status, total_seen, finished_at FROM vault_cache_runs WHERE account_id=? "
                          "ORDER BY started_at DESC LIMIT 1", (aid,)).fetchone()
    finally:
        con.close()
    items = {}
    for (mid, kind, created, removed, st, desc, tags, vdesc, terms, ofids, raw, h, sends, ai) in rows:
        items[int(mid)] = {"kind": kind, "created": created, "t": int(re.sub(r"\D", "", created[:19])),
                           "removed": removed is not None,
                           "text": [(x or "").lower() for x in (st, desc, tags, vdesc, terms)],
                           "of": json.loads(ofids or "[]"), "raw": json.loads(raw or "{}"), "hash": h,
                           "sends": int(sends or 0), "ai": json.loads(ai) if ai else None}
    folders: dict[int, dict[int, int | None]] = {}
    for fid, mid, mo in members:
        folders.setdefault(int(fid), {})[int(mid)] = mo
    return {"items": items, "folders": folders,
            "run": {"id": run[0], "status": run[1], "total_seen": run[2], "finished_at": run[3]}}


def _walks(aid: str, t: dict, meta: dict) -> list[dict]:
    """Every items walk for a Creator: params, the SQL set in the sort's order, and its sort key (ties in it may
    come in any order)."""
    items = t["items"]
    live = {m: it for m, it in items.items() if not it["removed"]}
    newest = lambda m: -items[m]["t"]  # noqa: E731
    out = []

    def add(label, params, ids, key=newest):
        ids = sorted(ids, key=key)
        out.append({"aid": aid, "label": label, "params": {"account_id": aid, **params}, "ids": ids, "key": key,
                    "pages": max(1, math.ceil(len(ids) / PAGE))})

    def match(it, q):
        return any(q in x for x in it["text"])

    add("all newest", {"type": "all", "sort": "newest"}, live)
    add("all oldest", {"type": "all", "sort": "oldest"}, live, lambda m: items[m]["t"])
    for k in ("photo", "video", "gif", "audio"):
        add(f"type {k}", {"type": k, "sort": "newest"}, [m for m, it in live.items() if it["kind"] == k])
    for q in SEARCHES:
        add(f"search {q}", {"type": "all", "sort": "newest", "query": q}, [m for m, it in live.items() if match(it, q)])
    add("photo + search beach", {"type": "photo", "sort": "newest", "query": "beach"},
        [m for m, it in live.items() if it["kind"] == "photo" and match(it, "beach")])
    for f in meta["of_folders"]:
        add(f"OF folder {f['name']}", {"type": "all", "sort": "newest", "of_folder_id": f["id"]},
            [m for m, it in live.items() if f["id"] in it["of"]])
    for f in meta["folders"]:
        mo = t["folders"].get(f["id"], {})
        add(f"AI folder {f['name']}", {"type": "all", "sort": "newest", "internal_folder_id": f["id"]},
            [m for m in mo if m in live], lambda m, mo=mo: (*_folder_key(mo.get(m)), -items[m]["t"]))
    return out


def _folder_key(mo):
    """local_items' internal-folder order: 0,1,2.. first, then unpinned, then ..-2,-1 (bucket, manual_order)."""
    return (1, 0) if mo is None else (0, mo) if mo >= 0 else (2, mo)


def _oracle(t: dict, copies: dict, threshold: int) -> dict:
    """The sets at a strictness from the seed's planted groups alone (no hash is read or compared): a group's
    original (live; the seed never hides one that has copies) keeps its live copies that are its bytes (exact,
    0 / 0) or within the strictness on both planted distances (dHash, aHash), never a decoy edit (duration off
    by > 1 s). A copy not kept is more than the strictness from its original, so d1 + d2 more from any other
    copy, and forms no set of its own (seed docstring). Clusters in the route's order: (-copies, worst), ties by
    the original's upload (created, media id)."""
    items = t["items"]
    live = {m: it for m, it in items.items() if not it["removed"]}
    kept: dict[int, list[tuple]] = {}
    for m, p in copies.items():
        if m not in live or p["decoy"]:
            continue
        if p["exact"]:
            kept.setdefault(p["original"], []).append((m, 0, 0, True))
        elif p["dd"] <= threshold and p["da"] <= threshold:
            kept.setdefault(p["original"], []).append((m, p["dd"], p["da"], False))
    clusters = [{"original": o, "dupes": sorted(ds), "worst": max(max(d[1], d[2]) for d in ds),
                 "sent": sum(1 for d in ds if live[d[0]]["sends"] > 0)} for o, ds in kept.items()]
    clusters.sort(key=lambda c: (-len(c["dupes"]), c["worst"], items[c["original"]]["t"], c["original"]))
    scanned = sum(1 for it in live.values() if it["hash"])
    return {"clusters": clusters, "scanned": scanned, "unhashed": len(live) - scanned,
            "sets": len(clusters), "removable": sum(len(c["dupes"]) for c in clusters)}


def _of_folders(t: dict) -> list[dict]:
    key = {"photo": "photosCount", "video": "videosCount", "gif": "gifsCount", "audio": "audiosCount"}
    out: dict = {}
    for it in t["items"].values():
        if it["removed"]:
            continue
        for ls in it["raw"].get("listStates") or []:
            if not ls.get("hasMedia") or ls.get("id") is None:
                continue
            f = out.setdefault(ls["id"], {"id": ls["id"], "name": ls.get("name") or "", "photosCount": 0,
                                          "videosCount": 0, "gifsCount": 0, "audiosCount": 0})
            if it["kind"] in key:
                f[key[it["kind"]]] += 1
    for f in out.values():
        f["mediaCount"] = f["photosCount"] + f["videosCount"] + f["gifsCount"] + f["audiosCount"]
    return sorted(out.values(), key=lambda f: f["name"].lower())


def _flags(t: dict, planted_iffy: set) -> dict:
    """Known flags and graded-at-this-version from SQL; iffy = the seed's planted suspects still live."""
    known = graded = 0
    ids = set()
    for m, it in t["items"].items():
        f = it["ai"]
        if it["removed"] or it["kind"] not in ("photo", "video") or not isinstance(f, dict):
            continue
        if not isinstance(f.get("underwear_visible"), bool) or any(f.get(r) not in VIS for r in REGIONS):
            continue
        known += 1
        ids.add(m)
        graded += int(((f.get("_graded") or {}).get("v") or 0) >= vault_items.FLAGS_VERSION)
    return {"total": known, "graded": graded, "ids": ids, "iffy": planted_iffy & ids}


# ── the load ────────────────────────────────────────────────────────

async def _pool(ctx, tasks: list, run_one) -> None:
    """`--users` owner sessions take tasks off one list until it is empty, thinking after each."""
    it = iter(tasks)
    clients = [ctx.owner.share(limits=2) for _ in range(ctx.users)]

    async def user(i: int, http) -> None:
        rng = ctx.world.rng(f"scenario:vault-pro:user:{i}")
        await asyncio.sleep(rng.uniform(0, THINK_S[1]))
        for task in it:
            await run_one(http, task)
            await asyncio.sleep(rng.uniform(*THINK_S))

    try:
        await asyncio.gather(*(user(i, h) for i, h in enumerate(clients)))
    finally:
        for h in clients:
            await h.aclose()


def _json(r):
    try:
        return r.json()
    except ValueError:
        return None


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    big = min(int(ctx.param("vault_items", w.size["vault_pro_items"])), COLLECT_CAP)
    sizes = {c["id"]: big if i == 0 else max(50, big // 20) for i, c in enumerate(creators)}
    t0 = time.perf_counter()
    meta = vault_items.seed(w, creators, sizes)
    seed_s = time.perf_counter() - t0
    (ctx.stack.tmp / "of-vault-pro.json").write_text("{}")
    aids = [c["id"] for c in creators]
    ui_creator = creators[1]
    ui_aid = ui_creator["id"]
    truth = {aid: _truth(w, aid) for aid in aids}

    # ── stage read: every page of every walk, plus summary / of-folders / flags-review ──
    walks = [wk for aid in aids for wk in _walks(aid, truth[aid], meta[aid])]
    tasks: list[tuple[tuple, str]] = [
        ((PAGE_T, wi, p), f"{ITEMS_PATH}?{urlencode({**wk['params'], 'limit': PAGE, 'offset': p * PAGE})}")
        for wi, wk in enumerate(walks) for p in range(wk["pages"])]
    for aid in aids:
        tasks += [((SUMMARY_T, aid), f"{SUMMARY_PATH}?account_id={aid}")] * SUMMARY_READS
        tasks += [((OF_FOLDERS_T, aid), f"{OF_FOLDERS_PATH}?account_id={aid}")] * OF_FOLDERS_READS
        tasks += [((FLAGS_T, aid, iffy), f"{FLAGS_PATH}?account_id={aid}&limit={FLAGS_LIMIT}"
                                         f"&only_iffy={'true' if iffy else 'false'}") for iffy in (False, True)]
    w.rng("scenario:vault-pro:tasks").shuffle(tasks)
    results: dict[tuple, list[tuple[int, object]]] = {}

    async def read_one(http, task) -> None:
        key, url = task
        r = await http.get(url)
        results.setdefault(key, []).append((r.status_code, _json(r)))

    ctx.rec.stage = "read"
    t_read = time.perf_counter()
    await _pool(ctx, tasks, read_one)
    read_s = time.perf_counter() - t_read

    _check_walks(ctx, walks, results)
    _check_summary(ctx, aids, truth, results)
    _check_of_folders(ctx, aids, truth, results)
    _check_flags(ctx, aids, truth, results, meta)

    oracles = {(aid, th): _oracle(truth[aid], meta[aid]["copies"], th) for aid in aids for th in THRESHOLDS}
    dupes_http = ctx.owner.share(limits=len(aids) * len(THRESHOLDS) + 2)
    try:
        # ── stage dupes: each Creator at each strictness, all at once ──
        ctx.rec.stage = "dupes"

        async def scan(aid: str, th: int):
            r = await dupes_http.get(f"{DUPES_PATH}?account_id={aid}&threshold={th}&limit={DUPES_ALL_SETS}",
                                     timeout=DUPES_TIMEOUT_S)
            return (aid, th), r.status_code, _json(r)

        t_d = time.perf_counter()
        scans = {k: (s, b) for k, s, b in await asyncio.gather(*(scan(a, th) for a in aids for th in THRESHOLDS))}
        dupes_s = time.perf_counter() - t_d
        _check_dupes(ctx, scans, oracles, aids[0])

        # ── stage hide: one ticked selection per Creator (not the UI's), from the oracle ──
        ctx.rec.stage = "hide"
        rng = w.rng("scenario:vault-pro:hide")
        plans = {aid: _hide_plan(rng, truth[aid], *(oracles[(aid, th)] for th in (0, HIDE_T, THRESHOLDS[-1])))
                 for aid in aids if aid != ui_aid}
        before = _removed(w)

        async def hide(aid: str, media_ids: list[int], threshold: int):
            r = await dupes_http.post(HIDE_PATH, json={"account_id": aid, "media_ids": media_ids,
                                                       "threshold": threshold}, timeout=DUPES_TIMEOUT_S)
            return r.status_code, _json(r)

        hidden = dict(zip(plans, await asyncio.gather(*(hide(a, p["ticked"], HIDE_T) for a, p in plans.items()))))
        after = _removed(w)
        of_hidden = await _of_hidden(ctx)
        summ2 = {}
        for aid in aids:
            r = await ctx.owner.get(f"{SUMMARY_PATH}?account_id={aid}")
            summ2[aid] = (r.status_code, _json(r))
        _check_hide(ctx, plans, hidden, before, after, of_hidden, summ2, truth)

        # ── stage hide-strict0: a copy only at 2, ticked at strictness 0 (a small Creator first) ──
        ctx.rec.stage = "hide-strict0"
        s0_aid = next((a for a in aids[2:] + aids[:1] if plans[a]["strict0"] is not None), None)
        s0 = {"aid": s0_aid}
        if s0_aid is not None:
            mid = s0["media_id"] = plans[s0_aid]["strict0"]
            s0["status"], s0["body"] = await hide(s0_aid, [mid], 0)
            s0["newly"] = sorted(_removed(w).get(s0_aid, set()) - after.get(s0_aid, set()))
            s0["of_calls"] = (await _of_hidden(ctx)).get(s0_aid, [])[len(of_hidden.get(s0_aid, [])):]
        _check_strict0(ctx, s0, big)
    finally:
        await dupes_http.aclose()

    # ── UI: Creator 1's Duplicates modal, Remove ──
    ctx.rec.stage = "ui"
    if ctx.app is None:
        ctx.skip(UI_HIDE, "--no-ui")
    else:
        await _ui(ctx, w, ui_creator, scans[(ui_aid, HIDE_T)][1], oracles[(ui_aid, HIDE_T)], truth[ui_aid])

    # ── budgets, metrics ──
    stats = {route: ctx.rec.summary(stage).get(route) for stage, route in ROUTES}
    for name, (_, route), budget in BUDGETS:
        s = stats[route]
        if not s:
            ctx.skip(name, "no samples")
            continue
        _verdict(ctx, name, s["p95_ms"] <= budget, big, budget=True, p95=s["p95_ms"], n=s["n"], budget_ms=budget)
    p95 = {route: (s["p95_ms"], s["n"]) for route, s in stats.items() if s}
    ctx.metric("p95_vs_last_green", {k: v[0] for k, v in p95.items()})
    ctx.metric("p95_vs_last_green_n", {k: v[1] for k, v in p95.items()})
    ctx.metric("load", {"vault_items": sizes, "rows": sum(sizes.values()), "seed_s": round(seed_s, 2),
                        "walks": len(walks), "pages": sum(wk["pages"] for wk in walks), "read_tasks": len(tasks),
                        "read_s": round(read_s, 1), "dupes_calls": len(scans), "dupes_s": round(dupes_s, 1),
                        "hides": len(plans), "users": ctx.users, "think_s": THINK_S})


async def _of_hidden(ctx) -> dict[str, list[list[int]]]:
    """What OnlyFans received (lib/vault_pro_relay.py): per Creator, each PUT's ids, in order."""
    out: dict[str, list[list[int]]] = {}
    for h in (await ctx.owner.get(FAKE_PATH)).json()["hidden"]:
        out.setdefault(h["account"], []).append(h["media_ids"])
    return out


# ── checks ──────────────────────────────────────────────────────────

def _verdict(ctx, name: str, ok: bool, big: int, **detail) -> None:
    """A check, or its KNOWN_RED skip when it is red and the big vault is at least the finding's size."""
    from_size, reason = KNOWN_RED.get(name, (None, ""))
    if not ok and from_size is not None and big >= from_size:
        ctx.skip(name, reason, **detail)
    else:
        ctx.check(name, ok, **detail)


def _responses(results: dict, key: tuple, n: int) -> list[tuple]:
    """The (status, body) answers to a read task, padded with (None, None) to the n it was sent: a missing
    answer is a failure, never a vacuous pass."""
    got = results.get(key, [])
    return got + [(None, None)] * (n - len(got))


def _page(st, body):
    """(ids, types, hasMore) of a 200 items page, or None when it is not one."""
    if st != 200:
        return None
    try:
        return [int(x["id"]) for x in body["list"]], [x.get("type") for x in body["list"]], body["hasMore"]
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


def _check_walks(ctx, walks, results) -> None:
    bad_paging, bad_filter = [], []
    for wi, wk in enumerate(walks):
        raw = [_responses(results, (PAGE_T, wi, p), 1)[0] for p in range(wk["pages"])]
        got = [_page(st, body) for st, body in raw]
        if any(g is None for g in got):
            st = [s for (s, _), g in zip(raw, got) if g is None]
            bad_paging.append({"walk": wk["label"], "aid": wk["aid"], "bad_pages": Counter(st).most_common(3)})
            bad_filter.append({"walk": wk["label"], "aid": wk["aid"], "error": "a page not a 200 items list"})
            continue
        ids = [m for g in got for m in g[0]]
        want = wk["ids"]
        want_set = set(want)
        foreign = [m for m in ids if m not in want_set]
        dup = [m for m, n in Counter(ids).items() if n > 1]
        sizes_ok = all(len(g[0]) == PAGE and g[2] is True for g in got[:-1]) and got[-1][2] is False \
            and len(got[-1][0]) == len(want) - PAGE * (wk["pages"] - 1)
        keys = [wk["key"](m) for m in ids] if not foreign else []
        order_ok = not foreign and keys == sorted(keys)
        if dup or not sizes_ok or not order_ok or len(ids) != len(want) or set(ids) != want_set:
            bad_paging.append({"walk": wk["label"], "aid": wk["aid"], "pages": wk["pages"], "got": len(ids),
                               "want": len(want), "twice": dup[:5], "n_twice": len(dup), "foreign": foreign[:5],
                               "sizes_ok": sizes_ok, "order_ok": order_ok,
                               "page_sizes": [len(g[0]) for g in got][:5], "more": [g[2] for g in got][-3:]})
        kind = wk["params"]["type"]
        types_ok = kind == "all" or all(x == kind for g in got for x in g[1])
        if set(ids) != want_set or not types_ok:
            bad_filter.append({"walk": wk["label"], "aid": wk["aid"], "got": len(set(ids)), "want": len(want),
                               "missing": sorted(want_set - set(ids))[:5], "extra": sorted(set(ids) - want_set)[:5],
                               "types_ok": types_ok})
    n_pages = sum(wk["pages"] for wk in walks)
    ctx.check(PAGING, not bad_paging, walks=len(walks), pages=n_pages, bad=len(bad_paging), sample=bad_paging[:5])
    ctx.check(FILTERS, not bad_filter, walks=len(walks), bad=len(bad_filter), sample=bad_filter[:5],
              sizes={wk["label"]: len(wk["ids"]) for wk in walks if wk["aid"] == walks[0]["aid"]})


def _summary_want(t: dict, minus: int = 0) -> dict:
    run = t["run"]
    return {"count": sum(1 for it in t["items"].values() if not it["removed"]) - minus,
            "last_run": {"id": run["id"], "status": run["status"], "total_seen": run["total_seen"]}}


def _summary_got(body) -> dict:
    body = body if isinstance(body, dict) else {}
    lr = body.get("last_run") if isinstance(body.get("last_run"), dict) else {}
    return {"count": body.get("count"), "last_run": {k: lr.get(k) for k in ("id", "status", "total_seen")}}


def _check_summary(ctx, aids, truth, results) -> None:
    bad, want_s = [], {}
    for aid in aids:
        want = want_s[aid] = _summary_want(truth[aid])
        for st, body in _responses(results, (SUMMARY_T, aid), SUMMARY_READS):
            if st != 200 or _summary_got(body) != want:
                bad.append({"aid": aid, "status": st, "got": _summary_got(body), "want": want})
    ctx.check(SUMMARY_BEFORE, not bad, bad=bad[:5], want={aid: s["count"] for aid, s in want_s.items()})


def _check_of_folders(ctx, aids, truth, results) -> None:
    keys = ("id", "name", "photosCount", "videosCount", "gifsCount", "audiosCount", "mediaCount")
    bad = []
    for aid in aids:
        wf = _of_folders(truth[aid])
        for st, body in _responses(results, (OF_FOLDERS_T, aid), OF_FOLDERS_READS):
            lst = (body.get("list") if isinstance(body, dict) else None) or []
            fs = [f for f in lst if isinstance(f, dict)]
            got = [{k: f.get(k) for k in keys} for f in fs]
            if st != 200 or len(fs) != len(lst) or got != wf or any(f.get("builtin") for f in fs):
                bad.append({"aid": aid, "status": st, "got": got[:3], "want": wf[:3], "n": [len(got), len(wf)]})
    ctx.check(OF_FOLDERS, not bad, bad=bad[:3])


def _flags_body(st, body):
    """{total, graded, iffy, items: [(media_id, iffy)]} of a 200 flags-review answer, or None when it is not one."""
    if st != 200:
        return None
    try:
        return {"total": body["total"], "graded": body.get("graded"), "iffy": body.get("iffy"),
                "items": [(int(i["media_id"]), bool(i.get("iffy"))) for i in body["items"]]}
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


def _check_flags(ctx, aids, truth, results, meta) -> None:
    bad, want_fl = [], {}
    for aid in aids:
        fw = _flags(truth[aid], meta[aid]["iffy"])
        want_fl[aid] = {"total": fw["total"], "graded": fw["graded"], "iffy": len(fw["iffy"])}
        all_ = _flags_body(*_responses(results, (FLAGS_T, aid, False), 1)[0])
        only = _flags_body(*_responses(results, (FLAGS_T, aid, True), 1)[0])
        sub = {"parsed": all_ is not None and only is not None}
        if sub["parsed"]:
            sub["totals"] = {k: all_[k] for k in ("total", "graded", "iffy")} == want_fl[aid]
            sub["items"] = (len(all_["items"]) == min(FLAGS_LIMIT, fw["total"])
                            and all(m in fw["ids"] and iffy == (m in fw["iffy"]) for m, iffy in all_["items"]))
            sub["only_iffy"] = (only["total"] == len(fw["iffy"]) and all(m in fw["iffy"] for m, _ in only["items"])
                                and len(only["items"]) == min(FLAGS_LIMIT, len(fw["iffy"])))
        if not all(sub.values()):
            bad.append({"aid": aid, "sub": sub, "want": want_fl[aid],
                        "got": all_ and {k: all_[k] for k in ("total", "graded", "iffy")},
                        "items": all_ and len(all_["items"]), "iffy_total": only and only["total"],
                        "iffy_items": only and len(only["items"])})
    planted = want_fl[aids[0]]["iffy"]   # non-vacuous: the big vault has live planted suspects
    ctx.check(FLAGS, not bad and planted > 0, bad=bad[:5], planted_iffy_creator0=planted, want=want_fl)


DUPES_COUNTS = ("sets", "removable", "scanned", "unhashed", "returned", "threshold")


def _scan_body(st, body):
    """([{original, dupes, worst, sent, bands_ok}], counts) of a 200 /duplicates answer, or None when it is not
    one (a set with no copies is not one)."""
    if st != 200:
        return None
    try:
        out = []
        for c in body["clusters"]:
            ds = [(int(d["media_id"]), int(d["dhash_dist"]), int(d["ahash_dist"]), bool(d["exact"]), d["band"])
                  for d in c["dupes"]]
            worst = max(max(d[1], d[2]) for d in ds)
            out.append({"original": int(c["original"]["media_id"]), "dupes": tuple(sorted(d[:4] for d in ds)),
                        "worst": c["worst"], "sent": c["sent_dupes"],
                        "bands_ok": c["band"] == _band(c["worst"]) and c["worst"] == worst
                        and all(d[4] == _band(max(d[1], d[2])) for d in ds)})
        return out, {k: body.get(k) for k in DUPES_COUNTS}
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


def _check_dupes(ctx, scans, oracles, big_aid: str) -> None:
    bad, shown = [], {}
    for (aid, th), (st, body) in scans.items():
        o = oracles[(aid, th)]
        wcounts = {"sets": o["sets"], "removable": o["removable"], "scanned": o["scanned"],
                   "unhashed": o["unhashed"], "returned": o["sets"], "threshold": th}
        shown[f"{aid}@{th}"] = [o["sets"], o["removable"]]
        want = sorted((c["original"], tuple(c["dupes"])) for c in o["clusters"])
        parsed = _scan_body(st, body)
        if parsed is None:
            bad.append({"aid": aid, "threshold": th, "status": st, "error": "not a 200 duplicates answer"})
            continue
        cl, counts = parsed
        got = sorted((c["original"], c["dupes"]) for c in cl)
        bands_ok = all(c["bands_ok"] for c in cl)
        sent_ok = sorted((c["original"], c["sent"]) for c in cl) == sorted((c["original"], c["sent"])
                                                                         for c in o["clusters"])
        keys = [(-len(c["dupes"]), c["worst"]) for c in cl]
        order_ok = keys == sorted(keys)
        if got != want or counts != wcounts or not bands_ok or not sent_ok or not order_ok:
            gs, ws = set(got), set(want)
            bad.append({"aid": aid, "threshold": th, "status": st, "counts": counts, "want": wcounts,
                        "bands_ok": bands_ok, "sent_ok": sent_ok, "order_ok": order_ok,
                        "only_got": sorted(gs - ws)[:3], "only_want": sorted(ws - gs)[:3]})
    # non-vacuous: the big vault's planted sets grow with the strictness (0 < 2 < 6), none empty
    growing = [oracles[(big_aid, th)]["sets"] for th in (0, HIDE_T, THRESHOLDS[-1])]
    nonvacuous = 0 < growing[0] < growing[1] < growing[2]
    ctx.check(DUPES, not bad and nonvacuous, scans=len(scans), bad=len(bad), sample=bad[:4],
              creator0_sets_0_2_6=growing, sets_removable=shown)


def _hide_plan(rng, t: dict, o0: dict, o2: dict, o6: dict) -> dict:
    items = t["items"]
    dupes2 = [d[0] for c in o2["clusters"] for d in c["dupes"]]
    dupes0 = {d[0] for c in o0["clusters"] for d in c["dupes"]}
    unsent = [m for m in dupes2 if items[m]["sends"] == 0]
    sent = [m for m in dupes2 if items[m]["sends"] > 0]
    strict0 = min((m for m in unsent if m not in dupes0), default=None)   # kept for stage hide-strict0
    unsent = [m for m in unsent if m != strict0]
    in2 = set(dupes2) | {c["original"] for c in o2["clusters"]}
    in6 = {d[0] for c in o6["clusters"] for d in c["dupes"]} | {c["original"] for c in o6["clusters"]}
    only6 = sorted(m for m in in6 - in2 if not items[m]["removed"])
    single = sorted(m for m, it in items.items() if it["hash"] and not it["removed"] and m not in in6)
    pick = rng.sample(unsent, min(HIDE_K, len(unsent)))
    keeper = [o2["clusters"][0]["original"]] if o2["clusters"] else []
    sent_p = rng.sample(sent, min(2, len(sent)))
    nod = rng.sample(single, min(1, len(single))) + rng.sample(only6, min(1, len(only6)))
    ticked = pick + keeper + sent_p + nod
    rng.shuffle(ticked)
    picked = set(pick)
    approved = [m for m in ticked if m in picked]
    refused = {"is_original": [m for m in ticked if m in keeper],
               "not_a_duplicate": [m for m in ticked if m in nod],
               "has_sends": [m for m in ticked if m in sent_p]}
    return {"ticked": ticked, "approved": approved, "refused": {k: v for k, v in refused.items() if v},
            "keepers": {c["original"] for c in o2["clusters"]}, "strict0": strict0}


def _removed(w) -> dict[str, set[int]]:
    con = w.sql()
    try:
        out: dict[str, set[int]] = {}
        for aid, mid in con.execute("SELECT account_id, media_id FROM vault_items WHERE removed_at IS NOT NULL"):
            out.setdefault(str(aid), set()).add(int(mid))
        return out
    finally:
        con.close()


def _check_hide(ctx, plans, hidden, before, after, of_hidden, summ2, truth) -> None:
    bad = []
    for aid, plan in plans.items():
        st, body = hidden[aid]
        body = body if isinstance(body, dict) else {}
        newly = after.get(aid, set()) - before.get(aid, set())
        chunks = of_hidden.get(aid, [])
        sent_of = [m for ids in chunks for m in ids]
        ok = (st == 200 and body.get("hidden_ids") == plan["approved"] and body.get("hidden") == len(plan["approved"])
              and body.get("refused") == plan["refused"] and newly == set(plan["approved"])
              and sent_of == plan["approved"] and all(len(ids) <= OF_HIDE_CHUNK for ids in chunks)
              and not (newly & plan["keepers"]) and "of_error" not in body)
        if not ok:
            bad.append({"aid": aid, "status": st, "hidden": body.get("hidden"), "want": len(plan["approved"]),
                        "ids_eq": body.get("hidden_ids") == plan["approved"], "refused": body.get("refused"),
                        "want_refused": plan["refused"], "newly": len(newly), "of_ids": len(sent_of),
                        "chunks": [len(ids) for ids in chunks], "keepers_hit": sorted(newly & plan["keepers"])[:3],
                        "of_error": body.get("of_error")})
    ctx.check(HIDE, not bad, creators=len(plans), ticked={a: len(p["ticked"]) for a, p in plans.items()},
              approved={a: len(p["approved"]) for a, p in plans.items()}, bad=bad[:4])
    bad_s = []
    for aid, (st, body) in summ2.items():
        want = _summary_want(truth[aid], len(plans[aid]["approved"]) if aid in plans else 0)
        sql = len(truth[aid]["items"]) - len(after.get(aid, set()))
        if st != 200 or _summary_got(body) != want or sql != want["count"]:
            bad_s.append({"aid": aid, "status": st, "got": _summary_got(body), "want": want, "sql": sql})
    ctx.check(SUMMARY_AFTER, not bad_s, bad=bad_s[:5])


def _check_strict0(ctx, s0: dict, big: int) -> None:
    """A copy only at 2 ticked at strictness 0: refused as not_a_duplicate, nothing hidden or sent to OF."""
    if s0["aid"] is None:
        ctx.check(HIDE_STRICT0, False, error="no Creator has an unsent copy at 2 that is none at 0")
        return
    body = s0["body"] if isinstance(s0["body"], dict) else {}
    mid = s0["media_id"]
    ok = (s0["status"] == 200 and body.get("hidden") == 0 and body.get("refused") == {"not_a_duplicate": [mid]}
          and not s0["newly"] and not s0["of_calls"])
    _verdict(ctx, HIDE_STRICT0, ok, big, aid=s0["aid"], media_id=mid, http=s0["status"],
             hidden=body.get("hidden"), hidden_ids=body.get("hidden_ids"), refused=body.get("refused"),
             newly_removed=s0["newly"], of_calls=s0["of_calls"])


# ── UI ──────────────────────────────────────────────────────────────

async def _ui(ctx, w, creator: dict, api_body, o2: dict, t: dict) -> None:
    aid = creator["id"]
    got: dict = {}
    before = _removed(w).get(aid, set())
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.context.add_init_script(TOURS_SEEN)
        with recorded(page, "POST", HIDE_PATH) as sent:
            try:
                await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
                await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
                await page.get_by_role("button", name=re.compile(r" extras$")).first.click(timeout=WAIT_MS)
                # enabled once the summary says the mirror holds media; click waits for that
                await page.get_by_role("button", name="Duplicates", exact=True).click(timeout=WAIT_MS)
                line = page.get_by_text(re.compile(r"^\d+ sets · \d+ copies · \d+ items scanned"))
                await line.wait_for(timeout=WAIT_MS)
                got["line"] = (await line.inner_text()).strip()
                remove = page.get_by_role("button", name=re.compile(r"^Remove \d+ cop"))
                await remove.wait_for(timeout=30_000)
                got["remove"] = (await remove.inner_text()).strip()
                await page.wait_for_timeout(500)
                got["trigger_shot"] = await ui.shot(ctx, page, "vault-pro-dupes-trigger")
                await remove.click(timeout=10_000)
                await page.get_by_role("button", name="Yes, remove them").click(timeout=10_000)
                done = page.get_by_text(re.compile(r"^Removed \d+ cop"))
                await done.wait_for(timeout=WAIT_MS)
                got["done"] = (await done.inner_text()).strip()
                await page.wait_for_timeout(1500)
                got["settled_shot"] = await ui.shot(ctx, page, "vault-pro-dupes-settled")
            except Exception as e:  # noqa: BLE001 — the check reports it
                got["error"] = f"{type(e).__name__}: {e}"[:600]
                try:
                    await ui.shot(ctx, page, "failed-vault-pro")
                except Exception:  # noqa: BLE001
                    pass
            bodies = [x["body"] or {} for x in sent]
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
    after = _removed(w).get(aid, set())
    of_ids = sorted(m for ids in (await _of_hidden(ctx)).get(aid, []) for m in ids)
    shown = o2["clusters"][:MODAL_SETS]   # oracle clusters are in the route's order
    dupes = sorted(d[0] for c in shown for d in c["dupes"])
    unsent = sorted(m for m in dupes if t["items"][m]["sends"] == 0)
    sent_ids = sorted(m for b in bodies for m in b.get("media_ids") or [])
    newly = sorted(after - before)
    api_body = api_body if isinstance(api_body, dict) else {}
    want_line = f"{api_body.get('sets')} sets · {api_body.get('removable')} copies"
    keepers = {c["original"] for c in o2["clusters"]}
    (ctx.out / "ui-hide.json").write_text(json.dumps({"ui": got, "sent": bodies, "newly_removed": newly,
                                                      "of_ids": of_ids, "want_hidden": unsent}, indent=2))
    ctx.check(UI_HIDE, "error" not in got and got.get("line", "").startswith(want_line) and sent_ids == dupes
              and newly == unsent and of_ids == unsent and not (set(newly) & keepers)
              and all(b.get("threshold") == HIDE_T and not b.get("allow_sent") for b in bodies),
              ui={k: v for k, v in got.items() if not k.endswith("_shot")}, want_line=want_line,
              sent=len(sent_ids), want_sent=len(dupes), newly=len(newly), of_ids=len(of_ids), want_hidden=len(unsent),
              keepers_hit=sorted(set(newly) & keepers)[:3], shots=[got.get("trigger_shot"), got.get("settled_shot")])
