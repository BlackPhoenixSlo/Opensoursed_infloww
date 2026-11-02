"""Vault Pro's part of the slop relay (lib/relay.py loads it: `OF` joins `_OfflineOF`'s bases, `wire` runs at
the end of its `_wire`).

OnlyFans' side of the duplicates hide (`POST /admin/vault-ai/duplicates/hide` -> `OFClient.hide_vault_media`,
OF's `PUT /api2/v2/vault/media/hidden {"mediaIds": [...]}`) is faked only when a scenario writes
`$DEMO_SHOTS_TMP/of-vault-pro.json` (`{}` is enough); without it the call re-raises the client build's error
as before.

  hide_vault_media(media_ids)   recorded per call (t, Creator, ids in order), answered {"success": true}
                                (OF's answer body is a guess; the route reads none of it).

  GET FAKE_PATH (/__slop/vault-pro/fake)  {hidden: [{t, account, media_ids}]}: what OnlyFans received, in order.
"""

import os
import threading
import time
from pathlib import Path

FAKE_PATH = "/__slop/vault-pro/fake"   # the scenario reads what OnlyFans received here
_lock = threading.Lock()   # the route calls OF on a worker thread
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
