import contextlib
import contextvars
import os
import re
import runpy
import sys
import threading
import time
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from proof_core import (READ_ID_KINDS, READS, Request, Run, add_read_id, decide, log_body, pace_wait,  # noqa: E402
                        read_id_query, redact_query)
from undo_log import append_jsonl, read_undo_log  # noqa: E402
from proofs import ALL  # noqa: E402

DEMO = HERE.parent / "demo-shots"
EVIDENCE = Path(os.environ["OFM_PROOF_EVIDENCE"])
WIRE = EVIDENCE / "wire.jsonl"
UNDO = EVIDENCE / "undo-log.jsonl"
_FAKE = urlsplit(os.environ.get("OF_API_ORIGIN", "")).netloc
_OF_HOST = "onlyfans.com"
POSTS_PATH = "/api2/v2/posts"
READ_BACK = {
    ("POST", POSTS_PATH): (POSTS_PATH + "/{id}", {}, "text", ("rawText", "text")),
    ("POST", "/api2/v2/messages/queue"): ("/api2/v2/messages/queue/{id}", {"format": "scheduled"}, "text",
                                          ("rawText", "text")),
    ("POST", "/api2/v2/lists"): ("/api2/v2/lists/{id}", {}, "name", ("name",)),
    ("POST", "/api2/v2/vault/lists"): ("/api2/v2/vault/lists/{id}", {}, "name", ("name",)),
    ("POST", "/api2/v2/trials"): ("/api2/v2/trials", {"offset": 0, "limit": 100}, "trialLinkName", ("trialLinkName",)),
    ("PUT", "/api2/v2/users/social/buttons"): ("/api2/v2/users/social/buttons", {}, "label", ("label",)),
    ("PUT", "/api2/v2/users/links"): ("/api2/v2/users/links", {}, "link", ("url",)),
    ("POST", re.compile(r"/api2/v2/streams/users/(?P<username>[A-Za-z0-9._-]+)/block")): (
        "/api2/v2/streams/users/blocked", {"limit": 50}, "username", ("username",)),
    ("POST", re.compile(r"/api2/v2/chats/(?P<fan>\d+)/messages")): (*read_id_query("message", None, "{fan}"), "text",
                                                                    ("rawText", "text")),
}
MADE_BY = {("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$")): (("POST", "/api2/v2/messages/queue"),
                                                                     ("POST", POSTS_PATH))}
_CDN = os.environ.get("OFM_FAKE_CDN_HOST", "") if _FAKE else ""
TAG = "x-oi-proof-read"
_DRIVER = contextvars.ContextVar("ofm_driver_read", default=False)


def _to_fake(url: str) -> str:
    parts = urlsplit(str(url))
    if not _FAKE or parts.netloc == _FAKE:
        return str(url)
    return f"http://{_FAKE}{parts.path}" + (f"?{parts.query}" if parts.query else "")


_lock = threading.Lock()
_pace_lock = threading.Lock()
_last_write = None
_run = Run(of="fake" if _FAKE else "live")
_wire: dict = {}
_seq = 0
_rows: dict = {}


_row = max((r["row"] for r in read_undo_log(UNDO)), default=0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _body(k: dict):
    if k.get("json") is not None:
        return k["json"]
    return log_body(k.get("data"))


def _complete(entry: dict, status) -> None:
    done = {**entry, "status": status, "phase": "done"}
    with _lock:
        _wire[entry["seq"]] = done
    append_jsonl(WIRE, done)


def _intent(origin: str, method: str, url: str, body):
    global _run, _seq, _row, _last_write
    parts = urlsplit(str(url))
    host = _OF_HOST if _FAKE and parts.netloc == _FAKE else (parts.hostname or "")
    method = method.upper()

    def verdict(run, at):
        return decide(Request(method, host, parts.path, body, at), run)

    with _lock:
        peek = verdict(_run, _now())
    paced = peek.kind in ("allow", "reversal") and method not in READS
    with (_pace_lock if paced else contextlib.nullcontext()):
        while paced and (wait := pace_wait(_last_write, _now())) > 0:
            time.sleep(wait)
        with _lock:
            run = _run
            now = _now()
            v = verdict(run, now)
            _seq += 1
            entry = {"seq": _seq, "time": now.isoformat(), "origin": origin, "method": method, "host": host,
                     "path": parts.path, "query": redact_query(parts.query), "body": body, "status": None, "verdict": v.kind,
                     "class": v.cls, "reason": v.reason, "proof": run.proof.id if run.proof else None,
                     "phase": "intent"}
            _wire[_seq] = entry
            append_jsonl(WIRE, entry)
            row = None
            if v.kind in ("allow", "reversal") and method not in READS:
                _last_write = now
            if v.kind in ("allow", "reversal") and v.key is not None:
                _run = replace(run, spent={**run.spent, v.key: run.spent.get(v.key, 0) + 1})
            if v.fan_visible and run.proof is not None:
                _run = replace(_run, fan_visible_done=(*_run.fan_visible_done, run.proof.id))
            if v.kind == "allow" and method not in READS:
                _row += 1
                row = {"row": _row, "proof": run.proof.id, "state": "pending", "opened": entry["time"], "arm": v.key[1],
                       "write": {"method": method, "path": parts.path,
                                 "narrowed": str(run.proof.narrowing) if run.proof.narrowing else "none"},
                       "of_id": None, "wire_seq": _seq, "fan_visible": v.fan_visible, "note": v.reason}
                append_jsonl(UNDO, row)
                if origin == "of-browser":
                    _rows[_seq] = row
    if v.kind == "refused":
        _complete(entry, "refused")
    return entry, v, row


def _add_created(run: Run, row: dict, of_id: str) -> Run:
    arm = row.get("arm")
    by = run.created_by if arm is None else {**run.created_by, arm: run.created_by.get(arm, frozenset()) | {of_id}}
    return replace(run, created=run.created | {of_id}, created_by=by)


def _created(row: dict, of_id, status) -> None:
    global _run
    if of_id is not None:
        with _lock:
            if _run.proof is not None and _run.proof.id == row["proof"]:
                _run = _add_created(_run, row, of_id)
    append_jsonl(UNDO, {**row, "of_id": of_id, "write_status": status})


def _guarded(origin: str, method: str, url: str, body, forward):
    import of_client

    entry, v, row = _intent(origin, method, url, body)
    if v.kind == "refused":
        raise of_client.OFDeniedError(f"Live guard refused {entry['method']} {entry['path']} ({v.cls}: {v.reason})")
    try:
        resp, status = forward()
    except BaseException as e:
        _complete(entry, f"error: {type(e).__name__}")
        if row is not None:
            append_jsonl(UNDO, {**row, "write_status": f"reply lost: {type(e).__name__}"})
        raise
    _complete(entry, status)
    if row is not None:
        of_id = None
        try:
            got = resp.json()
            of_id = str(got["id"]) if isinstance(got, dict) and got.get("id") is not None else None
        except Exception:  # noqa: BLE001  (a body that is not JSON names no id)
            pass
        _created(row, of_id, status)
    return resp


def _refuse_driver(method: str, url: str, body, why: str) -> None:
    global _seq
    parts = urlsplit(str(url))
    with _lock:
        _seq += 1
        entry = {"seq": _seq, "time": _now().isoformat(), "origin": "driver", "method": method.upper(),
                 "host": _OF_HOST if _FAKE and parts.netloc == _FAKE else (parts.hostname or ""), "path": parts.path,
                 "query": redact_query(parts.query), "body": body, "status": None, "verdict": "refused", "class": "driver_read",
                 "reason": why, "proof": _run.proof.id if _run.proof else None, "phase": "intent"}
        _wire[_seq] = entry
        append_jsonl(WIRE, entry)
    _complete(entry, "refused")


def driver_read(get, path: str, query: str):
    if not path.startswith("/api2/v2/") or any(x in path for x in ("?", "#", "//", "..", "://")):
        raise ValueError(f"not an OnlyFans API path: {path!r}")
    token = _DRIVER.set(True)
    try:
        return get(path + (f"?{query}" if query else ""))
    finally:
        _DRIVER.reset(token)


# curl_cffi bypasses net_guard's socket guard, so this wrap is the real egress gate.
def _guard_egress() -> None:
    from curl_cffi import CurlOpt
    from curl_cffi import requests as cffi
    import curl_cffi.requests.session as cffi_session
    import of_session_stream
    real = cffi.Session.request

    fresh = threading.local()
    real_set = cffi_session.set_curl_options

    def set_curl_options(c, *a, **k):
        out = real_set(c, *a, **k)
        # libcurl resends once when a reused connection dies, so a lost-reply write could reach OF twice; writes get a fresh one.
        if getattr(fresh, "write", False):
            c.setopt(CurlOpt.FRESH_CONNECT, 1)
        return out

    cffi_session.set_curl_options = set_curl_options
    of_session_stream.set_curl_options = set_curl_options

    def request(self, method, url, *a, **k):
        parts = urlsplit(str(url))
        if _CDN and parts.hostname == _CDN:
            url = f"http://{_FAKE}/cdn{parts.path}" + (f"?{parts.query}" if parts.query else "")
        driver = _DRIVER.get()
        if driver and method.upper() != "GET":
            import of_client
            why = f"driver reads are GET only: {method.upper()} {parts.path}"
            _refuse_driver(method, url, _body(k), why)
            raise of_client.OFDeniedError(f"Live guard refused {why}")
        if driver and _FAKE:
            k = {**k, "headers": {**dict(k.get("headers") or {}), TAG: "1"}}

        def forward():
            fresh.write = method.upper() not in READS
            try:
                r = real(self, method, _to_fake(url), *a, **k)
            finally:
                fresh.write = False
            return r, r.status_code

        return _guarded("driver" if driver else "relay", method, url, _body(k), forward)

    request.__ofm_live_guard__ = True
    cffi.Session.request = request

    real_open = urllib.request.urlopen

    def urlopen(url, data=None, *a, **k):
        target = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        method = url.get_method() if isinstance(url, urllib.request.Request) else ("POST" if data else "GET")
        payload = data if data is not None else getattr(url, "data", None)
        body = _body({"data": payload}) if payload is not None else None

        def forward():
            sent, fake = url, _to_fake(target)
            if fake != target:
                sent = (urllib.request.Request(fake, data=url.data, headers=dict(url.headers), method=method)
                        if isinstance(url, urllib.request.Request) else fake)
            r = real_open(sent, data, *a, **k)
            return r, getattr(r, "status", None)

        return _guarded("relay", method, target, body, forward)

    urllib.request.urlopen = urlopen


def read_id_matches(kind: str, oid: str, source: str, body) -> bool:
    if not isinstance(body, dict):
        return False
    if kind == "media":
        return any(isinstance(m, dict) and str(m.get("id")) == oid for m in body.get("media") or [])
    rows = [x for x in body.get("list") or [] if isinstance(x, dict) and str(x.get("id")) == oid]
    if kind == "schedule":
        return any(str((x.get("entity") or {}).get("id")) == source for x in rows)
    return kind == "message" and any(str(x.get("queueId")) == source for x in rows)


def _read_id_line(proof, b: dict, status: int, reason: str) -> None:
    global _seq
    with _lock:
        _seq += 1
        entry = {"seq": _seq, "time": _now().isoformat(), "origin": "proof-read-id", "method": "READ-ID", "host": "",
                 "path": "/__proof/read-id", "query": "", "body": b, "status": status, "verdict": "read-id",
                 "class": "read-id", "reason": reason, "proof": proof.id if proof else None, "phase": "done"}
        _wire[_seq] = entry
    append_jsonl(WIRE, entry)


def _loopback(request) -> None:
    if (request.client.host if request.client else "") not in ("127.0.0.1", "::1"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="proof hooks are loopback-only")


def _found_mismatch(of_get, request, row, of_id: str, rows) -> str | None:
    w = row["write"]
    made = next((c for (m, rx), c in MADE_BY.items() if w["method"] == m and rx.match(w["path"])), None)
    if made is not None:
        own = any(r["proof"] == row["proof"] and (r["write"]["method"], r["write"]["path"]) in made
                  and str(r.get("of_id")) == of_id for r in rows.values())
        return None if own else (f"{of_id} is no id {row['proof']}'s own "
                                 + " or ".join(f"{m} {p}" for m, p in made) + " got")
    hit = None
    for (m, p), r in READ_BACK.items():
        g = p.fullmatch(w["path"]) if isinstance(p, re.Pattern) else p == w["path"]
        if m == w["method"] and g:
            hit = g, r
            break
    if hit is None:
        return f"{w['method']} {w['path']} has no read-back to confirm a found id"
    g, (path, params, field, fields) = hit
    in_path = isinstance(g, re.Match) and field in g.groupdict()
    sent = (_wire.get(row.get("wire_seq")) or {}).get("body")
    want = g[field] if in_path else sent.get(field) if isinstance(sent, dict) else None
    if not isinstance(want, str) or not want:
        return f"row {row['row']}'s write sent no {field} to match"
    listed = "{id}" not in path
    path = path.format(**(g.groupdict() if isinstance(g, re.Match) else {}), id=of_id)
    try:
        got = of_get(request, path, dict(params))
    except Exception as e:  # noqa: BLE001  (a refused or failed read takes no id)
        return f"the Relay's read {path} failed: {type(e).__name__}: {str(e)[:200]}"
    if listed:
        page = got.get("list") if isinstance(got, dict) else got
        hits = [r for r in page if isinstance(r, dict) and str(r.get("id")) == of_id] if isinstance(page, list) else []
        if len(hits) != 1:
            return f"{path} lists {len(hits)} rows with id {of_id}, not one"
        got = hits[0]
    have = next((str(got[f]) for f in fields if got.get(f)), "") if isinstance(got, dict) else ""
    if have == want or (in_path and want == f"u{of_id}"):
        return None
    return f"{path} reads {have[:80]!r}, not the row's sent {field} {want[:80]!r}"


def proof_routes(app, of_get) -> None:
    from fastapi import HTTPException
    from fastapi import Request as FRequest

    registered: set = set()

    async def arm(request: FRequest) -> dict:
        global _run
        _loopback(request)
        b = await request.json()
        pid = b.get("proof")
        if pid is not None and pid not in ALL:
            raise HTTPException(status_code=404, detail=f"unknown proof {pid!r}")
        if b.get("quiet_hour") and not _FAKE:
            raise HTTPException(status_code=400, detail="quiet_hour is declared by the owner, never armed live")
        with _lock:
            proof = ALL[pid] if pid else None
            _run = Run(proof=proof, of="fake" if _FAKE else "live",
                       capture_abort=bool(b.get("capture_abort")), proof_fan=b.get("proof_fan"),
                       owner_go=frozenset(b.get("owner_go") or ()), lockout=bool(b.get("lockout")),
                       fan_visible_done=_run.fan_visible_done, hosts=tuple(proof.hosts) if proof else (),
                       quiet_hour=datetime.fromisoformat(b["quiet_hour"]) if b.get("quiet_hour") else None,
                       cotag_partner=str(b["cotag_partner"]) if b.get("cotag_partner") else None,
                       marker=str(b["marker"]) if b.get("marker") else None)
            registered.clear()
        return {"armed": pid}

    async def wire(request: FRequest) -> dict:
        _loopback(request)
        with _lock:
            return {"wire": [_wire[k] for k in sorted(_wire)]}

    def found(request: FRequest, b: dict) -> dict:
        """A lost reply's id the driver's finder read (story 53) joins the row. Sync: the id is first read back by the
        Relay through the guard (`_found_mismatch`), which takes `_lock`, in the threadpool."""
        global _run
        _loopback(request)
        of_id = str(b.get("of_id") or "")
        rows = {r["row"]: r for r in read_undo_log(UNDO)}
        row = rows.get(b.get("row"))
        why = _found_mismatch(of_get, request, row, of_id, rows) if of_id and row is not None else None
        if why:
            raise HTTPException(status_code=409, detail=f"found id refused: {why}")
        with _lock:
            proof = _run.proof
            if not of_id or row is None or proof is None or row["proof"] != proof.id \
                    or row["state"] != "pending" or row.get("of_id") is not None:
                raise HTTPException(status_code=409, detail="only a pending row of the armed proof with no "
                                                            "OnlyFans id takes a found id")
            _run = _add_created(_run, row, of_id)
        append_jsonl(UNDO, {**row, "of_id": of_id, "found_by": "after-write read"})
        return {"row": row["row"], "of_id": of_id}

    def read_id(request: FRequest, b: dict) -> dict:
        """An id read off `source` joins the ids of kind `key`, once the Relay's own read shows it so (ticket 131's
        registration, ticket 100's safety). Sync: the read goes through the guard, which takes `_lock`, in the
        threadpool."""
        global _run
        of_id, key, source = str(b.get("of_id") or ""), str(b.get("key") or ""), str(b.get("source") or "")
        line = {"key": key, "of_id": of_id, "source": source, **({"row": b["row"]} if "row" in b else {})}
        try:
            _loopback(request)
        except HTTPException as e:
            _read_id_line(_run.proof, line, e.status_code, str(e.detail))
            raise
        rows = [r for r in read_undo_log(UNDO) if "row" not in b or r["row"] == b["row"]]
        with _lock:
            proof, fan = _run.proof, _run.proof_fan
            try:
                add_read_id(_run, key, of_id, source)
                why = None
            except ValueError as e:
                why = str(e)
            why = why or (f"the Relay has no read for kind {key!r}" if key not in READ_ID_KINDS
                          else f"no pending row of {proof.id} carries {source}" if not any(
                              r["proof"] == proof.id and r["state"] == "pending" and str(r.get("of_id")) == source
                              for r in rows)
                          else f"{source} already has its {key} registered" if (source, key) in registered
                          else "the Proof fan is unset" if key == "message" and fan is None
                          else None)
        if why is None:
            path, params = read_id_query(key, source, fan, _now())
            try:
                body = of_get(request, path, params)
            except Exception as e:  # noqa: BLE001  (a refused or failed read registers nothing)
                why = f"the Relay's read {path} failed: {type(e).__name__}: {str(e)[:200]}"
            else:
                if not read_id_matches(key, of_id, source, body):
                    why = f"the Relay's read {path} does not show {of_id} as the {key} of {source}"
        if why is None:
            with _lock:
                if _run.proof is not proof:
                    why = "the armed proof changed during the read"
                elif (source, key) in registered:
                    why = f"{source} already has its {key} registered"
                else:
                    try:
                        _run = add_read_id(_run, key, of_id, source)
                        registered.add((source, key))
                    except ValueError as e:
                        why = str(e)
        _read_id_line(proof, line, 409 if why else 200, why or f"{of_id} is the {key} of {source}")
        if why:
            raise HTTPException(status_code=409, detail=f"read id refused: {why}")
        return line

    def browser_decide(request: FRequest, b: dict) -> dict:
        _loopback(request)
        entry, v, _ = _intent("of-browser", str(b["method"]), str(b["url"]), b.get("body"))
        return {"seq": entry["seq"], "verdict": v.kind, "class": v.cls, "reason": v.reason, "capture": v.capture}

    def browser_done(request: FRequest, b: dict) -> dict:
        _loopback(request)
        with _lock:
            entry = _wire.get(b.get("seq"))
            ok = entry is not None and entry["origin"] == "of-browser" and entry["phase"] == "intent" \
                and entry["verdict"] != "refused"
            if ok:
                _wire[entry["seq"]] = {**entry, "phase": "completing"}
            row = _rows.pop(entry["seq"], None) if ok else None
        if not ok:
            raise HTTPException(status_code=409, detail="only a forwarded capture-browser intent line takes a "
                                                        "completion, once")
        _complete(entry, b.get("status"))
        if row is not None:
            status = b.get("status")
            if isinstance(status, int):
                _created(row, None if b.get("of_id") is None else str(b["of_id"]), status)
            else:
                append_jsonl(UNDO, {**row, "write_status": f"reply lost: {status}"})
        return {"seq": entry["seq"]}

    app.add_api_route("/__proof/arm", arm, methods=["POST"])
    app.add_api_route("/__proof/wire", wire, methods=["GET"])
    app.add_api_route("/__proof/found", found, methods=["POST"])
    app.add_api_route("/__proof/decide", browser_decide, methods=["POST"])
    app.add_api_route("/__proof/done", browser_done, methods=["POST"])
    app.add_api_route("/__proof/read-id", read_id, methods=["POST"])


def _wire_routes(app) -> None:
    from fastapi import HTTPException, Response
    from fastapi import Request as FRequest

    import employees
    import server

    if hasattr(employees, "_AUDIT_SKIP_PREFIXES"):
        employees._AUDIT_SKIP_PREFIXES = (*employees._AUDIT_SKIP_PREFIXES, "/__proof/")

    def session(request: FRequest) -> dict:
        _loopback(request)
        return server._users_me_read()

    def of_read(request: FRequest, path: str, query: str = ""):
        _loopback(request)
        try:
            r = driver_read(lambda pq: server._proxy(lambda: server._get_client().get(pq)), path, query)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return Response(content=r.content, status_code=r.status_code, media_type="application/json")

    app.add_api_route("/__proof/session", session, methods=["GET"])
    app.add_api_route("/__proof/of-read", of_read, methods=["GET"])
    proof_routes(app, lambda request, path, params: server._get_client(request).get_json(path, params=params))


def main() -> None:
    real_run = uvicorn.run

    def run(app, **kw):
        _guard_egress()
        _wire_routes(app)
        return real_run(app, **kw)

    uvicorn.run = run
    sys.argv = [str(DEMO / "relay_guarded.py")]
    runpy.run_path(str(DEMO / "relay_guarded.py"), run_name="__main__")


if __name__ == "__main__":
    main()
