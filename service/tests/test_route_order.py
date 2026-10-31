#!/usr/bin/env python3
"""Route-order golden: moving handlers between modules must not reorder routes.

Starlette matches the first route in `server.app.routes` order, so e.g.
`/posts/chart` must stay before `/posts/{post_id}` and
`/users/me/stats/top/post` before `/users/me/stats/top/{kind}`. A router split
(`app.include_router(x.router)`) placed at the wrong spot silently shadows one.

Pins: the ordered (methods, path, endpoint __name__) list over
`server.app.routes`, plus sha1 of `app.openapi()`, equal the committed
test_route_order.golden.json. Regenerate ONLY for a deliberate route change
and say so in the PR:  ./venv/bin/python service/tests/test_route_order.py --write-golden

Run: ./venv/bin/python service/tests/test_route_order.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

# The golden is the harness-env route set. FLEET_SECRET (>=32 chars) mounts
# /auth/fleet/whois (server.py `if fleet_api.enabled()`); the only env-gated
# route registration. Set empty (not popped) before `import server`: db/engine's
# load_dotenv(override=False) would refill a popped key from service/.env.
os.environ["FLEET_SECRET"] = ""

import server  # noqa: E402 — registers routers + middleware

GOLDEN = Path(__file__).with_name("test_route_order.golden.json")
WANT = None if "--write-golden" in sys.argv else json.loads(GOLDEN.read_text())


def _routes() -> list:
    routes = []
    for r in server.app.routes:
        methods = sorted(getattr(r, "methods", None) or [])
        endpoint = getattr(r, "endpoint", None)
        name = getattr(endpoint, "__name__", None) or type(r).__name__
        routes.append([",".join(methods), r.path, name])
    return routes


def _openapi_sha1() -> str:
    spec = json.dumps(server.app.openapi(), sort_keys=True).encode()
    return hashlib.sha1(spec).hexdigest()


def case_route_order_matches_golden():
    got = [json.dumps(r) for r in _routes()]
    want = [json.dumps(r) for r in WANT["routes"]]
    if got != want:
        diff = "\n".join(difflib.unified_diff(
            want, got, "golden", "server.app.routes", lineterm=""))
        raise AssertionError(f"route order changed:\n{diff}")


def case_openapi_sha1_matches_golden():
    got, want = _openapi_sha1(), WANT["openapi_sha1"]
    assert got == want, f"app.openapi() changed: sha1 {got} != golden {want}"


if __name__ == "__main__" and "--write-golden" in sys.argv:
    rows = ",\n  ".join(json.dumps(r) for r in _routes())
    GOLDEN.write_text(f'{{"openapi_sha1": "{_openapi_sha1()}",\n "routes": [\n  {rows}\n]}}\n')
    print(f"wrote {GOLDEN}")
    sys.exit(0)

_harness.run()
