import ast
from pathlib import Path

_TASK: dict = {}


def _real_fast_poll():
    import purchase_poll as pp
    tree = ast.parse(Path(pp.__file__).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "start_fast_poll")
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), pp.__file__, "exec"), pp.__dict__, ns)
    return ns["start_fast_poll"]


def wire(app, _loopback, _relay) -> None:
    import asyncio

    from fastapi import Request

    async def fast_poll(request: Request) -> dict:
        _loopback(request)
        if "task" not in _TASK:
            import of_call_counter
            with of_call_counter.caller("loop:tx-ingest-fast-poll"):
                _TASK["task"] = asyncio.create_task(_real_fast_poll()(), name="tx-ingest-fast-poll")
        return {"started": True}

    async def leased(request: Request) -> dict:
        _loopback(request)
        import view_lease
        return {"leased": sorted(view_lease.leased_ids())}

    app.add_api_route("/__slop/fast-poll", fast_poll, methods=["POST"])
    app.add_api_route("/__slop/view-lease", leased, methods=["GET"])
