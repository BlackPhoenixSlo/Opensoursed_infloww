#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

API = of_client.API_BASE
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "app", "lib", "__fixtures__", "of")


def _fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"id": 1}
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, kw)) or []
    return c


AID = "npt_acct"


async def _seed():
    async with get_session() as s:
        s.add(Account(id=AID))
asyncio.run(_seed())


def _route(fn, *args, **kwargs):
    c = _client()
    orig, orig_aid = server._get_client, server._current_aid
    server._get_client = lambda: c
    server._current_aid = lambda: AID
    try:
        out = fn(*args, **kwargs)
        if asyncio.iscoroutine(out):
            asyncio.run(out)
    finally:
        server._get_client, server._current_aid = orig, orig_aid
    return c.sent


def _one(sent):
    (method, path, kw), = sent
    return method, path, kw.get("json_body"), kw.get("params")


def case_promotion_free_trial_body():
    fx = _fixture("new-post-promotion-body.json")
    for case in fx["cases"]:
        sent = _route(server.of_create_promo, server._PromoBody(**case["relay"]))
        method, path, body, _ = _one(sent)
        assert (method, path) == ("POST", f"{API}/promotions"), (method, path)
        assert body == case["of"], (case["name"], body)


def case_promotion_rejects_bad_type():
    try:
        _route(server.of_create_promo, server._PromoBody(discount=100, subscribe_counts=0, type=["fans"]))
    except HTTPException as e:
        assert e.status_code == 422
    else:
        raise AssertionError("type ['fans'] was accepted")


def case_stop_promotion_is_finish():
    fx = _fixture("new-post-promotion-stop-body.json")
    sent = _route(server.of_finish_promo, fx["promo_id"])
    method, path, body, _ = _one(sent)
    assert (method, path) == (fx["of"]["method"], f"{API}{fx['of']['path']}"), (method, path)
    assert body == fx["of"]["body"], body


def case_trial_link_body():
    fx = _fixture("new-post-trial-body.json")
    for case in fx["cases"]:
        sent = _route(server.of_create_trial_link, server._TrialLinkBody(**case["relay"]))
        method, path, body, _ = _one(sent)
        assert (method, path) == ("POST", f"{API}/trials"), (method, path)
        assert body == case["of"], (case["name"], body)


def case_trial_sort_params():
    sent = _route(server.of_trial_links, field="claims_count", sort="asc")
    _, path, _, params = _one(sent)
    assert path == f"{API}/trials" and params == {"limit": 100, "offset": 0, "pagination": 1, "field": "claims_count", "sort": "asc"}, params
    sent = _route(server.of_trial_links, field=None, sort=None)
    _, _, _, params = _one(sent)
    assert params == {"offset": 0, "limit": 100}, params
    try:
        _route(server.of_trial_links, field="name", sort="asc")
    except HTTPException as e:
        assert e.status_code == 422
    else:
        raise AssertionError("field=name was accepted")


def case_trials_shared_with_me_and_share():
    sent = _route(server.of_trials_shared_with_me, limit=100, offset=0)
    _, path, _, params = _one(sent)
    assert path == f"{API}/trials/share-access" and params == {"limit": 100, "offset": 0, "pagination": 1}, (path, params)
    fx = _fixture("new-post-trial-share-body.json")
    sent = _route(server.of_share_trial_stats, server._ShareTrialBody(**fx["relay"]))
    method, path, body, _ = _one(sent)
    assert (method, path, body) == ("POST", f"{API}/trials/share-access", fx["of"]), (method, path, body)


def case_bundle_body():
    fx = _fixture("new-post-bundle-body.json")
    sent = _route(server.of_create_bundle, server._BundleBody(**fx["relay"]))
    method, path, body, _ = _one(sent)
    assert (method, path, body) == ("POST", f"{API}/subscriptions/bundles", fx["of"]), (method, path, body)
    try:
        _route(server.of_create_bundle, server._BundleBody(discount=10))
    except HTTPException as e:
        assert e.status_code == 422
    else:
        raise AssertionError("a bundle with no duration was accepted")


def case_user_search_is_ofs_search_box():
    sent = _route(server.of_search_users, q="alpha", limit=10, offset=0)
    _, path, _, params = _one(sent)
    assert path == f"{API}/users" and params == {"limit": 10, "offset": 0, "query": "alpha", "view": "se"}, params


def case_performers_and_posts_search():
    sent = _route(server.of_performers_search, query="alpha", limit=10, offset=0)
    _, path, _, params = _one(sent)
    assert path == f"{API}/users/performers-search" and params == {"limit": 10, "offset": 0, "query": "alpha"}, params
    sent = _route(server.of_search_posts, query="alpha", limit=10)
    _, path, _, params = _one(sent)
    assert path == f"{API}/posts" and params == {"limit": 10, "query": "alpha", "skip_users": "all", "format": "infinite"}, params


def case_release_forms_and_toggle():
    sent = _route(server.of_release_forms, limit=20, offset=0, filter="all", sort="name:asc", name="al")
    _, path, _, params = _one(sent)
    assert path == f"{API}/release-forms" and params == {"limit": 20, "offset": 0, "filter": "all", "sort": "name:asc", "name": "al"}, params
    fx = _fixture("new-post-tag-hide-body.json")
    sent = _route(server.of_toggle_release_form, server._ReleaseFormToggleBody(**fx["relay"]))
    method, path, body, _ = _one(sent)
    assert (method, path, body) == ("PATCH", f"{API}/release-forms/toggle-show", fx["of"]), (method, path, body)


def case_invite_guest():
    fx = _fixture("new-post-invite-body.json")
    sent = _route(server.of_create_guest, server._GuestBody(**fx["relay"]))
    method, path, body, _ = _one(sent)
    assert (method, path, body) == ("POST", f"{API}/guests/", fx["of"]), (method, path, body)


def case_label_sort():
    fx = _fixture("new-post-labels-sort-body.json")
    sent = _route(server.of_sort_labels, server._LabelSortBody(**fx["relay"]))
    method, path, body, _ = _one(sent)
    assert (method, path, body) == ("POST", f"{API}/labels/sort", fx["of"]), (method, path, body)


def case_new_routes_are_registered_before_their_catch_alls():
    paths = [(sorted(r.methods or []), r.path) for r in server.app.routes if hasattr(r, "methods")]

    def at(method, path):
        return next(i for i, (m, p) in enumerate(paths) if method in m and p == path)

    assert at("GET", "/api/of/v2/users/performers-search") < at("GET", "/api/of/v2/users/{user_id_or_username}")
    assert at("GET", "/api/of/v2/posts/search") < at("GET", "/api/of/v2/posts/{post_id}")
    for method, path in [("POST", "/api/of/v2/promotions/{promo_id}/finish"), ("POST", "/api/of/v2/trials/share-access"),
                         ("PATCH", "/api/of/v2/release-forms/toggle-show"), ("POST", "/api/of/v2/guests"),
                         ("POST", "/api/of/v2/labels/sort")]:
        at(method, path)


def case_formatted_text_and_media_bodies():
    for name in ("new-post-format-body.json", "new-post-media-body.json"):
        fx = _fixture(name)
        for case in fx.get("cases") or [fx]:
            relay = case["relay"]
            body = server._CreatePostBody(**relay)
            c = _client()
            c.create_post(body.text, media_files=body.media_files, price=body.price, auto_tag=False)
            (method, path, kw), = c.sent
            assert (method, path) == ("POST", f"{API}/posts"), (method, path)
            assert kw["json_body"] == case["of"], (name, kw["json_body"])


def case_video_story_body():
    fx = _fixture("new-post-story-video-body.json")
    c = _client()
    seen = {}

    def fake_upload(path, **kw):
        seen.update(kw)
        return fx["upload"]

    c.upload_media = fake_upload
    c.post_story("/tmp/synthetic-clip.mp4", content_type=fx["file"]["type"])
    assert seen.get("content_type") == "video/mp4" and seen.get("check_dedupe") is False, seen
    (method, path, kw), = c.sent
    assert (method, path) == (fx["of"]["method"], f"{API}{fx['of']['path']}"), (method, path)
    assert kw["json_body"] == fx["of"]["body"], kw["json_body"]


_harness.run()
