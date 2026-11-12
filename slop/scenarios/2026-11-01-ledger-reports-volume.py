"""Ledger reports at volume (W16): Fan reports (Top fans, Traffic), the Tips tab (tips list, top
tippers), the Message dashboard's paid broadcasts, Sales records and the Excel export, read by many
owners of two Agencies over a big ledger, every figure against an oracle the harness computes in SQL.

World: `multi_agency_big_models` (5 Agencies, 20 Creators, 3 big; Agency 0 = the UI's owner with the
3 big Creators, Agency 1 = the scope probe) + `seed/ledger_bulk.py` on all 20 Creators: `--set n=`
ledger rows (small 10k, medium 200k, huge 1M) over 60 days, kinds tip / tip_post / ppv_message /
ppv_post / subscription / rebill / custom, statuses cleared / pending and the reversals chargedback /
refunded / refund_pending / failed, 1 in 10 tips a WS-pump row with no net, 1 in 200 ledger rows with
net 0; paid mass broadcasts (`--set runs=`, `recipients=` per Creator) whose buyers' copies are marked
bought with their linked sale (some since refunded); 1 in 5 fans a free trial / promotion claimer
(`link_claimers`) + `seed/earnings.py` on Agencies 0 and 1's Creators (OF Statistics' days and the
ledger rows it caught, `history_days` 40, connected 5 days ago): its ledger rows are `transactions`
every check's oracle reads, so they are part of each figure checked.

Load (`ctx.rec.stage` "load", `--set load_s=`: small 20 s, medium 60 s): `--users` owners, half each
Agency, each its own pool on its Agency's session, a human think time (actors/reports THINK_S, 3-15 s)
between page loads, what to read picked from the seed: Fan reports (fan-report for one Creator or all,
a random sort), the Tips tab (tips-list for one Creator or all + top-tippers), the Message dashboard
(paid-messages), Sales records (sales-records), or an export (a CSV of fan-report / tips-list /
top-tippers, route label prefixed `export `, or POST /admin/stats/xlsx with rows from the seeded fans).
Every JSON list and CSV export a crowd read answers is scanned for another Agency's Creator. The
owner is this file's `_owner`, not an actors/ module: no actor reads these routes (actors/reports.py
reads the Dashboard and Creator reports), and the module stays here until a second flow needs it.

Checks (after the load, route labels prefixed `check `), all against the oracle: SQL over the run's
`transactions` / `messages` / `link_claimers`, written from the rules, never importing a product
function: spend counts cleared + pending only (attribution_backfill.TRACKED_STATUSES), net = net_cents
(0 included) else 80% of gross rounded down (floor), tips = tip / tip_post / tip_stream, PPV = the ppv
family, subs = subscription + rebill; ranking by the sort key desc, then total desc, then fan id;
Sales records list each tracked sale of a credited kind once, without subscription / rebill / referral
(default Sales Settings leave Subscriptions unattributed); a paid broadcast's buyers are its bought
copies whose linked sale is not a reversal. Each correctness check also needs its oracle set non-empty
(no vacuous pass). Names: lib/ledger_reports_faults.py (rank and CSV checks one per route). Budgets
(budget=True, stage "load"): p95 fan-report <= 1500 ms, tips-list / top-tippers <= 800 ms; p95 vs the
last green run (P95_VS_LAST) over those and the other report routes. UI (small, UI on): Fan reports'
Top fans cells == the fan-report rows the page read == oracle, and its Download report file == oracle
(the side effect); the Message dashboard's Tips tab list with its next pages answering 500 at the browser
wire (page.route) and its foot in view PAGE_ERR_WAIT_S: <= 2 next-page requests (retry: 1) and Load more
offered, then the route lifted, Load more renders that page's rows (the side effect); screenshots
fan-reports-settled, fan-reports-download-trigger, message-dashboard, sales-records, page-error-trigger,
page-error-settled.

Acceptance: all three crowd p95 budgets and all three isolated probe budgets are mandatory,
independent checks at every scale. Missing samples, missing probes, non-200 probe responses, and
latencies over budget FAIL. Probe selection never depends on historical waiver metadata. With the
crowd stopped, tips-list reads Agency 0's 45-day first page and fan-report reads one big Creator's
45-day report. Top-tippers runs alone for PROBE_ALONE_S with the same owners, Agency split, think
time, windows and Tips-tab share. Big Creators remain eligible for crowd fan-report reads and exports.
Historical known-red reasons and narrowed-run results are retained in
slop/evidence/fd3-integration/ledger-contract/historical-contract.txt and ledger-volume-attribution.md;
they neither waive a current failure nor turn a within-budget measurement into a stale-marker failure.

Break-it-once (targets in lib/ledger_reports_faults.py): fan-report-counts-refunds (FAULT; reversals
counted as spend: fan totals, fan-report rank, fan-report CSV, traffic), --fault=top-tippers-crosses-agency
(top-tippers loses its Agency clamp: scope, top-tippers totals, rank and CSV),
--fault=fan-report-csv-truncates (the fan-report CSV stops at 100 rows: fan-report CSV),
--fault=fan-report-latest-claim (traffic credits each spender's newest claim: traffic),
--fault=loadmore-refires-on-error (client: the load-more sentinel loses its error gate: the page-error check).
With the UI on,
the UI checks of Fan reports go red too under the fan-report faults (noise, not targets: they skip
under --no-ui, where a target would be INCONCLUSIVE).

Bypasses (declared): every ledger, message, mass run and claimer row is SQL-seeded (the payouts
ingest, the WS pump, the mass send and OF's claimer walk are not run), in the shapes those writers
leave; the tx_rollup triggers fire on the inserts as on any write. The oracle reads the same DB rows
the product reads (it checks the reads, not the writers). OnlyFans is never reached; in the browser
`/api/of/*` stays held; the Tips tab's next-page 500s are answered at the browser's wire. The Message dashboard and Sales records screens are screenshot only; their
figures are checked through the API.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import random
import re
import time as clock
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import NamedTuple
from urllib.parse import parse_qs, urlencode, urlsplit

from slop.actors import ui
from slop.actors.reports import THINK_S
from slop.lib.ledger_reports_faults import (FAN_CSV, FAN_RANK, FAN_TOTALS, PAGE_ERR_BOUNDED, PAID, SALES, SCOPE,
                                            TIPS, TIPS_CSV, TOP_CSV, TOP_RANK, TOP_TOTALS, TRAFFIC, UI_SIDE, UI_TOTALS,
                                            XLSX)
from slop.seed import earnings, ledger_bulk, ts

PROFILE = "multi_agency_big_models"
UI = True
FAULT = "fan-report-counts-refunds"
FAN_ROUTE, TIPS_ROUTE, TOP_ROUTE = "GET /admin/stats/fan-report", "GET /admin/tips-list", "GET /admin/top-tippers"
P95_MS = {FAN_ROUTE: 1500, TIPS_ROUTE: 800, TOP_ROUTE: 800}
P95_ALSO = ("GET /admin/paid-messages", "GET /admin/stats/sales-records", "export GET /admin/stats/fan-report",
            "export GET /admin/tips-list", "export GET /admin/top-tippers", "export POST /admin/stats/xlsx")
P95_VS_LAST = (1.5, 150)
P95_VS_LAST_MIN_N = 20


def _budget_name(route: str) -> str:
    return f"ledger reports: p95 {route} <= {P95_MS[route]} ms under the crowd (stage load)"


# Isolated checks use the same unchanged thresholds, separately from crowd verdicts.
PROBE_P95_MS = {FAN_ROUTE: 1500, TIPS_ROUTE: 800, TOP_ROUTE: 800}
TIPS_TAB = (0.35, 0.6)  # the share of an owner's page loads that open the Tips tab (tips-list + top-tippers)
PROBE_ALONE_S = 30  # top-tippers alone: how long (~170 calls at 200 owners)

TRACKED = ("cleared", "pending")
TIP_KINDS = ("tip", "tip_post", "tip_stream")
PPV_KINDS = ("ppv", "ppv_message", "ppv_post", "ppv_stream")
SUB_KINDS = ("subscription", "rebill")
CREDITED = ("ppv", "ppv_message", "ppv_post", "ppv_stream", "tip", "tip_post", "tip_stream", "custom")
SORTS = ("total", "tips", "ppv", "subs")
SORT_COL = {"total": 0, "tips": 2, "ppv": 3, "subs": 4}  # into the oracle's (total, net, tips, ppv, subs)
CSV_CAP = 50_000  # csv_export.CSV_MAX_ROWS: past it the file ends in a TRUNCATED line
WINDOW_DAYS = 45
TIP_PAGES = 3
PAGE_ERR_WAIT_S = 5  # the foot in view after its next page failed (unfixed: 13 requests in 5 s, finding 133.1)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Window(NamedTuple):
    """The reports' window: [lo, hi] (WINDOW_DAYS days), its last 7 days starting at `week`."""
    lo: datetime
    hi: datetime
    week: datetime

    def q(self, week: bool = False) -> dict[str, str]:
        """The window as a route's from / to params."""
        return {"from": _iso(self.week if week else self.lo), "to": _iso(self.hi)}


class Menu(NamedTuple):
    """What one Agency's owners may read: its Creators (tips-list, top-tippers and their exports), the
    including big Creators for fan-report and its export, and the rows an XLSX export posts."""
    creators: list[str]
    fan_rows: list


def _instant(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)


def _marks(vals) -> str:
    return "(" + ",".join("?" * len(vals)) + ")"


def _fmt_cents(c: int) -> str:
    """app/lib/format.ts fmtCentsBlankZero: whole dollars (JS Math.round), commas, '—' for 0."""
    if not c:
        return "—"
    d = math.floor(abs(c) / 100 + 0.5)
    return f"{'-' if c < 0 and d > 0 else ''}${d:,}"


def _parse_csv(text: str) -> tuple[list[dict], bool]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], False
    header, body = rows[0], rows[1:]
    truncated = bool(body) and body[-1][0].startswith("# TRUNCATED")
    return [dict(zip(header, r)) for r in (body[:-1] if truncated else body)], truncated


# ── The oracle: the harness's own reading of the run's DB. ───────────────────

def _rows(w, sql: str, params: list) -> list[tuple]:
    con = w.sql()
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def oracle_fans(w, accounts, lo: datetime, hi: datetime) -> dict[tuple[str, int], tuple[int, ...]]:
    """(account, fan) -> (total, net_or_80, tips, ppv, subs) over tracked sales in [lo, hi]."""
    rows = _rows(
        w, "SELECT account_id, fan_id, SUM(amount_cents), SUM(COALESCE(net_cents, CASE WHEN amount_cents >= 0 "
        "THEN amount_cents * 8 / 10 ELSE -((-amount_cents * 8 + 9) / 10) END)), "
        f"SUM(CASE WHEN kind IN {_marks(TIP_KINDS)} THEN amount_cents ELSE 0 END), "
        f"SUM(CASE WHEN kind IN {_marks(PPV_KINDS)} THEN amount_cents ELSE 0 END), "
        f"SUM(CASE WHEN kind IN {_marks(SUB_KINDS)} THEN amount_cents ELSE 0 END) "
        f"FROM transactions WHERE status IN {_marks(TRACKED)} AND fan_id IS NOT NULL AND occurred_at >= ? "
        f"AND occurred_at <= ? AND account_id IN {_marks(accounts)} GROUP BY account_id, fan_id",
        [*TIP_KINDS, *PPV_KINDS, *SUB_KINDS, *TRACKED, ts(lo), ts(hi), *accounts])
    return {(a, int(f)): tuple(int(x) for x in v) for a, f, *v in rows}


def ranked(fans: dict, sort: str) -> list[tuple[str, int]]:
    col = SORT_COL[sort]
    return [k for k, _ in sorted(fans.items(), key=lambda kv: (-kv[1][col], -kv[1][0], kv[0][1]))]


def oracle_tips(w, accounts, lo, hi) -> list[tuple[int, str, int | None, int]]:
    """Every tracked tip, newest id first: (id, account, fan, amount)."""
    return _rows(
        w, f"SELECT id, account_id, fan_id, amount_cents FROM transactions WHERE kind IN {_marks(TIP_KINDS)} "
        f"AND status IN {_marks(TRACKED)} AND occurred_at >= ? AND occurred_at <= ? AND account_id IN "
        f"{_marks(accounts)} ORDER BY id DESC", [*TIP_KINDS, *TRACKED, ts(lo), ts(hi), *accounts])


def tippers_of(tips) -> dict[tuple[str, int], tuple[int, int]]:
    out: dict = defaultdict(lambda: [0, 0])
    for _id, a, f, amt in tips:
        if f is not None:
            out[(a, int(f))][0] += amt
            out[(a, int(f))][1] += 1
    return {k: tuple(v) for k, v in out.items()}


def oracle_sales(w, accounts, lo, hi) -> list[tuple[int, int]]:
    """Sales records' sales, newest first: (id, gross)."""
    return _rows(
        w, f"SELECT id, amount_cents FROM transactions WHERE account_id IN {_marks(accounts)} AND status IN "
        f"{_marks(TRACKED)} AND kind IN {_marks(CREDITED)} AND occurred_at >= ? AND occurred_at <= ? "
        "ORDER BY occurred_at DESC, id DESC", [*accounts, *TRACKED, *CREDITED, ts(lo), ts(hi)])


def oracle_traffic(w, accounts, fans: dict) -> dict[tuple, tuple[int, int]]:
    """(account, kind, of_id) -> (fans, total): each spender under his earliest claim
    (OF's subscribe_at, else first seen; then the claim's id), the rest (account, None, None)."""
    first: dict[tuple[str, int], tuple] = {}
    for cid, a, f, kind, of_id, sub, seen in _rows(
            w, "SELECT id, account_id, fan_id, kind, of_id, subscribe_at, first_seen_at FROM link_claimers "
            f"WHERE account_id IN {_marks(accounts)}", list(accounts)):
        key, rank = (a, int(f)), (sub or seen, cid)
        if key not in first or rank < first[key][0]:
            first[key] = (rank, kind, int(of_id))
    out: dict = defaultdict(lambda: [0, 0])
    for (a, f), v in fans.items():
        c = first.get((a, f))
        k = (a, c[1], c[2]) if c else (a, None, None)
        out[k][0] += 1
        out[k][1] += v[0]
    return {k: tuple(v) for k, v in out.items()}


def oracle_paid(w, accounts, lo, hi) -> dict[int, dict]:
    """Paid broadcasts with a copy in [lo, hi]: run -> account, recipients, buyers, earnings."""
    runs = {int(r): {"account_id": a, "recipients": int(n), "buyers": 0, "earnings": 0} for r, a, n in _rows(
        w, f"SELECT r.id, r.account_id, r.recipient_count FROM mass_runs r WHERE r.account_id IN {_marks(accounts)} "
        "AND EXISTS (SELECT 1 FROM messages m WHERE m.mass_run_id = r.id AND m.direction = 'out' AND "
        "m.price_cents > 0 AND m.created_at >= ? AND m.created_at <= ?)", [*accounts, ts(lo), ts(hi)])}
    for r, n, cents in _rows(
            w, "SELECT m.mass_run_id, COUNT(DISTINCT m.fan_id), SUM(m.price_cents) FROM messages m "
            f"WHERE m.account_id IN {_marks(accounts)} AND m.mass_run_id IS NOT NULL AND m.direction = 'out' "
            "AND m.funnel_step IS NULL AND (m.is_paid = 1 OR m.purchased_at IS NOT NULL) AND NOT EXISTS ("
            "SELECT 1 FROM transactions t WHERE t.account_id = m.account_id AND t.fan_id = m.fan_id "
            f"AND t.message_id = m.message_id AND t.status NOT IN {_marks(TRACKED)}) GROUP BY m.mass_run_id",
            [*accounts, *TRACKED]):
        if int(r) in runs:
            runs[int(r)].update(buyers=int(n), earnings=int(cents))
    return runs


# ── Scope and the check phase's reads. ───────────────────────────────────────

class Scope:
    """Every account id a list answered, per Agency, against that Agency's Creators."""

    def __init__(self, accounts: dict[int, set[str]]):
        self.accounts, self.foreign, self.lists = accounts, defaultdict(set), 0

    def scan_rows(self, ag: int, rows) -> None:
        self.lists += 1
        for r in rows:
            a = r.get("account_id") if isinstance(r, dict) else None
            if a not in (None, "") and a not in self.accounts[ag]:
                self.foreign[ag].add(a)

    def scan_body(self, ag: int, body) -> None:
        if isinstance(body, dict):
            self.scan_rows(ag, [r for key in ("top_fans", "traffic", "rows") for r in body.get(key) or []])


def _next_id(body: dict) -> dict:
    return {"before_id": body["next_before_id"]} if body.get("next_before_id") else {}


def _next_sent(body: dict) -> dict:
    return {"before_id": body["next_before_id"], "before_sent_at": body["next_before_sent_at"]} \
        if body.get("next_before_id") else {}


class Checks:
    """The check phase's reads (route labels `check `, scanned for scope) and failures per check name."""

    def __init__(self, http: dict, scope: Scope):
        self.h = {i: h.share(limits=4) for i, h in http.items()}
        for h in self.h.values():
            h.prefix = "check "
        self.scope = scope
        self.bad: dict[str, list] = defaultdict(list)

    def fail(self, name: str, **detail) -> None:
        self.bad[name].append(detail)

    async def json(self, i: int, path: str, **q) -> tuple[int, dict | None]:
        r = await self.h[i].get(f"{path}?{urlencode(q, doseq=True)}", timeout=180)
        body = r.json() if r.status_code == 200 else None
        self.scope.scan_body(i, body)
        return r.status_code, body

    async def csv(self, i: int, path: str, **q) -> tuple[int, list[dict], bool]:
        r = await self.h[i].get(f"{path}?{urlencode({**q, 'format': 'csv'}, doseq=True)}", timeout=300)
        rows, trunc = _parse_csv(r.text) if r.status_code == 200 else ([], False)
        self.scope.scan_rows(i, rows)
        return r.status_code, rows, trunc

    async def pages(self, i: int, path: str, cursor, max_pages: int, **q) -> tuple[int, list[dict]]:
        """Every row of up to `max_pages` keyset pages; `cursor(body)` is the next page's params ({} = last)."""
        rows: list[dict] = []
        cur: dict = {}
        for _ in range(max_pages):
            st, body = await self.json(i, path, **q, **cur)
            if st != 200:
                return st, rows
            rows += body["rows"]
            cur = cursor(body)
            if not cur:
                break
        return 200, rows

    async def aclose(self) -> None:
        for h in self.h.values():
            await h.aclose()


# ── The crowd. ───────────────────────────────────────────────────────────────

async def _owner(*, pool, export, ag: int, menu: Menu, windows: list[dict], stop, rng, scope: Scope) -> int:
    """One owner: page loads until `stop`, a human think time between; what to read from `rng` and `menu` only."""
    done = 0
    await asyncio.sleep(rng.uniform(0, THINK_S[1]))
    while not stop.is_set():
        win = rng.choice(windows)
        x = rng.random()
        reads: list[tuple] = []  # (pool, method, path, json body or None)
        if x < TIPS_TAB[0]:
            q = {**win, "sort": rng.choice(SORTS)}
            if rng.random() < 0.75:
                q["account_id"] = rng.choice(menu.creators)
            reads.append((pool, "GET", f"/admin/stats/fan-report?{urlencode(q)}", None))
        elif x < TIPS_TAB[1]:
            q = {**win, "limit": 50}
            if rng.random() < 0.75:
                q["account_id"] = rng.choice(menu.creators)
            reads.append((pool, "GET", f"/admin/tips-list?{urlencode(q)}", None))
            reads.append((pool, "GET", f"/admin/top-tippers?{urlencode({**win, 'limit': 20})}", None))
        elif x < 0.75:
            reads.append((pool, "GET", f"/admin/paid-messages?{urlencode({**win, 'limit': 50})}", None))
        elif x < 0.9:
            reads.append((pool, "GET", f"/admin/stats/sales-records?{urlencode({**win, 'limit': 50})}", None))
        else:
            kind = rng.choice(("fan", "tips", "top", "xlsx"))
            if kind == "xlsx":
                k = rng.randint(50, 1000)
                rows = [["Fan", "Total spend"]] + [[r[0], r[1]] for r in menu.fan_rows[:k]]
                reads.append((export, "POST", "/admin/stats/xlsx", {"sheet": "Top fans", "rows": rows}))
            else:
                path, pick = {"fan": ("/admin/stats/fan-report", menu.creators),
                              "tips": ("/admin/tips-list", menu.creators),
                              "top": ("/admin/top-tippers", menu.creators)}[kind]
                q = {**win, "account_id": rng.choice(pick), "format": "csv"}
                reads.append((export, "GET", f"{path}?{urlencode(q)}", None))
        for h, method, path, body in reads:
            try:
                r = await h.request(method, path, timeout=120, **({"json": body} if body is not None else {}))
            except Exception:  # noqa: BLE001 — recorded as a transport error by lib/client
                continue
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ctype.startswith("application/json"):
                scope.scan_body(ag, r.json())
            elif r.status_code == 200 and ctype.startswith("text/csv"):
                scope.scan_rows(ag, _parse_csv(r.text)[0])
        done += 1
        await asyncio.sleep(rng.uniform(*THINK_S))
    return done


def _owners(users: int) -> dict[int, int]:
    """Owners per Agency: half each, the odd one to Agency 0."""
    return {i: max(1, users // 2 + (users % 2 if i == 0 else 0)) for i in (0, 1)}


async def _load(ctx, *, http: dict, menus: dict[int, Menu], windows: list[dict], load_s: float, scope: Scope) -> int:
    per = _owners(ctx.users)
    pools = {i: http[i].share(limits=max(10, per[i])) for i in (0, 1)}
    exports = {i: http[i].share(limits=max(10, per[i])) for i in (0, 1)}
    for h in exports.values():
        h.prefix = "export "
    stop = asyncio.Event()
    ctx.rec.stage = "load"
    tasks = [asyncio.create_task(_owner(
        pool=pools[i], export=exports[i], ag=i, menu=menus[i], windows=windows, stop=stop,
        rng=random.Random(f"{ctx.seed}:ledger-reports:{i}:{k}"), scope=scope))
        for i in (0, 1) for k in range(per[i])]
    await asyncio.sleep(load_s)
    stop.set()
    loads = sum(await asyncio.gather(*tasks))
    ctx.rec.stage = None
    for p in (*pools.values(), *exports.values()):
        await p.aclose()
    return loads


def _probe_stats(calls: list[tuple[int, float]], **detail) -> dict:
    """A probe's calls (status, ms) -> n, status counts, p95; `ok` only if every call answered 200."""
    lat = sorted(ms for _, ms in calls)
    status: dict[int, int] = defaultdict(int)
    for st, _ in calls:
        status[st] += 1
    return {**detail, "n": len(calls), "status": dict(status), "ok": bool(calls) and set(status) == {200},
            "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1) if lat else None}


async def _timed(h, path: str, timeout: float) -> tuple[int, float]:
    t1 = clock.perf_counter()
    try:
        st = (await h.get(path, timeout=timeout)).status_code
    except Exception:  # noqa: BLE001 — recorded as a transport error by lib/client
        st = 599
    return st, round((clock.perf_counter() - t1) * 1000, 1)


async def _alone(ctx, *, http: dict, windows: list[dict]) -> dict:
    """top-tippers alone, the rest of the crowd stopped: every owner of both Agencies (the crowd's split,
    think time and windows) reads it Agency-wide on the page loads that open the Tips tab, for
    PROBE_ALONE_S; the other page loads read nothing."""
    per = _owners(ctx.users)
    pools = {i: http[i].share(limits=max(10, per[i])) for i in (0, 1)}
    for h in pools.values():
        h.prefix = "probe "
    calls: list[tuple[int, float]] = []
    stop = asyncio.Event()

    async def owner(h, rng) -> None:
        await asyncio.sleep(rng.uniform(0, THINK_S[1]))
        while not stop.is_set():
            win = rng.choice(windows)
            if TIPS_TAB[0] <= rng.random() < TIPS_TAB[1]:
                calls.append(await _timed(h, f"/admin/top-tippers?{urlencode({**win, 'limit': 20})}", 120))
            await asyncio.sleep(rng.uniform(*THINK_S))

    tasks = [asyncio.create_task(owner(pools[i], random.Random(f"{ctx.seed}:ledger-reports:alone:{i}:{k}")))
             for i in (0, 1) for k in range(per[i])]
    await asyncio.sleep(PROBE_ALONE_S)
    stop.set()
    await asyncio.gather(*tasks)
    for h in pools.values():
        await h.aclose()
    return _probe_stats(calls, alone_s=PROBE_ALONE_S, owners=sum(per.values()))


async def _probes(ctx, *, w, http: dict, big: set, win: Window, o_fans0: dict,
                  o_tips0: list) -> dict:
    """All three required isolated probes, independent of historical findings."""
    out = {TOP_ROUTE: await _alone(ctx, http=http, windows=[win.q(), win.q(week=True)])}
    if big:
        probe = ctx.owner.share(limits=1)
        probe.prefix = "probe "
        aid = sorted(big)[0]
        for route, path, q in (
                (TIPS_ROUTE, "/admin/tips-list", {**win.q(), "limit": 50}),
                (FAN_ROUTE, "/admin/stats/fan-report", {**win.q(), "sort": "total", "account_id": aid})):
            out[route] = _probe_stats([await _timed(probe, f"{path}?{urlencode(q)}", 900)],
                                          account_id=q.get("account_id", "all of Agency 0"), **{"from": q["from"]})
        await probe.aclose()
        msgs = _rows(w, "SELECT COUNT(*) FROM messages WHERE account_id = ?", [aid])[0][0]
        out["creator"] = {"id": aid, "tips_45d": sum(1 for t in o_tips0 if t[1] == aid),
                          "spenders_45d": sum(1 for k in o_fans0 if k[0] == aid), "messages": msgs}
    if out:
        ctx.metric("ledger_probes", out)
    return out


def _budgets(ctx, probes: dict) -> None:
    """Crowd and isolated budgets stand independently; absent evidence fails closed."""
    routes = ctx.rec.summary("load")
    for route, budget in P95_MS.items():
        sample = routes.get(route) or {}
        crowd = sample.get("p95_ms")
        ctx.check(_budget_name(route), bool(sample.get("n")) and crowd is not None and crowd <= budget,
                  budget=True, p95=crowd, n=sample.get("n", 0), users=ctx.users)
    for route, budget in PROBE_P95_MS.items():
        probe = probes.get(route) or {}
        latency = probe.get("p95_ms")
        status = probe.get("status", {})
        valid = (probe.get("n", 0) > 0 and probe.get("ok") is True
                 and status == {200: probe["n"]} and latency is not None)
        ctx.check(f"ledger reports: p95 {route} <= {budget} ms isolated probe",
                  valid and latency <= budget, budget=True, probe=probe, users=ctx.users)
    # Every route with samples, so the stock check lists the thin ones as skipped; none when no route
    # reaches P95_VS_LAST_MIN_N (a short small run): the stock check fails a comparison of 0 routes.
    seen = [r for r in (*P95_MS, *P95_ALSO)
            if routes.get(r, {}).get("n", 0) > 0 and routes[r].get("p95_ms") is not None]
    if any(routes[r]["n"] >= P95_VS_LAST_MIN_N for r in seen):
        ctx.metric("p95_vs_last_green", {r: routes[r]["p95_ms"] for r in seen})
        ctx.metric("p95_vs_last_green_n", {r: routes[r]["n"] for r in seen})


# ── The check sections. ──────────────────────────────────────────────────────

def _fan_vals(r) -> tuple[int, ...]:
    return tuple(int(r[k]) for k in ("total_cents", "net_or_80_cents", "tips_cents", "ppv_cents", "subs_cents"))


def _cmp_fans(ck: Checks, where: str, rows: list, want: dict, order: list, limit: int) -> None:
    keys = [(r["account_id"], int(r["fan_id"])) for r in rows]
    wrong = [(k, _fan_vals(r), want.get(k)) for k, r in zip(keys, rows) if _fan_vals(r) != want.get(k)]
    if wrong:
        ck.fail(FAN_TOTALS, where=where, wrong=len(wrong), first=[str(x) for x in wrong[:3]])
    if keys != order[:limit]:
        first = next((j for j, (a, b) in enumerate(zip(keys, order)) if a != b), min(len(keys), len(order)))
        ck.fail(FAN_RANK, where=where, got_n=len(keys), want_n=len(order[:limit]), first_diff_at=first)


def _cmp_tips(ck: Checks, where: str, st: int, rows: list, want: list, n: int) -> list[tuple[int, int]]:
    """tips-list JSON rows vs the oracle's newest `n` tips; returns the rows' (id, amount)."""
    got = [(r["transaction_id"], r["amount_cents"]) for r in rows]
    exp = [(t[0], t[3]) for t in want[:n]]
    if st != 200 or got != exp:
        ck.fail(TIPS, where=where, status=st, got=len(got), want=len(exp),
                first=str(next(((a, b) for a, b in zip(got, exp) if a != b), None)))
    return got


def _cmp_tippers(ck: Checks, where: str, st: int, body: dict | None, tippers: dict, limit: int) -> list[dict]:
    """top-tippers JSON vs the oracle's tippers: totals / counts (TOP_TOTALS), rank (TOP_RANK); returns its rows."""
    rows = (body or {}).get("rows", [])
    wrong = [r for r in rows if tippers.get((r["account_id"], r["fan_id"])) != (r["total_cents"], r["tip_count"])]
    if st != 200 or wrong:
        ck.fail(TOP_TOTALS, where=where, status=st, wrong=len(wrong), first=str(wrong[:2]))
    totals = sorted((v[0] for v in tippers.values()), reverse=True)
    if [r["total_cents"] for r in rows] != totals[:limit] or [r["rank"] for r in rows] != list(range(1, len(rows) + 1)):
        ck.fail(TOP_RANK, where=where, got_n=len(rows), want_n=min(limit, len(totals)))
    return rows


async def _fan_report(ck: Checks, w, mine, o_fans, win: Window) -> dict:
    """Agency-wide fan-report per sort key and limit; its total / 100 read's traffic, and that read's
    Top fans through the XLSX export (Agency 0). Returns the XLSX check's detail."""
    xlsx: dict = {"ok": False, "error": "never read"}
    for i in (0, 1):
        first: tuple = (None, None)  # the total / 100 read
        for sort in SORTS:
            order = ranked(o_fans[i], sort)
            for limit in (100, 5000):
                st, body = await ck.json(i, "/admin/stats/fan-report", **win.q(), sort=sort, limit=limit)
                if (sort, limit) == ("total", 100):
                    first = (st, body)
                if st != 200:
                    ck.fail(FAN_TOTALS, where=f"ag{i} {sort} {limit}", status=st)
                    continue
                _cmp_fans(ck, f"ag{i} sort={sort} limit={limit}", body["top_fans"], o_fans[i], order, limit)
        st, body = first
        want = oracle_traffic(w, mine[i], o_fans[i])
        got = {(r["account_id"], r["kind"], r["of_id"]): (r["fans"], r["total_cents"]) for r in (body or {}).get(
            "traffic", [])}
        if st != 200 or got != want:
            diff = {str(k): {"got": got.get(k), "want": want.get(k)} for k in set(got) | set(want)
                    if got.get(k) != want.get(k)}
            ck.fail(TRAFFIC, ag=i, status=st, wrong=len(diff), first=dict(list(diff.items())[:4]))
        if i == 0:
            rows = [["Fan", "Total spend", "Tips", "PPV"]] + [
                [r["fan_name"], r["total_cents"], r["tips_cents"], r["ppv_cents"]] for r in (body or {}).get(
                    "top_fans", [])]
            rx = await ck.h[0].post("/admin/stats/xlsx", json={"sheet": "Top fans", "rows": rows}, timeout=60)
            xlsx = {"ok": 200 <= rx.status_code < 300 and rx.content[:4] == b"PK\x03\x04",
                       "http_status": rx.status_code, "magic": rx.content[:4].hex(), "bytes": len(rx.content),
                       "content_type": rx.headers.get("content-type")}
    return xlsx


async def _per_creator_fans(ck: Checks, mine, o_fans, win: Window) -> None:
    """Per Creator: fan-report JSON (limit 5000) and its CSV, one sort key each."""
    for i in (0, 1):
        for ci, aid in enumerate(mine[i]):
            sort = SORTS[ci % len(SORTS)]
            want = {k: v for k, v in o_fans[i].items() if k[0] == aid}
            order = ranked(want, sort)
            q = {**win.q(), "account_id": aid}
            st, body = await ck.json(i, "/admin/stats/fan-report", **q, sort=sort, limit=5000)
            json_keys = [(r["account_id"], int(r["fan_id"])) for r in (body or {}).get("top_fans", [])]
            if st == 200:
                _cmp_fans(ck, f"{aid} sort={sort} limit=5000", body["top_fans"], want, order, 5000)
            else:
                ck.fail(FAN_TOTALS, where=aid, status=st)
            st, rows, trunc = await ck.csv(i, "/admin/stats/fan-report", **q, sort=sort)
            keys = [(r["account_id"], int(r["fan_id"])) for r in rows]
            vals_bad = sum(1 for k, r in zip(keys, rows) if _fan_vals(r) != want.get(k))
            if not (st == 200 and trunc == (len(want) > CSV_CAP) and keys == order[:CSV_CAP] and not vals_bad
                    and keys[:len(json_keys)] == json_keys):
                ck.fail(FAN_CSV, where=aid, status=st, rows=len(rows), want=len(want), truncated=trunc,
                        vals_bad=vals_bad, json_prefix_ok=keys[:len(json_keys)] == json_keys)


async def _tips(ck: Checks, mine, o_tips, win: Window) -> None:
    """Per Creator: tips-list pages + CSV, top-tippers JSON + CSV (the window); then each Agency's own
    Tips tab reads (tips-list first page, top-tippers)."""
    for i in (0, 1):
        for aid in mine[i]:
            tips = [t for t in o_tips[i] if t[1] == aid]
            q = {**win.q(), "account_id": aid}
            st, rows = await ck.pages(i, "/admin/tips-list", _next_id, TIP_PAGES, **q, limit=100)
            got = _cmp_tips(ck, f"tips-list {aid} from {q['from']}", st, rows, tips, 100 * TIP_PAGES)
            st, crows, trunc = await ck.csv(i, "/admin/tips-list", **q)
            ids = [(int(r["transaction_id"]), int(r["amount_cents"])) for r in crows]
            want = [(t[0], t[3]) for t in tips]
            if not (st == 200 and ids == want[:CSV_CAP] and trunc == (len(want) > CSV_CAP)
                    and ids[:len(got)] == got):
                ck.fail(TIPS_CSV, where=aid, status=st, rows=len(ids), want=len(want), truncated=trunc,
                        sum=sum(a for _, a in ids), want_sum=sum(a for _, a in want))

            tippers = tippers_of(tips)
            st, body = await ck.json(i, "/admin/top-tippers", **q, limit=100)
            jrows = _cmp_tippers(ck, f"top-tippers {aid}", st, body, tippers, 100)
            st, crows, trunc = await ck.csv(i, "/admin/top-tippers", **q)
            cvals = {(r["account_id"], int(r["fan_id"])): (int(r["total_cents"]), int(r["tip_count"])) for r in crows}
            ctot = [int(r["total_cents"]) for r in crows]
            if not (st == 200 and len(crows) == min(len(tippers), CSV_CAP) and cvals == tippers
                    and ctot == sorted(ctot, reverse=True)
                    and all(cvals.get((r["account_id"], r["fan_id"]), (None,))[0] == r["total_cents"] for r in jrows)):
                ck.fail(TOP_CSV, where=aid, status=st, rows=len(crows), want=len(tippers), sum=sum(ctot),
                        want_sum=sum(v[0] for v in tippers.values()))

        st, body = await ck.json(i, "/admin/tips-list", **win.q(), limit=100)
        _cmp_tips(ck, f"tips-list ag{i} from {win.q()['from']}", st, (body or {}).get("rows", []), o_tips[i], 100)
        st, body = await ck.json(i, "/admin/top-tippers", **win.q(), limit=100)
        _cmp_tippers(ck, f"top-tippers ag{i}", st, body, tippers_of(o_tips[i]), 100)


async def _paid(ck: Checks, o_paid, win: Window) -> None:
    """Paid broadcasts (Message dashboard, mass tab): every run once, with its figures."""
    for i in (0, 1):
        want = o_paid[i]
        st, rows = await ck.pages(i, "/admin/paid-messages", _next_sent, 50, **win.q(), kind="mass", type="paid",
                                  limit=100)
        got = {r.get("mass_run_id"): {"account_id": r["account_id"], "recipients": r.get("recipient_count"),
                                      "buyers": r.get("purchased_count"), "earnings": r.get("earnings_cents")}
               for r in rows}
        dup = len(rows) - len(got)
        if st != 200 or not want or got != want or dup:
            diff = {k: {"got": got.get(k), "want": want.get(k)} for k in set(got) | set(want) if got.get(k) != want.get(k)}
            ck.fail(PAID, ag=i, status=st, runs=len(got), want_runs=len(want), dup=dup,
                    first=dict(list(diff.items())[:3]))


async def _sales(ck: Checks, w, mine, big: set, win: Window) -> None:
    """Sales records: one Creator per Agency that is not big, JSON pages and CSV; Agency 1 whole as CSV."""
    q = win.q()
    for i in (0, 1):
        aid = next(a for a in mine[i] if a not in big)  # run() checks each Agency has one
        want = oracle_sales(w, [aid], win.lo, win.hi)
        st, rows = await ck.pages(i, "/admin/stats/sales-records", _next_id, 400, **q, account_id=aid, limit=500)
        got = [(r["tx_id"], r["gross_cents"]) for r in rows]
        cst, crows, trunc = await ck.csv(i, "/admin/stats/sales-records", **q, account_id=aid)
        cgot = [(int(r["tx_id"]), int(r["gross_cents"])) for r in crows]
        if not (want and st == cst == 200 and got == want and cgot == want[:CSV_CAP]
                and trunc == (len(want) > CSV_CAP)):
            ck.fail(SALES, where=aid, status=[st, cst], json=len(got), csv=len(cgot), want=len(want), truncated=trunc,
                    json_sum=sum(g for _, g in got), want_sum=sum(g for _, g in want))
    want = oracle_sales(w, mine[1], win.lo, win.hi)
    st, crows, trunc = await ck.csv(1, "/admin/stats/sales-records", **q)
    cgot = [(int(r["tx_id"]), int(r["gross_cents"])) for r in crows]
    if not (want and st == 200 and cgot == want[:CSV_CAP] and trunc == (len(want) > CSV_CAP)):
        ck.fail(SALES, where="ag1 csv", status=st, rows=len(cgot), want=len(want), truncated=trunc)


async def _refusals(ck: Checks, mine, win: Window) -> dict[str, int]:
    """A foreign Creator id on every list: each answer's status (403 / 404 = refused)."""
    out = {}
    for i, other in ((1, mine[0][0]), (0, mine[1][0])):
        for path in ("/admin/stats/fan-report", "/admin/tips-list", "/admin/top-tippers", "/admin/paid-messages",
                     "/admin/stats/sales-records"):
            out[f"ag{i} {path}"], _ = await ck.json(i, path, **win.q(), account_id=other)
    return out


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    ags = [a["user_id"] for a in w.data["agencies"]]
    accounts = {i: {c["id"] for c in creators if c["owner"] == ags[i]} for i in range(len(ags))}
    mine = {i: [c["id"] for c in creators if c["owner"] == ags[i]] for i in (0, 1)}
    big = {c["id"] for c in creators if c.get("big")}
    n = ctx.param("n", w.size["ledger_reports_rows"])
    runs = ctx.param("runs", w.size["ledger_reports_runs"])
    recipients = ctx.param("recipients", w.size["ledger_reports_recipients"])
    load_s = ctx.param("load_s", {"small": 20, "medium": 60, "huge": 90}[ctx.scale])
    t0 = datetime.now()
    bulk = ledger_bulk.seed(w, creators, n=n, runs=runs, recipients=recipients)
    earnings.seed(w, [c for c in creators if c["owner"] in ags[:2]], ctx.stack.tmp, history_days=40,
                  connected_days=5)
    tx_total = _rows(w, "SELECT COUNT(*) FROM transactions", [])[0][0]
    by_status = dict(_rows(w, "SELECT status, COUNT(*) FROM transactions GROUP BY status", []))
    ctx.metric("world", {"ledger_bulk": bulk, "earnings_rows": w.data["ledger_rows"], "transactions": tx_total,
                         "by_status": by_status, "seed_s": round((datetime.now() - t0).total_seconds(), 1),
                         "agency_creators": {i: len(v) for i, v in mine.items()}})

    today = w.now.date()
    win = Window(datetime.combine(today - timedelta(days=WINDOW_DAYS - 1), time(0)),
                 datetime.combine(today, time(23, 59, 59, 999_000)), datetime.combine(today - timedelta(days=6), time(0)))
    o_fans = {i: oracle_fans(w, mine[i], win.lo, win.hi) for i in (0, 1)}
    o_tips = {i: oracle_tips(w, mine[i], win.lo, win.hi) for i in (0, 1)}
    names = {(c["id"], f["id"]): f["name"] for c in creators for f in w.data["fans"][c["id"]]}
    scope = Scope(accounts)

    menus = {i: Menu(creators=mine[i],
                     fan_rows=[[names.get(k, str(k[1])), o_fans[i][k][0]] for k in ranked(o_fans[i], "total")[:1000]])
             for i in (0, 1)}
    for i in menus:  # the Sales records check needs a Creator that is not big
        if not set(mine[i]) - big:
            raise RuntimeError(f"Agency {i}: no Creator that is not big ({mine[i]}); the world changed")

    # ── Load: owners of both Agencies read the reports. ──────────────────────
    http = {0: ctx.owner, 1: w.data["agencies"][1]["http"]}
    ctx.metric("page_loads", await _load(ctx, http=http, menus=menus, windows=[win.q(), win.q(week=True)],
                                         load_s=load_s, scope=scope))
    probes = await _probes(ctx, w=w, http=http, big=big, win=win, o_fans0=o_fans[0],
                           o_tips0=o_tips[0])
    _budgets(ctx, probes)

    # ── Checks, against the oracle. ──────────────────────────────────────────
    ck = Checks(http, scope)
    o_paid = {i: oracle_paid(w, mine[i], win.lo, win.hi) for i in (0, 1)}
    xlsx = await _fan_report(ck, w, mine, o_fans, win)
    await _per_creator_fans(ck, mine, o_fans, win)
    await _tips(ck, mine, o_tips, win)
    await _paid(ck, o_paid, win)
    await _sales(ck, w, mine, big, win)
    refused = await _refusals(ck, mine, win)
    await ck.aclose()

    fans_ok, tips_ok = all(o_fans.values()), all(o_tips.values())
    each = {i: len(mine[i]) for i in (0, 1)}
    ctx.check(XLSX, **xlsx)
    # (check, its oracle set non-empty, extra detail); PAID / SALES need theirs per comparison.
    for name, ready, extra in (
            (FAN_TOTALS, fans_ok, {"fans": {i: len(o_fans[i]) for i in (0, 1)}, "window": win.q()}),
            (FAN_RANK, fans_ok, {}),
            (FAN_CSV, fans_ok, {"creators": each}),
            (TRAFFIC, fans_ok, {}),
            (TIPS, tips_ok, {"tips": {i: len(o_tips[i]) for i in (0, 1)}}),
            (TIPS_CSV, tips_ok, {}),
            (TOP_TOTALS, tips_ok, {"creators": each}),
            (TOP_RANK, tips_ok, {}),
            (TOP_CSV, tips_ok, {}),
            (PAID, True, {"runs": {i: len(o_paid[i]) for i in (0, 1)}}),
            (SALES, True, {})):
        ctx.check(name, ready and not ck.bad[name], wrong=ck.bad[name][:6], **extra)
    foreign = {i: sorted(v) for i, v in scope.foreign.items() if v}
    not_refused = {k: v for k, v in refused.items() if v not in (403, 404)}
    ctx.check(SCOPE, not foreign and not not_refused, foreign=foreign, not_refused=not_refused, lists=scope.lists)

    if not ctx.app:
        for name in (UI_TOTALS, UI_SIDE, PAGE_ERR_BOUNDED):
            ctx.skip(name, "--no-ui")
        return
    await _ui(ctx, w, mine[0])


async def _ui(ctx, w, mine: list[str]) -> None:
    async with ui.owner_browser(ctx, viewport=(1600, 1000)) as page:
        hits = await _fan_reports(ctx, w, page)
        await _page_error(ctx, page)  # its own list, so it runs whether or not Fan reports showed rows
    ctx.metric("ui", {"creators": mine, "fan_report_reads": len(hits)})


async def _fan_reports(ctx, w, page) -> list:
    hits = []
    page.on("response", lambda r: hits.append(r) if "/admin/stats/fan-report" in r.url
            and "format=csv" not in r.url and r.status == 200 else None)
    await page.goto(f"{ctx.app}/analytics/fan-reports", timeout=180_000)
    cells = page.locator('[data-testid="total-spend"]')
    try:
        await cells.first.wait_for(timeout=180_000)
    except Exception as e:  # noqa: BLE001
        await ui.shot(ctx, page, "fan-reports-failed")
        ctx.check(UI_TOTALS, False, error=f"no Top fans rows: {type(e).__name__}")
        ctx.skip(UI_SIDE, "the Fan reports page never showed its rows")
        return hits
    await page.wait_for_timeout(1500)  # a refetch after the Applied settings landed
    texts = await cells.all_inner_texts()
    resp = hits[-1] if hits else None
    body = await resp.json() if resp else {}
    q = {k: v[0] for k, v in parse_qs(urlsplit(resp.url).query).items()} if resp else {}
    top = body.get("top_fans", [])
    aid = q.get("account_id")
    lo, hi = (_instant(q["from"]), _instant(q["to"])) if "from" in q else (None, None)
    want = oracle_fans(w, [aid], lo, hi) if aid and lo else {}
    order = ranked(want, q.get("sort", "total"))
    api_ok = [(r["account_id"], r["fan_id"]) for r in top] == order[:100] and all(
        (r["total_cents"], r["tips_cents"], r["ppv_cents"]) == (want[(aid, r["fan_id"])][0],
                                                              want[(aid, r["fan_id"])][2], want[(aid, r["fan_id"])][3])
        for r in top if (aid, r["fan_id"]) in want)
    cells_ok = texts == [_fmt_cents(r["total_cents"]) for r in top]
    await cells.first.scroll_into_view_if_needed()
    await ui.shot(ctx, page, "fan-reports-settled")
    ctx.check(UI_TOTALS, bool(top) and api_ok and cells_ok, rows=len(top), cells=len(texts), account_id=aid,
              window=[q.get("from"), q.get("to")], api_ok=api_ok, cells_ok=cells_ok,
              first=list(zip(texts[:3], [r["total_cents"] for r in top[:3]])), screenshot="fan-reports-settled.png")

    btn = page.get_by_role("button", name="Download report")
    await btn.scroll_into_view_if_needed()
    await ui.shot(ctx, page, "fan-reports-download-trigger")
    try:
        async with page.expect_download(timeout=120_000) as dl:
            await btn.click()
        path = await (await dl.value).path()
        rows, trunc = _parse_csv(open(path, encoding="utf-8").read())
        got_total = sum(int(r["total_cents"]) for r in rows)
        ok = (bool(want) and trunc == (len(want) > CSV_CAP)
              and [(r["account_id"], int(r["fan_id"])) for r in rows] == order[:CSV_CAP]
              and (trunc or got_total == sum(v[0] for v in want.values())))
        ctx.check(UI_SIDE, ok, rows=len(rows), want=len(want), truncated=trunc, total=got_total,
                  want_total=sum(v[0] for v in want.values()), account_id=aid, file=str(path))
    except Exception as e:  # noqa: BLE001
        ctx.check(UI_SIDE, False, error=f"{type(e).__name__}: {e}"[:300])

    for page_path, route, shot in (("/analytics/message-dashboard?tab=mass", "/admin/paid-messages", "message-dashboard"),
                                   ("/analytics/sales-records", "/admin/stats/sales-records", "sales-records")):
        try:
            async with page.expect_response(lambda r, p=route: p in r.url, timeout=120_000):
                await page.goto(f"{ctx.app}{page_path}", timeout=180_000)
            await page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001 — the screenshot still shows what loaded
            pass
        await ui.shot(ctx, page, shot)
    return hits


_TIP_ROWS_JS = """() => {
  const b = [...document.querySelectorAll('button')].find((x) => /^(Load more|Loading…)$/.test(x.textContent.trim()));
  const list = b && b.closest('.space-y-2');
  return list ? list.querySelectorAll(':scope > .block').length : 0;
}"""


async def _page_error(ctx, page) -> None:
    """PAGE_ERR_BOUNDED: every Tips tab list read with a cursor (`before_id`, its next pages) answers 500 at the
    browser's wire (page.route, set before the tab opens), the list's foot scrolled into view for PAGE_ERR_WAIT_S;
    then the route lifted and Load more clicked, the next page's rows must render (the side effect)."""
    def is_next(u: str) -> bool:
        s = urlsplit(u)
        return s.path.endswith("/admin/tips-list") and "before_id=" in s.query and "format=csv" not in s.query

    asked: list[str] = []

    async def fail(route):
        asked.append(route.request.url)
        await route.fulfill(status=500, content_type="application/json", body='{"detail":"slop: injected 500"}')

    await page.route(is_next, fail)
    d: dict = {}
    try:
        async with page.expect_response(lambda r: "/admin/tips-list" in r.url and "before_id=" not in r.url,
                                        timeout=120_000):
            await page.goto(f"{ctx.app}/analytics/message-dashboard?tab=tips", timeout=180_000)
        foot = page.get_by_role("button", name=re.compile(r"^(Load more|Loading…)$"))
        await foot.wait_for(timeout=60_000)
        d["rows_before"] = await page.evaluate(_TIP_ROWS_JS)
        d["asked_before_scroll"] = len(asked)
        await foot.scroll_into_view_if_needed()
        await page.wait_for_timeout(PAGE_ERR_WAIT_S * 1000)
        d["page2_requests"] = len(asked)
        more = page.get_by_role("button", name="Load more")
        d["load_more_offered"] = await more.is_visible() and await more.is_enabled()
        d["error_banner"] = await page.get_by_text("Failed to load:").count() > 0
        await ui.shot(ctx, page, "page-error-trigger")
        await page.unroute(is_next, fail)
        await more.click(timeout=15_000)
        await page.wait_for_function(f"({_TIP_ROWS_JS})() > {d['rows_before']}", timeout=30_000)
        d["rows_after"] = await page.evaluate(_TIP_ROWS_JS)
        await ui.shot(ctx, page, "page-error-settled")
    except Exception as e:  # noqa: BLE001
        d["error"] = f"{type(e).__name__}: {e}"[:300]
        await ui.shot(ctx, page, "page-error-failed")
    finally:
        await page.unroute(is_next)
    n = d.get("page2_requests", 0)
    ctx.check(PAGE_ERR_BOUNDED, "error" not in d and d["rows_before"] > 0 and 1 <= n <= 2 and d["load_more_offered"]
              and d["rows_after"] > d["rows_before"], **d, wait_s=PAGE_ERR_WAIT_S,
              screenshots=["page-error-trigger.png", "page-error-settled.png"])
