"""service/tests/test_of_message_body.py — send_message's wire body, pinned.

`SendsMixin._message_body` is send_message's body before the tag block, pulled
out as a pure function like `_mass_body`/`_post_body`. The expected dicts were
captured from send_message on origin/main 9b6dabd0d (auto_tag=False, so the tag
block leaves them as built) and are compared ITEM BY ITEM IN ORDER: the JSON OF
receives is byte-identical, not just equal as a dict.

Run:  ./venv/bin/python service/tests/test_of_message_body.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import json  # noqa: E402

from of_client import API_BASE, OFClient  # noqa: E402

# send_message's defaults: _message_body takes every arg, send_message owns these.
DEFAULTS = dict(locked_text=False, price=0, media_files=None, previews=None,
                is_forward=False, reply_to_message_id=None, giphy_id=None,
                rf_guest=None, rf_partner=None)

# (name, text, kwargs, expected body in wire order)
TABLE = [
    ('plain', 'hi', dict(),
     {'text': '<p>hi</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('empty_text', '', dict(),
     {'text': '', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('html', '<p>x</p>', dict(),
     {'text': '<p>x</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('multiline', 'a & b\n<c>', dict(),
     {'text': '<p>a &amp; b<br />&lt;c&gt;</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('ppv_locked_previews', 'pay', dict(price=5, locked_text=True, media_files=[1, 2, 3], previews=[1]),
     {'text': '<p>pay</p>', 'lockedText': True, 'mediaFiles': [1, 2, 3], 'price': 5, 'previews': [1], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('free_media', 'look', dict(media_files=[9]),
     {'text': '<p>look</p>', 'lockedText': False, 'mediaFiles': [9], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('price_no_media', 't', dict(price=3),
     {'text': '<p>t</p>', 'lockedText': False, 'mediaFiles': [], 'price': 3, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('previews_free', 't', dict(media_files=[1], previews=[1]),
     {'text': '<p>t</p>', 'lockedText': False, 'mediaFiles': [1], 'price': 0, 'previews': [1], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
    ('gif_no_text', '', dict(giphy_id=123),
     {'text': '', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False, 'giphyId': '123'}),
    ('gif_with_text', 'lol', dict(giphy_id='abc'),
     {'text': '<p>lol</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False, 'giphyId': 'abc'}),
    ('reply_forward', 're', dict(reply_to_message_id=55, is_forward=True),
     {'text': '<p>re</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': True, 'replyToMessageId': 55}),
    ('reply_zero', 're', dict(reply_to_message_id=0),
     {'text': '<p>re</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False, 'replyToMessageId': 0}),
    ('rf_guest_partner', 't', dict(rf_guest=['1', 2], rf_partner=[3]),
     {'text': '<p>t</p>', 'lockedText': False, 'mediaFiles': [], 'price': 0, 'previews': [], 'rfTag': [], 'rfGuest': [1, 2], 'rfPartner': [3], 'isForward': False}),
    ('float_price', 't', dict(price=4.99, media_files=[7], locked_text=False),
     {'text': '<p>t</p>', 'lockedText': False, 'mediaFiles': [7], 'price': 4.99, 'previews': [], 'rfTag': [], 'rfGuest': [], 'rfPartner': [], 'isForward': False}),
]


def case_message_body_table():
    for name, text, kw, want in TABLE:
        got = OFClient._message_body(text, **{**DEFAULTS, **kw})
        assert list(got.items()) == list(want.items()), (name, got)
        assert json.dumps(got) == json.dumps(want), name


def _capturing_client():
    c = OFClient.__new__(OFClient)
    c.account_id = "1"
    c.sent = []
    c._post_dropping_auto_cotag = lambda path, body, plan: c.sent.append((path, body, plan)) or {}
    return c


def case_send_message_posts_the_body():
    c = _capturing_client()
    for name, text, kw, want in TABLE:
        c.sent.clear()
        c.send_message("42", text, auto_tag=False, **kw)
        (path, body, plan), = c.sent
        assert path == f"{API_BASE}/chats/42/messages", path
        assert json.dumps(body) == json.dumps(want), (name, body)
        assert plan is None, name


def case_operator_tag_lands_in_rf_tag_after_build():
    """The tag block still runs on the built body: an explicit pick rides in
    `userTags` and `rfTag`; rfGuest/rfPartner keep the composer's values."""
    c = _capturing_client()
    c.send_message("42", "hi", tagged_users=["7"], rf_guest=[3], auto_tag=False)
    (_, body, plan), = c.sent
    assert body["userTags"] == [7] and body["rfTag"] == [7], body
    assert body["rfGuest"] == [3] and body["rfPartner"] == [], body
    assert plan is None, plan


_harness.run()
