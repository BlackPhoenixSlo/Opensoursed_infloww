"""OnlyFans ledger chargeback phase, scan-settle helpers, and time parsing."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from slop.lib.ledger_faults import CB_CALLS, CB_MONEY, CB_OPEN, CB_REPOLL, CB_UNMATCHED
from slop.lib.relay_telemetry import flushed_log, writers

SETTLE_S = 90


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse(s) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)


async def _ticks_ended(ctx, creators: list[str], timeout_s: float = 30.0) -> tuple[bool, str]:
    """relay.log once every ledger scan that started has ended for each Creator (its
    `ingest_tx_scan_start` matched by an `ingest_tx_scan_end` or `ingest_tx_scan_failed`), twice
    0.3 s apart: settle_scans returns when the last scan's status is `ok`, which `_mark_success`
    stamps before the disputes poll and the scan_end line."""
    t0, prev = time.time(), None
    while True:
        text = (ctx.out / "relay.log").read_text(errors="replace")
        state = tuple((text.count(f"ingest_tx_scan_start account={a} "),
                       text.count(f"ingest_tx_scan_end account={a} ") + text.count(f"ingest_tx_scan_failed account={a}"))
                      for a in creators)
        if all(s == e for s, e in state) and state == prev:
            return True, text
        if time.time() - t0 > timeout_s:
            return False, text
        prev = state
        await asyncio.sleep(0.3)


CB_SALES = {  # name -> (Creator index, cents, seconds before the phase, ledger text, paymentType)
    "a1_ledger_and_dispute": (1, 1234, 30 * 60, "Payment for message from", "chat_messages"),
    "b_dispute_only_aged_out": (1, 3456, 2 * 86400, "Payment for message from", "chat_messages"),
    "c_open": (1, 4567, 50 * 60, "Tip from", "tips"),
    "e1_pair_kept": (2, 999, 2 * 86400, "Tip from", "tips"),
    "e2_pair_disputed": (2, 999, 2 * 86400 - 1, "Tip from", "tips"),   # same fan as e1, 1 s later
}
CB_REVERSED = ("a1_ledger_and_dispute", "b_dispute_only_aged_out", "e2_pair_disputed")
CB_APPLIED = 2   # b, e2: a1's ledger undo lands first in the same walk, so its dispute finds it reversed


CB_CHECKS = (CB_MONEY, CB_OPEN, CB_UNMATCHED, CB_REPOLL, CB_CALLS)


async def run_chargebacks(ctx, w, creators: list[str], ledger, used: set) -> None:
    """OF's disputes list against the real refresh walk (README.attribution.md, the module
    docstring's chargebacks phase). Step 1: the phase's sales land in the fake ledger (status
    done) and two scans per Creator ingest them; then OF's ledger window drops b and the e pair
    (the latest n-1 / n-2 rows: they are the oldest). Step 2: the ledger shows a1 `undo`; the disputes list gets a1,
    b (undo), c (done: open), d (undo, a sale never in the ledger) and e2 (undo, its twin e1
    1 s earlier, same fan and amount); two scans per Creator. Step 3: two more scans re-poll
    the same disputes. No sale is disputed while the ledger still calls it `done`: OF's two
    lists show the same payment's status, and that state (the walk reinstates, the poll
    re-deducts, every walk) is the product's documented "lifetime follows status both ways"."""
    service_dir = str(Path(__file__).resolve().parents[2] / "service")
    if service_dir not in sys.path:
        sys.path.append(service_dir)
    from transaction_ingest_decide import _NON_REVENUE_STATUSES

    names = [*CB_CHECKS]
    C = len(creators)
    X, Y = creators[1 % C], creators[2 % C]
    free = {aid: [f for f in w.data["fans"][aid] if (aid, f["id"]) not in used] for aid in {X, Y}}
    if C < 3 or len(free[X]) < 3 or len(free[Y]) < 2:
        for n in names:
            ctx.skip(n, f"needs 3 Creators with 3 / 2 unused fans: { {a: len(v) for a, v in free.items()} }")
        return
    pick = {a: iter(free[a]) for a in free}
    fan_of = {"a1_ledger_and_dispute": next(pick[X])["id"], "b_dispute_only_aged_out": next(pick[X])["id"],
              "c_open": next(pick[X])["id"]}
    fan_of["e1_pair_kept"] = fan_of["e2_pair_disputed"] = next(pick[Y])["id"]
    fan_d = next(pick[Y])["id"]
    aid_of = {k: creators[v[0] % C] for k, v in CB_SALES.items()}
    owner, out = ctx.owner, ctx.stack.tmp / "of-chargebacks.jsonl"
    t0 = now().replace(microsecond=0)
    sec = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")   # OF's ledger and disputes: whole seconds

    def con_rows() -> tuple[dict, dict, dict]:
        con = w.sql()
        try:
            rows = {str(p): (st, int(c), int(f)) for p, st, c, f in con.execute(
                "SELECT provider_transaction_id, status, amount_cents, fan_id FROM transactions "
                "WHERE account_id IN (?, ?) AND provider_transaction_id IS NOT NULL", (X, Y))}
            life = {(str(a), int(f)): v or 0 for a, f, v in con.execute(
                "SELECT account_id, fan_id, lifetime_spend_cents FROM fans WHERE account_id IN (?, ?)", (X, Y))}
            count = {str(a): n for a, n in con.execute(
                "SELECT account_id, COUNT(*) FROM transactions WHERE account_id IN (?, ?) GROUP BY account_id",
                (X, Y))}
        finally:
            con.close()
        return rows, life, count

    async def snap(step: str) -> dict:
        settled = await settle_scans(owner, creators)
        ticks_ended, text = await _ticks_ended(ctx, creators)
        try:
            text = await flushed_log(ctx) or text
        except TimeoutError:
            pass
        rows, life, count = con_rows()
        led = (await owner.get("/__slop/ledger")).json()
        return {"step": step, "settled": settled, "ticks_ended": ticks_ended, "text": text, "rows": rows, "life": life, "count": count,
                "cb_txns": writers(text).get("ledger-chargebacks", 0),
                "applied": text.count("ingest_cb_applied account="), "cb_calls": led.get("cb_calls", {})}

    # Step 1: the sales, ingested by the real walk.
    _, life0, _ = con_rows()
    sale_row: dict[str, dict] = {}
    for name, (_ci, cents, ago, what, _pt) in CB_SALES.items():
        ledger.add(aid_of[name], fan_of[name], cents, t0, what, created=sec(t0 - timedelta(seconds=ago)))
        sale_row[name] = dict(ledger.last)
    s1 = await snap("ingested")
    # b, and the e pair, age out of OF's ledger window (each the oldest of its Creator): only the
    # disputes list can reverse them, so the pair is told apart by the matcher alone.
    await owner.post("/__slop/ledger", json={"latest": {X: ledger.per_aid[X] - 1, Y: ledger.per_aid[Y] - 2}})

    def dispute(name: str | None, status: str, ago_s: int, *, row: dict | None = None, ptype: str = "") -> dict:
        row = row or sale_row[name]
        pay = {k: v for k, v in row.items() if k not in ("payoutPendingDays", "refundReason", "id")}
        pid = hashlib.md5(f"cb{row['id']}".encode()).hexdigest()   # OF's payment id is not the ledger's
        return {"id": 0, "createdAt": sec(t0 - timedelta(seconds=ago_s)),
                "paymentType": ptype or CB_SALES[name][4], "payment": {**pay, "id": pid, "status": status}}

    # Step 2: OF reverses them.
    ledger.put(X, {**sale_row["a1_ledger_and_dispute"], "status": "undo", "refundReason": "agent"})
    d_row = {"id": "never-ingested", "user": {"id": fan_d}, "amount": 7.77, "currency": "USD", "net": 6.22,
             "fee": 1.55, "vatAmount": 0, "createdAt": sec(t0 - timedelta(days=3)),
             "description": f"Payment for message from u{fan_d}"}
    items = [(X, dispute("a1_ledger_and_dispute", "undo", 600)),
             (X, dispute("b_dispute_only_aged_out", "undo", 3600)), (X, dispute("c_open", "done", 800)),
             (Y, dispute(None, "undo", 7200, row=d_row, ptype="chat_messages")),
             (Y, dispute("e2_pair_disputed", "undo", 900))]
    with out.open("a") as f:
        for aid, item in items:
            f.write(json.dumps({"account_id": aid, "item": item}) + "\n")
    s2 = await snap("disputed")
    # Step 3: the same disputes, re-polled.
    s3 = await snap("re-polled")

    # ---- checks ----
    pid = {k: str(r["id"]) for k, r in sale_row.items()}
    key = lambda k: (aid_of[k], fan_of[k])
    fans_cb = sorted({key(k) for k in CB_SALES})
    want_life = {fk: life0.get(fk, 0) + sum(CB_SALES[k][1] for k in CB_SALES if key(k) == fk and k not in CB_REVERSED)
                 for fk in fans_cb}
    status = {st["step"]: {k: (st["rows"].get(pid[k]) or (None,))[0] for k in CB_SALES} for st in (s1, s2, s3)}
    kept = [k for k in CB_SALES if k not in CB_REVERSED]
    revenue = sum(st_amt[1] for k in CB_SALES if (st_amt := s3["rows"].get(pid[k]))
                  and st_amt[0] not in _NON_REVENUE_STATUSES)
    ingested = all(status["ingested"][k] is not None and status["ingested"][k] not in _NON_REVENUE_STATUSES
                   for k in CB_SALES)
    life_off = [{"fan": fk[1], "lifetime": s3["life"].get(fk), "want": want_life[fk], "before": life0.get(fk)}
                for fk in fans_cb if s3["life"].get(fk) != want_life[fk]]
    ctx.check(CB_MONEY, ingested and all(status["re-polled"][k] == "chargedback" for k in CB_REVERSED)
              and not life_off and revenue == sum(CB_SALES[k][1] for k in kept),
              statuses=status, lifetime_off=life_off, revenue_cents=revenue,
              want_revenue_cents=sum(CB_SALES[k][1] for k in kept))
    c_key = key("c_open")
    ctx.check(CB_OPEN, status["re-polled"]["c_open"] == status["ingested"]["c_open"] not in _NON_REVENUE_STATUSES
              and s3["life"].get(c_key) == s1["life"].get(c_key) == want_life[c_key],
              c_status=[status[st]["c_open"] for st in status], lifetime=[s["life"].get(c_key) for s in (s1, s2, s3)],
              open_lines=s3["text"].count("ingest_cb_open account="))
    d_rows = [p for p, (_st, _c, f) in s3["rows"].items() if f == fan_d]
    ctx.check(CB_UNMATCHED, s3["count"] == s2["count"] == s1["count"] and not d_rows
              and "ingest_cb_poll account=%s" % Y in s3["text"],
              rows_per_creator=[s1["count"], s2["count"], s3["count"]], rows_for_unmatched_fan=d_rows)
    polls_by_step = {a: [s["text"].count(f"ingest_cb_poll account={a} ") for s in (s1, s2, s3)]
                     for a in creators}
    steps_ok = all(s["settled"]["ok"] and s["ticks_ended"] for s in (s1, s2, s3))
    polls_grew = all(p[0] < p[1] < p[2] for p in polls_by_step.values())
    ctx.check(CB_REPOLL, steps_ok and polls_grew and s1["applied"] == 0 and s2["applied"] == CB_APPLIED and s3["applied"] == s2["applied"]
              and 0 < s2["cb_txns"] == s3["cb_txns"] and s3["life"] == s2["life"]
              and status["re-polled"] == status["disputed"],
              applied=[s1["applied"], s2["applied"], s3["applied"]], want_applied=CB_APPLIED,
              steps_ok=steps_ok, polls_by_step=polls_by_step,
              cb_write_txns=[s1["cb_txns"], s2["cb_txns"], s3["cb_txns"]],
              lifetimes_changed=[{"fan": fk[1], "s2": v, "s3": s3["life"].get(fk)}
                                 for fk, v in s2["life"].items() if s3["life"].get(fk) != v][:6])
    text = s3["text"]
    budget = {}
    for a in creators:
        full = len(re.findall(rf"ingest_tx_scan_end account={re.escape(a)} mode=refresh ", text))
        polls = re.findall(rf"ingest_cb_poll account={re.escape(a)} .* pages=(\d+) ", text)
        budget[a] = {"refresh_walks": full, "of_calls": s3["cb_calls"].get(a, 0), "polls": len(polls),
                     "multi_page_polls": sum(p != "1" for p in polls),
                     "errors": text.count(f"ingest_cb_error account={a}")}
    ctx.check(CB_CALLS, steps_ok and polls_grew and all(b["refresh_walks"] > 0 and b["of_calls"] == b["refresh_walks"] == b["polls"]
                            and not b["multi_page_polls"] and not b["errors"] for b in budget.values()),
              per_creator=budget)
    ctx.metric("chargebacks", {"of_calls": s3["cb_calls"], "per_step_of_calls": [s["cb_calls"] for s in (s1, s2, s3)],
                               "applied": [s["applied"] for s in (s1, s2, s3)],
                               "cb_write_txns": [s["cb_txns"] for s in (s1, s2, s3)],
                               "settled": [s["settled"]["ok"] for s in (s1, s2, s3)]})


async def settle_scans(owner, creators: list[str]) -> dict:
    """Per Creator: one scan queued after the last ledger append (A), then another (B), which
    waits on A's tick lock; B started => A and its relink are done."""
    t0 = time.time()

    async def queue(aid: str) -> datetime | None:
        while time.time() - t0 < SETTLE_S:
            at = now()
            r = await owner.post(f"/admin/ingest/transactions/{aid}/run")
            if r.status_code == 202:
                return at
            if r.status_code != 409:
                return None
            await asyncio.sleep(0.2)
        return None

    async def one(aid: str) -> bool:
        if await queue(aid) is None:
            return False
        qb = await queue(aid)
        if qb is None:
            return False
        while time.time() - t0 < SETTLE_S:
            h = next((a for a in (await owner.get("/admin/ingest/transactions/health")).json()["accounts"]
                      if str(a["account_id"]) == str(aid)), None)
            if h and h["last_scan_at"] and parse(h["last_scan_at"]) >= qb and h["current_status"] not in (
                    "refreshing", "backfilling"):
                return True
            await asyncio.sleep(0.2)
        return False

    oks = await asyncio.gather(*(one(a) for a in creators))
    health = (await owner.get("/admin/ingest/transactions/health")).json()["accounts"]
    mine = [a for a in health if str(a["account_id"]) in {str(c) for c in creators}]
    errors = [(a["account_id"], a["last_error"]) for a in mine if a["last_error"]]
    return {"ok": all(oks) and not errors, "inserted": sum(a["rows_inserted_total"] for a in mine),
            "errors": errors, "seconds": round(time.time() - t0, 1)}
