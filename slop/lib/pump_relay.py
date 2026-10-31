"""The pump supervisor's part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`), for scenarios/2026-10-25-session-health-otp.py's crash-loop check.

A pump that exits without parking (an error before its own reconnect loop: e.g. its
start-up `is_deactivated` read failing) cannot be provoked from OnlyFans' side: every
wire failure the pump meets is retried inside it (of_ws's 1-30 s backoff, the pump's
10 / 30 s sleeps) or parks it. So this stands in for it, harness side, never in service/:

  POST /__slop/pump-crash {account_ids}  from now on a pump task started for one of
       these Creators returns at once (exits without parking, no socket, no OF call);
       a pump already running for one is stopped (`server._do_stop_account_pump`, as
       the deactivate endpoint does), so the next supervisor pass Starts a crashing
       one whatever the Stop before it did; `[]` ends it. Bypass, declared: the
       crashing pump body and that stop are the harness's; the supervisor
       (`server._reconcile_pumps`), `pump_reconcile.reconcile` / `restart_due`, the
       start, stop and exit bookkeeping are the product's.
  GET  /__slop/pump-crash  {account_ids, starts: {account: [epoch s, ...]}}: each
       crashing pump's start, in order (one per Start or Restart that reached it).
"""

import time

_crash: set[str] = set()
_starts: dict[str, list[float]] = {}


def wire(app, _loopback, _relay) -> None:
    from fastapi import Request

    import server
    real = server._ws_pump_for_account  # _do_start_account_pump looks it up per start

    async def pump(account_id: str) -> bool:
        aid = str(account_id)
        if aid in _crash:
            _starts.setdefault(aid, []).append(time.time())
            return False
        return await real(account_id)   # True when it parked: the supervisor's backoff reads it

    server._ws_pump_for_account = pump

    async def set_crash(request: Request) -> dict:
        _loopback(request)
        body = await request.json()
        _crash.clear()
        _crash.update(str(a) for a in body.get("account_ids") or ())
        for aid in _crash:
            server._do_stop_account_pump(aid)
        return {"account_ids": sorted(_crash)}

    async def get_crash(request: Request) -> dict:
        _loopback(request)
        return {"account_ids": sorted(_crash), "starts": {a: list(v) for a, v in _starts.items()}}

    app.add_api_route("/__slop/pump-crash", set_crash, methods=["POST"])
    app.add_api_route("/__slop/pump-crash", get_crash, methods=["GET"])
