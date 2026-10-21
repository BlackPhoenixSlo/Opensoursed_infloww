#!/usr/bin/env python3
"""POST /api/of/v2/posts extras, post labels, and the pin/like toggles.

The relay's create-post body keeps our snake_case names; of_client.create_post
is the one place they become OF's own keys, as OF's composer
(`MakeFeedPost getDataObject`, build 202610091632) sends them. Pin and like
are toggles on OF: unpin and unlike send the same POST again. Plain-assert,
OF faked (no request leaves the process).

  case_text_only_body_has_no_extras
  case_schedule_is_is_scheduled_plus_scheduled_date
  case_save_for_later_has_no_date
  case_vault_carrier_keeps_the_live_verified_posted_at
  case_expiry_target_labels
  case_poll_and_quiz
  case_route_forwards_every_field
  case_create_label_posts_name
  case_label_route_is_registered
  case_pin_and_unpin_are_the_same_post
  case_like_and_unlike_are_the_same_post
  case_unlike_route_forwards_the_author

Run: ./venv/bin/python service/tests/test_create_post_body.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402

AT = "2026-10-20T18:30:00+02:00"
OLD_KEYS = {"postedAt", "expirePeriod", "fundRaisingTarget", "votingDueDate"}


def _client():
    """An OFClient whose every request is recorded instead of sent."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"id": 1}
    return c


def _post_body(**kw):
    c = _client()
    c.create_post("Synthetic post", auto_tag=False, **kw)
    (method, path, kw), = c.sent
    assert (method, path) == ("POST", f"{of_client.API_BASE}/posts"), (method, path)
    body = kw["json_body"]
    assert not OLD_KEYS & body.keys(), body
    return body


def case_text_only_body_has_no_extras():
    assert _post_body() == {"text": "Synthetic post", "mediaFiles": [], "price": 0}


def case_schedule_is_is_scheduled_plus_scheduled_date():
    body = _post_body(posted_at=AT)
    assert body["isScheduled"] == 1 and body["scheduledDate"] == AT, body
    assert "isPublishedWithPeriod" not in body, body


def case_save_for_later_has_no_date():
    body = _post_body(save_for_later=True)
    assert body["isScheduled"] == 1 and body["isPublishedWithPeriod"] == 1, body
    assert "scheduledDate" not in body, body


def case_vault_carrier_keeps_the_live_verified_posted_at():
    # The vault carrier stays on the `postedAt` body it was verified live on;
    # the new scheduling keys are not verified live yet.
    c = _client()
    c.create_post("Synthetic post", carrier_posted_at=AT, auto_tag=False)
    (_m, _p, kw), = c.sent
    assert kw["json_body"] == {"text": "Synthetic post", "mediaFiles": [], "price": 0,
                               "postedAt": AT}, kw
    calls = []

    def _create(text, **kw):
        calls.append(kw)
        raise of_client.OFAPIError("stop after the create")

    c = _client()
    c.create_post = _create
    try:
        c.materialize_to_vault([{"id": 1}])
    except of_client.OFAPIError:
        pass
    kw, = calls
    assert kw.get("carrier_posted_at") and not kw.get("posted_at"), kw


def case_expiry_target_labels():
    body = _post_body(expire_days=7, fund_raising_target=50, label_ids=[11, "12"])
    assert body["expireDays"] == 7, body
    # OF sends the target only with presets; its composer's default preset is [5]
    assert body["fundRaisingTargetAmount"] == 50 and body["fundRaisingTipsPresets"] == [5], body
    assert body["labelIds"] == [11, 12], body
    body = _post_body(fund_raising_target=50, fund_raising_presets=[5, 10])
    assert body["fundRaisingTipsPresets"] == [5, 10], body


def case_poll_and_quiz():
    body = _post_body(voting_type=1, voting_options=["Yes", "No"], voting_due=7,
                      voting_correct_index=0)
    assert body["votingType"] == 1 and body["votingOptions"] == ["Yes", "No"], body
    assert body["votingDue"] == 7, body
    assert "votingCorrectIndex" not in body, body  # a poll has no correct answer
    body = _post_body(voting_type=2, voting_options=["A", "B", "C"], voting_due=7,
                      voting_correct_index=2)
    assert body["votingType"] == 2 and body["votingCorrectIndex"] == 2, body
    assert "votingType" not in _post_body(voting_type=1), "no options, no poll"


def case_route_forwards_every_field():
    calls = []

    class _Fake:
        def create_post(self, **kw):
            calls.append(kw)
            return {"id": 9}

    async def _not_paid(_req, _price):
        return None

    orig = server._get_client, server._refuse_paid_post_on_paid_page
    server._get_client = lambda: _Fake()
    server._refuse_paid_post_on_paid_page = _not_paid
    try:
        body = server._CreatePostBody(
            text="Synthetic post", save_for_later=True, expire_days=3,
            fund_raising_target=25, voting_type=2, voting_options=["A", "B"],
            voting_due=7, voting_correct_index=1, label_ids=[11])
        out = asyncio.run(server.of_create_post(None, body))
    finally:
        server._get_client, server._refuse_paid_post_on_paid_page = orig
    assert out == {"id": 9}, out
    kw, = calls
    want = {"save_for_later": True, "expire_days": 3, "fund_raising_target": 25,
            "fund_raising_presets": [], "voting_type": 2, "voting_options": ["A", "B"],
            "voting_due": 7, "voting_correct_index": 1, "label_ids": [11], "posted_at": None}
    assert {k: kw[k] for k in want} == want, kw


def case_create_label_posts_name():
    c = _client()
    c.create_label("Synthetic label")
    assert c.sent == [("POST", f"{of_client.API_BASE}/labels",
                       {"json_body": {"name": "Synthetic label"}})], c.sent


def case_label_route_is_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("POST", "/api/of/v2/labels") in routes, "POST /api/of/v2/labels missing"
    assert ("GET", "/api/of/v2/labels") in routes, "GET /api/of/v2/labels missing"


def case_pin_and_unpin_are_the_same_post():
    c = _client()
    c.pin_post(77)
    c.unpin_post(77)
    want = ("POST", f"{of_client.API_BASE}/posts/77/pin", {"params": {"format": "status"}})
    assert c.sent == [want, want], c.sent


def case_like_and_unlike_are_the_same_post():
    c = _client()
    c.like_post(77)
    c.unlike_post(77)
    want = ("POST", f"{of_client.API_BASE}/posts/77/favorites/4242", {})
    assert c.sent == [want, want], c.sent


def case_unlike_route_forwards_the_author():
    # wave6 B9: unliking another creator's post toggles HIS favorite, not mine.
    c = _client()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        server.of_unlike_post(2820237470, author_id=800000260)
    finally:
        server._get_client = orig
    assert c.sent == [("POST", f"{of_client.API_BASE}/posts/2820237470/favorites/800000260",
                       {})], c.sent


_harness.run()
