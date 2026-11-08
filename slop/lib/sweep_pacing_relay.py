"""The background OF walks' part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`), for scenarios/2026-11-05-sweep-pacing.py. Inert until called.

  POST /__slop/sweep-pacing/knobs {NAME: seconds, ...}  sets service/of_pacing.py's USER_WINDOW_S
       and link_metrics' _PREWARM_SPREAD_S (time compression, declared) and from then on keeps of_pacing's,
       link_metrics' and transaction_ingest's log lines (each ledger walk's mode: ingest_tx_scan_start).
       Pins transaction_ingest.full_phase_s for the run (bypass, declared); `"PHASE_PIN": false`
       restores the product's crc32 phase instead (the watermark stage: a restarted relay).
       The pacer's own PAGE_GAP_S / JITTER_S and the 429 retry are never set here.
  POST /__slop/sweep-pacing/run {job, account_ids, cycles}  starts the production job in a fresh
       context (no request around it, as the supervisors' tasks), and answers at once:
         link_prewarm  link_metrics.prewarm_all()   once (the hourly loop's pass; account_ids unused)
         subscribers   lifecycle_messages.refresh_roster(aid, ax._make_client(aid), now=utcnow())
                       per Creator (the lifecycle sweep's roster crawl)
         tx_cycles     transaction_ingest.supervisor_cycle() `cycles` times back to back (the
                       ledger supervisor's loop body over every live Creator); result: each
                       cycle's {t0, t1}
       Bypass, declared: the jobs' cadences (hourly / 30 min / _TICK_INTERVAL_S) and prewarm_all's spread.
  POST /__slop/sweep-pacing/failover {label}  an ADR-0030 move of the pool proxy `label`'s Creators now:
       proxies.failover_pool (each destination probed by proxy_health.verify_pick, one registry
       write, the clients evicted) -> {moved}. Bypass, declared: the trigger (DOWN_AFTER failures,
       the confirm, two failed rechecks); the move is the product's.
  GET  /__slop/sweep-pacing/runs  {runs: [{n, job, account, t0, t1, error, result}], log: [{t, msg}],
       tick_interval_s: transaction_ingest._TICK_INTERVAL_S (the supervisor's sleep this relay runs with),
       full_every_s: transaction_ingest._FULL_EVERY_S (its full 7-day walk's period),
       recent_window_h: transaction_ingest._RECENT_WINDOW_H,
       phases: {id: transaction_ingest.full_phase_s(id, full_every_s)} for `?phase_ids=a,b`}
"""

import asyncio
import contextvars
import logging
import time
from datetime import datetime

KNOBS = ("USER_WINDOW_S",)
SPREAD = "PREWARM_SPREAD_S"   # link_metrics._PREWARM_SPREAD_S
_runs: list[dict] = []
_log: list[dict] = []
_tasks: set = set()


_TX_KEEP = ("ingest_tx_scan_start", "ingest_tx_scan_end", "ingest_tx_recent_window_ignored",
            "ingest_tx_recent_walk_empty", "ingest_tx_backfill_stop", "ingest_tx_backfill_recent_capped")


class _Keep(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "of-relay.ingest_tx" and not record.getMessage().startswith(_TX_KEEP):
            return
        _log.append({"t": record.created, "msg": record.getMessage()})


_keep = _Keep(logging.INFO)


async def _job(job: str, aid: str, cycles: int = 1):
    if job == "link_prewarm":
        import link_metrics
        return await link_metrics.prewarm_all()
    if job == "subscribers":
        import automation_executor as ax
        from automations import lifecycle_messages
        client = await asyncio.to_thread(ax._make_client, aid)
        return await lifecycle_messages.refresh_roster(aid, client, now=datetime.utcnow())
    if job == "tx_cycles":
        import transaction_ingest
        out = []
        for _ in range(cycles):
            t0 = time.time()
            await transaction_ingest.supervisor_cycle()
            out.append({"t0": t0, "t1": time.time()})
        return {"cycles": out}
    raise ValueError(f"unknown job {job!r}")


def wire(app, loopback, _relay) -> None:
    from fastapi import HTTPException, Request

    async def knobs(request: Request) -> dict:
        loopback(request)
        import link_metrics
        import of_pacing
        body = await request.json()
        pin = body.pop("PHASE_PIN", True)
        for k, v in body.items():
            if k == SPREAD:
                link_metrics._PREWARM_SPREAD_S = float(v)
            elif k in KNOBS:
                setattr(of_pacing, k, float(v))
            else:
                raise HTTPException(400, f"not a knob: {k}")
        for name in ("of-relay.of_pacing", link_metrics.log.name, "of-relay.ingest_tx"):
            lg = logging.getLogger(name)
            if _keep not in lg.handlers:
                lg.addHandler(_keep)
                lg.setLevel(logging.INFO)
        # Every Creator a quarter into its full-walk period, so none crosses one mid-run: a crossing adds a full walk
        # to whichever Creator's crc32 phase falls in those minutes, and reds its call bounds (measured, 3 runs of ~17).
        import transaction_ingest as ti
        import transaction_ingest_decide
        now = (datetime.utcnow() - datetime(1970, 1, 1)).total_seconds()
        ti.full_phase_s = ((lambda _account_id, every=ti._FULL_EVERY_S: (every / 4 - now) % every) if pin
                           else transaction_ingest_decide.full_phase_s)
        return {**{k: getattr(of_pacing, k) for k in (*KNOBS, "PAGE_GAP_S", "JITTER_S")},
                SPREAD: link_metrics._PREWARM_SPREAD_S}

    async def run(request: Request) -> dict:
        loopback(request)
        body = await request.json()
        job = body["job"]
        started = []
        for aid in (body.get("account_ids") or ()) if job == "subscribers" else ("*",):
            rec = {"n": len(_runs), "job": job, "account": str(aid), "t0": time.time(), "t1": None,
                   "error": None, "result": None}
            _runs.append(rec)

            async def go(rec=rec):
                try:
                    res = await _job(job, rec["account"], int(body.get("cycles") or 1))
                    rec["result"] = res if isinstance(res, (dict, type(None))) else repr(res)
                except Exception as e:  # noqa: BLE001  the run's answer, never the relay's
                    rec["error"] = repr(e)[:300]
                rec["t1"] = time.time()

            t = asyncio.get_running_loop().create_task(go(), context=contextvars.Context())
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)
            started.append(rec["n"])
        return {"started": started}

    async def runs(request: Request) -> dict:
        loopback(request)
        import transaction_ingest
        every = transaction_ingest._FULL_EVERY_S
        ids = [x for x in (request.query_params.get("phase_ids") or "").split(",") if x]
        return {"runs": [dict(r) for r in _runs], "log": list(_log),
                "tick_interval_s": transaction_ingest._TICK_INTERVAL_S,
                "full_every_s": every,
                "recent_window_h": transaction_ingest._RECENT_WINDOW_H,
                "phases": {a: transaction_ingest.full_phase_s(a, every) for a in ids}}

    async def failover(request: Request) -> dict:
        loopback(request)
        import proxies
        import proxy_health
        label = (await request.json())["label"]
        moved = await asyncio.to_thread(proxies.failover_pool, label, bad=set(), geo=proxy_health.last_geo,
                                        verify=proxy_health.verify_pick)
        return {"moved": moved}

    app.add_api_route("/__slop/sweep-pacing/knobs", knobs, methods=["POST"])
    app.add_api_route("/__slop/sweep-pacing/run", run, methods=["POST"])
    app.add_api_route("/__slop/sweep-pacing/runs", runs, methods=["GET"])
    app.add_api_route("/__slop/sweep-pacing/failover", failover, methods=["POST"])
