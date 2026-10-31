"""The app's own TypeScript, run in node (`app_ts.mjs`): a check that rests on client
logic (a pure module under `app/lib/`, `app/hooks/`) evaluates the app's real code on
what the relay answered, also in a `--no-ui` run, instead of a Python copy of its rules
that would stay green when the TypeScript is wrong.

`await run(ctx, script, payload)`: `script` is a node module exporting
`run(load, input)` (`load("/lib/x.ts")` is that app module, through vite's SSR loader:
the app's `@/` alias, TypeScript stripped); `payload` its JSON input; returns its JSON
output. The run's client fault (lib/faults.py `browser=`) rewrites the modules as they
load, as actors/ui.py does to the browser's JS: matches add to `ctx.browser_fault_hits`
and the modules hit to `ctx.app_ts_fault_files` (lib/cli.py holds both to the fault's
rules). Needs `node` and `app/node_modules` (vitest's vite). Each call starts a node
process (about 0.5 s); its vite cache goes to the run's temp dir.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = Path(__file__).with_name("app_ts.mjs")


async def run(ctx, script: Path, payload) -> dict:
    from slop.lib.faults import FAULTS
    f = FAULTS.get(getattr(ctx, "fault", None) or "")
    env = {"SLOP_TS_REWRITES": json.dumps([list(p) for p in (f.browser if f else ())])}
    proc = await asyncio.create_subprocess_exec(
        "node", str(BRIDGE), str(ROOT / "app"), str(script), str(ctx.stack.tmp / "app-ts-vite"),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env})
    out, err = await proc.communicate(json.dumps(payload).encode())
    if proc.returncode != 0:
        raise RuntimeError(f"app_ts {Path(script).name}: node exited {proc.returncode}: {err.decode()[-2000:]}")
    body = json.loads(out)
    hits = ctx.browser_fault_hits
    for rx, n in body["hits"].items():
        hits[rx] = hits.get(rx, 0) + n
    files = ctx.app_ts_fault_files
    for p, n in body["files"].items():
        files[p] = files.get(p, 0) + n
    return body["out"]
