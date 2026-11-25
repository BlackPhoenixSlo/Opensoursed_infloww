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
OWNER_CREATORS = 5
STORM_CREATOR, RACE_CREATOR = 3, 4
RETRIES = 3
THINK_S = 5.0
RAMP_S = 30.0
# lib/client.py's 30 s default would turn a slow preview into a transport error
CLIENT_TIMEOUT_S = 300.0

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
KNOWN_RED_MIN_OWNERS = {"huge": 20}
_COLLAPSE = ("open finding, perf paused (owner 10-29), projection done: 50k fans per Creator, preview / resolve "
             "still collapse under concurrent owners (every fan normalised + resolved in Python per call): huge "
             "--users=20, run 20261103T090901Z-2026-11-01-smart-lists-50k-babd: preview p95 99 s (p50 11 s), resolve "
             "p95 99 s, list p95 1.8 s; huge --users=50, run 20261103T085813Z-2026-11-01-smart-lists-50k-602d: "
             "preview p95 211 s, list p95 0.9 s, relay RSS 1.7 GB, no request past the 300 s timeout (was 52/91, "
             "3.5 GB); medium / 90 owners green in 5 of 6 runs since the projection (1 red pile-up, run "
             "20261103T091733Z-2026-11-01-smart-lists-50k-607a: preview p95 20 s, list 2.0 s, host load 15)")
KNOWN_RED: dict[str, str] = {CK_PREVIEW_LOAD: _COLLAPSE, CK_LIST_LOAD: _COLLAPSE}

LO, HI = smart_list_facts.LO, smart_list_facts.HI
PPV = "('ppv','ppv_message','ppv_post','ppv_stream')"
TIPS = "('tip','tip_post','tip_stream')"
TOT, PPVS, TIPSS = "COALESCE(t.tot,0)", "COALESCE(t.ppv,0)", "COALESCE(t.tips,0)"
LIFE = "COALESCE(f.lifetime_spend_cents,0)"
SNT = "(julianday(:now)-julianday(f.last_message_sent_at))"
RCV = "max(0, julianday(:now)-julianday(f.last_message_received_at))"
SUB = "(julianday(:now)-julianday(f.subscribed_at))"
TAG = f"(COALESCE(f.tags,'') LIKE '%\"{smart_list_facts.TAG}\"%')"
STATUS = "LOWER(COALESCE(f.subscription_status,''))"


def _r(field, op, value) -> dict:
    return {"field": field, "op": op, "value": value}


def _row(rules: list[dict], pred: str, *, match: str = "all", expect: str = "some") -> dict:
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
    row, name, out = ROWS[key], f"slop {key} {aid}", {"aid": aid, "row": key, "tries": 0}
    to = {"timeout": CLIENT_TIMEOUT_S}
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
        rng = w.rng(f"scenario:smart-lists:owner{i}")

        async def think():
            await asyncio.sleep(think_s * rng.uniform(0.5, 1.5))

        await asyncio.sleep(i * ramp_s / n)
        for aid, key in units[i::n]:
            try:
                results.append(await _unit(http, w.db, aid, key, shared[aid], think))
            except Exception as e:
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
        elif _within(s, budget):
            ctx.check(name, False, finding_closed=f"measured green: drop {ctx.scale!r} from KNOWN_RED_MIN_OWNERS "
                      f"(and the KNOWN_RED entry once no scale is left) ({KNOWN_RED[name]})",
                      owners=owners, **_stats(s))
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
