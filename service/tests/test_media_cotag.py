#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json          # noqa: E402
import os            # noqa: E402

import media_cotag   # noqa: E402
import of_client     # noqa: E402
from db.engine import DATABASE_URL  # noqa: E402

ACCOUNT = "900001"
TAG_ID = 555_111



def _sync_exec(*statements: tuple[str, dict]) -> None:
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


COHANDLE = "cohandle"


def _seed_brain(**cols) -> None:
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
    media_cotag.reset_caches()
    os.environ.pop("OF_COTAG_ENABLED", None)
    _seed_brain()


class _Errors:

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
BLOWJOB = {"people_count": 1, "partner_visible": False, "acts": ["blowjob"]}
UNDESCRIBED: dict = {}


_seed_vault({
    10: SOLO, 11: SOLO, 12: SOLO, 13: SOLO,
    20: PARTNER,
    21: TWO_PEOPLE,
    22: BLOWJOB,
    30: UNDESCRIBED,
})
_seed_vault({40: SOLO, 41: PARTNER}, kind="video")



def case_solo_media_is_not_tagged():
    _reset()
    c = _client()
    c.send_message(4242, "here you go", media_files=[10])
    assert "userTags" not in c.last_body(), c.last_body()


# OF ignores userTags on every endpoint; the tag only lands via rfTag/rfGuest/rfPartner.
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



def case_every_body_that_carries_media_tags_it():
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



def case_chat_send_fills_the_release_form_array():
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20])
    assert c.last_body().get("rfTag") == [TAG_ID], c.last_body()
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_operator_picks_reach_the_release_form_array_too():
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
    _reset()
    c = _client()
    c.send_mass_message("blast", user_lists=["fans"], media_files=[10])
    body = c.last_body()
    assert "userTags" not in body, body
    for key in ("rfTag", "rfGuest", "rfPartner"):
        assert key not in body, (key, body)


def case_a_refused_queue_tag_retries_without_the_arrays_at_all():
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
    _reset()
    c = _client(reject_status=400)
    c.send_mass_message("blast", user_lists=["fans"], media_files=[20],
                        tagged_users=[314159])
    assert len(c.captured) == 2, c.captured
    assert c.captured[0][1].get("rfTag") == [314159, TAG_ID], c.captured[0][1]
    assert c.last_body().get("rfTag") == [314159], c.last_body()
    assert c.last_body().get("userTags") == [314159], c.last_body()


def case_retry_keeps_the_operators_pick_and_drops_only_ours():
    _reset()
    c = _client(reject_status=400)
    c.send_message(4242, "collab", media_files=[20], tagged_users=[314159])
    assert len(c.captured) == 2, c.captured
    first = c.captured[0][1]
    assert first.get("rfTag") == [314159, TAG_ID], first
    assert c.last_body().get("rfTag") == [314159], c.last_body()
    assert c.last_body().get("userTags") == [314159], c.last_body()
    assert c.last_body().get("mediaFiles") == [20], c.last_body()


def case_rejected_tag_retry_empties_the_release_form_array():
    _reset()
    c = _client(reject_status=400)
    c.send_message(4242, "collab", media_files=[20])
    assert len(c.captured) == 2, c.captured
    assert "userTags" not in c.last_body(), c.last_body()
    assert c.last_body().get("rfTag") == [], c.last_body()



def case_operator_tags_survive():
    _reset()
    c = _client()
    c.send_message(4242, "collab", media_files=[20], tagged_users=[314159])
    assert c.last_body().get("userTags") == [314159, TAG_ID], c.last_body()


def case_operator_tags_land_on_a_text_only_send():
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
    _reset()
    c = _client()
    c.send_message(4242, "manual", media_files=[20], auto_tag=False)
    assert "userTags" not in c.last_body(), c.last_body()



def case_unresolvable_handle_sends_untagged():
    _reset()
    c = _client(friend_hit=False)
    c.send_message(4242, "here you go", media_files=[20])
    assert "userTags" not in c.last_body(), c.last_body()
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
    _reset()
    c = _client(reject_status=400)
    result = c.send_message(4242, "here you go", media_files=[20])
    assert result == {"id": 1}, result
    assert len(c.captured) == 2, c.captured
    assert c.captured[0][1].get("userTags") == [TAG_ID], c.captured[0][1]
    assert "userTags" not in c.captured[1][1], c.captured[1][1]
    assert c.captured[1][1]["mediaFiles"] == [20], c.captured[1][1]


def case_rejection_invalidates_the_cached_id():
    _reset()
    c = _client(reject_status=400)
    c.send_message(4242, "first", media_files=[20])
    assert c.friend_lookups == 1, c.friend_lookups
    assert len(c.captured) == 2, "tagged POST + untagged retry"

    c.send_message(4242, "second", media_files=[21])
    assert c.friend_lookups == 2, ("rejected id was served from cache",
                                   c.friend_lookups)


def case_operator_tag_rejection_still_raises():
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
    _reset()
    original = media_cotag._describe_rows

    def _boom(*_a, **_kw):
        raise RuntimeError("database is locked")

    media_cotag._describe_rows = _boom
    try:
        c = _client()
        c.send_message(4242, "here you go", media_files=[10])
        assert c.last_body().get("userTags") == [TAG_ID], c.last_body()
    finally:
        media_cotag._describe_rows = original
        _reset()


def case_lookup_tag_id_ignores_the_cache():
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



def case_solo_video_not_tagged_by_default():
    _reset()
    c = _client()
    c.send_message(4242, "solo clip", media_files=[40])
    assert "userTags" not in c.last_body(), c.last_body()
    c.send_message(4242, "collab clip", media_files=[41])
    assert c.last_body().get("userTags") == [TAG_ID], c.last_body()


def case_null_brain_row_keeps_the_video_default():
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




def case_no_handle_configured_means_no_tag():
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
    _reset()
    with _Errors() as errs:
        c = _client(friend_hit=False)
        c.send_message(4242, "collab", media_files=[20])
        c.send_message(4242, "again", media_files=[21])
    assert "userTags" not in c.last_body(), c.last_body()
    assert len(errs) == 1 and "NOT in" in errs[0], errs


_harness.run()
