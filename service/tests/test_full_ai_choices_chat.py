#!/usr/bin/env python3
"""test_full_ai_choices_chat — the Router's Choices and the Content folders drive the Pick, through
the Relay API (phase 03b, ticket 43).

`POST /admin/full-ai/test/turn` over `_harness.make_client()` with real owner session cookies (the
two-Agency fixture), a seeded vault and internal folders, and the fakes at the two network edges
only (Jev at `_router_jev._client`, the Writers at `llm_client.httpx.AsyncClient`). Every Turn runs
inside `_full_ai_chat_helpers._guarded` (full-row snapshots incl. content_offers, no
`automation_runs` row, every send path plus `ownership.stamp_media_owned` trapped).

  case_choices_drive_the_pick       asks_subject=feet, asks_format=photo: every Pick is Feet-pack
                                    photos and `pick` got Ask(feet, photo, heat); asks_format=video
                                    on a clip ask: the clip. Fails if the Turn passed anything/any
  case_unoffered_or_missing_choice  a top label the Choice never offered: still sell_now, Ask
                                    anything/any, the map stored as Jev gave it; no Choice answer
                                    at all: jev_failed (a missing answer is an error)
  case_test_request_holds_new_ids   the test request asks the four 03b ids, the row records
                                    question_version("test"), the TEST_NOULS in `answers` and the
                                    Choices in `choices` (Shadow's request + digest:
                                    test_full_ai_router_test_mode.py)
  case_folders_bound_the_pool       include vf:A: every Pick in A; include a deleted folder:
                                    no_match; include A + exclude B: the one item only A holds
  case_windows_differ_by_folders    left (checkpoint, all folders) vs right (draft, vf:A): the pool
                                    each side got and the right Pick in A

Run: ./venv/bin/python service/tests/test_full_ai_choices_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import delete  # noqa: E402

import _full_ai_fixtures as ffx  # noqa: E402
from _full_ai_chat_helpers import A, NANO, OWNER_A, TURN, _db, _guarded, _rows  # noqa: E402
from _full_ai_fixtures import QUIET, QUIET_TEST, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_sell  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import VaultFolder, VaultFolderItem, VaultItem  # noqa: E402

CONFIG = "/admin/full-ai/config"
PICS, CLIP = "send me pics", "send me a clip"
LINE = "ok:mm ok i have something for u"
T0 = datetime(2026, 7, 1)


@contextlib.contextmanager
def _spy(name: str):
    """`full_ai_sell.<name>` spied: one (args, result) per call."""
    real, got = getattr(full_ai_sell, name), []

    def spy(*a, **k):
        got.append((a, real(*a, **k)))
        return got[-1][1]
    setattr(full_ai_sell, name, spy)
    try:
        yield got
    finally:
        setattr(full_ai_sell, name, real)


def _hot(**qs) -> dict[str, float]:
    return {**QUIET, **qs}


SELL = _hot(wants_content=0.9)


def _post(pair: str, text: str = PICS, *, side: str = "draft", choices: dict | None = None,
          jev=None):
    """One test turn under the invariants: (response json, pick calls, pool calls, Jev fake)."""
    fake_j = FakeJev(jev or (SELL, 1.0, choices or {}))
    fake_w = FakeWriterHTTP({NANO: LINE})
    body = {"account_id": A, "pair": pair, "side": side, "n": 1, "text": text}
    with _guarded(), _spy("pick") as picks, _spy("pool") as pools, fake_w.on(), _fake_jev(fake_j):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r.json(), picks, pools, fake_j


def _ppv(got: dict) -> dict | None:
    return next((p["ppv"] for p in got["parts"] if "ppv" in p), None)


# ── Config + vault ────────────────────────────────────────────────────

def _rev() -> int:
    return OWNER_A.get(CONFIG, params={"account_id": A}).json()["rev"]


def _put_draft(draft: dict) -> int:
    r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": draft, "rev": _rev()})
    assert r.status_code == 200, r.text
    return r.json()["rev"]


def _save() -> None:
    r = OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": _rev()})
    assert r.status_code == 200, r.text


@contextlib.contextmanager
def _sides(checkpoint: dict | None, draft: dict):
    """A's config for the block, set through the API (`checkpoint` saved first, None = DEFAULTS);
    then both sides back to DEFAULTS."""
    if checkpoint is not None:
        _put_draft({**DEFAULTS, **checkpoint})
        _save()
    _put_draft({**DEFAULTS, **draft})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))
        if checkpoint is not None:
            _save()


DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False, "description": "a mirror selfie in jeans"}


def _jev(kind: str) -> dict:
    """A current $10-lane Jev blob (a clip also `vv` and `frames`, test_full_ai_sell.py's)."""
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": "$10", "state": {}, "kind": kind,
         "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": {}}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    return j


@contextlib.contextmanager
def _vault(items: dict[int, str], folders: dict[str, tuple[tuple[int, ...], bool]]):
    """A's vault for the block: media id -> kind, all $10 DRESSED; `folders`: name -> (members,
    deleted). Yields name -> `vf:<id>`; everything removed after."""
    refs: dict[str, str] = {}

    async def add():
        async with get_session() as s:
            for mid, kind in items.items():
                s.add(VaultItem(account_id=A, media_id=mid, kind=kind,
                                duration_seconds=12 if kind == "video" else None,
                                created_at=T0 + timedelta(days=mid % 400), tags="[]",
                                describe_status="described", of_folder_ids="[]",
                                ai_fields_json=json.dumps({**DRESSED, vault_jev_rules.JEV_KEY: _jev(kind)})))
            for name, (members, deleted) in folders.items():
                f = VaultFolder(account_id=A, name=name, deleted_at=T0 if deleted else None)
                s.add(f)
                await s.flush()
                refs[name] = f"vf:{f.id}"
                for mid in members:
                    s.add(VaultFolderItem(account_id=A, folder_id=f.id, media_id=mid))

    async def drop():
        async with get_session() as s:
            for m in (VaultFolderItem, VaultFolder, VaultItem):
                await s.execute(delete(m).where(m.account_id == A))
    _db(add)
    try:
        yield refs
    finally:
        _db(drop)


# ── Choices ───────────────────────────────────────────────────────────

FEET, OTHER, CLIP_ID = (501, 502), (511, 512), 601
FEET_VAULT = {501: "photo", 502: "photo", 511: "photo", 512: "photo", 601: "video"}


def case_choices_drive_the_pick():
    with _sides(None, {"sell_on": True}), _vault(FEET_VAULT, {"feet-nude": (FEET, False)}):
        for i in range(4):          # four pairs, four seeds: anything/any would reach 511/512/601
            got, picks, _pools, _j = _post(f"p-feet-{i}", choices={"asks_subject": "feet",
                                                                   "asks_format": "photo"})
            assert (got["route"], got["route_row"]) == ("sell_now", "sell"), got
            ((args, pick),) = picks
            assert args[2] == full_ai_sell.Ask("feet", "photo", got["heat"]), args[2]
            assert isinstance(pick, full_ai_sell.Pick) and set(pick.media) <= set(FEET), pick
            assert _ppv(got)["media"] == list(pick.media), got["parts"]
        for i in range(3):
            got, picks, _pools, _j = _post(f"p-clip-{i}", CLIP, choices={"asks_format": "video"})
            ((args, pick),) = picks
            assert args[2] == full_ai_sell.Ask("anything", "video", got["heat"]), args[2]
            assert pick.media == (CLIP_ID,) and pick.format == "video", pick
            assert _ppv(got)["media"] == [CLIP_ID], got["parts"]


def case_unoffered_or_missing_choice():
    off = {"armpits": 0.8, "feet": 0.2}
    with _sides(None, {"sell_on": True}), _vault(FEET_VAULT, {"feet-nude": (FEET, False)}):
        got, picks, _pools, _j = _post("p-unoffered", choices={"asks_subject": off})
        assert (got["route"], got["route_row"]) == ("sell_now", "sell"), got
        ((args, _pick),) = picks
        assert args[2] == full_ai_sell.Ask("anything", "any", got["heat"]), args[2]
        (row,) = _rows(A, "p-unoffered")
        assert row.jev_error is None and json.loads(row.jev_json)["choices"]["asks_subject"] == off
        # No Choice answer at all: a missing answer, never a default.
        nouls = {**QUIET_TEST, "wants_content": 0.9}
        raw = ffx._raw(nouls, {"intensity": SimpleNamespace(score=1.0, probabilities={})})
        got, picks, _pools, _j = _post("p-nochoice", jev=raw)
        assert (got["route"], got["heat"], got["route_row"]) == ("chat", 1, "jev_failed"), got
        assert picks == [], picks
        (row,) = _rows(A, "p-nochoice")
        assert row.jev_error and json.loads(row.jev_json)["choices"] is None, row.jev_error


NEW_IDS = {"asks_subject", "asks_format", "counter_offer", "offer_moment"}


def case_test_request_holds_new_ids():
    with _sides(None, {"sell_on": True}), _vault(FEET_VAULT, {}):
        got, _p, _pools, fake = _post("p-ids", jev=(_hot(wants_content=0.9, counter_offer=0.7), 1.0,
                                                     {"asks_format": {"video": 0.6, "photo": 0.4}}))
    (call,) = fake.calls
    assert NEW_IDS <= set(call["questions"]), sorted(call["questions"])
    (row,) = _rows(A, "p-ids")
    assert row.question_version == rj.question_version("test") != rj.QUESTION_VERSION, row.question_version
    jev = json.loads(row.jev_json)
    assert jev["choices"] == {"asks_subject": {"anything": 0.9},
                              "asks_format": {"video": 0.6, "photo": 0.4}}, jev["choices"]
    assert jev["answers"] == {**QUIET_TEST, "wants_content": 0.9, "counter_offer": 0.7}, jev["answers"]
    assert "test_nouls" not in jev, sorted(jev)   # the TEST_NOULS live in `answers`, like gif_fits


# ── Folders ───────────────────────────────────────────────────────────

IN_A, SHARED, IN_B, LOOSE = 801, 802, 901, 1001
FOLDER_VAULT = {IN_A: "photo", SHARED: "photo", IN_B: "photo", LOOSE: "photo"}
FOLDERS = {"A": ((IN_A, SHARED), False), "B": ((IN_B, SHARED), False), "D": ((LOOSE,), True)}


def case_folders_bound_the_pool():
    with _vault(FOLDER_VAULT, FOLDERS) as vf:
        with _sides(None, {"sell_on": True, "folders": {"include": [vf["A"]], "exclude": []}}):
            for i in range(4):
                got, picks, _pools, _j = _post(f"p-in-a-{i}")
                ((_a, pick),) = picks
                assert set(pick.media) <= {IN_A, SHARED}, pick
                assert set(_ppv(got)["media"]) <= {IN_A, SHARED}, got["parts"]
        with _sides(None, {"sell_on": True, "folders": {"include": [vf["D"]], "exclude": []}}):
            got, picks, pools, _j = _post("p-deleted")
            assert pools[0][1] == full_ai_sell.Refusal("no_match") and picks == [], pools
            assert got["offer"] is None and _ppv(got) is None, got
            assert json.loads(_rows(A, "p-deleted")[0].reply_json)["refusal"] == "no_match"
        with _sides(None, {"sell_on": True, "folders": {"include": [vf["A"]], "exclude": [vf["B"]]}}):
            for i in range(3):
                got, picks, _pools, _j = _post(f"p-excl-{i}")
                ((_a, pick),) = picks
                assert pick.media == (IN_A,), pick


def case_windows_differ_by_folders():
    with _vault(FOLDER_VAULT, FOLDERS) as vf:
        only_a = {"include": [vf["A"]], "exclude": []}
        with _sides({"sell_on": True}, {"sell_on": True, "folders": only_a}):
            left, _lp, lpools, _j = _post("p-win", side="checkpoint")
            right, rpicks, rpools, _j = _post("p-win", side="draft")
    ((largs, lpool),) = lpools
    ((rargs, rpool),) = rpools
    assert largs[3] == {"include": [], "exclude": []}, largs[3]
    assert {r["media_id"] for r in lpool} == set(FOLDER_VAULT), lpool
    assert rargs[3] == only_a, rargs[3]
    assert {r["media_id"] for r in rpool} == {IN_A, SHARED}, rpool
    assert left["route"] == right["route"] == "sell_now", (left, right)
    ((_a, pick),) = rpicks
    assert set(pick.media) <= {IN_A, SHARED} and set(_ppv(right)["media"]) <= {IN_A, SHARED}, pick
    lrow, rrow = _rows(A, "p-win")
    assert (json.loads(lrow.reply_json)["side"], json.loads(rrow.reply_json)["side"]) == (
        "checkpoint", "draft")


_harness.run()
