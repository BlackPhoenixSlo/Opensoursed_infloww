"""Ledger pages paced per bound proxy (service/of_pacing.py `egress`), the last stage of
scenarios/2026-11-05-sweep-pacing.py (tx_proxy_pages_spaced).

PX_N Creators held out of every other check (an empty ledger until now, so the earlier passes
only completed their backfill) get PX_ROWS ledger rows of the last 6 days each. POOL fake proxies
(lib/proxy_wire.py) join the pool (`POST /__slop/proxy-pool`, the startup's sync) and each Creator
is bound through the product's `POST /admin/proxy-pool/assign` (least-used: 2 per proxy, so every
proxy is shared and the proxies are separate). Phase 1: every Creator's full walk at once
(`POST /admin/ingest/transactions/{id}/run` mode refresh: supervised_tick, paced as the
supervisor's). Then an ADR-0030 move: the last proxy's Creators failed over by
`proxies.failover_pool` (`POST /__slop/sweep-pacing/failover`: its one registry write, the
clients evicted; each destination probed first). Phase 2: every full walk at once again, 3 a proxy.

Per phase, at OF (lib/sweep_pacing_wire.py's log, each ledger GET's egress = the tunnel it came
through): per egress, every ledger GET left >= PAGE_GAP_S (- SPACE_SLACK_S) after the one before;
each Creator's GETs came through the proxy it is bound to at that time (after the move: the new
one, so the evicted client was rebuilt on the new transport); two egresses sent within
PAGE_GAP_S / 2 of each other (endpoints proceed independently, not one global slot); every GET 200;
the move moved exactly the last proxy's Creators onto the others. Ledger totals: each Creator holds
PX_ROWS rows, their SUM(amount_cents) and its fans' SUM(lifetime_spend_cents) == OF's sum after
phase 1, unchanged by phase 2.

Bypasses (declared): the move's trigger (a dead proxy's DOWN_AFTER failures, its confirm and two
failed rechecks, ~100 s) is the hook calling `proxies.failover_pool` on a live proxy; the move
itself is the product's. OF's limit stays per Creator (lib/sweep_pacing_wire.py): no per-IP
bucket is modelled, the check measures departure spacing per egress, not 429s.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict
from contextlib import ExitStack
from datetime import timedelta

from slop.lib.proxy_wire import ProxyWire
from slop.lib.sweep_pacing_faults import TX_PROXY_SPACED
from slop.lib.sweep_pacing_ledger import tx_row

PX_N, POOL, PX_ROWS = 6, 3, 450   # 5 ledger pages a walk (OF's 100 a page)
WALK_TIMEOUT_S = 180
# The rest of the scenario's topology (`bind`): AE's Creators are all on proxies, at most 5 on one
# (measured: proxy-health digests 2026-11-07/08, infloww-eba313d6 after the moves; 13-16 Creators,
# ~8 pool labels). Direct clients share one slot (the host's IP): every Creator direct would page
# the whole ledger through it (measured: 20261108T074315Z-2026-11-05-sweep-pacing-8241, ~1.16 s a page).
PER_PROXY = 5
BIND_THINK_S = 1.0   # back-to-back binds race the SQL mirror's sync (scenarios/2026-10-28-dead-proxy-interactive-reads.py)


async def bind(ctx, st: ExitStack, groups: list[list[str]]) -> dict[str, str]:
    """Each group on its own fake proxy (lib/proxy_wire.py, alive until `st` closes), through the
    product's `POST /admin/proxies` + `POST /admin/proxies/assign` (the owner's custom proxies, so
    this stage's pool sync never touches them). -> Creator -> "127.0.0.1:<port>". A refused bind ends
    the run: a Creator left direct would share the host's slot."""
    out: dict[str, str] = {}
    for k, g in enumerate(groups):
        wire = st.enter_context(ProxyWire())
        label = f"slop-tx-{k}"
        r = await ctx.owner.post("/admin/proxies", json={"label": label, "scheme": "socks5", "host": "127.0.0.1",
                                                         "port": wire.port, "notes": "slop: sweep-pacing topology"})
        if r.status_code != 200:
            raise RuntimeError(f"slop: POST /admin/proxies {label}: {r.status_code} {r.text[:200]}")
        for a in g:
            await asyncio.sleep(BIND_THINK_S)
            r = await ctx.owner.post("/admin/proxies/assign", json={"label": label, "account_id": a})
            if r.status_code != 200:
                raise RuntimeError(f"slop: assign {a} to {label}: {r.status_code} {r.text[:200]}")
            out[a] = f"127.0.0.1:{wire.port}"
    return out


def _bindings(path, aids) -> dict[str, str]:
    """Creator -> "127.0.0.1:<port>" of the proxy proxies.json binds it to."""
    out = {}
    for p in json.loads(path.read_text()).get("proxies", []):
        for a in p.get("assigned_account_ids") or ():
            if a in aids:
                out[a] = f"{p['host']}:{p['port']}"
    return out


def _labels(path) -> dict[str, str]:
    return {f"{p['host']}:{p['port']}": p["label"] for p in json.loads(path.read_text()).get("proxies", [])}


def _totals(w, aids) -> dict[str, tuple[int, int, int]]:
    con = w.sql()
    out = {}
    for a in aids:
        n, s = con.execute("SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) FROM transactions WHERE account_id = ? "
                           "AND provider_transaction_id IS NOT NULL", (a,)).fetchone()
        life = con.execute("SELECT COALESCE(SUM(lifetime_spend_cents), 0) FROM fans WHERE account_id = ?",
                           (a,)).fetchone()[0]
        out[a] = (n, s, life)
    con.close()
    return out


def _status(w, aids) -> dict[str, str]:
    con = w.sql()
    q = f"SELECT account_id, current_status FROM transaction_scan_history WHERE account_id IN ({','.join('?' * len(aids))})"
    out = dict(con.execute(q, list(aids)).fetchall())
    con.close()
    return out


_SCAN_END = re.compile(r"ingest_tx_scan_end account=(\S+) ")


async def _walks(ctx, w, sw, aids) -> dict:
    """Every Creator's full walk at once; its ledger GETs at OF once all ended: each tick's
    ingest_tx_scan_end (after its disputes poll, which still goes through the proxy; the status
    settles before it) or, failed, its status settled."""
    t0 = time.time()
    got = await asyncio.gather(*(ctx.owner.post(f"/admin/ingest/transactions/{a}/run", json={"mode": "refresh"})
                                 for a in aids))
    accepted = [r.status_code for r in got]
    until = time.monotonic() + WALK_TIMEOUT_S
    while time.monotonic() < until:
        await asyncio.sleep(1.0)
        st = _status(w, aids)
        ended = {m.group(1) for y in (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()["log"]
                 if y["t"] >= t0 and (m := _SCAN_END.search(y["msg"]))}
        gets = [e for e in sw.snapshot() if e["t"] >= t0 and e["route"] == "transactions" and e["account"] in aids]
        if all(st.get(a) not in ("refreshing", "backfilling") and (a in ended or st.get(a) == "error") for a in aids) \
                and {e["account"] for e in gets} >= set(aids):
            break
    gets = [e for e in sw.snapshot() if e["t"] >= t0 and e["route"] == "transactions" and e["account"] in aids]
    return {"t0": t0, "t1": time.time(), "accepted": accepted, "gets": gets, "status": _status(w, aids)}


def _judge(p: dict, binding: dict[str, str], gap: float, slack: float) -> dict:
    by_eg: dict[str, list[float]] = defaultdict(list)
    for e in p["gets"]:
        by_eg[e.get("egress") or "?"].append(e["t"])
    gaps = {eg: round(min((b - a for a, b in zip(sorted(ts), sorted(ts)[1:])), default=99.0), 3)
            for eg, ts in by_eg.items()}
    pairs = [(e["t"], e.get("egress")) for e in p["gets"]]
    overlap = any(abs(t1 - t2) < gap / 2 and g1 != g2 for (t1, g1), (t2, g2) in zip(sorted(pairs), sorted(pairs)[1:]))
    off_binding = sorted({e["account"] for e in p["gets"] if e.get("egress") != binding.get(e["account"])})
    per = defaultdict(int)
    for e in p["gets"]:
        per[e["account"]] += 1
    return {"min_gap_s": gaps, "spaced": all(g >= gap - slack for g in gaps.values()),
            "endpoints_overlap": overlap, "off_binding": off_binding,
            "gets": dict(per), "non_200": [e["status"] for e in p["gets"] if e["status"] != 200],
            "accepted": p["accepted"], "unsettled": {a: s for a, s in p["status"].items() if s in ("refreshing", "backfilling")},
            "wall_s": round(p["t1"] - p["t0"], 1)}


async def run(ctx, w, sw, px: list[str], rows: dict[str, list[dict]], *, gap: float, slack: float) -> None:
    reg = ctx.stack.sessions.parent / "proxies.json"
    with ExitStack() as st:
        wires = [st.enter_context(ProxyWire()) for _ in range(POOL)]
        text = ",".join(f"socks5://127.0.0.1:{p.port}" for p in wires)
        synced = (await ctx.owner.post("/__slop/proxy-pool", json={"text": text})).status_code
        assigned = [(await ctx.owner.post("/admin/proxy-pool/assign", json={"account_id": a})).status_code for a in px]
        b1 = _bindings(reg, set(px))
        for a in px:
            sw.txs[a] = rows[a]
        want = {a: (len(rows[a]), sum(round(r["amount"] * 100) for r in rows[a])) for a in px}
        p1 = await _walks(ctx, w, sw, px)
        tot1 = _totals(w, px)
        last = f"127.0.0.1:{wires[-1].port}"
        on_last = sorted(a for a, eg in b1.items() if eg == last)
        mv = await ctx.owner.post("/__slop/sweep-pacing/failover", json={"label": _labels(reg).get(last)})
        moved = sorted(mv.json().get("moved") or []) if mv.status_code == 200 else None
        b2 = _bindings(reg, set(px))
        p2 = await _walks(ctx, w, sw, px)
        tot2 = _totals(w, px)
    j1, j2 = _judge(p1, b1, gap, slack), _judge(p2, b2, gap, slack)
    per_proxy = defaultdict(list)
    for a, eg in b1.items():
        per_proxy[eg].append(a)
    shared = len(per_proxy) == POOL and all(len(v) >= 2 for v in per_proxy.values())
    totals_ok = all(tot1[a][0] == want[a][0] and tot1[a][1] == want[a][1] == tot1[a][2] for a in px) and tot1 == tot2
    move_ok = (moved == on_last and bool(on_last) and all(b2[a] != last for a in px)
               and all(b2[a] == b1[a] for a in px if a not in on_last))

    def ok(j: dict) -> bool:
        return (j["spaced"] and j["endpoints_overlap"] and not j["off_binding"] and not j["non_200"]
                and not j["unsettled"] and all(s == 202 for s in j["accepted"]) and len(j["gets"]) == len(px))
    ctx.check(TX_PROXY_SPACED, synced == 200 and all(s == 200 for s in assigned) and len(b1) == len(px) and shared
              and ok(j1) and ok(j2) and move_ok and totals_ok,
              creators=px, bound=b1, moved=moved, on_moved_proxy=on_last, bound_after=b2,
              phase1=j1, phase2=j2, totals_after_1=tot1, totals_after_2=tot2, want=want,
              synced=synced, assigned=assigned)
    ctx.metric("tx_proxy_pacing", {"phase_wall_s": [j1["wall_s"], j2["wall_s"]],
                                   "min_gap_s": [j1["min_gap_s"], j2["min_gap_s"]]})


def ledger_rows(rng, base: int, fan_ids: list[int], now) -> list[dict]:
    """PX_ROWS rows newest first over the last 6 days (inside the full walk's 7)."""
    step = timedelta(days=6) / PX_ROWS
    return [tx_row(base + k, rng.choice(fan_ids), rng.randint(5, 50) * 100, now - timedelta(minutes=5) - step * k)
            for k in range(PX_ROWS)]
