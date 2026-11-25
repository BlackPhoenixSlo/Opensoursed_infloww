from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from slop.lib.client import Recorder
from slop.lib.priority_mass_faults import (CANCEL, CRASH, FROZEN, LEG_SCAN, ONCE, REFUSE, REPEAT, RESUME,
                                           ROWS, SETTLED, UI_CREATOR, UI_SEED)
from slop.lib.priority_mass_relay import read_sends
from slop.seed import priority_mass_audience as pma

PROFILE = "agency_inbox"
UI = True
FAULT = "pm-claimed-row-resent-after-crash"
RELAY_ENV = {"SLOP_SUPERVISOR": "1"}
GET_P95_MS = 500
P95_VS_LAST = (1.5, 200)
DM_PER_MIN = 100_000
WRITE_GAP_S = 0.02
LIST_S = 0.05
HANG_S = 900.0
MAX_RECIPIENTS = 5_000  # automations/priority_mass.py MAX_RECIPIENTS
GUARD_H = {"out": 6, "in": 2}
SENSITIVE_BLOCK_MESSAGE = "Please check the contents of the messages"
CANCEL_AFTER = 15
HANG_AT = 0.4
EDGE_S = 60
RUN_TIMEOUT_S = 1500
HEAL_TIMEOUT_S = 60
OF_SEND_ID_BASE = 9_700_000_000_000
EMPTY_LIST = pma.OF_LIST_BASE + 999
SCAN_LIST = pma.OF_LIST_BASE + 998
SCAN_N = 20
SCAN_WORD = "pay pal"
SCAN_TEXT = "tip me on pay  pal, {name}"  # two spaces: the leg's exact scan misses it
LIVE = ("resolving", "running")
UI_TEXT = "hi {name}, thinking of you today"
ROOT = Path(__file__).resolve().parents[2]


def _xlsx(words: list[str]) -> bytes:
    spec = importlib.util.spec_from_file_location("slop_xlsx_io", ROOT / "service" / "xlsx_io.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.write_xlsx([["Sensitive Words"], *[[w] for w in words]], "Sensitive Words")


def _pm_cfg(tmp: Path, hang: dict | None = None) -> None:
    t = tmp / "of-pm.json.tmp"
    t.write_text(json.dumps({"write_gap_s": WRITE_GAP_S, "hang": hang or {}}))
    os.replace(t, tmp / "of-pm.json")


def _legs(q, rid: int) -> Counter:
    return Counter(dict(q("SELECT status, COUNT(*) FROM scheduled_jobs WHERE kind='priority_mass' AND status IN "
                          "('pending','running') AND payload_json=? GROUP BY status", (json.dumps({"run_id": rid}),))))


def _guarded(last_msg: dict[str, list[tuple]], fz: datetime) -> tuple[set[int], set[int]]:
    certain, amb = set(), set()
    for direction, hours in GUARD_H.items():
        cut = fz - timedelta(hours=hours)
        for f, last in last_msg[direction]:
            d = (datetime.fromisoformat(str(last)) - cut).total_seconds()
            if d >= EDGE_S:
                certain.add(f)
            elif d > -EDGE_S:
                amb.add(f)
    return certain, amb


def _last_msg(q, aid: str) -> dict[str, list[tuple]]:
    return {d: q("SELECT fan_id, MAX(created_at) FROM messages WHERE account_id=? AND direction=? "
                 "AND message_id < ? GROUP BY fan_id", (aid, d, OF_SEND_ID_BASE)) for d in GUARD_H}


def _massdm_local(q, aid: str) -> set[int]:
    return {f for (f,) in q("SELECT m.fan_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE "
                            "l.account_id=? AND l.kind='exclude' AND l.name='MASSdmEXCLUDE'", (aid,))}


def _frozen_oracle(of_lists: list[dict], include: list[int], exclude: list[int], local: set[int],
                   last_msg: dict[str, list[tuple]], fz: datetime | None, got: set[int],
                   counts: tuple) -> tuple[bool, dict]:
    by_id = {x["id"]: set(x["members"]) for x in of_lists}
    resolved = set().union(*(by_id[i] for i in include)) - set().union(*(by_id[i] for i in exclude))
    certain, amb = _guarded(last_msg, fz) if fz is not None else (set(), set())
    excl = (local | certain) & resolved
    amb_out = (amb & resolved) - excl - got
    eligible = sorted(resolved - excl - amb_out)
    want = set(eligible[:MAX_RECIPIENTS])
    rc, ec, cc = counts
    ok = (fz is not None and got == want and rc == len(resolved) and ec == len(resolved) - len(eligible)
          and cc == len(eligible) - len(want) and len(got) <= MAX_RECIPIENTS)
    return ok, {"resolved": len(resolved), "excluded": len(resolved) - len(eligible),
                "capped": len(eligible) - len(want), "frozen": len(got), "want": len(want),
                "db_counts": list(counts), "guard": len(certain & resolved), "edge": len(amb & resolved),
                "edge_out": len(amb_out), "missing": sorted(want - got)[:5], "extra": sorted(got - want)[:5]}


def _rows_verdict(rows: dict[int, tuple], of: list[dict], price: float) -> tuple[bool, dict]:
    of_by: dict[int, list[int]] = {}
    for s in of:
        of_by.setdefault(s["fan_id"], []).append(s["id"])
    sent = {f: mid for f, (st, mid, _r) in rows.items() if st == "sent"}
    unknown = {f for f, (st, _m, _r) in rows.items() if st == "unknown"}
    wrong = [f for f, mid in sent.items() if mid not in of_by.get(f, [])]
    orphan = [f for f in of_by if f not in sent and f not in unknown]
    bad_price = [s["fan_id"] for s in of if s["price"] != price]
    return (bool(sent) and not wrong and not orphan and not bad_price,
            {"sent_rows": len(sent), "unknown": len(unknown), "of_fans": len(of_by), "price": price,
             "wrong_id": wrong[:5], "of_without_row": orphan[:5], "wrong_price": bad_price[:5]})


def _run_rows(q, rid: int) -> dict[int, tuple]:
    return {int(f): (st, mid, reason) for f, st, mid, reason in q(
        "SELECT fan_id, status, message_id, reason FROM priority_mass_recipients WHERE run_id=?", (rid,))}


def _scan_setup(q, aid: str, pool, lists: list[dict]) -> dict:
    on_list = set().union(*(x["members"] for x in lists))
    owners = {f for (f,) in q("SELECT fan_id FROM vault_sends WHERE account_id=? AND was_purchased=1 AND "
                              "media_id=?", (aid, pma.MEDIA_ID))}
    certain, amb = _guarded(_last_msg(q, aid), datetime.utcnow())
    fans = sorted(set(pool) - on_list - owners - certain - amb - _massdm_local(q, aid)
                  - {f for (f,) in q("SELECT fan_id FROM blacklist")})[:SCAN_N]
    if not fans:
        raise RuntimeError("LEG_SCAN: no fan of A off every list and exclusion; another --seed")
    return {"id": SCAN_LIST, "name": "slop leg scan", "members": fans}


async def _scan_post(ctx, q, aid: str, priced: dict) -> dict:
    r = await ctx.owner.post("/admin/priority-mass/runs", json={
        "account_id": aid, "text": SCAN_TEXT, "user_lists": [str(SCAN_LIST)], **priced})
    scan = {"create": r.status_code, "rid": int(r.json()["id"]) if r.status_code == 200 else None}
    r = await ctx.owner.post("/admin/sensitive-words/add", json={"words": [SCAN_WORD]})
    scan["add"] = (r.status_code, r.json().get("success_count") if r.status_code == 200 else r.text[:200])
    if scan["rid"] is not None:
        scan["at_add"] = q("SELECT r.status, COUNT(x.fan_id) FROM priority_mass_runs r LEFT JOIN "
                           "priority_mass_recipients x ON x.run_id=r.id WHERE r.id=? GROUP BY r.id",
                           (scan["rid"],))[0]
    return scan


def _scan_verdict(q, scan: dict, of: list[dict], fans: list[int]) -> tuple[bool, dict]:
    st, err = q("SELECT status, last_error FROM priority_mass_runs WHERE id=?", (scan["rid"],))[0]
    rows = Counter(x for (x,) in q("SELECT status FROM priority_mass_recipients WHERE run_id=?", (scan["rid"],)))
    of_n = sum(1 for s in of if s["fan_id"] in fans)
    return (scan["create"] == 200 and scan["add"] == (200, 1) and tuple(scan["at_add"]) == ("resolving", 0)
            and st == "error" and SCAN_WORD in (err or "") and sum(rows.values()) >= 1 and not rows.get("sent")
            and not of_n,
            {**scan, "run_status": st, "last_error": err, "rows": dict(rows), "of_sends": of_n, "fans": len(fans)})


async def _kill_restart_heal(ctx) -> dict:
    log = ctx.out / "relay.log"

    def heals() -> int:
        return log.read_text(errors="replace").count("reconciled_orphans")

    before = heals()
    out = {"killed_at": ctx.stack.crash_relay()}
    _pm_cfg(ctx.stack.tmp)
    t = time.monotonic()
    await asyncio.to_thread(ctx.stack.start_relay)
    out["restart_s"] = round(time.monotonic() - t, 2)
    t = time.monotonic()
    while heals() <= before and time.monotonic() - t <= HEAL_TIMEOUT_S:
        await asyncio.sleep(0.1)
    out["heal_waited_s"] = round(time.monotonic() - t, 2)
    out["healed"] = heals() > before
    return out


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    cs = [c["id"] for c in w.data["creators"]]
    A, B, C = cs[0], cs[1], cs[2]
    roster_a = ctx.param("roster_a", w.size["priority_mass_roster_a"])
    per = int(w.size["fans_per_creator"])
    aud = pma.seed(w, {A: roster_a, B: per, C: per}, priced={A})
    tmp = ctx.stack.tmp
    poll_s = ctx.param("poll_s", 5.0)
    rng = w.rng("scenario:priority-mass")

    def q(sql: str, args=()) -> list[tuple]:
        con = w.sql()
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    (tmp / "of-mass.json").write_text(json.dumps({"list_s": LIST_S}))
    lists = {aid: a["lists"] for aid, a in aud.items()}
    lists[C] = [*lists[C], {"id": EMPTY_LIST, "name": "slop empty", "members": []}]
    scan_list = _scan_setup(q, A, aud[A]["pool"], lists[A])
    lists[A] = [*lists[A], scan_list]
    (tmp / "of-rosters.json").write_text(json.dumps(lists))
    _pm_cfg(tmp)
    r = await ctx.owner.post("/__slop/priority-mass/rosters")
    r.raise_for_status()
    fed, want_fed = r.json().get("lists"), sum(len(v) for v in lists.values())
    if fed != want_fed:
        raise RuntimeError(f"OF lists fed {fed}, want {want_fed}")
    r = await ctx.owner.post("/lanes-panel/config", json={"values": {"OF_DM_PER_MIN": DM_PER_MIN}})
    r.raise_for_status()
    ctx.metric("setup", {"lists_fed": fed, "dm_per_min": DM_PER_MIN, "roster_a": roster_a,
                         "pool": {k: len(v["pool"]) for k, v in aud.items()},
                         "no_row": {k: len(v["no_row"]) for k, v in aud.items()}})

    added = await ctx.owner.post("/admin/sensitive-words/add", json={"words": ["Venmo", "cash  app"]})
    imported = await ctx.owner.post("/admin/sensitive-words/import", files={"file": (
        "words.xlsx", _xlsx(["WhatsApp", "telegram me"]),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    bad_texts = ["send it on VENMO babe", "my Cash\napp is open", "add me on whatsapp?", "Telegram   me tonight"]
    refusals = []
    for t in bad_texts:
        r = await ctx.owner.post("/admin/priority-mass/runs", json={
            "account_id": C, "text": t, "user_lists": [str(EMPTY_LIST)]})
        refusals.append((r.status_code, r.json().get("detail") if r.status_code != 200 else None))
    rows_bad = q(f"SELECT COUNT(*) FROM priority_mass_runs WHERE text IN ({','.join('?' * len(bad_texts))})",
                 [t.strip() for t in bad_texts])[0][0]
    ctx.check(REFUSE, added.status_code == 200 and added.json().get("success_count") == 2
              and imported.status_code == 200 and imported.json().get("success_count") == 2
              and all(400 <= s < 500 and d == SENSITIVE_BLOCK_MESSAGE for s, d in refusals) and rows_bad == 0,
              add=added.text[:200], imported=imported.text[:200], refusals=refusals, run_rows=rows_bad)

    def body(aid: str, text: str, priced: bool = False) -> dict:
        a = aud[aid]
        return {"account_id": aid, "text": text, "user_lists": [str(x) for x in a["include"]],
                "excluded_user_lists": a["exclude"],
                **({"price": 5, "media_files": [pma.MEDIA_ID], "previews": []} if priced else {})}

    bodies = {A: body(A, "hey {name}, something just for you 💌", priced=True),
              B: body(B, "missed you {name}!"), C: body(C, "good morning {name} ☀️")}
    runs: dict[str, int] = {}
    for aid in (A, B, C):
        r = await ctx.owner.post("/admin/priority-mass/runs", json=bodies[aid])
        r.raise_for_status()
        runs[aid] = int(r.json()["id"])
    again = await ctx.owner.post("/admin/priority-mass/runs", json=bodies[A])
    n_a = q("SELECT COUNT(*) FROM priority_mass_runs WHERE account_id=? AND text=?", (A, bodies[A]["text"]))[0][0]
    ctx.check(REPEAT, again.status_code == 409 and n_a == 1, http=again.status_code, rows=n_a)

    def run_status(rid: int) -> str:
        return q("SELECT status FROM priority_mass_runs WHERE id=?", (rid,))[0][0]

    users = max(1, ctx.users)
    watch = [A, B, C]

    def shares() -> list:
        return [ctx.owner.share(limits=2) for _ in range(users)]

    https = shares()
    leg_rec = Recorder()  # legs: long by design, and one dies with the relay
    legs_http = ctx.owner.share(rec=leg_rec, limits=8)
    up = asyncio.Event()
    up.set()
    frozen_at: dict[str, datetime] = {}
    a_frozen = asyncio.Event()
    hang_ready = asyncio.Event()
    leg_log: list[dict] = []

    async def poll(stop: asyncio.Event) -> None:
        async def one(u: int) -> None:
            aid = watch[u % len(watch)]
            await asyncio.sleep(rng.uniform(0, poll_s))
            while not stop.is_set():
                try:
                    await https[u].get(f"/admin/priority-mass/runs?account_id={aid}")
                except httpx.HTTPError:
                    pass
                try:
                    await asyncio.wait_for(stop.wait(), poll_s * rng.uniform(0.6, 1.4))
                except asyncio.TimeoutError:
                    pass
        await asyncio.gather(*(one(u) for u in range(users)))

    deadline = time.monotonic() + RUN_TIMEOUT_S
    ended: dict[str, str] = {}

    async def drive(key: str, aid: str, rid: int) -> None:
        while time.monotonic() < deadline:
            await up.wait()
            t0 = time.perf_counter()
            try:
                r = await legs_http.post("/__slop/run-automation", timeout=900, json={
                    "account_id": aid, "kind": "priority_mass", "claim": True})
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
                continue
            res = (r.json().get("result") or {}) if r.status_code == 200 else {"status": f"http {r.status_code}"}
            ms = (time.perf_counter() - t0) * 1000
            leg_log.append({"aid": aid, "ms": ms, "status": res.get("status"), "reason": res.get("reason"),
                            "sent": res.get("sent", 0), "interrupted": res.get("interrupted", 0)})
            if key not in frozen_at:
                fz = q("SELECT MIN(updated_at) FROM priority_mass_recipients WHERE run_id=?", (rid,))[0][0]
                if fz is not None or run_status(rid) not in LIVE:
                    frozen_at[key] = datetime.fromisoformat(str(fz)) if fz else datetime.utcnow()
                    if key == A:
                        a_frozen.set()
                        await hang_ready.wait()
            st = run_status(rid)
            if st not in LIVE and not sum(_legs(q, rid).values()):
                ended[key] = st
                return
            if res.get("status") != "ok":
                await asyncio.sleep(0.25)
        ended[key] = "timeout"

    stop = asyncio.Event()
    pollers = asyncio.create_task(poll(stop))
    ctx.rec.stage = "send"
    t_send = time.monotonic()
    drivers = {aid: asyncio.create_task(drive(aid, aid, rid)) for aid, rid in runs.items()}

    cancel: dict = {}

    async def cancel_b() -> None:
        while time.monotonic() < deadline and not drivers[B].done():
            n = sum(1 for s in read_sends(tmp) if s["account_id"] == B)
            if n >= CANCEL_AFTER:
                r = await ctx.owner.post(f"/admin/priority-mass/runs/{runs[B]}/cancel")
                cancel.update(http=r.status_code, b_sends_seen=n, t_done=time.time(), body=r.text[:300])
                cancel["b_sends_at_cancel"] = sum(1 for s in read_sends(tmp)
                                                  if s["account_id"] == B and s["t"] <= cancel["t_done"])
                return
            await asyncio.sleep(0.05)

    canceller = asyncio.create_task(cancel_b())

    await asyncio.wait_for(a_frozen.wait(), 600)
    frozen_a = [f for (f,) in q("SELECT fan_id FROM priority_mass_recipients WHERE run_id=? ORDER BY fan_id",
                                (runs[A],))]
    hang_fan = frozen_a[int(len(frozen_a) * HANG_AT)] if frozen_a else None
    _pm_cfg(tmp, {f"{A}:{hang_fan}": HANG_S} if hang_fan else None)
    hang_ready.set()
    await canceller

    crash: dict = {"hit": False}
    while hang_fan and time.monotonic() < deadline and not drivers[A].done():
        if any(s["account_id"] == A and s["fan_id"] == hang_fan for s in read_sends(tmp)):
            await asyncio.sleep(0.5)
            crash["claimed_at_kill"] = q("SELECT status FROM priority_mass_recipients WHERE run_id=? AND fan_id=?",
                                         (runs[A], hang_fan))[0][0]
            crash["hit"] = True
            break
        await asyncio.sleep(0.1)
    scan: dict = {}
    if crash["hit"]:
        scan = await _scan_post(ctx, q, A, {k: bodies[A][k] for k in ("price", "media_files", "previews")})
        up.clear()
        stop.set()
        await pollers
        crash |= await _kill_restart_heal(ctx)
        old = ctx.owner  # their connections died with the relay
        for h in (*https, legs_http):
            await h.aclose()
        ctx.owner = old.share()
        await old.aclose()
        https = shares()
        legs_http = ctx.owner.share(rec=leg_rec, limits=8)
        ra = await ctx.owner.post(f"/admin/priority-mass/runs/{runs[A]}/resume")
        st_a, legs_a = run_status(runs[A]), _legs(q, runs[A])
        rb = await ctx.owner.post(f"/admin/priority-mass/runs/{runs[B]}/resume")
        crash["resume"] = {"a": ra.status_code, "a_status": st_a, "a_legs": dict(legs_a), "b": rb.status_code}
        ctx.check(RESUME, ra.status_code == 200 and st_a in LIVE and legs_a["pending"] <= 1
                  and sum(legs_a.values()) >= 1 and rb.status_code == 409, **crash["resume"])
        up.set()
        stop = asyncio.Event()
        pollers = asyncio.create_task(poll(stop))
        if scan["rid"] is not None:
            # S's first leg waits for the restart: A's hung leg holds the (A, priority_mass) run lock.
            drivers["scan"] = asyncio.create_task(drive("scan", A, scan["rid"]))
    else:
        ctx.skip(RESUME, "the crash leg did not run")
    await asyncio.gather(*drivers.values())
    stop.set()
    await pollers
    send_s = round(time.monotonic() - t_send, 1)
    ctx.rec.stage = None

    of = read_sends(tmp)
    per_fan = Counter((s["account_id"], s["fan_id"]) for s in of)
    dups = {f"{a}:{f}": n for (a, f), n in per_fan.items() if n > 1}
    ctx.check(ONCE, bool(of) and not dups, of_sends=len(of), fans=len(per_fan), dups=dict(list(dups.items())[:20]))

    rows = {aid: _run_rows(q, rid) for aid, rid in runs.items()}
    status_of = {aid: q("SELECT status, resolved_count, excluded_count, capped_count, last_error "
                        "FROM priority_mass_runs WHERE id=?", (rid,))[0] for aid, rid in runs.items()}

    black = {f for (f,) in q("SELECT fan_id FROM blacklist")}
    frozen_detail, frozen_ok = {}, True
    for aid in runs:
        massdm = _massdm_local(q, aid)
        owners = {f for (f,) in q("SELECT fan_id FROM vault_sends WHERE account_id=? AND was_purchased=1 AND "
                                  "media_id=?", (aid, pma.MEDIA_ID))} if "price" in bodies[aid] else set()
        last_msg = _last_msg(q, aid)
        ok, frozen_detail[aid[-4:]] = _frozen_oracle(
            lists[aid], aud[aid]["include"], aud[aid]["exclude"], black | massdm | owners, last_msg,
            frozen_at.get(aid), set(rows[aid]), tuple(status_of[aid][1:4]))
        frozen_ok &= ok
    ctx.check(FROZEN, frozen_ok, **frozen_detail)
    ctx.metric("frozen", frozen_detail)

    rows_detail, rows_ok = {}, True
    for aid in runs:
        mine = {**rows[aid], **(_run_rows(q, scan["rid"]) if aid == A and scan.get("rid") else {})}
        ok, rows_detail[aid[-4:]] = _rows_verdict(mine, [s for s in of if s["account_id"] == aid],
                                                  bodies[aid].get("price", 0))
        rows_ok &= ok
    ctx.check(ROWS, rows_ok, **rows_detail)

    hf = rows[A].get(hang_fan) if hang_fan else None
    ctx.check(CRASH, crash["hit"] and crash.get("healed") and crash.get("claimed_at_kill") == "claimed"
              and hf is not None and hf[0] == "unknown" and hf[2] == "interrupted"
              and per_fan.get((A, hang_fan), 0) == 1,
              hang_fan=hang_fan, row=hf, of_sends=per_fan.get((A, hang_fan), 0),
              **{k: v for k, v in crash.items() if k != "resume"})

    left = {aid[-4:]: dict(Counter(st for st, _m, _r in rows[aid].values() if st in ("pending", "claimed")))
            for aid in (A, C)}
    ctx.check(SETTLED, all(status_of[aid][0] == "done" for aid in (A, C)) and not any(left.values())
              and ended.get(A) == "done" and ended.get(C) == "done",
              runs={aid[-4:]: status_of[aid][0] for aid in runs}, left=left, ended=ended)

    t_c = cancel.get("t_done")
    after = [s for s in of if s["account_id"] == B and t_c is not None and s["t"] > t_c]
    bst = Counter(st for st, _m, _r in rows[B].values())
    skipped_c = sum(1 for st, _m, r in rows[B].values() if st == "skipped" and r == "cancelled")
    ctx.check(CANCEL, cancel.get("http") == 200 and status_of[B][0] == "cancelled" and not bst.get("pending")
              and not bst.get("claimed") and skipped_c > 0 and len(after) <= 1,
              cancel={k: v for k, v in cancel.items() if k != "body"}, rows=dict(bst), skipped_by_cancel=skipped_c,
              sends_after=len(after))

    if not crash["hit"]:
        ctx.skip(LEG_SCAN, "the crash leg did not run")
    elif scan.get("rid") is None:
        ctx.check(LEG_SCAN, False, **scan)
    else:
        ok, detail = _scan_verdict(q, scan, [s for s in of if s["account_id"] == A], scan_list["members"])
        ctx.check(LEG_SCAN, ok, **detail, ended=ended.get("scan"))

    leg_5xx, leg_599 = leg_rec.count(lambda s: 500 <= s < 599), leg_rec.count(lambda s: s == 599)
    ctx.check("legs: no 5xx, a transport error only for the leg in flight at the SIGKILL",
              leg_5xx == 0 and leg_599 <= (len(runs) if crash["hit"] else 0),
              five_xx=leg_5xx, transport=leg_599, errors=leg_rec.errors[:10])

    p95s = {}
    route = "GET /admin/priority-mass/runs"
    summ = ctx.rec.summary().get(route)
    name = f"p95 {route} <= {GET_P95_MS}ms"
    if summ:
        p95s[route] = summ["p95_ms"]
        ctx.check(name, summ["p95_ms"] <= GET_P95_MS, budget=True, p95=summ["p95_ms"], n=summ["n"])
    else:
        ctx.skip(name, "no samples")
    per_fan_ms = Recorder()
    for x in leg_log:
        if x["aid"] == A and x["status"] == "ok" and x["sent"]:
            per_fan_ms.add("leg/fan", 200, x["ms"] / x["sent"])
    if per_fan_ms.calls:
        p95s["A leg ms per fan sent"] = per_fan_ms.summary()["leg/fan"]["p95_ms"]
    ctx.metric("p95_vs_last_green", p95s)
    sent_a = sum(1 for st, _m, _r in rows[A].values() if st == "sent")
    ctx.metric("priority_mass", {
        "runs": {aid[-4:]: {"id": rid, "status": status_of[aid][0], "rows": dict(Counter(
            st for st, _m, _r in rows[aid].values()))} for aid, rid in runs.items()},
        "of_sends": len(of), "send_s": send_s, "a_fans_per_s": round(sent_a / send_s, 1) if send_s else None,
        "legs": len(leg_log), "legs_by_status": dict(Counter(f"{x['status']}:{x.get('reason')}" for x in leg_log)),
        "interrupted": sum(x["interrupted"] or 0 for x in leg_log), "ended": ended, "crash": crash,
        "leg_http": leg_rec.summary()})

    ui_runs = "UI: Priority mass messages lists A's run with its sent / total as the DB counts"
    ui_word = "UI: a word added in Sensitive words' Add dialog is listed and refuses a run"
    ui_listed = "UI: a run launched from the composer is listed Done with its sent / total as the DB counts"
    if ctx.app is None:
        for n in (ui_runs, ui_word, UI_SEED, ui_listed, UI_CREATOR):
            ctx.skip(n, "--no-ui")
    else:
        await _ui(ctx, A, C, runs[A], q, ui_runs, ui_word)
        await _ui_creator(ctx, C, w.data["creators"])
        await _ui_seed(ctx, B, lists[B], aud[B], q, ui_listed)
    for h in (*https, legs_http):
        await h.aclose()


async def _runs_tab(ctx, page, aid: str):
    await page.goto(f"{ctx.app}/growth/smart-messages?tab=mass", wait_until="domcontentloaded", timeout=180_000)
    await page.get_by_role("tab", name="Priority mass messages").click(timeout=120_000)
    picker = page.locator(f"select:has(option[value='{aid}'])").first
    await picker.wait_for(timeout=60_000)
    return picker


async def _run_listed(picker, page, aid: str, line: str, status: str) -> bool:
    await picker.select_option(aid)
    rows = page.get_by_role("listitem").filter(has_text=status)
    try:
        await rows.get_by_text(re.compile(rf"^{re.escape(line)}( ·|$)")).first.wait_for(timeout=60_000)
        return True
    except Exception:  # noqa: BLE001 — recorded as the caller's check failure
        return False


async def _ui(ctx, A: str, C: str, rid: int, q, ui_runs: str, ui_word: str) -> None:
    from slop.actors import ui

    counts = Counter(st for (st,) in q("SELECT status FROM priority_mass_recipients WHERE run_id=?", (rid,)))
    line = f"{counts.get('sent', 0):,} of {sum(counts.values()):,} sent"
    word = "onlyfriends"
    async with ui.owner_browser(ctx) as page:
        picker = await _runs_tab(ctx, page, A)
        await ui.shot(ctx, page, "smart-messages-1-priority-tab")
        shown = await _run_listed(picker, page, A, line, "Done")
        await ui.shot(ctx, page, "smart-messages-2-run-settled")
        ctx.check(ui_runs, shown, line=line, counts=dict(counts))

        before = (await ctx.owner.get("/admin/sensitive-words")).json().get("words", [])
        await page.goto(f"{ctx.app}/growth/sensitive-words", wait_until="domcontentloaded", timeout=180_000)
        await page.get_by_text(f"Total: {len(before)}").first.wait_for(timeout=60_000)
        await page.get_by_role("button", name="Add Sensitive Word").click()
        await page.get_by_label("Sensitive word 1").fill(word)
        await ui.shot(ctx, page, "sensitive-words-1-add-dialog")
        await page.get_by_role("button", name="Save").click()
        listed = True
        try:
            await page.get_by_text(f"Total: {len(before) + 1}").first.wait_for(timeout=30_000)
            await page.get_by_role("dialog").wait_for(state="hidden", timeout=30_000)
            await page.get_by_role("tab", name=word[0].upper(), exact=True).click(timeout=10_000)
            await page.get_by_role("list", name="Sensitive words").get_by_text(word, exact=True).first.wait_for(
                timeout=30_000)
        except Exception:  # noqa: BLE001
            listed = False
        await page.wait_for_timeout(1_000)
        await ui.shot(ctx, page, "sensitive-words-2-saved")
    after = (await ctx.owner.get("/admin/sensitive-words")).json().get("words", [])
    r = await ctx.owner.post("/admin/priority-mass/runs", json={
        "account_id": C, "text": "join me on OnlyFriends", "user_lists": [str(EMPTY_LIST)]})
    detail = r.json().get("detail") if r.status_code != 200 else None
    rows = q("SELECT COUNT(*) FROM priority_mass_runs WHERE text=?", ("join me on OnlyFriends",))[0][0]
    ctx.check(ui_word, listed and word in after and 400 <= r.status_code < 500 and detail == SENSITIVE_BLOCK_MESSAGE
              and rows == 0, listed=listed, words=after, http=r.status_code, detail=detail, run_rows=rows)


async def _ui_creator(ctx, C: str, creators: list[dict]) -> None:
    from slop.actors import ui

    nick = next(c["nickname"] for c in creators if c["id"] == C)
    seen: dict[str, str] = {}
    sends: list[dict] = []

    async def queue_route(route):
        if route.request.method == "POST":
            sends.append({"account": route.request.headers.get("x-account-id"), "body": route.request.post_data_json})
        await route.abort()

    async with ui.owner_browser(ctx) as page:
        await page.route(lambda u: urlsplit(u).path == "/api/of/v2/messages/queue", queue_route)
        await ui.accept_confirms(page)
        await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded", timeout=180_000)
        col = page.get_by_test_id("of-creator-column")
        await col.get_by_role("button", name=re.compile(re.escape(nick))).first.click(timeout=120_000)
        for card, title, slug in (("OF mass message", "New mass message", "of"),
                                  ("Message online fans", "New Mass Online message", "online")):
            await page.get_by_role("button", name="New Message").first.click(timeout=30_000)
            await page.get_by_role("button", name=re.compile(rf"^{re.escape(card)}")).first.click(timeout=30_000)
            await ui.shot(ctx, page, f"sm-creator-{slug}-1-card-picked")
            await page.get_by_role("button", name="Next", exact=True).click(timeout=10_000)
            dlg = page.get_by_role("dialog", name=title)
            await dlg.wait_for(timeout=120_000)
            post_as = dlg.locator("select").first
            try:
                await page.wait_for_function("([el, v]) => el && el.value === v",
                                             arg=[await post_as.element_handle(), C], timeout=15_000)
            except Exception:  # noqa: BLE001 — recorded as UI_CREATOR's failure
                pass
            seen[slug] = await post_as.input_value()
            await ui.shot(ctx, page, f"sm-creator-{slug}-2-composer-open")
            if slug == "of":
                await dlg.get_by_role("textbox").first.fill("slop sm creator check")
                try:
                    async with page.expect_request(lambda r: r.method == "POST"
                                                   and urlsplit(r.url).path == "/api/of/v2/messages/queue",
                                                   timeout=30_000):
                        await dlg.get_by_role("button", name="Broadcast", exact=True).click(timeout=30_000)
                except Exception:  # noqa: BLE001 — no send recorded: UI_CREATOR's failure
                    pass
            await dlg.get_by_role("button", name="Cancel").click(timeout=10_000)
            await dlg.wait_for(state="hidden", timeout=30_000)
    (ctx.out / "sm-creator-sends.json").write_text(json.dumps(sends, indent=2))
    ctx.check(UI_CREATOR, seen == {"of": C, "online": C} and [x["account"] for x in sends] == [C],
              picked=C, nickname=nick, post_as=seen, sent_as=[x["account"] for x in sends])


async def _ui_seed(ctx, B: str, of_lists: list[dict], aud_b: dict, q, ui_listed: str) -> None:
    from slop.actors import ui

    massdm = next(x for x in of_lists if x["id"] == aud_b["massdm_of"])
    vip = next(x for x in of_lists if x["id"] == aud_b["include"][0])
    members = set(massdm["members"])
    tmp = ctx.stack.tmp
    before = {s["fan_id"] for s in read_sends(tmp) if s["account_id"] == B}
    black = {f for (f,) in q("SELECT fan_id FROM blacklist")}
    certain, amb = _guarded(_last_msg(q, B), datetime.utcnow())
    witness = sorted(members & set(vip["members"]) - before - black - _massdm_local(q, B) - certain - amb)
    if not witness:
        raise RuntimeError("UI_SEED: no MASSDMEXCLUDE member the UI run would message but for the list "
                           "(B's API run sent them all, or blacklist / guard); another --seed")
    bodies: list[dict] = []
    answered: Counter = Counter()

    async def of_lists_route(route):
        aid = route.request.headers.get("x-account-id") or ""
        answered[aid] += 1
        rows = [{"id": x["id"], "name": x["name"], "type": "custom", "usersCount": len(x["members"])}
                for x in (of_lists if aid == B else [])]
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps({"list": rows, "hasMore": False}))

    async def runs_route(route):
        if route.request.method == "POST":
            bodies.append(route.request.post_data_json)
        await route.continue_()

    def path_is(path: str):
        return lambda u: urlsplit(u).path == path

    def box(dlg, name: str, side: int):
        return dlg.get_by_role("checkbox", name=re.compile(rf"^{re.escape(name)}")).nth(side)

    pre_ticked, status, t_launch, listed, rid = False, None, None, False, None
    line, counts = "", Counter()
    async with ui.owner_browser(ctx) as page:
        await page.route(path_is("/api/of/v2/lists"), of_lists_route)
        await page.route(path_is("/admin/priority-mass/runs"), runs_route)
        await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded", timeout=180_000)
        await page.get_by_role("button", name="New Message").first.click(timeout=120_000)
        await page.get_by_role("button", name=re.compile(r"^Priority mass message")).first.click(timeout=30_000)
        await page.get_by_role("button", name="Next", exact=True).click(timeout=10_000)
        dlg = page.get_by_role("dialog", name="Priority mass message")
        await dlg.wait_for(timeout=60_000)
        await dlg.locator("select").first.select_option(B, timeout=30_000)
        await box(dlg, vip["name"], 0).wait_for(timeout=60_000)
        excl = box(dlg, "MASSDMEXCLUDE", 1)
        try:
            await page.wait_for_function("(b) => b && b.checked", arg=await excl.element_handle(), timeout=15_000)
        except Exception:  # noqa: BLE001 — recorded as UI_SEED's failure
            pass
        pre_ticked = await excl.is_checked()
        await box(dlg, vip["name"], 0).click()
        await dlg.get_by_label("Message").fill(UI_TEXT)
        await ui.shot(ctx, page, "priority-mass-ui-1-massdm-preticked")
        t_launch = time.time()
        async with page.expect_response(lambda r: r.request.method == "POST"
                                        and urlsplit(r.url).path == "/admin/priority-mass/runs",
                                        timeout=30_000) as resp:
            await dlg.get_by_role("button", name="Send", exact=True).click(timeout=30_000)
        status = (await resp.value).status
        await dlg.wait_for(state="hidden", timeout=30_000)

        row = q("SELECT id FROM priority_mass_runs WHERE account_id=? AND text=?", (B, UI_TEXT))
        rid = row[0][0] if row else None
        deadline = time.monotonic() + RUN_TIMEOUT_S
        while rid is not None and time.monotonic() < deadline:
            st = q("SELECT status FROM priority_mass_runs WHERE id=?", (rid,))[0][0]
            if st not in LIVE and not sum(_legs(q, rid).values()):
                break
            await ctx.owner.post("/__slop/run-automation", timeout=900, json={
                "account_id": B, "kind": "priority_mass", "claim": True})
            await asyncio.sleep(0.1)

        counts = Counter(st for (st,) in q("SELECT status FROM priority_mass_recipients WHERE run_id=?", (rid,)))
        line = f"{counts.get('sent', 0):,} of {sum(counts.values()):,} sent"
        listed = await _run_listed(await _runs_tab(ctx, page, B), page, B, line, "Done")
        await ui.shot(ctx, page, "priority-mass-ui-2-run-settled")
    (ctx.out / "priority-mass-ui-body.json").write_text(json.dumps(bodies, indent=2))

    run = q("SELECT status, audience_json FROM priority_mass_runs WHERE id=?", (rid,)) if rid else []
    frozen = {f for (f,) in q("SELECT fan_id FROM priority_mass_recipients WHERE run_id=?", (rid,))} if rid else set()
    of_new = {s["fan_id"] for s in read_sends(tmp) if s["account_id"] == B and s["t"] >= (t_launch or 0)}
    b = bodies[0] if bodies else {}
    stored = json.loads(run[0][1]) if run else {}
    mid = str(massdm["id"])
    ctx.check(ui_listed, listed and bool(run) and run[0][0] == "done", line=line, counts=dict(counts),
              run_status=run[0][0] if run else None)
    ctx.check(UI_SEED, pre_ticked and status == 200 and len(bodies) == 1
              and b.get("excluded_user_lists") == [mid]
              and b.get("user_lists") == ["fans", "following", str(vip["id"])]
              and [str(x) for x in stored.get("excluded_user_lists") or []] == [mid]
              and bool(of_new) and not (frozen & members) and not (of_new & members),
              pre_ticked=pre_ticked, http=status, posts=len(bodies),
              body={k: b.get(k) for k in ("account_id", "user_lists", "excluded_user_lists")},
              row_audience=stored, massdm_list=mid, members=len(members), witness=len(witness),
              frozen=len(frozen), frozen_members=sorted(frozen & members)[:10], of_sends=len(of_new),
              of_sent_members=sorted(of_new & members)[:10], lists_answered=dict(answered))
