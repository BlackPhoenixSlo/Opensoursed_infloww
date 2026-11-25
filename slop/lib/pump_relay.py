import time

_crash: set[str] = set()
_starts: dict[str, list[float]] = {}


def wire(app, _loopback, _relay) -> None:
    from fastapi import Request

    import server
    real = server._ws_pump_for_account

    async def pump(account_id: str) -> bool:
        aid = str(account_id)
        if aid in _crash:
            _starts.setdefault(aid, []).append(time.time())
            return False
        return await real(account_id)

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
