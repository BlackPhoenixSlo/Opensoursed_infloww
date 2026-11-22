"""FakeOF (soak/fake_of, ADR 0024) for a fake-mode Live proof run, unchanged but for its priced /users/me (ticket 62),
behind a recorder.

Every request the fake answers is recorded in order: method, path, query, JSON body, status and whether it was the
driver's own tagged read (header `x-oi-proof-read`, story 12: the before / after / after-undo reads are told apart
from the app's). Serves on a loopback socket in a daemon thread.

Faults (`--fault`, the harness's failure paths, ticket 05), on the targeted proof's untagged requests only:
  delete-500   `DELETE /api2/v2/lists/{id}` or `/api2/v2/posts/{id}` answered 500 without deleting: the undo fails, the
               list or post stays (ofm-not-yet ticket 101: posts too, so a Phase 6 run stops on the first post undo).
  lost-reply   a create (`POST /api2/v2/lists`, `/api2/v2/vault/lists` or `/api2/v2/trials`, or ofm-not-yet ticket
               98's immediate Co-tagged `POST /api2/v2/posts`: no `isScheduled`, a non-empty `rfTag`) applied (the
               list, folder, trial link or post is made), then the connection is dropped with no reply.
  cdn-src      `GET /api2/v2/vault/media` answered with its first item's `_thumb` (the tile src) set to its CDN url:
               a tile that would load straight from a CDN host (vault--thumbnails must fail).
  trial-delete-500  `DELETE /api2/v2/trials/{id}` answered 500 without deleting (Phase 3 ticket 64: trial Create
               link's undo fails, the link stays).
  rename-ignored  `PATCH /api2/v2/vault/lists/{id}` answered 200 with the folder's id and the asked name, not applied
               (ofm-not-yet ticket 34: the folder keeps its name, so vault.more.rename
               fails at settle; the undo still runs).
  post-drop-label, post-drop-expiry, post-drop-target  `POST /api2/v2/posts` stored without its `labelIds`, its
               `expireDays`, or its `fundRaisingTargetAmount` + `fundRaisingTipsPresets`, answered 200 with that post
               (ofm-not-yet ticket 35: a 2xx that drops a field, so p2.post-labels-expiry-target's read-back fails).
  tip-filter   `GET /api2/v2/users/notifications?type=tip` answered with a non-tip row added (notifications--tips must fail).
  strip-miss   `GET /api2/v2/stories` answered without its first creator, whom OnlyFans's own strip read still shows
               (home--story-strip must fail).
  highlight-field  `GET /api2/v2/users/{id}/stories/highlights` answered with the first highlight's `cover` dropped
               (profile--highlights must fail).
  payout-field `GET /api2/v2/payouts/requests` answered with every row's `invoiceId` dropped (statements--payout-rows
               must fail).
  no-stored-order  `GET /api2/v2/vault/lists` answered without its `sort` and `order` and in the default folder order,
               the driver's own tagged read included: OnlyFans not returning the stored custom order
               (vault--customize-order-save must park, never Save).
  sort-restore-500 `POST /api2/v2/vault/lists/sort` answered 500 without applying it, after the first one (the Save)
               went through: the order restore fails (the run stops on its FAILED row).
  audience-list    `GET /api2/v2/messages/queue/{id}` (the queued item's own read, the driver's own tagged read
                   included) answered with a list in `userLists` (queue--send-message-right-now must stop before
                   Send now).
  audience-second  the same read answered with a second Fan in `userIds` (the same stop).
  unsend-refused   `DELETE /api2/v2/messages/queue/{id}` of a released item answered 400 without unsending (the
                   chat-message unsend fallback must run); a still-queued item's cancel is answered as usual.
  dup-id-refused   `POST /api2/v2/posts` whose `mediaFiles` holds one vault id twice answered 400 without posting
                   (new-post--dedupe-duplicate-id must fail with the refusal recorded; new-post--upload passes); any
                   other post is answered as usual (ticket 97).
  post-commit-500  `POST /api2/v2/posts` applied (the post is made), then answered 500: OnlyFans committing before a
                   5xx, so the driver's finder must find the post and delete it, or close the row FAILED (ticket 97).
  queue-500-foreign  `POST /api2/v2/messages/queue` answered 500 unapplied while another user's message (its own text,
                   to a second Fan) is queued instead: a lost reply whose after-write read shows one new queued item
                   that is not the run's, so the Relay's read-back must refuse it and the undo never touch it (ticket
                   100 review).
  composer-once    app side, FakeOF unchanged (`AppFault`: a route hook prove.py's app browser runs): the app's
                   `POST /api/of/v2/posts` sent with each media id once (new-post--dedupe-duplicate-id's body
                   assertion must fail; ticket 97).
  publish-other    app side (`AppFault`), FakeOF seeded with the owner's own scheduled post (`_seed_owner_post`): the
                   app's `PUT /api/of/v2/schedules/{id}/publish` sent with that post's schedule id instead
                   (queue--publish-now must fail on the guard's refusal, FakeOF receiving no publish; ticket 99).
  cotag-extra      app side (`AppFault`, ofm-not-yet ticket 98): the app's `POST /api/of/v2/posts` sent with a second
                   creator (COTAG_EXTRA) added to its `tagged_users`: the guard refuses the post (proof_core
                   `cotag_refusal`), FakeOF sees no create, the Co-tag proof fails.
  post-lost-hidden `POST /api2/v2/posts` holding a hidden vault id applied (the post is made), then the connection is
                   dropped with no reply (queue--publish-now's post D: found by the Relay's read-back and undone).
  hidden-refused   `PUT /api2/v2/schedules/{id}/publish` of a scheduled post holding a hidden medium answered 400
                   unpublished (queue--publish-now records the refusal, then re-runs on a fresh visible upload).
  publish-lost     `PUT /api2/v2/schedules/{id}/publish` applied (the post is published), then the connection is
                   dropped with no reply; publish-500 the same answered 500: queue--publish-now must fail unretried,
                   its post found by its marker through the Relay's strict read-back (`/__proof/found`) and deleted.
  unsend-delete-500  `DELETE /api2/v2/messages/{id}` answered 500 without unsending (ofm-not-yet ticket 33: Unsend
               PPV's unsend fails, the app shows its red note, the message stays and the proof fails).

Start states (`--fault`, the account as FakeOF starts it; no request is faulted, STATES): the run passes only when
the named proof parks (prove.py replaces "fault never fired" with that check).
  email-off    Email notifications and New Likes Summary off, as the live Proof Creator's (ticket 60,
               soak/fake_of/settings.py `email_off`): settings--email-update-frequency must park.
"""
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

PROOF_FAN = fan_id(1)   # the Proof fan a fake run arms with (a FakeOF fan, never a real one)

TAG = "x-oi-proof-read"
_ERR = b'{"error":{"code":%d,"message":"%s"}}'


def composer_once(planted: list):
    """Ticket 97's planted composer: a route hook (True when it answered the route) sending the app's
    `POST /api/of/v2/posts` with each media id once (`dedupe_media`); each time it fires is appended to `planted`."""
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


# ticket 60: start states, applied when the fake starts: (start(fake), the proof id that must park)
STATES = {"email-off": (fake_settings.email_off, "settings--email-update-frequency")}


def start_state_problems(name: str, parked) -> list:
    """A start state's run-level check, in place of "fault never fired": its named proof is in the report's
    `parked`, or a harness problem."""
    pid = STATES[name][1]
    return [] if any(p.get("proof") == pid for p in parked) else [f"start state {name}: {pid} did not park"]


OWNER_POST_TEXT = "Owner's scheduled post"   # publish-other's queued post, not the run's


def publish_other(planted: list):
    """Ticket 99's planted Publish now: a route hook sending the app's `PUT /api/of/v2/schedules/{id}/publish` with
    the owner's own scheduled post's schedule id (`_seed_owner_post`); each time it fires is appended to `planted`."""
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
    """publish-other: the owner's own post, scheduled 3 h ahead, queued before the run (post 1)."""
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
    """Close the client's connection with no reply at all (curl: empty reply). uvicorn's h11 cycle hands the app its
    bound `send`, whose cycle owns the transport; waiting for connection_lost keeps uvicorn from answering 500.
    False when no disconnect was seen (then uvicorn may still answer 500, a normal reply): the caller marks the hit so
    the run fails loudly instead of passing on a fault that never fired."""
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


# ── actions: `async (app, scope, receive, send, hit)`, `hit["fault"]` already set to the fault's name ──

async def _answer(send, hit, code: int, body: bytes) -> None:
    hit["status"] = code
    await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


def status(code: int, msg: str = "fault"):
    """Answer `code` with OnlyFans's error shape; FakeOF never sees the request (nothing applied)."""
    async def act(app, scope, receive, send, hit):
        await _answer(send, hit, code, _ERR % (0 if code < 500 else code, msg.encode()))
    return act


def rewrite(change):
    """FakeOF's JSON answer passed through `change(data, hit) -> data` (Content-Length fixed)."""
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
    """FakeOF applies the write, then its answer never leaves: answered `code` instead, or (None) the connection is
    dropped with no reply."""
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
    """ofm-not-yet ticket 35: FakeOF stores the post from the body without `keys` and answers as usual (a 2xx that
    drops a field); a body holding none of them marks the hit (the fault did not fire as designed)."""
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
    """rename-ignored (ofm-not-yet ticket 34): answered 200 with the folder's id and the asked name; FakeOF never sees
    it, so the folder keeps its name."""
    try:
        body = json.loads((await receive()).get("body") or b"null")
    except ValueError:
        body = None
    name = body.get("name") if isinstance(body, dict) else None
    await _answer(send, hit, 200, json.dumps({"id": int(scope["path"].rsplit("/", 1)[1]), "type": "custom",
                                              "name": name}).encode())


FOREIGN_QUEUE_TEXT = "Weekend special for my favourites"   # queue-500-foreign's other user's message


async def _queue_foreign(app, scope, receive, send, hit):
    """queue-500-foreign: FakeOF queues another user's message (FOREIGN_QUEUE_TEXT, to a second Fan, the run's own
    scheduled date) in place of the run's, then the answer is 500."""
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


# ── rewrite changes ──

def _cdn_src(data, hit):
    """cdn-src: the first item's `_thumb` (the tile src) set to its CDN thumb url."""
    items = data.get("list") or []
    if items:
        items[0]["_thumb"] = items[0]["files"]["thumb"]["url"]
    else:
        hit["fault"] = "cdn-src: no item to plant"
    return data


def _planted(plant):
    """Ticket 95: a plant (in place; None once planted, else why it could not) as a change: a plant that could not
    plant marks the hit why (the run then fails on a fault that did not fire as designed)."""
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
    """Ticket 100: a change adding `value` to the queued item's `field`."""
    def change(data, hit):
        if isinstance(data, dict) and "id" in data:
            data[field] = [*(data.get(field) or []), value]
        else:
            hit["fault"] = f"{hit['fault']}: no queued item to plant"
        return data
    return change


def _drop_stored_order(data: dict, hit) -> dict:
    """no-stored-order: the vault folder read without `sort`/`order`, its folders in the default order."""
    from soak.fake_of import render
    from soak.fake_of.vault import _rows
    at = {r["id"]: k for k, r in enumerate(_rows(render._tpl("vault-lists.json")))}
    data.pop("sort", None)
    data.pop("order", None)
    data["list"] = sorted(data.get("list") or [], key=lambda r: at.get(r.get("id"), len(at)))
    return data


# ofm-not-yet ticket 98: the Co-tag proofs' partner (a fake run's run input, prove.py `--cotag-partner`), the creator
# cotag-extra plants beside it (both from new-post-tags.json, FakeOF's taggable creators), and the faults' predicates.
COTAG_PARTNER = 2001
COTAG_EXTRA = 2002


def _lost_reply_target(of, path, query, body) -> bool:
    """lost-reply's predicate: every list, folder or trial create; a post create only when immediate (no
    `isScheduled`) and Co-tagged (a non-empty `rfTag`), the Co-tag immediate proof's."""
    if path != "/api2/v2/posts":
        return True
    return isinstance(body, dict) and not body.get("isScheduled") and bool(body.get("rfTag"))


def cotag_extra(planted: list):
    """Ticket 98's planted composer: a route hook sending the app's `POST /api/of/v2/posts` that names Co-tags with
    COTAG_EXTRA added to its `tagged_users`; each time it fires is appended to `planted`."""
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
    """One planted FakeOF fault: its untagged `method` request on a path matching `path_rx` (the driver's own tagged
    read too when `tagged_too`) where `when(FakeOF, path, query, body)` holds, past its first `after` such requests,
    is answered by `action(app, scope, receive, send, hit)`."""
    method: str
    path_rx: re.Pattern
    action: Callable
    when: Callable | None = None
    tagged_too: bool = False
    after: int = 0


@dataclass(frozen=True)
class AppFault:
    """One planted app-side fault: `hook(planted)` -> the route hook the app browser runs (of_browser.py
    `AppBrowser`); FakeOF runs unfaulted, `seed(FakeOF)` (ticket 99) given its state before it starts."""
    hook: Callable
    seed: Callable | None = None


FAULTS = {
    "delete-500": Fault("DELETE", re.compile(r"^/api2/v2/(lists|posts)/\d+$"), status(500)),   # posts: ticket 101
    "lost-reply": Fault("POST", re.compile(r"^/api2/v2/(vault/)?lists$|^/api2/v2/trials$|^/api2/v2/posts$"),
                        applied_then(None), when=_lost_reply_target),
    "cdn-src": Fault("GET", re.compile(r"^/api2/v2/vault/media$"), rewrite(_cdn_src)),   # ticket 94
    "trial-delete-500": Fault("DELETE", re.compile(r"^/api2/v2/trials/\d+$"), status(500)),   # ticket 64
    # ticket 95
    "tip-filter": Fault("GET", re.compile(r"^/api2/v2/users/notifications$"), rewrite(_planted(_plant_tip)),
                        when=lambda of, path, query, body: "type=tip" in query.split("&")),
    "strip-miss": Fault("GET", re.compile(r"^/api2/v2/stories$"), rewrite(_planted(_plant_strip))),
    "highlight-field": Fault("GET", re.compile(r"^/api2/v2/users/\d+/stories/highlights$"),
                             rewrite(_planted(_plant_highlight))),
    "payout-field": Fault("GET", re.compile(r"^/api2/v2/payouts/requests$"), rewrite(_planted(_plant_payout))),
    # ticket 96
    "no-stored-order": Fault("GET", re.compile(r"^/api2/v2/vault/lists$"), rewrite(_drop_stored_order),
                             tagged_too=True),
    "sort-restore-500": Fault("POST", re.compile(r"^/api2/v2/vault/lists/sort$"), status(500), after=1),
    # ticket 100
    "audience-list": Fault("GET", re.compile(r"^/api2/v2/messages/queue/\d+$"), rewrite(_audience("userLists", "fans")),
                           tagged_too=True),
    "audience-second": Fault("GET", re.compile(r"^/api2/v2/messages/queue/\d+$"),
                             rewrite(_audience("userIds", str(fan_id(2)))), tagged_too=True),
    "unsend-refused": Fault("DELETE", re.compile(r"^/api2/v2/messages/queue/\d+$"),
                            status(400, "fault: unsend refused"),
                            when=lambda of, path, query, body: _queue.released(of, int(path.rsplit("/", 1)[1]))),
    # ticket 97
    "dup-id-refused": Fault("POST", re.compile(r"^/api2/v2/posts$"), status(400, "fault: duplicate media id"),
                            when=_dup_ids),
    "post-commit-500": Fault("POST", re.compile(r"^/api2/v2/posts$"), applied_then(500)),
    "queue-500-foreign": Fault("POST", re.compile(r"^/api2/v2/messages/queue$"), _queue_foreign),   # ticket 100 review
    "rename-ignored": Fault("PATCH", re.compile(r"^/api2/v2/vault/lists/\d+$"), _rename_ignored),   # ofm-not-yet 34
    "composer-once": AppFault(composer_once),
    # ticket 99
    "publish-other": AppFault(publish_other, seed=_seed_owner_post),
    "post-lost-hidden": Fault("POST", re.compile(r"^/api2/v2/posts$"), applied_then(None), when=_holds_hidden),
    "hidden-refused": Fault("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$"), status(400, "fault: hidden media"),
                            when=_publishes_hidden),
    "publish-lost": Fault("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$"), applied_then(None)),
    "publish-500": Fault("PUT", re.compile(r"^/api2/v2/schedules/\d+/publish$"), applied_then(500)),
    # ofm-not-yet ticket 33
    "unsend-delete-500": Fault("DELETE", re.compile(r"^/api2/v2/messages/\d+$"), status(500)),
}
FAULTS["cotag-extra"] = AppFault(cotag_extra)   # ofm-not-yet ticket 98
# ofm-not-yet ticket 35: each drops its body keys before FakeOF stores the post
DROPS = {"post-drop-label": ("labelIds",), "post-drop-expiry": ("expireDays",),
         "post-drop-target": ("fundRaisingTargetAmount", "fundRaisingTipsPresets")}
FAULTS.update({name: Fault("POST", re.compile(r"^/api2/v2/posts$"), drop_fields(keys)) for name, keys in DROPS.items()})
# ticket 60: start states, applied when the fake starts: (start(fake), the proof id that must park)
STATES = {"email-off": (fake_settings.email_off, "settings--email-update-frequency")}


def start_state_problems(name: str, parked) -> list:
    """A start state's run-level check, in place of "fault never fired": its named proof is in the report's
    `parked`, or a harness problem."""
    pid = STATES[name][1]
    return [] if any(p.get("proof") == pid for p in parked) else [f"start state {name}: {pid} did not park"]


class Recorder:
    """ASGI wrapper: buffers the request body (then replays it), records the answer's status, applies `fault`."""

    def __init__(self, app, fault: str | None = None, of=None):
        if fault is not None and not isinstance(FAULTS.get(fault), Fault):
            known = sorted(k for k, f in FAULTS.items() if isinstance(f, Fault))
            raise ValueError(f"unknown FakeOF fault {fault!r}; known: {known}")
        self.app = app
        self.fault = FAULTS.get(fault) if fault else None
        self.fault_name = fault
        self.of = of   # ticket 100: the FakeOF a fault's predicate reads
        self.hits: list[dict] = []
        self._lock = threading.Lock()
        self._let_through = self.fault.after if self.fault else 0   # ticket 96

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
        body = log_body(raw) if raw else None   # a binary upload by its length only (ticket 53)
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
    """The Creator a `Fake(seed)` serves, known before it starts (the run lock is keyed by it)."""
    return str(World(seed).creator_id)


class Fake:
    """One FakeOF on 127.0.0.1:<free port>, seeded (soak/world.py: `Soak list 1`, `Soak list 2` among its lists)."""

    def __init__(self, seed: int = 1, fault: str | None = None):
        self.of = FakeOF(World(seed))
        priced_performer(self.of)   # ticket 62: /users/me as the Proof Creator was measured, a priced performer
        if fault in STATES:   # a start state faults no request
            STATES[fault][0](self.of)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(128)
        self.of.port = self.sock.getsockname()[1]
        self.recorder = Recorder(self.of.build(), None if fault in STATES else fault, self.of)
        # h11, not httptools: curl_cffi's chrome profile sends `Upgrade: h2c` on plain http (soak/runner.py)
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
        """The headers a signed read of `path_qs` needs, tagged as the driver's own read."""
        t = str(int(time.time() * 1000))
        uid = str(self.of.world.creator_id)
        return {"user-id": uid, "x-hash": self.of.x_hash, "time": t,
                "sign": sign_value(self.of.rules, time_ms=t, path_qs=path_qs, user_id=uid), TAG: "1"}
