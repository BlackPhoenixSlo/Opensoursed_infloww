"""The agency notification sweep's part of the slop relay (lib/relay.py loads it: `wire` runs at
the end of its `_wire`), for scenarios/2026-11-01-notifications-feed-volume.py.

No route reaches `notifications_api.tick` (missed clock-ins, retention prune): in production only
server.py's `_periodic` runs it, every TICK_S (5 min), and CHATTERLY_TEST_MODE skips that spawn.
So, harness side, never in service/:

  POST /__slop/notifications-tick {now?}  one `notifications_api.tick(now)` pass now (looked up at
       call time, so a fault's patch is what runs); `now` (naive UTC ISO-8601) stands in
       for the clock, so a prune can be held against seeded ages. Answers {filed, ms}.

Inert (404) unless the scenario wrote `$DEMO_SHOTS_TMP/notifications-tick.json` (`{}` is enough),
so no other scenario gets the hook. Bypass, declared: the 5-min cadence; the sweep is the product's.
"""

import os
import time
from datetime import datetime
from pathlib import Path


def _on() -> bool:
    return (Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "notifications-tick.json").is_file()


def wire(app, loopback, _relay) -> None:
    from fastapi import HTTPException, Request

    async def tick(request: Request) -> dict:
        loopback(request)
        if not _on():
            raise HTTPException(status_code=404, detail="Not Found")
        import notifications_api
        at = (await request.json()).get("now")
        now = datetime.fromisoformat(at) if at else None
        t0 = time.perf_counter()
        filed = await notifications_api.tick(now)
        return {"filed": filed, "ms": round((time.perf_counter() - t0) * 1000, 1)}

    app.add_api_route("/__slop/notifications-tick", tick, methods=["POST"])
