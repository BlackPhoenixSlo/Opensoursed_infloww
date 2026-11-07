"""The full chat sweep cadence's part of the slop relay (lib/relay.py loads it: `wire` runs at
the end of its `_wire`), for scenarios/2026-11-07-chat-sweep-cadence.py.

  POST /__slop/sweep-cadence-tick  one `sweep_cadence.tick()` pass now; answers its counts
       ({live, enqueued, cancelled}). Bypass, declared: it stands in for the periodic
       task's timer (server._start_event_pumps: first pass FIRST_AFTER_S after boot, then
       every TICK_S), which CHATTERLY_TEST_MODE never starts; the pass is the product's.
"""


def wire(app, _loopback, _relay) -> None:
    from fastapi import Request

    async def sweep_cadence_tick(request: Request) -> dict:
        _loopback(request)
        import sweep_cadence
        return await sweep_cadence.tick()

    app.add_api_route("/__slop/sweep-cadence-tick", sweep_cadence_tick, methods=["POST"])
