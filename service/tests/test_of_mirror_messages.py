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
  case_pins_two_reads_inside_the_ttl_cost_one_of_call
  case_pin_unpin_and_unpin_all_clear_the_chats_pins
  case_every_message_write_clears_the_accounts_pins
  case_a_failed_message_write_still_clears_the_pins
  case_pins_ttl_zero_reads_of_every_time
  case_head_read_on_a_deferred_chat_enqueues_its_backfill_once
  case_head_read_never_waits_on_the_backfill

Run: ./venv/bin/python service/tests/test_of_mirror_messages.py
"""
import asyncio
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import of_client  # noqa: E402
import server  # noqa: E402
import img_api  # noqa: E402

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

    orig = (server._get_client, server._resolve_account_id, server._reject_if_resale, img_api._pin_sent_media,
            employees.resolve_outbound_employee_id, rc.invalidate)
    server._get_client = lambda *a, **k: c
    server._resolve_account_id = lambda *a, **k: "acct"
    server._reject_if_resale = no_resale
    img_api._pin_sent_media = lambda *a, **k: None
    employees.resolve_outbound_employee_id = no_employee
    rc.invalidate = lambda *a, **k: None
    try:
        body = server.SendMessageBody(text="hi", tagged_users=[501], rf_guest=[77], rf_partner=[88, 89])
        asyncio.run(server.send_message(request=None, chat_id=FAN, body=body))
        plain = server.SendMessageBody(text="plain")
        asyncio.run(server.send_message(request=None, chat_id=FAN, body=plain))
    finally:
        (server._get_client, server._resolve_account_id, server._reject_if_resale, img_api._pin_sent_media,
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


async def case_mute_and_hide_routes_call_the_client():
    c = _client()
    orig = server._get_client, server._bust_chat_list_cache
    server._get_client = lambda: c
    server._bust_chat_list_cache = lambda *a, **k: None
    try:
        await server.of_mute_chat(FAN)
        await server.of_unmute_chat(FAN)
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

class _PinsClient:
    """A fake OF client for the pinned route: counts `/pinned` reads, records
    message writes; `fail_writes` makes every write raise OF's error."""

    def __init__(self):
        self.pinned_reads = 0
        self.writes = []
        self.fail_writes = False

    def get_pinned_messages(self, chat_id):
        self.pinned_reads += 1
        return [{"id": 100 + self.pinned_reads, "chat": chat_id}]

    def _answer(self, *write):
        self.writes.append(write)
        if self.fail_writes:
            raise of_client.OFAPIError(f"504 for https://onlyfans.com/api2/v2/messages/77/{write[0]}")
        return {"success": True}

    def pin_message(self, message_id, user_id):
        return self._answer("pin", message_id, user_id)

    def unsend_message(self, message_id, with_user_id=None):
        return self._answer("unsend", message_id, with_user_id)

    def hide_message(self, message_id, user_id):
        return self._answer("hide", message_id, user_id)

    def like_message(self, message_id):
        return self._answer("like", message_id)

    def unlike_message(self, message_id):
        return self._answer("unlike", message_id)

    def bookmark_message(self, message_id, group, on):
        return self._answer("bookmark" if on else "unbookmark", message_id)

    def unpin_message(self, message_id, user_id):
        return self._answer("unpin", message_id, user_id)

    def unpin_all_messages(self, chat_id):
        return self._answer("unpin_all", chat_id)


def _with_pins(ttl, run):
    """Run `async run(c)` with a fake pins client on account `acct-pins` and
    PINS_CACHE_TTL_S=`ttl` (None = unset, the default); returns the client."""
    import os
    c = _PinsClient()
    orig = (server._get_client, server._resolve_account_id, server._bust_chat_list_cache)
    orig_env = os.environ.get("PINS_CACHE_TTL_S")
    server._get_client = lambda *a, **k: c
    server._resolve_account_id = lambda *a, **k: "acct-pins"
    server._bust_chat_list_cache = lambda *a, **k: None
    if ttl is None:
        os.environ.pop("PINS_CACHE_TTL_S", None)
    else:
        os.environ["PINS_CACHE_TTL_S"] = ttl
    server.relay_cache.invalidate("chat_pinned", "acct-pins")
    try:
        asyncio.run(run(c))
    finally:
        (server._get_client, server._resolve_account_id, server._bust_chat_list_cache) = orig
        if orig_env is None:
            os.environ.pop("PINS_CACHE_TTL_S", None)
        else:
            os.environ["PINS_CACHE_TTL_S"] = orig_env
        server.relay_cache.invalidate("chat_pinned", "acct-pins")
    return c


def case_pins_two_reads_inside_the_ttl_cost_one_of_call():
    async def run(c):
        first = await server.get_pinned(FAN)
        second = await server.get_pinned(FAN)
        assert c.pinned_reads == 1, c.pinned_reads
        assert first == second == {"list": [{"id": 101, "chat": FAN}]}, (first, second)
        # Another chat is its own entry.
        await server.get_pinned(FAN + 1)
        assert c.pinned_reads == 2, c.pinned_reads
        # Concurrent opens of a cold chat share one OF read (the per-key lock).
        server.relay_cache.invalidate("chat_pinned", "acct-pins")
        await asyncio.gather(*(server.get_pinned(FAN) for _ in range(5)))
        assert c.pinned_reads == 3, c.pinned_reads
    _with_pins(None, run)


def case_pin_unpin_and_unpin_all_clear_the_chats_pins():
    async def run(c):
        await server.get_pinned(FAN)
        assert c.pinned_reads == 1
        for write in (lambda: server.of_pin_message(77, FAN),
                      lambda: server.of_unpin_message(77, FAN),
                      lambda: server.of_unpin_all_messages(FAN)):
            reads = c.pinned_reads
            assert write() == {"success": True}
            await server.get_pinned(FAN)
            assert c.pinned_reads == reads + 1, (c.writes[-1], c.pinned_reads)
            # ...and the read after that is cached again.
            await server.get_pinned(FAN)
            assert c.pinned_reads == reads + 1, (c.writes[-1], c.pinned_reads)
        assert c.writes == [("pin", 77, FAN), ("unpin", 77, FAN), ("unpin_all", FAN)], c.writes
    _with_pins(None, run)


class _UnsendReq:
    """The unsend route reads its optional `{withUserId}` body off the request."""

    async def body(self):
        return b'{"withUserId": %d}' % FAN


async def _unsend():
    return await server.of_unsend_message(_UnsendReq(), 77)


# Every message write route the pinned page offers, as the server handlers.
_MESSAGE_WRITES = (
    lambda: server.of_pin_message(77, FAN),
    lambda: server.of_unpin_message(77, FAN),
    lambda: server.of_unpin_all_messages(FAN),
    _unsend,
    lambda: server.of_hide_message(77, server._WithUserBody(withUserId=FAN)),
    lambda: server.of_like_message(77),
    lambda: server.of_unlike_message(77),
    lambda: server.of_bookmark_message(77, None),
    lambda: server.of_unbookmark_message(77, None),
)


def case_every_message_write_clears_the_accounts_pins():
    """Unsend, hide, like/unlike and bookmark/unbookmark name no chat, and the
    pinned page offers each: every one drops the account's pins (both chats)."""
    async def run(c):
        for write in _MESSAGE_WRITES[3:]:
            await server.get_pinned(FAN)
            await server.get_pinned(FAN + 1)
            reads = c.pinned_reads
            out = write()
            out = await out if asyncio.iscoroutine(out) else out
            assert out == {"success": True}, out
            await server.get_pinned(FAN)
            await server.get_pinned(FAN + 1)
            assert c.pinned_reads == reads + 2, (c.writes[-1], c.pinned_reads)
        assert [w[0] for w in c.writes] == ["unsend", "hide", "like", "unlike", "bookmark", "unbookmark"], c.writes
    _with_pins(None, run)


def case_a_failed_message_write_still_clears_the_pins():
    """OF may have applied a write it answered with an error (a timeout): every
    message write route drops the pins anyway, so the next read asks OF."""
    from fastapi import HTTPException

    async def run(c):
        c.fail_writes = True
        for write in _MESSAGE_WRITES:
            await server.get_pinned(FAN)
            reads = c.pinned_reads
            try:
                out = write()
                await out if asyncio.iscoroutine(out) else out
            except HTTPException as e:
                assert e.status_code == 502, (c.writes[-1], e.status_code)
            else:
                raise AssertionError(f"a failed write answered OK: {c.writes[-1]}")
            await server.get_pinned(FAN)
            assert c.pinned_reads == reads + 1, (c.writes[-1], c.pinned_reads)
        assert len(c.writes) == len(_MESSAGE_WRITES), c.writes
    _with_pins(None, run)


def case_pins_ttl_zero_reads_of_every_time():
    async def run(c):
        for _ in range(3):
            await server.get_pinned(FAN)
        assert c.pinned_reads == 3, c.pinned_reads
    _with_pins("0", run)


class _HeadClient:
    """A fake OF client for the messages route: counts OF reads per (chat, before_id)."""

    def __init__(self):
        self.reads = []

    def get_messages(self, chat_id, limit=10, order="desc", before_id=None):
        self.reads.append((chat_id, before_id))
        return {"list": [{"id": 500 + len(self.reads), "text": "hi", "fromUser": {"id": chat_id}}],
                "hasMore": False}


class _Req:
    """What `_current_priority` reads off the request in flight."""

    def __init__(self, priority):
        self.headers = {"x-priority": priority} if priority else {}


def _with_head(run):
    """Run `async run(c, read)` on account `acct-open` with a fake OF client; `read(chat, priority=None,
    before_id=None)` calls the route as that request would and lets its fired tasks finish."""
    import webhook_dispatch as wd
    c = _HeadClient()
    orig = (server._get_client, server._resolve_account_id)
    server._get_client = lambda *a, **k: c
    server._resolve_account_id = lambda *a, **k: "acct-open"
    wd._fan_scrape_claims.clear()

    async def read(chat, priority=None, before_id=None):
        token = server._request_ctx.set(_Req(priority))
        try:
            out = await server.get_messages(chat, limit=10, order="desc", before_id=before_id, refresh=True)
        finally:
            server._request_ctx.reset(token)
        await asyncio.gather(*(t for t in asyncio.all_tasks() if t.get_name().startswith("deferred-history")))
        return out

    try:
        asyncio.run(run(c, read))
    finally:
        server._get_client, server._resolve_account_id = orig
        wd._fan_scrape_claims.clear()
    return c


async def _seed_history(aid, fan, *, deferred):
    from datetime import datetime
    from db.engine import get_session
    from db.models import Account, ScrapeHistory
    now = datetime.utcnow()
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=None if deferred else 77,
                            last_scrape_at=now, history_deferred_at=now if deferred else None))


async def _backfills(aid):
    """{fan: deferred_history jobs} on `aid`."""
    import json
    from collections import Counter
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import ScheduledJob
    async with get_session() as s:
        rows = (await s.execute(select(ScheduledJob.payload_json).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == "scrape_chats"))).scalars().all()
    out = Counter()
    for p in rows:
        p = json.loads(p)
        assert p.get("source") == "deferred_history" and len(p["fan_ids"]) == 1, p
        out[p["fan_ids"][0]] += 1
    return dict(out)


def case_head_read_on_a_deferred_chat_enqueues_its_backfill_once():
    """A head read of a deferred chat enqueues its backfill once, at user and at background
    priority; a second read inside the window none; a not-deferred chat and an older page
    none; every head read still reaches OF."""
    aid, user_fan, bg_fan, plain_fan, older_fan = "acct-open", 9101, 9102, 9103, 9104

    async def run(c, read):
        await _seed_history(aid, user_fan, deferred=True)
        await _seed_history(aid, bg_fan, deferred=True)
        await _seed_history(aid, plain_fan, deferred=False)
        await _seed_history(aid, older_fan, deferred=True)
        out = await read(user_fan)
        assert out["list"][0]["id"] == 501, out
        assert await _backfills(aid) == {user_fan: 1}, await _backfills(aid)
        await read(user_fan)
        await read(user_fan, priority="background")
        assert await _backfills(aid) == {user_fan: 1}, await _backfills(aid)
        await read(bg_fan, priority="background")
        await read(plain_fan)
        await read(older_fan, before_id=400)
        assert await _backfills(aid) == {user_fan: 1, bg_fan: 1}, await _backfills(aid)
        assert c.reads == [(user_fan, None)] * 3 + [(bg_fan, None), (plain_fan, None), (older_fan, 400)], c.reads
    _with_head(run)


def case_head_read_never_waits_on_the_backfill():
    """The trigger is fired and forgotten: a backfill that never finishes holds no head read."""
    import webhook_dispatch as wd
    aid, fan = "acct-open", 9105
    gate = {}
    orig = wd.backfill_if_deferred

    async def stuck(*_a):
        await gate["ev"].wait()

    async def run(c, _read):
        gate["ev"] = asyncio.Event()
        await _seed_history(aid, fan, deferred=True)
        wd.backfill_if_deferred = stuck
        try:
            out = await asyncio.wait_for(server.get_messages(fan, limit=10, order="desc", before_id=None,
                                                             refresh=False), timeout=2)
        finally:
            wd.backfill_if_deferred = orig
            gate["ev"].set()
        assert out["list"] and c.reads == [(fan, None)], (out, c.reads)
    _with_head(run)


def case_messages_basic_grants_no_payment_route():
    """The mirror's Tip is disabled, so Messages Basic must not open POST /tips (a payment) to a chatter."""
    import permissions
    assert "/of-manager/messages" not in (permissions.route_pages("/api/of/v2/tips", "GET") or ()), \
        permissions.route_pages("/api/of/v2/tips", "GET")
    assert "/of-manager/messages" in permissions.route_pages("/api/of/v2/chats/1/messages", "GET")


_harness.run()
