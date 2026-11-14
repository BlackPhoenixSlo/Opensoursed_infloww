#!/usr/bin/env python3
"""test_full_ai_assistant_config — Do mode's `full_ai_config` flow (phase 03c, ticket 55; D63).

The assistant turns "reply slower" / "stop GIFs" into a proposed patch of Creator A's Full AI draft,
and the page's rev-checked draft PUT applies it. Seams (spec › Testing Decisions): the LLM at the
`llm_client.httpx.AsyncClient` wire (FakeWriterHTTP, fake Agency key), OF at `client_pool.get`
(a recording fake: only the lists read; any other call raises), every send path under `_guarded`
(messages / vault_sends / leases unchanged). Temp DB only.

  case_propose_table
  case_folders_patch_keeps_the_stored_exclude
  case_reply_slower_round_trip
  case_stop_gifs_proposes_true_to_false
  case_unreadable_config_reads_once_and_says_so
  case_propose_refuses_by_name_and_follows_validate        (ticket 56)
  case_wider_words_give_one_diff                           (ticket 56)
  case_invalid_patch_through_the_route_writes_nothing      (ticket 56)
  case_stale_apply_is_409_and_the_page_draft_stays         (ticket 56)
  case_a_chatter_with_auto_mass_is_refused_full_ai         (ticket 56)

Run: ./venv/bin/python service/tests/test_full_ai_assistant_config.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

from _full_ai_chat_helpers import (  # noqa: E402
    A, DEEPSEEK, IDS, OWNER_A, _OF, _agency_keys, _db, _guarded, _of_fake, _store_config,
)
import _agency_fixtures as fx  # noqa: E402
from _full_ai_fixtures import FakeWriterHTTP  # noqa: E402
import assistant_draft  # noqa: E402
import assistant_full_ai as af  # noqa: E402
import employees  # noqa: E402
from automations import full_ai_config  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AssistantTurn  # noqa: E402

CONFIG = "/admin/full-ai/config"
DRAFT = "/admin/assistant/draft"
# The seed: a saved checkpoint, a draft with GIFs on, rev 4. `checkpoint` / `previous` never move.
SEED = {"checkpoint": {**DEFAULTS}, "previous": {**DEFAULTS, "writer_timeout_s": 20},
        "draft": {**DEFAULTS, "gifs": True}, "rev": 4}


# ── propose (pure) ────────────────────────────────────────────────────

def case_propose_table():
    rows = [({"reply_speed": "0-15-60"}, [("reply_speed", "Reply speed", "0-2m", "0-15-60")]),
            ({"gifs": False}, [("gifs", "GIFs", True, False)])]
    for patch, want in rows:
        p = af.propose(full_ai_config.merged(copy.deepcopy(SEED)), af.ConfigPatch(set=patch))
        assert isinstance(p, af.Proposal), (patch, p)
        assert [(d["field"], d["label"], d["before"], d["after"]) for d in p.diffs] == want, (patch, p.diffs)
        assert p.rev == 4 and p.before == full_ai_config.merged(SEED)["draft"], p
        assert p.after == {**p.before, **patch}, p.after
        assert full_ai_config.validate(p.after) == [], p.after
    assert af.label("not_a_key") == "not_a_key" and af.label("text_style") == "Human style"
    # The prompt's legacy `text_style` lands as the stored `style` layers (one "Human style" row).
    on, off = DEFAULTS["style"], dict.fromkeys(DEFAULTS["style"], False)
    p = af.propose(full_ai_config.merged(copy.deepcopy(SEED)), af.ConfigPatch(set={"text_style": "formal"}))
    assert isinstance(p, af.Proposal) and "text_style" not in p.after and p.after["style"] == off, p
    assert [(d["field"], d["label"], d["before"], d["after"]) for d in p.diffs] == [("style", "Human style", on, off)]
    assert isinstance(af.propose(full_ai_config.merged(copy.deepcopy(SEED)),
                                 af.ConfigPatch(set={"text_style": "girl"})), af.Refusal)       # already all on
    r = af.propose(full_ai_config.merged(copy.deepcopy(SEED)), af.ConfigPatch(set={"text_style": "boy"}))
    assert isinstance(r, af.Refusal) and "Human style" in r.text, r


def case_folders_patch_keeps_the_stored_exclude():
    """03b's `folders`: a value without `exclude` keeps the stored one; one that sets it wins. `validate`
    is stubbed here (03b owns the key's rules); once DEFAULTS holds `folders`, the real one runs too."""
    f = full_ai_config.DEFAULTS.get("folders")
    if isinstance(f, dict) and "exclude" in f:
        # The stored folders re-sent without `exclude` is no change: carried over, not wiped.
        r = af.propose(full_ai_config.merged(copy.deepcopy(SEED)),
                       af.ConfigPatch(set={"folders": {k: v for k, v in f.items() if k != "exclude"}}))
        assert isinstance(r, af.Refusal) and r.error == "no_change", r
    validate, full_ai_config.validate = full_ai_config.validate, lambda _cfg: []
    try:
        cur = full_ai_config.merged(copy.deepcopy(SEED))
        cur["draft"]["folders"] = {"include": [1], "exclude": [9]}
        p = af.propose(cur, af.ConfigPatch(set={"folders": {"include": [2]}}))
        assert isinstance(p, af.Proposal) and p.after["folders"] == {"include": [2], "exclude": [9]}, p
        p = af.propose(cur, af.ConfigPatch(set={"folders": {"include": [2], "exclude": []}}))
        assert isinstance(p, af.Proposal) and p.after["folders"] == {"include": [2], "exclude": []}, p
    finally:
        full_ai_config.validate = validate


# ── Through the route ─────────────────────────────────────────────────

def _turns() -> int:
    async def q():
        async with get_session() as s:
            return (await s.execute(select(func.count()).select_from(AssistantTurn)
                                    .where(AssistantTurn.account_id == A))).scalar_one()
    return _db(q)


def _ask(request: str, intent: dict, *, client=OWNER_A,
         previous: dict | None = None) -> tuple[dict, FakeWriterHTTP, _OF]:
    """One Do-mode draft for Creator A with the model's reply faked at the wire."""
    fake_w = FakeWriterHTTP({DEEPSEEK: "ok:" + json.dumps(intent)})
    body = {"request": request, "account_id": A, **({"previous": previous} if previous else {})}
    with _agency_keys({"deepseek": "test-deepseek-agency-key"}), _guarded(), fake_w.on(), _of_fake() as of:
        r = client.post(DRAFT, json=body)
    assert r.status_code == 200, r.text
    assert len(fake_w.requests) == 1, fake_w.requests
    assert set(of.calls) <= {f"get:{A}", "get_lists"} and "get_lists" in of.calls, of.calls
    return r.json(), fake_w, of


def _intent(patch: dict) -> dict:
    return {"flow": "full_ai_config", "config": {"set": patch}, "assumptions": [], "unresolved": []}


def _get() -> dict:
    r = OWNER_A.get(CONFIG, params={"account_id": A})
    assert r.status_code == 200, r.text
    return r.json()


def _checkpoint_is_seed():
    cur = _get()
    want = full_ai_config.merged(SEED)
    assert (cur["checkpoint"], cur["previous"]) == (want["checkpoint"], want["previous"]), cur


def case_reply_slower_round_trip():
    _store_config(A, copy.deepcopy(SEED))
    try:
        turns = _turns()
        out, fake_w, _ = _ask("reply slower", _intent({"reply_speed": "0-15-60"}))
        # The model saw the stored draft (a config word, an owner) and the flow in its system prompt.
        user = fake_w.requests[0]["body"]["messages"][1]["content"]
        assert '"reply_speed": "0-2m"' in user and "Full AI draft: " in user, user
        assert (out["flow"], out["error"]) == ("full_ai_config", None), out
        s = out["slots"]
        assert (s["before"]["reply_speed"], s["after"]["reply_speed"], s["rev"]) == ("0-2m", "0-15-60", 4), s
        assert [d["field"] for d in s["diffs"]] == ["reply_speed"] and s["account_name"], s
        assert _turns() == turns + 1, "no assistant_turns row"
        before = _get()
        assert before["rev"] == 4 and before["draft"]["reply_speed"] == "0-2m", before   # proposing writes nothing
        r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": s["after"], "rev": s["rev"]})
        assert r.status_code == 200, r.text
        after = _get()
        assert after["rev"] == before["rev"] + 1 and after["draft"] == s["after"], after
        assert after["draft"]["reply_speed"] == "0-15-60", after
        assert json.dumps(after["checkpoint"], sort_keys=True) == json.dumps(before["checkpoint"], sort_keys=True)
        assert json.dumps(after["previous"], sort_keys=True) == json.dumps(before["previous"], sort_keys=True)
        _checkpoint_is_seed()
    finally:
        _store_config(A, {})


def case_stop_gifs_proposes_true_to_false():
    _store_config(A, copy.deepcopy(SEED))
    try:
        out, _, _ = _ask("stop GIFs", _intent({"gifs": False}))
        assert (out["flow"], out["error"]) == ("full_ai_config", None), out
        assert [(d["field"], d["before"], d["after"]) for d in out["slots"]["diffs"]] == [
            ("gifs", True, False)], out["slots"]
        assert _get()["rev"] == 4, "proposing wrote the config"
        _checkpoint_is_seed()
    finally:
        _store_config(A, {})



def case_unreadable_config_reads_once_and_says_so():
    """One config read per ask (the draft line and the proposal share it); an unreadable store drops the
    draft line and answers read_failed — never a 500, nothing written."""
    calls = []

    async def broken(account_id):
        calls.append(account_id)
        raise ValueError("corrupt blob")

    real = assistant_draft.stored_config
    assistant_draft.stored_config = broken
    try:
        out, fake_w, _ = _ask("reply slower", _intent({"reply_speed": "0-15-60"}))
    finally:
        assistant_draft.stored_config = real
    assert calls == [A], calls
    assert "Full AI draft: " not in fake_w.requests[0]["body"]["messages"][1]["content"]
    assert (out["error"], out["slots"]) == ("read_failed", None), out
    assert out["answer"] == assistant_draft.CONFIG_READ_FAILED_ANSWER, out


# ── Ticket 56: refusals and reach ─────────────────────────────────────

def _cur() -> dict:
    return full_ai_config.merged(copy.deepcopy(SEED))


def _refused(patch: dict, error: str = "invalid_patch") -> af.Refusal:
    cur = _cur()
    r = af.propose(cur, af.ConfigPatch(set=patch))
    assert isinstance(r, af.Refusal) and r.error == error, (patch, r)
    assert cur == full_ai_config.merged(SEED), "propose changed what it read"   # checkpoint seed too
    return r


def case_propose_refuses_by_name_and_follows_validate():
    base = _cur()["draft"]
    # Unknown keys, today's and 04a's not-yet-defined `fans_list`, refused the way the JSON box's
    # validate refuses them ("<key>: unknown key"); one bad key refuses the whole patch (nothing dropped).
    for patch, key in (({"foo": 1}, "foo"), ({"fans_list": [1, 2]}, "fans_list"),
                       ({"gifs": False, "foo": 1}, "foo")):
        assert f"{key}: unknown key" in _refused(patch).text, patch
    # Locked keys: named, never written.
    for key, value in (("checkpoint", {}), ("previous", None), ("rev", 9), ("version", 2)):
        t = _refused({key: value}).text
        assert t.startswith("I can't make that change: ") and f"{key}: locked" in t, (key, t)
    # Out of range, wrong type, null (never a reset): validate's own error, nothing clamped.
    for patch, key, why in (({"writer_timeout_s": 90}, "writer_timeout_s", "from 5 to 60"),
                            ({"writer_timeout_s": 61}, "writer_timeout_s", "from 5 to 60"),
                            ({"gifs": "no"}, "gifs", "true or false"),
                            ({"gifs": None}, "gifs", "true or false"),
                            ({"writers": None}, "writers", "list of model ids"),
                            ({"reply_speed": "slow"}, "reply_speed", "must be one of")):
        t = _refused(patch).text
        assert f"{key}: " in t and why in t, (patch, t)
        for e in full_ai_config.validate({**base, **patch}):
            assert e in t, (patch, e, t)
    # The current value: "already set", no revision.
    for patch in ({"gifs": True}, {"reply_speed": "0-2m"}, {"writers": list(base["writers"])}):
        assert "already" in _refused(patch, "no_change").text, patch
    # sell_on true: exactly what validate says when this runs (03a's lock or 03b's settable bool).
    errs = full_ai_config.validate({**base, "sell_on": True})
    got = af.propose(_cur(), af.ConfigPatch(set={"sell_on": True}))
    if errs:
        assert isinstance(got, af.Refusal) and got.error == "invalid_patch", got
        assert all(e in got.text for e in errs) and "sell_on" in got.text, got
    else:
        assert isinstance(got, af.Proposal), got
        assert [(d["field"], d["before"], d["after"]) for d in got.diffs] == [("sell_on", False, True)], got.diffs


def case_wider_words_give_one_diff():
    """Asks that name a Writer or a fact to learn pass the veto: the model sees the draft and the
    proposal is one diff."""
    infos = [x for x in full_ai_config.INFO_FIELDS if x != "hobbies"]
    rows = (("use Euryale then Hermes", {"writers": ["euryale-v2.3", "hermes-4-405b"]}, "writers"),
            ("stop learning his hobbies", {"info_fields": infos}, "info_fields"))
    _store_config(A, copy.deepcopy(SEED))
    try:
        for request, patch, field in rows:
            assert not assistant_draft.vetoed(request, refine=False, flow=assistant_draft.CONFIG_FLOW), request
            out, fake_w, _ = _ask(request, _intent(patch))
            assert "Full AI draft: " in fake_w.requests[0]["body"]["messages"][1]["content"], request
            assert (out["flow"], out["error"]) == ("full_ai_config", None), out
            d = out["slots"]["diffs"]
            assert [(x["field"], x["after"]) for x in d] == [(field, patch[field])], d
            assert d[0]["before"] == full_ai_config.merged(SEED)["draft"][field], d
            assert _get()["rev"] == 4, "proposing wrote the config"
            _checkpoint_is_seed()
    finally:
        _store_config(A, {})


def case_invalid_patch_through_the_route_writes_nothing():
    _store_config(A, copy.deepcopy(SEED))
    try:
        before = _get()
        # A stray config plan sent as `previous` is ignored (config plans are never refined).
        stale_plan = {"rev": 4, "before": before["draft"], "after": before["draft"], "diffs": []}
        out, fake_w, _ = _ask("set writer timeout to 500", _intent({"writer_timeout_s": 500}),
                              previous=stale_plan)
        assert "PREVIOUS DRAFT" not in fake_w.requests[0]["body"]["messages"][1]["content"]
        assert (out["error"], out["slots"]) == ("invalid_patch", None), out
        assert "writer_timeout_s" in out["answer"], out
        assert _get() == before, "an invalid patch wrote the config"
        _checkpoint_is_seed()
    finally:
        _store_config(A, {})


def case_stale_apply_is_409_and_the_page_draft_stays():
    _store_config(A, copy.deepcopy(SEED))
    try:
        out, _, _ = _ask("reply slower", _intent({"reply_speed": "0-15-60"}))
        s = out["slots"]
        assert s["rev"] == 4, s
        page = {**_get()["draft"], "gifs": False}            # the page's JSON box, meanwhile
        r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": page, "rev": 4})
        assert r.status_code == 200, r.text
        r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": s["after"], "rev": s["rev"]})
        assert r.status_code == 409, r.text
        cur = _get()
        assert (cur["draft"], cur["rev"]) == (page, 5), cur
        _checkpoint_is_seed()
    finally:
        _store_config(A, {})


@contextlib.contextmanager
def _chatter_with_auto_mass():
    """chatter_a under an enforcing role that ticks Auto Mass (and opens the Full AI Chat page)."""
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
    role = {"id": "role-am", "name": "Fixture role-am", "description": "", "scope": "self",
            "permissions": {"/growth/auto-mass": True, "/full-ai-chatter": True}}
    r = OWNER_A.put("/admin/settings/roles", json={"enforce": True, "roles": [role],
                                                   "assignments": {str(emp): "role-am"}})
    assert r.status_code == 200, r.text
    try:
        yield fx.login_chatter("chatter_a")
    finally:
        assert OWNER_A.put("/admin/settings/roles", json={"enforce": False}).status_code == 200


_MASS = {"flow": "mass_premade", "name": "VIP mass", "every": {"value": 1, "unit": "hours"},
         "delete_after": False, "unsend_after_hours": None, "online_only": False,
         "audience": {"include": ["everyone"], "exclude": []}, "folder": {"want": "none", "name": None},
         "captions": {"count": 1, "provided": ["Miss me?"], "generated": []}, "keep_skip_recent": True,
         "assumptions": [], "unresolved": []}


def case_a_chatter_with_auto_mass_is_refused_full_ai():
    _store_config(A, copy.deepcopy(SEED))
    try:
        before = _get()
        with _chatter_with_auto_mass() as chatter:
            out, fake_w, _ = _ask("reply slower", _intent({"reply_speed": "0-15-60"}), client=chatter)
            assert (out["error"], out["slots"]) == ("not_allowed", None), out
            assert out["answer"] == assistant_draft.FULL_AI_NOT_ALLOWED_ANSWER, out
            assert out["answer"] != assistant_draft.NOT_ALLOWED_ANSWER
            assert "Full AI draft: " not in fake_w.requests[0]["body"]["messages"][1]["content"]
            r = chatter.put(f"{CONFIG}/draft", json={"account_id": A, "draft": before["draft"], "rev": 4})
            assert r.status_code == 403, r.text
            # Its own kind is re-checked per flow: the same chatter still gets a mass draft.
            out, _, _ = _ask("send a mass every hour to everyone", _MASS, client=chatter)
            assert (out["flow"], out["error"]) == ("mass_premade", None), out
        assert _get() == before, "a refused ask wrote the config"
        _checkpoint_is_seed()
    finally:
        _store_config(A, {})


_harness.run()
