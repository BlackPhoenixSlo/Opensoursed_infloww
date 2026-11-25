from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from slop.actors import fan_dm, focus, manager, ui
from slop.lib.procmon import pct
from slop.lib.attribution_faults import (AUTO, PPV, SENDER, STAMP, TIP_AFTER, TIP_LEDGER, TIP_WS, TOTALS, WINDOW,
                                         WINDOW330)
from slop.lib.ledger_faults import LEDGER
from slop.lib import ledger_chargebacks, relay_telemetry
from slop.lib.ledger_chargebacks import run_chargebacks, settle_scans
from slop.seed import chatters as chatters_seed
from slop.seed import sales_touches

sys.path.append(str(Path(__file__).resolve().parents[2] / "service"))
from transaction_ingest_decide import _NON_REVENUE_STATUSES  # noqa: E402

PROFILE = "agency_inbox"
UI = True
FAULT = "converters-first-chatter"
# Send route budget is a stress budget: ~99 sends/s at medium --users=200, ~50x chatter-crowd's realistic rate.
E2E_P95_MS = 500
P95_MS = {"GET /admin/stats/per-employee": 1000, "GET /admin/stats/sales-records": 1000,
          "POST /api/of/v2/chats/:id/messages": 1500}
WINDOW_S = 3600
WINDOW_330_S = 3 * 3600 + 30 * 60
TICK_S, READ_S = 1.0, 0.5
THINK_MS = (50, 400)
EPOCH = "1970-01-01T00:00:00Z"
TIP_FRAME_BASE = 9_750_000_000_000  # between fan_dm's bands and sales_touches' 9.8e12
LEDGER_ID_BASE = 7_700_000_000
KINDS = (("ledger_tip", 35), ("ws_tip", 25), ("ppv_ws", 20), ("ppv_ledger", 20))
PPV_KINDS = ("ppv_ws", "ppv_ledger")
LINKED_KINDS = ("ws_tip", *PPV_KINDS)
FALLBACK_LINE = "Shift schedule needs Time tracking on; credited by Converters."
SPECIALS = {
    "edge_in": ([(59, "A")], "ledger_tip"),
    "edge_out": ([(61, "A")], "ledger_tip"),
    "w330_in": ([(209, "A")], "ledger_tip"),
    "w330_out": ([(211, "A")], "ledger_tip"),
    "auto_last": ([(30, "auto")], "ledger_tip"),
    "human_then_auto": ([(50, "A"), (20, "auto")], "ledger_tip"),
    "human_then_mass": ([(50, "A"), (20, "massB")], "ledger_tip"),
    "auto_then_human": ([(40, "auto"), (20, "A")], "ledger_tip"),
    "ws_human_then_auto": ([(50, "A"), (20, "auto")], "ws_tip"),
    "ws_a_then_b": ([(50, "A"), (20, "B")], "ws_tip"),
}
LIVE_SPECIAL = "ppv_a_then_b"
WINDOW_SPECIALS = ("edge_in", "edge_out", "w330_in", "w330_out")
AUTO_SPECIALS = ("auto_last", "human_then_auto", "human_then_mass", "auto_then_human", "ws_human_then_auto")

AGREE = "Employee reports == Sales records summed per Employee, to the cent"
FEE = ("Exclude the 20% OnlyFans fee on: each sale keeps its Employee, credited at OnlyFans' net (else 80% "
       "rounded down); Employee reports == expected to the cent")
SHIFT = ("Shift schedule with Time tracking off: every sale keeps its Converters credit (Sales records and "
         "Employee reports) and the report shows the fallback line")
VERSION = "a Sales change saved effective now (fee excluded) recredits no earlier sale (Employee reports unchanged)"
COUNT = ("nothing dropped: every send and frame 2xx, every payment exactly one sale in Sales records "
         "(a WS tip and its ledger twin are one)")
SCANS = "ledger scans settled: no error, rows inserted == ledger-only payments, every WS tip promoted by its twin"
UI_SAVE = ("Sales settings page: the Converters window shows 1 h 0 min, Save with 3 h 30 min answers 200 and "
           "shows Saved, GET /admin/settings/sales reads converters_window_seconds 12600")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds") + "+00:00"


class Ledger:

    def __init__(self, path):
        self.path, self.n, self.per_aid, self.last = path, 0, Counter(), None

    def add(self, aid: str, fan: int, cents: int, at: datetime, what: str, *, created: str | None = None) -> int:
        self.n += 1
        self.per_aid[aid] += 1
        fee = round(cents * 0.2)
        self.last = {"id": LEDGER_ID_BASE + self.n, "user": {"id": fan}, "amount": cents / 100, "currency": "USD",
                     "createdAt": created or _iso(at), "status": "done", "net": (cents - fee) / 100,
                     "fee": fee / 100, "vatAmount": 0, "description": f"{what} u{fan}"}
        self.put(aid, self.last)
        return cents - fee

    def put(self, aid: str, row: dict) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps({"account_id": aid, "row": row}) + "\n")


def expect(sale: dict, touches: list[dict], window_s: int) -> int | None:
    at, lo = sale["at"], sale["at"] - timedelta(seconds=window_s)
    xs = [t for t in touches if lo <= t["at"] <= at and not (t["auto"] or t["mass"])]
    return max(xs, key=lambda t: (t["at"], t["mid"]))["emp"] if xs else None


def _plan(w, creators: list[str], fans: dict, by_creator: dict, n_ep: int, taken: set) -> list[dict]:
    rng = w.rng("sales-attribution")
    names, weights = [k for k, _ in KINDS], [x for _, x in KINDS]
    eps = []
    for aid in creators:
        pool = [f for f in fans[aid] if f["id"] not in taken]
        rng.shuffle(pool)
        ch = by_creator[aid]
        for f in pool[:n_ep]:
            kind = rng.choices(names, weights)[0]
            steps: list[tuple] = []
            if kind in PPV_KINDS:
                a = rng.choice(ch)
                if rng.random() < 0.3:
                    steps.append(("reply", rng.choice(ch)))
                steps.append(("ppv", a))
                others = [x for x in ch if x != a]
                if others and rng.random() < 0.5:
                    steps.append(("reply", rng.choice(others)))
            elif kind == "ws_tip" and rng.random() < 0.5:
                one = rng.choice(ch)
                steps += [("reply", one)] * rng.randint(1, 3)
            else:
                steps += [("reply", rng.choice(ch)) for _ in range(rng.randint(1, 3))]
            steps.append(("pay",))
            if rng.random() < 0.5:
                steps.append(("reply", rng.choice(ch)))
            eps.append({"aid": aid, "fan": f, "kind": kind, "steps": steps, "cents": rng.randint(300, 5000),
                        "think": [rng.randint(*THINK_MS) / 1000 for _ in steps]})
    rng.shuffle(eps)
    return eps


async def run(ctx) -> None:
    if ctx.users < 2:
        raise ValueError("--users must be >= 2 (the specials need two chatters on Creator 0)")
    w = await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    fans = w.data["fans"]
    C = len(creators)
    n_ep = ctx.param("episodes", w.size["sales_attribution_episodes"])
    owner = ctx.owner

    async def put(tab: str, blob: dict, effective_from: str | None = EPOCH) -> None:
        r = await owner.put(f"/admin/settings/{tab}", json=blob,
                            **({"params": {"effective_from": effective_from}} if effective_from else {}))
        if r.status_code != 200:
            raise RuntimeError(f"PUT /admin/settings/{tab}: {r.status_code} {r.text[:300]}")

    def sales_blob(messages="converters", posts_tips="converters", fee=False, window=WINDOW_S) -> dict:
        return {"exclude_welcome": False, "exclude_of_fee": fee, "multi_employee_shift": False,
                "attribution": {"messages": messages, "posts_tips": posts_tips,
                                "subscriptions_chatter_opt_in": False, "converters_window_seconds": window}}

    async def saved_window():
        r = await owner.get("/admin/settings/sales")
        return r.json()["config"].get("attribution", {}).get("converters_window_seconds") if r.status_code == 200 \
            else f"GET {r.status_code}"

    await put("sales", sales_blob())
    await put("time-tracking", {"enabled": False})

    names = [f"attr-c{k:03d}" for k in range(ctx.users)]
    assign = [sorted({creators[k % C], creators[(k + 1) % C]}) for k in range(ctx.users)]
    recs = await chatters_seed.seed(w, owner, w.user_id, names, account_ids=assign)
    emp = sales_touches.employees(w, recs)
    by_creator = {aid: [k for k, r in enumerate(recs) if aid in r["account_ids"]] for aid in creators}
    chatters = [focus.Chatter(r, r["account_ids"][0]) for r in recs]
    sem = asyncio.Semaphore(20)

    async def login(c):
        async with sem:
            return await c.login(ctx.relay, ctx.rec)

    logins = await asyncio.gather(*(login(c) for c in chatters))
    ctx.check("every chatter signed in with its own login (POST /chatter/login 200)",
              all(s == 200 for s in logins), bad=sum(s != 200 for s in logins), chatters=len(chatters))
    locks = [asyncio.Lock() for _ in chatters]
    frame_locks = {aid: asyncio.Lock() for aid in creators}
    ledger = Ledger(ctx.stack.tmp / "of-ledger.jsonl")
    ledger.path.write_text("")
    (ctx.stack.tmp / "of-chargebacks.jsonl").write_text("")
    pump = owner.share(limits=max(10, C))
    touches: dict[tuple, list[dict]] = defaultdict(list)
    sales: list[dict] = []
    replies: list[dict] = []
    frames: list[dict] = []
    twins: list[tuple] = []
    tip_ids = iter(range(TIP_FRAME_BASE, TIP_FRAME_BASE + 10**9))

    sse = manager.SseListener(owner.share())
    await sse.start()

    async def send(k: int, aid: str, fan_id: int, sale: dict, *, ppv: bool, paid: bool) -> None:
        async with locks[k]:
            r = await chatters[k].reply(aid, fan_id, "slop ppv" if ppv else "slop reply",
                                        price=sale["cents"] / 100 if ppv else 0)
        r.update(chatter=recs[k]["username"], ppv=ppv, after_pay=paid)
        replies.append(r)
        if r["status"] < 300 and r["id"] is not None:
            e = emp[recs[k]["username"]]
            touches[(aid, fan_id)].append({"at": ledger_chargebacks.parse(r["created_at"]), "emp": e, "mid": int(r["id"]),
                                           "auto": False, "mass": False})
            if ppv:
                sale.update(sender=e, ppv_id=int(r["id"]))
            if paid:
                sale["after"] = True
        await asyncio.sleep(0.003)  # strictly after the previous createdAt (ms)

    async def pay(sale: dict, fan: dict) -> None:
        aid, cents, kind = sale["aid"], sale["cents"], sale["kind"]
        await asyncio.sleep(0.003)  # strictly after the previous createdAt (ms)
        if kind in ("ledger_tip", "ppv_ledger"):
            sale["at"] = ledger_chargebacks.now()
            sale["net"] = ledger.add(aid, fan["id"], cents, sale["at"],
                                     "Tip from" if kind == "ledger_tip" else "Payment for message from")
        else:
            async with frame_locks[aid]:
                if kind == "ws_tip":
                    mid = next(tip_ids)
                    fr = fan_dm.frame(mid, fan, "slop tip", tip_dollars=cents / 100)
                    sale["at"] = ledger_chargebacks.parse(fr["api2_chat_message"]["createdAt"])
                else:
                    mid = sale["ppv_id"]
                    fr = fan_dm.purchase_frame(mid, fan, cents / 100)
                    sale["at"] = ledger_chargebacks.parse(fr["purchase"]["openedAt"])
                t0 = time.time() * 1000
                r = await fan_dm.inject(pump, aid, fr)
                frames.append({"kind": kind, "message_id": mid, "status": r.status_code, "t0": t0})
            if kind == "ws_tip":
                twins.append((aid, fan["id"], cents, sale["at"], sale))
        await asyncio.sleep(0.003)  # strictly after the previous createdAt (ms)

    c0 = creators[0]
    rng_s = w.rng("sales-attribution:specials")
    pool0 = list(fans[c0])
    rng_s.shuffle(pool0)
    special_fans = dict(zip((*SPECIALS, LIVE_SPECIAL), pool0))
    kA, kB = by_creator[c0][:2]
    A, B = emp[recs[kA]["username"]], emp[recs[kB]["username"]]
    who = {"A": A, "B": B, "massB": B, "auto": emp["Automation"]}
    t_ref = ledger_chargebacks.now()
    rows = []
    for name, (spec, _kind) in SPECIALS.items():
        for mins, x in spec:
            rows.append({"account_id": c0, "fan_id": special_fans[name]["id"], "employee_id": who[x],
                         "at": t_ref - timedelta(minutes=mins), "mass": x == "massB",
                         **({"automation_kind": "autoreply"} if x == "auto" else {})})
    for t in sales_touches.seed(w, rows):
        touches[(c0, t["fan_id"])].append({"at": t["at"], "emp": t["employee_id"], "mid": t["message_id"],
                                           "auto": t.get("automation_kind") is not None, "mass": bool(t["mass"])})
    for name, (_spec, kind) in SPECIALS.items():
        f = special_fans[name]
        sale = {"aid": c0, "fan": f["id"], "kind": kind, "cents": 1000 + 111 * len(sales), "sender": None,
                "net": None, "special": name, "after": False}
        await pay(sale, f)
        sales.append(sale)
    f = special_fans[LIVE_SPECIAL]
    sale = {"aid": c0, "fan": f["id"], "kind": "ppv_ws", "cents": 1000 + 111 * len(sales), "sender": None,
            "net": None, "special": LIVE_SPECIAL, "after": False, "ppv_id": None}
    await send(kA, c0, f["id"], sale, ppv=True, paid=False)
    await send(kB, c0, f["id"], sale, ppv=False, paid=False)
    if sale["ppv_id"] is not None:
        await pay(sale, f)
        sales.append(sale)

    eps = _plan(w, creators, fans, by_creator, n_ep, {f["id"] for f in special_fans.values()})
    stop = asyncio.Event()

    async def every(s: float, fn) -> int:
        n = 0
        while not stop.is_set():
            await fn()
            n += 1
            try:
                await asyncio.wait_for(stop.wait(), s)
            except asyncio.TimeoutError:
                pass
        return n

    reader = owner.share(limits=4)
    d0, d1 = (ledger_chargebacks.now() - timedelta(days=1)).date(), (ledger_chargebacks.now() + timedelta(days=1)).date()
    per_emp_url = f"/admin/stats/per-employee?from={d0}&to={d1}&by_account=true"
    rec_url = f"/admin/stats/sales-records?from={d0}&to={d1}"

    async def tick() -> None:
        for aid in creators:
            await owner.post(f"/admin/ingest/transactions/{aid}/run")

    async def read() -> None:
        await asyncio.gather(reader.get(per_emp_url), reader.get(rec_url + "&limit=50"), return_exceptions=True)

    esem = asyncio.Semaphore(ctx.users)

    async def episode(ep: dict) -> None:
        aid, fan = ep["aid"], ep["fan"]
        sale = {"aid": aid, "fan": fan["id"], "kind": ep["kind"], "cents": ep["cents"], "sender": None,
                "net": None, "special": None, "after": False, "ppv_id": None}
        paid = False
        async with esem:
            for st, think in zip(ep["steps"], ep["think"]):
                await asyncio.sleep(think)
                if st[0] == "pay":
                    if ep["kind"] == "ppv_ws" and sale["ppv_id"] is None:
                        sale["failed"] = "no PPV id"
                    else:
                        await pay(sale, fan)
                    paid = True
                    continue
                await send(st[1], aid, fan["id"], sale, ppv=st[0] == "ppv", paid=paid)
        if "at" in sale:
            sales.append(sale)

    t_load = time.time()
    bg = [asyncio.create_task(every(TICK_S, tick)), asyncio.create_task(every(READ_S, read))]
    await asyncio.gather(*(episode(ep) for ep in eps))
    stop.set()
    ticks, reads = await asyncio.gather(*bg)
    load_s = time.time() - t_load
    stats = await manager.quiesce(owner)
    await asyncio.sleep(1.0)
    await sse.stop()

    for aid, fan, cents, at, sale in twins:
        sale["net"] = ledger.add(aid, fan, cents, at, "Tip in chat from")
    settled = await settle_scans(owner, creators)

    async def records() -> list[dict]:
        out, before = [], None
        while True:
            r = await owner.get(rec_url + "&limit=500" + (f"&before_id={before}" if before else ""))
            r.raise_for_status()
            body = r.json()
            out += body["rows"]
            before = body.get("next_before_id")
            if not before:
                return out

    async def report() -> tuple[dict, str | None]:
        r = await owner.get(per_emp_url)
        r.raise_for_status()
        body = r.json()
        return ({e["employee_id"]: e["revenue_cents"] for e in body["employees"] if e["revenue_cents"]},
                body.get("attribution_fallback"))

    def by_fan(rows: list[dict]) -> dict[tuple, list[dict]]:
        out = defaultdict(list)
        for r in rows:
            out[(str(r["account_id"]), int(r["fan_id"]))].append(r)
        return out

    def amount(s: dict, fee: bool) -> int:
        return (s["net"] if s["net"] is not None else s["cents"] * 8 // 10) if fee else s["cents"]

    def want_of(phase: str):
        if phase in ("converters", "window330"):
            window = WINDOW_S if phase == "converters" else WINDOW_330_S
            return lambda s: expect(s, touches[(s["aid"], s["fan"])], window)

        def base(s):
            got = fan_rows.get((s["aid"], s["fan"]), [])
            return got[0]["employee_id"] if len(got) == 1 else "no single converters row"
        if phase == "sender":
            return lambda s: s["sender"] if s["kind"] in LINKED_KINDS else base(s)
        return base

    def compare(phase: str, rows: dict, subset: list[dict], fee: bool = False) -> dict:
        want_fn, bad = want_of(phase), []
        for s in subset:
            want = want_fn(s)
            got = rows.get((s["aid"], s["fan"]), [])
            ok = len(got) == 1 and got[0]["employee_id"] == want and got[0]["earnings_cents"] == amount(s, fee)
            if not ok:
                bad.append({"fan": s["fan"], "kind": s["kind"], "special": s["special"], "want": want,
                            "got": [(g["employee_id"], g["earnings_cents"], g["rule"]) for g in got],
                            "cents": amount(s, fee)})
        return {"n": len(subset), "mismatches": len(bad), "sample": bad[:6]}

    def totals(phase: str, fee: bool = False) -> dict:
        want_fn, out = want_of(phase), Counter()
        for s in sales:
            out[want_fn(s)] += amount(s, fee)
        return {k: v for k, v in out.items() if v}

    def diff(got: dict, want: dict) -> list:
        return [{"employee_id": k, "got": got.get(k, 0), "want": want.get(k, 0)}
                for k in sorted(set(got) | set(want), key=lambda x: (x is None, x or 0))
                if got.get(k, 0) != want.get(k, 0)]

    rows1 = await records()
    fan_rows = by_fan(rows1)
    rep1, fb1 = await report()
    ep_sales = [s for s in sales if s["special"] is None]
    kinds = Counter(s["kind"] for s in sales)
    ctx.metric("load", {"episodes": len(eps), "sales": len(sales), "by_kind": dict(kinds),
                        "replies": len(replies), "frames": len(frames), "ledger_rows": ledger.n,
                        "scan_posts": ticks, "report_reads": reads, "seconds": round(load_s, 1),
                        "window_s": WINDOW_S, "users": ctx.users})

    sub = {
        TIP_LEDGER: [s for s in ep_sales if s["kind"] == "ledger_tip"],
        TIP_WS: [s for s in sales if s["kind"] == "ws_tip" and s["special"] in (None, "ws_a_then_b")],
        PPV: [s for s in sales if s["kind"] in PPV_KINDS],
        WINDOW: [s for s in sales if s["special"] in WINDOW_SPECIALS],
        AUTO: [s for s in sales if s["special"] in AUTO_SPECIALS],
    }
    results = {}
    for name, subset in sub.items():
        res = results[name] = compare("converters", fan_rows, subset)
        if subset:
            ctx.check(name, res["mismatches"] == 0, **res)
        else:
            ctx.skip(name, "no sale of this kind in the run")
    after_bad, after_n = [], 0
    for s in sales:
        tt = touches[(s["aid"], s["fan"])]
        late = {t["emp"] for t in tt if t["at"] > s["at"]} - {t["emp"] for t in tt if t["at"] <= s["at"]}
        if not late:
            continue
        after_n += 1
        got = [r["employee_id"] for r in fan_rows.get((s["aid"], s["fan"]), [])]
        if set(got) & late:
            after_bad.append({"fan": s["fan"], "kind": s["kind"], "got": got, "after_only": sorted(late)})
    if after_n:
        ctx.check(TIP_AFTER, not after_bad, sales_with_a_new_chatter_after=after_n, wrong=len(after_bad),
                  sample=after_bad[:6])
    else:
        ctx.skip(TIP_AFTER, "no sale got a reply from a new chatter after the payment")
    want1 = totals("converters")
    ctx.check(TOTALS, not diff(rep1, want1), wrong=diff(rep1, want1)[:8], employees=len(want1),
              cents=sum(want1.values()))
    rec_sum = Counter()
    for r in rows1:
        rec_sum[r["employee_id"]] += r["earnings_cents"]
    ctx.check(AGREE, not diff(rep1, dict(rec_sum)), wrong=diff(rep1, dict(rec_sum))[:8])

    bad_sends = [r for r in replies if r["status"] >= 300 or r["id"] is None]
    bad_frames = [f for f in frames if f["status"] >= 300]
    want_keys = Counter((s["aid"], s["fan"]) for s in sales)
    extra = {k: len(v) for k, v in fan_rows.items() if len(v) != want_keys.get(k, 0)}
    unpaid = [s["fan"] for s in ep_sales if s.get("failed")]
    ctx.check(COUNT, not bad_sends and not bad_frames and not extra and not unpaid
              and len(rows1) == len(sales) and not stats.get("timed_out"),
              sales=len(sales), records=len(rows1), bad_sends=len(bad_sends), bad_frames=len(bad_frames),
              wrong_count_fans=list(extra.items())[:6], unpaid=unpaid[:6], persist_drops=stats.get("persist_drops"))
    ws_n = sum(1 for s in sales if s["kind"] == "ws_tip")
    ledger_only = sum(1 for s in sales if s["kind"] in ("ledger_tip", "ppv_ledger"))
    ws_promoted = sum(1 for s in sales if s["kind"] == "ws_tip" and len(fan_rows.get((s["aid"], s["fan"]), [])) == 1
                      and fan_rows[(s["aid"], s["fan"])][0]["net_cents"] is not None)
    ctx.check(SCANS, settled["ok"] and settled["inserted"] == ledger_only and ws_promoted == ws_n,
              inserted=settled["inserted"], ledger_only=ledger_only, ws_tips=ws_n, ws_promoted=ws_promoted,
              errors=settled["errors"], waited_s=settled["seconds"])
    await _ledger(ctx, w, creators)

    async def thread(key):
        async with sem:
            return key, await manager.thread_messages(owner, key[0], key[1], limit=200)

    keys = sorted({(r["aid"], r["fan"]) for r in replies if r["id"] is not None})
    threads = dict(await asyncio.gather(*(thread(k) for k in keys)))
    bad_stamp = []
    for r in replies:
        if r["id"] is None:
            continue
        rows_ = [m for m in threads.get((r["aid"], r["fan"]), []) if int(m["message_id"]) == int(r["id"])]
        want = emp[r["chatter"]]
        if len(rows_) != 1 or rows_[0].get("direction") != "out" or rows_[0].get("sent_by_employee_id") != want:
            bad_stamp.append({"id": r["id"], "rows": len(rows_), "want": want,
                              "got": [m.get("sent_by_employee_id") for m in rows_]})
    ctx.check(STAMP, not bad_stamp, replies=len(replies), wrong=len(bad_stamp), sample=bad_stamp[:5])

    await put("sales", sales_blob(window=WINDOW_330_S))
    saved = await saved_window()
    rows_w, (rep_w, _) = by_fan(await records()), await report()
    res = compare("window330", rows_w, sales)
    want_w = totals("window330")
    ctx.check(WINDOW330, saved == WINDOW_330_S and res["mismatches"] == 0 and not diff(rep_w, want_w),
              saved_window_s=saved, **res, wrong_totals=diff(rep_w, want_w)[:6])
    specials_330 = {s["special"]: [(r["employee_id"], r["rule"]) for r in rows_w.get((s["aid"], s["fan"]), [])]
                    for s in sales if s["special"]}

    await put("sales", sales_blob(fee=True))
    rows_fee, (rep_fee, _) = by_fan(await records()), await report()
    res = compare("fee", rows_fee, sales, fee=True)
    want_fee = totals("fee", fee=True)
    ctx.check(FEE, res["mismatches"] == 0 and not diff(rep_fee, want_fee), **res,
              wrong_totals=diff(rep_fee, want_fee)[:6])

    await put("sales", sales_blob(messages="sender"))
    rows_s, (rep_s, _) = by_fan(await records()), await report()
    res = compare("sender", rows_s, sales)
    want_s = totals("sender")
    ctx.check(SENDER, res["mismatches"] == 0 and not diff(rep_s, want_s), **res,
              wrong_totals=diff(rep_s, want_s)[:6])

    await put("sales", sales_blob(messages="shift", posts_tips="shift"))
    rows_sh, (rep_sh, fb_sh) = by_fan(await records()), await report()
    res = compare("shift_off", rows_sh, sales)
    want_sh = totals("shift_off")
    want_fb = FALLBACK_LINE
    ctx.check(SHIFT, res["mismatches"] == 0 and not diff(rep_sh, want_sh) and fb_sh == want_fb, **res,
              wrong_totals=diff(rep_sh, want_sh)[:6], fallback=fb_sh, want_fallback=want_fb)

    await put("sales", sales_blob())
    await put("sales", sales_blob(fee=True), effective_from=None)
    rep_v, _ = await report()
    ctx.check(VERSION, rep_v == rep1, wrong=diff(rep_v, rep1)[:6], fallback_before=fb1)

    sent_at = {f["message_id"]: f["t0"] for f in frames if f["kind"] == "ws_tip" and f["status"] < 300}
    e2e = [sse.received_at[m] - t0 for m, t0 in sent_at.items() if m in sse.received_at]
    ctx.metric("e2e_ms", {"n": len(e2e), "of": len(sent_at),
                          **({"p50": round(pct(e2e, .5), 1), "p95": round(pct(e2e, .95), 1)} if e2e else {})})
    name = f"e2e p95 (WS tip frame handed to relay -> on the owner's /events) < {E2E_P95_MS}ms"
    if e2e:
        ctx.check(name, pct(e2e, 0.95) < E2E_P95_MS and len(e2e) == len(sent_at), budget=True,
                  p95=round(pct(e2e, 0.95), 1), n=len(e2e), missing=len(sent_at) - len(e2e))
    else:
        ctx.check(name, False, budget=True, reason="no WS tip frame reached /events")
    routes = ctx.rec.summary()
    for route, budget in P95_MS.items():
        if route in routes:
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"],
                      **({"offered_sends_per_s": round(len(replies) / load_s, 1)} if "chats" in route else {}))
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")

    ctx.metric("credit", {k: {"n": v["n"], "mismatches": v["mismatches"]} for k, v in results.items()})
    ctx.metric("specials", {s["special"]: {
        "want_1h": expect(s, touches[(s["aid"], s["fan"])], WINDOW_S),
        "want_3h30m": expect(s, touches[(s["aid"], s["fan"])], WINDOW_330_S),
        "sender": s["sender"],
        "got_1h": [(r["employee_id"], r["rule"]) for r in fan_rows.get((s["aid"], s["fan"]), [])],
        "got_3h30m": specials_330.get(s["special"]),
        "got_sender": [(r["employee_id"], r["rule"]) for r in rows_s.get((s["aid"], s["fan"]), [])]}
        for s in sales if s["special"]})
    ctx.metric("employee_ids", {"A": A, "B": B, "Automation": emp["Automation"]})
    ctx.note("Product notes (not this flow's change): Shift schedule with Time tracking off falls back to "
             "Converters (the report's fallback line); under Message sender a ledger-only tip has no message, "
             "so it is Posts and tips and keeps the Converters credit.")

    used = {(ep["aid"], ep["fan"]["id"]) for ep in eps} | {(c0, f["id"]) for f in special_fans.values()}
    await run_chargebacks(ctx, w, creators, ledger, used)

    if ctx.app is None:
        ctx.skip(UI_SAVE, "--no-ui")
    else:
        await _ui_window(ctx, saved_window)
    for c in chatters:
        await c.close()
    await asyncio.gather(pump.aclose(), reader.aclose())


async def _ledger(ctx, w, creators: list[str]) -> None:
    try:
        text = await relay_telemetry.flushed_log(ctx)
    except TimeoutError as e:
        ctx.check(LEDGER, False, reason=str(e))
        return
    if text is None:
        ctx.skip(LEDGER, "write_telemetry off (CHATTERLY_WRITE_TELEMETRY_S=0)")
        return
    writers = relay_telemetry.writers(text)
    txns = writers.get("ledger", 0)
    pages = len(re.findall(r"ingest_tx_page_fetched account=\S+ page=\d+ count=[1-9]", text))
    written = text.count("ingest_tx_page_written account=")
    seeded = {(aid, int(f["id"])): f["spend_cents"] or 0 for aid in creators for f in w.data["fans"][aid]}
    marks = ",".join("?" * len(creators))
    con = w.sql()
    try:
        life = {(str(a), int(f)): v or 0 for a, f, v in con.execute(
            f"SELECT account_id, fan_id, lifetime_spend_cents FROM fans WHERE account_id IN ({marks})", creators)}
        revenue = {(str(a), int(f)): v or 0 for a, f, v in con.execute(
            f"SELECT account_id, fan_id, SUM(amount_cents) FROM transactions WHERE status NOT IN "
            f"({','.join('?' * len(_NON_REVENUE_STATUSES))}) AND fan_id IS NOT NULL AND account_id IN ({marks}) "
            "GROUP BY account_id, fan_id", (*_NON_REVENUE_STATUSES, *creators))}
    finally:
        con.close()
    off = [{"fan": k[1], "lifetime": life.get(k, 0), "seeded": seeded.get(k, 0), "revenue": revenue.get(k, 0)}
           for k in sorted(set(life) | set(revenue)) if life.get(k, 0) - seeded.get(k, 0) != revenue.get(k, 0)]
    folded = txns == 0 and writers.get("other", 0) > 0
    ctx.check(LEDGER, 0 < written < pages and txns == written and not off,
              **({"reason": "`ledger` label folded into `other` (write_telemetry _WRITERS_MAX)"} if folded else {}),
              ledger_txns=txns, pages_written=written, pages_fetched=pages, quiet_pages=pages - written,
              other_writers={k: v for k, v in writers.items() if "ledger" in k or k == "other"},
              fans=len(set(life) | set(revenue)), lifetime_off=len(off), sample=off[:6])


async def _ui_window(ctx, saved_window) -> None:
    async with ui.owner_browser(ctx) as page:
        await page.goto(f"{ctx.app}/settings/sales", wait_until="domcontentloaded")
        hours, minutes = page.get_by_label("Converters window hours"), page.get_by_label("Converters window minutes")
        await hours.wait_for(timeout=120_000)
        await page.wait_for_timeout(800)
        before = (await hours.input_value(), await minutes.input_value())
        await ui.shot(ctx, page, "trigger-sales-converters-window")
        await hours.fill("3")
        await minutes.fill("30")
        async with page.expect_response(lambda r: r.request.method == "PUT"
                                        and "/admin/settings/sales" in r.url) as put_:
            await page.get_by_role("button", name="Save", exact=True).last.click(timeout=5_000)
        resp = await put_.value
        shown = True
        try:
            await page.get_by_text("Saved ✓").first.wait_for(timeout=10_000)
        except Exception:
            shown = False
        await page.wait_for_timeout(300)
        after = (await hours.input_value(), await minutes.input_value())
        await ui.shot(ctx, page, "settled-sales-converters-window-saved")
    saved = await saved_window()
    ctx.check(UI_SAVE, before == ("1", "0") and resp.status == 200 and shown and saved == WINDOW_330_S
              and after == ("3", "30"), fields_before=before, fields_after=after, put_status=resp.status,
              saved_shown=shown, get_converters_window_seconds=saved)
