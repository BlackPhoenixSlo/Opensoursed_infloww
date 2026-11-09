"""Backfill correctness evidence for sweep-pacing's marker, gap, and shared-bucket walks."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from slop.lib.sweep_pacing_evidence import held, scan_one, tx_status as _tx_status
from slop.lib.sweep_pacing_faults import (BF_BURST, BF_CALLS, BF_DISPUTE, BF_DROPPED, BF_FRESH, BF_GAP,
                                          BF_LIFETIME, BF_ONCE, BF_PARTIAL, BF_SHARED)
from slop.lib.sweep_pacing_ledger import (CROWD_ROWS, DEEP_ROWS, DEEP_WALK_PAGE, FRESH_PAGES, REACT_DISPUTED,
                                          REACT_FLIP_FROM, REACT_FLIPS, REACT_GAP_D, REACT_ROWS, TICK_PAGES,
                                          TX_CYCLES, TX_PAGE, pages as _pages, sale as _sale)
from slop.seed import ts


def check(ctx, w, sw, *, deep, react, blank, gap_a, crowd, passed, react0, blank0, gap0, admin, pass_modes,
          plog, log, cycles, same, t_walks, since, sse) -> None:
    ledger_only = (deep, react, blank, gap_a, *crowd)
    # ── the backfill's marker walk: DEEP, REACT, BLANK, GAP, CROWD ──────────
    end = {a: scan_one(w, a) for a in ledger_only}
    held_rows = {a: held(w, a) for a in ledger_only}

    def start_date(a: str) -> str:
        return (datetime.fromisoformat(end[a]["floor"]) - timedelta(days=1)).date().isoformat()

    def of_rows(a: str) -> list[dict]:
        # BLANK's old rows sit below its window, held since before it: OF's sum and ours hold them.
        return [r for r in sw.txs[a] if r["createdAt"][:10] >= start_date(a) or a == blank]

    def cents(rows: list[dict]) -> int:
        return sum(round(r["amount"] * 100) for r in rows)

    disputed = sw.txs[react][REACT_DISPUTED]
    dropped, doubled, wrong_sum, wrong_life = {}, {}, {}, {}
    for a in ledger_only:
        want, got_ = {str(r["id"]) for r in of_rows(a)}, held_rows[a][0]
        missing, above = want - set(got_), set(got_) - want
        dropped[a] = {"of": len(want), "held": len(got_), "missing": len(missing), "not_in_window": len(above),
                      "done": end[a]["done"], "e_g": sorted(missing | above)[:3]}
        doubled[a] = sum(1 for n in got_.values() if n > 1)
        wrong_sum[a] = {"of_cents": cents(of_rows(a)), "held_cents": held_rows[a][1]}
        wrong_life[a] = {"of_cents": cents(of_rows(a)) - (cents([disputed]) if a == react else 0),
                         "lifetime_cents": held_rows[a][2]}
    ctx.check(BF_DROPPED, all(v["missing"] == 0 and v["not_in_window"] == 0 and v["done"] for v in dropped.values()),
              **{a: dropped[a] for a in dropped})
    con = w.sql()
    # A first charge and a renewal are one count: the writer relabels a fan's later `Subscription from` a rebill.
    sub = lambda k: "sub" if k in ("subscription", "rebill") else k  # noqa: E731
    kinds = {a: (dict(Counter(sub(k) for k, in con.execute(
        "SELECT kind FROM transactions WHERE account_id = ? AND provider_transaction_id IS NOT NULL", (a,)))),
        dict(Counter(sub(_sale(r)[0]) for r in of_rows(a)))) for a in dropped}
    con.close()
    ctx.check(BF_ONCE, not any(doubled.values()) and all(v["of_cents"] == v["held_cents"] for v in wrong_sum.values())
              and all(held_k == of_k for held_k, of_k in kinds.values()),
              doubled=doubled, sums=wrong_sum, kinds_held_vs_of=kinds)
    ctx.check(BF_LIFETIME, all(v["of_cents"] == v["lifetime_cents"] for v in wrong_life.values()), lifetime=wrong_life)

    s1 = passed.get(1, {})
    d1, r1, d2, d3 = s1.get(deep) or {}, s1.get(react) or {}, (passed.get(2) or {}).get(deep) or {}, (passed.get(3) or {}).get(deep) or {}
    b1, g1 = s1.get(blank) or {}, s1.get(gap_a) or {}
    partial = {
        "reactivation_reopened": react0["done"] == 0 and bool(react0["floor"])
        and react0["floor"][:10] == ts(w.now - timedelta(days=REACT_GAP_D))[:10] and react0["cursor"] is None,
        "deep_pass1_not_done": d1.get("done") == 0,
        "deep_pass1_cursor_saved": bool(d1.get("cursor")),
        "deep_pass1_429_recorded": "429" in (d1.get("last_error") or "") and d1.get("failures") == 2,
        "deep_pass1_not_paused": d1.get("status") != "paused" and not d1.get("paused_until"),
        "react_pass1_not_done": r1.get("done") == 0,
        "react_pass1_stalled": r1.get("status") == "backfill_stalled" and bool(r1.get("cursor"))
        and r1.get("last_error") == "backfill_stopped: empty_page",
        "blank_reopened": blank0["done"] == 0 and blank0["cursor"] is None,
        "blank_pass1_stalled": b1.get("done") == 0 and b1.get("status") == "backfill_stalled"
        and b1.get("last_error") == "backfill_stopped: blank_first_page",
        "admin_run_accepted": admin.get("status") == 202,
        "deep_pass2_refreshed_cursor_kept": len(pass_modes) > 1 and pass_modes[1].get(deep) == "refresh"
        and d2.get("done") == 0 and bool(d1.get("cursor")) and d2.get("cursor") == d1.get("cursor"),
        "deep_pass3_not_done": d3.get("done") == 0,
        "deep_pass3_cursor_lower": bool(d3.get("cursor")) and bool(d2.get("cursor")) and d3["cursor"] < d2["cursor"],
        "all_complete_at_end": all(end[a]["done"] == 1 for a in end),
        "none_paused_at_end": not any(end[a]["paused_until"] for a in end),
    }
    ctx.check(BF_PARTIAL, all(partial.values()), **partial, deep_pass1=d1, react_pass1=r1, blank_pass1=b1,
              deep_pass2=d2, deep_pass3=d3, end={a: end[a] for a in (deep, react, blank, gap_a)})

    # ── GAP: the resumed read that cannot reach newest_seen ─────────────────
    capped = [y for y in plog if "ingest_tx_backfill_recent_capped" in y["msg"] and f"account={gap_a}" in y["msg"]]
    gap_gets = sorted((e for e in log if e["account"] == gap_a and e["route"] == "transactions" and e["status"] == 200
                       and len(cycles) > 1 and cycles[1]["t0"] <= e["t"] <= cycles[1]["t1"]), key=lambda e: e["t"])
    gap_q = [parse_qs(e["query"]) for e in gap_gets]
    rewalk = {
        "pass1_refresh": bool(pass_modes) and pass_modes[0].get(gap_a) == "refresh",
        "pass1_left_the_range": g1.get("newest") == gap0["newest"] and g1.get("cursor") == gap0["cursor"],
        "pass2_read_capped": len(capped) == 1,
        "pass2_read_pages": [e["offset"] for e in gap_gets[:FRESH_PAGES]] == [TX_PAGE * k for k in range(FRESH_PAGES)],
        "pass2_walk_from_the_top": len(gap_q) > FRESH_PAGES + 1 and "marker" not in gap_q[FRESH_PAGES]
        and "marker" in gap_q[FRESH_PAGES + 1],
        "complete_at_end": end[gap_a]["done"] == 1,
    }
    ctx.check(BF_GAP, all(rewalk.values()), **rewalk, gets=len(gap_gets), scan_seeded=gap0, scan_pass1=g1, scan_end=end[gap_a])

    # ── CROWD: one shared bucket ────────────────────────────────────────────
    crowd_set = set(crowd)
    crowd_429 = [e for e in log if e["account"] in crowd_set and e["status"] == 429]
    crowd_terminal, crowd_refresh_terminal = [], []
    for e in crowd_429:
        page = same[(e["account"], e["route"], e["query"])]
        if any(x["t"] < e["t"] and x["status"] == 429 for x in page):
            # The full 7-day walk (`start=`, _REFRESH_CONCURRENCY, unchanged) is reported, not held to this: its tick
            # fails and the next one redoes it, so the bound below gives it those pages.
            (crowd_refresh_terminal if "start=" in e["query"] else crowd_terminal).append(
                {"account": e["account"], "t": round(e["t"] - t_walks, 1), "query": e["query"]})
    crowd_calls = {}
    for a in crowd:
        rows_ = sw.txs[a]
        recent_rows = sum(1 for r in rows_ if r["createdAt"][:10] >= since)
        # Its walk + a full walk + its recent walks (never more pages than rows imply) + 2 polls (complete, full).
        bound = (_pages(len(rows_)) + 1 + FRESH_PAGES + (TX_CYCLES - 2) * _pages(recent_rows)
                 + FRESH_PAGES * sum(1 for x in crowd_refresh_terminal if x["account"] == a))
        n = sum(1 for e in log if e["account"] == a and e["route"] == "transactions" and e["status"] == 200)
        cb_n = sum(1 for e in log if e["account"] == a and e["route"] == "chargebacks")
        crowd_calls[a] = {"ledger": n, "bound": bound, "disputes": cb_n}
    crowd_done = {a: end[a]["done"] for a in crowd}
    ctx.check(BF_SHARED, all(crowd_done.values()) and not crowd_terminal
              and all(v["ledger"] <= v["bound"] and v["disputes"] <= 2 for v in crowd_calls.values()),
              creators=len(crowd), rows_each=CROWD_ROWS, of_429s=len(crowd_429), terminal_429s=len(crowd_terminal),
              refresh_terminal_429s=crowd_refresh_terminal,
              e_g=crowd_terminal[:4], calls=crowd_calls, not_done=[a for a, v in crowd_done.items() if not v],
              refill_per_s=sw.refill_per_s, burst=sw.burst)

    def walk_entries(a: str, t0: float, t1: float) -> tuple[list[dict], list[dict]]:
        """The Creator's ledger GETs between t0 and t1, 200s: its marker walk's / its recent read's."""
        rows = [e for e in log if e["account"] == a and e["route"] == "transactions" and t0 <= e["t"] <= t1
                and e["status"] == 200]
        wk = [e for e in rows if (parse_qs(e["query"]).get("startDate") or [""])[0] == start_date(a)]
        return wk, [e for e in rows if e not in wk]

    spans = [(c["t0"], c["t1"]) for c in cycles]
    react_spans = [(admin.get("t0") or 0, admin.get("t1") or 0), *spans[:1]]
    react_walks = [{"walk": len(x), "recent": len(y)} for x, y in (walk_entries(react, *c) for c in react_spans)]
    deep_full = [c for c, ms in zip(spans, pass_modes) if ms.get(deep) == "refresh"]   # no startDate: not a walk's
    deep_spans = [{"walk": len(x), "recent": len(y)} for x, y in (walk_entries(deep, *c) for c in spans if c not in deep_full)]
    deep_end = spans[-1][1] if spans else 0
    react_end = max(admin.get("t1") or 0, spans[0][1] if spans else 0)
    wire = [e for a in (deep, react) for e in log if e["account"] == a and e["route"] == "transactions"
            and e["t"] <= (deep_end if a == deep else react_end)
            and not (a == deep and any(t0 <= e["t"] <= t1 for t0, t1 in deep_full))]
    bad_wire = [e["query"] for e in wire
                if {"start", "end"} & set(parse_qs(e["query"]))
                or len((parse_qs(e["query"]).get("startDate") or [""])[0]) != 10]
    walk_q = [e for a in (deep, react) for c in ([*spans] if a == deep else react_spans) for e in walk_entries(a, *c)[0]]
    bad_offset = [e["query"] for e in walk_q if e["offset"] != 0]
    deep_total = sum(x["walk"] for x in deep_spans)
    deep_bound = DEEP_ROWS // DEEP_WALK_PAGE + len(spans)
    deep_cb = sum(1 for e in log if e["account"] == deep and e["route"] == "chargebacks")
    ctx.check(BF_CALLS, all(x["walk"] <= TICK_PAGES and x["recent"] <= FRESH_PAGES for x in [*deep_spans, *react_walks])
              and not bad_wire and not bad_offset and deep_total <= deep_bound and deep_cb == 2,
              deep_disputes_calls=deep_cb,
              tick_cap=TICK_PAGES, fresh_cap=FRESH_PAGES, deep_per_pass=deep_spans, react_admin_then_pass1=react_walks,
              deep_walk_pages=deep_total, deep_bound=deep_bound, bad_wire=bad_wire[:3], bad_offset=bad_offset[:3])

    pass3 = sorted((e for e in log if e["account"] == deep and e["route"] == "transactions"
                    and spans[2][0] <= e["t"] <= spans[2][1]), key=lambda e: e["t"]) if len(spans) > 2 else []
    fresh_first = bool(pass3) and "marker" not in pass3[0]["query"]
    ctx.check(BF_FRESH, passed.get(3, {}).get("fresh_held") is True and fresh_first
              and partial["deep_pass3_cursor_lower"],
              fresh_held_after_pass3=passed.get(3, {}).get("fresh_held"), pass3_first_get=pass3[0]["query"] if pass3 else None,
              cursor_pass2=d2.get("cursor"), cursor_pass3=d3.get("cursor"))

    con = w.sql()
    flips = dict(con.execute("SELECT status, COUNT(*) FROM transactions WHERE account_id = ? AND provider_transaction_id IN "
                             f"({','.join('?' * (REACT_FLIPS + 1))}) GROUP BY status",
                             (react, *(str(sw.txs[react][k]["id"]) for k in (0, *range(REACT_FLIP_FROM, REACT_FLIP_FROM + REACT_FLIPS)))))
                 .fetchall())
    con.close()
    react_all = [f for _t, f, acct in sse.state_events if str(acct) == str(react)]
    react_news = [f for f in react_all if f.get("status") != "chargedback"]
    dispute_news = [f for f in react_all if f.get("status") == "chargedback"]
    dispute = {"pass1_status": passed.get(1, {}).get("disputed"), "end_status": _tx_status(w, react, disputed["id"]),
               "lifetime": wrong_life[react], "announced": len(dispute_news),
               "disputes_calls": sum(1 for e in log if e["route"] == "chargebacks" and e["account"] == react)}
    ctx.check(BF_DISPUTE, dispute["pass1_status"] == dispute["end_status"] == "chargedback"
              and wrong_life[react]["of_cents"] == wrong_life[react]["lifetime_cents"] and len(dispute_news) == 1,
              **dispute)
    ctx.check(BF_BURST, flips == {"cleared": REACT_FLIPS + 1} and len(react_news) == 1,
              db_statuses=flips, sse_events=len(react_news), sse_all=len(sse.state_events), e_g=react_news[:3],
              frames=sse.frames, stream_ended=sse.ended)
    ctx.metric("tx_backfill", {"deep": deep, "react": react, "blank": blank, "gap": gap_a, "crowd": crowd, "deep_per_pass": deep_spans, "react_per_run": react_walks,
                               "deep_rows": DEEP_ROWS, "react_rows": REACT_ROWS,
                               "backfill_stops": [y["msg"] for y in plog if "ingest_tx_backfill_stop" in y["msg"]]})
