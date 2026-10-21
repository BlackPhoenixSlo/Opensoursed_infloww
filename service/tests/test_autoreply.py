#!/usr/bin/env python3
"""autoreply automation tests — a reply to a known fan nobody answered in time,
for the picked audience (folders / new fans). The send path is faked (no network, no LLM spend).

  case_disabled_no_send         gate OFF → nothing sent.
  case_eligible_one_nudge       fan-waiting (in-window) + info-complete → exactly
                                one reply; state recorded.
  case_nudge_cap                second run after we replied → he's covered, no 2nd.
  case_new_message_covered_again  a NEW waiting message → covered again.
  case_we_spoke_last_skipped    we already replied → he's not waiting → skip.
  case_silence_too_fresh        messaged 2 min ago (< min) → not yet eligible.
  case_hidden_caps_gone         a $50k fan who bought today is replied to; a
                                stored legacy cap key is ignored.
  case_not_info_complete_skipped  blank profile → not a "known" fan → skipped.
  case_step_in_minutes_helper   the per-(fan, message) step-in draw: off ⇒ floor,
                                deterministic, second-stable, inside the band.
  case_jitter_gates_candidates  the engine gates on the fan's OWN draw, not sil_min.
  case_jitter_rerolls_on_new_message  a new inbound ⇒ evaluated against the NEW anchor.
  case_config_api_keeps_step_in_max   _validate keeps/clamps the knob; to < from ⇒ 422.
  case_no_candidates_returns_early    nobody waiting ⇒ the short return, no LLM call.
  case_folder_pick_scopes_replies     folders picked ⇒ a fan in one is replied to,
                                      a waiting fan outside them is not.
  case_folder_read_failure_replies_to_nobody  OF folder read fails ⇒ nobody, no LLM.
  case_folder_cap_skips_high_spender  a folder member over the spend cap ⇒ skipped.
  case_new_fan_qualifies              new fans on: a recent, low-spend fan (by sub
                                      date, or by first message when none) ⇒ reply;
                                      an old / high-spend fan in no folder ⇒ skipped.
  case_folder_failure_keeps_new_fans  folder read fails ⇒ new fans still replied to.
  case_no_source_replies_to_nobody    both sources off ⇒ nobody.
  case_delay_zero_replies_at_once     delay 0 ⇒ a 1-second-old message is answered.
  case_randomised_window              randomise (step_in_max = 2d) ⇒ every draw in
                                      [d, 2d]; the engine gates on it.
  case_just_paid_fan_is_answered      a just-paid fan is Auto-reply's like any
                                      other: no closer answers him.
  case_config_api_audience_and_delay  _validate: delay 0, the audience keys.
  case_no_llm_key_skips_quietly       owned account, owner has no key ⇒ one check,
                                      no candidate query, no LLM call.
  case_llm_key_available_policy       the bool mirrors _tenant_api_key's policy.
  case_config_api_reports_key_state   GET carries {llm_key: {provider, available}}.
  case_config_api_list_ids            _validate keeps numeric ids, refuses names.
  case_auto_reply_never_sells         a content-ask: the never-sell rule stands
                                      and no tip-ask is injected.
  case_photo_only_unseen_still_replies  describe off: a bare photo is answered
                                      without claiming to know it; no download.
  case_skip_photo_only                skip_photo_only skips a bare photo only.
  case_describe_on_reads_the_photo_once  describe on + key: one vision call, cached.
  case_describe_without_key_is_a_hard_stop  no key: no download, no vision call.
  case_config_api_keeps_photo_options  the two bools validate, default off.

Run: ./venv/bin/python service/tests/test_autoreply.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers plugins
import automations.autoreply as _autoreply  # noqa: E402
import llm_client  # noqa: E402
from automations.autoreply import _step_in_minutes  # noqa: E402
from autoreply_config_api import _validate  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutoreplyState, Fan, Message, SkipList, Transaction,
    User, UserAccount,
)
import tenant_keys  # noqa: E402


class FakeOF:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self._id = 9_500_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._id += 1
        self.sent.append((int(chat_id), text))
        # Stamp the sent nudge 10 min in the PAST so a re-run sees it as the latest
        # message with a real in-window silence (so the CAP — not "too fresh" — is
        # what blocks a 2nd nudge in the same spell).
        when = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "+00:00"
        return {"id": self._id, "text": f"<p>{text}</p>", "createdAt": when}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "hey u, been thinking about that sunrise run 😏") -> None:
    async def _fake(**kw):
        return SimpleNamespace(content=reply, call_id=1)
    llm_client.chat = _fake  # type: ignore[attr-defined]


async def _seed_account(aid: str, *, enabled: bool = True, extra: dict | None = None) -> None:
    # Pin the step-in window to 5 min so these timing cases (which seed 8-30 min
    # old messages) stay independent of the production default (now 30 min).
    cfg = {"enabled": enabled, "silence_min_minutes": 5}
    if extra:
        cfg.update(extra)
    # The realism layers (human style / typos / non-native / space-before-?) default
    # ON for autoreply; pin them OFF so these cases assert the engine's own logic on
    # the exact text the fake LLM returned. The defaults live in test_realism_detectors.
    style = json.dumps({k: False for k in (
        "autoreply", "typos_autoreply", "nonnative_autoreply", "nonnative_spacing_autoreply")})
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        await s.execute(
            sqlite_insert(AccountAiConfig)
            .values(account_id=aid, utc_offset=0, autoreply_config_json=json.dumps(cfg),
                    style_config_json=style)
            .on_conflict_do_update(index_elements=["account_id"],
                                   set_={"autoreply_config_json": json.dumps(cfg),
                                         "style_config_json": style})
        )


async def _seed_fan(aid: str, fid: int, *, last_dir="in", last_ago_min=30,
                    spend=0, sub_days=5, complete=True,
                    last_at: datetime | None = None) -> None:
    """Seed a fan whose LAST message (messages table — the truth autoreply reads)
    is `last_dir` `last_ago_min` minutes ago. last_dir='in' = the FAN spoke last
    and is WAITING (the eligible case); 'out' = we already replied (skip).
    `last_at` pins that final message's created_at EXACTLY (the jitter cases seed
    the anchor the draw was searched at, to the second)."""
    now = datetime.utcnow()
    last_recv = now - timedelta(minutes=last_ago_min + (0 if last_dir == "in" else 5))
    async with get_session() as s:
        s.add(Fan(
            account_id=aid, fan_id=fid, of_display_name="Jack",
            lifetime_spend_cents=spend,
            subscribed_at=now - timedelta(days=sub_days),
            last_message_sent_at=now - timedelta(minutes=last_ago_min),
            last_message_received_at=last_recv,
            his_age=("27" if complete else None),
            home_city=("Ljubljana" if complete else None),
            hobbies=("trail running" if complete else None),
            likes_boobs=complete,
        ))
        # history + a FINAL message of `last_dir` at `last_ago_min` ago.
        hist = [("out", "hey 😏", 50), ("in", "haha hi", 48), ("out", "what u up to", 46)]
        hist.append((last_dir, "you up?" if last_dir == "in" else "miss u", last_ago_min))
        for i, (d, b, ago) in enumerate(hist):
            at = now - timedelta(minutes=ago)
            if last_at is not None and i == len(hist) - 1:
                at = last_at
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 100 + i,
                          direction=d, body=f"<p>{b}</p>", created_at=at))


async def _state(aid: str, fid: int):
    async with get_session() as s:
        return await s.get(AutoreplyState, (aid, fid))


# ── cases ─────────────────────────────────────────────────────────────

async def case_disabled_no_send():
    aid = "ar_off"
    await _seed_account(aid, enabled=False)
    await _seed_fan(aid, 1001)
    _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0 and res.get("enabled") is False, res


async def case_eligible_one_nudge():
    aid = "ar_ok"
    await _seed_account(aid)
    await _seed_fan(aid, 2001)
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1, res
    assert [c for c, _ in fake.sent] == [2001], fake.sent
    st = await _state(aid, 2001)
    assert st is not None and st.nudges_sent == 1, st


async def case_nudge_cap():
    aid = "ar_cap"
    await _seed_account(aid)  # max_nudges default 1
    await _seed_fan(aid, 3001)
    fake = _use_fake(); _patch_llm()
    await run_once(aid, "autoreply", payload={})           # covers his waiting msg
    res2 = await run_once(aid, "autoreply", payload={})
    assert res2["sent"] == 0, f"already replied → he's no longer waiting, got {res2}"
    assert len(fake.sent) == 1, fake.sent


async def case_new_message_covered_again():
    aid = "ar_reset"
    await _seed_account(aid)
    await _seed_fan(aid, 4001)
    fake = _use_fake(); _patch_llm()
    await run_once(aid, "autoreply", payload={})           # cover his first msg
    # He sends ANOTHER message — newer than our reply (~10m ago) but past the
    # 5-min window → waiting again. Backdate our last reply so the reply-gap has
    # elapsed (else the min-cadence guard would correctly hold it).
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=4001, message_id=4001 * 100 + 20,
                      direction="in", body="<p>u there?</p>",
                      created_at=now - timedelta(minutes=8)))
        f = await s.get(Fan, (aid, 4001))
        f.last_message_received_at = now - timedelta(minutes=8)
        st = await s.get(AutoreplyState, (aid, 4001))
        st.last_nudge_at = now - timedelta(minutes=10)     # reply-gap elapsed
    # The first cover holds the fan-lease to its TTL (so a concurrent sibling can't
    # double-message). 10 min later that TTL has long expired — release it to make
    # the fan re-coverable (same pattern as the welcome_chatter_for_info lease tests).
    await ax.release_fan_lease(aid, 4001)
    res2 = await run_once(aid, "autoreply", payload={})
    assert res2["sent"] == 1, f"a new waiting message → cover again, got {res2}"
    assert len(fake.sent) == 2, fake.sent


async def case_reply_gap_holds_fast_remessage():
    """≥ reply-gap between Auto Convo replies to the same fan: if he fires back
    inside the gap, he's NOT answered instantly — he waits the minimum again."""
    aid = "ar_gap"
    await _seed_account(aid)
    await _seed_fan(aid, 4101)
    fake = _use_fake(); _patch_llm()
    await run_once(aid, "autoreply", payload={})           # reply #1 (last_nudge_at≈now)
    now = datetime.utcnow()
    async with get_session() as s:  # new msg past the 5-min window, but gap NOT elapsed
        s.add(Message(account_id=aid, fan_id=4101, message_id=4101 * 100 + 20,
                      direction="in", body="<p>u there??</p>",
                      created_at=now - timedelta(minutes=8)))
        f = await s.get(Fan, (aid, 4101))
        f.last_message_received_at = now - timedelta(minutes=8)
    res2 = await run_once(aid, "autoreply", payload={})
    assert res2["sent"] == 0, f"reply-gap must hold a fast re-message, got {res2}"
    assert len(fake.sent) == 1, fake.sent


async def case_we_spoke_last_skipped():
    aid = "ar_welast"
    await _seed_account(aid)
    await _seed_fan(aid, 5001, last_dir="out", last_ago_min=30)  # we already replied
    _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0, "we spoke last → he's not waiting → Auto Convo skips"


async def case_silence_too_fresh():
    aid = "ar_fresh"
    await _seed_account(aid)
    await _seed_fan(aid, 6001, last_dir="in", last_ago_min=2)  # waiting only 2 min
    _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0, "under silence_min → give the team time, not yet"


async def case_hidden_caps_gone():
    """The hidden $20k-lifetime / $500-day / days-since gates are gone: WHO is
    the visible audience only. A $50k fan who bought today is replied to, even
    with a legacy cap key still in his account's stored blob."""
    aid = "ar_nocaps"
    await _seed_account(aid, extra={"max_lifetime_spend_cents": 2000,
                                    "min_days_since_purchase": 7})
    await _seed_fan(aid, 7001, spend=5_000_000)
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=7001, kind="purchase",
                          amount_cents=60_000,
                          occurred_at=datetime.utcnow() - timedelta(hours=3)))
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1 and [c for c, _ in fake.sent] == [7001], (res, fake.sent)
    assert "skipped_spend" not in res, res


async def case_not_info_complete_skipped():
    aid = "ar_unknown"
    # info_not_required now defaults ON — pin it off to test the known-fan gate.
    await _seed_account(aid, extra={"info_not_required": False})
    await _seed_fan(aid, 9001, complete=False)  # blank profile
    _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0, "not info-complete → not a known fan → skipped"


async def case_info_not_required_covers_incomplete():
    # "Info not needed" mode: an info-INCOMPLETE waiting fan is still covered
    # (reply from the last few messages + whatever's known).
    aid = "ar_infooff"
    await _seed_account(aid, extra={"info_not_required": True})
    await _seed_fan(aid, 9201, complete=False)  # blank profile
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1, ("info_not_required → cover even unknown fans", res)
    assert [c for c, _ in fake.sent] == [9201], fake.sent


async def case_unreachable_fan_costs_one_llm_call():
    """A deleted/blocked fan (send 404s 'User not found') burns at most ONE LLM
    call: tick 1 generates + the send fails → the fan is quarantined (skip_list
    'unreachable' + automation_paused_until, the gate autoreply honours), so tick
    2 drops the fan from candidacy BEFORE any generation."""
    aid = "ar_unreach"
    await _seed_account(aid)
    await _seed_fan(aid, 9301)
    fake = _use_fake()
    def _raise(chat_id, text, **kw):
        raise Exception(
            f"404 for https://onlyfans.com/api2/v2/chats/{chat_id}/messages\n"
            '{"error":{"code":0,"message":"User not found"}}'
        )
    fake.send_message = _raise
    calls: list[int] = []
    async def _fake_chat(**kw):
        calls.append(kw.get("fan_id"))
        return SimpleNamespace(content="hey u 😏", call_id=1)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]

    r1 = await run_once(aid, "autoreply", payload={})
    assert r1["sent"] == 0 and r1["errors"] == 1, r1
    assert calls == [9301], ("the one unavoidable pre-send call", calls)
    async with get_session() as s:
        row = await s.get(SkipList, (aid, 9301))
        assert row is not None and row.reason == "unreachable", row
        f = await s.get(Fan, (aid, 9301))
        assert f.automation_paused_until and f.automation_paused_until > datetime.utcnow()

    r2 = await run_once(aid, "autoreply", payload={})
    # Tick 2 has NO candidates (he is paused), so it takes the short no-candidate
    # return, which — like the disabled / quiet-hours ones — carries no `errors`.
    assert r2["sent"] == 0 and r2.get("errors", 0) == 0, r2
    assert calls == [9301], ("ZERO further LLM calls", calls)


# ── photos he sends: describe (opt-in), unseen, skip photo-only ─────────────

_PHOTO_RAW = json.dumps({"media": [{"type": "photo", "files": {
    "full": {"url": "https://cdn.example/p1.jpg"}}}]})


async def _make_last_inbound_a_photo(aid: str, fid: int, *, text: str = "") -> int:
    """Turn the fan's latest inbound into a photo DM (with `text`, or bare)."""
    async with get_session() as s:
        last = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fid,
                                  Message.direction == "in")
            .order_by(Message.created_at.desc()).limit(1))).scalars().all()[0]
        last.body = f"<p>{text}</p>" if text else ""
        last.media_count = 1
        last.raw_json = _PHOTO_RAW
        return int(last.message_id)


def _patch_llm_capture(reply: str, sink: list[dict], *, vision_reply: str = ""):
    """Capture every call; the vision purpose answers with `vision_reply`."""
    import inbound_describe
    async def _fake(**kw):
        sink.append(kw)
        if kw.get("purpose") == inbound_describe.PURPOSE:
            return SimpleNamespace(content=vision_reply, call_id=2)
        return SimpleNamespace(content=reply, call_id=1)
    llm_client.chat = _fake  # type: ignore[attr-defined]


@contextlib.contextmanager
def _patch_vision(*, key: bool, downloads: list[list[str]]):
    """Fake the DeepInfra key check and the CDN download (no network)."""
    import inbound_describe
    async def _key(account_id):
        return key
    async def _download(client, urls):
        downloads.append(list(urls))
        return ["data:image/jpeg;base64,AAAA" for _ in urls]
    saved = (inbound_describe.key_available, inbound_describe.download_frames,
             inbound_describe.shrink_data_url)
    inbound_describe.key_available = _key            # type: ignore[assignment]
    inbound_describe.download_frames = _download     # type: ignore[assignment]
    inbound_describe.shrink_data_url = lambda u, e=0: u  # type: ignore[assignment]
    try:
        yield
    finally:
        (inbound_describe.key_available, inbound_describe.download_frames,
         inbound_describe.shrink_data_url) = saved


def _reply_prompt(sink: list[dict]) -> str:
    replies = [c for c in sink if c.get("purpose") == "autoreply"]
    assert len(replies) == 1, sink
    return "\n".join(m["content"] for m in replies[0]["messages"]
                     if isinstance(m.get("content"), str))


async def case_auto_reply_never_sells():
    """Auto-reply only chats: even on an explicit content-ask the never-sell rule
    stands and no tip-ask is injected."""
    aid = "ar_never_sells"
    await _seed_account(aid)
    await _seed_fan(aid, 2601)
    async with get_session() as s:
        last = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == 2601,
                                  Message.direction == "in")
            .order_by(Message.created_at.desc()).limit(1))).scalars().all()[0]
        last.body = "<p>can i see some content??</p>"
    sink: list[dict] = []
    fake = _use_fake()
    _patch_llm_capture("haha u tease, what u been up to", sink)
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1, res
    sysmsg = _reply_prompt(sink)
    assert "NEVER offer or hint at PPV" in sysmsg, sysmsg
    assert "HE JUST ASKED TO SEE CONTENT" not in sysmsg, sysmsg
    assert fake.sent == [(2601, "haha u tease, what u been up to")], fake.sent


async def case_photo_only_unseen_still_replies():
    """Describe OFF (the default): a bare photo still gets a reply, the prompt
    says he sent a photo she can't see, and no vision call / download happens."""
    aid = "ar_photo_unseen"
    await _seed_account(aid)
    await _seed_fan(aid, 3101)
    await _make_last_inbound_a_photo(aid, 3101)
    downloads: list[list[str]] = []
    fake = _use_fake()
    sink: list[dict] = []
    _patch_llm_capture("omg what did u send me 😏", sink)
    with _patch_vision(key=True, downloads=downloads):
        res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1 and len(fake.sent) == 1, res
    assert downloads == [] and res["photos_described"] == 0, (downloads, res)
    prompt = _reply_prompt(sink)
    assert "FAN: [he sent a photo]" in prompt, prompt
    assert "Never say or imply what's in it" in prompt, prompt


async def case_skip_photo_only():
    """skip_photo_only: a bare photo is skipped; a photo WITH words is answered."""
    aid = "ar_photo_skip"
    await _seed_account(aid, extra={"skip_photo_only": True})
    await _seed_fan(aid, 3201)
    await _make_last_inbound_a_photo(aid, 3201)
    await _seed_fan(aid, 3202)
    await _make_last_inbound_a_photo(aid, 3202, text="rate me")
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["skipped_photo_only"] == 1, res
    assert [c for c, _ in fake.sent] == [3202], fake.sent


async def case_describe_on_reads_the_photo_once():
    """describe_photos + a DeepInfra key: the photo is described once, cached on
    messages.image_desc, and the reply prompt carries the description."""
    aid = "ar_photo_seen"
    await _seed_account(aid, extra={"describe_photos": True})
    await _seed_fan(aid, 3301)
    mid = await _make_last_inbound_a_photo(aid, 3301, text="what do u think")
    downloads: list[list[str]] = []
    _use_fake()
    sink: list[dict] = []
    _patch_llm_capture("ok that view is unreal", sink,
                       vision_reply="a mirror selfie at the gym, shirtless")
    with _patch_vision(key=True, downloads=downloads):
        res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1 and res["photos_described"] == 1, res
    assert downloads == [["https://cdn.example/p1.jpg"]], downloads
    async with get_session() as s:
        desc = (await s.execute(select(Message.image_desc).where(
            Message.account_id == aid, Message.message_id == mid))).scalar_one()
    assert desc == "a mirror selfie at the gym, shirtless", desc
    prompt = _reply_prompt(sink)
    assert "[he sent: a mirror selfie at the gym, shirtless]" in prompt, prompt
    assert "React to it like you're looking at it" in prompt, prompt

    # The cache: a second describe of the same message makes no call.
    import inbound_describe
    sink.clear(); downloads.clear()
    again = await inbound_describe.describe_photo(aid, mid, None)
    assert again == desc and sink == [] and downloads == [], (again, sink, downloads)


async def case_describe_without_key_is_a_hard_stop():
    """describe_photos on but no DeepInfra key: no download, no vision call, no
    retry — the reply still goes out, as an unseen photo."""
    aid = "ar_photo_nokey"
    await _seed_account(aid, extra={"describe_photos": True})
    await _seed_fan(aid, 3401)
    await _make_last_inbound_a_photo(aid, 3401)
    downloads: list[list[str]] = []
    _use_fake()
    sink: list[dict] = []
    _patch_llm_capture("haha what is this", sink)
    with _patch_vision(key=False, downloads=downloads):
        res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1 and res["photos_described"] == 0, res
    assert downloads == [], downloads
    import inbound_describe
    assert not [c for c in sink if c.get("purpose") == inbound_describe.PURPOSE], sink
    assert "FAN: [he sent a photo]" in _reply_prompt(sink)


def case_config_api_keeps_photo_options():
    assert _validate({"describe_photos": 1, "skip_photo_only": 0}) == {
        "describe_photos": True, "skip_photo_only": False}
    d = _autoreply._defaults()
    assert d["describe_photos"] is False and d["skip_photo_only"] is False, d


async def case_unreachable_fan_skipped():
    """skip_list 'unreachable' (deleted/blocked) is honored — even after the 7d
    pause expires — so Auto Convo doesn't re-generate + re-fail on a dead fan."""
    aid = "ar_unreach"
    await _seed_account(aid)
    await _seed_fan(aid, 6301)
    async with get_session() as s:
        s.add(SkipList(account_id=aid, fan_id=6301, reason="unreachable"))
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0 and res["skipped_unreachable"] == 1, res
    assert fake.sent == [], fake.sent


async def case_creator_we_follow_skipped():
    """A peer creator who has ACTUALLY blasted promo is skipped — Auto Convo must
    not banter with other creators' bots (the founder problem). Takes $0 spend, no
    prior exchange, AND rich-text promo on the wire; the flag alone is not enough
    (see case_creator_we_follow_without_promo_still_replied)."""
    aid = "ar_creator"
    await _seed_account(aid)
    await _seed_fan(aid, 6401, spend=0)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 6401))
        f.source = "creator_we_follow"
        f.turn_counter = 0
        # Backdated behind _seed_fan's final inbound so HE still spoke last at the
        # eligible age — this row is the promo evidence, not the trigger.
        s.add(Message(account_id=aid, fan_id=6401, message_id=6401 * 100 + 77,
                      direction="in", created_at=datetime.utcnow() - timedelta(minutes=60),
                      body='<p><strong>DOUBLE BUNDLE DEAL</strong> onlyfans.com/x</p>'))
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0 and res["skipped_spam"] == 1, res
    assert fake.sent == [], fake.sent


async def case_creator_we_follow_without_promo_still_replied():
    """REGRESSION (2026-07-24): OF's creator_we_follow flag is not evidence of
    anything — a free page that follows its fans back marks real fans with it. A
    labelled $0 fan who never blasted promo must still get Auto Convo."""
    aid = "ar_creator_ok"
    await _seed_account(aid)
    await _seed_fan(aid, 6402, spend=0)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 6402))
        f.source = "creator_we_follow"
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["skipped_spam"] == 0, ("no promo evidence ⇒ not spam", res)
    assert res["sent"] == 1, res


async def _seed_hot_lead(aid: str, fid: int) -> None:
    await _seed_account(aid)
    await _seed_fan(aid, fid)
    async with get_session() as s:  # a recent inbound TIP (leads the spend rollup)
        s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 100 + 30,
                      direction="in", body="<p>sent you a tip</p>", is_tip=True,
                      created_at=datetime.utcnow() - timedelta(minutes=25)))


async def case_just_paid_fan_is_answered():
    """A fan who tipped minutes ago is Auto-reply's like any other: there is no
    closer engine to hand him to, so nobody else would answer him."""
    aid = "ar_hot_nocloser"
    await _seed_hot_lead(aid, 6502)
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1, res
    assert "skipped_hot_lead" not in res, res
    assert [c for c, _ in fake.sent] == [6502], fake.sent


# ── random step-in ("jitter"): a per-(fan, message) deterministic draw ──────

_JITTER = {"silence_min_minutes": 3, "step_in_max_minutes": 20}


def case_step_in_minutes_helper():
    """The pure helper. Off (0 / absent / == floor) ⇒ exactly silence_min and no
    rng; on ⇒ the same number every call for the same (fan, second), inside
    [silence_min, min(step_in_max, silence_max - 1)]."""
    anchor = datetime(2026, 9, 22, 12, 0, 7, 123456)
    base = {"silence_min_minutes": 3, "silence_max_minutes": 3000}
    assert _step_in_minutes({**base, "step_in_max_minutes": 0}, 1, anchor) == 3
    assert _step_in_minutes(base, 1, anchor) == 3                       # absent
    assert _step_in_minutes({**base, "step_in_max_minutes": 3}, 1, anchor) == 3
    cfg = {**base, "step_in_max_minutes": 20}
    # deterministic: same (fan, anchor) ⇒ same draw, twice
    assert _step_in_minutes(cfg, 42, anchor) == _step_in_minutes(cfg, 42, anchor)
    # second-stable: the microsecond is not part of the seed
    assert (_step_in_minutes(cfg, 42, anchor.replace(microsecond=123456))
            == _step_in_minutes(cfg, 42, anchor.replace(microsecond=999)))
    draws = {_step_in_minutes(cfg, fid, anchor) for fid in range(200)}
    assert all(3 <= d <= 20 for d in draws), draws
    assert len(draws) > 1, ("a band that draws one value is a fixed timer", draws)
    # R1-c: the top is capped one minute under silence_max
    tight = {**cfg, "silence_max_minutes": 8}
    tight_draws = {_step_in_minutes(tight, fid, anchor) for fid in range(200)}
    assert all(3 <= d <= 7 for d in tight_draws), tight_draws


def _find_fans_for(cfg: dict, anchor: datetime, ids=range(7000, 7200)) -> tuple[int, int]:
    """(fid_skip, fid_send): at THIS anchor the first draws > 9, the second <= 7.
    The anchor is fixed first and the fans are searched against it — never the
    other way round — so the case cannot pass by construction."""
    skip = next((f for f in ids if _step_in_minutes(cfg, f, anchor) > 9), None)
    send = next((f for f in ids if _step_in_minutes(cfg, f, anchor) <= 7), None)
    assert skip is not None and send is not None, (skip, send)
    return skip, send


async def case_jitter_gates_candidates():
    """Two fans, both waiting exactly 8 min on the SAME anchor. One drew a
    threshold above 9, the other at or under 7 (a one-minute margin each side
    covers run() taking its own utcnow()). Only the second is covered — and the
    first is not a candidate at all, not merely skipped later. With the old
    `sil_min <= wait` comparison (floor 3) BOTH would have been sent."""
    aid = "ar_jitter"
    await _seed_account(aid, extra=dict(_JITTER))
    cfg = {**_autoreply._defaults(), **_JITTER}
    anchor = (datetime.utcnow() - timedelta(minutes=8)).replace(microsecond=0)
    fid_skip, fid_send = _find_fans_for(cfg, anchor)
    await _seed_fan(aid, fid_skip, last_at=anchor)
    await _seed_fan(aid, fid_send, last_at=anchor)
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["candidates"] == 1 and res["sent"] == 1, res
    assert [c for c, _ in fake.sent] == [fid_send], (fid_skip, fid_send, fake.sent)
    skipped = {k: v for k, v in res.items() if k.startswith("skipped_")}
    assert all(v == 0 for v in skipped.values()), \
        ("the high draw must fall out at candidacy, not in a later gate", skipped)


async def case_jitter_rerolls_on_new_message():
    """The anchor is his LAST inbound. Covered once; he writes again; the engine
    now waits on the NEW message's draw — he is not a candidate while his wait
    is under it (even though it is past silence_min AND past reply_gap), and is
    covered again once the clock passes it. The two draws are not asserted to
    differ (a "can differ" assertion never fails)."""
    aid = "ar_reroll"
    await _seed_account(aid, extra=dict(_JITTER))      # reply_gap = max(5, 3) = 5
    cfg = {**_autoreply._defaults(), **_JITTER}
    fid = 7301
    await _seed_fan(aid, fid, last_ago_min=30)         # 30 > any draw (<= 20)
    fake = _use_fake(); _patch_llm()
    r1 = await run_once(aid, "autoreply", payload={})
    assert r1["sent"] == 1, r1

    # A NEW inbound, 8 min old, whose draw at that second is above 9.
    now = datetime.utcnow()
    new_anchor = (now - timedelta(minutes=8)).replace(microsecond=0)
    if _step_in_minutes(cfg, fid, new_anchor) <= 9:
        for back in range(1, 600):                     # walk the second until it is
            new_anchor = (now - timedelta(minutes=8, seconds=back)).replace(microsecond=0)
            if _step_in_minutes(cfg, fid, new_anchor) > 9:
                break
    draw = _step_in_minutes(cfg, fid, new_anchor)
    assert draw > 9, draw
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 100 + 20,
                      direction="in", body="<p>u there?</p>", created_at=new_anchor))
        f = await s.get(Fan, (aid, fid))
        f.last_message_received_at = new_anchor
        st = await s.get(AutoreplyState, (aid, fid))
        st.last_nudge_at = now - timedelta(minutes=10)  # reply_gap elapsed: only the draw holds him
    await ax.release_fan_lease(aid, fid)

    r2 = await run_once(aid, "autoreply", payload={})
    assert r2["sent"] == 0 and r2["candidates"] == 0, \
        (f"wait 8 < draw {draw}: not a candidate yet", r2)
    assert len(fake.sent) == 1, fake.sent

    # Now the clock passes his draw. Only autoreply's own `now` is shifted.
    shift = timedelta(minutes=draw - 8 + 1)

    class _Later(datetime):
        @classmethod
        def utcnow(cls):
            return datetime.utcnow() + shift

    _autoreply.datetime = _Later  # type: ignore[attr-defined]
    try:
        r3 = await run_once(aid, "autoreply", payload={})
    finally:
        _autoreply.datetime = datetime  # type: ignore[attr-defined]
    assert r3["sent"] == 1, (f"wait {draw + 1} >= draw {draw}: covered", r3)
    assert [c for c, _ in fake.sent] == [fid, fid], fake.sent


def case_config_api_keeps_step_in_max():
    """R1-a: `_validate` rebuilds the blob from the `_INT_KNOBS` whitelist, so
    without the entry the operator's field saved as 200 OK and vanished. And
    the range rule (R2-a): to < from is a 422; 0 is off; equal is no spread."""
    assert _validate({"step_in_max_minutes": "20"})["step_in_max_minutes"] == 20
    assert _validate({"step_in_max_minutes": 0})["step_in_max_minutes"] == 0
    assert _validate({"step_in_max_minutes": 20000})["step_in_max_minutes"] == 10080
    try:
        _validate({"silence_min_minutes": 5, "step_in_max_minutes": 3})
    except HTTPException as e:
        assert e.status_code == 422, e
    else:
        raise AssertionError("to < from must be a 422")
    out = _validate({"silence_min_minutes": 5, "step_in_max_minutes": 5})
    assert out["step_in_max_minutes"] == 5 and out["silence_min_minutes"] == 5, out
    out = _validate({"silence_min_minutes": 5, "step_in_max_minutes": 0})
    assert out["step_in_max_minutes"] == 0, out


async def case_no_candidates_returns_early():
    """R1-d: nobody waiting ⇒ the short return right after the candidate slice —
    the same shape as the disabled / quiet-hours returns, none of the full
    path's counters, and no LLM call. This is what makes the 30 s tick cheap."""
    aid = "ar_empty"
    await _seed_account(aid, extra=dict(_JITTER))
    _use_fake()
    calls: list[dict] = []

    async def _count(**kw):
        calls.append(kw)
        return SimpleNamespace(content="hey", call_id=1)
    llm_client.chat = _count  # type: ignore[attr-defined]

    res = await run_once(aid, "autoreply", payload={})
    body = {k: v for k, v in res.items()
            if k not in ("status", "run_id", "job_id", "duration_ms")
            and not k.startswith("audience_")}
    assert body == {"enabled": True, "candidates": 0, "sent": 0}, res
    assert "skipped_cap" not in res and "model" not in res, ("full path ran", res)
    assert calls == [], ("an empty tick must never reach the model", calls)


class FolderOF(FakeOF):
    """FakeOF plus OF's `/lists/{id}/users` read: {list_id: [fan ids]}."""

    def __init__(self, folders: dict[int, list[int]], *, fail: bool = False):
        super().__init__()
        self.folders = folders
        self.fail = fail
        self.list_reads: list[int] = []

    def list_users_in(self, list_id, *, limit=20, offset=0):
        self.list_reads.append(int(list_id))
        if self.fail:
            raise RuntimeError("OF 500 on /lists/users")
        ids = self.folders.get(int(list_id), [])[offset:offset + limit]
        return [{"id": i} for i in ids]


async def case_folder_pick_scopes_replies():
    """The owner picked folder 555: the waiting fan IN it gets the reply, the
    waiting fan outside it gets nothing — and no LLM call is spent on him."""
    aid = "ar_folder"
    await _seed_account(aid, extra={"list_ids": [555]})
    await _seed_fan(aid, 8001)   # in the folder
    await _seed_fan(aid, 8002)   # waiting too, but not in the folder
    fake = FolderOF({555: [8001, 9999]})
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    calls: list[dict] = []

    async def _count(**kw):
        calls.append(kw)
        return SimpleNamespace(content="hey u 😏", call_id=1)
    llm_client.chat = _count  # type: ignore[attr-defined]

    res = await run_once(aid, "autoreply", payload={})
    assert [c for c, _ in fake.sent] == [8001], (fake.sent, res)
    assert res["sent"] == 1 and res.get("skipped_audience") == 1, res
    assert [c.get("fan_id") for c in calls] == [8001], calls
    assert set(fake.list_reads) == {555}, fake.list_reads   # page + empty terminal page


async def case_folder_read_failure_replies_to_nobody():
    """A folder OF won't read must never widen to every fan: nobody this tick."""
    aid = "ar_folder_fail"
    await _seed_account(aid, extra={"list_ids": [556]})
    await _seed_fan(aid, 8101)
    fake = FolderOF({}, fail=True)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    calls: list[dict] = []

    async def _count(**kw):
        calls.append(kw)
        return SimpleNamespace(content="hey", call_id=1)
    llm_client.chat = _count  # type: ignore[attr-defined]

    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0 and res.get("folder_error") == "read", res
    assert fake.sent == [] and calls == [], (fake.sent, calls)


async def _own(aid: str, username: str) -> str:
    uid = f"u_{username}"
    async with get_session() as s:
        if await s.get(User, uid) is None:
            s.add(User(id=uid, username=username, password="x", is_admin=False))
        s.add(UserAccount(user_id=uid, account_id=aid))
    return uid


async def case_no_llm_key_skips_quietly():
    """Owned account whose owner pasted no key: the house key does NOT apply,
    so the run stops at its one key check — no candidate query, no LLM call."""
    aid = "ar_nokey"
    await _seed_account(aid)
    await _seed_fan(aid, 8201)
    await _own(aid, "nokey_agency")
    fake = _use_fake()
    calls: list[dict] = []

    async def _count(**kw):
        calls.append(kw)
        return SimpleNamespace(content="hey", call_id=1)
    llm_client.chat = _count  # type: ignore[attr-defined]
    swept: list[str] = []
    real = _autoreply._candidates

    async def _spy(account_id, cfg, now):
        swept.append(account_id)
        return await real(account_id, cfg, now)
    _autoreply._candidates = _spy
    try:
        res = await run_once(aid, "autoreply", payload={})
    finally:
        _autoreply._candidates = real
    assert res.get("no_llm_key") and res["sent"] == 0, res
    assert swept == [] and calls == [] and fake.sent == [], (swept, calls, fake.sent)


async def case_llm_key_available_policy():
    prov = "deepseek"
    assert await llm_client.llm_key_available("ar_unowned_x", prov), \
        "un-owned account → the house key (set by the harness) applies"
    await _seed_account("ar_keyed")
    uid = await _own("ar_keyed", "keyed_agency")
    assert not await llm_client.llm_key_available("ar_keyed", prov)
    await tenant_keys.set_keys(uid, {prov: "sk-agency"})
    assert await llm_client.llm_key_available("ar_keyed", prov)
    assert not await llm_client.llm_key_available("ar_keyed", "no-such-provider")


async def case_config_api_reports_key_state():
    """GET tells the page whether the engine's provider has a key, so it can
    show the "add a key" notice; the folder pick round-trips."""
    import auth
    from autoreply_config_api import get_autoreply_config
    await _seed_account("ar_get", extra={"list_ids": [77]})
    uid = await _own("ar_get", "get_agency")
    tok = auth._request_user.set(auth.AuthedUser(uid, "get_agency", frozenset({"ar_get"})))
    try:
        out = await get_autoreply_config(account_id="ar_get")
    finally:
        auth._request_user.reset(tok)
    assert out["llm_key"]["available"] is False and out["llm_key"]["provider"], out
    assert out["config"]["list_ids"] == [77] and out["defaults"]["list_ids"] == [], out
    assert out["vision_key"] == {"provider": "deepinfra", "available": False}, out


def case_config_api_list_ids():
    assert _validate({"list_ids": ["12", 12, 34]})["list_ids"] == [12, 34]
    assert _validate({"list_ids": None})["list_ids"] == []
    for bad in (["fans"], "12", [True]):
        try:
            _validate({"list_ids": bad})
        except HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"{bad!r} must be refused")


async def _counting_llm() -> list[dict]:
    calls: list[dict] = []

    async def _count(**kw):
        calls.append(kw)
        return SimpleNamespace(content="hey u 😏", call_id=1)
    llm_client.chat = _count  # type: ignore[attr-defined]
    return calls


async def case_folder_cap_skips_high_spender():
    """Folder 557 with an "only if spent less than $500" cap: the member under
    it is replied to, the member over it is skipped before any LLM call."""
    aid = "ar_folder_cap"
    await _seed_account(aid, extra={"list_ids": [557], "folder_max_spend_cents": 50_000})
    await _seed_fan(aid, 8301, spend=10_000)   # $100, in the folder
    await _seed_fan(aid, 8302, spend=80_000)   # $800, in the folder, over the cap
    fake = FolderOF({557: [8301, 8302]})
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    calls = await _counting_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert [c for c, _ in fake.sent] == [8301], (fake.sent, res)
    assert res["skipped_audience"] == 1, res
    assert [c.get("fan_id") for c in calls] == [8301], calls


async def case_new_fan_qualifies():
    """Folders off, new fans on (72 h, under $10). Qualify: subscribed 1 day ago
    with $5 spent; and a fan with no sub date whose first message is under an
    hour old. Skipped: subscribed 5 days ago; new but $50 spent; no sub date but
    a subscription charge 10 days ago (the first-seen proxy reads it)."""
    aid = "ar_newfan"
    await _seed_account(aid, extra={"folders_enabled": False, "new_fans_enabled": True,
                                    "new_fan_hours": 72, "new_fan_max_spend_cents": 1_000})
    await _seed_fan(aid, 8401, sub_days=1, spend=500)     # new, low spend → reply
    await _seed_fan(aid, 8402, sub_days=5, spend=0)       # old → skip
    await _seed_fan(aid, 8403, sub_days=1, spend=5_000)   # new, high spend → skip
    await _seed_fan(aid, 8404)                            # no sub date, 50-min history → reply
    await _seed_fan(aid, 8405)                            # no sub date, old charge → skip
    async with get_session() as s:
        for fid in (8404, 8405):
            (await s.get(Fan, (aid, fid))).subscribed_at = None
        s.add(Transaction(account_id=aid, fan_id=8405, kind="subscription",
                          amount_cents=999,
                          occurred_at=datetime.utcnow() - timedelta(days=10)))
    fake = _use_fake()
    await _counting_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert sorted(c for c, _ in fake.sent) == [8401, 8404], (fake.sent, res)
    assert res["skipped_audience"] == 3, res


async def case_folder_failure_keeps_new_fans():
    """Both sources on; the folder read fails. The folder source drops for this
    tick (never widens to every fan), and the new-fan source still answers."""
    aid = "ar_both_fail"
    await _seed_account(aid, extra={"list_ids": [558], "new_fans_enabled": True})
    await _seed_fan(aid, 8501, sub_days=1)   # new → still replied
    await _seed_fan(aid, 8502, sub_days=30)  # old, folder unknown → nobody
    fake = FolderOF({}, fail=True)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    await _counting_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert [c for c, _ in fake.sent] == [8501], (fake.sent, res)
    assert res.get("folder_error") == "read" and res["skipped_audience"] == 1, res
    assert fake.list_reads == [558], fake.list_reads


async def case_no_source_replies_to_nobody():
    aid = "ar_nosource"
    await _seed_account(aid, extra={"folders_enabled": False, "new_fans_enabled": False})
    await _seed_fan(aid, 8601)
    fake = _use_fake()
    calls = await _counting_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 0 and res["skipped_audience"] == 1, res
    assert fake.sent == [] and calls == [], (fake.sent, calls)


async def case_delay_zero_replies_at_once():
    """Delay 0: a message one second old is already a candidate (the 30 s tick
    is then the only wait). The default 24-min delay would not touch it."""
    aid = "ar_delay0"
    await _seed_account(aid, extra={"silence_min_minutes": 0})
    await _seed_fan(aid, 8701, last_at=datetime.utcnow() - timedelta(seconds=1))
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert res["sent"] == 1 and [c for c, _ in fake.sent] == [8701], (res, fake.sent)


async def case_randomised_window():
    """Randomise = step_in_max 2 x delay (what the page saves): every fan's draw
    lands in [d, 2d], the draws spread, and the engine gates on the draw — a fan
    waiting 8 min on a 7-14 band is a candidate only when his draw is <= 8."""
    d = 7
    cfg = {**_autoreply._defaults(), "silence_min_minutes": d, "step_in_max_minutes": 2 * d}
    anchor = (datetime.utcnow() - timedelta(minutes=8, seconds=30)).replace(microsecond=0)
    draws = {fid: _step_in_minutes(cfg, fid, anchor) for fid in range(9000, 9200)}
    assert all(d <= v <= 2 * d for v in draws.values()), draws
    assert len(set(draws.values())) > 3, ("a randomised window must spread", draws)

    aid = "ar_random"
    await _seed_account(aid, extra={"silence_min_minutes": d, "step_in_max_minutes": 2 * d})
    early = next(f for f, v in draws.items() if v <= 8)
    late = next(f for f, v in draws.items() if v >= 10)
    await _seed_fan(aid, early, last_at=anchor)
    await _seed_fan(aid, late, last_at=anchor)
    fake = _use_fake(); _patch_llm()
    res = await run_once(aid, "autoreply", payload={})
    assert [c for c, _ in fake.sent] == [early], (early, late, fake.sent, res)


def case_config_api_audience_and_delay():
    out = _validate({"silence_min_minutes": 0, "step_in_max_minutes": 0})
    assert out["silence_min_minutes"] == 0 and out["step_in_max_minutes"] == 0, out
    out = _validate({"folders_enabled": 0, "new_fans_enabled": 1, "new_fan_hours": "72",
                     "new_fan_max_spend_cents": 1000, "folder_max_spend_cents": None})
    assert out == {"folders_enabled": False, "new_fans_enabled": True, "new_fan_hours": 72,
                   "new_fan_max_spend_cents": 1000, "folder_max_spend_cents": None}, out
    assert _validate({"folder_max_spend_cents": "50000"})["folder_max_spend_cents"] == 50000
    assert _validate({"new_fan_hours": 0})["new_fan_hours"] == 1
    # the retired hidden caps are no longer stored
    assert _validate({"max_lifetime_spend_cents": 5, "recent_spend_days": 2}) == {}
    try:
        _validate({"folder_max_spend_cents": "lots"})
    except HTTPException as e:
        assert e.status_code == 422, e
    else:
        raise AssertionError("a non-number cap must be refused")


_harness.run(
    case_disabled_no_send,
    case_eligible_one_nudge,
    case_nudge_cap,
    case_new_message_covered_again,
    case_reply_gap_holds_fast_remessage,
    case_we_spoke_last_skipped,
    case_silence_too_fresh,
    case_hidden_caps_gone,
    case_not_info_complete_skipped,
    case_info_not_required_covers_incomplete,
    case_unreachable_fan_costs_one_llm_call,
    case_auto_reply_never_sells,
    case_photo_only_unseen_still_replies,
    case_skip_photo_only,
    case_describe_on_reads_the_photo_once,
    case_describe_without_key_is_a_hard_stop,
    case_config_api_keeps_photo_options,
    case_unreachable_fan_skipped,
    case_creator_we_follow_skipped,
    case_creator_we_follow_without_promo_still_replied,
    case_just_paid_fan_is_answered,
    case_step_in_minutes_helper,
    case_jitter_gates_candidates,
    case_jitter_rerolls_on_new_message,
    case_config_api_keeps_step_in_max,
    case_no_candidates_returns_early,
    case_folder_pick_scopes_replies,
    case_folder_read_failure_replies_to_nobody,
    case_no_llm_key_skips_quietly,
    case_llm_key_available_policy,
    case_config_api_reports_key_state,
    case_config_api_list_ids,
    case_folder_cap_skips_high_spender,
    case_new_fan_qualifies,
    case_folder_failure_keeps_new_fans,
    case_no_source_replies_to_nobody,
    case_delay_zero_replies_at_once,
    case_randomised_window,
    case_config_api_audience_and_delay,
)
