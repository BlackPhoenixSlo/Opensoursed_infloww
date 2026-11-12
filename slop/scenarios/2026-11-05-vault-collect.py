"""The vault week cache's background collector (service/vault_collect.py) under a working Agency.

World: `flat_agency`, vault_collect_creators Creators (6 / 16 / 40), each with a captured OF session (the relay's
REAL OFClient against lib/of_wire.py, `OF_WIRE`) and a vault of vault_collect_items media in 6 folders
(lib/vault_wire.py, made per Creator on first sight, so it is there the moment a session lands). OF's CDN is
lib/img_relay.py's fake, armed with every vault thumb + full (`pictures`: small PNGs), and
vault_stills' stores point into the run's temp dir. The collector runs on its own (RELAY_ENV: tick 2 s, first
tick 1 s, GAP_S 2 s, USER_QUIET_S 20 s). GAP_S stays above of_pacing's per-Creator 1 s page gap (+0.3 s
jitter), which every collector call also goes through: at 1 s that pacer alone kept the gaps and hid collect-unpaced.

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
  collect_skips_busy     no collector OF page read on a busy Creator is admitted within USER_QUIET_S after a user
                         picker refresh (only refreshes since the relay last started: the product keeps that clock
                         in RAM; exempt past MAX_SKIP_S). CDN thumbs already queued behind the user are excluded.
  collect_fills_mirror   per quiet Creator: latest auto run done/auto:done, vault_items == the fake's count,
                         /admin/vault-ai/cache/summary complete + count, the picker's hot keys in vault_response_cache.
  collect_thumbs_warm    per quiet Creator: the thumbs store holds exactly the newest 100 media; no image /
                         poster / storyboard file; every CDN fetch a thumb, every one 200.
  collect_resume         the restarted relay's first walk page for the stopped Creator is the persisted cursor,
                         no walk offset fetched twice but that one, the walk reaches auto:done, mirror complete.
  user_read_p95          picker + chat reads during load: p95 <= BUDGET_MS each; stock p95 vs last green
                         (P95_VS_LAST) on the same keys.
  rewarm_after_switch    after the load: every other Creator made due (its last done run aged past STALE_S by
                         SQL), then, while the collector walks one of them, a quiet Creator with a fresh run is moved
                         to a proxy (POST /admin/proxies + /assign, lib/proxy_wire.py). Its hot pass (folder-list
                         call through the new proxy) comes before any due Creator's that was not already walking (a
                         rival's first folder-list call must be seen, after it), and its picker hot keys are back in
                         vault_response_cache.
User vs collector on a busy Creator: an OF vault call inside one of the harness's own picker requests to that
Creator (+-50 ms) is the user's; the rest the collector's.

Bypasses (declared): OF at its wire (lib/of_wire.py + lib/vault_wire.py), OF's CDN in the relay process
(lib/img_relay.py, `pictures`: small PNGs), vault_stills / storyboard dirs re-pointed by env
(lib/vault_collect_relay.py), the collector's env knobs shortened (RELAY_ENV; USER_QUIET_S 20 s, not 120 s, so
a run stays minutes long), picker users are httpx clients reading the picker's routes (no browser), 6 h passing
for rewarm_after_switch is an SQL age of finished_at, the proxy is a loopback SOCKS5 (lib/proxy_wire.py).
Break-it-once: collect-unpaced (GAP_S 0: only collect_pacing goes red); no-rewarm-on-switch (only
rewarm_after_switch).
"""
from __future__ import annotations

import asyncio
import itertools
import json
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from slop.actors import fan_dm
from slop.actors.chatter import Chatters
from slop.lib.img_relay import arm_run
from slop.lib.proxy_wire import ProxyWire
from slop.lib.vault_collect_faults import (FILLS_MIRROR, ONE_AT_A_TIME, PACING, RESUME, REWARM, SKIPS_BUSY,
                                           THUMBS_WARM, USER_P95)
from slop.seed import ts
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_ui import cdn_calls
from slop.seed.vault_cache import LISTS_KEY
from slop.lib.vault_wire import VaultWire, owner_of

sys.path.append(str(Path(__file__).resolve().parents[2] / "service"))   # of_pacing imports its sibling of_call_counter
from of_pacing import JITTER_S, PAGE_GAP_S  # noqa: E402

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "collect-unpaced"
GAP_S, QUIET_S, MAX_SKIP_S = 2.0, 20.0, 1800.0
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
STALE_S = 21600           # vault_collect's default, not shortened here
WAIT_S = 360.0            # one walk in flight (<= a full walk) + the re-warm's run + the next rival's start, with room


def _q(path: str, **kv) -> str:
    return path + "?" + "&".join(f"{k}={v}" for k, v in kv.items() if v is not None)


async def run(ctx):
    assert GAP_S > PAGE_GAP_S + JITTER_S + 0.5, "collector gap cannot be masked by OF pacing"
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
                cdn += await cdn_calls(ctx, allow_failure=True)
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
    cdn += await cdn_calls(ctx, allow_failure=True)
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

    # collect_skips_busy: OF page reads admitted during a user's quiet window are forbidden.
    # Thumbnail work already queued on the CDN lane can arrive after the user request.
    viol, active = [], 0
    for a in busy:
        refs = [p for p in picks if p["aid"] == a and p["refresh"] and p["status"] == 200]
        active += bool(refs)
        collector = by_aid.get(a, [])
        for call in collector:
            t = call["t"]
            since = t_up if t >= t_up else t_run0
            if t - t_run0 >= MAX_SKIP_S:
                continue
            # A call admitted before the user's request can arrive after it through OF pacing.
            last = max((p["t1"] for p in refs if since <= p["t1"] <= t
                        and t > p["t0"] + PAGE_GAP_S + JITTER_S + TOL_S), default=None)
            if last is not None and t - last < QUIET_S:
                viol.append({"aid": a, "call_s": round(t - t_run0, 1), "user_s_before": round(t - last, 2)})
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
        want = {LISTS_KEY} | {
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
    # rewarm_after_switch
    rw = await _rewarm_after_switch(ctx, fake, vw, cs, quiet, runs, latest_auto)
    (Path(ctx.out) / "vault-collect-records.json").write_text(json.dumps(
        {"busy": busy, "quiet": quiet, "spans": spans, "resume": resume, "gaps": gaps, "rewarm": rw}, default=str))


async def _rewarm_after_switch(ctx, fake, vw, cs, quiet, runs, latest_auto) -> dict:
    """A proxy switch on a quiet Creator whose run is fresh, while the collector walks a due one: that Creator's hot
    pass is the next one to start, ahead of every other due Creator (never-walked or stale)."""
    if not quiet or len(cs) < 2:
        ctx.skip(REWARM, "needs a quiet Creator and one other")
        return {}
    t = quiet[0]
    con = ctx.world.sql()
    try:
        old = ts(datetime.utcnow() - timedelta(seconds=STALE_S + 60))
        for a in cs:
            la = latest_auto(a)
            if a != t and la and la["status"] == "done":
                con.execute("UPDATE vault_cache_runs SET finished_at=? WHERE id=?", (old, la["id"]))
        con.commit()
    finally:
        con.close()

    def running() -> set[str]:
        return {r["account_id"] for r in runs("status='running' AND phase LIKE 'auto:%'")}

    t0 = time.time()
    while not (running() - {t}) and time.time() - t0 < 30:
        await asyncio.sleep(0.2)
    label = "slop-vault-collect-rw"
    with ProxyWire() as pw:
        try:
            await ctx.owner.post("/admin/proxies", json={"label": label, "scheme": "socks5", "host": "127.0.0.1",
                                                         "port": pw.port, "notes": "slop: vault-collect rewarm"})
            await asyncio.sleep(1.0)  # proxies.json writes apart (dead-proxy scenario's measured race)
            v0 = len(fake.vault_calls)
            inflight = running()
            bind = (await ctx.owner.post("/admin/proxies/assign", json={"label": label, "account_id": t})).status_code
            t_sw = time.time()
            inflight |= running()
            rivals = sorted(set(cs) - inflight - {t})
            egress = f"127.0.0.1:{pw.port}"

            def first_lists() -> dict[str, float]:
                out: dict[str, float] = {}
                for c in fake.vault_calls[v0:]:
                    if c["route"] == "lists" and c["account"] not in out:
                        out[c["account"]] = c["t"]
                return out

            # one Creator walks at a time: the first rival's hot pass starting fixes the order (and the target's keys)
            while rivals and not any(a in first_lists() for a in rivals) and time.time() - t_sw < WAIT_S:
                await asyncio.sleep(0.5)
            fl = first_lists()
            t_hot = fl.get(t)
            ahead = sorted(a for a in rivals if a in fl and (t_hot is None or fl[a] < t_hot))
            rival_first = {a: fl[a] for a in rivals if a in fl}
            reason = ("bind != 200" if bind != 200 else "no hot pass for the target" if t_hot is None
                      else f"a rival's hot pass first: {ahead}" if ahead
                      else f"no rival's hot pass within {WAIT_S:.0f} s of the switch" if not rival_first
                      else None)
            t_calls = [c for c in fake.vault_calls[v0:] if c["account"] == t]
            via = sorted({c["egress"] for c in t_calls})
            con = ctx.world.sql()
            try:
                keys = {k for (k,) in con.execute("SELECT query_key FROM vault_response_cache WHERE account_id=?", (t,))}
            finally:
                con.close()
            want = {"lists:view=main|limit=50|offset=0"} | {
                f"media:type=all|list={f['id']}|offset=0|limit=24|sort=desc|field=recent|query="
                for f in vw.vault(t)["folders"]} | {
                f"media:type=all|list=None|offset={o}|limit=24|sort=desc|field=recent|query=" for o in (0, 24)}
            miss = sorted(want - keys)
            detail = {"aid": t, "bind": bind, "inflight": sorted(inflight), "rivals": rivals, "ahead": ahead,
                      "hot_after_s": None if t_hot is None else round(t_hot - t_sw, 1), "egress": via,
                      "missing_keys": miss[:3], "rival_first_s": {a: round(v - t_sw, 1) for a, v in rival_first.items()},
                      "reason": reason or (f"egress {via}" if via != [egress] else "missing keys" if miss else None)}
            if not rivals:
                ctx.skip(REWARM, "no due Creator left to race the re-warm", **detail)
            else:
                ctx.check(REWARM, reason is None and via == [egress] and not miss, **detail)
            return detail
        finally:
            await ctx.owner.post(f"/admin/proxies/{label}/unbind", json={"account_id": t})
            await asyncio.sleep(1.0)
