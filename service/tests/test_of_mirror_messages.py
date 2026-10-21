#!/usr/bin/env python3
"""OF Manager's Messages tab (app/lib/ofMirrorChat.ts): the relay calls it makes.

The mirror sends only bodies the relay already accepts; these cases pin the
exact OF request each one becomes, with the OF client faked (no network, no
signing): a chat send and a PPV, a scheduled chat send, the mass message to
user lists, mute / unmute and hide, and the chat list's Clear messages (the
row "x") and Mark all as read.

  case_routes_are_registered
  case_send_is_one_post_to_the_chat
  case_composer_gif_tags_and_release_forms_ride_ofs_fields
  case_send_route_passes_the_release_form_fields
  case_ppv_send_carries_price_and_vault_ids
  case_scheduled_send_goes_to_the_queue_for_one_fan
  case_mass_to_lists_is_one_queue_post
  case_mute_unmute_hide_paths
  case_mute_and_hide_routes_call_the_client
  case_clear_messages_and_mark_all_read_paths
  case_clear_messages_route_calls_the_client_and_busts_the_list
  case_chat_media_type_tabs_are_a_path_segment
  case_chat_media_kind_route_calls_the_client
  case_chat_media_kind_route_rejects_other_kinds
  case_chat_header_menu_paths
  case_chat_header_menu_routes_call_the_client
  case_message_menu_paths
  case_message_menu_routes_call_the_client
  case_unrestrict_unhides_only_when_asked

Run: ./venv/bin/python service/tests/test_of_mirror_messages.py
"""
import asyncio
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import of_client  # noqa: E402
import server  # noqa: E402

FAN = 9001
API = of_client.API_BASE


def _client():
    """An OFClient that skips __init__ and records (method, path, json_body) instead of calling OF."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw.get("json_body"))) or {"id": 1}
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, None)) or []
    return c


def case_routes_are_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for want in [
        ("POST", "/api/of/v2/chats/{chat_id}/messages"),
        ("POST", "/api/of/v2/chats/{chat_id}/messages/scheduled"),
        ("POST", "/api/of/v2/messages/queue"),
        ("POST", "/api/of/v2/chats/{chat_id}/mute"),
        ("DELETE", "/api/of/v2/chats/{chat_id}/mute"),
        ("POST", "/api/of/v2/chats/{chat_id}/hide"),
        ("DELETE", "/api/of/v2/chats/{chat_id}"),
        ("POST", "/api/of/v2/chats/mark-as-read"),
        ("GET", "/api/of/v2/chats/folders"),
        ("PATCH", "/api/of/v2/lists/{list_id}/pin-chat"),
        ("GET", "/api/of/v2/lists"),
        ("GET", "/api/of/v2/chats/{chat_id}/media"),
        ("GET", "/api/of/v2/chats/{chat_id}/media/{kind}"),
        ("PUT", "/api/of/v2/subscriptions/{user_id}/discount"),
        ("DELETE", "/api/of/v2/chats/{chat_id}/messages/pin"),
        ("PUT", "/api/of/v2/messages/{message_id}/hide"),
        ("POST", "/api/of/v2/messages/{message_id}/bookmark"),
        ("DELETE", "/api/of/v2/messages/{message_id}/bookmark"),
    ]:
        assert want in routes, f"{want} missing"


def case_send_is_one_post_to_the_chat():
    c = _client()
    # The relay's send route passes exactly these (auto_tag off: a human composed it).
    c.send_message(FAN, text="Synthetic hello", locked_text=False, price=0, media_files=[], previews=[],
                   is_forward=False, reply_to_message_id=None, tagged_users=[], giphy_id=None, auto_tag=False)
    assert c.sent == [("POST", f"{API}/chats/{FAN}/messages", {
        "text": "<p>Synthetic hello</p>",
        "lockedText": False,
        "mediaFiles": [],
        "price": 0,
        "previews": [],
        "rfTag": [],
        "rfGuest": [],
        "rfPartner": [],
        "isForward": False,
    })], c.sent


def case_composer_gif_tags_and_release_forms_ride_ofs_fields():
    c = _client()
    # The chat composer's GIF (text "" with a GIF), a tagged creator, a guest and a release-form document.
    c.send_message(FAN, text="", price=0, media_files=[], previews=[], tagged_users=[501], giphy_id="gif123",
                   rf_guest=[77], rf_partner=[88], auto_tag=False)
    method, path, body = c.sent[-1]
    assert (method, path) == ("POST", f"{API}/chats/{FAN}/messages"), (method, path)
    assert body["text"] == "" and body["giphyId"] == "gif123", body
    assert body["rfTag"] == [501] and body["userTags"] == [501], body
    assert body["rfGuest"] == [77] and body["rfPartner"] == [88], body
    # Formatted text (OF's editor markup) goes as it is, not wrapped again.
    c.send_message(FAN, text='<p><strong>Hi</strong> <span class="m-editor-fc__blue-1">there</span></p>', auto_tag=False)
    assert c.sent[-1][2]["text"] == '<p><strong>Hi</strong> <span class="m-editor-fc__blue-1">there</span></p>', c.sent[-1]


def case_send_route_passes_the_release_form_fields():
    """The send ROUTE (not just the client) carries the composer's guest and release-form tags to OF's
    rfGuest / rfPartner: the route runs with a recording OF client and no DB or network."""
    assert server.SendMessageBody(text="x").rf_guest == [] and server.SendMessageBody(text="x").rf_partner == []
    import employees
    import relay_cache as rc

    c = _client()

    async def no_employee(*a, **k):
        return None

    async def no_resale(*a, **k):
        return None

    orig = (server._get_client, server._resolve_account_id, server._reject_if_resale, server._pin_sent_media,
            employees.resolve_outbound_employee_id, rc.invalidate)
    server._get_client = lambda *a, **k: c
    server._resolve_account_id = lambda *a, **k: "acct"
    server._reject_if_resale = no_resale
    server._pin_sent_media = lambda *a, **k: None
    employees.resolve_outbound_employee_id = no_employee
    rc.invalidate = lambda *a, **k: None
    try:
        body = server.SendMessageBody(text="hi", tagged_users=[501], rf_guest=[77], rf_partner=[88, 89])
        asyncio.run(server.send_message(request=None, chat_id=FAN, body=body))
        plain = server.SendMessageBody(text="plain")
        asyncio.run(server.send_message(request=None, chat_id=FAN, body=plain))
    finally:
        (server._get_client, server._resolve_account_id, server._reject_if_resale, server._pin_sent_media,
         employees.resolve_outbound_employee_id, rc.invalidate) = orig
    (m1, p1, tagged), (m2, p2, untagged) = c.sent
    assert (m1, p1) == (m2, p2) == ("POST", f"{API}/chats/{FAN}/messages"), c.sent
    assert tagged["rfTag"] == [501] and tagged["rfGuest"] == [77] and tagged["rfPartner"] == [88, 89], tagged
    # A plain text send carries OF's empty release-form arrays, exactly as before these fields existed.
    assert untagged["text"] == "<p>plain</p>" and untagged["rfTag"] == untagged["rfGuest"] == untagged["rfPartner"] == [], untagged


def case_ppv_send_carries_price_and_vault_ids():
    c = _client()
    c.send_message(FAN, text="", price=12, media_files=[61, 62], previews=[], tagged_users=[], auto_tag=False)
    method, path, body = c.sent[-1]
    assert (method, path) == ("POST", f"{API}/chats/{FAN}/messages"), (method, path)
    assert body["price"] == 12 and body["mediaFiles"] == [61, 62] and body["lockedText"] is False, body


def case_scheduled_send_goes_to_the_queue_for_one_fan():
    c = _client()
    at = "2026-10-20T18:30:00+02:00"
    c.schedule_message(FAN, text="later", scheduled_date=at, price=0, locked_text=False, media_files=[61],
                       previews=[], tagged_users=[], auto_tag=False)
    assert c.sent == [("POST", f"{API}/messages/queue", {
        "text": "later",
        "lockedText": False,
        "mediaFiles": [61],
        "price": 0,
        "previews": [],
        "scheduledDate": at,
        "userIds": [FAN],
    })], c.sent


def case_mass_to_lists_is_one_queue_post():
    c = _client()
    # {text, user_lists} from the mirror; the relay's other knobs at their defaults.
    c.send_mass_message(text="Synthetic blast", user_lists=["fans", "42"], included_users=[], excluded_users=[],
                        excluded_user_lists=[], price=0, locked_text=False, media_files=[], previews=[],
                        tagged_users=[], giphy_id=None, filters=None, online_only=False)
    assert c.sent == [("POST", f"{API}/messages/queue", {
        "text": "Synthetic blast",
        "lockedText": False,
        "mediaFiles": [],
        "price": 0,
        "previews": [],
        "userLists": ["fans", "42"],
        "userIds": [],
        "excludedLists": [],
    })], c.sent


def case_mute_unmute_hide_paths():
    c = _client()
    c.mute_chat(FAN)
    c.unmute_chat(FAN)
    c.hide_chat(FAN)
    assert c.sent == [
        ("POST", f"{API}/chats/{FAN}/mute", None),
        ("DELETE", f"{API}/chats/{FAN}/mute", None),
        ("POST", f"{API}/chats/{FAN}/hide", None),
    ], c.sent


def case_mute_and_hide_routes_call_the_client():
    c = _client()
    orig = server._get_client, server._bust_chat_list_cache
    server._get_client = lambda: c
    server._bust_chat_list_cache = lambda *a, **k: None
    try:
        server.of_mute_chat(FAN)
        server.of_unmute_chat(FAN)
        server.of_hide_chat(FAN)
    finally:
        server._get_client, server._bust_chat_list_cache = orig
    assert [(m, p) for m, p, _ in c.sent] == [
        ("POST", f"{API}/chats/{FAN}/mute"),
        ("DELETE", f"{API}/chats/{FAN}/mute"),
        ("POST", f"{API}/chats/{FAN}/hide"),
    ], c.sent



def case_clear_messages_and_mark_all_read_paths():
    # OF web: the row "x" is DELETE /chats/{id} (its chats store's deleteChat), Mark all as read POST /chats/mark-as-read, no body.
    c = _client()
    c.delete_chat(FAN)
    c.mark_all_chats_read()
    assert c.sent == [
        ("DELETE", f"{API}/chats/{FAN}", None),
        ("POST", f"{API}/chats/mark-as-read", None),
    ], c.sent


def _with_paced_writes(c, run):
    """Run `run()` with `c` as the OF client and the write pacer recording each
    (account, send_purpose) before running the write unspaced; returns
    (paced calls, relay_cache invalidations)."""
    import automation_executor
    paced, busted = [], []

    async def _fake_paced(aid, fn, *, send_purpose=None, **_kw):
        paced.append((aid, send_purpose))
        return await asyncio.to_thread(fn)

    orig = (server._get_client, server._resolve_account_id,
            automation_executor.of_write_paced, server.relay_cache.invalidate)
    server._get_client = lambda: c
    server._resolve_account_id = lambda _req=None: "acct-mirror"
    automation_executor.of_write_paced = _fake_paced
    server.relay_cache.invalidate = lambda ns, aid, *a, **k: busted.append((ns, aid))
    try:
        run()
    finally:
        (server._get_client, server._resolve_account_id,
         automation_executor.of_write_paced, server.relay_cache.invalidate) = orig
    return paced, busted


def case_clear_messages_route_is_paced_and_busts_the_list():
    c = _client()
    got = []
    paced, busted = _with_paced_writes(c, lambda: got.append(asyncio.run(server.of_delete_chat(FAN))))
    assert got == [{"id": 1}], got
    assert [(m, p) for m, p, _ in c.sent] == [("DELETE", f"{API}/chats/{FAN}")], c.sent
    assert paced == [("acct-mirror", "not_fan_dm")], paced
    assert ("list_chats", "acct-mirror") in busted and ("roster_count", "acct-mirror") in busted, busted


def case_mark_read_is_unpaced():
    """A read flip reaches no fan, so it never takes the account's write slot."""
    async def _no_local(*_a, **_k):
        return None

    orig_local = server._set_local_unread
    server._set_local_unread = _no_local
    try:
        c = _client()
        paced, _ = _with_paced_writes(c, lambda: asyncio.run(server.of_mark_chat_read(FAN)))
        assert paced == [], paced
        assert [(m, p) for m, p, _ in c.sent] == [("POST", f"{API}/chats/{FAN}/mark-as-read")], c.sent
    finally:
        server._set_local_unread = orig_local



def _get_client_recorder():
    """An OFClient whose get_json records (path, params) instead of calling OF."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.got = []
    c.get_json = lambda path, **kw: c.got.append((path, kw.get("params"))) or {"list": [], "hasMore": False}
    return c


def case_chat_media_type_tabs_are_a_path_segment():
    """OF web's gallery Photos / Videos / Audio tabs: /chats/{id}/media/<kind>, the rest of the query as /media's."""
    c = _get_client_recorder()
    for kind in ("photos", "videos", "audios"):
        c.chat_media(FAN, limit=20, last_id="77", skip_users="all", kind=kind)
    c.chat_media(FAN, limit=20, opened=1, skip_users="all")
    assert [p for p, _ in c.got] == [f"{API}/chats/{FAN}/media/photos", f"{API}/chats/{FAN}/media/videos", f"{API}/chats/{FAN}/media/audios", f"{API}/chats/{FAN}/media"], c.got
    assert c.got[0][1] == {"limit": 20, "last_id": "77", "skip_users": "all"}, c.got[0]
    assert c.got[3][1] == {"limit": 20, "skip_users": "all", "opened": 1}, c.got[3]
    try:
        c.chat_media(FAN, kind="posts")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown kind must not reach OF")


def case_chat_media_kind_route_calls_the_client():
    c = _get_client_recorder()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        assert server.of_chat_media_kind(FAN, "videos", limit=20, last_id=None, skip_users="all", opened=None, purchased=1, from_user=1001) == {"list": [], "hasMore": False}
    finally:
        server._get_client = orig
    assert c.got == [(f"{API}/chats/{FAN}/media/videos", {"limit": 20, "skip_users": "all", "purchased": 1, "from_user": 1001})], c.got


def case_chat_media_kind_route_rejects_other_kinds():
    """FastAPI answers 422 for any kind outside OF's three tabs: the route's `kind` is that Literal."""
    import typing
    kind = typing.get_type_hints(server.of_chat_media_kind)["kind"]
    assert typing.get_origin(kind) is typing.Literal, kind
    assert set(typing.get_args(kind)) == {"photos", "videos", "audios"}, typing.get_args(kind)
    c = _get_client_recorder()
    c.chat_media(FAN, limit=20, offset=40)
    assert c.got == [(f"{API}/chats/{FAN}/media", {"limit": 20, "offset": 40})], c.got


def case_chat_header_menu_paths():
    """OF web's chat menu: Give user a discount (616150 `S`), its Clear, View user's comments."""
    c = _client()
    c.set_subscription_discount(FAN, 15, 3)
    c.set_subscription_discount(FAN, 0, 1)
    assert c.sent == [
        ("PUT", f"{API}/subscriptions/{FAN}/discount", {"discount": 15, "period": 3}),
        ("PUT", f"{API}/subscriptions/{FAN}/discount", {"discount": 0, "period": 1}),
    ], c.sent
    g = _get_client_recorder()
    g.notifications(limit=20, type="commented", related_user=FAN)
    g.notifications(limit=20, type="commented")
    assert g.got == [
        (f"{API}/users/notifications", {"limit": 20, "offset": 0, "type": "commented", "related_user": FAN}),
        (f"{API}/users/notifications", {"limit": 20, "offset": 0, "type": "commented"}),
    ], g.got


def case_chat_header_menu_routes_call_the_client():
    c = _client()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        server.of_set_subscription_discount(FAN, server._DiscountBody(discount=20, period=2))
        server._DiscountBody(discount=0, period=1)  # OF's Clear
        server._DiscountBody(discount=60, period=12)
    finally:
        server._get_client = orig
    assert c.sent == [
        ("PUT", f"{API}/subscriptions/{FAN}/discount", {"discount": 20, "period": 2}),
    ], c.sent
    import pydantic
    # OF's select: 5..60 by 5 (0 clears), 1..12 months.
    for bad in ({"discount": 65, "period": 1}, {"discount": 3, "period": 1}, {"discount": 12, "period": 1}, {"discount": 10, "period": 13}, {"discount": 10, "period": 0}):
        try:
            server._DiscountBody(**bad)
        except pydantic.ValidationError:
            continue
        raise AssertionError(f"{bad} must be refused (422)")


def case_message_menu_paths():
    """OF web's per-message menu (13560) and pinned page: hide (204607 `M`), bookmark (458723 `P`/`w`), unpin all (`k`), its search."""
    c = _client()
    c.hide_message(77, FAN)
    c.bookmark_message(77, 5, True)
    c.bookmark_message(77, 5, False)
    c.bookmark_message(78, None, True)
    c.unpin_all_messages(FAN)
    assert c.sent == [
        ("PUT", f"{API}/messages/77/hide", {"withUserId": FAN}),
        ("POST", f"{API}/posts/77/bookmarks", {"chat_group_id": 5}),
        ("DELETE", f"{API}/posts/77/bookmarks", {"chat_group_id": 5}),
        ("POST", f"{API}/posts/78/bookmarks", None),
        ("DELETE", f"{API}/chats/{FAN}/messages/pin", None),
    ], c.sent
    g = _get_client_recorder()
    g.search_chat(FAN, "hey", "pinned")
    g.search_chat(FAN, "hey")
    assert g.got == [(f"{API}/chats/{FAN}/messages/search", {"query": "hey", "filter": "pinned"}), (f"{API}/chats/{FAN}/messages/search", {"query": "hey"})], g.got


def case_message_menu_routes_call_the_client():
    c = _client()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        server.of_hide_message(77, server._WithUserBody(withUserId=FAN))
        server.of_bookmark_message(77, server._BookmarkBody(chat_group_id=5))
        server.of_unbookmark_message(77, None)
        server.of_unpin_all_messages(FAN)
    finally:
        server._get_client = orig
    assert c.sent == [
        ("PUT", f"{API}/messages/77/hide", {"withUserId": FAN}),
        ("POST", f"{API}/posts/77/bookmarks", {"chat_group_id": 5}),
        ("DELETE", f"{API}/posts/77/bookmarks", None),
        ("DELETE", f"{API}/chats/{FAN}/messages/pin", None),
    ], c.sent


def case_unrestrict_unhides_only_when_asked():
    """OF's Unrestrict is one DELETE: the mirror's ?unhide=false leaves a chat the Creator hid hidden."""
    import asyncio
    import automations._common as common
    c = _client()
    c.delete_json = lambda path, **kw: c.sent.append(("DELETE", path, None)) or {}
    orig = (server._get_client, server._resolve_account_id, common.set_of_restricted_skip)
    skips = []

    async def skip(aid, uid, on):
        skips.append((aid, uid, on))

    server._get_client = lambda: c
    server._resolve_account_id = lambda request: "acc"
    common.set_of_restricted_skip = skip
    try:
        asyncio.run(server.of_unrestrict_user(FAN, None, unhide=False))
        assert c.sent == [("DELETE", f"{API}/users/{FAN}/restrict", None)], c.sent
        c.sent.clear()
        asyncio.run(server.of_unrestrict_user(FAN, None, unhide=True))
        assert c.sent == [("DELETE", f"{API}/users/{FAN}/restrict", None), ("DELETE", f"{API}/chats/{FAN}/hide", None)], c.sent
    finally:
        server._get_client, server._resolve_account_id, common.set_of_restricted_skip = orig
    assert skips == [("acc", FAN, False), ("acc", FAN, False)], skips

def case_messages_basic_grants_no_payment_route():
    """The mirror's Tip is disabled, so Messages Basic must not open POST /tips (a payment) to a chatter."""
    import permissions
    assert "/of-manager/messages" not in (permissions.route_pages("/api/of/v2/tips", "GET") or ()), \
        permissions.route_pages("/api/of/v2/tips", "GET")
    assert "/of-manager/messages" in permissions.route_pages("/api/of/v2/chats/1/messages", "GET")


_harness.run()
