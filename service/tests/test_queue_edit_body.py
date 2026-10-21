#!/usr/bin/env python3
"""OF Manager Queue: Edit post, Edit message and Save for later bodies.

Edit post (relay PUT /api/of/v2/queue/posts/{id}) is OF's PUT /posts/{id} with the create body (MakeFeedPost sends
`px(post.id, getDataObject())`); Edit message is OF's PUT /messages/queue/{id}
with the message body (`654685.Os`: `isScheduled: 1` + `scheduledDate`, or
`isPublishedWithPeriod: 1` for saved for later), loaded first with
GET /messages/queue/{id}?format=scheduled. A mass message saved for later is
POST /messages/queue with `isPublishedWithPeriod: 1` and no date (relay POST
/api/of/v2/messages/queue/later), and must never take the send-now path. Shapes read from OF's bundles (build
202610091632), not verified live. Plain-assert, OF faked (no request leaves
the process).

  case_edit_post_puts_the_create_body
  case_edit_post_save_for_later
  case_edit_post_route_forwards_every_field
  case_queued_message_get
  case_edit_message_reschedules_with_lists_and_recipients
  case_edit_message_save_for_later_has_no_date
  case_edit_message_needs_a_schedule
  case_edit_message_route_refuses_no_schedule
  case_mass_save_for_later_body
  case_mass_route_save_for_later_takes_the_scheduled_branch
  case_later_route_saves_for_later
  case_routes_are_registered

Run: ./venv/bin/python service/tests/test_queue_edit_body.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402

AT = "2026-11-27T20:15:00+02:00"


def _client():
    """An OFClient whose every request is recorded instead of sent."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"id": 1}
    return c


def case_edit_post_puts_the_create_body():
    c = _client()
    c.save_queued_post(2433845504, "Synthetic post", media_files=[11, 12], price=5, posted_at=AT, label_ids=[3])
    (method, path, kw), = c.sent
    assert (method, path) == ("PUT", f"{of_client.API_BASE}/posts/2433845504"), (method, path)
    assert kw["json_body"] == {"text": "Synthetic post", "mediaFiles": [11, 12], "price": 5,
                               "isScheduled": 1, "scheduledDate": AT, "labelIds": [3]}, kw


def case_edit_post_save_for_later():
    c = _client()
    c.save_queued_post(7, "Synthetic post", save_for_later=True)
    (_, _, kw), = c.sent
    assert kw["json_body"] == {"text": "Synthetic post", "mediaFiles": [], "price": 0,
                               "isScheduled": 1, "isPublishedWithPeriod": 1}, kw


def case_edit_post_route_forwards_every_field():
    calls = []

    class _Fake:
        def save_queued_post(self, post_id, text, **kw):
            calls.append((post_id, text, kw))
            return {"id": post_id}

    async def _not_paid(_req, _price):
        return None

    orig = server._get_client, server._refuse_paid_post_on_paid_page
    server._get_client = lambda: _Fake()
    server._refuse_paid_post_on_paid_page = _not_paid
    try:
        body = server._CreatePostBody(text="Synthetic post", media_files=[11], posted_at=AT, label_ids=[3])
        out = asyncio.run(server.of_save_queued_post(55, None, body))
    finally:
        server._get_client, server._refuse_paid_post_on_paid_page = orig
    assert out == {"id": 55}, out
    (post_id, text, kw), = calls
    assert (post_id, text) == (55, "Synthetic post")
    want = {"media_files": [11], "posted_at": AT, "save_for_later": False, "label_ids": [3], "price": 0}
    assert {k: kw[k] for k in want} == want, kw


def case_queued_message_get():
    c = _client()
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, kw)) or {}
    c.queued_message(31)
    assert c.sent == [("GET", f"{of_client.API_BASE}/messages/queue/31", {"params": {"format": "scheduled"}})], c.sent


def case_edit_message_reschedules_with_lists_and_recipients():
    c = _client()
    c.edit_queued_message(31, text="Synthetic message", scheduled_date=AT, user_ids=[501, 502],
                          user_lists=["fans", "1234"], excluded_user_lists=["99"], price=5, media_files=[11])
    (method, path, kw), = c.sent
    assert (method, path) == ("PUT", f"{of_client.API_BASE}/messages/queue/31"), (method, path)
    assert kw["json_body"] == {"text": "Synthetic message", "lockedText": False, "mediaFiles": [11], "price": 5,
                               "previews": [], "userIds": [501, 502], "userLists": ["fans", "1234"],
                               "excludedLists": ["99"], "isScheduled": 1, "scheduledDate": AT}, kw


def case_edit_message_save_for_later_has_no_date():
    c = _client()
    c.edit_queued_message(31, text="Synthetic message", save_for_later=True, user_lists=["fans"])
    (_, _, kw), = c.sent
    body = kw["json_body"]
    assert body["isPublishedWithPeriod"] == 1 and "scheduledDate" not in body and "isScheduled" not in body, body


def case_edit_message_needs_a_schedule():
    c = _client()
    try:
        c.edit_queued_message(31, text="Synthetic message", user_lists=["fans"])
    except ValueError:
        pass
    else:
        raise AssertionError("an edit with no schedule must not be sent")
    assert c.sent == [], c.sent


def case_edit_message_route_refuses_no_schedule():
    try:
        server.of_edit_queued_message(31, server._EditQueuedMessageBody(text="Synthetic message", user_lists=["fans"]))
    except HTTPException as e:
        assert e.status_code == 422, e
    else:
        raise AssertionError("PUT with no schedule must be refused")


def case_mass_save_for_later_body():
    c = _client()
    c.schedule_mass_message(text="Synthetic message", save_for_later=True, user_lists=["fans"], auto_tag=False)
    (method, path, kw), = c.sent
    assert (method, path) == ("POST", f"{of_client.API_BASE}/messages/queue"), (method, path)
    body = kw["json_body"]
    assert body["isPublishedWithPeriod"] == 1 and "scheduledDate" not in body, body


def case_mass_route_save_for_later_takes_the_scheduled_branch():
    """Save for later must never reach send_mass_message (an immediate blast)."""
    import inspect
    src = inspect.getsource(server.of_send_or_schedule_mass)
    assert "if body.scheduled_date or body.save_for_later:" in src, "SFL must take the scheduled branch"
    assert "save_for_later=body.save_for_later" in src


def case_later_route_saves_for_later():
    """POST /api/of/v2/messages/queue/later forces save_for_later and no date, then takes the mass route."""
    seen = []

    async def _fake(request, body):
        seen.append((body.save_for_later, body.scheduled_date))
        return {"id": 1}

    orig = server.of_send_or_schedule_mass
    server.of_send_or_schedule_mass = _fake
    try:
        asyncio.run(server.of_save_mass_for_later(None, server._MassScheduleBody(text="x", user_lists=["fans"], scheduled_date="2026-11-07T10:00:00+01:00")))
    finally:
        server.of_send_or_schedule_mass = orig
    assert seen == [(True, None)], seen


def case_routes_are_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for want in [("GET", "/api/of/v2/messages/queue/{queue_id:int}"), ("PUT", "/api/of/v2/messages/queue/{queue_id:int}"),
                 ("PUT", "/api/of/v2/queue/posts/{post_id}"), ("POST", "/api/of/v2/messages/queue/later")]:
        assert want in routes, f"{want} missing"


_harness.run()
