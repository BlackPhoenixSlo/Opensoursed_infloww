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
