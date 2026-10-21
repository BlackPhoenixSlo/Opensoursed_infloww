#!/usr/bin/env python3
"""
Co-performer auto-tag — media that isn't PROVABLY solo goes out @-tagged.

OF's release-form rule: content showing anyone besides the account owner has to
name them. Every automated sender attaches vault media through one of five
`of_client` bodies, and none of them ever set `userTags` — so the decision is
made in `media_cotag` and enforced in those five bodies, not at the ~20 call
sites. These cases pin both halves.

  case_solo_media_is_not_tagged          a described solo item stays clean
  case_partner_visible_is_tagged         partner_visible: true → tagged
  case_people_count_two_is_tagged        people_count: 2 → tagged
  case_partner_act_beats_the_count       blowjob + people_count:1 → tagged
  case_undescribed_media_is_tagged       no describe fields → tagged (fail safe)
  case_missing_vault_row_is_tagged       id we've never collected → tagged
  case_one_bad_item_taints_the_bundle    4 solo + 1 partner → tagged
  case_text_only_send_is_not_tagged      no media → nothing to tag
  case_mass_and_post_bodies_tag_too      the other four send bodies
  case_operator_tags_survive             explicit picks are added to, not replaced
  case_no_duplicate_when_operator_picked_same
  case_auto_tag_false_opts_out           the manual composer path
  case_unresolvable_handle_sends_untagged  OF would 400 an unknown id
  case_disabled_by_env
  case_of_rejection_resends_without_tag  a stale tag must not kill the send
  case_rejection_invalidates_the_cached_id  ...nor cost a 400 on every send after
  case_operator_tag_rejection_still_raises
  case_lookup_failure_tags_anyway        a DB error is not proof she's alone
  case_lookup_tag_id_ignores_the_cache   the probe's entry point

The Brain's per-account overrides (account_ai_config, 2026-08-19 — a video the
describe pass read as solo still shows the POV partner, which is how Blake1/2
clips shipped untagged; the video rule is a collab-account OPT-IN because most
creators are solo):

  case_solo_video_not_tagged_by_default  the video rule ships OFF, no row needed
  case_null_brain_row_keeps_the_video_default   a row with NULLs ≡ no row
  case_video_rule_on_tags_solo_videos    the opt-in, photos still verdict-only
  case_brain_username_is_folded_on_both_paths  ...the userTags AND story paths
  case_brain_username_change_invalidates_the_cached_id
  case_forget_account_cfg_re_resolves    the Brain save path's narrow drop

"Tag a co-creator, which one, or no one" (ticket 85, 2026-10-21 — the built-in
default handle was the test creator's own, so every media send there logged an
ERROR for a tag that could never resolve):

  case_no_handle_configured_means_no_tag     the default: no tag, no lookup, no ERROR
  case_a_real_miss_still_logs_the_error      a configured miss stays loud

Run: ./venv/bin/python service/tests/test_media_cotag.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import json          # noqa: E402
import os            # noqa: E402

import media_cotag   # noqa: E402
import of_client     # noqa: E402
from db.engine import DATABASE_URL  # noqa: E402

ACCOUNT = "900001"
TAG_ID = 555_111


# ── Fixtures ────────────────────────────────────────────────────────

def _sync_exec(*statements: tuple[str, dict]) -> None:
    """Run SQL through a throwaway sync engine on the harness DB — the same
    shape media_cotag itself reads through."""
    from sqlalchemy import create_engine, text

    url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            for sql, params in statements:
                conn.execute(text(sql), params)
    finally:
        eng.dispose()


def _seed_vault(rows: dict[int, dict | None], *, kind: str = "photo") -> None:
    """Write vault_items the way media_cotag reads them. `None` fields = the
    row exists but was never described."""
    _sync_exec(
        ("INSERT OR IGNORE INTO accounts (id) VALUES (:a)", {"a": ACCOUNT}),
        *((
            "INSERT OR REPLACE INTO vault_items "
            "(account_id, media_id, kind, tags, send_count, created_at, "
            " ai_fields_json) "
            "VALUES (:a, :m, :k, '[]', 0, CURRENT_TIMESTAMP, :f)",
            {"a": ACCOUNT, "m": media_id, "k": kind,
             "f": json.dumps(fields) if fields is not None else None},
        ) for media_id, fields in rows.items()),
    )


# The co-creator the cases below tag. Nothing is tagged by default (ticket 85),
# so the decision cases run as an account whose Brain HAS a co-creator to tag.
COHANDLE = "cohandle"


def _seed_brain(**cols) -> None:
    """This account's Brain row (account_ai_config), the way a Save stores it.
    The co-creator is COHANDLE unless `cotag_username` is given; every other
    column not given is NULL."""
    cols.setdefault("cotag_username", COHANDLE)
    names = "".join(f", {k}" for k in cols)
    binds = "".join(f", :{k}" for k in cols)
    _sync_exec((
        "INSERT OR REPLACE INTO account_ai_config "
        f"(account_id, utc_offset, daily_cost_cap_cents{names}) "
        f"VALUES (:a, 0, 100{binds})", {"a": ACCOUNT, **cols}))


def _clear_brain() -> None:
    _sync_exec(("DELETE FROM account_ai_config WHERE account_id = :a",
                {"a": ACCOUNT}))


def _client(*, friend_hit: bool = True, reject_status: int | None = None,
            reject_id: int = TAG_ID, handle_in_list: str | None = None):
    """A REAL OFClient that skips __init__ (no session/signing needed), with the
    two seams that would touch the network stubbed out.

    Same shape as test_of_client_mass_body's `_client`. Deliberately not a
    lookalike class rebinding the send methods off OFClient: a lookalike is only
    faithful until a send body starts calling some other method on `self`, and
    then it passes while the real client raises AttributeError.
    """
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.account_id = ACCOUNT
    c.captured: list[tuple[str, dict]] = []
    c.friend_lookups = 0

    def _tagged_friend_users(*, search=None, limit=20, **_kw):
        c.friend_lookups += 1
        if not friend_hit:
            return {"items": [], "hasMore": False}
        return {"items": [
            {"id": 999, "name": "Someone Else", "type": "user",
             "user": {"id": 999, "username": "someoneelse"}},
            {"id": TAG_ID, "name": "Founder", "type": "user",
             "user": {"id": TAG_ID,
                      "username": handle_in_list or COHANDLE}},
        ], "hasMore": False}

    def _post_json(path, json_body=None):
        c.captured.append((path, json_body))
        # OF refuses a SPECIFIC id it does not accept — it does not refuse the
        # field. Modelling it as "any body carrying tags" made the retry
        # untestable: a retry that correctly kept the operator's pick looked
        # identical to one that failed, which is how the blanking bug shipped.
        body = json_body or {}
        tagged = list(body.get("userTags") or []) + list(body.get("rfTag") or [])
        if reject_status is not None and reject_id in tagged:
            resp = type("R", (), {"status_code": reject_status})()
            raise of_client.OFAPIError(
                f"{reject_status} for {path}\n"
                '{"error":{"code":400,"message":"tag id is invalid"}}', response=resp)
        return {"id": 1}

    c.tagged_friend_users = _tagged_friend_users
    c.post_json = _post_json
    c.last_body = lambda: c.captured[-1][1]
    return c


def _reset():
    """Fresh caches, no env, and the account's Brain row back to tagging
    COHANDLE."""
    media_cotag.reset_caches()
    os.environ.pop("OF_COTAG_ENABLED", None)
    _seed_brain()


class _Errors:
    """Collects ERROR records from media_cotag's logger for one block."""

    def __enter__(self):
        import logging

        self.records: list = []
        outer = self

        class _H(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    outer.records.append(record.getMessage())

        self._h = _H()
        logging.getLogger("of-relay.media_cotag").addHandler(self._h)
        return self.records

    def __exit__(self, *exc):
        import logging

        logging.getLogger("of-relay.media_cotag").removeHandler(self._h)
        return False


SOLO = {"people_count": 1, "partner_visible": False, "primary_folder": "nude_stills"}
PARTNER = {"people_count": 1, "partner_visible": True}
TWO_PEOPLE = {"people_count": 2, "partner_visible": False}
# people_count says one, the act says two. `is_solo` reads the act.
BLOWJOB = {"people_count": 1, "partner_visible": False, "acts": ["blowjob"]}
UNDESCRIBED: dict = {}


_seed_vault({
    10: SOLO, 11: SOLO, 12: SOLO, 13: SOLO,
    20: PARTNER,
    21: TWO_PEOPLE,
    22: BLOWJOB,
    30: UNDESCRIBED,
})
# VIDEOS. 40 is the Blake1/Blake2 hole in miniature: the describe verdict says
# solo, the POV partner is in the clip anyway. 41 pins that the describe
# verdict governs videos with or without the opt-in — the knob only adds tags.
_seed_vault({40: SOLO, 41: PARTNER}, kind="video")


# ── The decision ────────────────────────────────────────────────────

def case_solo_media_is_not_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[10])
    assert "userTags" not in c.last_body(), c.last_body()


def case_partner_visible_is_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[20])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_people_count_two_is_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[21])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_partner_act_beats_the_count():
    """The describe pass returns `people_count: 1` on partner acts often enough
    to matter — it counts the person the clip is ABOUT. The act is the tell."""
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[22])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_undescribed_media_is_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[30])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_missing_vault_row_is_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[7777777])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_one_bad_item_taints_the_bundle():
    _reset()
    c = _client()
    c.send_message(4242, "set of five", media_files=[10, 11, 12, 13, 20])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_text_only_send_is_not_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "hey you")
    assert "userTags" not in c.last_body(), c.last_body()
    assert c.friend_lookups == 0, "text-only send should not cost an OF lookup"


# ── Every send body, not just the 1:1 one ───────────────────────────

def case_every_body_that_carries_media_tags_it():
    """All four non-chat bodies, in both fields, in one pass.

    The queue and the wall had `userTags` and no `rfTag` — that is why mass PPVs
    shipped untagged for months (prod, August 2026: 1,903 mass `ppv_send`
    messages with intact `raw_json`, every one `releaseForms: []`, while the 1:1
    lane landed its tags). `userTags` was never the field: it appears in ZERO
    captured OF chunks, and OF's own composer spreads `{rfTag, rfGuest,
    rfPartner}` into the chat body, the scheduled/queue body (same builder, plus
    `isScheduled`) and the post body alike. The full trio, not just `rfTag`:
    that is the shape OF emits, and a partial one is a guess."""
    _reset()
    c = _client()
    for label, send in (
        ("send_mass_message",
         lambda: c.send_mass_message("blast", user_lists=["fans"], media_files=[20])),
        ("create_post",
         lambda: c.create_post("wall post", media_files=[21])),
        ("schedule_message",
         lambda: c.schedule_message(4242, "later",
                                    scheduled_date="2026-09-01T10:00:00+00:00",
                                    media_files=[22])),
        ("schedule_mass_message",
         lambda: c.schedule_mass_message(text="later blast",
                                         scheduled_date="2026-09-01T10:00:00+00:00",
                                         user_lists=["fans"], media_files=[30])),
    ):
        send()
        body = c.last_body()
        assert body.get("userTags") == [TAG_ID], (label, body)
        assert body.get("rfTag") == [TAG_ID], (label, body)
        assert body.get("rfGuest") == [], (label, body)
        assert body.get("rfPartner") == [], (label, body)


# ── WHERE the tag rides ─────────────────────────────────────────────
# `userTags` does nothing on ANY OF endpoint. Proven live 2026-08-16 for the 1:1
# chat send: two sends carrying it (an operator pick and the auto co-tag, both
# ids on the account's tagged-friend list) returned 200 and stored
# `releaseForms: []`. The queue looked like the exception and was not — 2026-08-23
# read 1,903 August mass `ppv_send` messages out of prod and every one stored
# `releaseForms: []` too. OF web never sends `userTags` at all: its composer
# marshals the ids into the release-form arrays, `rfTag` taking the
# `type: "user"` picks, and every send body it builds carries the trio.

def case_chat_send_fills_the_release_form_array():
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20])
    assert c.last_body().get("rfTag") == [TAG_ID], c.last_body()
    # userTags stays: it has been tolerated on the wire for months and dropping
    # it is a separate change, and one helper writes both fields so the paths
    # can't drift apart.
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_operator_picks_reach_the_release_form_array_too():
    """The composer's TAGGED chip is the case that sent this looking: an
    operator picked a creator, OF answered 200, and the tag was nowhere."""
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20], tagged_users=[314159],
                   auto_tag=False)
    assert c.last_body().get("rfTag") == [314159], c.last_body()


def case_untagged_chat_send_leaves_the_array_empty():
    _reset()
    c = _client()
    c.send_message(4242, "just me", media_files=[10])
    assert c.last_body().get("rfTag") == [], c.last_body()


def case_an_untagged_queue_send_grows_no_release_form_arrays():
    """Solo media on the queue leaves the body exactly as it was — the arrays
    are what we ADD to say something, not shape we owe the endpoint. (The chat
    body is the exception: it declares them itself, so its empty `rfTag` stays
    — `case_untagged_chat_send_leaves_the_array_empty` pins that.)"""
    _reset()
    c = _client()
    c.send_mass_message("blast", user_lists=["fans"], media_files=[10])
    body = c.last_body()
    assert "userTags" not in body, body
    for key in ("rfTag", "rfGuest", "rfPartner"):
        assert key not in body, (key, body)


def case_a_refused_queue_tag_retries_without_the_arrays_at_all():
    """The fallback body has to be the one that has been shipping all along.

    On the chat send the rf* arrays are OF's required shape, so the retry empties
    them. On the queue they are OURS — if OF ever refuses the field itself there,
    emptying it would refuse again and the retry would raise, taking a mass PPV
    down over a tag. With no operator pick to preserve, they come back out."""
    _reset()
    c = _client(reject_status=400)
    c.send_mass_message("blast", user_lists=["fans"], media_files=[20])
    assert len(c.captured) == 2, c.captured
    assert c.captured[0][1].get("rfTag") == [TAG_ID], c.captured[0][1]
    retried = c.last_body()
    assert "userTags" not in retried, retried
    for key in ("rfTag", "rfGuest", "rfPartner"):
        assert key not in retried, (key, retried)
    assert retried.get("mediaFiles") == [20], retried


def case_a_refused_queue_tag_keeps_the_operators_pick():
    """...but never at the cost of a human's own pick. An operator who tagged
    someone on a broadcast keeps their `rfTag` on the retry; if OF refuses THAT
    body too it raises, which is the same contract the chat send has had."""
    _reset()
    c = _client(reject_status=400)
    c.send_mass_message("blast", user_lists=["fans"], media_files=[20],
                        tagged_users=[314159])
    assert len(c.captured) == 2, c.captured
    assert c.captured[0][1].get("rfTag") == [314159, TAG_ID], c.captured[0][1]
    assert c.last_body().get("rfTag") == [314159], c.last_body()
    assert c.last_body().get("userTags") == [314159], c.last_body()


def case_retry_keeps_the_operators_pick_and_drops_only_ours():
    """The retry must strip OUR id, not the human's.

    Both sources share ONE array (`explicit + extra`), so a boolean "did we add
    one?" left the retry unable to strip selectively — it blanked the field, and
    the media went out with the operator's own release-form pick silently gone
    behind a 200. That is the violation this module exists to prevent, arriving
    by way of its own safety net.

    Reachable from plain UI: the composer's tag chips plus a quick-send delay go
    to `/api/of/v2/scheduled-sends` -> `scheduled_send.py`, which passes
    `tagged_users=` and leaves `auto_tag` at its default True. (That default is
    deliberate and stays: automations enqueue `scheduled_send` jobs too --
    server.py's `send_purpose` comment -- so forcing it False there would take
    the co-tag off automated multi-person sends.)"""
    _reset()
    c = _client(reject_status=400)
    c.send_message(4242, "collab", media_files=[20], tagged_users=[314159])
    assert len(c.captured) == 2, c.captured
    first = c.captured[0][1]
    assert first.get("rfTag") == [314159, TAG_ID], first
    # Second attempt: the human's pick survives, ours is gone.
    assert c.last_body().get("rfTag") == [314159], c.last_body()
    assert c.last_body().get("userTags") == [314159], c.last_body()
    assert c.last_body().get("mediaFiles") == [20], c.last_body()


def case_rejected_tag_retry_empties_the_release_form_array():
    """The tag can never cost a send — and the retry has to strip BOTH fields
    now. `rfTag` is emptied, not dropped: the rf* arrays are part of the shape
    OF requires, and omitting them is what used to 400 creator-to-creator."""
    _reset()
    c = _client(reject_status=400)
    c.send_message(4242, "collab", media_files=[20])
    assert len(c.captured) == 2, c.captured
    assert "userTags" not in c.last_body(), c.last_body()
    assert c.last_body().get("rfTag") == [], c.last_body()


# ── Interaction with the operator's own picks ───────────────────────

def case_operator_tags_survive():
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20], tagged_users=[314159])
    assert c.last_body().get("userTags") == [314159, TAG_ID], c.last_body()


def case_operator_tags_land_on_a_text_only_send():
    """Pins pre-existing behaviour through the refactor: `_apply_cotags` took
    over writing `userTags`, and the auto path skips text-only sends — an
    operator's own picks must still reach the wire on one."""
    _reset()
    c = _client()
    c.send_message(4242, "no media, still tagging you", tagged_users=[314159])
    assert c.last_body().get("userTags") == [314159], c.last_body()
    assert c.friend_lookups == 0, "no media → no auto-tag lookup"


def case_no_duplicate_when_operator_picked_same():
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20], tagged_users=[TAG_ID])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_auto_tag_false_opts_out():
    """The manual chat composer: a human is looking at the tag picker."""
    _reset()
    c = _client()
    c.send_message(4242, "manual", media_files=[20], auto_tag=False)
    assert "userTags" not in c.last_body(), c.last_body()


# ── Failing safe ────────────────────────────────────────────────────

def case_unresolvable_handle_sends_untagged():
    """OF 400s a `userTags` id that isn't on the caller's tagged-friend list, so
    an unresolvable handle must NOT be guessed — that would take every media
    send on the account offline. Send untagged and shout in the log."""
    _reset()
    c = _client(friend_hit=False)
    c.send_message(4242, "here you go", media_files=[20])
    assert "userTags" not in c.last_body(), c.last_body()
    # And the miss is cached — one lookup, not one per send.
    c.send_message(4242, "again", media_files=[21])
    assert c.friend_lookups == 1, c.friend_lookups


def case_disabled_by_env():
    _reset()
    os.environ["OF_COTAG_ENABLED"] = "0"
    try:
        c = _client()
        c.send_message(4242, "here you go", media_files=[20])
        assert "userTags" not in c.last_body(), c.last_body()
    finally:
        _reset()


def case_of_rejection_resends_without_tag():
    """A tag OF refuses must cost a mention, never the message."""
    _reset()
    c = _client(reject_status=400)
    result = c.send_message(4242, "here you go", media_files=[20])
    assert result == {"id": 1}, result
    assert len(c.captured) == 2, c.captured
    assert c.captured[0][1].get("userTags") == [TAG_ID], c.captured[0][1]
    assert "userTags" not in c.captured[1][1], c.captured[1][1]
    # The media still went — degrading the tag must not degrade the send.
    assert c.captured[1][1]["mediaFiles"] == [20], c.captured[1][1]


def case_rejection_invalidates_the_cached_id():
    """A refused tag must not be re-offered for the rest of its TTL, or every
    send in the next hour pays POST → 400 → POST."""
    _reset()
    c = _client(reject_status=400)
    c.send_message(4242, "first", media_files=[20])
    assert c.friend_lookups == 1, c.friend_lookups
    assert len(c.captured) == 2, "tagged POST + untagged retry"

    # Second send re-resolves rather than reusing the id OF just refused.
    c.send_message(4242, "second", media_files=[21])
    assert c.friend_lookups == 2, ("rejected id was served from cache",
                                   c.friend_lookups)


def case_operator_tag_rejection_still_raises():
    """We only retry away tags WE added. An operator's rejected pick is a real
    error and has to surface, not get silently stripped."""
    _reset()
    c = _client(reject_status=400, reject_id=314159)
    try:
        c.send_message(4242, "manual", media_files=[10], tagged_users=[314159],
                       auto_tag=False)
    except of_client.OFAPIError:
        assert len(c.captured) == 1, c.captured
    else:
        raise AssertionError("expected the operator's rejected tag to raise")


def case_lookup_failure_tags_anyway():
    """A vault read that fails is not evidence that she is alone."""
    _reset()
    original = media_cotag._describe_rows

    def _boom(*_a, **_kw):
        raise RuntimeError("database is locked")

    media_cotag._describe_rows = _boom
    try:
        c = _client()
        c.send_message(4242, "here you go", media_files=[10])   # a SOLO item
        assert c.last_body().get("userTags") == [TAG_ID], c.last_body()
    finally:
        media_cotag._describe_rows = original
        _reset()


def case_lookup_tag_id_ignores_the_cache():
    """The public probe entry point. `tag_user_id` serves a cached id, which
    would make a probe report a tag OF has not agreed to since. `lookup_tag_id`
    always asks OF."""
    _reset()
    c = _client()
    assert media_cotag.tag_user_id(c) == TAG_ID
    assert media_cotag.tag_user_id(c) == TAG_ID
    assert c.friend_lookups == 1, "sends should serve the cached id"

    assert media_cotag.lookup_tag_id(c) == TAG_ID
    assert c.friend_lookups == 2, c.friend_lookups
    media_cotag.lookup_tag_id(c)
    assert c.friend_lookups == 3, "probe must not serve a cached answer"

    assert media_cotag.lookup_tag_id(_client(friend_hit=False)) is None


# ── The Brain's per-account overrides ───────────────────────────────

def case_solo_video_not_tagged_by_default():
    """The video rule ships OFF — most creators are solo, and their videos
    really are just them. A solo-described video follows the describe verdict
    like a photo, while a partner VIDEO still tags with no opt-in at all: the
    knob only ever ADDS tags on top of the verdict, never removes one."""
    _reset()
    c = _client()
    c.send_message(4242, "solo clip", media_files=[40])
    assert "userTags" not in c.last_body(), c.last_body()
    c.send_message(4242, "collab clip", media_files=[41])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_null_brain_row_keeps_the_video_default():
    """An account whose operator saved a persona and never touched the tag
    section stores NULLs — which must mean OFF, exactly like no row at all."""
    _reset()
    _seed_brain()
    try:
        c = _client()
        c.send_message(4242, "solo clip", media_files=[40])
        assert "userTags" not in c.last_body(), c.last_body()
    finally:
        _clear_brain()
        _reset()


def case_video_rule_on_tags_solo_videos():
    """The Blake1/Blake2 hole: a video the describe pass read as solo still
    shows the POV partner. Ticking the box on a collab account tags EVERY
    video send — while photos keep the describe verdict
    (case_solo_media_is_not_tagged proves the solo photo stays clean)."""
    _reset()
    _seed_brain(cotag_tag_videos=1)
    try:
        c = _client()
        c.send_message(4242, "clip for you", media_files=[40])
        assert c.last_body().get("userTags") == [TAG_ID], c.last_body()
        c.send_message(4242, "pic for you", media_files=[10])
        assert "userTags" not in c.last_body(), c.last_body()
    finally:
        _clear_brain()
        _reset()


def case_brain_username_is_folded_on_both_paths():
    """The Brain's username drives BOTH tag paths, and the raw stored value is
    folded the way OF stores handles ('@CustomGuy' ≡ customguy)."""
    _reset()
    _seed_brain(cotag_username="@CustomGuy")
    try:
        c = _client(handle_in_list="customguy")
        c.send_message(4242, "collab", media_files=[20])
        assert c.last_body().get("userTags") == [TAG_ID], c.last_body()
        assert media_cotag.story_mention(ACCOUNT, [20]) == "@customguy"
    finally:
        _clear_brain()
        _reset()


def case_brain_username_change_invalidates_the_cached_id():
    """A saved username change must re-resolve, not keep tagging the OLD person
    for the rest of the 1h id TTL. White-box: only the config cache is dropped
    (what its own 60s TTL does), the id cache is deliberately left warm."""
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20])
    assert c.friend_lookups == 1, c.friend_lookups
    _seed_brain(cotag_username="someoneelse")
    media_cotag._acct_cfg.clear()
    try:
        c.send_message(4242, "again", media_files=[21])
        assert c.friend_lookups == 2, ("stale id served for a DIFFERENT handle",
                                       c.friend_lookups)
        assert c.last_body().get("userTags") == [999], c.last_body()
    finally:
        _clear_brain()
        _reset()


def case_forget_account_cfg_re_resolves():
    """What a Brain save calls: drops THIS account's config + id caches so the
    saved settings apply on the very next send — and doubles as the operator's
    "I just accepted the tag request, re-ask now" lever. Narrow on purpose: a
    brain save must not cost every other account a fresh lookup."""
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20])
    assert c.friend_lookups == 1, c.friend_lookups
    media_cotag._acct_cfg["someone_else"] = (0.0, (False, None))

    media_cotag.forget_account_cfg(ACCOUNT)
    c.send_message(4242, "again", media_files=[21])
    assert c.friend_lookups == 2, ("the id cache should have been dropped",
                                   c.friend_lookups)
    assert "someone_else" in media_cotag._acct_cfg, "other accounts must survive"



# ── Tag a co-creator, which one, or no one (ticket 85) ──────────────

def case_no_handle_configured_means_no_tag():
    """The default is "No co-creator tag": no Brain row, or a blank username
    (NULL or '') → partner media goes out untagged, OF is never asked, the story
    path agrees, and nothing is logged at ERROR — there was nothing to tag."""
    _reset()
    try:
        for seed in ("no row", None, ""):
            media_cotag.reset_caches()
            _clear_brain()
            if seed != "no row":
                _seed_brain(cotag_username=seed)
            with _Errors() as errs:
                c = _client()
                c.send_message(4242, "collab", media_files=[20])
                c.send_mass_message("blast", user_lists=["fans"], media_files=[21])
                mention = media_cotag.story_mention(ACCOUNT, [20])
            assert "userTags" not in c.captured[0][1], c.captured[0][1]
            assert c.captured[0][1].get("rfTag") == [], c.captured[0][1]
            assert "rfTag" not in c.last_body(), c.last_body()
            assert c.friend_lookups == 0, c.friend_lookups
            assert mention is None, mention
            assert errs == [], errs
            assert media_cotag.handle(ACCOUNT) == "", media_cotag.handle(ACCOUNT)
    finally:
        _clear_brain()
        _reset()


def case_a_real_miss_still_logs_the_error():
    """A configured co-creator who does not resolve is the case the ERROR
    exists for — it stays loud, once per cached miss."""
    _reset()
    with _Errors() as errs:
        c = _client(friend_hit=False)
        c.send_message(4242, "collab", media_files=[20])
        c.send_message(4242, "again", media_files=[21])
    assert "userTags" not in c.last_body(), c.last_body()
    assert len(errs) == 1 and "NOT in" in errs[0], errs


_harness.run()
