#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import os  # noqa: E402

os.environ["OFM_NEW_WRITES_ENABLED"] = "1"

import re  # noqa: E402
from pathlib import Path  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

API = of_client.API_BASE


def _client():
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
    for route, body in (
        (server.of_update_profile, {"about": "bio", "email": "x@example.invalid"}),
        (server.of_update_profile, {"isPrivate": True}),
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


def case_a_formatted_about_goes_out_with_ofs_tags_only():
    calls = _forwarded(lambda: (
        server.of_update_profile({"about": '<p><strong>Hi</strong> <img src=x onerror="a()">'
                                           '<span class="m-editor-fs__l evil">there</span></p>'}),
        server.of_update_profile({"about": "plain <3 bio"}),
    ))
    assert calls[0][2] == {"about": '<p><strong>Hi</strong> <span class="m-editor-fs__l">there</span></p>'}, calls[0]
    assert calls[1][2] == {"about": "plain <3 bio"}, calls[1]


APP_LIB = Path(__file__).resolve().parents[2] / "app" / "lib"


def _ts_strings(src: str, start: str, end: str) -> set[str]:
    body = src[src.index(start):]
    return set(re.findall(r'"([A-Za-z0-9_]+)"', body[:body.index(end)]))


def case_the_allow_lists_match_the_keys_the_app_sends():
    writes = (APP_LIB / "ofMirrorSettingsWrites.ts").read_text()
    profile = (APP_LIB / "ofMirrorWrites.ts").read_text()
    security = _ts_strings(writes, "export const SECURITY_KEYS", "]);")
    assert security == server._SECURITY_PATCH_KEYS, security ^ server._SECURITY_PATCH_KEYS
    profile_patch = _ts_strings(profile, "export type ProfilePatch", ">>;")
    assert profile_patch and profile_patch <= server._PROFILE_KEYS, profile_patch - server._PROFILE_KEYS
    for key in server._WATERMARK_KEYS:
        assert key in writes, f"{key} is allowed but the mirror never sends it"


def _settings_map_fields(page: str) -> set[str]:
    whole = (APP_LIB / "ofMirrorSettings.ts").read_text()
    src = whole[whole.index("export const SETTINGS_MAP"):]
    key = f"  {page}:" if re.fullmatch(r"\w+", page) else f'  "{page}":'
    block = src[src.index(f"\n{key}") + 1:]
    end = re.search(r"\n  [\w\"]", block)
    block = block[:end.start()] if end else block
    fields = set(re.findall(r'field: "(\w+)"', block))
    for listed in re.findall(r'of\("(?:me|settings)", \[(.*?)\]', block, re.S):
        fields |= set(re.findall(r'"(\w+)"', listed))
    if "coStreaming" in block:
        fields |= set(re.findall(r'coStreaming: SettingsEntry = \{[^}]*field: "(\w+)"', whole))
    return fields


def case_every_toggle_the_mirror_saves_to_users_me_is_a_profile_key():
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
    assert _settings_map_fields("profile") <= server._PROFILE_KEYS


def case_story_route_takes_only_ofs_values():
    try:
        server._StorySettingsBody(allowReplyFrom="everyone")
    except ValidationError:
        return
    raise AssertionError("allowReplyFrom accepted a value OF's switch never sends")



def case_drawn_switches_and_frequency_are_allowed_and_drop_my_settings():
    calls, dropped = [], []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a, k)) or {"success": True}

    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._get_client = lambda: _Fake()
    server._resolve_account_id = lambda _ctx: "acct-1"
    server.relay_cache.invalidate = lambda name, aid: dropped.append((name, aid))
    try:
        server.of_update_profile({"canAcceptMessageOnlyFromFriends": True})
        server.of_patch_security_settings({"isPrivate": True})
        server.of_patch_notification_settings({"notifications": {"email": [{"code": "new_likes_digest", "value": 12}]}})
        try:
            server.of_update_profile({"canAcceptMessageOnlyFromFriends": True, "canAddFriends": True})
        except HTTPException as e:
            assert e.status_code == 422 and "canAddFriends" in e.detail, e.detail
        else:
            raise AssertionError("users/me forwarded a key the mirror never sends")
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    assert [c[0] for c in calls] == ["update_profile", "patch_security_settings", "patch_notification_settings"], calls
    assert calls[0][2] == {"canAcceptMessageOnlyFromFriends": True}, calls[0]
    assert calls[1][1] == ({"isPrivate": True},), calls[1]
    assert calls[2][1] == ({"notifications": {"email": [{"code": "new_likes_digest", "value": 12}]}},), calls[2]
    assert dropped == [("my_settings", "acct-1")] * 3, dropped
    writes = (APP_LIB / "ofMirrorSettingsWrites.ts").read_text()
    drawn = _ts_strings(writes, "export const DRAWN_TOGGLES", "};")
    keys = {k for k in drawn if not k.startswith(("messageOnly", "setting_"))} - {"messaging", "security"}
    assert keys == {"canAcceptMessageOnlyFromFriends", "isPrivate"}, keys
    assert "canAcceptMessageOnlyFromFriends" in server._PROFILE_KEYS
    assert "isPrivate" in server._SECURITY_PATCH_KEYS

def case_close_all_sessions_route_calls_the_client_and_the_backstop_refuses_it():
    import types
    from _of_wire import fake_wire

    c = _client()
    c.close_all_sessions()
    assert c.sent == [("DELETE", f"{API}/sessions", {})], c.sent

    calls, dropped = [], []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a, k)) or {"success": True}

    sent = []
    real = of_client.OFClient.__new__(of_client.OFClient)
    real.account_id, real.user_id, real.timeout_s, real._x_hash = "TEST", "999", 5, "HASH"
    real.proxy_label = real.proxy_url = None
    fake_wire(real, types.SimpleNamespace(get=lambda url, **_k: sent.append(("GET", url)),
                                          request=lambda m, url, **_k: sent.append((m, url))))
    real._signed_headers = lambda _url: {}
    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._resolve_account_id = lambda _ctx: "acct-1"
    server.relay_cache.invalidate = lambda name, aid: dropped.append((name, aid))
    try:
        server._get_client = lambda: _Fake()
        assert server.of_close_all_sessions() == {"success": True}
        server._get_client = lambda: real
        try:
            server.of_close_all_sessions()
        except HTTPException as e:
            assert e.status_code == 403 and e.detail["upstream_status"] == "refused_by_relay", e.detail
            assert "DELETE /api2/v2/sessions" in e.detail["upstream_body"], e.detail
        else:
            raise AssertionError("the sessions backstop let Close all sessions through")
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    assert calls == [("close_all_sessions", (), {})], calls
    assert sent == [], sent
    assert dropped == [("my_settings", "acct-1")], dropped
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("DELETE", "/api/of/v2/sessions") in routes


def case_profile_images_save_and_the_upload_route_refuses_before_of():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    item = {"processId": "p1", "host": "convert", "name": "cover.png", "thumbId": 7}
    calls = _forwarded(lambda: (server.of_update_profile({"header": item}), server.of_update_profile({"avatar": ""})))
    assert [(c[0], c[2]) for c in calls] == [("update_profile", {"header": item}), ("update_profile", {"avatar": ""})], calls
    for bad in ({"header": "https://example.invalid/x.png"}, {"avatar": {"processId": "p", "url": "x"}}, {"header": {}}):
        def _call(bad=bad):
            try:
                server.of_update_profile(bad)
            except HTTPException as e:
                assert e.status_code == 422, e.detail
                return
            raise AssertionError(f"forwarded {bad}")
        assert _forwarded(_call) == [], bad

    uploads = []

    class _Fake:
        def upload_media(self, path, **kw):
            uploads.append((Path(path).read_bytes(), kw))
            return {"ready": True, "send_with": [item]}

    app = FastAPI()
    app.add_api_route("/up", server.of_upload_profile_image, methods=["POST"])
    client = TestClient(app)
    png = ("c.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")
    orig = server._get_client, server._resolve_account_id
    server._get_client = lambda: _Fake()
    server._resolve_account_id = lambda _ctx: "acct-1"
    try:
        for files, data, status in (
            ({"file": ("c.txt", b"hello", "text/plain")}, {"kind": "header"}, 415),
            ({"file": ("c.svg", b"<svg/>", "image/svg+xml")}, {"kind": "header"}, 415),
            ({"file": ("big.png", b"0" * (server.PROFILE_IMAGE_MAX + 1), "image/png")}, {"kind": "avatar"}, 413),
            ({"file": png}, {"kind": "banner"}, 422),
            ({"file": png}, {"kind": "header", "extra": "1"}, 422),
            ({}, {"kind": "header"}, 422),
        ):
            r = client.post("/up", files=files or None, data=data)
            assert r.status_code == status, (files.keys(), data, r.status_code, r.text)
        assert uploads == [], uploads
        r = client.post("/up", files={"file": png}, data={"kind": "avatar"})
        assert r.status_code == 200 and r.json() == item, r.text
        assert uploads == [(png[1], {"content_type": "image/png", "check_dedupe": False, "thumb_size": "avatar"})], uploads
        for bad in (None, "ok", {"ready": False, "note": "x"}, {"ready": True, "send_with": {}}):
            server._get_client = lambda bad=bad: type("_Bad", (), {"upload_media": lambda self, path, **kw: bad})()
            r = client.post("/up", files={"file": png}, data={"kind": "avatar"})
            assert r.status_code == 502, (bad, r.status_code, r.text)
    finally:
        server._get_client, server._resolve_account_id = orig

    sent = {}
    c = _client()
    c.me = lambda: {"upload": {"geoUploadArgs": {"preset": "of_beta", "additional": {"user": "4242"}}}}
    c.convert_register = lambda **kw: sent.update(kw) or {"processId": "p9", "host": "h"}
    got = c._claim_uploaded(upload_key="upload/k/1/c.png", etag="e", filename="c.png", thumb_size="header")
    assert got["send_with"] == [{"processId": "p9", "host": "h", "name": "c.png"}], got
    assert sent["upload_args"]["additional"] == {"user": "4242", "customThumbSize": "header"}, sent


def case_social_buttons_add_and_remove_send_the_captured_requests():
    import json

    record = json.loads((Path(__file__).resolve().parents[2] / ".scratch/ofm-not-yet/captures"
                         / "settings--social-media-buttons.json").read_text())
    by_role = {(r["role"], r["method"], r["path"]) for r in record["requests"]}
    assert ("write", "PUT", "/api2/v2/users/social/buttons") in by_role
    assert ("undo", "DELETE", "/api2/v2/users/social/buttons/{id}") in by_role
    captured = next(r for r in record["requests"] if r["role"] == "write" and r["method"] == "PUT"
                    and r["path"] == "/api2/v2/users/social/buttons")
    assert set(captured["body"]) == server._SOCIAL_BUTTON_KEYS, captured["body"]

    body = {"socialMedia": "instagram", "label": "My IG", "link": "", "username": "alpha"}
    link_body = {"socialMedia": "amazon", "label": "Wishlist", "link": "https://www.amazon.com/hz/wishlist/ls/X1", "username": ""}
    c = _client()
    c.add_social_button(body)
    c.delete_social_button(7)
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, kw)) or []
    c.social_buttons()
    assert c.sent == [("PUT", f"{API}/users/social/buttons", {"json_body": body}),
                      ("DELETE", f"{API}/users/social/buttons/7", {}),
                      ("GET", f"{API}/users/social/buttons", {})], c.sent
    providers = [{"socialMedia": "instagram", "label": "Instagram", "isLink": False, "isShowAt": False}]
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, kw)) or {"socialMediaProviders": providers, "csrf": "x",
                                                                         "socialButtonsMaxLimit": 10}
    assert c.social_media_providers() == {"socialMediaProviders": providers}
    assert c.sent[-1] == ("GET", f"{API}/init", {}), c.sent[-1]
    c.get_json = lambda path, **kw: {"socialMediaProviders": None}
    assert c.social_media_providers() == {"socialMediaProviders": []}

    calls, dropped = [], []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a)) or {"success": True}

    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._get_client, server._resolve_account_id = (lambda: _Fake()), (lambda _ctx: "acct-1")
    server.relay_cache.invalidate = lambda name, aid: dropped.append((name, aid))
    try:
        server.of_add_social_button(dict(body))
        server.of_add_social_button(dict(link_body))
        server.of_delete_social_button(7)
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    assert calls == [("add_social_button", (body,)), ("add_social_button", (link_body,)), ("delete_social_button", (7,))], calls
    assert dropped == [("my_settings", "acct-1")] * 3, dropped
    for bad in ({**body, "id": 1}, {**link_body, "link": "javascript:alert(1)"}, {**link_body, "link": "instagram"},
                {**body, "label": "  "}, {**body, "username": 5}, {**body, "socialMedia": " "}, {**body, "username": " "},
                {**body, "link": "https://instagram.com/alpha"}, {}):
        def _call(bad=bad):
            try:
                server.of_add_social_button(bad)
            except HTTPException as e:
                assert e.status_code == 422, e.detail
                return
            raise AssertionError(f"forwarded {bad}")
        assert _forwarded(_call) == [], bad
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for want in (("GET", "/api/of/v2/users/social/buttons"), ("PUT", "/api/of/v2/users/social/buttons"),
                 ("DELETE", "/api/of/v2/users/social/buttons/{button_id}"), ("GET", "/api/of/v2/init")):
        assert want in routes, f"{want} missing"


def case_things_i_like_links_create_and_delete_send_the_captured_requests():
    import json

    record = json.loads((Path(__file__).resolve().parents[2] / ".scratch/ofm-not-yet/captures"
                         / "settings--things-i-like-links.json").read_text())
    by_role = {(r["role"], r["method"], r["path"]) for r in record["requests"]}
    assert ("read", "GET", "/api2/v2/users/links") in by_role
    assert ("undo", "DELETE", "/api2/v2/users/links/{id}") in by_role
    captured = next(r for r in record["requests"] if r["role"] == "write" and r["method"] == "PUT"
                    and r["path"] == "/api2/v2/users/links")
    assert set(captured["body"]) == server._USERS_LINK_KEYS, captured["body"]

    body = {"link": "https://www.youtube.com/watch?v=alpha"}
    c = _client()
    c.add_users_link(body)
    c.delete_users_link(7)
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, kw)) or []
    c.users_links()
    assert c.sent == [("PUT", f"{API}/users/links", {"json_body": body}),
                      ("DELETE", f"{API}/users/links/7", {}),
                      ("GET", f"{API}/users/links", {})], c.sent

    calls, dropped = [], []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a)) or {"success": True}

    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._get_client, server._resolve_account_id = (lambda: _Fake()), (lambda _ctx: "acct-1")
    server.relay_cache.invalidate = lambda name, aid: dropped.append((name, aid))
    try:
        server.of_add_users_link(dict(body))
        server.of_delete_users_link(7)
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    assert calls == [("add_users_link", (body,)), ("delete_users_link", (7,))], calls
    assert dropped == [("my_settings", "acct-1")] * 2, dropped
    for bad in ({**body, "id": 1}, {"link": "javascript:alert(1)"}, {"link": "youtube"}, {"link": 5}, {}):
        def _call(bad=bad):
            try:
                server.of_add_users_link(bad)
            except HTTPException as e:
                assert e.status_code == 422, e.detail
                return
            raise AssertionError(f"forwarded {bad}")
        assert _forwarded(_call) == [], bad
    order = [(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())]
    for want in (("GET", "/api/of/v2/users/links"), ("PUT", "/api/of/v2/users/links"),
                 ("DELETE", "/api/of/v2/users/links/{link_id}")):
        assert want in order, f"{want} missing"
    assert order.index(("GET", "/api/of/v2/users/links")) < order.index(("GET", "/api/of/v2/users/{user_id_or_username}"))


def case_reset_stream_key_sends_the_captured_request_and_drops_my_settings():
    import json

    rec = json.loads((Path(__file__).resolve().parents[2] / "docs/of-manager/captures"
                      / "settings--streaming-reset-stream-key.json").read_text())
    want = rec["request"]
    assert rec["source"] == "aborted" and want["body"] is None, rec
    c = _client()
    c.reset_stream_key(want["query"]["type"])
    assert c.sent == [(want["method"], API.replace("/api2/v2", "") + want["path"], {"params": want["query"]})], c.sent

    calls, dropped = [], []

    class _Fake:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a, k)) or {"success": True}

    orig = server._get_client, server._resolve_account_id, server.relay_cache.invalidate
    server._get_client = lambda: _Fake()
    server._resolve_account_id = lambda _ctx: "acct-1"
    server.relay_cache.invalidate = lambda name, aid: dropped.append((name, aid))
    try:
        assert server.of_reset_stream_key("mux_direct", None) == {"success": True}
        try:
            server.of_reset_stream_key("obs_agora", {"key": "x"})
        except HTTPException as e:
            assert e.status_code == 422, e.detail
        else:
            raise AssertionError("a body went through")
    finally:
        server._get_client, server._resolve_account_id, server.relay_cache.invalidate = orig
    assert calls == [("reset_stream_key", ("mux_direct",), {})], calls
    assert dropped == [("my_settings", "acct-1")], dropped
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("DELETE", "/api/of/v2/streams/obs/key") in routes


_harness.run()
