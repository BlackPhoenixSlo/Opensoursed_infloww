"""Send once's part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its
`_wire`): OnlyFans' side of a 1:1 send that OF takes but the relay never hears back about.

Only when a scenario writes `$DEMO_SHOTS_TMP/of-send-once.json` ({"fans": {"<account>:<fan>":
"stall" | "hang" | "refuse_once" | "echo_5xx"}, "stall_s": s, "hang_s": s}; read on every send, so a
scenario rewrites it between phases), `_OfflineOF.send_message` (POST
/api2/v2/chats/{fan}/messages, every flow's offline client and automation_relay's walker inherit it)
answers per fan, the FIRST time OF sees that text (a resend of it answers as OF does):
  stall        OF takes the message, then the answer never comes: after `stall_s` (the client's
               30 s read timeout, compressed) the call raises curl_cffi's ReadTimeout, what
               OFClient raises then;
  hang         OF takes the message and the call blocks `hang_s` (the relay is killed meanwhile);
  refuse_once  the proxy refuses the CONNECT (curl_cffi ProxyError): OF never sees it;
  echo_5xx     OF takes the message, then the answer is a 502 whose text echoes OF's rate-limit
               refusal ("Please allow 10 seconds"): of_client.OFAPIError, `response.status_code`
               502, so only a text sniff calls it a refusal.
Opt-in `"first_key": "fan_text"` (lines repeat across fans: a funnel's step, the drip's one
nudge line): "the first time" is per (account, fan, text) instead, OF refusing a bubble with a
400 counts as seen too, and three more fan behaviours answer (none without the opt-in):
  4xx_after_first       the fan's first send OF takes and answers; a later first-time text
                        OF refuses with a 400 (curl_cffi HTTPError, `response.status_code`
                        400, OF created nothing: a `rejected` line);
  noid_4xx_after_first  the same, but OF answers that first send without its `id` (OF has it:
                        `accepted`, then `returned` with id null);
  hang_after_first      the fan's first send answered; a later first-time text OF takes and
                        the call blocks `hang_s` (a step killed after its bubble 0 landed).
Any other fan: answered as OF does. No file: unchanged. OnlyFans' record (every send while the
file exists) is `$DEMO_SHOTS_TMP/of-send-once.jsonl`, one line per step (`refused`, `rejected`, `accepted`
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


def _fan_first(key: dict) -> tuple[bool, bool]:
    """The opt-in `fan_text` key: (OF never saw this (account, fan, text), OF already took
    one of this fan's sends) over the journal."""
    mine = [r for r in read_journal(_tmp())
            if r["account_id"] == key["account_id"] and r["fan_id"] == key["fan_id"]]
    first = not any(r["text"] == key["text"] and r["op"] in ("accepted", "refused", "rejected") for r in mine)
    return first, any(r["op"] == "accepted" for r in mine)


class _Refused400:
    """The response curl_cffi's raise_for_status hands HTTPError on OF's 400."""
    status_code = 400
    reason = "Bad Request"
    text = json.dumps({"error": {"code": 0, "message": f"{SLOP_MARK}: OF refused the message"}})

    def json(self) -> dict:
        return json.loads(self.text)


class _Echo502:
    """The response OFAPIError carries on a 5xx whose body echoes OF's rate-limit text."""
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
    """Before the call: a later first-time text, OF refuses it (created nothing)."""
    from curl_cffi.requests import exceptions as curl
    if after_first:
        _line({"op": "rejected", **key})
        raise curl.HTTPError(f"{SLOP_MARK}: HTTP Error 400: Bad Request", 0, _Refused400())


def _drop_id(key: dict, after_first: bool, cfg: dict, msg: dict) -> dict | None:
    """After the call: the fan's first send answered without its `id` (OF has it)."""
    if after_first:
        return None
    _line({"op": "returned", "id": None, **key})
    return {k: v for k, v in msg.items() if k != "id"}


def _hang_later(key: dict, after_first: bool, cfg: dict, msg: dict) -> None:
    """After the call: a later first-time text, OF took it and the answer hangs."""
    if after_first:
        time.sleep(float(cfg.get("hang_s", 300.0)))


# The opt-in modes, on a first-time text: (before the call, after it); an `after` that
# returns a dict answers with it instead.
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
        per_fan = cfg.get("first_key") == "fan_text"   # opt-in (module docstring)
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
            msg = real(self, chat_id, text, **kw)   # OnlyFans has it from here on
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
