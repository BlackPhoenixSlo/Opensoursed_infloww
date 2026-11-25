#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"id": 1}
    return c


def _poll_body(**kw):
    c = _client()
    c.create_post("Synthetic post", voting_type=1, voting_options=["Yes", "No"], auto_tag=False, **kw)
    (method, path, kw), = c.sent
    assert (method, path) == ("POST", f"{of_client.API_BASE}/posts"), (method, path)
    return kw["json_body"]


def case_poll_length_is_voting_due():
    body = _poll_body(voting_due=3)
    assert body == {"text": "Synthetic post", "mediaFiles": [], "price": 0,
                    "votingType": 1, "votingOptions": ["Yes", "No"], "votingDue": 3}, body


def case_poll_no_limit_sends_no_voting_due():
    body = _poll_body(voting_due=None)
    assert "votingDue" not in body, body
    assert body["votingOptions"] == ["Yes", "No"], body


def case_story_by_vault_id_body():
    c = _client()
    c.create_story([62])
    assert c.sent == [("POST", f"{of_client.API_BASE}/stories", {"json_body": {
        "mediaFiles": [62], "rfTag": [], "rfGuest": [], "rfPartner": []}})], c.sent


class _Fake:
    def __init__(self):
        self.calls = []

    def create_story(self, media_files, **kw):
        self.calls.append(("create_story", media_files, kw))
        return {"id": 5}

    def post_story_from_url(self, url, **kw):
        self.calls.append(("post_story_from_url", url, kw))
        return {"id": 6}


def _route(**body):
    fake = _Fake()
    orig, orig_aid = server._get_client, server._current_aid
    server._get_client = lambda: fake
    server._current_aid = lambda: "of_story_acct"
    try:
        out = asyncio.run(server.of_create_story(server._CreateStoryBody(**body)))
    finally:
        server._get_client, server._current_aid = orig, orig_aid
    return out, fake.calls


def case_story_route_forwards_media_files():
    out, calls = _route(media_files=[62])
    assert out == {"id": 5}, out
    assert calls == [("create_story", [62], {"caption": None, "mention": None, "question": None})], calls


def case_story_route_reuploads_media_url():
    url = "https://cdn.example/61-full.jpg"
    out, calls = _route(media_url=url)
    assert out == {"id": 6}, out
    (name, got, _kw), = calls
    assert (name, got) == ("post_story_from_url", url), calls


_harness.run()
