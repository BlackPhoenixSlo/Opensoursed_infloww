from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

SLOP_MARK = "slop-send-once"
_lock = threading.Lock()


def _tmp() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", ""))


def _cfg() -> dict | None:
    f = _tmp() / "of-send-once.json"
    return json.loads(f.read_text()) if f.is_file() else None


def read_journal(tmp: Path) -> list[dict]:
    f = tmp / "of-send-once.jsonl"
    if not f.is_file():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def _fan_first(key: dict) -> tuple[bool, bool]:
    mine = [r for r in read_journal(_tmp())
            if r["account_id"] == key["account_id"] and r["fan_id"] == key["fan_id"]]
    first = not any(r["text"] == key["text"] and r["op"] in ("accepted", "refused", "rejected") for r in mine)
    return first, any(r["op"] == "accepted" for r in mine)


class _Refused400:
    status_code = 400
    reason = "Bad Request"
    text = json.dumps({"error": {"code": 0, "message": f"{SLOP_MARK}: OF refused the message"}})

    def json(self) -> dict:
        return json.loads(self.text)


class _Echo502:
    status_code = 502
    reason = "Bad Gateway"
    text = json.dumps({"error": {"code": 0, "message": "Please allow 10 seconds"}})


def _line(row: dict) -> None:
    fd = os.open(_tmp() / "of-send-once.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps({**row, "t": time.time()}) + "\n").encode())
    finally:
        os.close(fd)


def _reject_400(key: dict, after_first: bool) -> None:
    from curl_cffi.requests import exceptions as curl
    if after_first:
        _line({"op": "rejected", **key})
        raise curl.HTTPError(f"{SLOP_MARK}: HTTP Error 400: Bad Request", 0, _Refused400())


def _drop_id(key: dict, after_first: bool, cfg: dict, msg: dict) -> dict | None:
    if after_first:
        return None
    _line({"op": "returned", "id": None, **key})
    return {k: v for k, v in msg.items() if k != "id"}


def _hang_later(key: dict, after_first: bool, cfg: dict, msg: dict) -> None:
    if after_first:
        time.sleep(float(cfg.get("hang_s", 300.0)))


_FAN_MODES = {
    "4xx_after_first": (_reject_400, None),
    "noid_4xx_after_first": (_reject_400, _drop_id),
    "hang_after_first": (None, _hang_later),
}


def wire(_app, _loopback, relay) -> None:
    from curl_cffi.requests import exceptions as curl

    real = relay._OfflineOF.send_message

    def send_message(self, chat_id, text, **kw) -> dict:
        cfg = _cfg()
        if cfg is None:
            return real(self, chat_id, text, **kw)
        how = cfg.get("fans", {}).get(f"{self.account_id}:{int(chat_id)}")
        key = {"account_id": str(self.account_id), "fan_id": int(chat_id), "text": text}
        per_fan = cfg.get("first_key") == "fan_text"
        before, after = _FAN_MODES.get(how, (None, None)) if per_fan else (None, None)
        with _lock:
            if per_fan:
                first, after_first = _fan_first(key)
            else:
                first = not any(r["text"] == text and r["op"] in ("accepted", "refused") for r in read_journal(_tmp()))
            if how == "refuse_once" and first:
                _line({"op": "refused", **key})
                raise curl.ProxyError(f"{SLOP_MARK}: CONNECT tunnel failed, response 403")
            if before and first:
                before(key, after_first)
            msg = real(self, chat_id, text, **kw)
            _line({"op": "accepted", "id": msg["id"], **key})
        if first and how == "stall":
            time.sleep(float(cfg.get("stall_s", 3.0)))
            raise curl.ReadTimeout(f"{SLOP_MARK}: Operation timed out after 30000 milliseconds")
        if first and how == "hang":
            time.sleep(float(cfg.get("hang_s", 300.0)))
        if first and how == "echo_5xx":
            from of_client import OFAPIError
            raise OFAPIError(f"{SLOP_MARK}: 502 for /api2/v2/chats/{int(chat_id)}/messages\n{_Echo502.text}",
                             response=_Echo502())
        if after and first and (answer := after(key, after_first, cfg, msg)) is not None:
            return answer
        _line({"op": "returned", "id": msg["id"], **key})
        return msg

    relay._OfflineOF.send_message = send_message
