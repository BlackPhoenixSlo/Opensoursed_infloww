import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

OF_MASS_QUEUE_BASE = 8_800_000_000
_OF_LIST_BASE = 6_600_000
DEEPSEEK_LATENCY_S = 0.4
_of_lists: dict[str, list[dict]] = {}
_of_members: dict[int, set[int]] = {}
repeat_pages: set[int] = set()
_mass_lock = threading.Lock()
_fake_calls: Counter = Counter()
WALKER_MIXINS: list[type] = []
ANSWERS: list = []
_FOLLOWUP = "the follow-up drip (send_followup)"


def _mass_file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-mass.jsonl"


def _mass_append(row: dict) -> None:
    # one write on an O_APPEND fd: on disk even if the process is SIGKILLed next
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

    def me(self) -> dict:
        return {"id": int(self.account_id)}

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
        from types import SimpleNamespace
        import of_client
        r = SimpleNamespace(status_code=status, text=text)
        of_client._observe_consent(str(self.account_id), "POST",
                                   "https://onlyfans.com/api2/v2/messages/queue", wire, r)
        return r

    def subscribers(self, *, type="active", limit=10, offset=0, **_kw) -> dict:
        self._mass_cfg()
        return {"list": [], "hasMore": False}

    following = subscribers

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
    msgs = body.get("messages") or []
    user = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    system = next((m["content"] for m in msgs if m.get("role") == "system"), "")
    text = next((t for _p, fn in ANSWERS for t in [fn(system, user)] if t is not None), None)
    if text is None and "\nFollow-up step: " in user:
        _fake_calls["deepseek:followup"] += 1
        text = "hey you, what are you up to tonight? 😘"
    if text is None:
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
