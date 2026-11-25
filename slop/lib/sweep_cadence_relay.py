def wire(app, _loopback, _relay) -> None:
    from fastapi import Request

    async def sweep_cadence_tick(request: Request) -> dict:
        _loopback(request)
        import sweep_cadence
        return await sweep_cadence.tick()

    app.add_api_route("/__slop/sweep-cadence-tick", sweep_cadence_tick, methods=["POST"])
