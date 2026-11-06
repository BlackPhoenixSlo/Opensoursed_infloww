"""The vault week cache's background collector (service/vault_collect.py) under a working Agency.

World: `flat_agency`, vault_collect_creators Creators (6 / 16 / 40), each with a captured OF session (the relay's
REAL OFClient against lib/of_wire.py, `OF_WIRE`) and a vault of vault_collect_items media in 6 folders
(lib/vault_wire.py, made per Creator on first sight, so it is there the moment a session lands). OF's CDN is
lib/img_relay.py's fake, armed with every vault thumb + full (`pictures`: small PNGs), and
vault_stills' stores point into the run's temp dir. The collector runs on its own (RELAY_ENV: tick 2 s, first
tick 1 s, GAP_S 1 s, USER_QUIET_S 20 s).

Load (until every quiet Creator's walk reached auto:done, then LINGER_S more): BUSY_FRAC of the Creators are
busy: --users/2 picker users (each: the folder list, All page 0 with refresh=1 — the picker's refresh, so every
open reaches OF on the user lane — and one scroll / folder / type page, then 3-7 s think), --users/4 chatters
(actors/chatter.py: inbox head, thread, mark-read, a reply through OF) and fan DMs (actors/fan_dm.serial,
0.5 frame/s per Creator) on those Creators only. The other Creators are quiet: no traffic at all, so every
OF vault call and CDN fetch they get is the collector's. Mid-walk (a quiet Creator in auto:all:<K>, K > 0)
the load pauses, the relay is stopped (SIGTERM) and started again, the CDN re-armed, the load resumed.

Checks (lib/vault_collect_faults.py names):
  collect_pacing         per quiet Creator, consecutive OF vault calls >= GAP_S - 50 ms apart.
  collect_one_at_a_time  per-Creator collector spans (its OF vault calls + its CDN fetches, split on 20 s
                         gaps) never overlap another Creator's.
  collect_skips_busy     no collector span on a busy Creator starts within USER_QUIET_S after a user picker
                         refresh on it (only refreshes since the relay last started: the product keeps that
                         clock in RAM; exempt past MAX_SKIP_S).
  collect_fills_mirror   per quiet Creator: latest auto run done/auto:done, vault_items == the fake's count,
                         /admin/vault-ai/cache/summary complete + count, the picker's hot keys in vault_response_cache.
  collect_thumbs_warm    per quiet Creator: the thumbs store holds exactly the newest 100 media; no image /
                         poster / storyboard file; every CDN fetch a thumb, every one 200.
  collect_resume         the restarted relay's first walk page for the stopped Creator is the persisted cursor,
                         no walk offset fetched twice but that one, the walk reaches auto:done, mirror complete.
  user_read_p95          picker + chat reads during load: p95 <= BUDGET_MS each; stock p95 vs last green
                         (P95_VS_LAST) on the same keys.
User vs collector on a busy Creator: an OF vault call inside one of the harness's own picker requests to that
Creator (+-50 ms) is the user's; the rest the collector's.

Bypasses (declared): OF at its wire (lib/of_wire.py + lib/vault_wire.py), OF's CDN in the relay process
(lib/img_relay.py, `pictures`: small PNGs), vault_stills / storyboard dirs re-pointed by env
(lib/vault_collect_relay.py), the collector's env knobs shortened (RELAY_ENV; USER_QUIET_S 20 s, not 120 s, so
a run stays minutes long), picker users are httpx clients reading the picker's routes (no browser).
Break-it-once: collect-unpaced (GAP_S 0: only collect_pacing goes red).
"""
from __future__ import annotations

import asyncio
import itertools
import json
import random
import time
from pathlib import Path

from slop.actors import fan_dm
from slop.actors.chatter import Chatters
from slop.lib.img_relay import arm_run
from slop.lib.vault_collect_faults import (FILLS_MIRROR, ONE_AT_A_TIME, PACING, RESUME, SKIPS_BUSY, THUMBS_WARM,
                                           USER_P95)
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_wire import VaultWire, owner_of

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "collect-unpaced"
GAP_S, QUIET_S, MAX_SKIP_S = 1.0, 20.0, 1800.0
RELAY_ENV = {"VAULT_COLLECT_TICK_S": "2", "VAULT_COLLECT_FIRST_AFTER_S": "1", "VAULT_COLLECT_GAP_S": str(GAP_S),
             "VAULT_COLLECT_USER_QUIET_S": str(QUIET_S), "VAULT_COLLECT_MAX_SKIP_S": str(MAX_SKIP_S),
             "SLOP_VAULT_STILLS": "1"}
P95_VS_LAST = (1.10, 25)  # +10%, and 25 ms slack so a 30 ms read does not flap
P95_VS_LAST_MIN_N = 30
BUDGET_MS = {"GET /api/of/v2/vault/lists": 1500, "GET /api/of/v2/vault/media": 1500,
             "GET /admin/chats/recent": 800, "GET /admin/messages/:id/:id": 800}  # guesses until measured
BUSY_FRAC = 0.6
CDN_LATENCY_S = 0.05
LINGER_S = 15.0
SPAN_GAP_S = 20.0
HOT_THUMBS = 100
TOL_S = 0.05


def _q(path: str, **kv) -> str:
    return path + "?" + "&".join(f"{k}={v}" for k, v in kv.items() if v is not None)


async def run(ctx):
    w, fake = ctx.world, ctx.of_wire
    n_items = int(ctx.param("items", w.size["vault_collect_items"]))
    vw = VaultWire(fake, seed=ctx.seed, items=n_items)
    w.data["flat_creators"] = int(ctx.param("creators", w.size["vault_collect_creators"]))
    t_run0 = time.time()
    await ctx.build(PROFILE)
    cs = [c["id"] for c in w.data["creators"]]
    order = cs[:]
    w.rng("vault_collect").shuffle(order)
    busy = sorted(order[:round(len(cs) * BUSY_FRAC)])
    quiet = sorted(set(cs) - set(busy))
    assets = vw.assets(cs)
    armed = await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S, pictures=True)
    ctx.note(f"{len(cs)} Creators x {n_items} media; busy {len(busy)}, quiet {len(quiet)}; CDN {armed}")
    stills = stills_dir(ctx.stack.tmp)

    def runs(where: str = "1=1", args=()) -> list[dict]:
        con = w.sql()
        try:
            con.row_factory = lambda c, r: {d[0]: v for d, v in zip(c.description, r)}
            return con.execute(f"SELECT * FROM vault_cache_runs WHERE {where} ORDER BY id", args).fetchall()
        finally:
            con.close()

    def latest_auto(aid: str) -> dict | None:
        rs = runs("account_id=? AND phase LIKE 'auto:%'", (aid,))
        return rs[-1] if rs else None

    # ── load ──
    picks: list[dict] = []   # every picker request: aid, kind, t0, t1, status, refresh
    dm_ids = itertools.count(fan_dm.INJECT_ID_BASE)
    fans = w.data["fans"]
    ctx.rec.stage = "load"

    async def picker(i: int, http, aid: str, stop: asyncio.Event) -> None:
        rng = random.Random(f"{ctx.seed}:picker:{i}")
        fids = [f["id"] for f in vw.vault(aid)["folders"]]
        hdr = {"X-Account-Id": aid}
        k = rng.randrange(1000)
        while not stop.is_set():
            k += 1
            extra = (dict(offset=24 * (1 + k % 12), type="all") if k % 3 == 0 else
                     dict(offset=0, type="all", list_id=fids[k % len(fids)]) if k % 3 == 1 else
                     dict(offset=0, type=("photo", "video")[k % 2]))
            reqs = [("lists", _q("/api/of/v2/vault/lists", view="main", limit=50, offset=0), False),
                    ("media", _q("/api/of/v2/vault/media", limit=24, offset=0, type="all", sort="desc", refresh=1), True),
                    ("media", _q("/api/of/v2/vault/media", limit=24, sort="desc", **extra), False)]
            for kind, p, refresh in reqs:
                t0 = time.time()
                try:
                    r = await http.get(p, headers=hdr)
                    st = r.status_code
                except Exception:  # noqa: BLE001 — recorded by the client (599)
                    st = 599
                picks.append({"aid": aid, "kind": kind, "t0": t0, "t1": time.time(), "status": st,
                              "refresh": refresh})
            try:
                await asyncio.wait_for(stop.wait(), rng.uniform(3, 7))
            except asyncio.TimeoutError:
                pass

    def segment() -> dict:
        stop = asyncio.Event()
        n_pick = max(len(busy), ctx.users // 2)
        pool = ctx.owner.share(limits=min(100, n_pick + 10))
        tasks = [asyncio.create_task(picker(i, pool, busy[i % len(busy)], stop)) for i in range(n_pick)] if busy else []
        ch = Chatters({a: ctx.owner.share(limits=10) for a in busy}, {a: 1.0 for a in busy},
                      random.Random(f"{ctx.seed}:chat:{len(segs)}"), think_s=(2.0, 6.0))
        if busy:
            ch.start(max(1, ctx.users // 4))
        targets = [f for a in busy for f in fans.get(a, [])[:3]]
        if targets:
            tasks.append(asyncio.create_task(fan_dm.serial(pool, targets, 10_000, rate=0.5, stop=stop, ids=dm_ids)))
        return {"stop": stop, "tasks": tasks, "chat": ch, "pools": [pool, *ch.sessions.values()]}

    async def end(seg: dict) -> None:
        seg["stop"].set()
        await seg["chat"].stop()
        await asyncio.gather(*seg["tasks"], return_exceptions=True)
        for p in seg["pools"]:
            await p.aclose()

    async def cdn_calls() -> list[dict]:
        r = await ctx.owner.get("/__slop/img/calls")
        return r.json()["calls"] if r.status_code == 200 else []

    segs: list[dict] = []
    segs.append(segment())
    cdn: list[dict] = []
    resume: dict = {}
    deadline = time.time() + float(ctx.param("max_s", 300 + 60 * len(cs)))
    done_at = None
    while time.time() < deadline:
        if not resume:
            for r in runs("status='running' AND phase LIKE 'auto:all:%'"):
                if r["account_id"] in quiet and int(r["phase"].rsplit(":", 1)[1] or 0) > 0:
                    resume = {"aid": r["account_id"], "seen_phase": r["phase"], "run_id": r["id"]}
                    break
            if resume:
                await end(segs[-1])
                cdn += await cdn_calls()
                resume["wire_i"] = len(fake.vault_calls)
                t_term, took = await asyncio.to_thread(ctx.stack.stop_relay, 0, 20.0)
                row = runs("id=?", (resume["run_id"],))[0]
                resume.update(t_term=t_term, took=took, cursor_phase=row["phase"], status_at_stop=row["status"])
                await asyncio.to_thread(ctx.stack.start_relay)
                resume["t_up"] = time.time()
                await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S, pictures=True)
                ctx.note(f"relay restarted mid-walk: {resume}")
                segs.append(segment())
        if all((latest_auto(a) or {}).get("phase") == "auto:done" for a in quiet):
            done_at = done_at or time.time()
            if time.time() - done_at >= LINGER_S:
                break
        await asyncio.sleep(0.2)
    await end(segs[-1])
    ctx.rec.stage = None
    cdn += await cdn_calls()
    t_up = resume.get("t_up", t_run0)
    ctx.metric("vault_collect_load", {"seconds": round(time.time() - t_run0, 1), "quiet_done": done_at is not None,
                                      "picks": len(picks), "wire_vault_calls": len(fake.vault_calls),
                                      "cdn_calls": len(cdn), "resume": resume})

    # ── attribution ──
    win: dict[str, list[tuple[float, float]]] = {}
    for p in picks:
        win.setdefault(p["aid"], []).append((p["t0"] - TOL_S, p["t1"] + TOL_S))

    def is_user(c: dict) -> bool:
        return any(a <= c["t"] <= b for a, b in win.get(c["account"], ()))

    col = [c for c in fake.vault_calls if not is_user(c)]
    by_aid: dict[str, list[dict]] = {}
    for c in col:
        by_aid.setdefault(c["account"], []).append(c)
    cdn_by: dict[str, list[dict]] = {}
    for c in cdn:
        o = owner_of(c["key"])
        if o:
            cdn_by.setdefault(o[0], []).append({**c, "mid": o[1], "variant": o[2]})

    # collect_pacing
    gaps = {}
    for a in quiet:
        ts_ = sorted(c["t"] for c in by_aid.get(a, []))
        gaps[a] = min((b - x for x, b in zip(ts_, ts_[1:])), default=None)
    bad = {a: round(g, 3) for a, g in gaps.items() if g is not None and g < GAP_S - TOL_S}
    ctx.check(PACING, not bad and any(g is not None for g in gaps.values()), gap_s=GAP_S, min_gap_s=gaps, too_close=bad)

    # spans
    spans = []
    for a in cs:
        ev = sorted([c["t"] for c in by_aid.get(a, [])] + [c["t"] for c in cdn_by.get(a, [])])
        s = None
        for t in ev:
            if s and t - s[2] <= SPAN_GAP_S:
                s[2] = t
            else:
                s = [a, t, t]
                spans.append(s)
    spans.sort(key=lambda s: s[1])
    overlaps = [(x[0], y[0], round(x[2] - y[1], 3)) for x, y in zip(spans, spans[1:]) if y[1] < x[2] - TOL_S]
    ctx.check(ONE_AT_A_TIME, not overlaps and bool(spans), spans=len(spans), overlaps=overlaps[:10])

    # collect_skips_busy
    viol, active = [], 0
    for a in busy:
        refs = [p["t1"] for p in picks if p["aid"] == a and p["refresh"] and p["status"] == 200]
        active += bool(refs)
        for s in (s for s in spans if s[0] == a):
            since = t_up if s[1] >= t_up else t_run0
            if s[1] - t_run0 >= MAX_SKIP_S:
                continue
            last = max((t for t in refs if since <= t < s[1]), default=None)
            if last is not None and s[1] - last < QUIET_S:
                viol.append({"aid": a, "span_start": round(s[1] - t_run0, 1), "user_s_before": round(s[1] - last, 2)})
    if not active:
        ctx.skip(SKIPS_BUSY, "no busy Creator had a user refresh reach OF")
    else:
        ctx.check(SKIPS_BUSY, not viol, quiet_s=QUIET_S, busy=len(busy), violations=viol[:10])

    # collect_fills_mirror
    con = w.sql()
    try:
        mirror = dict(con.execute("SELECT account_id, COUNT(*) FROM vault_items WHERE removed_at IS NULL "
                                  "GROUP BY account_id").fetchall())
        keys = {}
        for a, k in con.execute("SELECT account_id, query_key FROM vault_response_cache").fetchall():
            keys.setdefault(a, set()).add(k)
    finally:
        con.close()
    fill_bad = {}
    for a in quiet:
        la = latest_auto(a) or {}
        summ = (await ctx.owner.get(f"/admin/vault-ai/cache/summary?account_id={a}")).json()
        want = {"lists:view=main|limit=50|offset=0"} | {
            f"media:type=all|list={f['id']}|offset=0|limit=24|sort=desc|field=recent|query="
            for f in vw.vault(a)["folders"]} | {
            f"media:type=all|list=None|offset={o}|limit=24|sort=desc|field=recent|query=" for o in (0, 24)}
        miss = sorted(want - keys.get(a, set()))
        got = {"run": (la.get("status"), la.get("phase")), "mirror": mirror.get(a, 0), "want": n_items,
               "complete": summ.get("complete"), "summary_count": summ.get("count"), "missing_keys": miss[:3]}
        if not (got["run"] == ("done", "auto:done") and got["mirror"] == n_items and got["complete"] is True
                and got["summary_count"] == n_items and not miss):
            fill_bad[a] = got
    ctx.check(FILLS_MIRROR, not fill_bad and done_at is not None, quiet=len(quiet), bad=fill_bad)

    # collect_thumbs_warm
    warm_bad = {}
    for a in quiet:
        have = {p.name for p in (stills / "thumbs" / a).glob("*")} if (stills / "thumbs" / a).is_dir() else set()
        want = {f"{m}.jpg" for m in vw.newest(a, HOT_THUMBS)}
        other = [str(p) for sub in ("images", "posters", "storyboards") for p in (stills / sub).rglob(f"*{a}*")]
        if have != want or other:
            warm_bad[a] = {"have": len(have), "want": len(want), "extra": sorted(have - want)[:3],
                           "missing": sorted(want - have)[:3], "other_stores": other[:3]}
    not_thumb = [c["key"] for v in cdn_by.values() for c in v if c["variant"] != "thumb"]
    non200 = [(c["key"], c["status"]) for v in cdn_by.values() for c in v if c["status"] != 200]
    ctx.check(THUMBS_WARM, not warm_bad and not not_thumb and not non200, bad=warm_bad, non_thumb_fetches=not_thumb[:5],
              non_200=non200[:5])

    # collect_resume
    if not resume:
        ctx.skip(RESUME, "no quiet Creator seen in auto:all:<K>, K > 0 (walk too fast to catch)")
    else:
        a = resume["aid"]
        cur = int(resume["cursor_phase"].rsplit(":", 1)[1]) if resume["cursor_phase"].startswith("auto:all:") else None
        walk = [c for c in by_aid.get(a, []) if c["route"] == "media" and c["query"].get("limit") == "100"]
        after = [int(c["query"].get("offset") or 0) for c in walk if c["t"] >= resume["t_up"]]
        offs = [int(c["query"].get("offset") or 0) for c in walk]
        dup = sorted({o for o in offs if offs.count(o) > 1} - {cur})
        la = latest_auto(a) or {}
        ok = (cur is not None and bool(after) and after[0] == cur and not dup and la.get("id") == resume["run_id"]
              and (la.get("status"), la.get("phase")) == ("done", "auto:done") and mirror.get(a, 0) == n_items)
        ctx.check(RESUME, ok, aid=a, cursor=resume["cursor_phase"], first_after=after[:1], offsets=offs, dup=dup,
                  run=(la.get("id"), la.get("status"), la.get("phase")), want_run=resume["run_id"],
                  mirror=mirror.get(a, 0), stop_took_s=resume["took"])

    # user_read_p95
    summ = ctx.rec.summary("load")
    p95 = {k: v["p95_ms"] for k, v in summ.items() if k in BUDGET_MS}
    over = {k: (p95[k], BUDGET_MS[k]) for k in p95 if p95[k] > BUDGET_MS[k]}
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", {k: summ[k]["n"] for k in p95})
    ctx.check(USER_P95, bool(p95) and not over, budget=True, p95_ms=p95, over=over)
    (Path(ctx.out) / "vault-collect-records.json").write_text(json.dumps(
        {"busy": busy, "quiet": quiet, "spans": spans, "resume": resume, "gaps": gaps}, default=str))
