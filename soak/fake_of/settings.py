"""Settings surface of the fake OnlyFans (Phase 3 ticket 60: the settings switches' fake-mode proofs).

Mounted from app.py right after automations' gate rows (so its fault knobs still apply), ahead of every other row:
  GET    /users/me/settings                      the settings blob (service/of_reads.py `my_settings`)
  PATCH  /users/me/settings/security             the security-section keys (server.py `_SECURITY_PATCH_KEYS`)
  PATCH  /users/me                               profile keys that live in the settings blob, Edit profile's
                                                 `avatar`/`header`/`about` (tickets 67, 68: `profile`), then
                                                 automations' `_me`, whose GET and PATCH replies carry `profile`'s
  GET    /users/settings/notifications/{t}       flat items; groups with ?group=1 (of_reads `notification_settings`)
  PATCH  /users/settings/notifications           `{notifications: {t: [{code, value}]}}`, the app's own body
                                                 (ofMirrorSettingsWrites)
  PUT    /users/me/settings/security             ticket 66: Block by country's `{blockedCountries, blockedStates}` and
                                                 Block by IP's `{blockedIps}` (the Relay's own routes; whole lists)
  GET    /countries                              ticket 66: Block by country's picker list, the fake's own (COUNTRIES)

Edit profile (tickets 67, 68): `avatar`/`header` take a convert item `{processId, ...}` (stores its picture) or `""`
(clears it); `about` (a string) is stored as sent. The account starts with a cover (`PRIOR_COVER`) and no avatar, as the
Proof Creator (a cover, measured 2026-11-21), so the cover proof's undo must upload it again: each upload's item names a
new picture, so the URL changes, and `/cdn` serves each picture's own picture (PRIOR_COVER_PNG, else what the upload
behind its processId stored: posts.py `converted`), so the undo's picture check means something here; `about` reads as
the fixture's own bio until a PATCH stores one. As live OF (ticket 67 follow-up, measured 2026-11-21: the header URL
changed again after the restore; its bytes were a re-encode), a saved upload shows only `STALE_S` seconds after the
PATCH (the previous picture until then, the PATCH reply included) and `/cdn` serves it re-encoded (`reencode`: other
bytes, the same pixels); a remove (`""`) applies at once. A stored picture is
`https://<vault.CDN_HOST>/files/soak/profile/<processId>.png`: the Relay's `/img` fetches it from this fake's `/cdn`,
as the vault's. The upload before the PATCH (signed/create, the storage PUT, the convert claim) is posts.py's.

Shapes start from the captured fixtures settings-settings.json and settings-notifications-*.json
(app/lib/__fixtures__/of). Every write is logged with its body and applied before the response, so the next read
reflects it. The write replies are the fake's own (no capture of OF's): the settings blob, and the transport's groups.
"""
from __future__ import annotations

import copy
import json
import re
import struct
import time
import zlib
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from soak.fake_of import posts, render, vault

_STATE = "_soak_settings"
# The fake account has New Likes Summary on at 12 hours, so Update frequency's menu (the stored hours and the default
# 24, ofMirrorSettingsWrites frequencyChoices) holds a change; the capture has it off. A live run needs the same: the
# digest on at hours other than 24 (scripts/of-live-proof/proofs/phase3.py FREQUENCY).
DIGEST = "new_likes_digest"
DIGEST_HOURS = 12
# OnlyFans draws the email list and the select only with the master Email notifications switch on (sitting 2026-11-21,
# settings-email.js); the capture has it off, so the fake account starts with it on, beside the digest.
EMAIL_MASTER = "isEmailNotificationsEnabled"
# ticket 66: the fake's own country list (no capture of OF's GET /countries?all=1 reply; its record names `code` and
# `name`, ISO-2 codes a guess). Tuvalu is the proofs' harmless pick (scripts/of-live-proof/proofs/phase3.py); live OF lists it, not Antarctica.
COUNTRIES = [{"id": i, "code": code, "name": name} for i, (code, name) in enumerate((
    ("BV", "Bouvet Island"), ("DE", "Germany"), ("GB", "United Kingdom"), ("TV", "Tuvalu"),
    ("US", "United States of America")), 1)]


def _state(fake) -> dict[str, Any]:
    st = fake.__dict__.get(_STATE)
    if st is None:
        st = fake.__dict__[_STATE] = {"settings": copy.deepcopy(render.fixture("settings-settings.json")),
                                      "notifications": {},
                                      "profile": {"avatar": None, "header": picture_url(PRIOR_COVER), "about": None,
                                                  "pending": {}}}
        st["settings"][EMAIL_MASTER] = True
    return st


def email_off(fake) -> None:
    """ticket 60: start the account as the live Proof Creator's (sitting 2026-11-21): Email notifications and New Likes
    Summary both off, as captured. scripts/of-live-proof/fake_layer.py `--fault email-off`."""
    settings(fake)[EMAIL_MASTER] = False
    for x in _items(notifications(fake, "email") or []):
        if x.get("code") == DIGEST:
            x.update(isEnabled=False, value=0)


def settings(fake) -> dict[str, Any]:
    return _state(fake)["settings"]


# tickets 67, 68
PICTURES = ("avatar", "header")
PRIOR_COVER = "soak-prior-cover"   # the account's cover before any proof (a processId no upload answers)
PRIOR_COVER_PNG = vault._png(12)   # its bytes: fixed, served as they are (never re-encoded: no upload stored them)
_PROFILE_FILE = re.compile(r"/cdn/files/soak/profile/([^/]+)\.png")
# ASSUMPTION: 3 s, under the driver's 6 s quiet wait before its after-write read (so the write's own cover shows by
# then) and under its 60 s after-undo wait (so the restore is waited out, not missed); live's delay is not measured.
STALE_S = 3.0
_clock = time.monotonic   # tests set it
_NOTE = b"soak re-encode"


def reencode(data: bytes) -> bytes:
    """The picture `data` as OF serves a saved upload: other bytes, the same pixels (a PNG gains a tEXt chunk after its
    IHDR, a JPEG a comment after its SOI); any other bytes as they are."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        body = b"tEXt" + b"Comment\x00" + _NOTE
        chunk = struct.pack(">I", len(body) - 4) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return data[:33] + chunk + data[33:]
    if data.startswith(b"\xff\xd8"):
        return data[:2] + b"\xff\xfe" + struct.pack(">H", len(_NOTE) + 2) + _NOTE + data[2:]
    return data


def picture_url(process_id: str) -> str:
    return f"https://{vault.CDN_HOST}/files/soak/profile/{process_id}.png"


async def cdn(fake, req: Request) -> Response:
    """The fake's /cdn: a profile picture as its bytes (PRIOR_COVER_PNG, or what the upload behind its processId
    stored; unknown: 404), anything else the vault's placeholder."""
    m = _PROFILE_FILE.fullmatch(req.url.path)
    if m is None:
        return await vault.cdn(fake, req)
    data = PRIOR_COVER_PNG if m[1] == PRIOR_COVER else posts.converted(fake).get(m[1])
    if data is not None and m[1] != PRIOR_COVER:
        data = reencode(data)
    if data is None:
        fake._log(req, 404, True)
        return Response(b"", status_code=404)
    fake._log(req, 200, True)
    kind = ("image/jpeg" if data.startswith(b"\xff\xd8") else "image/gif" if data.startswith(b"GIF8")
            else "image/webp" if data[8:12] == b"WEBP" else "image/png")
    return Response(data, media_type=kind)


def profile_overlay(fake, d: dict[str, Any]) -> dict[str, Any]:
    """The profile `d` (automations' `_me`) with Edit profile's stored pictures, and `about` once a PATCH stored one."""
    st = _state(fake)["profile"]
    for k, (url, due) in list(st["pending"].items()):   # a saved upload shows STALE_S after its PATCH
        if _clock() >= due:
            st[k] = url
            del st["pending"][k]
    d.update({k: st[k] for k in PICTURES})
    if st["about"] is not None:
        d["about"] = st["about"]
    return d


def notifications(fake, transport: str) -> list[dict[str, Any]] | None:
    st = _state(fake)["notifications"]
    if transport not in st:
        try:
            st[transport] = copy.deepcopy(render.fixture(f"settings-notifications-{transport}.json"))
        except FileNotFoundError:
            return None
        if transport == "email":
            for x in _items(st[transport]):
                if x.get("code") == DIGEST:
                    x.update(isEnabled=True, value=DIGEST_HOURS)
    return st[transport]


def _items(groups: list[dict[str, Any]]):
    for g in groups:
        yield from g.get("items") or []


async def _body(req: Request) -> Any:
    raw = await req.body()
    return json.loads(raw) if raw else {}


async def _get_settings(fake, req: Request, ok) -> Response:
    return ok(req, settings(fake))


async def _patch_security(fake, req: Request, ok) -> Response:
    body = await _body(req)
    if isinstance(body, dict):
        settings(fake).update(body)
    fake._log(req, 200, True, body)
    return JSONResponse(settings(fake))


# ticket 66
async def _put_security(fake, req: Request, ok) -> Response:
    return await _patch_security(fake, req, ok)   # the same apply, log and reply: the lists replace the stored ones


async def _get_countries(fake, req: Request, ok) -> Response:
    return ok(req, COUNTRIES)


async def _patch_me(fake, req: Request, ok) -> Response:
    from soak.fake_of import automations
    body = await _body(req)
    s = settings(fake)
    if isinstance(body, dict):
        s.update({k: v for k, v in body.items() if k in s})
        prof = _state(fake)["profile"]
        for k in PICTURES:
            v = body.get(k)
            if v == "":
                prof[k] = None
                prof["pending"].pop(k, None)
            elif isinstance(v, dict) and v.get("processId"):
                prof["pending"][k] = (picture_url(str(v["processId"])), _clock() + STALE_S)
        if isinstance(body.get("about"), str):
            prof["about"] = body["about"]
    return await automations._me(fake, req, ok)   # logs the PATCH and answers the profile (Starlette caches the body)


async def _get_notifications(fake, req: Request, ok, transport: str) -> Response:
    groups = notifications(fake, transport)
    if groups is None:
        fake._log(req, 404, False)
        return JSONResponse({"error": {"code": 0, "message": "Not found (soak fake: unmodelled)"}}, status_code=404)
    # OF groups only with ?group=1; bare, it answers the flat item list (measured live 2026-11-21)
    return ok(req, groups if req.query_params.get("group") == "1" else list(_items(groups)))


async def _patch_notifications(fake, req: Request, ok) -> Response:
    body = await _body(req)
    out: dict[str, Any] = {}
    for transport, items in ((body or {}).get("notifications") or {}).items():
        groups = notifications(fake, transport) or []
        for it in items or []:
            for x in _items(groups):
                if x.get("code") == it.get("code") and "value" in it:
                    # a switch sends true/false (email: its hours or 1 when on); the read keeps isEnabled + a number
                    v = it["value"]
                    x["isEnabled"] = bool(v)
                    x["value"] = v if type(v) in (int, float) else int(bool(v))
        out[transport] = groups
    fake._log(req, 200, True, body)
    return JSONResponse(out)


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/users/me/settings"), _get_settings),
    ("PATCH", re.compile(r"/api2/v2/users/me/settings/security"), _patch_security),
    ("PATCH", re.compile(r"/api2/v2/users/me"), _patch_me),
    ("GET", re.compile(r"/api2/v2/users/settings/notifications/([a-z]+)"), _get_notifications),
    ("PATCH", re.compile(r"/api2/v2/users/settings/notifications"), _patch_notifications),
    # ticket 66
    ("PUT", re.compile(r"/api2/v2/users/me/settings/security"), _put_security),
    ("GET", re.compile(r"/api2/v2/countries"), _get_countries),
]
