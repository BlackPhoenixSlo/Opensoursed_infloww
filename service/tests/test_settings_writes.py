#!/usr/bin/env python3
"""OF settings writes behind the OF Manager mirror's settings pages.

Each of_client method sends the body OF's own web client sends (build
202610091632, app.js module 202600, per-key routing in module 289051); each
relay route forwards it unchanged. Plain-assert, OF faked (no request leaves
the process).

  case_security_toggle_patches_the_section
  case_watermarks_save_puts_the_section
  case_notification_toggle_patches_notifications
  case_story_replies_patch_story
  case_empty_bodies_are_refused
  case_routes_forward_the_body
  case_users_me_writes_refuse_a_key_the_mirror_never_sends
  case_users_me_writes_forward_the_keys_the_mirror_sends
  case_the_allow_lists_match_the_keys_the_app_sends
  case_every_toggle_the_mirror_saves_to_users_me_is_a_profile_key
  case_story_route_takes_only_ofs_values

Run: ./venv/bin/python service/tests/test_settings_writes.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import re  # noqa: E402
from pathlib import Path  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

API = of_client.API_BASE


def _client():
    """An OFClient whose every request is recorded instead of sent."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"success": True}
    return c


def case_security_toggle_patches_the_section():
    c = _client()
    c.patch_security_settings({"isAutoFollowBack": True})
    assert c.sent == [("PATCH", f"{API}/users/me/settings/security",
                       {"json_body": {"isAutoFollowBack": True}})], c.sent


def case_watermarks_save_puts_the_section():
    c = _client()
    body = {"hasWatermarkPhoto": True, "hasWatermarkVideo": False, "watermarkPosition": "bottom_right"}
    c.put_security_settings(body)
    assert c.sent == [("PUT", f"{API}/users/me/settings/security", {"json_body": body})], c.sent


def case_notification_toggle_patches_notifications():
    c = _client()
    body = {"notifications": {"toast": [{"code": "new_tips", "value": False}]}}
    c.patch_notification_settings(body)
    c.patch_notification_settings({"isEmailNotificationsEnabled": False, "isMonthlyNewsletters": False})
    assert c.sent == [
        ("PATCH", f"{API}/users/settings/notifications", {"json_body": body}),
        ("PATCH", f"{API}/users/settings/notifications",
         {"json_body": {"isEmailNotificationsEnabled": False, "isMonthlyNewsletters": False}}),
    ], c.sent


def case_story_replies_patch_story():
    c = _client()
    c.patch_story_settings("nobody")
    assert c.sent == [("PATCH", f"{API}/users/settings/story",
                       {"json_body": {"allowReplyFrom": "nobody"}})], c.sent


def case_empty_bodies_are_refused():
    c = _client()
    for call in (c.patch_security_settings, c.put_security_settings, c.patch_notification_settings):
        try:
            call({})
        except ValueError:
            continue
        raise AssertionError(f"{call.__name__} sent an empty body")
    assert c.sent == [], c.sent
    for route in (server.of_patch_security_settings, server.of_put_security_settings,
                  server.of_patch_notification_settings):
        try:
            route({})
        except HTTPException as e:
            assert e.status_code == 422, e
            continue
        raise AssertionError(f"{route.__name__} forwarded an empty body")


def case_routes_forward_the_body():
    calls = []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a: calls.append((name, a)) or {"success": True}

    dropped = []
    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._get_client = lambda: _Fake()
    server._resolve_account_id = lambda _ctx: "acct-1"
    server.relay_cache.invalidate = lambda name, aid: dropped.append((name, aid))
    try:
        server.of_patch_security_settings({"showPostsTips": False})
        server.of_put_security_settings({"hasWatermarkPhoto": True, "watermarkPosition": "center"})
        server.of_patch_notification_settings({"notifications": {"email": [{"code": "new_tips", "value": 1}]}})
        server.of_patch_story_settings(server._StorySettingsBody(allowReplyFrom="subscribers"))
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    # every settings write may change /users/me/settings: its cached blob goes
    assert dropped == [("my_settings", "acct-1")] * 4, dropped
    assert calls == [
        ("patch_security_settings", ({"showPostsTips": False},)),
        ("put_security_settings", ({"hasWatermarkPhoto": True, "watermarkPosition": "center"},)),
        ("patch_notification_settings", ({"notifications": {"email": [{"code": "new_tips", "value": 1}]}},)),
        ("patch_story_settings", ("subscribers",)),
    ], calls
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for want in (("PATCH", "/api/of/v2/users/me/settings/security"),
                 ("PUT", "/api/of/v2/users/me/settings/security"),
                 ("PATCH", "/api/of/v2/users/settings/notifications"),
                 ("PATCH", "/api/of/v2/users/settings/story")):
        assert want in routes, f"{want} missing"


def _forwarded(fn) -> list:
    """Run `fn` with OF faked; the client calls it made."""
    calls = []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a, k)) or {"success": True}

    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._get_client = lambda: _Fake()
    server._resolve_account_id = lambda _ctx: "acct-1"
    server.relay_cache.invalidate = lambda *_a: None
    try:
        fn()
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    return calls


def case_users_me_writes_refuse_a_key_the_mirror_never_sends():
    """S3: each users/me write forwards only the keys the OF Manager mirror sends; any other key
    (an email, a password, a payout field…) is a 422 and nothing reaches OF."""
    for route, body in (
        (server.of_update_profile, {"about": "bio", "email": "x@example.invalid"}),
        (server.of_update_profile, {"isPrivate": True}),  # a security-section key, not a profile one
        (server.of_patch_security_settings, {"showPostsTips": True, "twoFactor": False}),
        (server.of_patch_security_settings, {"name": "not a security key"}),
        (server.of_put_security_settings, {"hasWatermarkPhoto": True, "about": "x"}),
    ):
        def _call(route=route, body=body):
            try:
                route(body)
            except HTTPException as e:
                assert e.status_code == 422 and "keys not allowed" in e.detail, e.detail
                return
            raise AssertionError(f"{route.__name__} forwarded {body}")
        assert _forwarded(_call) == [], route.__name__


def case_users_me_writes_forward_the_keys_the_mirror_sends():
    calls = _forwarded(lambda: (
        server.of_update_profile({"name": "N", "about": "A", "location": "L", "website": "W", "wishlist": "X"}),
        server.of_update_profile({"subscribePrice": 12.5}),
        server.of_update_profile({"isVisibleOnline": False}),
        server.of_patch_security_settings({"coStreamingRequestFrom": "friends"}),
        server.of_put_security_settings({"hasWatermarkPhoto": True, "hasWatermarkVideo": False,
                                         "watermarkText": "t", "watermarkPosition": "center"}),
    ))
    assert [c[0] for c in calls] == ["update_profile", "update_profile", "update_profile",
                                     "patch_security_settings", "put_security_settings"], calls
    assert calls[1][2] == {"subscribePrice": 12.5}, calls[1]


APP_LIB = Path(__file__).resolve().parents[2] / "app" / "lib"


def _ts_strings(src: str, start: str, end: str) -> set[str]:
    """The quoted strings between `start` and the next `end` in `src`."""
    body = src[src.index(start):]
    return set(re.findall(r'"([A-Za-z0-9_]+)"', body[:body.index(end)]))


def case_the_allow_lists_match_the_keys_the_app_sends():
    """The Relay's allow-lists follow the mirror: its SECURITY_KEYS are the security PATCH list, and
    ProfilePatch's fields are profile keys (a key added there without the Relay's list fails here)."""
    writes = (APP_LIB / "ofMirrorSettingsWrites.ts").read_text()
    profile = (APP_LIB / "ofMirrorWrites.ts").read_text()
    security = _ts_strings(writes, "export const SECURITY_KEYS", "]);")
    assert security == server._SECURITY_PATCH_KEYS, security ^ server._SECURITY_PATCH_KEYS
    profile_patch = _ts_strings(profile, "export type ProfilePatch", ">>;")
    assert profile_patch and profile_patch <= server._PROFILE_KEYS, profile_patch - server._PROFILE_KEYS
    for key in server._WATERMARK_KEYS:
        assert key in writes, f"{key} is allowed but the mirror never sends it"


def _settings_map_fields(page: str) -> set[str]:
    """The string `field`s SETTINGS_MAP (app/lib/ofMirrorSettings.ts) maps on settings `page`."""
    whole = (APP_LIB / "ofMirrorSettings.ts").read_text()
    src = whole[whole.index("export const SETTINGS_MAP"):]
    key = f"  {page}:" if re.fullmatch(r"\w+", page) else f'  "{page}":'
    block = src[src.index(f"\n{key}") + 1:]
    end = re.search(r"\n  [\w\"]", block)
    block = block[:end.start()] if end else block
    fields = set(re.findall(r'field: "(\w+)"', block))
    for listed in re.findall(r'of\("(?:me|settings)", \[(.*?)\]', block, re.S):
        fields |= set(re.findall(r'"(\w+)"', listed))
    if "coStreaming" in block:  # the streaming radios' shared entry, declared above the map
        fields |= set(re.findall(r'coStreaming: SettingsEntry = \{[^}]*field: "(\w+)"', whole))
    return fields


def case_every_toggle_the_mirror_saves_to_users_me_is_a_profile_key():
    """settingWrite (ofMirrorSettingsWrites.ts) sends a saved toggle's field to the security PATCH when it is in
    SECURITY_KEYS and to PATCH /users/me otherwise: every such field must pass that route's allow-list, or the
    toggle 422s. The pages are TOGGLE_PAGES that save through settingWrite (not notifications/* by transport,
    not story's own route)."""
    writes = (APP_LIB / "ofMirrorSettingsWrites.ts").read_text()
    listed = writes[writes.index("export const TOGGLE_PAGES"):]
    pages = set(re.findall(r'"([\w/]+)"', listed[:listed.index("]);")]))
    pages = {p for p in pages if p == "notifications/mentions" or not p.startswith(("notifications/", "story"))}
    assert pages == {"fans", "security", "streaming", "notifications/mentions"}, pages
    to_me: set[str] = set()
    for page in pages:
        fields = _settings_map_fields(page)
        assert fields, page
        to_me |= fields - server._SECURITY_PATCH_KEYS
    assert "coStreamingRequestFrom" in _settings_map_fields("streaming")
    assert to_me and to_me <= server._PROFILE_KEYS, to_me - server._PROFILE_KEYS
    # The profile page's fields too (its Save sends ProfilePatch to PATCH /users/me).
    assert _settings_map_fields("profile") <= server._PROFILE_KEYS


def case_story_route_takes_only_ofs_values():
    try:
        server._StorySettingsBody(allowReplyFrom="everyone")
    except ValidationError:
        return
    raise AssertionError("allowReplyFrom accepted a value OF's switch never sends")


_harness.run()
