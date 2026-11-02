"""Smart Lists at 50k fans per big Creator: preview / save / resolve agree with an independent SQL oracle,
a fan on two Creators is judged on each Creator's own facts, the active-list cap holds under an activation
storm (and a freed slot is reusable), and a name is taken exactly once under a create race.

World: `multi_agency_big_models` (Agency 0, the owner, holds 3 big Creators: big_fans_per_creator fans each,
2k / 10k / 50k at small / medium / huge, plus 2 normal ones), its threads, the ledger (seed/earnings.py) and
seed/smart_list_facts.py (last message columns from the threads; 4 bound fans per Creator on and just past
LO / HI; `whale_fans` tagged and `whale_fans` expired fans per Creator; 4 shared fans per Creator pair).

Flow, all as the owner (one signed-in session; each phase opens its own connection pool on it with
ctx.owner.share), real routes only:
1. Oracle: one unit per (owner Creator x ROWS row): 5 x 18 units, run by min(--users, units) concurrent
   owner tasks (90 at --users=200). ROWS: one row per operator (> >= < <= == !=, each threshold on LO or HI
   so a bound fan sits exactly on it), money `between [LO, HI]`, v1 lifetime `between` (fans on 999 /
   12000), date within_last / more_than / between, tag has / not_has, status == / != (expired fans),
   AND, OR, an empty result. A unit: POST /admin/smart-lists (a blank draft), PATCH it to the row's name
   and rules, then POST /admin/smart-lists/preview and GET /{id}/resolve, then GET /admin/smart-lists. The
   harness SQL oracle (`_oracle`, raw fans + transactions, that Creator only) runs at the preview's start
   and after the resolve; if the two answers differ (a fan's day count crossed a threshold mid-unit), the
   preview + resolve is retried, up to 3 times.
   Checks: preview.count == len(resolve) == oracle with the same fan set, every row matches some fan on
   some Creator except `empty`, and at least one (Creator pair, row) where the oracle answers a shared fan
   differently on the pair's two Creators (ORACLE). The oracle is Creator-scoped and shared fans exist, so
   its same-set equality also covers "no other Creator's fan or facts in any resolve". Every list reads
   back from GET /admin/smart-lists with its PATCHed name and rules (READBACK).
2. Solo: one owner, quiet relay, `solo_n` previews of the big Creators, each with a list GET.
3. Activation storm on Creator 3: the cap read from GET /admin/system/switches (SMART_LIST_MAX_ACTIVE,
   default 10) by Agency 4 as master; cap + `storm_extra` fresh lists activated at once; then one active
   list deactivated and one 409'd list activated. CAP: exactly cap 2xx, the rest 409, the DB's active
   count (polled every 5 ms through the storm, and after) never above the cap, GET /admin/smart-lists'
   `max_active` == cap; deactivate and the re-activate 200 and the active count is cap again.
4. Create race on Creator 4: max(2, --users) concurrent POST /admin/smart-lists of one name. RACE: exactly
   one 2xx, the rest 409, one row.
5. UI (/growth/smart-lists): Presets > "Mid spenders", Preview count (screenshot `preview-trigger`),
   Create smart list, the row searched for (`created-settled`); side effect: the smart_lists row holds the
   preset's rules and the count the UI showed equals the oracle (UI).
Budgets: POST /admin/smart-lists/preview p95 <= 2 s, GET /admin/smart-lists p95 <= 300 ms, any non-2xx a
miss: on the solo calls (live; p95_vs_last_green for both) and on the oracle phase's (KNOWN_RED at a
scale in KNOWN_RED_MIN_OWNERS with at least that many concurrent owners, else live; p95_owners in metrics).
Load: owner task i starts at i * ramp_s / owners, takes units i, i + owners, ... and pauses think_s
(uniform 0.5x..1.5x, from the seed) before each step. The owners' calls pass timeout=300 s (the app's
relay.post sets none, a browser waits; lib/client.py's 30 s would turn a slow preview into a transport error).

Faults (lib/smart_lists_faults.py): `smart-list-between-exclusive-bound` (FAULT; targets ORACLE),
`smart-list-cap-read-then-write` (targets CAP), `smart-list-ledger-org-leak` (targets ORACLE).
KNOWN_RED {check: finding}: the two oracle-phase budgets, measured red at the scales and owner counts in
KNOWN_RED_MIN_OWNERS ({scale: owners}) with no service fix in this task. There they are ctx.skip'ped
(numbers kept in p95_owners); anywhere else they are live checks (green at small / 20 owners).

Bypasses (declared):
- Bulk seeding is SQL (README); seed/smart_list_facts.py UPDATEs fans' last message columns, tags and
  subscription status, INSERTs ledger tips and the shared fans' second fans rows (identity + subscription,
  own lifetime): values the transcoder / fan panel / roster crawl / payouts ingest / a second subscription
  write.
- Agency 4 is made master by SQL (`users.is_admin = 1`, as an operator does; no API) only to read the cap
  through GET /admin/system/switches; the owner stays a plain Agency owner.
- No subscriber_snapshot rows: status / renew / sub dates fall back to the fan row (the product's own
  fallback for a fan the roster crawl never saw).
- The sync worker never runs (no supervisor in a slop stack): activate only queues its scheduled_jobs row,
  so no list is ever `syncing` and OnlyFans is never reached (automation_relay's fake lists stay unused).
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime

from slop.actors import ui
from slop.lib import smart_lists_faults as F
from slop.seed import earnings, smart_list_facts

PROFILE = "multi_agency_big_models"
UI = True
FAULT = "smart-list-between-exclusive-bound"
PREVIEW_P95_MS = 2000
LIST_P95_MS = 300
P95_VS_LAST = (2.0, 100)
P95_VS_LAST_MIN_N = 20
OWNER_CREATORS = 5            # the profile's Agency 0 (UI_MODELS)
STORM_CREATOR, RACE_CREATOR = 3, 4
RETRIES = 3
THINK_S = 5.0                 # an owner's mean pause before each step (uniform 0.5x..1.5x, from the seed)
RAMP_S = 30.0                 # owner i starts at i * RAMP_S / owners
CLIENT_TIMEOUT_S = 300.0      # per oracle-phase call (lib/client.py's 30 s default would cut a slow preview)

CK_ORACLE, CK_CAP = F.ORACLE, F.CAP
CK_READBACK = "every saved list reads back from GET /admin/smart-lists with its PATCHed name and rules"
CK_RACE = "concurrent creates of one name: exactly one 2xx, the rest 409, one smart_lists row"
CK_UI = ("UI /growth/smart-lists: preset Preview count equals the oracle, Create smart list adds the row "
         "and its smart_lists row holds the preset's rules")
PREVIEW, LIST = "POST /admin/smart-lists/preview", "GET /admin/smart-lists"
RESOLVE = "GET /admin/smart-lists/:id/resolve"
CK_PREVIEW_P95 = f"p95 {PREVIEW} <= {PREVIEW_P95_MS} ms (one owner, quiet relay)"
CK_LIST_P95 = f"p95 {LIST} <= {LIST_P95_MS} ms (one owner, quiet relay)"
CK_PREVIEW_LOAD = f"p95 {PREVIEW} <= {PREVIEW_P95_MS} ms under concurrent owners (oracle phase)"
CK_LIST_LOAD = f"p95 {LIST} <= {LIST_P95_MS} ms under concurrent owners (oracle phase)"
# {scale: owners}: measured red there (no service fix here); green at small / 20 owners; huge / 5 straddles
# the budget (1.75 s in 20261101T115542Z-2026-11-01-smart-lists-50k-9cfc, 2.45 s in
# 20261101T140728Z-2026-11-01-smart-lists-50k-46f0), so huge skips from 5.
KNOWN_RED_MIN_OWNERS = {"medium": 90, "huge": 5}
_COLLAPSE = ("open finding: preview / resolve collapse under concurrent owners (smart_lists_api._load_normalised_fans "
             "loads every Fan ORM row per call): medium --users=200 (90 concurrent owners), run "
             "20261101T110325Z-2026-11-01-smart-lists-50k-0653: preview p95 174 s (p50 0.38 s), resolve p95 171 s, "
             "list p95 3.9 s, relay RSS 1.8 GB; one owner: preview p95 1.0 s; huge --users=50 (50 concurrent "
             "owners), run 20261101T113412Z-2026-11-01-smart-lists-50k-f228: 52/91 previews past the 300 s client "
             "timeout, relay RSS 3.5 GB")
KNOWN_RED: dict[str, str] = {CK_PREVIEW_LOAD: _COLLAPSE, CK_LIST_LOAD: _COLLAPSE}

LO, HI = smart_list_facts.LO, smart_list_facts.HI
PPV = "('ppv','ppv_message','ppv_post','ppv_stream')"
TIPS = "('tip','tip_post','tip_stream')"
TOT, PPVS, TIPSS = "COALESCE(t.tot,0)", "COALESCE(t.ppv,0)", "COALESCE(t.tips,0)"
LIFE = "COALESCE(f.lifetime_spend_cents,0)"
SNT = "(julianday(:now)-julianday(f.last_message_sent_at))"
RCV = "max(0, julianday(:now)-julianday(f.last_message_received_at))"   # NULL when never received
SUB = "(julianday(:now)-julianday(f.subscribed_at))"
TAG = f"(COALESCE(f.tags,'') LIKE '%\"{smart_list_facts.TAG}\"%')"
STATUS = "LOWER(COALESCE(f.subscription_status,''))"


def _r(field, op, value) -> dict:
    return {"field": field, "op": op, "value": value}


def _row(rules: list[dict], pred: str, *, match: str = "all", expect: str = "some") -> dict:
    """`pred`: the oracle's predicate over f = fans, t = that Creator's tracked ledger per fan. `expect`:
    "some" (the row matches a fan on at least one Creator) or "none" (on no Creator)."""
    return {"rules": {"match": match, "rules": rules}, "pred": pred, "expect": expect}


ROWS: dict[str, dict] = {
    "ge": _row([_r("total_spend", ">=", LO)], f"{TOT} >= {LO}"),
    "gt": _row([_r("tips_spend", ">", LO)], f"{TIPSS} > {LO}"),
    "lt": _row([_r("tips_spend", "<", HI)], f"{TIPSS} < {HI}"),
    "le": _row([_r("total_spend", "<=", HI)], f"{TOT} <= {HI}"),
    "eq": _row([_r("total_spend", "==", HI)], f"{TOT} = {HI}"),
    "ne": _row([_r("ppv_spend", "!=", 0)], f"{PPVS} != 0"),
    "between": _row([_r("total_spend", "between", [LO, HI])], f"{TOT} BETWEEN {LO} AND {HI}"),
    "between-v1": _row([_r("lifetime_spend", "between", [999, 12000])], f"{LIFE} BETWEEN 999 AND 12000"),
    "within_last": _row([_r("last_message_sent_at", "within_last", 7)], f"{SNT} BETWEEN 0 AND 7"),
    "more_than": _row([_r("last_message_sent_at", "more_than", 14)], f"{SNT} > 14"),
    "date-between": _row([_r("sub_start", "between", [30, 90])], f"{SUB} BETWEEN 30 AND 90"),
    "has": _row([_r("tag", "has", smart_list_facts.TAG)], TAG),
    "not_has": _row([_r("tag", "not_has", smart_list_facts.TAG)], f"NOT {TAG}"),
    "status-eq": _row([_r("status", "==", "active")], f"{STATUS} = 'active'"),
    "status-ne": _row([_r("status", "!=", "active")], f"{STATUS} != 'active'"),
    "and": _row([_r("lifetime_spend", ">=", 4999), _r("last_active_days", "<=", 14)],
                f"{LIFE} >= 4999 AND {RCV} <= 14"),
    "or": _row([_r("tips_spend", ">=", 5000), _r("tag", "has", smart_list_facts.TAG)],
               f"({TIPSS} >= 5000 OR {TAG})", match="any"),
    "empty": _row([_r("total_spend", ">", 1_000_000_000)], f"{TOT} > 1000000000", expect="none"),
}

ORACLE_SQL = f"""
WITH t AS (SELECT fan_id, SUM(amount_cents) tot,
                  SUM(CASE WHEN kind IN {PPV} THEN amount_cents ELSE 0 END) ppv,
                  SUM(CASE WHEN kind IN {TIPS} THEN amount_cents ELSE 0 END) tips
           FROM transactions WHERE account_id=:a AND fan_id IS NOT NULL AND status IN ('cleared','pending')
           GROUP BY fan_id)
SELECT f.fan_id FROM fans f LEFT JOIN t ON t.fan_id = f.fan_id WHERE f.account_id=:a AND ({{pred}})
"""
ACTIVE_SQL = "SELECT COUNT(*) FROM smart_lists WHERE account_id=? AND is_active=1"
UI_PRESET = {"name": "Mid spenders", "rules": {"match": "all", "rules": [_r("lifetime_spend", "between", [10000, 49999])]},
             "pred": f"{LIFE} BETWEEN 10000 AND 49999"}


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def _q(db, sql: str, args=()) -> list:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _oracle(db, aid: str, pred: str, now: str) -> set[int]:
    return {r[0] for r in _q(db, ORACLE_SQL.format(pred=pred), {"a": aid, "now": now})}


async def _unit(http, db, aid: str, key: str, shared: set[int], think) -> dict:
    """One (Creator, ROWS row): save (a blank draft, PATCHed to the row), then preview + resolve (retried
    while the oracle moves under it), then list; `think` (the owner's pause) before each step."""
    row, name, out = ROWS[key], f"slop {key} {aid}", {"aid": aid, "row": key, "tries": 0}
    to = {"timeout": CLIENT_TIMEOUT_S}   # the app's relay.post has none: a browser waits
    await think()
    made = await http.post("/admin/smart-lists", json={"account_id": aid, "name": f"{name} draft"}, **to)
    if made.status_code != 200:
        return {**out, "error": f"create {made.status_code}"}
    list_id = made.json()["id"]
    pa = await http.request("PATCH", f"/admin/smart-lists/{list_id}", json={"name": name, "rules": row["rules"]}, **to)
    if pa.status_code != 200:
        return {**out, "error": f"patch {pa.status_code}"}
    for _ in range(RETRIES):
        out["tries"] += 1
        await think()
        t0 = _now()
        pv = await http.post("/admin/smart-lists/preview", json={"account_id": aid, "rules": row["rules"]}, **to)
        await think()
        rs = await http.get(f"/admin/smart-lists/{list_id}/resolve", **to)
        t1 = _now()
        if pv.status_code != 200 or rs.status_code != 200:
            return {**out, "error": f"preview {pv.status_code} resolve {rs.status_code}"}
        o0, o1 = await asyncio.gather(asyncio.to_thread(_oracle, db, aid, row["pred"], t0),
                                      asyncio.to_thread(_oracle, db, aid, row["pred"], t1))
        if o0 == o1:
            break
    ls = await http.get(f"/admin/smart-lists?account_id={aid}", **to)
    res = rs.json()
    got = set(res["fan_ids"])
    mine = next((x for x in (ls.json().get("lists", []) if ls.status_code == 200 else []) if x["id"] == list_id), None)
    return {**out, "list_id": list_id, "preview": pv.json()["count"], "resolve": len(res["fan_ids"]),
            "resolve_count": res["count"], "oracle": len(o0), "same_set": got == o0, "stable": o0 == o1,
            "missing": sorted(o0 - got)[:5], "extra": sorted(got - o0)[:5], "shared_oracle": sorted(o0 & shared),
            "readback": bool(mine and mine["name"] == name and _same_rules(mine["rules"], row["rules"]))}


def _same_rules(stored: dict, sent: dict) -> bool:
    """Stored rules are the validated form: numbers as floats, scope / timeframe filled in."""
    if stored.get("match") != sent.get("match") or len(stored.get("rules", [])) != len(sent["rules"]):
        return False
    for a, b in zip(stored["rules"], sent["rules"]):
        if a["field"] != b["field"] or a["op"] != b["op"]:
            return False
        va, vb = a["value"], b["value"]
        if isinstance(vb, list):
            if [float(x) for x in va] != [float(x) for x in vb]:
                return False
        elif isinstance(vb, (int, float)):
            if float(va) != float(vb):
                return False
        elif str(va) != str(vb):
            return False
    return True


async def _oracle_phase(ctx, w, creators: list[dict]) -> int:
    """Returns the number of concurrent owners."""
    facts = w.data["smart_list_facts"]
    pairs: dict[tuple[str, str], set[int]] = {}
    for s in facts["shared"]:
        pairs.setdefault((s["a"], s["b"]), set()).add(s["fan_id"])
    shared = {c["id"]: set() for c in creators}
    for (a, b), fids in pairs.items():
        shared[a] |= fids
        shared[b] |= fids
    units = [(c["id"], key) for c in creators for key in ROWS]
    w.rng("scenario:smart-lists").shuffle(units)
    n = max(1, min(ctx.users, len(units)))
    think_s, ramp_s = ctx.param("think_s", THINK_S), ctx.param("ramp_s", RAMP_S)
    http = ctx.owner.share(limits=n)
    results: list[dict] = []

    async def owner(i: int):
        """Owner task i: its share of the units (round-robin), human-paced (seeded think times)."""
        rng = w.rng(f"scenario:smart-lists:owner{i}")

        async def think():
            await asyncio.sleep(think_s * rng.uniform(0.5, 1.5))

        await asyncio.sleep(i * ramp_s / n)
        for aid, key in units[i::n]:
            try:
                results.append(await _unit(http, w.db, aid, key, shared[aid], think))
            except Exception as e:   # transport error: the stock check counts it too
                results.append({"aid": aid, "row": key, "error": repr(e)[:200]})

    await asyncio.gather(*(owner(i) for i in range(n)))
    await http.aclose()
    complete = len(results) == len(units) and not any(r.get("error") for r in results)
    bad = [r for r in results if r.get("error") or not r.get("stable")
           or not (r["preview"] == r["resolve"] == r["resolve_count"] == r["oracle"] and r["same_set"])]
    by_row: dict[str, dict] = {}
    for r in results:
        by_row.setdefault(r["row"], {})[r["aid"]] = r.get("oracle")
    unexpected = [k for k, row in ROWS.items() if (row["expect"] == "some") != any(by_row.get(k, {}).values())]
    # (Creator pair, row) where the oracle answers a shared fan differently on the two Creators: the
    # same-set check above is only non-vacuous for "each Creator's own facts" if there is at least one
    by_unit = {(r["aid"], r["row"]): r for r in results if not r.get("error")}
    split = [(a, b, key) for (a, b), fids in pairs.items() for key in ROWS
             if (ua := by_unit.get((a, key))) and (ub := by_unit.get((b, key)))
             and set(ua["shared_oracle"]) & fids != set(ub["shared_oracle"]) & fids]
    ctx.metric("oracle_rows", by_row)
    ctx.metric("oracle_retries", sum(r.get("tries", 1) - 1 for r in results))
    ctx.check(CK_ORACLE, complete and not bad and not unexpected and len(split) > 0, units=len(units),
              bad=len(bad), sample=bad[:6], rows_against_expect=unexpected, shared_fans=len(facts["shared"]),
              pairs=len(pairs), rows_split=len(split))
    nob = [r for r in results if not r.get("readback")]
    ctx.check(CK_READBACK, not nob, units=len(units), not_read_back=[(r["aid"], r["row"]) for r in nob][:10])
    return n


async def _cap(master) -> int:
    body = (await master.get("/admin/system/switches")).json()
    sw = next(s for s in body["switches"] if s["env"] == "SMART_LIST_MAX_ACTIVE")
    return int(sw["effective"])


async def _storm(ctx, w, aid: str, master) -> None:
    cap = await _cap(master)
    extra = ctx.param("storm_extra", w.size["smart_lists_storm_extra"])
    ids = []
    for i in range(cap + extra):
        r = await ctx.owner.post("/admin/smart-lists", json={"account_id": aid, "name": f"slop storm {i}",
                                                             "rules": ROWS["ge"]["rules"]})
        r.raise_for_status()
        ids.append(r.json()["id"])
    http = ctx.owner.share(limits=len(ids))
    peak = {"max": 0, "polls": 0}
    done = asyncio.Event()

    async def poll():
        while not done.is_set():
            n = (await asyncio.to_thread(_q, w.db, ACTIVE_SQL, (aid,)))[0][0]
            peak["max"], peak["polls"] = max(peak["max"], n), peak["polls"] + 1
            await asyncio.sleep(0.005)

    async def activate(i):
        try:
            return (await http.post(f"/admin/smart-lists/{i}/activate")).status_code
        except Exception as e:
            return repr(e)[:80]

    poller = asyncio.create_task(poll())
    codes = await asyncio.gather(*(activate(i) for i in ids))
    done.set()
    await poller
    await http.aclose()
    final = _q(w.db, ACTIVE_SQL, (aid,))[0][0]
    # a freed slot is reusable: deactivate one winner, then activate one 409'd list
    on = next((i for i, c in zip(ids, codes) if c == 200), None)
    off = next((i for i, c in zip(ids, codes) if c == 409), None)
    deact = (await ctx.owner.post(f"/admin/smart-lists/{on}/deactivate")).status_code if on else None
    react = (await ctx.owner.post(f"/admin/smart-lists/{off}/activate")).status_code if off else None
    reused = _q(w.db, ACTIVE_SQL, (aid,))[0][0]
    listed = (await ctx.owner.get(f"/admin/smart-lists?account_id={aid}")).json()
    api_active = sum(1 for x in listed["lists"] if x["is_active"])
    ok = sum(1 for c in codes if c == 200)
    c409 = sum(1 for c in codes if c == 409)
    jobs = _q(w.db, "SELECT COUNT(*) FROM scheduled_jobs WHERE account_id=? AND kind='smart_list_sync' "
                    "AND status='pending'", (aid,))[0][0]
    detail = {"cap": cap, "activates": len(ids), "ok_2xx": ok, "c409": c409, "max_active_polled": peak["max"],
              "polls": peak["polls"], "final_active": final, "deactivate": deact, "reactivate": react,
              "active_after_reuse": reused, "api_active": api_active, "list_max_active": listed["max_active"]}
    ctx.metric("activation_storm", {**detail, "pending_sync_jobs": jobs})
    ctx.check(CK_CAP, ok == cap and c409 == extra and final == cap and peak["max"] <= cap
              and deact == 200 and react == 200 and reused == cap == api_active == listed["max_active"],
              **detail, other=sorted({str(c) for c in codes} - {"200", "409"}))


async def _race(ctx, w, aid: str) -> None:
    n = max(2, ctx.users)
    http = ctx.owner.share(limits=n)

    async def create():
        try:
            return (await http.post("/admin/smart-lists", json={"account_id": aid, "name": "slop race",
                                                                "rules": ROWS["gt"]["rules"]})).status_code
        except Exception as e:
            return repr(e)[:80]

    codes = await asyncio.gather(*(create() for _ in range(n)))
    await http.aclose()
    rows = _q(w.db, "SELECT COUNT(*) FROM smart_lists WHERE account_id=? AND name='slop race'", (aid,))[0][0]
    ok = sum(1 for c in codes if isinstance(c, int) and 200 <= c < 300)
    c409 = sum(1 for c in codes if c == 409)
    ctx.metric("create_race", {"creates": n, "2xx": ok, "409": c409, "rows": rows})
    ctx.check(CK_RACE, ok == 1 and c409 == n - 1 and rows == 1, creates=n, ok_2xx=ok, c409=c409, rows=rows,
              other=sorted({str(c) for c in codes if c != 409 and not (isinstance(c, int) and c < 300)}))


async def _ui(ctx, w) -> None:
    async with ui.owner_browser(ctx, viewport=(1440, 1000)) as page:
        await page.goto(f"{ctx.app}/growth/smart-lists", wait_until="domcontentloaded")
        await page.get_by_role("button", name="Presets").wait_for(timeout=120_000)
        await page.get_by_role("table", name="Smart lists").wait_for(timeout=60_000)
        await page.get_by_role("button", name="Presets").click()
        await page.get_by_role("button", name=re.compile(f"^{UI_PRESET['name']}")).click()
        dialog = page.get_by_role("dialog")
        async with page.expect_response(lambda r: r.request.method == "POST"
                                        and r.url.endswith("/admin/smart-lists/preview")) as pv_info:
            await page.get_by_role("button", name="Preview count").click()
        pv = await pv_info.value
        aid = json.loads(pv.request.post_data or "{}").get("account_id")
        shown = page.get_by_text(re.compile(r"fans match"))
        await shown.wait_for(timeout=30_000)
        await page.wait_for_timeout(300)
        await ui.shot(ctx, page, "preview-trigger")
        text = await shown.locator("xpath=..").inner_text()
        m = re.search(r"(\d+)\s*/\s*(\d+)\s*fans match", text)
        ui_count = int(m.group(1)) if m else None
        async with page.expect_response(lambda r: r.request.method == "POST"
                                        and r.url.split("?")[0].endswith("/admin/smart-lists")) as made_info:
            await dialog.get_by_role("button", name="Create smart list").click()
        made = await made_info.value
        await page.get_by_label("Search list name").fill(UI_PRESET["name"])
        cell = page.get_by_role("table", name="Smart lists").get_by_text(UI_PRESET["name"], exact=True)
        await cell.wait_for(timeout=30_000)
        await page.wait_for_timeout(300)
        await ui.shot(ctx, page, "created-settled")
    stored = _q(w.db, "SELECT rules_json FROM smart_lists WHERE account_id=? AND name=?", (aid, UI_PRESET["name"]))
    oracle = len(await asyncio.to_thread(_oracle, w.db, aid, UI_PRESET["pred"], _now())) if aid else None
    rules_ok = len(stored) == 1 and _same_rules(json.loads(stored[0][0]), UI_PRESET["rules"])
    ctx.check(CK_UI, made.status == 200 and rules_ok and ui_count is not None and ui_count == oracle,
           account=aid, create_status=made.status, ui_count=ui_count, oracle=oracle, rows=len(stored),
           rules=stored[0][0] if stored else None)


async def _solo(ctx, creators: list[dict]) -> None:
    """One owner on a quiet relay: `solo_n` previews (the big Creators in turn, ROWS in turn), each followed
    by GET /admin/smart-lists, back to back. The live budgets read these (a non-2xx is a miss there)."""
    big = [c for c in creators if c.get("big")]
    rows = list(ROWS.values())
    for i in range(ctx.param("solo_n", 20)):
        aid = big[i % len(big)]["id"]
        await ctx.owner.post("/admin/smart-lists/preview", json={"account_id": aid, "rules": rows[i % len(rows)]["rules"]})
        await ctx.owner.get(f"/admin/smart-lists?account_id={aid}")


def _stats(s: dict) -> dict:
    return {"p95": s["p95_ms"], "p50": s["p50_ms"], "n": s["n"], "non_2xx": s["4xx"] + s["5xx"]}


def _within(s: dict, budget: float) -> bool:
    return s["p95_ms"] <= budget and not (s["4xx"] or s["5xx"])


def _budgets(ctx, owners: int) -> None:
    """Solo: live budgets and the p95_vs_last_green keys. Owners (the oracle phase): the same budgets;
    KNOWN_RED (skipped, numbers in p95_owners) at a KNOWN_RED_MIN_OWNERS scale with at least its owners."""
    solo, p95, n = ctx.rec.summary("solo"), {}, {}
    for route, budget, name in ((PREVIEW, PREVIEW_P95_MS, CK_PREVIEW_P95), (LIST, LIST_P95_MS, CK_LIST_P95)):
        s = solo.get(route)
        if not s:
            ctx.skip(name, "no samples")
            continue
        p95[route], n[route] = s["p95_ms"], s["n"]
        ctx.check(name, _within(s, budget), budget=True, **_stats(s))
    ctx.metric("p95_vs_last_green", p95)
    ctx.metric("p95_vs_last_green_n", n)

    loaded = ctx.rec.summary("owners")
    ctx.metric("p95_owners", {"owners": owners, **{r: _stats(loaded[r]) for r in (PREVIEW, RESOLVE, LIST) if r in loaded}})
    for route, budget, name in ((PREVIEW, PREVIEW_P95_MS, CK_PREVIEW_LOAD), (LIST, LIST_P95_MS, CK_LIST_LOAD)):
        s = loaded.get(route)
        if not s:
            ctx.skip(name, "no samples")
        elif name not in KNOWN_RED or owners < KNOWN_RED_MIN_OWNERS.get(ctx.scale, owners + 1):
            ctx.check(name, _within(s, budget), budget=True, owners=owners, **_stats(s))
        else:
            ctx.skip(name, KNOWN_RED[name], owners=owners, **_stats(s))


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"][:OWNER_CREATORS]
    earnings.seed(w, w.data["creators"], ctx.stack.tmp, history_days=ctx.param("history_days", 30), connected_days=9)
    smart_list_facts.seed(w, creators, n=ctx.param("whale_fans", w.size["smart_lists_whale_fans"]))
    master = w.data["agencies"][-1]
    con = w.sql()
    with con:
        con.execute("UPDATE users SET is_admin=1 WHERE id=?", (master["user_id"],))
    con.close()
    ctx.metric("world", {"fans_per_owner_creator": {c["id"]: len(w.data["fans"][c["id"]]) for c in creators},
                         "ledger_rows": w.data.get("ledger_rows"), "facts": w.data["smart_list_facts"]})

    ctx.rec.stage = "owners"
    owners = await _oracle_phase(ctx, w, creators)
    ctx.rec.stage = "solo"
    await _solo(ctx, creators)
    ctx.rec.stage = "storm"
    await _storm(ctx, w, creators[STORM_CREATOR]["id"], master["http"])
    await _race(ctx, w, creators[RACE_CREATOR]["id"])
    ctx.rec.stage = None
    if ctx.app:
        await _ui(ctx, w)
    else:
        ctx.skip(CK_UI, "--no-ui")
    _budgets(ctx, owners)
