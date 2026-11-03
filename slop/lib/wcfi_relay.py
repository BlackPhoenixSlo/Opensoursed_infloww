"""The welcome chatter's part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`). Its DeepSeek answer joins lib/automation_relay.py's ANSWERS at import
(`insert(0)`: relay.py imports every `*_relay.py` part, sorted, before any `wire`, so this part,
sorted after the others that register, is asked first). `automations.welcome_chatter_for_info` runs
as in production: W7 (`webhook_dispatch.on_inbound_message`) queues a fan-scoped job on
his DM and wakes the supervisor (a scenario's RELAY_ENV SLOP_SUPERVISOR=1).

Two fakes, declared, both at a wire boundary:
  DeepSeek  lib/automation_relay.py's loopback fake (`llm_providers.PROVIDERS["deepseek"]`
            re-pointed there) also answers a chat completion whose prompt carries
            PERSONA (seed/welcome_chatter.py writes it as the Creators' persona, so no
            other flow's prompt matches): the fact extract (system "You are a profile
            analyzer") gets `{}` (nothing new he said), the reply gets two lines with a
            tag unique to the call (`wcfi_reply_text`), after automation_relay.DEEPSEEK_LATENCY_S.
            A fan whose history carries ECHO_LINE (the scenario writes it as his opening
            line, for its seeded echo fans) gets the small-model echo instead: his last
            line verbatim, then the tagged question (`wcfi_echo_text`); the product must
            drop the parroting bubble and send the rest.
            Counted at GET /__slop/fake/calls as deepseek:wcfi_extract / deepseek:wcfi_reply
            (deepseek:wcfi_echo: the echo replies among them).
            Its ANSWERS purpose is None: the fake's 503 body names only the others.
  OF sends  `_OfflineOF.send_message` (every flow's offline client and automation_relay's walker,
            the lane's client here) keeps a journal of what OF received for the Creators
            whose persona is PERSONA only (read once per Creator from the relay's temp DB),
            so other flows' sends neither land in it nor grow it: GET
            /__slop/wcfi/of-sends answers [{account_id, fan_id, text, id, t}] (t: epoch s,
            when OF answered), what the no-double-send and e2e checks read.
No pacing bypass: typing holds are 0 under CHATTERLY_TEST_MODE; the account DM rate stays
real (the scenario raises it through the real Concurrency panel route).
"""

import itertools
import os
import sqlite3
import threading
import time

import automation_relay as _base

PERSONA = ("slop-wcfi persona: you are Mia, 24, a warm, flirty OnlyFans creator from Austin "
           "chatting with one of your fans.")
_EXTRACT_HEAD = "You are a profile analyzer"
# An echo fan's opening line (the scenario's seeded echo fans): his reply parrots his DM.
ECHO_LINE = "say it back to me so i know you actually read it"
_ids = itertools.count(1)
_lock = threading.Lock()
_of_sends: list[dict] = []
_wcfi_creator: dict[str, bool] = {}   # account_id -> persona is PERSONA (seeded before any DM)


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


def _tag(n: int) -> str:
    """n as letters (no digits: the off-platform guard reads digit runs as a phone number)."""
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
    """The echo reply: his line verbatim (the bubble the product drops), then a tagged question."""
    t = _tag(n)
    return f"{his_line}\nso what keeps you busy these days {t}?"


def _his_last_line(user: str) -> str:
    """His newest line in the reply prompt's transcript (`FAN: ...`, oldest to newest)."""
    return next((ln[5:] for ln in reversed(user.splitlines()) if ln.startswith("FAN: ")), "")


def _answer(system: str, user: str) -> str | None:
    """The fake DeepSeek's text for a PERSONA prompt (module docstring); None for any other."""
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
