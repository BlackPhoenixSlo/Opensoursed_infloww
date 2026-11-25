import os
import threading
import time
from pathlib import Path

FAKE_PATH = "/__slop/vault-pro/fake"
_lock = threading.Lock()
_hidden: list[dict] = []


def _on() -> bool:
    return (Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-vault-pro.json").is_file()


class OF:
    def hide_vault_media(self, media_ids) -> dict:
        if not _on():
            raise self._err
        with _lock:
            _hidden.append({"t": time.time(), "account": self.account_id, "media_ids": [int(m) for m in media_ids]})
        return {"success": True}


def wire(app, loopback, _relay) -> None:
    from fastapi import Request

    async def fake(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {"hidden": [dict(h) for h in _hidden]}

    app.add_api_route(FAKE_PATH, fake, methods=["GET"])
