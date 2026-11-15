"""The View lease / purchases poll tiers' part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`), for scenarios/2026-11-09-view-lease-purchases-tiers.py.

  POST /__slop/fast-poll   starts the product's 30 s purchases loop (`purchase_poll.start_fast_poll`,
       compiled again from its own source: `_run_ui_safe` no-ops the module attribute) once, as server.py's
       `_spawn_bg(..., "tx-ingest-fast-poll")` does (Caller kind `loop:tx-ingest-fast-poll`); a second call
       is a no-op. Answers {started}. Bypass, declared: CHATTERLY_TEST_MODE never runs the startup spawn
       block, so the scenario starts the loop once its world is seeded instead of at boot (+ boot grace).
  GET  /__slop/view-lease  the Relay's lease registry now: {leased: [Creator ids]} (`view_lease.leased_ids`),
       read-only.
"""
import ast
from pathlib import Path

_TASK: dict = {}


def _real_fast_poll():
    """`purchase_poll.start_fast_poll` as written, in the module's namespace (faults patch its globals)."""
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
