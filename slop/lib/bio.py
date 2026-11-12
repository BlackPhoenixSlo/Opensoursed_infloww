"""Standalone bio process using the slop stack's existing loopback and temp-data guards."""
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    os.environ["DEMO_SHOTS_PROCESS"] = "bio"
    runpy.run_path(str(root / "scripts/demo-shots/net_guard.py"))
    os.environ["BIO_FILES_DIR"] = str(Path(os.environ["DEMO_SHOTS_TMP"]) / "bio_files")
    sys.path.insert(0, str(root / "service"))
    sys.path.insert(0, str(root / "slop/lib"))
    sys.path.append(str(root))  # *_faults.py import `slop.lib.*`

    if os.environ.get("SLOP_FAULT"):
        import faults
        faults.apply(os.environ["SLOP_FAULT"])

    import uvicorn
    from bio_pages.app import app

    async def covered_app(scope, receive, send):
        if scope["type"] != "lifespan" or not os.environ.get("SLOP_COVERAGE"):
            await app(scope, receive, send)
            return

        async def saved_send(message):
            if message["type"] == "lifespan.shutdown.complete":
                import coverage
                current = coverage.Coverage.current()
                if current is not None:
                    current.save()
            await send(message)

        await app(scope, receive, saved_send)

    uvicorn.run(covered_app, host="127.0.0.1", port=int(os.environ["BIO_PORT"]), loop="asyncio", log_level="warning",
                proxy_headers=False, server_header=False, access_log=False,
                timeout_graceful_shutdown=int(os.environ.get("UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN", "5")))


if __name__ == "__main__":
    main()
