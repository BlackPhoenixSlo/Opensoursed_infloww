import itertools
import os
import sqlite3
import threading
import time

import automation_relay as _base

PERSONA = ("slop-wcfi persona: you are Mia, 24, a warm, flirty OnlyFans creator from Austin "
           "chatting with one of your fans.")
_EXTRACT_HEAD = "You are a profile analyzer"
ECHO_LINE = "say it back to me so i know you actually read it"
_ids = itertools.count(1)
_lock = threading.Lock()
_of_sends: list[dict] = []
_wcfi_creator: dict[str, bool] = {}


def _is_wcfi(account_id: str) -> bool:
    hit = _wcfi_creator.get(account_id)
    if hit is None:
        db = os.environ["CHATTERLY_DB_URL"].removeprefix("sqlite:///")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
        try:
            row = con.execute("SELECT persona FROM account_ai_config WHERE account_id=?",
                              (account_id,)).fetchone()
        finally:
            con.close()
        hit = _wcfi_creator[account_id] = bool(row and row[0] == PERSONA)
    return hit


# letters only: the off-platform guard reads digit runs as a phone number
def _tag(n: int) -> str:
    s = ""
    while True:
        n, r = divmod(n, 26)
        s = "abcdefghijklmnopqrstuvwxyz"[r] + s
        if n == 0:
            return "zq" + s


def wcfi_reply_text(n: int) -> str:
    t = _tag(n)
    return f"haha you are trouble {t}\nso what keeps you busy these days {t}?"


def wcfi_echo_text(his_line: str, n: int) -> str:
    t = _tag(n)
    return f"{his_line}\nso what keeps you busy these days {t}?"


def _his_last_line(user: str) -> str:
    return next((ln[5:] for ln in reversed(user.splitlines()) if ln.startswith("FAN: ")), "")


def _answer(system: str, user: str) -> str | None:
    if PERSONA not in system and PERSONA not in user:
        return None
    if system.startswith(_EXTRACT_HEAD):
        _base._fake_calls["deepseek:wcfi_extract"] += 1
        return "{}"
    _base._fake_calls["deepseek:wcfi_reply"] += 1
    if f"FAN: {ECHO_LINE}" in user:
        _base._fake_calls["deepseek:wcfi_echo"] += 1
        return wcfi_echo_text(_his_last_line(user), next(_ids))
    return wcfi_reply_text(next(_ids))


_base.ANSWERS.insert(0, (None, _answer))


def wire(app, _loopback, relay) -> None:
    from fastapi import Request

    real_send = relay._OfflineOF.send_message

    def send_message(self, chat_id, text, *a, **kw):
        out = real_send(self, chat_id, text, *a, **kw)
        if not _is_wcfi(str(self.account_id)):
            return out
        with _lock:
            _of_sends.append({"account_id": str(self.account_id), "fan_id": int(chat_id), "text": text,
                              "id": int(out["id"]), "t": time.time()})
        return out

    relay._OfflineOF.send_message = send_message

    async def of_sends(request: Request) -> list:
        _loopback(request)
        with _lock:
            return list(_of_sends)

    app.add_api_route("/__slop/wcfi/of-sends", of_sends, methods=["GET"])
