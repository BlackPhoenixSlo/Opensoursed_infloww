from __future__ import annotations

import json
import os
import time
from pathlib import Path

# module level: the route's annotation is a string here
from fastapi import Request


def _tmp() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", ""))


def _cfg() -> dict | None:
    f = _tmp() / "of-pm.json"
    return json.loads(f.read_text()) if f.is_file() else None


def read_sends(tmp: Path) -> list[dict]:
    f = tmp / "of-pm-sends.jsonl"
    if not f.is_file():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def _line(row: dict) -> None:
    fd = os.open(_tmp() / "of-pm-sends.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode())
    finally:
        os.close(fd)


def _feed_lists() -> int:
    import automation_relay as ar
    f = _tmp() / "of-rosters.json"
    if not f.is_file():
        return 0
    rows = [(str(aid), lst["name"], (int(m) for m in lst["members"]), int(lst["id"]))
            for aid, lists in json.loads(f.read_text()).items() for lst in lists]
    return len(ar.add_lists(rows))


def wire(app, loopback, relay) -> None:
    import automation_executor as ax

    real_send = relay._OfflineOF.send_message

    def send_message(self, chat_id, text, **kw) -> dict:
        msg = real_send(self, chat_id, text, **kw)
        cfg = _cfg()
        if cfg is None:
            return msg
        aid, fid = str(self.account_id), int(chat_id)
        _line({"account_id": aid, "fan_id": fid, "id": int(msg["id"]), "price": kw.get("price") or 0,
               "t": time.time()})
        hang = float(cfg["hang"].get(f"{aid}:{fid}", 0.0))
        if hang:
            time.sleep(hang)
        return msg

    relay._OfflineOF.send_message = send_message

    real_paced = ax.of_write_paced

    async def of_write_paced(account_id, fn, **kw):
        cfg = _cfg()
        if cfg is not None and "min_gap_s" not in kw:
            kw["min_gap_s"] = float(cfg["write_gap_s"])
        return await real_paced(account_id, fn, **kw)

    ax.of_write_paced = of_write_paced
    _feed_lists()

    async def rosters(request: Request) -> dict:
        loopback(request)
        return {"lists": _feed_lists()}

    app.add_api_route("/__slop/priority-mass/rosters", rosters, methods=["POST"])
