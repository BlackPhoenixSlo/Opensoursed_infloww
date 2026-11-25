from __future__ import annotations

import asyncio
import json
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from soak.fake_of import settings as fake_settings  # noqa: E402
from soak.fake_of.app import FakeOF  # noqa: E402
from soak.fake_of.automations import priced_performer  # noqa: E402
from soak.fake_of.vault import CDN_HOST  # noqa: E402,F401  (prove.py hands it to the Relay)
from soak.fake_of.signing import sign_value  # noqa: E402
from soak.world import World  # noqa: E402
from soak.ids import fan_id  # noqa: E402
from soak.fake_of import queue as _queue  # noqa: E402  (ticket 100: unsend-refused asks whether the item is released)
from soak.fake_of import posts as _posts  # noqa: E402  (ticket 99: the hidden media faults)
from soak import ids as _ids  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proof_core import log_body, redact_query  # noqa: E402

PROOF_FAN = fan_id(1)

TAG = "x-oi-proof-read"
_ERR = b'{"error":{"code":%d,"message":"%s"}}'


def composer_once(planted: list):
    from of_browser import dedupe_media

    def hook(route, request) -> bool:
        if request.method != "POST" or urlsplit(request.url).path != "/api/of/v2/posts":
            return False
        try:
            body = json.loads(request.post_data or "")
        except ValueError:
            return False
        media = body.get("media_files") if isinstance(body, dict) else None
        if not isinstance(media, list) or dedupe_media(media) == media:
            return False
        planted.append({"method": "POST", "path": "/api/of/v2/posts", "media_files": media})
        route.continue_(post_data=json.dumps({**body, "media_files": dedupe_media(media)}))
        return True
    return hook


STATES = {"email-off": (fake_settings.email_off, "settings--email-update-frequency")}


def start_state_problems(name: str, parked) -> list:
    pid = STATES[name][1]
    return [] if any(p.get("proof") == pid for p in parked) else [f"start state {name}: {pid} did not park"]


OWNER_POST_TEXT = "Owner's scheduled post"


def publish_other(planted: list):
    rx = re.compile(r"^/api/of/v2/schedules/([^/]+)/publish$")

    def hook(route, request) -> bool:
        parts = urlsplit(request.url)
        m = rx.match(parts.path) if request.method == "PUT" else None
        if m is None:
            return False
        other = str(_ids.post_schedule_id(1))
        planted.append({"method": "PUT", "path": parts.path, "sent": other})
        route.continue_(url=parts._replace(path=f"/api/of/v2/schedules/{other}/publish").geturl())
        return True
    return hook


def _seed_owner_post(of) -> None:
    from datetime import timedelta
    from soak.world import now_utc
    p = _posts.Post(n=1, text=OWNER_POST_TEXT, media=[_ids.vault_media_id(1)],
                    scheduled_at=now_utc() + timedelta(hours=3), created_at=now_utc())
    _posts.state(of)["posts"][p.id] = p


def _holds_hidden(of, path, query, body) -> bool:
    media = (body.get("mediaFiles") if isinstance(body, dict) else None) or []
    return any(isinstance(m, int) and str(m) in _posts.hidden(of) for m in media)


def _publishes_hidden(of, path, query, body) -> bool:
    sid = int(path.split("/")[-2])
    return any(not p.deleted and p.published_at is None and p.schedule == sid
               and any(str(m) in _posts.hidden(of) for m in p.media) for p in _posts.state(of)["posts"].values())


async def _drop(send) -> bool:
    cycle = getattr(send, "__self__", None)
    if cycle is None or not hasattr(cycle, "transport"):
        return False
    for close in (cycle.transport.close, cycle.transport.abort):
        close()
        for _ in range(100):
            if getattr(cycle, "disconnected", False):
                return True
            await asyncio.sleep(0.01)
    return False



async def _answer(send, hit, code: int, body: bytes) -> None:
    hit["status"] = code
    await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


def status(code: int, msg: str = "fault"):
    async def act(app, scope, receive, send, hit):
        await _answer(send, hit, code, _ERR % (0 if code < 500 else code, msg.encode()))
    return act


def rewrite(change):
    async def act(app, scope, receive, send, hit):
        start, chunks = {}, []

        async def hold(msg):
            if msg["type"] == "http.response.start":
                start.update(msg)
                hit["status"] = msg["status"]
            else:
                chunks.append(msg.get("body", b""))

        await app(scope, receive, hold)
        out = json.dumps(change(json.loads(b"".join(chunks)), hit)).encode()
        headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
        await send({"type": "http.response.start", "status": start["status"],
                    "headers": [*headers, (b"content-length", str(len(out)).encode())]})
        await send({"type": "http.response.body", "body": out})
    return act


def applied_then(code: int | None, msg: str = "fault"):
    async def act(app, scope, receive, send, hit):
        async def swallow(msg_):
            if msg_["type"] == "http.response.start":
                hit["status"] = msg_["status"]
        await app(scope, receive, swallow)
        if code is not None:
            await _answer(send, hit, code, _ERR % (code, msg.encode()))
        elif not await _drop(send):
            hit["fault"] = f"{hit['fault']}: connection not dropped"
    return act


def drop_fields(keys: tuple[str, ...]):
    async def act(app, scope, receive, send, hit):
        raw = (await receive()).get("body") or b""
        try:
            body = json.loads(raw or b"null")
        except ValueError:
            body = None
        dropped = [k for k in keys if isinstance(body, dict) and k in body]
        if dropped:
            raw = json.dumps({k: v for k, v in body.items() if k not in dropped}).encode()
        else:
            hit["fault"] = f"{hit['fault']}: the body had no {keys[0]}"

        async def replay():
            return {"type": "http.request", "body": raw, "more_body": False}

        async def record(msg):
            if msg["type"] == "http.response.start":
                hit["status"] = msg["status"]
            await send(msg)
        await app({**scope, "headers": [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
                   + [(b"content-length", str(len(raw)).encode())]}, replay, record)
    return act


async def _rename_ignored(app, scope, receive, send, hit):
    try:
        body = json.loads((await receive()).get("body") or b"null")
    except ValueError:
        body = None
    name = body.get("name") if isinstance(body, dict) else None
    await _answer(send, hit, 200, json.dumps({"id": int(scope["path"].rsplit("/", 1)[1]), "type": "custom",
                                              "name": name}).encode())


FOREIGN_QUEUE_TEXT = "Weekend special for my favourites"


async def _queue_foreign(app, scope, receive, send, hit):
    try:
        body = json.loads((await receive()).get("body") or b"null")
    except ValueError:
        body = None
    body = {**(body if isinstance(body, dict) else {}), "text": FOREIGN_QUEUE_TEXT, "userIds": [fan_id(2)],
            "userLists": []}
    raw = json.dumps(body).encode()

    async def foreign():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def swallow(msg):
        pass
    await app({**scope, "headers": [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
               + [(b"content-length", str(len(raw)).encode())]}, foreign, swallow)
    await _answer(send, hit, 500, _ERR % (500, b"fault"))



def _cdn_src(data, hit):
    items = data.get("list") or []
    if items:
        items[0]["_thumb"] = items[0]["files"]["thumb"]["url"]
    else:
        hit["fault"] = "cdn-src: no item to plant"
    return data


def _planted(plant):
    def change(data, hit):
        why = plant(data)
        if why:
            hit["fault"] = f"{hit['fault']}: {why}"
        return data
    return change


def _plant_tip(data):
    if not isinstance((data or {}).get("list"), list):
        return "no list to plant in"
    data["list"].insert(0, {"id": 1, "type": "commented", "createdAt": "2026-01-01T00:00:00+00:00", "isRead": True,
                            "text": "Planted fan commented on your post",
                            "user": {"id": 2, "name": "Planted fan", "username": "plantedfan"}})


def _plant_strip(data):
    rows = data if isinstance(data, list) else (data or {}).get("list")
    if not rows:
        return "no creator to drop"
    rows.pop(0)


def _plant_highlight(data):
    rows = (data or {}).get("list") or []
    if not rows or "cover" not in rows[0]:
        return "no highlight cover to drop"
    rows[0].pop("cover")


def _plant_payout(data):
    rows = (data or {}).get("list") or []
    if not rows:
        return "no payout row to plant in"
    for r in rows:
        r.pop("invoiceId", None)


def _audience(field, value):
    def change(data, hit):
        if isinstance(data, dict) and "id" in data:
            data[field] = [*(data.get(field) or []), value]
        else:
            hit["fault"] = f"{hit['fault']}: no queued item to plant"
        return data
    return change


def _drop_stored_order(data: dict, hit) -> dict:
    from soak.fake_of import render
    from soak.fake_of.vault import _rows
    at = {r["id"]: k for k, r in enumerate(_rows(render._tpl("vault-lists.json")))}
    data.pop("sort", None)
    data.pop("order", None)
    data["list"] = sorted(data.get("list") or [], key=lambda r: at.get(r.get("id"), len(at)))
    return data


COTAG_PARTNER = 2001
COTAG_EXTRA = 2002


def _lost_reply_target(of, path, query, body) -> bool:
    if path != "/api2/v2/posts":
        return True
    return isinstance(body, dict) and not body.get("isScheduled") and bool(body.get("rfTag"))


def cotag_extra(planted: list):
    def hook(route, request) -> bool:
        if request.method != "POST" or urlsplit(request.url).path != "/api/of/v2/posts":
            return False
        try:
            body = json.loads(request.post_data or "")
        except ValueError:
            return False
        tags = body.get("tagged_users") if isinstance(body, dict) else None
        if not isinstance(tags, list) or not tags or COTAG_EXTRA in tags:
            return False
        planted.append({"method": "POST", "path": "/api/of/v2/posts", "tagged_users": tags})
        route.continue_(post_data=json.dumps({**body, "tagged_users": [*tags, COTAG_EXTRA]}))
        return True
    return hook


def _dup_ids(of, path, query, body) -> bool:
    ids = [m for m in (body.get("mediaFiles") if isinstance(body, dict) else None) or [] if isinstance(m, int)]
    return len(set(ids)) < len(ids)


@dataclass(frozen=True)
class Fault:
    method: str
    path_rx: re.Pattern
    action: Callable
    when: Callable | None = None
    tagged_too: bool = False
    after: int = 0


@dataclass(frozen=True)
class AppFault:
    hook: Callable
    seed: Callable | None = None


FAULTS = {
    "delete-500": Fault("DELETE", re.compile(r"^/api2/v2/(lists|posts)/\d+$"), status(500)),
    "lost-reply": Fault("POST", re.compile(r"^/api2/v2/(vault/)?lists$|^/api2/v2/trials$|^/api2/v2/posts$"),
                        applied_then(None), when=_lost_reply_target),
    "cdn-src": Fault("GET", re.compile(r"^/api2/v2/vault/media$"), rewrite(_cdn_src)),
    "trial-delete-500": Fault("DELETE", re.compile(r"^/api2/v2/trials/\d+$"), status(500)),
    "tip-filter": Fault("GET", re.compile(r"^/api2/v2/users/notifications$"), rewrite(_planted(_plant_tip)),
                        when=lambda of, path, query, body: "type=tip" in query.split("&")),
    "strip-miss": Fault("GET", re.compile(r"^/api2/v2/stories$"), rewrite(_planted(_plant_strip))),
    "highlight-field": Fault("GET", re.compile(r"^/api2/v2/users/\d+/stories/highlights$"),
                             rewrite(_planted(_plant_highlight))),
    "payout-field": Fault("GET", re.compile(r"^/api2/v2/payouts/requests$"), rewrite(_planted(_plant_payout))),
    "no-stored-order": Fault("GET", re.compile(r"^/api2/v2/vault/lists$"), rewrite(_drop_stored_order),
                             tagged_too=True),
    "sort-restore-500": Fault("POST", re.compile(r"^/api2/v2/vault/lists/sort$"), status(500), after=1),
    "audience-list": Fault("GET", re.compile(r"^/api2/v2/messages/queue/\d+$"), rewrite(_audience("userLists", "fans")),
                           tagged_too=True),
    "audience-second": Fault("GET", re.compile(r"^/api2/v2/messages/queue/\d+$"),
                             rewrite(_audience("userIds", str(fan_id(2)))), tagged_too=True),
    "unsend-refused": Fault("DELETE", re.compile(r"^/api2/v2/messages/queue/\d+$"),
                            status(400, "fault: unsend refused"),
                            when=lambda of, path, query, body: _queue.released(of, int(path.rsplit("/", 1)[1]))),
    "dup-id-refused": Fault("POST", re.compile(r"^/api2/v2/posts$"), status(400, "fault: duplicate media id"),
                            when=_dup_ids),
    "post-commit-500": Fault("POST", re.compile(r"^/api2/v2/posts$"), applied_then(500)),
    "queue-500-foreign": Fault("POST", re.compile(r"^/api2/v2/messages/queue$"), _queue_foreign),
    "rename-ignored": Fault("PATCH", re.compile(r"^/api2/v2/vault/lists/\d+$"), _rename_ignored),
    "composer-once": AppFault(composer_once),
    "publish-other": AppFault(publish_other, seed=_seed_owner_post),
    "post-lost-hidden": Fault("POST", re.compile(r"^/api2/v2/posts$"), applied_then(None), when=_holds_hidden),
    "hidden-refused": Fault("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$"), status(400, "fault: hidden media"),
                            when=_publishes_hidden),
    "publish-lost": Fault("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$"), applied_then(None)),
    "publish-500": Fault("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$"), applied_then(500)),
    "unsend-delete-500": Fault("DELETE", re.compile(r"^/api2/v2/messages/\d+$"), status(500)),
}
FAULTS["cotag-extra"] = AppFault(cotag_extra)
DROPS = {"post-drop-label": ("labelIds",), "post-drop-expiry": ("expireDays",),
         "post-drop-target": ("fundRaisingTargetAmount", "fundRaisingTipsPresets")}
FAULTS.update({name: Fault("POST", re.compile(r"^/api2/v2/posts$"), drop_fields(keys)) for name, keys in DROPS.items()})
STATES = {"email-off": (fake_settings.email_off, "settings--email-update-frequency")}


def start_state_problems(name: str, parked) -> list:
    pid = STATES[name][1]
    return [] if any(p.get("proof") == pid for p in parked) else [f"start state {name}: {pid} did not park"]


class Recorder:

    def __init__(self, app, fault: str | None = None, of=None):
        if fault is not None and not isinstance(FAULTS.get(fault), Fault):
            known = sorted(k for k, f in FAULTS.items() if isinstance(f, Fault))
            raise ValueError(f"unknown FakeOF fault {fault!r}; known: {known}")
        self.app = app
        self.fault = FAULTS.get(fault) if fault else None
        self.fault_name = fault
        self.of = of
        self.hits: list[dict] = []
        self._lock = threading.Lock()
        self._let_through = self.fault.after if self.fault else 0

    def _fires(self, hit) -> bool:
        f = self.fault
        if f is None or hit["method"] != f.method or not f.path_rx.match(hit["path"]):
            return False
        if hit["tagged"] and not f.tagged_too:
            return False
        if f.when is not None and not f.when(self.of, hit["path"], hit["query"], hit["body"]):
            return False
        if self._let_through > 0:
            self._let_through -= 1
            return False
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, more = [], True
        while more:
            msg = await receive()
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        raw = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        body = log_body(raw) if raw else None
        hit = {"t": time.time(), "method": scope["method"], "path": scope["path"],
               "query": redact_query(scope.get("query_string", b"").decode()), "body": body, "tagged": TAG in headers,
               "status": None}

        async def record(msg):
            if msg["type"] == "http.response.start":
                hit["status"] = msg["status"]
            await send(msg)

        try:
            if self._fires(hit):
                hit["fault"] = self.fault_name
                await self.fault.action(self.app, scope, replay, send, hit)
            else:
                await self.app(scope, replay, record)
        finally:
            with self._lock:
                self.hits.append(hit)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.hits)


def creator_id(seed: int = 1) -> str:
    return str(World(seed).creator_id)


class Fake:

    def __init__(self, seed: int = 1, fault: str | None = None):
        self.of = FakeOF(World(seed))
        priced_performer(self.of)
        if fault in STATES:
            STATES[fault][0](self.of)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(128)
        self.of.port = self.sock.getsockname()[1]
        self.recorder = Recorder(self.of.build(), None if fault in STATES else fault, self.of)
        self.server = uvicorn.Server(uvicorn.Config(self.recorder, log_level="error", lifespan="off",
                                                    http="h11", ws="websockets"))
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve(sockets=[self.sock])),
                                       name="fake-of", daemon=True)

    @property
    def origin(self) -> str:
        return self.of.origin

    def start(self, timeout: float = 10.0) -> None:
        self.thread.start()
        t = time.time() + timeout
        while not self.server.started:
            if time.time() > t:
                raise RuntimeError("FakeOF did not start")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def signed_headers(self, path_qs: str) -> dict:
        t = str(int(time.time() * 1000))
        uid = str(self.of.world.creator_id)
        return {"user-id": uid, "x-hash": self.of.x_hash, "time": t,
                "sign": sign_value(self.of.rules, time_ms=t, path_qs=path_qs, user_id=uid), TAG: "1"}
