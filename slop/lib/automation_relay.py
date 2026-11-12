"""The automation lane's part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`, before any flow's part sorted after it; no `OF` class, so it adds no
method to `_OfflineOF`): the lane's offline OnlyFans client and a loopback DeepSeek fake.

Without `OF_API_ORIGIN` (no lib/of_wire.py OnlyFans), the lane's OF client
(`ax._make_client`, every flow's automations) is `_OfflineWalkerOF`: `me()` and
`send_message` (a priced one answers as OF's PPV and is kept per fan, `of_ppv` at
/__slop/fake/calls) answer as OF does, as do the methods below and other flows' mixins;
any other OF call raises `slop: OF is offline ...`. Another flow's part adds
methods to it with `WALKER_MIXINS.insert(0, cls)` at import: relay.py imports the parts in
sorted order, so the part sorted last comes first in the MRO, all before `_Walker`.

DeepSeek is faked at its HTTP boundary, keeping its latency and concurrency:
  POST <own loopback port>/chat/completions   the OpenAI-compatible wire `llm_client`
       posts to (`llm_providers.PROVIDERS["deepseek"]` re-pointed there; its own port, so
       it still answers while the relay drains after SIGTERM, a thread per call). Each
       (purpose, fn) in ANSWERS is asked in list order with the prompt's (system, user)
       turns; the first that returns text answers (fn counts its own label). Another
       flow's part adds one with `ANSWERS.insert(0, ...)` at import, so the part sorted
       last is asked first. Then send_followup's nudge (its user turn carries `Follow-up
       step:`): one fixed short line. Any other prompt is a 503 (`slop: prompt not faked`,
       naming the entries' purposes and the nudge; an entry whose purpose is None is faked
       but not named; other purposes stay unreachable). Each answer after DEEPSEEK_LATENCY_S.
Calls count by label at relay.py's GET /__slop/fake/calls. With SLOP_LIVE=1 the fake is
not installed: the run reaches the real API with the caller's test key through the
guard's allowlist (lib/stack.py).

OF's mass messages are faked on the lane's client too, only when a scenario writes
`$DEMO_SHOTS_TMP/of-mass.json` ({"send_s": s, "accept_at": 0..1, "cancel_s": s}):
`send_mass_message` (POST /api2/v2/messages/queue), `cancel_scheduled` (DELETE
/messages/queue/{id}) and `mass_message_history` (GET /users/me/stats/messages/group,
UTC dates, newest first). OnlyFans' side lives in `$DEMO_SHOTS_TMP/of-mass.jsonl`,
one line per step, written straight to the file so it outlives a SIGKILLed relay:
`send_begin`, `send_accepted` (OF has the mass: it gets its queue id and is in the
history from here on) after `accept_at` of `send_s`, `send_returned` (the relay has
OF's answer) at `send_s`; `cancel_begin` / `cancel_done` after `cancel_s`. A Creator in
`cancel_fail` ({account: "proxy" | "of"}, re-read every call) gets `cancel_refused`
instead and the cancel raises: "proxy" as curl_cffi's ProxyError after `proxy_s` (the
proxy's CONNECT 403 once OFClient._proxy_retry's ~6 s of retries ran out; OF never sees
it), "of" as OF's own error (OFAPIError, a 400) after `cancel_s`. A Creator in
`send_fail` ({account: "proxy" | "of"}, re-read every call) gets `send_refused` instead of
`send_begin` and the send raises: "proxy" the same ProxyError after `proxy_s` (OF never sees it),
"of" OF's own 400 after `accept_at` of `send_s` (AE 2026-11-07: `{"error":{"code":0,"message":
"Consent not accepted"}}`), as request_json raises it: OFAPIError with the response, here a
stand-in carrying only its `status_code` and `text` (declared). Every send first builds
the body the product's real `OFClient.send_mass_message` would POST (`_Walker._wire_body`,
transport captured; declared: `auto_tag=False`); `send_begin` carries its
`isConsentAccepted` (`consent`) and how many `mediaFiles` (`media`). A Creator in
`consent_required` ([account, ...]) whose body has media but no `isConsentAccepted: true`
gets `send_refused` (`why: "consent"`) and that same OF 400; for such a Creator each answer
(the 400, a sent one's 2xx) also goes to the product's consent observer as `_http_call`
hands it over (`_observed`: the consent_required notice flags, then clears). A kill
between `send_accepted` and `send_returned` is OF accepting a mass the relay never
heard back about. Blocking sleeps, in the caller's worker thread as the real curl.
With the same file: `subscribers` / `following` answer empty pages (a send's
a pre-send roster read), and OF's user lists (`get_lists`, `create_list`, `list_users_in`,
`add_user_to_list`, `remove_user_from_list`: buyer lists, a send's Auto_Exclude) live
in this relay process (`_of_lists` / `_of_members`, ids from _OF_LIST_BASE + 1 up),
`list_s` (0.3 s) a call; a restarted relay finds no list and makes them again. A list
in `repeat_pages` is OF ignoring the offset: `list_users_in` serves its page 1 on every
call (`hasMore` true while members remain past it), unpaced (armed without of-mass.json),
counted `of:repeat_list_page`. A
Creator in `lists_fail` ({account: n}) gets its first n `get_lists` refused (a
`lists_refused` line each, counted from the journal, then OF's 500 as OFAPIError).
"""

import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

OF_MASS_QUEUE_BASE = 8_800_000_000
_OF_LIST_BASE = 6_600_000
DEEPSEEK_LATENCY_S = 0.4
_of_lists: dict[str, list[dict]] = {}   # account -> OF's user lists (this process)
_of_members: dict[int, set[int]] = {}
repeat_pages: set[int] = set()   # list ids whose `list_users_in` ignores the offset (page 1 again)
_mass_lock = threading.Lock()  # queue ids: one accept at a time (the count of accepts so far, all processes)
_fake_calls: Counter = Counter()  # relay.py's, from wire() on (served at /__slop/fake/calls)
WALKER_MIXINS: list[type] = []   # other flows' methods on the lane's client, before _Walker's (insert(0))
ANSWERS: list = []   # (purpose | None, fn(system, user) -> text | None): other flows' DeepSeek prompts (insert(0))
_FOLLOWUP = "the follow-up drip (send_followup)"


def _mass_file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-mass.jsonl"


def _mass_append(row: dict) -> None:
    """One line, one write(2) on an O_APPEND fd: in the file the moment it returns,
    whatever happens to this process next."""
    fd = os.open(_mass_file(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode())
    finally:
        os.close(fd)


def _mass_rows() -> list[dict]:
    f = _mass_file()
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def add_lists(rows) -> list[dict]:
    """OF user lists into this process's `_of_lists` / `_of_members`, all rows under one
    `_mass_lock`; answers each row's list entry. A row is (account, name, members, lid):
    lid None mints the next id (`_OF_LIST_BASE` + every list so far + 1, as `create_list`),
    `name` may be a callable of that id; an explicit lid the account already has keeps its
    entry, members replaced."""
    out = []
    with _mass_lock:
        for aid, name, members, lid in rows:
            if lid is None:
                lid = _OF_LIST_BASE + sum(len(v) for v in _of_lists.values()) + 1
            mine = _of_lists.setdefault(aid, [])
            lst = next((x for x in mine if int(x["id"]) == lid), None)
            if lst is None:
                lst = {"id": lid, "name": name(lid) if callable(name) else name}
                mine.append(lst)
            _of_members[lid] = set(members)
            out.append(lst)
    return out


class _Walker:
    """The automation lane's client (`automation_executor._make_client`) in a slop
    run: never a real OFClient (its curl_cffi transport would pass the socket
    guard). `me()` answers the account, as OF does for a live session. Joins
    relay.py's `_OfflineOF` in `wire` (`_OfflineWalkerOF`)."""

    def me(self) -> dict:
        return {"id": int(self.account_id)}

    # OF's mass messages (module docstring), when a scenario wrote of-mass.json.
    def _mass_cfg(self) -> dict:
        f = Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-mass.json"
        if not f.is_file():
            raise self._err
        return json.loads(f.read_text())

    def _mass_line(self, op: str, **kw) -> dict:
        row = {"op": op, "account_id": self.account_id, "t": time.time(), **kw}
        _mass_append(row)
        return row

    def _wire_body(self, text, price, media_files, kw) -> dict:
        """The POST /messages/queue body the product's real `OFClient.send_mass_message`
        builds for this call (its transport stubbed: the body is captured, nothing is
        sent). Declared: `auto_tag=False`, the co-performer tag lookup is not run."""
        from of_client import OFClient
        c = OFClient.__new__(OFClient)
        c.account_id = self.account_id
        got: dict = {}
        c.post_json = lambda path, json_body=None: got.update(json_body or {}) or {}
        OFClient.send_mass_message(c, text, price=price, media_files=media_files,
                                   **{**kw, "auto_tag": False})
        return got

    def send_mass_message(self, text, *, price=0, media_files=None, **_kw) -> dict:
        from datetime import datetime, timezone
        cfg = self._mass_cfg()
        send_s, frac = float(cfg.get("send_s", 1.0)), float(cfg.get("accept_at", 0.5))
        token = f"{self.account_id}:{time.time_ns()}:{threading.get_ident()}"
        wire = self._wire_body(text, price, media_files, _kw)
        consent = wire.get("isConsentAccepted")
        law = str(self.account_id) in {str(a) for a in cfg.get("consent_required") or ()}
        if law and wire.get("mediaFiles") and consent is not True:
            from of_client import OFAPIError
            time.sleep(send_s * frac)
            self._mass_line("send_refused", token=token, text=text, by="of", why="consent",
                            consent=consent, media=len(wire["mediaFiles"]))
            body = '{"error":{"code":0,"message":"Consent not accepted"}}'
            r = self._observed(wire, 400, body)
            raise OFAPIError(f"400 for https://onlyfans.com/api2/v2/messages/queue\n{body}", response=r)
        if (cfg.get("send_fail") or {}).get(self.account_id) == "proxy":
            from curl_cffi.requests.exceptions import ProxyError
            time.sleep(float(cfg.get("proxy_s", 6.0)))
            self._mass_line("send_refused", token=token, text=text, by="proxy")
            raise ProxyError("Failed to perform, curl: (56) CONNECT tunnel failed, response 403")
        if (cfg.get("send_fail") or {}).get(self.account_id) == "of":
            from types import SimpleNamespace
            from of_client import OFAPIError
            time.sleep(send_s * frac)
            self._mass_line("send_refused", token=token, text=text, by="of")
            body = '{"error":{"code":0,"message":"Consent not accepted"}}'
            raise OFAPIError(f"400 for https://onlyfans.com/api2/v2/messages/queue\n{body}",
                             response=SimpleNamespace(status_code=400, text=body))
        self._mass_line("send_begin", token=token, text=text, consent=consent,
                        media=len(wire.get("mediaFiles") or []))
        time.sleep(send_s * frac)
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with _mass_lock:
            qid = OF_MASS_QUEUE_BASE + 1 + sum(1 for r in _mass_rows() if r["op"] == "send_accepted")
            self._mass_line("send_accepted", token=token, queue_id=qid, text=text, date=at,
                            price=price or 0, media=len(media_files or []))
        time.sleep(send_s * (1 - frac))
        self._mass_line("send_returned", token=token, queue_id=qid)
        out = {"id": qid, "createdAt": at, "text": text, "price": price or 0, "isFree": not price,
               "mediaCount": len(media_files or [])}
        if law:
            self._observed(wire, 200, json.dumps(out))
        return out

    def _observed(self, wire: dict, status: int, text: str):
        """OF's answer as `_Transport._http_call` hands it to the product's consent
        observer (of_client._observe_consent: the consent_required notice flags on
        the 400, clears on a 2xx media send); only for a `consent_required` Creator.
        Declared: the response is a stand-in carrying `status_code` and `text`."""
        from types import SimpleNamespace
        import of_client
        r = SimpleNamespace(status_code=status, text=text)
        of_client._observe_consent(str(self.account_id), "POST",
                                   "https://onlyfans.com/api2/v2/messages/queue", wire, r)
        return r

    def subscribers(self, *, type="active", limit=10, offset=0, **_kw) -> dict:
        """A roster read (audiences.roster_audience_blocking: thresholded / Priority sends):
        an empty page. Fake, declared: the scenario counts sends, not fans."""
        self._mass_cfg()
        return {"list": [], "hasMore": False}

    following = subscribers

    # OF's user lists (buyer lists, a send's Auto_Exclude), in this relay process
    # only: a restarted relay finds none and makes them again, as on a fresh
    # account. Each call takes `list_s` (a guess).
    def _list_op(self) -> None:
        time.sleep(float(self._mass_cfg().get("list_s", 0.3)))

    def get_lists(self, *, limit=20, offset=0, **_kw) -> dict:
        self._list_op()
        n = int((self._mass_cfg().get("lists_fail") or {}).get(str(self.account_id), 0))
        with _mass_lock:
            refuse = n and sum(1 for r in _mass_rows() if r["op"] == "lists_refused"
                               and r["account_id"] == self.account_id) < n
            if refuse:
                self._mass_line("lists_refused")
        if refuse:
            from of_client import OFAPIError
            raise OFAPIError("500 for https://onlyfans.com/api2/v2/lists\nInternal Server Error")
        mine = _of_lists.setdefault(self.account_id, [])
        return {"list": mine[offset:offset + limit], "hasMore": offset + limit < len(mine)}

    def create_list(self, name) -> dict:
        self._list_op()
        return add_lists([(self.account_id, name, (), None)])[0]

    def list_users_in(self, list_id, *, limit=20, offset=0, **_kw) -> dict:
        if int(list_id) in repeat_pages:
            _fake_calls["of:repeat_list_page"] += 1
            offset = 0
        else:
            self._list_op()
        ids = sorted(_of_members.get(int(list_id), set()))
        return {"list": [{"id": i} for i in ids[offset:offset + limit]], "hasMore": offset + limit < len(ids)}

    def add_user_to_list(self, list_id, user_id) -> dict:
        self._list_op()
        _of_members.setdefault(int(list_id), set()).add(int(user_id))
        return {"success": True}

    def remove_user_from_list(self, list_id, user_id) -> dict:
        self._list_op()
        _of_members.get(int(list_id), set()).discard(int(user_id))
        return {"success": True}

    def cancel_scheduled(self, queue_id) -> dict:
        cfg = self._mass_cfg()
        token = f"{self.account_id}:{time.time_ns()}:{threading.get_ident()}"
        fail = (cfg.get("cancel_fail") or {}).get(self.account_id)
        if fail == "proxy":
            from curl_cffi.requests.exceptions import ProxyError
            time.sleep(float(cfg.get("proxy_s", 6.0)))
            self._mass_line("cancel_refused", token=token, queue_id=int(queue_id), by=fail)
            raise ProxyError("Failed to perform, curl: (56) CONNECT tunnel failed, response 403")
        if fail == "of":
            from of_client import OFAPIError
            time.sleep(float(cfg.get("cancel_s", 0.5)))
            self._mass_line("cancel_refused", token=token, queue_id=int(queue_id), by=fail)
            raise OFAPIError(f"400 for https://onlyfans.com/api2/v2/messages/queue/{int(queue_id)}\n"
                             '{"error":{"code":0,"message":"Something went wrong"}}')
        self._mass_line("cancel_begin", token=token, queue_id=int(queue_id))
        time.sleep(float(cfg.get("cancel_s", 0.5)))
        self._mass_line("cancel_done", token=token, queue_id=int(queue_id))
        return {"success": True}

    def mass_message_history(self, *, start_date, end_date, limit=50, offset=0, **_kw) -> dict:
        from datetime import datetime
        self._mass_cfg()
        fmt = "%Y-%m-%d %H:%M:%S"
        lo, hi = datetime.strptime(start_date, fmt), datetime.strptime(end_date, fmt)
        rows = _mass_rows()
        canceled = {r["queue_id"] for r in rows if r["op"] == "cancel_done"}
        items = [r for r in rows if r["op"] == "send_accepted" and r["account_id"] == self.account_id
                 and lo <= datetime.fromisoformat(r["date"]).replace(tzinfo=None) <= hi]
        items.sort(key=lambda r: (r["date"], r["queue_id"]), reverse=True)
        page = items[offset:offset + limit]
        _fake_calls["of:mass_message_history"] += 1
        return {"hasMore": len(items) > offset + limit, "items": [
            {"id": r["queue_id"], "date": r["date"], "text": r["text"], "rawText": r["text"],
             "giphyId": None, "mediaCount": r.get("media", 0), "media": [], "price": r.get("price", 0),
             "sentCount": 0, "viewedCount": 0, "isCanceled": r["queue_id"] in canceled,
             "canUnsend": True, "unsendSeconds": 1000000, "template": "group"} for r in page]}


def _deepseek_answer(body: dict) -> tuple[int, dict]:
    """The fake DeepSeek's answer to one chat completion (module docstring)."""
    msgs = body.get("messages") or []
    user = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    system = next((m["content"] for m in msgs if m.get("role") == "system"), "")
    text = next((t for _p, fn in ANSWERS for t in [fn(system, user)] if t is not None), None)
    if text is None and "\nFollow-up step: " in user:
        # send_followup's nudge (its user turn names the step, `_compose_user`):
        # one short line, as the real model writes it.
        _fake_calls["deepseek:followup"] += 1
        text = "hey you, what are you up to tonight? 😘"
    if text is None:
        # Only the prompts named above are faked; any other purpose stays as
        # unreachable as it was before this fake existed.
        _fake_calls["deepseek:other"] += 1
        names = [p for p, _fn in ANSWERS if p is not None] + [_FOLLOWUP]
        return 503, {"error": {"message": f"slop: prompt not faked (named fakes: {', '.join(names)})"}}
    time.sleep(DEEPSEEK_LATENCY_S)
    return 200, {"id": f"slop-{sum(_fake_calls.values())}", "object": "chat.completion",
                 "model": body.get("model"), "created": int(time.time()),
                 "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": text}}],
                 "usage": {"prompt_tokens": 900, "completion_tokens": 20, "total_tokens": 920}}


def _serve_deepseek() -> int:
    """The fake DeepSeek on its own loopback port, a thread per call: it keeps
    answering while the relay drains after SIGTERM (uvicorn has closed the
    relay's own socket by then; the real DeepSeek is still there)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/chat/completions":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            status, out = _deepseek_answer(body)
            raw = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="slop-fake-deepseek", daemon=True).start()
    return srv.server_address[1]


def _install_fakes() -> None:
    """Point DeepSeek at the loopback fake."""
    import dataclasses

    import llm_providers
    p = llm_providers.PROVIDERS["deepseek"]
    llm_providers.PROVIDERS["deepseek"] = dataclasses.replace(
        p, base_url=f"http://127.0.0.1:{_serve_deepseek()}")


def wire(app, _loopback, relay) -> None:
    import automation_executor as ax

    global _fake_calls
    _fake_calls = relay._fake_calls
    if not os.environ.get("OF_API_ORIGIN"):
        walker = type("_OfflineWalkerOF", (*WALKER_MIXINS, _Walker, relay._OfflineOF), {})
        ax._make_client = lambda account_id: walker(  # type: ignore[assignment]
            str(account_id), RuntimeError("slop: OF is offline (this OF call is not faked on the lane's client)"))
    if os.environ.get("SLOP_LIVE") != "1":
        _install_fakes()
