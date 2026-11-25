from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from collections import Counter
from pathlib import Path

from slop.lib.img_relay import arm_run
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_manual_collect_faults import COMPLETE, FIRST_BATCH_EARLY, NEWEST_FIRST, ONCE, STATUS_P95
from slop.lib.vault_ui import cdn_calls
from slop.lib.vault_wire import HOST, VaultWire, path as cdn_path
from slop.seed import merge_sizes

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "manual-collect-asc-first"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
SIZES = {"vault_manual_creators": (3, 6, 10), "vault_manual_items": (450, 1_500, 5_000)}
merge_sizes(SIZES)
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 30
STATUS = "GET /admin/vault-ai/collect/status"
# measured medium/200 users, 6 Creators collecting: new order 1726/1816/1963 ms vs old download-at-end 1382/1688/1845; the ceiling is the 200-user load on SQLite, not the order
BUDGET_MS = {STATUS: 2300, "GET /admin/vault-ai/items": 2400, "GET /api/of/v2/vault/media": 2600}
PAGE, PICKER_PAGE, NEWEST = 100, 24, 100
STEP = PAGE - 1
LISTS_PAGE = 50
FOLD, TOP_PAGES, BOTTOM_PAGES = 10, 5, 1
COLD_VIDEOS = 4
STORYBOARD_FRAMES = 12
CDN_LATENCY_S = 0.01
_KEY = re.compile(r"[^/]+/files/v/([^/]+)/(\d+)/(\w+)\.(?:jpg|mp4)")


def _sb_hash(uid: str, mid: int) -> str:
    return hashlib.sha1(f"{HOST}{cdn_path(uid, mid, '240p')}".encode()).hexdigest()[:20]


def _is_collect(c: dict) -> bool:
    return c["route"] == "lists" or (c["route"] == "media" and "type" not in c["query"])


def _want(folders: list[int], sizes: dict[int, int], n_items: int) -> list[tuple]:
    seq: list[tuple] = [("lists", o) for o in range(0, max(len(folders), 1), LISTS_PAGE)]
    fi = 0
    off, cov = {"desc": 0, "asc": 0}, {"desc": 0, "asc": 0}
    walked = False
    while True:
        for f in folders[fi:fi + FOLD]:
            for o in range(0, sizes[f], PAGE):
                seq.append(("folder", f, o, PAGE, "desc"))
        fi += FOLD
        for sort, k in (("desc", TOP_PAGES), ("asc", BOTTOM_PAGES)):
            for _ in range(k):
                if walked:
                    break
                seq.append((sort, off[sort], PAGE))
                cov[sort] = off[sort] + PAGE
                off[sort] += STEP
                walked = max(cov.values()) >= n_items or cov["desc"] + cov["asc"] > n_items
        if walked and fi >= len(folders):
            return seq


def _order(calls: list[dict], folders: list[int], sizes: dict[int, int], n_items: int) -> dict:
    seq = []
    for c in calls:
        q = c["query"]
        if c["route"] == "lists":
            seq.append(("lists", int(q.get("offset") or 0)))
        elif q.get("list", "all") != "all":
            seq.append(("folder", int(q["list"]), int(q.get("offset") or 0), int(q.get("limit") or 0),
                        q.get("sort")))
        else:
            seq.append((q.get("sort"), int(q.get("offset") or 0), int(q.get("limit") or 0)))
    want = _want(folders, sizes, n_items)
    why = []
    if seq != want:
        i = next((i for i, (g, w) in enumerate(zip(seq, want)) if g != w), min(len(seq), len(want)))
        why.append(f"call {i}: got {seq[i:i + 3]} want {want[i:i + 3]} ({len(seq)} calls, want {len(want)})")
    return {"ok": not why, "why": why, "seq": seq}


async def run(ctx):
    w, fake = ctx.world, ctx.of_wire
    n_items = int(ctx.param("items", w.size["vault_manual_items"]))
    vw = VaultWire(fake, seed=ctx.seed, items=n_items, mp4=True)
    w.data["flat_creators"] = int(ctx.param("creators", w.size["vault_manual_creators"]))
    await ctx.build(PROFILE)
    cs = [c["id"] for c in w.data["creators"]]
    armed = await arm_run(ctx.owner, ctx.stack.tmp, vw.assets(cs), CDN_LATENCY_S, pictures=True)
    stills = stills_dir(ctx.stack.tmp)

    cold: dict[str, list[int]] = {}
    warm_n = 0
    for a in cs:
        vids = [m for m in vw.vault(a)["media"] if m["type"] == "video"]
        cold[a] = [m["id"] for m in vids[:COLD_VIDEOS]]
        for m in vids[COLD_VIDEOS:]:
            d = stills / "storyboards" / _sb_hash(a, m["id"])
            d.mkdir(parents=True, exist_ok=True)
            for i in range(STORYBOARD_FRAMES):
                (d / f"{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
            warm_n += 1
    ctx.note(f"{len(cs)} Creators x {n_items} media; CDN {armed}; storyboards pre-warmed {warm_n}, "
             f"cold {sum(map(len, cold.values()))}")

    ctx.rec.stage = "collect"
    stop = asyncio.Event()
    n_pick = max(len(cs), ctx.users)
    pool = ctx.owner.share(limits=min(100, n_pick + 10))

    async def picker(i: int, aid: str) -> None:
        rng = random.Random(f"{ctx.seed}:manual-picker:{i}")
        hdr = {"X-Account-Id": aid}
        k = rng.randrange(1000)
        while not stop.is_set():
            k += 1
            typ = ("photo", "video")[k % 2]
            for p in (f"/api/of/v2/vault/media?limit={PICKER_PAGE}&offset={PICKER_PAGE * (k % 4)}&type={typ}"
                      f"&sort=desc",
                      f"/admin/vault-ai/items?account_id={aid}&limit=40&offset={40 * (k % 3)}&sort=newest",
                      f"/admin/vault-ai/collect/status?account_id={aid}"):
                try:
                    await pool.get(p, headers=hdr)
                except Exception:  # noqa: BLE001 — recorded by the client
                    pass
            try:
                await asyncio.wait_for(stop.wait(), rng.uniform(1, 3))
            except asyncio.TimeoutError:
                pass

    tasks = [asyncio.create_task(picker(i, cs[i % len(cs)])) for i in range(n_pick)]
    await asyncio.sleep(1.0)
    t_press = time.time()
    presses = await asyncio.gather(*(ctx.owner.post(f"/admin/vault-ai/collect?account_id={a}") for a in cs))
    press = {a: (r.status_code, r.json() if r.status_code == 200 else r.text[:200]) for a, r in zip(cs, presses)}
    status: dict[str, dict] = {}
    deadline = time.time() + float(ctx.param("max_s", 180 + 0.25 * n_items))
    while time.time() < deadline:
        rs = await asyncio.gather(*(ctx.owner.get(f"/admin/vault-ai/collect/status?account_id={a}") for a in cs))
        status = {a: (r.json().get("run") or {}) if r.status_code == 200 else {"http": r.status_code}
                  for a, r in zip(cs, rs)}
        if all(s.get("running") is False and s.get("status") in ("done", "error") for s in status.values()):
            break
        await asyncio.sleep(0.5)
    t_end = time.time()
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    await pool.aclose()
    ctx.rec.stage = None
    cdn = await cdn_calls(ctx)
    ctx.metric("vault_manual_collect", {"seconds": round(t_end - t_press, 1), "press": press,
                                        "wire_vault_calls": len(fake.vault_calls), "cdn_calls": len(cdn)})

    wire: dict[str, list[dict]] = {a: [] for a in cs}
    typed = Counter()
    for c in fake.vault_calls:
        if c["account"] in wire and c["t"] >= t_press:
            if _is_collect(c):
                wire[c["account"]].append(c)
            else:
                typed[c["route"]] += 1
    fetch: dict[str, list[dict]] = {a: [] for a in cs}
    for c in cdn:
        m = _KEY.fullmatch(c["key"])
        if m and m.group(1) in fetch:
            fetch[m.group(1)].append({**c, "mid": int(m.group(2)), "variant": m.group(3)})

    order_bad, early_bad, complete_bad, once_bad = {}, {}, {}, {}
    con = w.sql()
    try:
        mirror = dict(con.execute("SELECT account_id, COUNT(*) FROM vault_items WHERE removed_at IS NULL "
                                  "GROUP BY account_id").fetchall())
    finally:
        con.close()
    for a in cs:
        v = vw.vault(a)
        media = v["media"]
        created = {m["id"]: m["created"] for m in media}
        calls = sorted(wire[a], key=lambda c: c["t"])
        rail = [f["id"] for f in v["folders"] if f.get("type") == "custom" and f.get("hasMedia")]
        sizes = {f: sum(f in m["folders"] for m in media) for f in rail}
        o = _order(calls, rail, sizes, n_items)
        walk_t = [c["t"] for c in calls]
        clips = sorted((c for c in fetch[a] if c["variant"] == "240p"), key=lambda c: c["t"])
        clip_ids = [c["mid"] for c in clips]
        if walk_t and clips and clips[0]["t"] < walk_t[-1]:
            o["why"].append("a clip fetched before the walk ended")
        if clip_ids != sorted(clip_ids, key=lambda m: created[m], reverse=True):
            o["why"].append(f"clips not newest first: {clip_ids}")
        if o["why"]:
            order_bad[a] = {"why": o["why"], "seq_head": o["seq"][:10], "calls": len(o["seq"])}

        first_ok: dict[tuple[int, str], float] = {}
        for c in fetch[a]:
            if c["status"] == 200 and c["variant"] in ("thumb", "full"):
                first_ok.setdefault((c["mid"], c["variant"]), c["t"])

        def late(ids: list[int], by: float | None) -> list[tuple[int, str]]:
            return [(m, var) for m in ids for var in ("thumb", "full")
                    if by is None or first_ok.get((m, var), float("inf")) >= by]
        mcalls = [c for c in calls if c["route"] == "media"]
        f1 = rail[0] if rail else None
        i1 = next((i for i, c in enumerate(mcalls) if f1 is not None and str(c["query"].get("list")) == str(f1)
                   and int(c["query"].get("offset") or 0) == 0), None)
        first_by = mcalls[i1 + 1]["t"] if i1 is not None and i1 + 1 < len(mcalls) else None
        first_late = late([m["id"] for m in media if f1 in m["folders"]][:PAGE], first_by) if f1 else [None]
        second = next((c["t"] for c in mcalls if c["query"].get("list", "all") == "all"
                       and c["query"].get("sort") == "desc" and int(c["query"].get("offset") or 0) == STEP), None)
        new_late = late([x["id"] for x in media[:NEWEST]], second)
        if first_by is None or first_late or second is None or new_late:
            early_bad[a] = {"first_folder": f1, "first_next_call_t": first_by, "first_late": len(first_late),
                            "first_late_head": first_late[:4], "second_page_t": second, "late": len(new_late),
                            "late_head": new_late[:4]}

        s = status.get(a, {})
        thumbs = {p.name for p in (stills / "thumbs" / a).glob("*.jpg")}
        images = {p.name for p in (stills / "images" / a).glob("*.jpg")}
        want = {f"{m['id']}.jpg" for m in media}
        got = {"status": s.get("status"), "running": s.get("running"), "error": s.get("error"),
               "total_seen": s.get("total_seen"), "upserted": s.get("upserted"), "mirror": mirror.get(a, 0),
               "thumbs_missing": len(want - thumbs), "images_missing": len(want - images)}
        summ = (await ctx.owner.get(f"/admin/vault-ai/cache/summary?account_id={a}")).json()
        got.update(complete=summ.get("complete"), summary_count=summ.get("count"))
        if not (got["status"] == "done" and got["running"] is False and got["error"] is None
                and got["total_seen"] == got["upserted"] == got["mirror"] == got["summary_count"] == n_items
                and got["complete"] is True and not got["thumbs_missing"] and not got["images_missing"]):
            complete_bad[a] = got

        keys = Counter(c["key"] for c in fetch[a])
        non200 = [(c["key"], c["status"]) for c in fetch[a] if c["status"] != 200]
        want_keys = {f"{HOST}{cdn_path(a, m['id'], var)}": 1 for m in media for var in ("thumb", "full")}
        want_keys.update({f"{HOST}{cdn_path(a, mid, '240p')}": 1 for mid in cold[a]})
        diff = {k: (keys.get(k, 0), n) for k, n in {**{k: 0 for k in keys}, **want_keys}.items()
                if keys.get(k, 0) != n}
        if diff or non200:
            once_bad[a] = {"wrong_counts": len(diff), "head": list(diff.items())[:4], "non_200": non200[:4]}

    ctx.check(NEWEST_FIRST, not order_bad and all(wire.values()), creators=len(cs), bad=order_bad,
              picker_typed_calls=dict(typed))
    ctx.check(FIRST_BATCH_EARLY, not early_bad, newest=NEWEST, bad=early_bad)
    ctx.check(COMPLETE, not complete_bad and all(p[0] == 200 for p in press.values()), want=n_items,
              bad=complete_bad, press={a: p[0] for a, p in press.items()})
    ctx.check(ONCE, not once_bad, bad=once_bad, cdn_calls=len(cdn))

    summ = ctx.rec.summary("collect")
    p95 = {k: v["p95_ms"] for k, v in summ.items() if k in BUDGET_MS}
    over = {k: (p95[k], BUDGET_MS[k]) for k in p95 if p95[k] > BUDGET_MS[k]}
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", {k: summ[k]["n"] for k in p95})
    ctx.check(STATUS_P95, STATUS in p95 and not over, budget=True, p95_ms=p95, over=over,
              n={k: summ[k]["n"] for k in p95})
    (Path(ctx.out) / "vault-manual-collect.json").write_text(json.dumps({
        "t_press": t_press, "t_end": t_end, "status": status,
        "wire": {a: [{"t": c["t"], "route": c["route"], "query": c["query"]} for c in sorted(v, key=lambda c: c["t"])]
                 for a, v in wire.items()},
        "clips": {a: [(c["t"], c["mid"]) for c in fetch[a] if c["variant"] == "240p"] for a in cs}}, default=str))
