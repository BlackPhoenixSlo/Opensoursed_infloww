"""Send once's part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its
`_wire`): OnlyFans' side of a 1:1 send that OF takes but the relay never hears back about.

Only when a scenario writes `$DEMO_SHOTS_TMP/of-send-once.json` ({"fans": {"<account>:<fan>":
"stall" | "hang" | "refuse_once"}, "stall_s": s, "hang_s": s}; read on every send, so a
scenario rewrites it between phases), `_OfflineOF.send_message` (POST
/api2/v2/chats/{fan}/messages, every flow's offline client inherits it)
answers per fan, the FIRST time OF sees that text (a resend of it answers as OF does):
  stall        OF takes the message, then the answer never comes: after `stall_s` (the client's
               30 s read timeout, compressed) the call raises curl_cffi's ReadTimeout, what
               OFClient raises then;
  hang         OF takes the message and the call blocks `hang_s` (the relay is killed meanwhile);
  refuse_once  the proxy refuses the CONNECT (curl_cffi ProxyError): OF never sees it.
Any other fan: answered as OF does. No file: unchanged. OnlyFans' record (every send while the
file exists) is `$DEMO_SHOTS_TMP/of-send-once.jsonl`, one line per step (`refused`, `accepted`
with OF's message id, `returned`), each one write(2) on an O_APPEND fd, so it outlives a
SIGKILLed relay. The raised errors' text starts SLOP_MARK (the scenario's EXPECTED_TRACEBACKS). Blocking sleeps, in the caller's worker thread
as the real curl. Fakes, declared: the latency and the compressed timeout are guesses.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

SLOP_MARK = "slop-send-once"
_lock = threading.Lock()   # the first-time check and its line, one at a time


def _tmp() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", ""))


def _cfg() -> dict | None:
    f = _tmp() / "of-send-once.json"
    return json.loads(f.read_text()) if f.is_file() else None


def read_journal(tmp: Path) -> list[dict]:
    """OnlyFans' record under `tmp` (the run's DEMO_SHOTS_TMP), one dict per line, in
    order; the scenario reads it too."""
    f = tmp / "of-send-once.jsonl"
    if not f.is_file():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def _line(row: dict) -> None:
    fd = os.open(_tmp() / "of-send-once.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps({**row, "t": time.time()}) + "\n").encode())
    finally:
        os.close(fd)


def wire(_app, _loopback, relay) -> None:
    from curl_cffi.requests import exceptions as curl

    real = relay._OfflineOF.send_message

    def send_message(self, chat_id, text, **kw) -> dict:
        cfg = _cfg()
        if cfg is None:
            return real(self, chat_id, text, **kw)
        how = cfg.get("fans", {}).get(f"{self.account_id}:{int(chat_id)}")
        key = {"account_id": str(self.account_id), "fan_id": int(chat_id), "text": text}
        with _lock:
            first = not any(r["text"] == text and r["op"] in ("accepted", "refused") for r in read_journal(_tmp()))
            if how == "refuse_once" and first:
                _line({"op": "refused", **key})
                raise curl.ProxyError(f"{SLOP_MARK}: CONNECT tunnel failed, response 403")
            msg = real(self, chat_id, text, **kw)   # OnlyFans has it from here on
            _line({"op": "accepted", "id": msg["id"], **key})
        if first and how == "stall":
            time.sleep(float(cfg.get("stall_s", 3.0)))
            raise curl.ReadTimeout(f"{SLOP_MARK}: Operation timed out after 30000 milliseconds")
        if first and how == "hang":
            time.sleep(float(cfg.get("hang_s", 300.0)))
        _line({"op": "returned", "id": msg["id"], **key})
        return msg

    relay._OfflineOF.send_message = send_message
