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

Golden refresh (2026-11-09): inspected ce072f9ce -> 40cd38d1e OpenAPI diff:
- GET /admin/stats/per-employee adds optional include_series: bool = false
  (9d5c8d811, dashboard daily employee sales).
Routes/order and all other schema fields are unchanged; Phase 2's schema is
identical to 40cd38d1e. Keep these intentional base changes in the golden.
Phase 3 integration also retains its vault lists/media revalidate query params
and pins/head-read handler descriptions. The combined schema has its own hash;
route order stays unchanged.

Golden refresh (2026-11-10): main 8ab4d6fb4 intentionally adds POST
/admin/agency-notifications/dismiss-all and /{notification_id}/dismiss.
Removing exactly those paths reproduces the prior OpenAPI hash; remaining
routes retain their order. Refresh after integrating main into Phase 2.
Phase 3's hash = that schema plus Phase 3's four GET param/description edits
(measured: OpenAPI diff vs 40cd38d1e is exactly main's two paths + those four).

Golden refresh (2026-11-11): inspected ac38007b9 -> rwl W28-shell-notif OpenAPI diff:
- POST /admin/agency-notifications/dismiss-all takes an optional JSON body
  {up_to_id} (+ its 422); a missing body keeps the old behaviour.
- nudge preview (#416) adds optional `weekday` query + doc wording.
After rebase on main a9ae82cc8: main's own drift since its 094966d87 golden =
help bot routes POST /admin/assistant/draft + GET /admin/assistant/do-caps; inspected, intentional.
Golden refresh (2026-11-11): rwl W28-relay-infra on main 6c68e13ed: only the tracking-link
verify doc adds "429 + Retry-After" (verify throttle); inspected, intentional.
Golden refresh (2026-11-12): merge main 6083d918e into feat/redirect-links-stats: OpenAPI diff
merged-vs-main == base-vs-branch exactly (tracking-links /summary + /{id}/analytics?days, verify body ref);
inspected, intentional.
Golden refresh (2026-11-12): merge main 78eaf88bc into feat/redirect-links-stats: same check, OpenAPI diff
merged-vs-main == base-vs-branch exactly; inspected, intentional.
Golden refresh (2026-11-11, bio admin API): adds the 15 /admin/bio-pages* rows right after the
link-share rows (bio_pages/admin.py); no existing row moves. The base's OpenAPI sha already
mismatched the golden before this change (88bfcd7a… vs 8b932eca…); the new sha includes both.
Golden refresh (2026-11-12): merge feat/bio-pages-port (main 6083d918e + redirect-link stats) into
feat/bio-admin-api: OpenAPI diff merged-vs-bio-pages-port == base-vs-bio-admin-api exactly; inspected.
Golden refresh (2026-11-12): merge feat/bio-pages-port (main 78eaf88bc) into feat/bio-admin-api: same check;
inspected.
Golden refresh (2026-11-12): do-mode mass_edit (spec D11) adds POST /admin/assistant/edit/apply
(assistant_draft.edit_apply); inspected, intentional.
Golden refresh (2026-11-12): merge main 130d15eb4 into ship/fetch-diet-p3 (4421feb87): routes == main's golden
(main adds bio-pages/tracking-stats rows); OpenAPI diff merged-vs-main == base(6d6f8a61d)-vs-P3 exactly
(measured, 18 leaves): P3's four GET edits (vault/lists + vault/media revalidate params, pinned + wall-media
descriptions); inspected, intentional.
Golden refresh (2026-11-12): merge main 46223e71c into p3-final (f5e594c3d): routes == main's golden (611);
OpenAPI diff merged-vs-main == base(6d6f8a61d)-vs-P3(4421feb87) exactly (measured, 18 leaves); inspected.

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
