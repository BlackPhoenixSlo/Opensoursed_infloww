"""The live Relay launcher: scripts/demo-shots/relay_guarded.py's sandbox (temp DB, redirected secrets, sessions and
proxies, net_guard, `_run_ui_safe`: every background loop off) plus the Live guard on every OnlyFans request.

Every `curl_cffi` `Session.request` and every `urllib.request.urlopen` the Relay makes goes through
`proof_core.decide`; its wire log line is written before the request is forwarded (the intent), then completed with
the status. A refusal raises `of_client.OFDeniedError` (the Relay answers 403, never retried) and nothing is sent. An
allowed write opens its Undo log row as `pending` before it is forwarded. No file under service/ changes: every hook
lives here (precedent: scripts/demo-shots/promo_proof_relay.py, slop/lib/relay.py `_guard_curl_cffi`).

Loopback-only routes:
  POST /__proof/arm {proof: id|null, of, proof_fan, owner_go: [..], lockout, capture_abort, quiet_hour}   arm or
                           disarm; `quiet_hour` (ISO, aware) starts the run's declared quiet hour (Run.quiet_hour),
                           fake mode only (a live arm carrying it is answered 400); `cotag_partner` (ticket 98):
                           a POST /posts's only allowed Co-tag (Run.cotag_partner)
  GET  /__proof/wire       the wire log so far (one entry per request, completed)
  GET  /__proof/session    OnlyFans's /users/me through the undecorated route (no 60 s cache)
  GET  /__proof/of-read?path=/api2/v2/...&query=<qs>   the driver's own OnlyFans-side read (ticket 11, prove.py
                           `Stack.of_get`, both modes): one signed GET on the X-Account-Id Creator's OFClient (the
                           session copy in the run's temp dir), through `_proxy` like the Relay's own routes, decided
                           and logged by the egress wrap with origin `driver` (`driver_read`); OnlyFans's status and
                           JSON body answered as they came. Fake mode adds FakeOF's TAG header so its recorder tells
                           the driver's read from the app's; live mode never sends it
  POST /__proof/found {row, of_id}   a write whose reply was lost (story 53), found by the driver's after-write
                           read: its id joins the armed proof's created ids so its declared undo can pass; the write
                           itself is never retried (its armed count stays spent); only once the Relay's own read of
                           that id shows what the row's write sent (`READ_BACK`, keyed on the create path: posts, the
                           message queue, fan lists, vault folders, trial links,
                           social buttons, Things I Like links, stream blocks), or (`MADE_BY`: the publish, no id
                           in its reply) once it is an id the proof's own queue write or post create got, else 409;
                           any other write's found id is refused (409)
  POST /__proof/decide {method, url, body}   the capture browser's route (of_browser.py), before its request
                           leaves: the same decision, wire log intent and pending row as a Relay request, origin
                           `of-browser`, with one counter, one Undo log and one Run (spent, created ids) for both
  POST /__proof/done {seq, status, of_id}   that request's completion: the wire line's status and, for an allowed
                           write, its OnlyFans id on the row this Relay opened for that seq (kept here, never sent by
                           the caller); only an `of-browser` intent line takes one, once (a lost reply leaves the row
                           pending, never retried)
  POST /__proof/read-id {key, of_id, source, row?}   an id the driver read off `source`, an OnlyFans id the armed
                           proof created that a pending row of it carries (ticket 30: the vault media id the created
                           post carries, `Proof.undo_keys`; ticket 100: the queued message's "schedule" item, the
                           "message" it became), created by an arm the key is read off (ticket 131): it joins the ids
                           of kind `key` (`Run.keys`, never `id`), so the undo's or publish's `{key}` binds to it
                           alone in the guard (`proof_core.add_read_id`). Only a kind the proof declares and the
                           Relay can verify, once its own OnlyFans read shows it so (`read_id_matches`), once per
                           (source, kind); every attempt is a wire log line (verdict `read-id`); anything else 409

Env: OFM_PROOF_EVIDENCE (the run's evidence folder: wire.jsonl, undo-log.jsonl), OF_API_ORIGIN (fake mode: FakeOF's
loopback origin, decided as the onlyfans.com host), OFM_FAKE_CDN_HOST (fake mode: FakeOF's picture host, a request to
it rewritten to FakeOF's `/cdn` before it is decided; soak/fake_of/vault.py), plus relay_guarded.py's DEMO_SHOTS_*
variables. Fake mode never leaves the machine: a request the guard lets through to any other host (an onlyfans.com
subdomain such as the upload's fixed convert host, or a host named from a capture) is decided and logged on its own host,
then sent to FakeOF on the same path (`_to_fake`), which answers what it models and 404s and counts the rest.
"""
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
# A found id's read-back (`/__proof/found`, story 53; ticket 97 review), keyed on the row's create path: the Relay's
# own read of the id and the field the write sent that it must show exactly. (read path, params, sent field, read
# fields: the first non-empty one is compared). Reads modelled on service/of_reads.py and FakeOF: posts
# (`GET /posts/{id}`), the queue (`queued_message`, captured: app/lib/__fixtures__/of/queue-edit-message.json), fan
# lists (`get_list`, soak/fake_of/growth.py), vault folders (`GET /vault/lists/{id}`, the path in OF's own JS,
# .scratch/ofm-not-yet/captures/of-js-endpoints.txt:593; its answer INFERRED per D29: no capture, the listing's folder
# row with its `name` assumed), trial links (no single-item read: the Relay's own list read, of_reads `trial_links`,
# captured fixture app/lib/__fixtures__/of/settings-trials.json; newest first, so a just-made link is on page one).
# Phase 3's creates OF answers with the whole list (no id) read back on the list read their proof's finder used:
# social buttons (`GET /users/social/buttons`, its `label`), Things I Like (`GET /users/links`, the sent `link` read as
# `url`: capture records settings--social-media-buttons / settings--things-i-like-links), stream blocks (`GET
# /streams/users/blocked`, its proof's read arm; no body, so the path's username: the row's `username`, or OF's
# default handle `u<id>` naming the found id itself). A create path is a string or a regex (a named group is a sent
# field). A read path without `{id}` is such a list read: exactly one row carries the id, and its field must match. A
# create path not here has no read-back, so its found id is refused, never exempted. A chat send (the PPV proof's, to
# the Proof fan the guard held it to) is read back on the driver's own thread read (`read_id_query`), its sent text
# (the run's marker, Write.payload) exact on the one row with the id (follow-up #10). A read path's `{name}` other
# than `{id}` takes the create path's named group.
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
# A write whose reply carries no id (the publish answers `{success}`) takes the id of what it acted on: only an id
# one of the armed proof's own create writes on one of those paths got in its reply (no read: that id is the Relay's
# own). Ticket 99: a post's Publish now acts on the post its own post create made.
MADE_BY = {("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$")): (("POST", "/api2/v2/messages/queue"),
                                                                     ("POST", POSTS_PATH))}
_CDN = os.environ.get("OFM_FAKE_CDN_HOST", "") if _FAKE else ""
TAG = "x-oi-proof-read"   # fake_layer.TAG (not imported: FakeOF's stack stays out of a live Relay)
_DRIVER = contextvars.ContextVar("ofm_driver_read", default=False)   # set around the driver's read (`driver_read`)


def _to_fake(url: str) -> str:
    """Fake mode: `url` on FakeOF, same path and query, whatever its host (decided first; `_guarded`'s forward)."""
    parts = urlsplit(str(url))
    if not _FAKE or parts.netloc == _FAKE:
        return str(url)
    return f"http://{_FAKE}{parts.path}" + (f"?{parts.query}" if parts.query else "")


_lock = threading.Lock()
_pace_lock = threading.Lock()   # forwarded writes pass the pacing wait one at a time (story 22)
_last_write = None              # intent time of the last forwarded write
_run = Run(of="fake" if _FAKE else "live")
_wire: dict = {}      # seq -> entry
_seq = 0
_rows: dict = {}      # seq -> the pending Undo log row of an allowed capture-browser write, until /__proof/done


_row = max((r["row"] for r in read_undo_log(UNDO)), default=0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _body(k: dict):
    """The request body as decided and logged: JSON parsed; a binary upload by its length only (ticket 53, `log_body`)."""
    if k.get("json") is not None:
        return k["json"]
    return log_body(k.get("data"))


def _complete(entry: dict, status) -> None:
    done = {**entry, "status": status, "phase": "done"}
    with _lock:
        _wire[entry["seq"]] = done
    append_jsonl(WIRE, done)


def _intent(origin: str, method: str, url: str, body):
    """Decide, log the intent and, for an allowed write, open its `pending` Undo log row. -> (entry, verdict, row)."""
    global _run, _seq, _row, _last_write
    parts = urlsplit(str(url))
    host = _OF_HOST if _FAKE and parts.netloc == _FAKE else (parts.hostname or "")
    method = method.upper()

    def verdict(run, at):
        return decide(Request(method, host, parts.path, body, at), run)

    # Story 22: a write the guard would forward waits until PACE after the last forwarded one, then is decided
    # again and logged, so the wire log's intent times are paced. Reads and refusals never wait.
    with _lock:
        peek = verdict(_run, _now())
    paced = peek.kind in ("allow", "reversal") and method not in READS
    with (_pace_lock if paced else contextlib.nullcontext()):
        # Re-check after each sleep: the logged time is the wall clock, which can land a few ms short of a sleep
        # timed on the monotonic clock (measured: gaps a hair under 5 s failed pace_problems, run 20261121T071230Z).
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
                # one entry per attempt (ticket 99: Proof.fan_visible_max), so the guard counts a proof's attempts
                _run = replace(_run, fan_visible_done=(*_run.fan_visible_done, run.proof.id))
            if v.kind == "allow" and method not in READS:
                _row += 1
                # ticket 30: the arm index (Verdict.key, ("arm", i)) picks the undo Writes that reverse this row
                # (undo_log.row_undos); the driver reads it, never re-matches the write against the arms.
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
    """`run` with `of_id` among the created ids, and among those of the row's arm (ticket 131: `Run.created_by`)."""
    arm = row.get("arm")
    by = run.created_by if arm is None else {**run.created_by, arm: run.created_by.get(arm, frozenset()) | {of_id}}
    return replace(run, created=run.created | {of_id}, created_by=by)


def _created(row: dict, of_id, status) -> None:
    """An allowed write's reply: its OnlyFans id joins the armed proof's created ids, and its row records both."""
    global _run
    if of_id is not None:
        with _lock:
            if _run.proof is not None and _run.proof.id == row["proof"]:
                _run = _add_created(_run, row, of_id)
    append_jsonl(UNDO, {**row, "of_id": of_id, "write_status": status})


def _guarded(origin: str, method: str, url: str, body, forward):
    """Decide, log the intent, forward (or refuse), complete. `forward()` -> (response, status)."""
    import of_client

    entry, v, row = _intent(origin, method, url, body)
    if v.kind == "refused":
        raise of_client.OFDeniedError(f"Live guard refused {entry['method']} {entry['path']} ({v.cls}: {v.reason})")
    try:
        resp, status = forward()
    except BaseException as e:
        _complete(entry, f"error: {type(e).__name__}")
        if row is not None:
            # Counted as sent (story 53): the row stays pending, never retried here.
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
    """A driver request that is not a GET: logged refused (class `driver_read`) like a guard refusal, never decided or
    sent."""
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
    """The driver's OnlyFans-side read (ticket 11): `get(path_qs)` (the route's signed OFClient GET) with every request
    it makes marked as the driver's, so the egress wrap logs it with origin `driver` and refuses anything but a GET.
    Only an /api2/v2/ path with no query, scheme, host or `..` of its own: `query` is the only query."""
    if not path.startswith("/api2/v2/") or any(x in path for x in ("?", "#", "//", "..", "://")):
        raise ValueError(f"not an OnlyFans API path: {path!r}")
    token = _DRIVER.set(True)
    try:
        return get(path + (f"?{query}" if query else ""))
    finally:
        _DRIVER.reset(token)


def _guard_egress() -> None:
    """curl_cffi goes past net_guard's socket guard, so this wrap is the real egress gate; urlopen too
    (the paste-curl bootstrap's signing-chunk fetch, service/session_bootstrap.py:253). Every curl_cffi call passes
    `Session.request`: service's ManagedSession overrides only `_request_once` (its streamed branch is
    `of_session_stream.stream_once`), which `Session.request` calls; service has no curl_cffi AsyncSession."""
    from curl_cffi import CurlOpt
    from curl_cffi import requests as cffi
    import curl_cffi.requests.session as cffi_session
    import of_session_stream
    real = cffi.Session.request

    # Story 53, measured in the lost-reply fault run: libcurl itself resends a request once when a reused keep-alive
    # connection dies with no reply, below this wrap, so a write whose reply was lost reached OnlyFans twice. A write on
    # a fresh, never-reused connection is never resent. The flag is per thread and lands only on the Curl handle this
    # request leased: curl_cffi 0.15.0's Session._request_once (and service's stream_once) copy options onto it in
    # set_curl_options, and reset it after perform. Session.curl_options, shared by every Relay thread, never changes.
    fresh = threading.local()
    real_set = cffi_session.set_curl_options

    def set_curl_options(c, *a, **k):
        out = real_set(c, *a, **k)
        if getattr(fresh, "write", False):
            c.setopt(CurlOpt.FRESH_CONNECT, 1)
        return out

    cffi_session.set_curl_options = set_curl_options
    of_session_stream.set_curl_options = set_curl_options

    def request(self, method, url, *a, **k):
        parts = urlsplit(str(url))
        if _CDN and parts.hostname == _CDN:   # fake mode: FakeOF serves the picture
            url = f"http://{_FAKE}/cdn{parts.path}" + (f"?{parts.query}" if parts.query else "")
        driver = _DRIVER.get()
        if driver and method.upper() != "GET":   # the driver only reads (ticket 11); logged refused, never sent
            import of_client
            why = f"driver reads are GET only: {method.upper()} {parts.path}"
            _refuse_driver(method, url, _body(k), why)
            raise of_client.OFDeniedError(f"Live guard refused {why}")
        if driver and _FAKE:   # FakeOF's recorder tells the driver's read from the app's; never sent to OnlyFans
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
            if fake != target:   # a new Request, so the caller's keeps its own host and headers
                sent = (urllib.request.Request(fake, data=url.data, headers=dict(url.headers), method=method)
                        if isinstance(url, urllib.request.Request) else fake)
            r = real_open(sent, data, *a, **k)
            return r, getattr(r, "status", None)

        return _guarded("relay", method, target, body, forward)

    urllib.request.urlopen = urlopen


def read_id_matches(kind: str, oid: str, source: str, body) -> bool:
    """Whether the read shows `oid` as the `kind` of `source`: a medium of the post, a schedule item whose entity is
    the queued message, or a chat message carrying its queueId. Any other kind: never."""
    if not isinstance(body, dict):
        return False
    if kind == "media":
        return any(isinstance(m, dict) and str(m.get("id")) == oid for m in body.get("media") or [])
    rows = [x for x in body.get("list") or [] if isinstance(x, dict) and str(x.get("id")) == oid]
    if kind == "schedule":
        return any(str((x.get("entity") or {}).get("id")) == source for x in rows)
    return kind == "message" and any(str(x.get("queueId")) == source for x in rows)


def _read_id_line(proof, b: dict, status: int, reason: str) -> None:
    """Every registration attempt on the wire log: verdict `read-id`, method READ-ID (no forwarded write, no
    OnlyFans hit; the Relay's own read has its own line)."""
    global _seq
    with _lock:
        _seq += 1
        entry = {"seq": _seq, "time": _now().isoformat(), "origin": "proof-read-id", "method": "READ-ID", "host": "",
                 "path": "/__proof/read-id", "query": "", "body": b, "status": status, "verdict": "read-id",
                 "class": "read-id", "reason": reason, "proof": proof.id if proof else None, "phase": "done"}
        _wire[_seq] = entry
    append_jsonl(WIRE, entry)


def _loopback(request) -> None:
    """Every `/__proof/*` route answers loopback callers only."""
    if (request.client.host if request.client else "") not in ("127.0.0.1", "::1"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="proof hooks are loopback-only")


def _found_mismatch(of_get, request, row, of_id: str, rows) -> str | None:
    """Why a found id cannot join its row, or None: the Relay's own read of `of_id` (`READ_BACK`, by the row's create
    path) must show exactly what the row's write sent, so another user's item made meanwhile is never undone on a
    finder's word; a write `MADE_BY` names takes only an id its proof's own create write got. Any other: refused."""
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
    if not isinstance(want, str) or not want:   # an empty name matches any unnamed item: never taken
        return f"row {row['row']}'s write sent no {field} to match"
    listed = "{id}" not in path
    path = path.format(**(g.groupdict() if isinstance(g, re.Match) else {}), id=of_id)
    try:
        got = of_get(request, path, dict(params))
    except Exception as e:  # noqa: BLE001  (a refused or failed read takes no id)
        return f"the Relay's read {path} failed: {type(e).__name__}: {str(e)[:200]}"
    if listed:   # a list read: exactly one row with the id
        page = got.get("list") if isinstance(got, dict) else got
        hits = [r for r in page if isinstance(r, dict) and str(r.get("id")) == of_id] if isinstance(page, list) else []
        if len(hits) != 1:
            return f"{path} lists {len(hits)} rows with id {of_id}, not one"
        got = hits[0]
    have = next((str(got[f]) for f in fields if got.get(f)), "") if isinstance(got, dict) else ""
    if have == want or (in_path and want == f"u{of_id}"):   # OF's default handle `u<id>` names the id itself
        return None
    return f"{path} reads {have[:80]!r}, not the row's sent {field} {want[:80]!r}"


def proof_routes(app, of_get) -> None:
    """The loopback `/__proof/*` routes but `session`. `of_get(request, path, params)` -> JSON is the Relay's own
    signed OnlyFans read (through the Live guard, so it has its wire line); raises on a refusal."""
    from fastapi import HTTPException
    from fastapi import Request as FRequest

    registered: set = set()   # (source, kind) registered for the armed proof; reset on arm

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
            # spent and created reset per proof; fan_visible_done is whole-effort (FAN_VISIBLE_CAP); hosts are the
            # armed proof's own (ticket 53), none between proofs
            proof = ALL[pid] if pid else None
            _run = Run(proof=proof, of="fake" if _FAKE else "live",   # the Relay's own mode, never the body's
                       capture_abort=bool(b.get("capture_abort")), proof_fan=b.get("proof_fan"),
                       owner_go=frozenset(b.get("owner_go") or ()), lockout=bool(b.get("lockout")),
                       fan_visible_done=_run.fan_visible_done, hosts=tuple(proof.hosts) if proof else (),
                       quiet_hour=datetime.fromisoformat(b["quiet_hour"]) if b.get("quiet_hour") else None,
                       cotag_partner=str(b["cotag_partner"]) if b.get("cotag_partner") else None,   # ticket 98
                       marker=str(b["marker"]) if b.get("marker") else None)   # round 2 #22: payloads bind to it
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
        except HTTPException as e:   # a refused caller is an attempt too: on the wire log
            _read_id_line(_run.proof, line, e.status_code, str(e.detail))
            raise
        rows = [r for r in read_undo_log(UNDO) if "row" not in b or r["row"] == b["row"]]
        with _lock:
            proof, fan = _run.proof, _run.proof_fan
            try:   # the pure decision first (proof armed, kind declared, source created by its arm): no read before
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
        _loopback(request)   # sync: a paced write's wait runs in the threadpool, never on the event loop
        entry, v, _ = _intent("of-browser", str(b["method"]), str(b["url"]), b.get("body"))
        return {"seq": entry["seq"], "verdict": v.kind, "class": v.cls, "reason": v.reason, "capture": v.capture}

    def browser_done(request: FRequest, b: dict) -> dict:
        _loopback(request)
        with _lock:
            entry = _wire.get(b.get("seq"))
            ok = entry is not None and entry["origin"] == "of-browser" and entry["phase"] == "intent" \
                and entry["verdict"] != "refused"
            if ok:   # completed once: a second call finds the line done
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
            else:   # counted as sent (story 53): the row stays pending, never retried
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
        return server._users_me_read()   # uncached OF read; main #892 made users_me async + cached

    def of_read(request: FRequest, path: str, query: str = ""):
        _loopback(request)   # sync, like `session`: the signed GET runs in the threadpool with the request's context
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
