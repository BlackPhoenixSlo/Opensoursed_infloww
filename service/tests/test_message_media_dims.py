#!/usr/bin/env python3
"""
T-API — message-media dimension tests.

Covers the named cases that pin the render-stability dims pipeline
(18_chat_render_stability §1.1):

  case_dims_from_rest_not_rawjson (DA bug 1):
      OF REST media (files/info width/height) → message_media gets the dims;
      a WS-shaped media item (id only, the shape raw_json stores) → dims stay
      null. Proves raw_json is NOT the dims source.
  case_ofmedia_shape:
      GET /admin/messages/{account}/{fan} (the cold-start seed) returns a
      `media` array carrying width/height per item — present-but-null when
      unknown (the UI must tolerate null).

Run: ./venv/bin/python service/tests/test_message_media_dims.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import messages  # noqa: E402 — the router module under test (helpers + routes)
from db.engine import get_session  # noqa: E402
from db.models import Message, MessageMedia  # noqa: E402

client = _harness.make_client()


def _run(coro):
    """Drive an async seeder/reader to completion (sync test bodies)."""
    return asyncio.run(coro)


async def _seed_message(account_id: str, fan_id: int, message_id: int) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=account_id, fan_id=fan_id, message_id=message_id,
            direction="out", created_at=datetime.utcnow(),
        ))


async def _seed_media(
    account_id: str, fan_id: int, message_id: int, media_id: int,
    *, width: int | None, height: int | None, type_: str = "photo",
) -> None:
    async with get_session() as s:
        s.add(MessageMedia(
            account_id=account_id, fan_id=fan_id, message_id=message_id,
            media_id=media_id, type=type_, width=width, height=height,
        ))


# A media object shaped like OF's real REST /chats/{id}/messages response
# (verified against prod raw_json): natural dims live under files.full; the
# thumb is a 300x300 SQUARE that must NOT be used for the aspect ratio.
def _rest_media(media_id: int) -> dict:
    return {
        "id": media_id,
        "type": "photo",
        "files": {
            "full": {"url": "https://cdn/full.jpg", "width": 3024, "height": 4032},
            "thumb": {"url": "https://cdn/thumb.jpg", "width": 300, "height": 300},
            "preview": {"url": "https://cdn/preview.jpg", "width": 960, "height": 1280},
        },
    }


# A media object shaped like the WS event payload that lands in raw_json:
# id only, no files/info — so no dims are recoverable.
def _ws_media(media_id: int) -> dict:
    return {"id": media_id}


async def case_dims_from_rest_not_rawjson():
    account_id, fan_id = "100", 200
    rest_mid, rest_media_id = 5001, 9001
    ws_mid, ws_media_id = 5002, 9002

    # Parent messages must exist — message_media is a CASCADE child.
    await _seed_message(account_id, fan_id, rest_mid)
    await _seed_message(account_id, fan_id, ws_mid)

    rest_item = _rest_media(rest_media_id)
    ws_item = _ws_media(ws_media_id)

    # Extraction: REST yields the FULL dims (never the square thumb); WS none.
    assert messages.extract_media_dims(rest_item) == (3024, 4032), "REST files.full dims"
    assert messages.extract_media_dims(ws_item) == (None, None), "WS media (id only) → no dims"

    # The same holds when the WS item is round-tripped through raw_json — the
    # canonical proof raw_json can't be the dims source.
    parsed = json.loads(json.dumps({"id": ws_mid, "media": [ws_item]}))
    assert messages.extract_media_dims(parsed["media"][0]) == (None, None), "raw_json parse → no dims"

    # Reconcile both into message_media.
    async with get_session() as s:
        await messages.reconcile_rest_media(
            s, account_id, fan_id,
            [{"id": rest_mid, "media": [rest_item]}, {"id": ws_mid, "media": [ws_item]}],
        )

    async with get_session() as s:
        rest_row = await s.get(MessageMedia, (account_id, fan_id, rest_mid, rest_media_id))
        assert rest_row is not None, "REST media row written"
        assert rest_row.width == 3024 and rest_row.height == 4032, "REST dims persisted"
        assert rest_row.thumb_url == "https://cdn/thumb.jpg", "thumb_url persisted"
        assert rest_row.source_url == "https://cdn/full.jpg", "source_url = full url"

        ws_row = await s.get(MessageMedia, (account_id, fan_id, ws_mid, ws_media_id))
        assert ws_row is not None, "WS media row written (parent existed)"
        assert ws_row.width is None and ws_row.height is None, "WS dims stay null"


async def case_reconcile_skips_orphan_parents():
    # message_media is FK-CASCADE to messages; reconcile must NOT write (and
    # must not raise) for a message we haven't persisted yet.
    account_id, fan_id, orphan_mid, media_id = "100", 200, 5999, 9999
    async with get_session() as s:
        await messages.reconcile_rest_media(
            s, account_id, fan_id,
            [{"id": orphan_mid, "media": [_rest_media(media_id)]}],
        )
    async with get_session() as s:
        row = await s.get(MessageMedia, (account_id, fan_id, orphan_mid, media_id))
        assert row is None, "no row for an unpersisted (orphan) parent message"


async def case_rest_refresh_preserves_patched_dims():
    # A later REST fetch that lacks dims (OF still didn't size the item) must
    # NOT clobber a stored dim — COALESCE(excluded, existing).
    account_id, fan_id, mid, media_id = "103", 203, 6201, 7201
    await _seed_message(account_id, fan_id, mid)
    await _seed_media(account_id, fan_id, mid, media_id, width=800, height=600)
    async with get_session() as s:
        await messages.reconcile_rest_media(
            s, account_id, fan_id,
            [{"id": mid, "media": [_ws_media(media_id)]}],  # no dims this round
        )
    async with get_session() as s:
        row = await s.get(MessageMedia, (account_id, fan_id, mid, media_id))
        assert row.width == 800 and row.height == 600, "stored dims survive a dims-less refresh"


def case_ofmedia_shape():
    account_id, fan_id, mid = "101", 201, 6001
    sized_media, null_media = 7001, 7002
    _run(_seed_message(account_id, fan_id, mid))
    _run(_seed_media(account_id, fan_id, mid, sized_media, width=1080, height=1920))
    _run(_seed_media(account_id, fan_id, mid, null_media, width=None, height=None))

    r = client.get(f"/admin/messages/{account_id}/{fan_id}")
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    msgs = r.json()["messages"]
    row = next((m for m in msgs if m["message_id"] == mid), None)
    assert row is not None, "seeded message present in payload"

    media = row["media"]
    assert isinstance(media, list) and len(media) == 2, f"two media items, got {media!r}"
    by_id = {m["id"]: m for m in media}
    # Every item carries the width/height keys (nullable by design).
    for item in media:
        assert "width" in item and "height" in item, f"dims keys present: {item!r}"
    assert by_id[sized_media]["width"] == 1080 and by_id[sized_media]["height"] == 1920, "sized dims surfaced"
    assert by_id[null_media]["width"] is None and by_id[null_media]["height"] is None, "null dims tolerated (present-but-null)"


_harness.run(
    case_dims_from_rest_not_rawjson,
    case_reconcile_skips_orphan_parents,
    case_rest_refresh_preserves_patched_dims,
    case_ofmedia_shape,
)
