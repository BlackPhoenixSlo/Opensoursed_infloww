"""The fan-info sweep (`automations.gen_info`, Automation 02) at volume after its persist plan became pure
(service/automations/gen_info_plan.py `plan_persist`): every Creator's gen_info rule is run at once with the owner's
"Run now", the real supervisor runs them, and every fan it profiles is checked against what his seed says, while
`--users` owner tabs keep opening fans' drawers.

World: `agency_inbox` (an Agency, its Creators, fans, a short thread for some: never past gen_info's 8-message
gate) plus seed/fan_info_history.py, `--set fans=` per Creator (12 small, 60 medium, 150 huge): fans with 10-16
inbound lines, a quarter with an operator-pinned language (`language_source='manual'`) the fake detects as another,
a quarter with a month-old profile whose extract comes back empty, the rest never profiled. The Agency's DeepSeek
key is a dummy set through the real Setup > Keys route (`PUT /admin/my-llm-keys`); one gen_info rule per Creator
(every 24 h, `limit` LIMIT, gen_info's default) by SQL, as the rules API writes it, with its last job an hour ago.

Flow: `--users` owner tabs open drawers (`GET /admin/fans/{creator}/{fan}`, the seeded fans, think time
THINK_S) from before the press until every run is done; the owner presses Run now on every rule at once
(`POST /admin/automation-rules/{id}/run-now`, which wakes the supervisor); the scenario waits for each Creator's
`automation_runs` row to complete; then every seeded fan's drawer is read once more.

Checks (names in lib/fan_info_faults.py):
  PIN     every manual fan keeps his language and source (DB and drawer), though the fake answered him another
          language past the 40-char evidence floor (the seeder asserts both) and his profile was regenerated.
  KEEP    every keep fan's fan_profiles nickname / short_bio / bullet_points / original_name are the seeded ones
          after a regeneration (last_generated_at moved) whose extract returned them empty.
  OWN     every seeded fan's occupation / hobbies carry his own marker, a non-keep fan's short_bio /
          bullet_points too, a non-manual fan has his own detected language (source 'ai'); DB and drawer agree;
          OF's drawer push took one Fan note per fan, naming his marker and no other fan's.
  COUNTS  one ok run per Creator after Run now; its stats: candidates == the SQL oracle (fans with an inbound
          message, capped at LIMIT), attempted == generated == the seeded fans, skipped_fresh the rest, failed /
          capped / deferred_for_scrape 0; the fake saw each seeded fan's prompt exactly once and no other gen_info
          prompt; fan_profiles rows and fans rows written this run == generated == done gen_info grok_calls.
Budgets: Run now -> run done p95 per Creator (RUN_P95_MS), the drawer read p95 (DRAWER_P95_MS) and both vs the last
green run; plus the stock no 5xx / no unexpected Traceback.

Bypasses (declared):
  - DeepSeek is lib/fan_info_relay.py's answer on lib/automation_relay.py's loopback fake (`llm_client.chat`
    with its key lookup, cap reservation, grok_calls rows and parse is the product's); per fan from
    `fan-info-extracts.json`, told apart by the display name on the prompt's first line (the seeder makes it
    unique); 0.4 s per answer (DEEPSEEK_LATENCY_S, a guess). SLOP_LIVE=1 is refused (every check SKIPs).
  - OnlyFans is automation_relay's offline walker; gen_info's nickname / Fan notes push (PUT /subscriptions/{fan})
    is kept and answered there by lib/fan_info_relay.py (OF's answer body a guess; the product ignores it).
  - The rules and their last job (an hour ago, so the 24 h cadence is not due and only Run now fires) are SQL,
    the rows the rules API and the materializer write; fans, messages, chats and old profiles are SQL
    (seed/fan_info_history.py docstring).
  - The owner tabs are one owner session's connection pool, not browsers.

Break-it-once: gen-info-manual-language-overwritten (the scenario's FAULT: gen_info_plan.MANUAL_LANGUAGE_SOURCES
emptied, the SQL pin never holds) turns only PIN red; `--fault=gen-info-facts-cross-fan` (plan_persist reuses the
previous fan's facts) only OWN.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import httpx

from slop.lib.fan_info_faults import COUNTS, KEEP, OWN, PIN
from slop.lib.fan_info_relay import write_extracts
from slop.lib.procmon import pct
from slop.seed import fan_info_history, ts

PROFILE = "agency_inbox"
UI = False
FAULT = "gen-info-manual-language-overwritten"
RELAY_ENV = {"SLOP_SUPERVISOR": "1"}   # the real supervisor: Run now's wake drains the jobs
LIMIT = 200                 # the rule's sweep ceiling (gen_info's _DEFAULT_FAN_LIMIT)
EVERY_S = 86_400
RUN_TIMEOUT_S = 900
THINK_S = (2.0, 6.0)        # an owner reading one drawer before the next (a guess)
# measured at medium / 200 users (slop/evidence/20261102T165855Z-2026-11-02-fan-info-sweep-30df): Run now -> done
# p95 19,966 ms (runs go 4 at a time: 6.8 / 13.4 / 19.9 s waves), drawer p95 15 ms; small: 1.6 s / 27 ms
RUN_P95_MS = 40_000
DRAWER_P95_MS = 500
P95_VS_LAST = (2.0, 2000)
FAKE_KEY = "slop-fake-deepseek"
MARKER = re.compile(r"\bzq[a-z]+\b")   # seed/fan_info_history.tag


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _runs(con, run0: int) -> dict[str, list[dict]]:
    """Every gen_info run after `run0`, per Creator, oldest first."""
    out: dict[str, list[dict]] = defaultdict(list)
    for rid, a, st, done, status, stats, err in con.execute(
            "SELECT id, account_id, started_at, completed_at, status, stats_json, error_text FROM automation_runs "
            "WHERE kind='gen_info' AND id > ? ORDER BY id", (run0,)):
        out[str(a)].append({"id": rid, "start": _dt(st), "done": _dt(done), "status": status,
                            "stats": json.loads(stats or "{}"), "error": err})
    return out


def _seed_rules(w, aids: list[str]) -> dict[str, int]:
    """One gen_info rule per Creator as the rules API writes it, with its last job an hour ago (done)."""
    con = w.sql()
    now = w.now
    rules = {}
    with con:
        for a in aids:
            cur = con.execute(
                "INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled, created_at)"
                " VALUES (?, 'Fan info', 'gen_info', ?, ?, 1, ?)",
                (a, json.dumps({"every_seconds": EVERY_S}), json.dumps({"limit": LIMIT}),
                 ts(now - timedelta(days=3))))
            rules[a] = int(cur.lastrowid)
            at = ts(now - timedelta(hours=1))
            con.execute("INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts, rule_id,"
                        " created_at) VALUES (?, 'gen_info', ?, ?, 'done', 1, ?, ?)",
                        (a, json.dumps({"limit": LIMIT}), at, rules[a], at))
    con.close()
    return rules


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    aids = [c["id"] for c in w.data["creators"]]
    if os.environ.get("SLOP_LIVE") == "1":
        for c in (PIN, KEEP, OWN, COUNTS):
            ctx.skip(c, "SLOP_LIVE=1: this scenario runs on the DeepSeek fake only, never the paid API")
        return
    per = int(ctx.param("fans", w.size["fan_info_fans"]))
    seed = fan_info_history.seed(w, w.data["creators"], per)
    fans = seed["fans"]
    write_extracts(ctx.stack.tmp, seed["extracts"])
    roles = Counter(f["role"] for f in fans)
    ctx.metric("world", {"creators": len(aids), "seeded_fans": len(fans), **roles})

    (await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": FAKE_KEY})).raise_for_status()
    rules = _seed_rules(w, aids)
    con = w.sql()
    oracle = {str(a): int(n) for a, n in con.execute(
        "SELECT account_id, COUNT(DISTINCT fan_id) FROM messages WHERE direction='in' GROUP BY account_id")}
    run0 = con.execute("SELECT COALESCE(MAX(id), 0) FROM automation_runs").fetchone()[0]
    call0 = con.execute("SELECT COALESCE(MAX(id), 0) FROM grok_calls").fetchone()[0]
    con.close()
    t_start = datetime.utcnow()

    # ── owner tabs opening drawers ────────────────────────────────────────
    rng = w.rng("scenario:fan-info-sweep")
    plans = [[fans[rng.randrange(len(fans))] for _ in range(64)] for _ in range(max(1, ctx.users))]
    thinks = [[rng.uniform(*THINK_S) for _ in range(64)] for _ in range(len(plans))]
    tabs_http = ctx.owner.share(limits=max(10, len(plans)))
    stop = asyncio.Event()
    reads = Counter()

    async def tab(i: int) -> None:
        await asyncio.sleep(THINK_S[1] * i / len(plans))
        j = 0
        while not stop.is_set():
            f = plans[i][j % 64]
            try:
                r = await tabs_http.get(f"/admin/fans/{f['account_id']}/{f['fan_id']}")
                reads[r.status_code] += 1
            except httpx.HTTPError:   # recorded as 599 by the client: the stock no-5xx check fails, the tab goes on
                reads[599] += 1
            try:
                await asyncio.wait_for(stop.wait(), thinks[i][j % 64])
            except asyncio.TimeoutError:
                pass
            j += 1

    ctx.rec.stage = "sweep"
    tabs = asyncio.gather(*(tab(i) for i in range(len(plans))))
    await asyncio.sleep(THINK_S[1])

    # ── Run now on every rule at once ─────────────────────────────────────
    pressed: dict[str, datetime] = {}
    statuses: dict[str, int] = {}

    async def press(a: str) -> None:
        pressed[a] = datetime.utcnow()
        r = await ctx.owner.post(f"/admin/automation-rules/{rules[a]}/run-now")
        statuses[a] = r.status_code

    await asyncio.gather(*(press(a) for a in aids))

    deadline = time.monotonic() + RUN_TIMEOUT_S
    con = w.sql()
    while True:
        runs = _runs(con, run0)
        if all(runs.get(a) and all(x["done"] for x in runs[a]) for a in aids) or time.monotonic() > deadline:
            break
        await asyncio.sleep(0.1)
    timed_out = time.monotonic() > deadline
    await asyncio.sleep(1.0)   # a second run, were one to start late, shows up
    stop.set()
    await tabs
    ctx.rec.stage = None
    await tabs_http.aclose()

    # ── what landed ───────────────────────────────────────────────────────
    seen = (await ctx.owner.get("/__slop/fan-info/calls")).json()
    calls, pushes = seen["calls"], seen["pushes"]
    sem = asyncio.Semaphore(16)
    drawer: dict[tuple[str, int], dict] = {}

    async def read(f) -> None:
        async with sem:
            r = await ctx.owner.get(f"/admin/fans/{f['account_id']}/{f['fan_id']}")
            drawer[(f["account_id"], f["fan_id"])] = r.json() if r.status_code == 200 else {"status": r.status_code}

    ctx.rec.stage = "after"
    await asyncio.gather(*(read(f) for f in fans))
    ctx.rec.stage = None

    runs = _runs(con, run0)
    db_fans = {(str(a), int(f)): {"language": l, "source": s, "occupation": o, "hobbies": h, "facts_at": _dt(fa)}
               for a, f, l, s, o, h, fa in con.execute(
                   "SELECT account_id, fan_id, language, language_source, occupation, hobbies, grok_facts_updated_at "
                   "FROM fans")}
    db_prof = {(str(a), int(f)): {"nickname": n, "short_bio": b, "bullet_points": bp, "original_name": on,
                                   "gen_at": _dt(g)}
               for a, f, n, b, bp, on, g in con.execute(
                   "SELECT account_id, fan_id, nickname, short_bio, bullet_points, original_name, last_generated_at "
                   "FROM fan_profiles")}
    gcalls = Counter((str(a), st) for a, st in con.execute(
        "SELECT account_id, status FROM grok_calls WHERE purpose='gen_info' AND id > ?", (call0,)))
    con.close()

    asked = Counter(c["name"] for c in calls if c["known"])
    unknown = [c["name"] for c in calls if not c["known"]]

    def fresh(at) -> bool:
        return at is not None and at >= t_start

    # PIN
    manual = [f for f in fans if f["role"] == "manual"]
    pin_bad = {}
    for f in manual:
        k = (f["account_id"], f["fan_id"])
        row, api = db_fans.get(k, {}), drawer.get(k, {})
        got = (row.get("language"), row.get("source"), api.get("language"), api.get("language_source"))
        if got != (f["lang_before"], "manual", f["lang_before"], "manual") or asked[f["name"]] != 1 \
                or not fresh(row.get("facts_at")):
            pin_bad[f"{k[0]}/{k[1]}"] = {"pinned": f["lang_before"], "detected": f["detected"], "db_api": got,
                                         "asked": asked[f["name"]], "regenerated": fresh(row.get("facts_at"))}
    ctx.check(PIN, bool(manual) and not pin_bad, manual=len(manual), wrong=len(pin_bad),
              e_g=dict(list(pin_bad.items())[:4]),
              min_in_chars=min((f["in_chars"] for f in manual), default=None),
              evidence_floor=fan_info_history.EVIDENCE_MIN_CHARS)

    # KEEP
    keep = [f for f in fans if f["role"] == "keep"]
    keep_bad = {}
    for f in keep:
        k = (f["account_id"], f["fan_id"])
        p = db_prof.get(k, {})
        diff = {x: p.get(x) for x in fan_info_history.KEEP_FIELDS if p.get(x) != f["kept"][x]}
        api_nick = (drawer.get(k, {}).get("profile") or {}).get("nickname")
        if diff or not fresh(p.get("gen_at")) or api_nick != f["kept"]["nickname"]:
            keep_bad[f"{k[0]}/{k[1]}"] = {"changed": diff, "regenerated": fresh(p.get("gen_at")), "drawer_nick": api_nick}
    ctx.check(KEEP, bool(keep) and not keep_bad, keep=len(keep), fields=list(fan_info_history.KEEP_FIELDS),
              wrong=len(keep_bad), e_g=dict(list(keep_bad.items())[:4]))

    # OWN
    own_bad = {}
    for f in fans:
        k, m = (f["account_id"], f["fan_id"]), f["marker"]
        row, p, api = db_fans.get(k, {}), db_prof.get(k, {}), drawer.get(k, {})
        want = {"occupation": f"slop job {m}", "hobbies": f"slop hobby {m}"}
        got = {"occupation": row.get("occupation"), "hobbies": row.get("hobbies")}
        api_got = {"occupation": api.get("occupation"), "hobbies": api.get("hobbies")}
        if f["role"] != "keep":
            want |= {"short_bio": f"slop bio {m}", "bullet_points": f"- Recent: slop {m}"}
            got |= {"short_bio": p.get("short_bio"), "bullet_points": p.get("bullet_points")}
            api_got["short_bio"] = (api.get("profile") or {}).get("short_bio")
        if f["role"] != "manual":
            want |= {"language": f["detected"], "source": "ai"}
            got |= {"language": row.get("language"), "source": row.get("source")}
            api_got |= {"language": api.get("language"), "source": api.get("language_source")}
        api_want = {x: want[x] for x in api_got}
        if got != want or api_got != api_want:
            own_bad[f"{k[0]}/{k[1]}"] = {"want": want, "db": {x: v for x, v in got.items() if v != want[x]},
                                         "drawer": {x: v for x, v in api_got.items() if v != api_want[x]}}
    # ... and OF's drawer push (Fan notes) for each fan names only his own marker
    by_fan = defaultdict(list)
    for p in pushes:
        by_fan[(p["account_id"], p["fan_id"])].append(p)
    push_bad = {}
    for f in fans:
        k = (f["account_id"], f["fan_id"])
        notices = [p["value"] for p in by_fan.get(k, []) if p["field"] == "notice"]
        foreign = sorted({m for p in by_fan.get(k, []) for m in MARKER.findall(p["value"])} - {f["marker"]})
        if len(notices) != 1 or f["marker"] not in MARKER.findall(notices[0]) or foreign:
            push_bad[f"{k[0]}/{k[1]}"] = {"notices": notices[:2], "foreign_markers": foreign[:4]}
    ctx.check(OWN, bool(fans) and not own_bad and not push_bad, fans=len(fans), wrong=len(own_bad),
              e_g=dict(list(own_bad.items())[:3]), of_push_wrong=len(push_bad),
              of_push_e_g=dict(list(push_bad.items())[:3]), of_pushes=len(pushes))

    # COUNTS
    n_seed = Counter(f["account_id"] for f in fans)
    cnt_bad = {}
    for a in aids:
        rs = runs.get(a, [])
        st = rs[0]["stats"] if len(rs) == 1 else {}
        want = {"candidates": min(oracle.get(a, 0), LIMIT), "attempted": n_seed[a], "generated": n_seed[a],
                "skipped_fresh": min(oracle.get(a, 0), LIMIT) - n_seed[a], "failed": 0, "capped": 0,
                "deferred_for_scrape": 0}
        got = {x: st.get(x) for x in want}
        written = {"fan_profiles": sum(1 for (fa, _), p in db_prof.items() if fa == a and fresh(p["gen_at"])),
                   "fans": sum(1 for (fa, _), r in db_fans.items() if fa == a and fresh(r["facts_at"])),
                   "grok_calls": dict((s, n) for (fa, s), n in gcalls.items() if fa == a)}
        ok = (len(rs) == 1 and rs[0]["status"] == "ok" and rs[0]["done"] and got == want
              and written["fan_profiles"] == written["fans"] == st.get("generated")
              and sum(written["grok_calls"].values()) == st.get("generated")
              and statuses.get(a) == 200 and "key_error" not in st and "no_llm_key" not in st)
        if not ok:
            cnt_bad[a] = {"runs": [(x["status"], x["error"]) for x in rs], "want": want,
                          "got": {x: v for x, v in got.items() if v != want[x]}, "written": written,
                          "run_now": statuses.get(a)}
    twice = {n: c for n, c in asked.items() if c != 1}
    never = [f["name"] for f in fans if asked[f["name"]] == 0]
    ctx.check(COUNTS, not cnt_bad and not twice and not never and not unknown and not timed_out
              and not any(s >= 500 for s in reads),
              creators=len(aids), seeded=len(fans), asked=sum(asked.values()), asked_twice=dict(list(twice.items())[:4]),
              never_asked=never[:4], unknown_prompts=unknown[:4], timed_out=timed_out, drawer_reads=dict(reads),
              wrong=cnt_bad, grok_call_status=dict(Counter(s for (_, s), n in gcalls.items() for _ in range(n))))

    # Budgets
    lat = [(x["done"] - pressed[a]).total_seconds() * 1000 for a in aids for x in runs.get(a, [])[:1]
           if x["done"] and a in pressed]
    p95 = pct(lat)
    ctx.check(f"Run now -> run done p95 <= {RUN_P95_MS} ms (per Creator)", p95 is not None and p95 <= RUN_P95_MS,
              budget=True, p95_ms=None if p95 is None else round(p95), per_creator=sorted(round(x) for x in lat))
    drawer_sum = ctx.rec.summary("sweep").get("GET /admin/fans/:id/:id", {})
    dp95 = drawer_sum.get("p95_ms")
    ctx.check(f"drawer read during the sweep p95 <= {DRAWER_P95_MS} ms", dp95 is not None and dp95 <= DRAWER_P95_MS,
              budget=True, **drawer_sum)
    ctx.metric("p95_vs_last_green", {"run now to run done": round(p95 or 0), "drawer read": dp95})
    ctx.metric("runs", {a: {"wall_s": round((x["done"] - x["start"]).total_seconds(), 2) if x["done"] else None,
                            **{k: x["stats"].get(k) for k in ("candidates", "attempted", "generated", "skipped_fresh",
                                                               "failed", "capped", "deferred_for_scrape")}}
                        for a in aids for x in runs.get(a, [])[:1]})
    ctx.note(f"{len(aids)} Creators, {len(fans)} seeded fans ({dict(roles)}), {sum(asked.values())} model calls, "
             f"Run now -> done p95 {p95 and round(p95)} ms, drawer p95 {dp95} ms over {sum(reads.values())} reads "
             f"by {len(plans)} tabs")
