#!/usr/bin/env python3
"""
A05 welcome_chatter_for_info — automation tests (spec 05_of_ai_chat.md, DB-rewrite form).

Acceptance the PROMPT calls out: an eligible chat receives ONE AI reply,
persisted; skip_list / blacklist fans are skipped. These cases run the
automation through the real `run_once` dispatcher (registry wiring +
automation_runs exercised) against a fake OFClient + a patched llm_client.chat —
no network.

  case_eligible_chat_gets_one_reply:
      a fan who spoke last gets exactly one reply — an outbound `messages` row
      (body persisted = visible in chat), turn_counter bumped, automation_runs ok.
  case_blacklist_and_skiplist_skipped:
      a globally-blacklisted fan and an account-skip_listed fan are NOT replied.
  case_we_spoke_last_is_skipped:
      a chat whose last message is ours yields no reply (nothing to answer).
  case_spend_gate_skiplists:
      a fan with > $1 lifetime spend is added to skip_list ("spent"), not replied.
  case_too_long_skiplists:
      a fan with ≥ 10 inbound messages is added to skip_list ("too_long").
  case_fan_lease_blocks_reply:
      a live lease held by another automation makes that fan skip this cycle.
  case_dry_run_sends_nothing:
      dry_run generates but neither sends nor bumps turn_counter.
  case_cap_stops_run:
      llm_client raising LLMCapExceeded halts the run cleanly (cap_hit=True).

Run: ./venv/bin/python service/tests/test_welcome_chatter_for_info.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
import automations.welcome_chatter_for_info as a05  # noqa: E402
from automations.welcome_chatter_for_info import (  # noqa: E402
    _HISTORY_TAIL, _Candidate, _build_messages, _extract_and_fill,
    _extract_worthwhile, _graduate,
)
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRun, Blacklist, Fan, FanLease, FanProfile,
    FunnelState, MassRun, Message, ScheduledJob, SkipList,
)
from llm_client import LLMCapExceeded  # noqa: E402

_T0 = datetime(2026, 6, 4, 12, 0, 0)


# ── Fakes (no network) ────────────────────────────────────────────────

class FakeOF:
    """Records sends and echoes a real-looking OF message object."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.marked_read: list[int] = []
        self.nicks: list[tuple[int, str]] = []
        self.notes: list[tuple[int, str]] = []
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-04T12:30:00+00:00"}

    def set_fan_custom_name(self, user_id, name) -> dict:
        self.nicks.append((int(user_id), name))
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        self.notes.append((int(user_id), note))
        return {"success": True}

    def mark_chat_read(self, chat_id) -> dict:
        self.marked_read.append(int(chat_id))
        return {"success": True}

    def get_user(self, user_id) -> dict:
        # Default: an active fan (subscribedOn truthy) → a no-id send reads as a
        # transient blip. Tests override this to model a lapsed / deleted sub.
        return {"id": int(user_id), "subscribedOn": True}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "heyy what are you up to tonight? 😏") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply, call_id=1)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]


def _patch_llm_cap() -> None:
    async def _raise(**kw):
        raise LLMCapExceeded("acc", 100, 200)
    llm_client.chat = _raise  # type: ignore[attr-defined]


# ── Seeding ───────────────────────────────────────────────────────────

async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fan_id: int, *, spend_cents: int = 0,
                    name: str | None = None) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id,
                      of_display_name=name, lifetime_spend_cents=spend_cents))


async def _add_msgs(aid: str, fan_id: int, msgs: list[tuple[str, str]]) -> None:
    """msgs = [(direction, body), …] in chronological order."""
    async with get_session() as s:
        for i, (direction, body) in enumerate(msgs):
            s.add(Message(
                account_id=aid, fan_id=fan_id, message_id=fan_id * 1000 + i,
                direction=direction, body=body,
                created_at=_T0 + timedelta(minutes=i),
            ))


async def _add_msg_row(aid: str, fan_id: int, direction: str, body: str,
                       created_at: datetime, *, automation_kind: str | None = None,
                       media_count: int = 0, image_desc: str | None = None) -> None:
    """ONE message row, with the columns `_add_msgs` does not expose.

    `_add_msgs` writes plain text rows on a fixed one-per-minute ladder, which is
    all most cases need. A case about WHICH KIND of row took the turn needs
    `automation_kind`, and a case about a photo needs the two media columns — so
    this is the same insert with those three parameters and an explicit timestamp,
    rather than four optional arguments bolted onto the list helper."""
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id,
            message_id=int(created_at.timestamp() * 1000) % 1_000_000 + fan_id * 1000,
            direction=direction, body=body, created_at=created_at,
            automation_kind=automation_kind, media_count=media_count,
            image_desc=image_desc,
        ))


async def _seed_unlock(aid: str, fan_id: int, price_cents: int = 500) -> None:
    """He BOUGHT a PPV — a priced outbound with is_paid set. `is_paid` and not
    `purchased_at` is what marks a purchase: on prod only 540 of 3,484 paid rows
    carry that timestamp, so keying off it would miss 85% of real buyers."""
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id,
                      message_id=fan_id * 1000 + 900,
                      direction="out", body="unlock me", is_paid=True,
                      price_cents=price_cents,
                      created_at=_T0 - timedelta(hours=1)))


async def _seed_tip(aid: str, fan_id: int, price_cents: int = 300) -> None:
    """He TIPPED — an inbound is_tip row."""
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id,
                      message_id=fan_id * 1000 + 901,
                      direction="in", body="here u go", is_tip=True,
                      price_cents=price_cents,
                      created_at=_T0 - timedelta(hours=1)))


async def _geninfo_targets(s, aid: str) -> set[int]:
    """fan_ids targeted by any enqueued gen_info job for this account (force_ids)."""
    import json as _json
    jobs = (await s.execute(
        select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                   ScheduledJob.kind == "gen_info")
    )).scalars().all()
    out: set[int] = set()
    for j in jobs:
        out.update(_json.loads(j.payload_json or "{}").get("force_ids", []))
    return out


# ── 🔴 Acceptance: an eligible chat receives exactly one reply ────────

async def case_eligible_chat_gets_one_reply():
    aid = "acc_c1"
    await _seed_account(aid)
    await _seed_fan(aid, 1001, name="Bob")
    await _add_msgs(aid, 1001, [("out", "hey babe"), ("in", "hi! how are you")])
    _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    assert res["replies_sent"] == 1, res
    assert res["errors"] == 0 and res["skipped_locked"] == 0, res

    async with get_session() as s:
        out = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.fan_id == 1001,
                                  Message.direction == "out",
                                  Message.message_id >= 9_000_000_000_000)
        )).scalars().all()
        assert len(out) == 1 and out[0].body, ("one persisted reply", out)

        fan = await s.get(Fan, (aid, 1001))
        assert fan.turn_counter == 1, ("turn bumped", fan.turn_counter)

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs


# ── blacklist + skip_list fans are skipped ────────────────────────────

async def case_blacklist_and_skiplist_skipped():
    aid = "acc_c2"
    await _seed_account(aid)
    # 2001 blacklisted (global), 2002 skip_listed (account), 2003 eligible.
    for fid in (2001, 2002, 2003):
        await _seed_fan(aid, fid)
        await _add_msgs(aid, fid, [("in", "yo")])
    async with get_session() as s:
        s.add(Blacklist(fan_id=2001, reason="manual"))
        s.add(SkipList(account_id=aid, fan_id=2002, reason="info"))
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res
    assert res["skipped_listed"] == 2, res
    assert {c for c, _ in fake.sent} == {2003}, fake.sent


# ── we spoke last → nothing to answer ─────────────────────────────────

async def case_we_spoke_last_is_skipped():
    aid = "acc_c3"
    await _seed_account(aid)
    await _seed_fan(aid, 3001)
    await _add_msgs(aid, 3001, [("in", "hey"), ("out", "hey you 💕")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res
    assert res["skipped_not_turn"] == 1, res
    assert fake.sent == [], fake.sent


# ── spend > $1 → skip_list("spent") ───────────────────────────────────

async def case_spend_gate_skiplists():
    """He BOUGHT CONTENT (a PPV unlock) → graduated to the seller."""
    aid = "acc_c4"
    await _seed_account(aid)
    await _seed_fan(aid, 4001)
    await _add_msgs(aid, 4001, [("in", "can we chat")])
    await _seed_unlock(aid, 4001)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res
    assert res["newly_skiplisted"] == 1, res
    assert fake.sent == [], fake.sent

    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 4001))
        assert sk is not None and sk.reason == "spent", sk
        # The cutoff also collects info: a final gen_info regen is enqueued so the
        # human taking over the paying fan gets a fresh profile/nickname/note.
        assert 4001 in await _geninfo_targets(s, aid), "spent cutoff must enqueue gen_info"


async def case_tip_also_graduates():
    """A TIP is content money too — same hand-off as an unlock."""
    aid = "acc_c4b"
    await _seed_account(aid)
    await _seed_fan(aid, 4101)
    await _add_msgs(aid, 4101, [("in", "can we chat")])
    await _seed_tip(aid, 4101)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["newly_skiplisted"] == 1, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 4101))
        assert sk is not None and sk.reason == "spent", sk


async def case_subscriber_is_not_graduated():
    """A SUBSCRIPTION IS NOT A PURCHASE — the bug this gate used to have.

    The old test was `lifetime_spend_cents > $1`, and that column is fed by the
    transactions ledger, which counts `subscription` / `rebill` rows. So on a paid
    page every new subscriber crossed the line the moment he subscribed: he was
    skip_listed 'spent' PERMANENTLY (skip_list has no expiry) and this engine never
    gathered a single fact about him. Prod 2026-08-15: 17 fans graduated on a
    subscription alone, and 1,766 have non-zero lifetime spend having never bought
    a thing. He is a lead, not a customer — keep working him."""
    aid = "acc_c4c"
    await _seed_account(aid)
    await _seed_fan(aid, 4201, spend_cents=1200)  # $12 sub — no content purchase
    await _add_msgs(aid, 4201, [("in", "can we chat")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, ("a subscriber is still ours to work", res)
    assert res["newly_skiplisted"] == 0, res
    async with get_session() as s:
        assert await s.get(SkipList, (aid, 4201)) is None, "must not graduate a subscriber"


# ── ≥10 fan messages → skip_list("too_long") ──────────────────────────

async def case_too_long_skiplists():
    aid = "acc_c5"
    await _seed_account(aid)
    await _seed_fan(aid, 5001)
    await _add_msgs(aid, 5001, [("in", f"msg {i}") for i in range(10)])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res
    assert res["newly_skiplisted"] == 1, res
    assert fake.sent == [], fake.sent

    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 5001))
        assert sk is not None and sk.reason == "too_long", sk
        # The 10-message cutoff also enqueues a final gen_info regen (collect info).
        assert 5001 in await _geninfo_targets(s, aid), "too_long cutoff must enqueue gen_info"


# ── emoji-only reactions don't burn a slot toward the too_long cap ─────

async def case_emoji_reactions_not_counted_toward_cap():
    """A fan who taps reaction emoji between real lines must NOT graduate
    'too_long' before he's actually said _MAX_FAN_MESSAGES real things — only
    substantive inbound counts (live: fan 331806865 hit the 10-cap on 5 real
    msgs + 5 emoji). The emoji still reach the model's history; just not the cap."""
    aid = "acc_emoji"
    await _seed_account(aid)
    await _seed_fan(aid, 5201)
    # 11 inbound total, but only 5 substantive (< _MAX_FAN_MESSAGES=10).
    msgs: list[tuple[str, str]] = []
    for i in range(5):
        msgs.append(("in", f"real message {i}"))
        msgs.append(("in", "😍"))      # emoji reaction — must not count
    msgs.append(("in", "🔥🔥"))         # 11th inbound, still emoji-only
    await _add_msgs(aid, 5201, msgs)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, ("5 substantive < cap → still replies", res)
    assert res["newly_skiplisted"] == 0, ("no too_long graduation on emoji", res)
    assert len(fake.sent) == 1, fake.sent
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 5201))
        assert sk is None, ("emoji spam must not skip-list the fan", sk)


# ── a live fan-lease blocks the reply this cycle ──────────────────────

async def case_fan_lease_blocks_reply():
    aid = "acc_c6"
    await _seed_account(aid)
    for fid in (6001, 6002):
        await _seed_fan(aid, fid)
        await _add_msgs(aid, fid, [("in", "hi")])
    fake = _use_fake()
    _patch_llm()

    assert await acquire_fan_lease(aid, 6001, "send_welcome", ttl_s=300) is True

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["skipped_locked"] == 1, res
    assert res["replies_sent"] == 1, res
    assert {c for c, _ in fake.sent} == {6002}, fake.sent


# ── W3: a fan on post-send cooldown is skipped (before the lease) ─────

async def case_cooldown_skips_reply():
    aid = "acc_c6b"
    await _seed_account(aid)
    for fid in (6101, 6102):
        await _seed_fan(aid, fid)
        await _add_msgs(aid, fid, [("in", "hi")])
    fake = _use_fake()
    _patch_llm()

    # Another automation messaged 6101 moments ago → it's resting.
    await ax.start_fan_cooldown(aid, 6101)

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    # The resting fan is skipped — caught by the paused gate (gather pre-filters a
    # pre-set cooldown as skipped_listed; the BEFORE-acquire fan_on_cooldown check
    # catches one set mid-tick). Either way 6101 is never messaged.
    assert res["skipped_cooldown"] + res["skipped_listed"] == 1, res
    assert res["replies_sent"] == 1, res
    assert {c for c, _ in fake.sent} == {6102}, fake.sent
    # A confirmed reply rests 6102 too (one send → cooldown the fan).
    assert await ax.fan_on_cooldown(aid, 6102) is True


# ── W3 live-chat variant: short rest + lease RELEASED so it stays responsive ─

async def case_reply_short_cooldown_releases_lease():
    aid = "acc_c6c"
    await _seed_account(aid)
    await _seed_fan(aid, 6201)
    await _add_msgs(aid, 6201, [("in", "hey")])
    _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res

    # Unlike the other senders, welcome_chatter_for_info RELEASES its lease on success so the
    # next reply can re-acquire once the short rest elapses (live chat must not
    # go silent for the 900s lease TTL).
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 6201)) is None, "lease released after reply"

    # The rest is the SHORT live-chat cooldown (~45s), not the 30-min default.
    async with get_session() as s:
        until = (await s.get(Fan, (aid, 6201))).automation_paused_until
    assert until is not None and await ax.fan_on_cooldown(aid, 6201) is True
    # Well under the 30-min generic cooldown — proves the welcome_chatter_for_info override.
    assert until < datetime.utcnow() + timedelta(minutes=5), until


# ── dry_run: generate but neither send nor bump ───────────────────────

async def case_dry_run_sends_nothing():
    aid = "acc_c7"
    await _seed_account(aid)
    await _seed_fan(aid, 7001)
    await _add_msgs(aid, 7001, [("in", "hey there")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={"dry_run": True})
    assert res["replies_sent"] == 1, res  # counted as would-send
    assert fake.sent == [], "dry run must not call send_message"

    async with get_session() as s:
        out = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.message_id >= 9_000_000_000_000)
        )).scalars().all()
        assert out == [], "dry run writes no outbound row"
        fan = await s.get(Fan, (aid, 7001))
        assert fan.turn_counter == 0, "dry run does not bump turn_counter"


# ── daily LLM cap halts the run cleanly ───────────────────────────────

async def case_cap_stops_run():
    aid = "acc_c8"
    await _seed_account(aid)
    await _seed_fan(aid, 8001)
    await _add_msgs(aid, 8001, [("in", "hello")])
    fake = _use_fake()
    _patch_llm_cap()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res  # the run succeeds; it just stops early
    assert res["cap_hit"] is True, res
    assert res["replies_sent"] == 0, res
    assert fake.sent == [], fake.sent


async def case_rejected_key_stops_run_after_one_call():
    """A wrong key (401) is the same for every fan: the run makes ONE reply
    call, stops, sends nothing, and leaves the owner-facing payload in its
    stats — that is what the page's "AI key" notice reads."""
    aid = "acc_c8_key"
    await _seed_account(aid)
    for fid in (8101, 8102, 8103):
        await _seed_fan(aid, fid)
        await _add_msgs(aid, fid, [("in", "hello")])
    fake = _use_fake()
    reply_calls: list[int] = []

    async def _rejected(**kw):
        if kw.get("purpose") == "welcome_chatter_for_info":
            reply_calls.append(1)
        raise llm_client.LLMKeyError("invalid", "deepseek", kw.get("purpose", ""),
                                     status=401, detail="HTTP 401: bad key")
    llm_client.chat = _rejected  # type: ignore[attr-defined]

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    assert len(reply_calls) == 1, f"one reply call, not one per fan: {len(reply_calls)}"
    assert res["replies_sent"] == 0 and fake.sent == [], (res, fake.sent)
    ke = res.get("key_error") or {}
    assert ke.get("error") == "api_key_invalid", res
    assert ke.get("fix_url") == "/settings/ai-keys", ke
    async with get_session() as s:
        run = (await s.execute(select(AutomationRun).where(
            AutomationRun.account_id == aid))).scalars().one()
        assert json.loads(run.stats_json)["key_error"]["error"] == "api_key_invalid", run.stats_json


async def case_missing_key_skips_run_without_a_call():
    """No key for the run's provider: skip the whole run before any LLM call
    (the autoreply behaviour), reported as `no_llm_key`."""
    aid = "acc_c8_nokey"
    await _seed_account(aid)
    await _seed_fan(aid, 8201)
    await _add_msgs(aid, 8201, [("in", "hello")])
    fake = _use_fake()
    calls: list[int] = []

    async def _never(**kw):
        calls.append(1)
        raise AssertionError("an LLM call was made with no key")
    llm_client.chat = _never  # type: ignore[attr-defined]
    real = llm_client.llm_key_available

    async def _no_key(*a, **k):
        return False
    llm_client.llm_key_available = _no_key  # type: ignore[assignment]
    try:
        res = await run_once(aid, "welcome_chatter_for_info", payload={})
    finally:
        llm_client.llm_key_available = real  # type: ignore[assignment]
    assert res.get("no_llm_key") == "deepseek", res
    assert calls == [] and fake.sent == [], (calls, fake.sent)


async def case_no_id_pauses_fan_no_double_reply():
    """A 200-without-id can't be persisted (message_id is the PK), so eligibility
    ('fan spoke last') would re-fire next tick → double-reply. The fan must be
    paused (automation_paused_until set) instead.

    NB: NO _seed_fan — candidates come from the messages table, so an eligible
    fan may have no Fan row yet. The pause must UPSERT (a plain UPDATE would
    no-op on the missing row and the double-reply would survive)."""
    aid = "acc_noid"
    await _seed_account(aid)
    await _add_msgs(aid, 9101, [("in", "hey there")])  # spoke last, NO Fan row

    fake = FakeOF()
    fake.send_message = lambda chat_id, text, **kw: {"success": True}  # 200, no id
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9101))
        assert f is not None, "no-id pause must UPSERT a Fan row even when none existed"
        assert f.automation_paused_until is not None, \
            "no-id send must pause the fan so it isn't re-replied next tick"
    # subscribedOn truthy (FakeOF default) → transient → SHORT pause (≈1h), not a week.
    assert f.automation_paused_until < datetime.utcnow() + timedelta(hours=6), \
        "an active fan's no-id must stay a short retry pause, not the week-long quarantine"
    assert f.subscription_status != "expired", "active fan must not be marked expired"


async def case_no_id_lapsed_sub_quarantines_a_week():
    """The burn-loop bug: a fan whose subscription lapsed no-id's on EVERY send, so
    'fan spoke last' re-fires it every tick forever (1000+ wasted LLM calls). When
    the probe (get_user) shows the sub is gone (`subscribedOn` falsy), welcome_chatter_for_info
    must quarantine the fan for a WEEK and record WHY — not keep re-calling."""
    aid = "acc_lapsed"
    await _seed_account(aid)
    await _add_msgs(aid, 9201, [("in", "how badly?")])  # spoke last

    fake = FakeOF()
    fake.send_message = lambda chat_id, text, **kw: {"success": True}    # 200, no id
    fake.get_user = lambda user_id: {"id": int(user_id), "subscribedOn": False}  # lapsed
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9201))
    assert f is not None and f.automation_paused_until is not None, res
    assert f.automation_paused_until > datetime.utcnow() + timedelta(days=6), \
        "lapsed-sub fan must be rested ~a week (retry then), not a 1h pause"
    assert f.subscription_status == "expired", \
        "quarantine must record WHY the fan was undeliverable"


async def case_turn_cap_ends_the_interview():
    """A deliverable fan who chats forever without ever revealing the bio facts
    would never finish the gather on his own. After _MAX_TURNS replies the
    interview ends and he moves on to his gen_info openers — and this fan has no
    profile, so there are none, and welcome_chatter_for_info graduates him instead of looping.
    No further reply this tick either way."""
    from automations.welcome_chatter_for_info import _MAX_TURNS
    aid = "acc_turncap"
    await _seed_account(aid)
    await _seed_fan(aid, 9301)
    await _add_msgs(aid, 9301, [("in", "hey")])  # spoke last, facts still empty
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9301))
        f.turn_counter = _MAX_TURNS  # hit the cap
    fake = _use_fake(); _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0 and res["newly_skiplisted"] == 1, res
    assert fake.sent == [], "capped fan must NOT get another reply — hand off instead"


async def case_failed_send_still_counts_a_turn():
    """The cap must count TRIES, not just confirmed sends: a no-id send (nothing
    landed) must still bump turn_counter, else an undeliverable fan sits at 0
    forever and the _MAX_TURNS cap could never fire. (subscribedOn truthy → the
    no-id is treated as transient, so the fan isn't quarantined this tick.)"""
    aid = "acc_tryct"
    await _seed_account(aid)
    await _seed_fan(aid, 9401)
    await _add_msgs(aid, 9401, [("in", "hey")])  # spoke last → eligible
    fake = FakeOF()
    fake.send_message = lambda chat_id, text, **kw: {"success": True}  # 200, no id
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    async with get_session() as s:
        f = await s.get(Fan, (aid, 9401))
    assert f is not None and f.turn_counter == 1, \
        ("a tried-but-not-sent reply must count toward the cap", f and f.turn_counter)


# ── mark-read fires once after a send, never on a skip ────────────────

async def case_mark_read_after_send_not_on_skip():
    """A replied chat is marked read exactly once; a fan we DON'T reply to
    (here: we spoke last) is never marked read. Reading never marks read in V2,
    so this is the only place the unread badge is cleared."""
    aid = "acc_mr"
    await _seed_account(aid)
    await _seed_fan(aid, 10001, name="Replyme")   # fan spoke last → replied
    await _add_msgs(aid, 10001, [("out", "hi"), ("in", "hey what's up")])
    await _seed_fan(aid, 10002, name="Skipme")    # we spoke last → skipped
    await _add_msgs(aid, 10002, [("in", "yo"), ("out", "hey you 💕")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res
    assert fake.marked_read == [10001], \
        ("mark_chat_read once for the replied fan, never for the skip", fake.marked_read)


# ── a mark-read failure must NOT break the already-persisted send ─────

async def case_mark_read_failure_does_not_break_send():
    aid = "acc_mrfail"
    await _seed_account(aid)
    await _seed_fan(aid, 11001, name="Bob")
    await _add_msgs(aid, 11001, [("in", "hi! how are you")])
    fake = _use_fake()

    def _boom(chat_id):
        raise RuntimeError("OF 500 on mark-as-read")
    fake.mark_chat_read = _boom
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    assert res["replies_sent"] == 1, res
    assert res["errors"] == 0, res  # the send + persist still succeeded

    async with get_session() as s:
        out = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.fan_id == 11001,
                                  Message.direction == "out",
                                  Message.message_id >= 9_000_000_000_000)
        )).scalars().all()
        assert len(out) == 1, ("send persisted despite mark-read failure", out)


# ── refresh-if-stale: a reply enqueues a gen_info job for a stale fan ──

async def case_reply_refreshes_stale_profile():
    """After replying, welcome_chatter_for_info enqueues a gen_info refresh for a fan whose profile
    is stale (here: no profile yet), so the stored info keeps up with the convo. A
    fan whose profile is already fresh enqueues NOTHING. The job is enqueued as
    refill_ids (gate re-checked at run time), NOT force_ids — the runaway fix."""
    aid = "acc_refresh"
    await _seed_account(aid)
    # Stale fan: 8 inbound (≥ the 8-new floor), no fan_profiles row → stale → enqueue.
    await _seed_fan(aid, 12001, name="Stale")
    await _add_msgs(aid, 12001, [("out", "hey")] + [("in", f"hi {i}") for i in range(8)])
    # Fresh fan: a profile generated at the same msg count, just now → NOT stale.
    await _seed_fan(aid, 12002, name="Fresh")
    await _add_msgs(aid, 12002, [("out", "yo"), ("in", "hey")])  # 1 inbound
    async with get_session() as s:
        s.add(FanProfile(account_id=aid, fan_id=12002, nickname="Fresh",
                         message_count_at_gen=1, last_generated_at=datetime.utcnow()))
    _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 2, res

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalars().all()
        targets = []
        for j in jobs:
            import json as _json
            # refill_ids now (was force_ids): the run re-checks the gate, so a
            # duplicate slipping through no-ops instead of re-mining every reply.
            targets += _json.loads(j.payload_json or "{}").get("refill_ids", [])
        assert 12001 in targets, ("stale fan refresh enqueued", targets)
        assert 12002 not in targets, ("fresh fan must NOT be refreshed", targets)


async def case_refresh_dedups_pending_job():
    """REGRESSION (one fan drew 23 regens in 3h): the refresh hook must NOT stack a
    second gen_info job when one is already pending/running for that fan. A reply to
    a stale fan who already has a queued gen_info job enqueues NOTHING new."""
    aid = "acc_refresh_dedup"
    await _seed_account(aid)
    await _seed_fan(aid, 13001, name="Stale")
    await _add_msgs(aid, 13001, [("out", "hey")] + [("in", f"hi {i}") for i in range(8)])
    # A refresh is already in flight for this fan (payload carries [13001]).
    await ax.enqueue_job(aid, "gen_info", payload={"refill_ids": [13001]})
    _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalars().all()
    assert len(jobs) == 1, ("dedup failed — a duplicate gen_info job was stacked", len(jobs))


async def case_inline_fill_saves_facts_before_reply():
    """V1 inline fill: welcome_chatter_for_info extracts + saves the facts he stated THIS tick
    (before the reply), so his_age lands immediately — not on a later gen_info pass."""
    aid = "acc_fill1"
    await _seed_account(aid)
    await _seed_fan(aid, 17001)
    await _add_msgs(aid, 17001, [("in", "haha im 31 btw, work as a chef")])
    fake = _use_fake()

    async def _smart_chat(**kw):
        # The extraction call uses the profile-analyzer system prompt; reply call doesn't.
        if "profile analyzer" in kw["messages"][0]["content"]:
            return SimpleNamespace(
                content='{"his_age":"31","occupation":"chef"}',
                parsed={"his_age": "31", "occupation": "chef"}, call_id=1)
        return SimpleNamespace(content="mmm a chef huh 😏", call_id=2)
    llm_client.chat = _smart_chat  # type: ignore[attr-defined]

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res
    async with get_session() as s:
        f = await s.get(Fan, (aid, 17001))
        assert f.his_age == "31" and f.occupation == "chef", (f.his_age, f.occupation)


async def case_nickname_pushed_on_reply():
    """The structured nickname (Name/Loc/Age/Job) is pushed to OF + mirrored to
    fans.custom_nickname on a convo tick."""
    aid = "acc_nick1"
    await _seed_account(aid)
    await _seed_fan(aid, 18001)
    await _add_msgs(aid, 18001, [("in", "hey")])
    async with get_session() as s:
        f = await s.get(Fan, (aid, 18001))
        f.real_name = "Jack"; f.his_age = "31"; f.home_country = "Slovenia"
        f.occupation = "chef"; f.questions_asked = json.dumps(["name", "age", "job"])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res
    assert (18001, "Jack/Slovenia/31/chef") in fake.nicks, fake.nicks
    async with get_session() as s:
        assert (await s.get(Fan, (aid, 18001))).custom_nickname == "Jack/Slovenia/31/chef"


async def case_info_complete_keeps_gathering_if_questions_left():
    """Info-complete (≥75%) is NOT enough to hand off — if topics remain unasked
    (e.g. name, body-prefs), welcome_chatter_for_info keeps gathering ('lots of info' first)."""
    aid = "acc_info1"
    await _seed_account(aid)
    await _seed_fan(aid, 15001)
    await _add_msgs(aid, 15001, [("in", "hey")])
    async with get_session() as s:
        f = await s.get(Fan, (aid, 15001))
        f.his_age = "31"; f.home_city = "Austin"; f.hobbies = "hiking"
        f.recent_events = '["a trip"]'          # 4/4 groups → info-complete
        f.questions_asked = json.dumps([])       # but nothing asked → name/boobs_ass remain
    fake = _use_fake(); _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1 and res["newly_skiplisted"] == 0, res
    async with get_session() as s:
        assert await s.get(SkipList, (aid, 15001)) is None, "must NOT hand off yet"


async def case_info_complete_handoff_regens_geninfo():
    """Once info-complete AND every topic has been asked, welcome_chatter_for_info hands off:
    skip_list('info') + enqueues a gen_info job to (re)generate Q/Teases."""
    aid = "acc_info2"
    await _seed_account(aid)
    await _seed_fan(aid, 16001)
    await _add_msgs(aid, 16001, [("in", "hey")])
    async with get_session() as s:
        f = await s.get(Fan, (aid, 16001))
        f.real_name = "Jack"; f.his_age = "31"; f.home_city = "Austin"
        f.home_country = "USA"; f.hobbies = "hiking"; f.occupation = "engineer"
        f.likes_boobs = True; f.recent_events = '["a trip"]'; f.fetishes = "feet"
        f.questions_asked = json.dumps(
            ["name", "age", "location", "country_from_city", "city",
             "job", "hobbies", "boobs_ass", "recent_events"])
    fake = _use_fake(); _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0 and res["newly_skiplisted"] == 1, res
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 16001))
        assert sk is not None and sk.reason == "info", sk
        jobs = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "gen_info")
        )).scalars().all()
        assert len(jobs) == 1, ("gen_info regen enqueued at handoff", jobs)


async def case_history_tail_override_truncates_convo():
    """The `history_tail` payload knob caps how many recent messages reach the
    model; absent → the _HISTORY_TAIL default. _build_messages embeds the trimmed
    convo in the user content, so we count the FAN/YOU turns there."""
    f = Fan(account_id="acc_ht", fan_id=12345)
    c = _Candidate(12345)
    # 6 inbound turns, oldest→newest, distinct so we can spot which survive.
    c.messages = [("in", f"msg{i}") for i in range(6)]
    c.last_dir = "in"

    def _turns(history_tail):
        msgs, _ = _build_messages("persona", f, c, set(), history_tail)
        content = "\n".join(m["content"] for m in msgs)
        return [f"msg{i}" for i in range(6) if f"msg{i}" in content]

    # history_tail=2 → only the last two messages.
    assert _turns(2) == ["msg4", "msg5"], _turns(2)
    # Default (>= 6) → all of them survive.
    assert _turns(_HISTORY_TAIL) == [f"msg{i}" for i in range(6)], _turns(_HISTORY_TAIL)


async def case_reply_and_extract_use_separate_tails():
    """Cost trim: the REPLY prompt carries ~20 recent turns (the durable info is in
    the facts block), but the fact-EXTRACT prompt only needs the last few turns to
    catch a just-stated fact — so they use different default tails (20 vs 8)."""
    from automations.welcome_chatter_for_info import (
        _EXTRACT_HISTORY_TAIL, _build_messages, _extract_messages,
    )
    assert _HISTORY_TAIL == 20 and _EXTRACT_HISTORY_TAIL == 8, \
        (_HISTORY_TAIL, _EXTRACT_HISTORY_TAIL)

    f = Fan(account_id="acc_tails", fan_id=222)
    c = _Candidate(222)
    c.messages = [("in", f"m{i}") for i in range(30)]  # 30 turns, more than either tail
    c.last_dir = "in"

    # Reply default → last 20 turns (m10..m29), NOT the older ones.
    reply_msgs, _ = _build_messages("persona", f, c, set())
    reply = "\n".join(m["content"] for m in reply_msgs)
    assert "m10" in reply and "m29" in reply and "m9" not in reply, "reply tail != 20"

    # Extract default → last 8 turns only (m22..m29).
    extract = "\n".join(m["content"] for m in _extract_messages(f, c))
    assert "m22" in extract and "m29" in extract and "m21" not in extract, "extract tail != 8"


# ── W7 cross-tick ownership: a mid-funnel fan is NOT interleaved ──────

async def case_mid_funnel_fan_skipped():
    """A fan who spoke last would normally get a reply — but if reply_mass_funnel
    owns them (a pending funnel_state under one of this account's mass runs),
    welcome_chatter_for_info must stand down so it doesn't interleave the funnel's step waits.
    force_ids still overrides."""
    aid = "acc_w7funnel"
    await _seed_account(aid)
    await _seed_fan(aid, 7777, name="Mid")
    await _add_msgs(aid, 7777, [("out", "step 1 of funnel"), ("in", "ooh tell me more")])
    async with get_session() as s:
        mr = MassRun(account_id=aid, status="ok")
        s.add(mr)
        await s.flush()
        s.add(FunnelState(mass_run_id=mr.id, fan_id=7777, status="pending"))
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res
    assert fake.sent == [], fake.sent

    # force_ids overrides the funnel-ownership skip.
    res2 = await run_once(aid, "welcome_chatter_for_info", payload={"force_ids": [7777]})
    assert res2["replies_sent"] == 1, res2


async def case_only_fan_ids_scopes_to_one_fan():
    """W7 fan-scope: with only_fan_ids set, welcome_chatter_for_info answers ONLY that fan even
    when other fans are equally eligible (no full-account sweep)."""
    aid = "acc_w7scope"
    await _seed_account(aid)
    await _seed_fan(aid, 8801, name="A")
    await _seed_fan(aid, 8802, name="B")
    await _add_msgs(aid, 8801, [("out", "hi"), ("in", "hey you")])
    await _add_msgs(aid, 8802, [("out", "hi"), ("in", "hey you too")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={"only_fan_ids": [8801]})
    assert res["replies_sent"] == 1, res
    assert [cid for cid, _ in fake.sent] == [8801], f"only fan 8801 should be answered, got {fake.sent}"


async def case_graduation_closes_the_fan_to_every_bot():
    """welcome_chatter_for_info finishing with a fan must leave NO automation able to pick him up.

    One marker: `skip_list('info')` is what the dispatcher reads as "left the
    gather loop", and every other engine honours it as an ordinary skip."""
    aid = "acc_graduate"
    await _seed_account(aid)
    fan = 7701
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan))
    # client=None → the OF nick/notes push throws and is swallowed; the skip-list
    # and gen_info enqueue run first.
    await _graduate(None, aid, fan, Fan(account_id=aid, fan_id=fan))
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, fan))
        targets = await _geninfo_targets(s, aid)
    assert sk is not None and sk.reason == "info", "graduation must skip-list 'info'"
    assert fan in targets, "graduation must enqueue the final gen_info regen"


async def case_question_order_age_first_boobs_last():
    """Natural-flow gather: the bot is offered the remaining gaps as SOFT goals (it
    picks what fits the convo, any order) — but the PRIORITY list still puts the
    get-to-know-you facts first and the spicy boobs/ass question LAST. With name
    known, the first gap is 'age' and the last is 'boobs_ass'."""
    from automations.welcome_chatter_for_info import _questions_still_needed
    f = Fan(account_id="x", fan_id=1, real_name="Jack")  # name known, rest blank
    keys = [k for k, _ in _questions_still_needed(f, set())]
    assert keys and keys[0] == "age", keys
    assert keys[-1] == "boobs_ass", keys


async def case_name_capped_at_two_asks_then_drops():
    """HARD RULE — never ask the same core fact a 3rd time. Marking the PRIORITY
    target (not the poke-later-reordered front) escalates name→name:2 over two
    ask-turns; on the third turn `_questions_still_needed` has dropped name, so a
    dodgy fan graduates (handoff → gen_info makes the nickname itself)."""
    from automations.welcome_chatter_for_info import _questions_still_needed, _primary_ask_target
    f = Fan(account_id="x", fan_id=1)  # blank profile → name is top priority
    asked: set[str] = set()
    for turn in (1, 2):
        presented = [k for k, _ in _questions_still_needed(f, asked)]
        target = _primary_ask_target(presented)
        assert target == "name", (turn, presented)  # model fixates on the name gap
        # mimic _mark_question_asked's escalating mark
        asked.add(target if target not in asked else f"{target}:2")
    assert "name:2" in asked, asked
    keys3 = [k for k, _ in _questions_still_needed(f, asked)]
    assert "name" not in keys3, f"name must NOT be asked a 3rd time, got {keys3}"


async def case_style_splits_line_into_three():
    """Style mode breaks a single line into texting bubbles on a leading reaction +
    sentence boundaries + EVERY comma + the dash family (em/en/--/spaced hyphen) —
    the comma/dash is removed. Each clause STAYS its own bubble (the count is driven
    by the content, NOT a dice roll that re-merges); a reply carries >1 question
    bubble at most once; overflow past the cap merges into the last (never dropped)."""
    import random as _r
    from automations.welcome_chatter_for_info import (
        split_for_bubbles, _split_sentences, _cap_one_question,
    )
    # Seeds chosen so the per-reply strategy randomiser lands on a known strategy.
    LENGTH, CLAUSE = _r.Random(1), _r.Random(5)
    line = "oof, restaurant life is brutal. how old are ya, anyway"
    # _split_sentences exposes the RAW unit split: every comma + sentence boundary.
    assert _split_sentences(line, 6) == \
        ["oof", "restaurant life is brutal", "how old are ya", "anyway"]
    # the LENGTH strategy groups those units to a length-appropriate count — 10 words
    # → 3 bubbles (the short tail 'anyway' rejoins, never a lone fragment)…
    assert split_for_bubbles(line, 6, rng=_r.Random(1)) == \
        ["oof", "restaurant life is brutal", "how old are ya, anyway"]
    # …while the CLAUSE strategy keeps every comma/clause its own bubble.
    assert split_for_bubbles(line, 6, rng=_r.Random(5)) == \
        ["oof", "restaurant life is brutal", "how old are ya", "anyway"]
    # EVERY comma is a candidate break (raw units): no leading reaction here.
    assert _split_sentences("no, i dont think so", 6) == ["no", "i dont think so"]
    # 2 units → 2 bubbles regardless of strategy
    assert split_for_bubbles("no, i dont think so", 6, rng=_r.Random(1)) == ["no", "i dont think so"]
    # the dash family is a bubble break too, dash removed (em / -- / spaced hyphen).
    assert _split_sentences("got it jack — how old r u", 6) == ["got it jack", "how old r u"]
    assert _split_sentences("got it jack -- how old r u", 6) == ["got it jack", "how old r u"]
    assert _split_sentences("got it jack - how old r u", 6) == ["got it jack", "how old r u"]
    # overflow past the cap MERGES into the last bubble — content is never dropped
    over = _split_sentences("a, b, c, d, e, f, g, h", 3)
    assert len(over) == 3 and over[:2] == ["a", "b"] and "h" in over[2], over
    # a short single-clause reply stays ONE bubble (don't over-split)
    assert split_for_bubbles("what do u do for work", 6, rng=_r.Random(1)) == ["what do u do for work"]
    # newline lines DO get the comma split as raw units…
    assert _split_sentences("austin texas, nice", 6) == ["austin texas", "nice"]
    # …LENGTH groups a short (6-word) reply to 2 bubbles; CLAUSE keeps all 3
    assert split_for_bubbles("austin texas, nice\nwhat's your dish?", 6, rng=_r.Random(1)) == \
        ["austin texas", "nice, what's your dish?"]
    assert split_for_bubbles("austin texas, nice\nwhat's your dish?", 6, rng=_r.Random(5)) == \
        ["austin texas", "nice", "what's your dish?"]
    # a stranded emoji (peeled off after a '?') glues back onto the previous bubble —
    # never a lone '😏' bubble
    assert split_for_bubbles("oh, it's like that? 😏", 6) == ["oh", "it's like that? 😏"]
    # a LONG line breaks further at a mid emoji (kept) and at a WH word with lead-in
    assert split_for_bubbles("bet ur kitchen is as hot as you are 😏 where ya located", 6) == \
        ["bet ur kitchen is as hot as you are 😏", "where ya located"]
    assert split_for_bubbles("bold move for a guy who hasnt even told me his dish yet", 6) == \
        ["bold move for a guy", "who hasnt even told me his dish yet"]
    # …but a SHORT line with a WH word is NOT split (don't chop a tiny reply)
    assert split_for_bubbles("i know what u mean", 6) == ["i know what u mean"]
    # non-style mode (max 2) is unchanged — no comma/sentence splitting
    assert split_for_bubbles("oof, restaurant life is brutal. how old are ya", 2) == \
        ["oof, restaurant life is brutal. how old are ya"]


async def case_length_drives_bubble_count():
    """The bubble COUNT tracks reply LENGTH, not 'every comma' — short stays one line,
    longer earns a couple, but it never explodes into a 5-line burst. Balanced grouping
    sends the extra units to the END so a trailing fragment rejoins."""
    import random as _r
    from automations.welcome_chatter_for_info import (
        split_for_bubbles, _target_bubbles, _group_to_target,
    )
    assert _target_bubbles(3) == 1
    assert _target_bubbles(5) == 2
    assert _target_bubbles(13) == 3
    assert _target_bubbles(25) == 4
    # a 15-word comma-heavy reply on the LENGTH strategy → 3 bubbles (NOT 5)
    raw = "haha okay jack, i see how it is, where you from, what do you do"
    out = split_for_bubbles(raw, 6, rng=_r.Random(1))  # seed 1 → length strategy
    assert len(out) == 3, out
    joined = " ".join(out)
    for w in ("jack", "where", "from", "what"):
        assert w in joined, (w, out)
    # balanced grouping: extra units land in the LAST groups (trailing bit rejoins)
    assert _group_to_target(["a", "b", "c", "d"], 2) == ["a, b", "c, d"]
    assert _group_to_target(["a", "b", "c", "d"], 3) == ["a", "b", "c, d"]


async def case_split_strategy_randomiser_varies():
    """The per-reply split-strategy randomiser yields DIFFERENT bubble counts across
    seeds for a multi-clause reply (length / clause / terse), but ALWAYS preserves
    every word and stays within the cap — so replies don't all chop the same way."""
    import random as _r
    from automations.welcome_chatter_for_info import (
        split_for_bubbles, _strategy_target, _split_units,
    )
    raw = "haha okay jack, i see how it is, where you from, what do you do"
    units = _split_units(raw)                       # 4 candidate clauses
    counts = set()
    for seed in range(60):
        out = split_for_bubbles(raw, 6, rng=_r.Random(seed))
        counts.add(len(out))
        assert 1 <= len(out) <= len(units), (seed, out)
        joined = " ".join(out).replace(",", "")     # content preserved every time
        for w in raw.replace(",", "").split():
            assert w in joined, (seed, w, out)
    assert len(counts) >= 2, f"randomiser produced no variety: {counts}"
    # the three strategies resolve to the expected targets
    assert _strategy_target(units, 6, _r.Random(1)) == 3   # length (15 words → 3)
    assert _strategy_target(units, 6, _r.Random(5)) == 4   # clause (every clause)
    assert _strategy_target(units, 6, _r.Random(0)) == 2   # terse (one or two)


async def case_seeded_split_never_touches_the_global_rng():
    """`rng` governs EVERY draw, not just style mode. The senders pass
    Random(f"split:{fan_id}:{raw}") for a stable split, but the non-style (cap 2)
    path used to reach past it for the module-level `random` — so the same draft
    bubbled differently on a retry, and a suite run leaked its randomness into the
    next test. Swap the module global for a tripwire: nothing may call it."""
    import random as _r
    from automations import welcome_chatter_for_info as _oac

    class _Tripwire:
        def random(self):
            raise AssertionError("split_for_bubbles reached for the GLOBAL random")

    raw = "bet ur kitchen is as hot as you are 😏 where ya located"
    orig = _oac.random
    _oac.random = _Tripwire()
    try:
        for seed in range(12):
            _oac.split_for_bubbles(raw, 2, rng=_r.Random(seed))   # non-style
            _oac.split_for_bubbles(raw, 6, rng=_r.Random(seed))   # style
    finally:
        _oac.random = orig
    # …and the seed genuinely drives the non-style outcome (not a constant split)
    outs = {tuple(_oac.split_for_bubbles(raw, 2, rng=_r.Random(s))) for s in range(30)}
    assert len(outs) >= 2, f"the seed never changed the split: {outs}"


async def case_two_questions_never_drops_content():
    """REGRESSION — the 'one question' rule must NEVER drop a bubble (that silently
    loses the message). 'oh yeah? bet u could, but words are cheap jack 😏 how old
    are ya again?' used to collapse to just ['oh', 'yeah?']; now ALL content survives
    and only the LAST question keeps its '?'."""
    from automations.welcome_chatter_for_info import (
        split_for_bubbles, _split_sentences, _cap_one_question,
    )
    import random as _r
    raw = "oh yeah? bet u could, but words are cheap jack 😏 how old are ya again?"
    capped = _cap_one_question(_split_sentences(raw, 6))
    joined = " ".join(capped).lower()
    for w in ("yeah", "bet", "could", "words", "cheap", "jack", "old", "again"):
        assert w in joined, (w, capped)              # nothing dropped
    assert sum(b.rstrip().endswith("?") for b in capped) == 1, capped  # one '?'
    assert capped[-1].rstrip().endswith("?"), capped  # kept the LAST (real) question
    # the full randomized wrapper also never drops content and stays ≤ max bubbles
    for seed in range(40):
        _r.seed(seed)
        out = split_for_bubbles(raw, 6)
        j = " ".join(out).lower()
        for w in ("words", "cheap", "old", "again"):
            assert w in j, (seed, w, out)
        assert sum(b.rstrip().endswith("?") for b in out) <= 1, (seed, out)
        assert 1 <= len(out) <= 6, (seed, out)


async def case_lead_reaction_dedup_stops_repeated_oof():
    """The 'oof every message' tell: if the reply opens with the same reaction word
    the bot just used, drop that lead — the standalone bubble, or the fused opener —
    but never empty the reply, and leave a DIFFERENT reaction alone."""
    from automations.welcome_chatter_for_info import _dedupe_lead_reaction, _react_token
    # normalized token collapses stretched letters
    assert _react_token("oof") == _react_token("ooof") == "of"
    assert _react_token("lol") == _react_token("looool") == "lol"
    assert _react_token("lmao") == "lmao"
    assert _react_token("where u from") is None
    # repeat standalone 'oof' → dropped (recent out had an 'oof')
    assert _dedupe_lead_reaction(["oof", "where u from"], ["oof"]) == ["where u from"]
    # repeat fused into one line → just the opener is stripped
    assert _dedupe_lead_reaction(["oof babe that's wild"], ["oof"]) == ["babe that's wild"]
    # stretched repeat still caught
    assert _dedupe_lead_reaction(["ooof", "haha"], ["oof"]) == ["haha"]
    # a DIFFERENT reaction is left alone
    assert _dedupe_lead_reaction(["lol", "nice"], ["oof"]) == ["lol", "nice"]
    # no recent reaction → nothing dropped
    assert _dedupe_lead_reaction(["oof", "hi"], ["how was work"]) == ["oof", "hi"]
    # a lone repeated reaction with nothing after is NOT emptied
    assert _dedupe_lead_reaction(["oof"], ["oof"]) == ["oof"]


async def case_echo_guard_drops_parroted_bubbles():
    """A small model (esp. under the humanizer) sometimes parrots the fan's last
    message back. `_looks_like_echo` catches verbatim + near-verbatim echoes while
    leaving genuine short reactions and real replies alone."""
    from automations.welcome_chatter_for_info import _looks_like_echo
    last_in = "long shift too? at least the coffee here is solid"
    # verbatim echo (the guard runs BEFORE the typo pass, so it sees the clean echo)
    assert _looks_like_echo(last_in, last_in)
    # punctuation/case differences don't save it (normalized compare)
    assert _looks_like_echo("Long shift too at least the coffee here is solid!!", last_in)
    # echo + a couple extra words → last_in is a dominant substring → caught
    assert _looks_like_echo(last_in + " haha", last_in)
    # genuine reply + short reactions → kept
    assert not _looks_like_echo("a chef? thats hot ngl", last_in)
    assert not _looks_like_echo("lol", last_in)
    assert not _looks_like_echo("haha u up", "haha u up")  # too short to be an echo


async def case_core_facts_pursued_until_filled():
    """name/age/location are pursued until actually FILLED — even if a topic was
    already marked 'asked' (the marker desyncs from what the model really asked).
    So a fan at 75% 'info-complete' but with a BLANK location still lists
    'location' → can't graduate without it."""
    from automations.welcome_chatter_for_info import _questions_still_needed
    f = Fan(account_id="x", fan_id=1, real_name="Jack", his_age="27",
            hobbies="running", likes_boobs=True)  # location blank
    keys = [k for k, _ in _questions_still_needed(f, {"location", "name", "age"})]
    assert "location" in keys, f"blank location must stay on the list, got {keys}"


async def _seed_fan_source(aid: str, fan_id: int, source: str, *,
                           spend_cents: int = 0, is_muted: bool = False) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id, source=source,
                      lifetime_spend_cents=spend_cents, is_muted=is_muted))


# ── promo-spam guard: a peer creator (source=creator_we_follow, $0) is skipped
#    WITHOUT a reply AND without a persisted skip — reversible. ──────────────

async def case_peer_creator_skipped_as_spam():
    aid = "acc_spam1"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7001, "creator_we_follow")
    # fan spoke last (would otherwise be eligible), even has a prior reply. The
    # inbound carries real promo evidence — OF rich-text editor spans, the shape a
    # peer creator's mass blast actually arrives in. Without that the guard now
    # (correctly) lets him through; see case_labelled_fan_without_promo_replied.
    await _add_msgs(aid, 7001, [
        ("in", "<p><strong>FLASH SALE!!</strong> unlock my bundle</p>"),
        ("out", "lol"),
        ("in", '<p><span class="m-editor-fc__blue-1">check my page</span></p>'),
    ])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res
    assert res["skipped_spam"] == 1, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        # REVERSIBLE: no skip_list row, no gen_info enqueue.
        assert await s.get(SkipList, (aid, 7001)) is None, "spam skip must not persist"
        assert 7001 not in await _geninfo_targets(s, aid), "spam must not enqueue gen_info"


# ── REGRESSION (2026-07-24): OF's creator_we_follow flag alone must NOT silence
#    a fan. It only means we're subscribed to THEM, which is true of any fan a
#    free page followed back — and for five weeks it muted 71 real fans on one
#    live account, one of them mid-conversation asking "why you ignore me?".
#    A labelled fan who types plain text and never blasted promo gets answered. ──

async def case_labelled_fan_without_promo_replied():
    aid = "acc_spam5"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7005, "creator_we_follow")   # $0, OF-flagged
    await _add_msgs(aid, 7005, [
        ("out", "hey you"),
        ("in", "<p>Baby girl! 😍</p>"),
        ("in", "<p>Why you ignore me?</p>"),
    ])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["skipped_spam"] == 0, ("no promo evidence ⇒ not spam", res)
    assert res["replies_sent"] == 1, res
    assert fake.sent, "a real fan must get his reply"


# ── …and once we HAVE had a real exchange with him (turn_counter > 0), later
#    promo-looking formatting can't retroactively silence him either. ─────────

async def case_labelled_fan_with_history_replied():
    aid = "acc_spam6"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7006, "creator_we_follow")
    async with get_session() as s:
        (await s.get(Fan, (aid, 7006))).turn_counter = 3
    await _add_msgs(aid, 7006, [("out", "hi"), ("in", "<p><em>missed you</em></p>")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["skipped_spam"] == 0, ("prior real exchange ⇒ never spam", res)
    assert res["replies_sent"] == 1, res


# ── a PAYING peer creator is NOT silenced (spend umbrella protects collabs) ──

async def case_paying_peer_creator_still_replied():
    aid = "acc_spam2"
    await _seed_account(aid)
    # spend > $0 (clears the spam umbrella) but <= $1 (stays under the human
    # hand-off gate) so we isolate the spam guard, not the "spent" cutoff.
    await _seed_fan_source(aid, 7002, "creator_we_follow", spend_cents=50)
    await _add_msgs(aid, 7002, [("out", "hey"), ("in", "loved your last drop")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["skipped_spam"] == 0, res
    assert res["replies_sent"] == 1, res


# ── a real fan on a NON-"fan" source (onlyfans/ledger) is still answered:
#    only creator_we_follow is treated as spam, so non-paying real fans survive ──

async def case_real_fan_other_source_replied():
    aid = "acc_spam3"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7003, "onlyfans")  # $0 spend, real-fan-ish source
    await _add_msgs(aid, 7003, [("out", "hey babe"), ("in", "hi cutie")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["skipped_spam"] == 0, res
    assert res["replies_sent"] == 1, res


# ── force_ids overrides the spam guard (manual targeting) ─────────────────────

async def case_force_ids_overrides_spam_guard():
    aid = "acc_spam4"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7004, "creator_we_follow")
    await _add_msgs(aid, 7004, [("in", "yo")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={"force_ids": [7004]})
    assert res["skipped_spam"] == 0, res
    assert res["replies_sent"] == 1, res


# ── muted-creator guard: a creator we follow whose chat we MUTED is a HARD skip,
#    even when PAYING (so it's the mute, not the $0 spam umbrella, that catches). ─

async def case_muted_creator_not_replied():
    aid = "acc_muted1"
    await _seed_account(aid)
    # spend>0 clears the $0 promo-spam umbrella; is_muted=True → the muted-creator
    # guard is what silences this fan (NOT skipped_spam).
    await _seed_fan_source(aid, 7101, "creator_we_follow", spend_cents=50, is_muted=True)
    await _add_msgs(aid, 7101, [("in", "promo!"), ("out", "hi"), ("in", "check my page")])
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res
    assert res["skipped_muted_creator"] == 1, res
    assert res["skipped_spam"] == 0, res
    assert fake.sent == [], fake.sent


# ── durable skip persists + is honored on re-run ───────────────────────────────

async def case_muted_creator_skip_persisted_and_honored():
    from automations._common import mark_muted_creator_skip, MUTED_CREATOR_REASON
    aid = "acc_muted2"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7102, "creator_we_follow", spend_cents=50, is_muted=True)
    await _add_msgs(aid, 7102, [("in", "yo"), ("out", "hi"), ("in", "buy my stuff")])

    # The scrape would write this when the chat is muted — assert it persists.
    await mark_muted_creator_skip(aid, 7102)
    async with get_session() as s:
        row = await s.get(SkipList, (aid, 7102))
        assert row is not None and row.reason == MUTED_CREATOR_REASON, row

    fake = _use_fake()
    _patch_llm()
    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    # Honored: skip_list membership skips it (skipped_listed), zero sends.
    assert res["replies_sent"] == 0, res
    assert res["skipped_listed"] == 1, res
    assert fake.sent == [], fake.sent


# ── executor reconciliation: scrape sets is_muted + writes/clears the skip ────

async def case_scrape_mute_flip_reconciles_skip():
    from automation_executor import _upsert_fan_identity
    from automations._common import MUTED_CREATOR_REASON
    aid = "acc_muted3"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7103, "creator_we_follow")

    # Muted on OF → persist is_muted + durable skip.
    async with get_session() as s:
        await _upsert_fan_identity(s, aid, 7103, "999", {"id": 7103}, [],
                                   last_in_at=None, last_out_at=None, is_muted=True)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 7103))
        assert f.is_muted is True, f
        row = await s.get(SkipList, (aid, 7103))
        assert row is not None and row.reason == MUTED_CREATOR_REASON, row

    # Un-muted on OF → flag flips + auto skip removed.
    async with get_session() as s:
        await _upsert_fan_identity(s, aid, 7103, "999", {"id": 7103}, [],
                                   last_in_at=None, last_out_at=None, is_muted=False)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 7103))
        assert f.is_muted is False, f
        assert await s.get(SkipList, (aid, 7103)) is None


# ── a muted NON-creator (a regular fan we muted) is NOT auto-skip-listed ──────
#    Only muted CREATORS we follow are spam; a muted real fan keeps automations.

async def case_muted_non_creator_not_skiplisted():
    from automation_executor import _upsert_fan_identity
    aid = "acc_muted4"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7104, "onlyfans")  # a real-fan-ish source

    async with get_session() as s:
        await _upsert_fan_identity(s, aid, 7104, "999", {"id": 7104}, [],
                                   last_in_at=None, last_out_at=None, is_muted=True)
    async with get_session() as s:
        f = await s.get(Fan, (aid, 7104))
        assert f.is_muted is True, f            # flag still persisted
        assert await s.get(SkipList, (aid, 7104)) is None, "non-creator must not auto-skip"


# ── manual "restrict from automations" toggle: durable skip + honored + lift ──

async def case_manual_restrict_blocks_and_lifts():
    from automations._common import automation_restrict_status, MANUAL_RESTRICT_REASON
    aid = "acc_restrict1"
    await _seed_account(aid)
    await _seed_fan_source(aid, 7105, "onlyfans")  # an ordinary fan
    await _add_msgs(aid, 7105, [("out", "hey"), ("in", "hi cutie")])

    async with get_session() as s:
        s.add(SkipList(account_id=aid, fan_id=7105, reason=MANUAL_RESTRICT_REASON,
                       added_at=datetime.utcnow()))
    assert (await automation_restrict_status(aid, 7105))["restricted"] is True

    fake = _use_fake()
    _patch_llm()
    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0, res        # honored everywhere via skip_list
    assert fake.sent == [], fake.sent

    async with get_session() as s:
        await s.delete(await s.get(SkipList, (aid, 7105)))
    assert (await automation_restrict_status(aid, 7105))["restricted"] is False


# ── content-ask: no tip-ask any more ──────────────────────────────────────────
#    The tip-ask was removed (its `tip_reward_config_json` blob is unmapped): a fan
#    who asks to SEE content gets the normal reply prompt, with its "don't offer"
#    rule.

async def case_content_ask_never_builds_a_tip_ask():
    aid = "acc_ca1"
    await _seed_account(aid)
    async with get_session() as s:
        if await s.get(AccountAiConfig, aid) is None:
            s.add(AccountAiConfig(account_id=aid))
    await _seed_fan(aid, 9101, name="Bob")
    await _add_msgs(aid, 9101, [("out", "hey babe 💕"), ("in", "can i see some content??")])
    _use_fake()
    sink: list[dict] = []

    async def _fake_chat(**kw):
        sink.append(kw)
        return SimpleNamespace(content="haha slow down cutie, tell me about u", call_id=1)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok" and res["replies_sent"] == 1, res
    reply_calls = [kw for kw in sink if kw.get("purpose") == "welcome_chatter_for_info"
                   and "Reply to his last message" in kw["messages"][-1]["content"]]
    assert len(reply_calls) == 1, sink
    sysmsg = reply_calls[0]["messages"][0]["content"]
    assert "HE JUST ASKED TO SEE CONTENT" not in sysmsg, sysmsg
    assert "don't offer pics or videos yet" in sysmsg, sysmsg


async def case_extract_skips_saturated_profile():
    """COST — the fact-extract is FILL-EMPTY-ONLY, so once every field it can
    write is populated a re-extract is a guaranteed no-op. It must be skipped (no
    LLM call), turning a complete-profile fan into ONE call per reply; a fan with
    any empty field is still extracted."""
    full = Fan(account_id="acc_x", fan_id=1, real_name="Tom", his_age="30",
               home_country="US", home_city="NYC", hobbies="golf",
               occupation="eng", fetishes="feet", recent_events='["a trip"]')
    empty = Fan(account_id="acc_x", fan_id=2)
    partial = Fan(account_id="acc_x", fan_id=3, real_name="Tom", his_age="30",
                  home_country="US", home_city="NYC", hobbies="golf",
                  occupation="eng", fetishes="feet")  # recent_events still empty
    # The candidate carries HER side of the chat: a saturated profile is skipped
    # UNLESS she made a claim about herself this turn (see _persona.
    # mentions_self_claim). Plain banter here, so saturated still skips.
    quiet = _Candidate(1)
    quiet.messages = [("in", "hey"), ("out", "hey you 😏")]
    assert _extract_worthwhile(full, quiet) is False, "saturated profile should skip extract"
    assert _extract_worthwhile(empty, quiet) is True, "empty profile must extract"
    assert _extract_worthwhile(partial, quiet) is True, "empty recent_events must extract"

    # and _extract_and_fill must NOT reach the LLM for a saturated profile
    called = {"n": 0}

    async def _boom(**kw):
        called["n"] += 1
        raise AssertionError("extract fired on a saturated profile")

    orig = llm_client.chat
    llm_client.chat = _boom  # type: ignore[attr-defined]
    try:
        out = await _extract_and_fill("acc_x", 1, full, _Candidate(1),
                                      "deepseek-v4-flash")
        assert out is full and called["n"] == 0, "saturated extract still called the LLM"
    finally:
        llm_client.chat = orig


# ── Cat stickers (this is Auto Convo's wiring) ──

class _FakeOFKw(FakeOF):
    """FakeOF that also records send kwargs — the sticker send's giphy_id."""

    def __init__(self):
        super().__init__()
        self.sent_kw: list[tuple[int, str, dict]] = []

    def send_message(self, chat_id, text, **kw) -> dict:
        self.sent_kw.append((int(chat_id), text, dict(kw)))
        return super().send_message(chat_id, text, **kw)


def _use_fake_kw() -> _FakeOFKw:
    fake = _FakeOFKw()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def case_sticker_rides_after_reply():
    from automations import cat_stickers as cs
    cs._last_sent.clear()
    real_roll = cs.roll_mode
    cs.roll_mode = lambda *a, **k: "allow"
    try:
        aid = "acc_st1"
        await _seed_account(aid)
        await _seed_fan(aid, 7001, name="Sam")
        await _add_msgs(aid, 7001, [("in", "lol that was so funny")])
        fake = _use_fake_kw()
        _patch_llm("omg ur funny\nSTICKER: laugh")
        res = await run_once(aid, "welcome_chatter_for_info", payload={})
        assert res["status"] == "ok" and res["replies_sent"] == 1, res
        assert res["stickers_sent"] == 1 and res["errors"] == 0, res
        giphy = [s for s in fake.sent_kw if s[2].get("giphy_id")]
        assert len(giphy) == 1 and giphy[0][1] == "", ("gif is its own empty-text bubble", giphy)
        assert giphy[0][2]["giphy_id"] in cs._CATALOG["laugh"][1], giphy
        texts = [t for _c, t, k in fake.sent_kw if not k.get("giphy_id")]
        assert texts and all("STICKER" not in t for t in texts), ("marker never reaches the fan", texts)
        assert cs.cooldown_active(aid, 7001, gap_min=30), "delivery must record the send"
    finally:
        cs.roll_mode = real_roll
        cs._last_sent.clear()


async def case_sticker_only_reply_welcome_chatter_for_info():
    from automations import cat_stickers as cs
    cs._last_sent.clear()
    real_roll = cs.roll_mode
    cs.roll_mode = lambda *a, **k: "solo"
    try:
        aid = "acc_st2"
        await _seed_account(aid)
        await _seed_fan(aid, 7002)
        await _add_msgs(aid, 7002, [("in", "good night babe")])
        fake = _use_fake_kw()
        _patch_llm("STICKER: sleepy")
        res = await run_once(aid, "welcome_chatter_for_info", payload={})
        assert res["status"] == "ok" and res["replies_sent"] == 1, res
        assert res["stickers_sent"] == 1 and res["errors"] == 0, res
        assert len(fake.sent_kw) == 1, ("the gif IS the whole reply", fake.sent_kw)
        _cid, text, kw = fake.sent_kw[0]
        assert text == "" and kw.get("giphy_id") in cs._CATALOG["sleepy"][1], fake.sent_kw
        # a gif-only reply asked nothing — the ask ledger must stay untouched
        async with get_session() as s:
            fan = await s.get(Fan, (aid, 7002))
            assert not json.loads(fan.questions_asked or "[]"), fan.questions_asked
    finally:
        cs.roll_mode = real_roll
        cs._last_sent.clear()


async def case_skip_roll_strips_stray_marker_welcome_chatter_for_info():
    from automations import cat_stickers as cs
    cs._last_sent.clear()
    real_roll = cs.roll_mode
    cs.roll_mode = lambda *a, **k: "skip"
    try:
        aid = "acc_st3"
        await _seed_account(aid)
        await _seed_fan(aid, 7003)
        await _add_msgs(aid, 7003, [("in", "heyy")])
        fake = _use_fake_kw()
        _patch_llm("heyy u 😏\nSTICKER: wave_hi")
        res = await run_once(aid, "welcome_chatter_for_info", payload={})
        assert res["status"] == "ok" and res["replies_sent"] == 1, res
        assert res["stickers_sent"] == 0, res
        assert fake.sent_kw and all(not k.get("giphy_id") and "STICKER" not in t
                                    for _c, t, k in fake.sent_kw), fake.sent_kw
    finally:
        cs.roll_mode = real_roll
        cs._last_sent.clear()


# ── The turn handoff: answering a fan a welcome bubble talked over ───────
#
# plans/welcome-pacing §C3. `send_welcome`'s `stop_on_reply` lets her FINISH the
# bubble she was already typing, so that bubble can land on top of the fan's
# reply — and every gate in this lane then reads "we spoke last" and skips him.
# `turn_handoff_ids` is the one key that reopens that gate, and these cases are
# the proof that it does something and that it does not do anything else.
#
# ⚠️ The scenario is seeded as ROWS and answered by the REAL `run()`. Asserting
# that send_welcome dropped a GIF proves nothing about whether the fan was ever
# answered; only an outbound reply row does.

async def _seed_eaten_reply(aid: str, fan_id: int, *,
                            welcome_kind: str | None = "welcome",
                            reply_body: str = "hey! im good, u?",
                            then_photo: str | None = None,
                            then_photo_described: bool = True,
                            then_tip_cents: int | None = None,
                            photo_after_the_bubble: bool = False) -> None:
    """The exact shape a `stop_on_reply` abort leaves behind: our welcome
    greeting, HIS reply 40s later, and then the bubble she was already typing
    landing 40s after THAT — tagged `welcome`, which is what moved the turn.

    `welcome_kind=None` writes that last bubble as a HUMAN send instead (no
    automation_kind), which is the "somebody already answered him" case the
    handoff must stand down for.

    `then_photo` inserts a CAPTION-LESS photo of his between the reply and that
    bubble — the wordless row `stop_on_reply` deliberately does NOT abort on, so
    it can be, and routinely is, NEWER than the words the handoff owes an answer
    to. `then_photo_described=False` leaves `image_desc` NULL (the describe has
    not landed, or `_should_describe` refused it for a $0 fan over the free-fan
    daily budget — the welcome-burst population exactly).

    `then_tip_cents` inserts `transaction_ingest`'s BARE-TIP LEDGER ROW instead:
    an inbound row whose body is our own bookkeeping string, written by the
    5-minute poll, which `newest_worded_inbound` excludes by its SECOND clause.

    `photo_after_the_bubble` lands that photo AFTER the finishing bubble, so the
    thread ENDS with his wordless row and it is already his turn."""
    base = _T0
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 10 + 1,
                      direction="out", body="Hey S-S-S-Sexy Sam ! !!",
                      automation_kind="welcome", created_at=base))
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 10 + 2,
                      direction="in", body=reply_body,
                      created_at=base + timedelta(seconds=40)))
        if then_photo is not None:
            s.add(Message(account_id=aid, fan_id=fan_id,
                          message_id=fan_id * 10 + 4, direction="in", body="",
                          media_count=1,
                          image_desc=(then_photo if then_photo_described
                                      else None),
                          created_at=base + timedelta(
                              seconds=100 if photo_after_the_bubble else 55)))
        if then_tip_cents is not None:
            from transaction_ingest import tip_ledger_body  # noqa: E402
            s.add(Message(account_id=aid, fan_id=fan_id,
                          message_id=fan_id * 10 + 5, direction="in",
                          body=tip_ledger_body(then_tip_cents), is_tip=True,
                          created_at=base + timedelta(seconds=60)))
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 10 + 3,
                      direction="out", body="it's Thursday afternoon in Canada",
                      automation_kind=welcome_kind,
                      created_at=base + timedelta(seconds=80)))


def _handoff_payload(fan_id: int, *, with_key: bool = True) -> dict:
    """Byte-for-byte the payload `welcome_turn.enqueue_turn_handoff` writes."""
    body = {"only_fan_ids": [fan_id], "force_ids": [fan_id]}
    if with_key:
        body["turn_handoff_ids"] = [fan_id]
    return body


async def case_turn_handoff_answers_the_fan_our_welcome_talked_over():
    """🔴 THE PROOF (§H5 / R1-a). Inbound at T, a welcome bubble at T+40s, then
    the real engine run — and an outbound reply row lands for that fan.

    Without the seam this run reports `skipped_not_turn`, which is the whole
    reason `stop_on_reply` could not ship on its own: a girl who stops spamming
    and starts ignoring people is a worse product than the burst it fixed."""
    aid = "acc_c_handoff"
    fid = 61001
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    await _seed_eaten_reply(aid, fid)
    fake = _use_fake()
    _patch_llm("aww hey you 😊 what are you up to today?")

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    assert res["status"] == "ok", res
    assert res["turn_handoffs"] == 1 and res["skipped_not_turn"] == 0, res
    assert res["replies_sent"] == 1, res
    # ONE reply, however many bubbles the humanizer split it into.
    assert fake.sent and {c for c, _ in fake.sent} == {fid}, fake.sent

    async with get_session() as s:
        out = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.fan_id == fid,
                                  Message.direction == "out",
                                  Message.message_id >= 9_000_000_000_000)
        )).scalars().all()
        assert out and all(m.body for m in out), ("he was actually answered", out)
        assert all(m.automation_kind == "welcome_chatter_for_info" for m in out), \
            [m.automation_kind for m in out]


async def case_turn_handoff_reads_HIS_line_not_our_welcome_bubble():
    """The admission rewrites the candidate, and the rewrite is load-bearing.

    This lane feeds the model `last_body` gated on `last_dir` — and on a handoff
    the last message on the thread is OUR welcome bubble. Without the rewrite the
    prompt would be handed "it's Thursday afternoon in Canada" as the thing he
    just said, and she would answer herself."""
    aid = "acc_c_handoff_body"
    fid = 61002
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    await _seed_eaten_reply(aid, fid, reply_body="im from portugal actually")
    _use_fake()
    seen: list[dict] = []
    async def _capture(**kw):
        seen.append(kw)
        return SimpleNamespace(content="portugal!! ive always wanted to go 😍",
                               call_id=1)
    llm_client.chat = _capture  # type: ignore[attr-defined]

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    assert res["replies_sent"] == 1, res
    prompt = json.dumps(seen[0]["messages"])
    assert "im from portugal actually" in prompt, prompt[:600]


async def case_turn_handoff_answers_an_EMOJI_ONLY_reply_too():
    """The two halves of `stop_on_reply` have to agree about what a reply IS.

    send_welcome stops the burst on WORDS — `body != ''`, the operator's own rule
    (§C4) — so "😍", the single most likely thing a brand-new subscriber types,
    truncates his welcome. This lane's `fan_msg_n` counts only
    `is_substantive_msg` text and never moves for one, so the admission used to
    refuse the very rescue that abort created: his burst cut short AND nobody
    answering him. The worst of both, and invisible — the run reports
    `skipped_not_turn`, which is what a healthy no-op looks like.

    Same rows as the proof case above, one emoji instead of a sentence."""
    aid = "acc_c_handoff_emoji"
    fid = 61006
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    await _seed_eaten_reply(aid, fid, reply_body="😍")
    fake = _use_fake()
    _patch_llm("aww 🥰 tell me about your day")

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    assert res["turn_handoffs"] == 1 and res["skipped_not_turn"] == 0, res
    assert res["replies_sent"] == 1, res
    assert fake.sent and {c for c, _ in fake.sent} == {fid}, fake.sent


async def case_turn_handoff_without_the_key_answers_nobody():
    """THE ADD-ON GATE. The same rows and the same force, minus the one key: the
    fan is skipped as `not_turn`, exactly as he is today.

    This is what makes the two engine edits dead code on every run that is not a
    handoff job — the guarantee the plan's fence rests on, and the reason the two
    most dangerous files in the tree could be touched at all."""
    aid = "acc_c_handoff_off"
    fid = 61003
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    await _seed_eaten_reply(aid, fid)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid, with_key=False))
    assert res["replies_sent"] == 0, res
    assert res["skipped_not_turn"] == 1 and res["turn_handoffs"] == 0, res
    assert fake.sent == [], fake.sent


async def case_turn_handoff_stands_down_when_somebody_already_answered():
    """The job is SELF-VERIFYING. It is due ~3 minutes after the abort, and in
    that window a human chatter (or any other automation) may have answered him.
    Then not every outbound since his message is a welcome bubble, the admission
    refuses, and the job is a no-op instead of a second voice on the same turn."""
    aid = "acc_c_handoff_answered"
    fid = 61004
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    # The last outbound is a HUMAN send (automation_kind NULL), not a welcome.
    await _seed_eaten_reply(aid, fid, welcome_kind=None)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    assert res["replies_sent"] == 0, res
    assert res["skipped_not_turn"] == 1 and res["turn_handoffs"] == 0, res
    assert fake.sent == [], fake.sent


async def _handoff_over_a_newer_wordless_row(aid: str, fid: int, **seed_kw):
    """Seed the eaten reply plus one WORDLESS row NEWER than his words and run the
    real engine on the handoff payload. Returns `(res, fake)`."""
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    await _seed_eaten_reply(aid, fid, **seed_kw)
    fake = _use_fake()
    _patch_llm("aww hey you 😊 what are you up to today?")
    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    return res, fake


async def case_turn_handoff_survives_an_UNDESCRIBED_wordless_photo():
    """🔴 He answers in WORDS, then sends a caption-less selfie the vision call
    never described — and NOBODY used to answer him, on either lane.

    Both engines re-derived "did he say something" from his newest inbound of ANY
    kind, latest-wins. `_history_text` synthesises nothing without an
    `image_desc`, so this lane's rendering of that selfie was `''` too and the
    rescue refused — while the run reported `skipped_not_turn`, which is what a
    healthy no-op looks like. On prod this is the ordinary case, not the exotic
    one: `_should_describe` returns False for a $0 fan over the free-fan daily
    budget, which is precisely a brand-new subscriber inside his welcome burst.

    The question the job was enqueued on is `_newest_worded_inbound`'s, and a
    wordless row is not an answer to it."""
    aid, fid = "acc_c_handoff_nodesc", 61011
    res, fake = await _handoff_over_a_newer_wordless_row(
        aid, fid, then_photo="unused", then_photo_described=False)
    assert res["turn_handoffs"] == 1 and res["skipped_not_turn"] == 0, res
    assert res["replies_sent"] == 1, res
    assert fake.sent and {c for c, _ in fake.sent} == {fid}, fake.sent


async def case_turn_handoff_line_is_his_words_not_the_newer_wordless_row():
    """🔴 THE REWRITE, driven off the REAL `_gather` — the half an end-to-end run
    cannot see on this lane, because this lane already ADMITTED him.

    `TurnHandoff.admit` hands back the words the lane installs as "he spoke
    last, and this is what he said"; downstream reads `last_body` gated on `last_dir`: the
    content-ask detector, the sticker seed, the echo filter, the consistency
    guard and the prompt's own "reply to his last message". Three wordless rows,
    all of them things `_newest_worded_inbound` skips, all of them latest-wins on
    this lane — and each one used to become his line:

      • a DESCRIBED selfie → "[he sent: a selfie of a man in a car]", which is
        this lane's own synthesis and not a word he typed;
      • an UNDESCRIBED selfie → "", which refused the rescue outright;
      • the ledger's bare-tip row → "💸 Sent a $5.00 tip", a string WE wrote.

    Hand-building a `_Candidate` cannot see any of this: the defect was entirely
    in what the lane computed BEFORE the call, so the gather has to run."""
    from automations import welcome_chatter_for_info as wc

    shapes = (
        ("desc", {"then_photo": "a selfie of a man in a car"}),
        ("nodesc", {"then_photo": "unused", "then_photo_described": False}),
        ("ledger", {"then_tip_cents": 500}),
    )
    for tag, kw in shapes:
        aid, fid = f"acc_c_handoff_line_{tag}", 61020 + len(tag)
        await _seed_account(aid)
        await _seed_fan(aid, fid, name="Sam")
        await _seed_eaten_reply(aid, fid, reply_body="hey are you real",
                                **kw)
        c = (await wc._gather(aid, {fid}))[fid]
        # The thread ends with OUR welcome bubble — that is the whole premise.
        assert c.last_dir == "out", (tag, c.last_dir, c.last_body)
        assert c.turn.admit(fid, {fid}) == "hey are you real", (tag, c.turn)


async def case_turn_handoff_rewrites_his_line_even_when_a_photo_made_it_his_turn():
    """🔴 The photo lands AFTER the bubble that ate his reply, so the thread ENDS
    with his wordless row and `last_dir` is already "in" when the job runs.

    The admission used to be asked only under `last_dir != "in"`, so on this
    shape it never ran: `turn_handoffs` stayed 0 and the prompt's "his line" was
    the photo — `''` undescribed, `[he sent: …]` described — not the words the
    job exists to answer. The oracle is the echo filter, which reads
    `c.last_body`: an LLM reply that parrots HIS WORDS is dropped as an echo
    only if his words are the line the lane holds. Without the rewrite the same
    reply ships, because `''` echoes nothing."""
    words = "hey are you real or what"
    for tag, described in (("desc", True), ("nodesc", False)):
        aid, fid = f"acc_c_handoff_after_{tag}", 61030 + len(tag)
        await _seed_account(aid)
        await _seed_fan(aid, fid, name="Sam")
        await _seed_eaten_reply(aid, fid, reply_body=words,
                                then_photo="a selfie of a man in a car",
                                then_photo_described=described,
                                photo_after_the_bubble=True)
        c = (await a05._gather(aid, {fid}))[fid]
        assert c.last_dir == "in", (tag, c.last_dir)     # the photo made it his turn
        fake = _use_fake()
        _patch_llm(words)                                  # an echo of HIS words
        res = await run_once(aid, "welcome_chatter_for_info",
                             payload=_handoff_payload(fid))
        assert res["turn_handoffs"] == 1 and res["skipped_not_turn"] == 0, (tag, res)
        assert res["replies_sent"] == 0 and fake.sent == [], (
            tag, "the echo of his words shipped — his line was not his words", res)
        assert res["errors"] == 1, (tag, res)             # dropped as echo-only


async def case_turn_handoff_still_refuses_a_fan_who_only_ever_tipped():
    """THE CONTROL. Widening "his newest inbound" to "his newest WORDED inbound"
    must not widen the GATE: a fan whose only inbound rows are a bare tip and a
    caption-less photo has said NOTHING, and the admission still refuses him.

    Without this, the cases above pass just as well on an admission that stopped
    asking the question at all."""
    from transaction_ingest import tip_ledger_body  # noqa: E402
    aid, fid = "acc_c_handoff_wordless_only", 61013
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fid, message_id=610131,
                      direction="out", body="Hey S-S-S-Sexy Sam ! !!",
                      automation_kind="welcome", created_at=_T0))
        s.add(Message(account_id=aid, fan_id=fid, message_id=610132,
                      direction="in", body=tip_ledger_body(500), is_tip=True,
                      created_at=_T0 + timedelta(seconds=40)))
        s.add(Message(account_id=aid, fan_id=fid, message_id=610133,
                      direction="in", body="", media_count=1,
                      image_desc="a selfie of a man in a car",
                      created_at=_T0 + timedelta(seconds=55)))
        s.add(Message(account_id=aid, fan_id=fid, message_id=610134,
                      direction="out", body="it's Thursday afternoon in Canada",
                      automation_kind="welcome",
                      created_at=_T0 + timedelta(seconds=80)))
    fake = _use_fake()
    _patch_llm()
    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    assert res["turn_handoffs"] == 0 and res["skipped_not_turn"] == 1, res
    assert res["replies_sent"] == 0 and fake.sent == [], (res, fake.sent)


async def case_words_predicate_matches_the_sql():
    """`_common.inbound_is_words` is `welcome_turn.newest_worded_inbound`'s
    predicate in Python — one rule that has to be written twice, in two languages,
    which is exactly how the second clause went missing from the Python copy. So
    drive BOTH over one body matrix and pin the relationship between them.

    Three properties. The first two are about the PREDICATE:

    1. **The Python is never WIDER than the SQL.** Admitting a fan on a row the
       burst never aborted for is the whole defect — the ledger row is non-empty,
       so it passed the old check and became his line. If the SQL grows a third
       clause and the Python does not learn it, this is what goes red. The matrix
       carries a lower- and an UPPER-case ledger prefix for this: SQLite's `LIKE`
       is ASCII-case-insensitive and `str.startswith` is not, so a case-varied
       prefix was the one input on which the copy really was wider — the property
       was asserted and false at the same time, because no body in the matrix
       could see it.
    2. **They AGREE on every body that renders as text.**

    The third is about the SEAM, and it is the half a predicate matrix cannot
    reach:

    3. **His words are never lost.** For a TAGS-ONLY body the two sides agree —
       the SQL counts `"<br>"` as words and so does the predicate, so property 1
       is satisfied — and the fan is still dropped, because the value each lane
       STORES is the body RENDERED, and that is `""`. His real earlier words got
       overwritten with nothing and the engine then refused the rescue. So the
       matrix is driven through the real `_gather` as well, with his words
       already on the thread, and what it stored is compared to the one string
       that is right.

    The whitespace residual is deliberate and documented on `inbound_is_words`: a
    body that is only whitespace satisfies the SQL's `body != ''` and not the
    Python's strip. The seam is allowed to be narrower there and must be — it hands
    `last_body` to the model, and a blank fan line is the failure its own docstring
    names. The cost is a fan whose burst aborted on whitespace getting no rescue,
    which is silence in answer to nothing."""
    from automations._common import inbound_is_words
    from automations import welcome_turn as wt
    from automations import welcome_chatter_for_info as wc
    from transaction_ingest import tip_ledger_body  # noqa: E402

    ledger = tip_ledger_body(500)
    bodies = ["hey are you real", "😍", "", "   ", "\n",
              ledger, tip_ledger_body(0),
              "💸 Sent a $5.00 tip and here is a note",
              "thanks for the $5 babe", "0", "?",
              # TAGS ONLY — non-empty to the SQL, empty once rendered. OF wraps
              # every body in <p>…</p>, so this is the shape of the whole corpus
              # with the words taken out.
              "<br>", "<p></p>", "<p><br/></p>",
              # …and one that really is words wearing tags, so the guard cannot
              # be "reject anything with a tag in it".
              "<p>hey are you real</p>",
              # CASE-VARIED ledger prefix: the SQL's LIKE excludes both.
              ledger.lower(), ledger.upper()]
    aid = "acc_c_words_predicate"
    await _seed_account(aid)
    for i, body in enumerate(bodies):
        fid = 61300 + i
        await _seed_fan(aid, fid)
        async with get_session() as s:
            s.add(Message(account_id=aid, fan_id=fid, message_id=613000 + i,
                          direction="in", body=body,
                          created_at=_T0 + timedelta(seconds=10)))
        sql_says = await wt.newest_worded_inbound(aid, fid) is not None
        py_says = inbound_is_words(body)
        # 1. never wider.
        assert not (py_says and not sql_says), (repr(body), py_says, sql_says)
        # 2. and identical wherever there is text at all.
        if body.strip():
            assert py_says is sql_says, (repr(body), py_says, sql_says)
    # …and the None/absent case both sides agree is "no words".
    assert inbound_is_words(None) is False

    # ── 3. what the LANES store, over the same matrix ────────────────────
    # His words land first; the matrix body lands on top of them. That is the
    # live shape: `stop_on_reply` aborts the burst on the WORDED row and the
    # handoff job then has to find it again, however many wordless rows arrived
    # in the meantime.
    words = "hey are you real"
    for i, body in enumerate(bodies):
        aid2, fid = "acc_c_words_stored", 61400 + i
        if i == 0:
            await _seed_account(aid2)
        await _seed_fan(aid2, fid, name="Sam")
        async with get_session() as s:
            s.add(Message(account_id=aid2, fan_id=fid, message_id=614000 + i * 3,
                          direction="in", body=words, created_at=_T0))
            s.add(Message(account_id=aid2, fan_id=fid, message_id=614001 + i * 3,
                          direction="out", body="Hey S-S-S-Sexy Sam ! !!",
                          automation_kind="welcome",
                          created_at=_T0 + timedelta(seconds=20)))
            s.add(Message(account_id=aid2, fan_id=fid, message_id=614002 + i * 3,
                          direction="in", body=body,
                          created_at=_T0 + timedelta(seconds=40)))
        rendered = wc._strip_html(body)
        # The composite `_gather` actually applies: the shared predicate,
        # AND the lane's own rendering of the body being non-empty.
        overwrites = inbound_is_words(body) and bool(rendered)
        want = rendered if overwrites else words

        wc_c = (await wc._gather(aid2, {fid}))[fid]
        assert wc_c.turn.last_worded_in == want, (repr(body), wc_c.turn.last_worded_in, want)
        # 🔴 The one that matters: whatever landed on top, he is still admitted
        # with something he actually said. An empty `last_worded_in` is a fan the
        # SQL aborted a burst for and the engine will not answer.
        assert (wc_c.turn.last_worded_in or "").strip(), (repr(body), "wcfi DROPS him")

    # …and the DIVERGENCE the tags-only row opened, which needs a describe to see:
    # `text` on this lane is "[he sent: …]" for a body that renders empty, so a
    # guard written against `text` instead of the rendered BODY would store our
    # own synthesis here instead of his real words.
    aid3, fid = "acc_c_words_stored_desc", 61499
    await _seed_account(aid3)
    await _seed_fan(aid3, fid, name="Sam")
    async with get_session() as s:
        s.add(Message(account_id=aid3, fan_id=fid, message_id=614900,
                      direction="in", body=words, created_at=_T0))
        s.add(Message(account_id=aid3, fan_id=fid, message_id=614901,
                      direction="out", body="Hey S-S-S-Sexy Sam ! !!",
                      automation_kind="welcome",
                      created_at=_T0 + timedelta(seconds=20)))
        s.add(Message(account_id=aid3, fan_id=fid, message_id=614902,
                      direction="in", body="<br>", media_count=1,
                      image_desc="a selfie of a man in a car",
                      created_at=_T0 + timedelta(seconds=40)))
    wc_c = (await wc._gather(aid3, {fid}))[fid]
    assert wc_c.turn.last_worded_in == words, wc_c.turn.last_worded_in

    # 🔴 THE ROW THE MATRIX ABOVE CANNOT HOLD: WORDS **and** a describe.
    #
    # Every body in the matrix is words-or-nothing, and the described case above
    # renders EMPTY — so on both, the stored line was right by construction and
    # this case certified a seam that was still open. Give the same row real words
    # and a describe and the old wcfi guard (`c.last_worded_in = text`) stored our
    # own synthesis instead of his line:
    #
    #     wcfi : 'is that you babe [he sent: a selfie of a man in a car]'
    #
    # `TurnHandoff.admit` hands this back as `c.last_body` — the model's "his
    # line" and what every intent detector parses. The lane now feeds
    # `TurnHandoff.on_inbound` the rendering of the BODY and never its history line.
    aid4, fid = "acc_c_words_stored_both", 61498
    await _seed_account(aid4)
    await _seed_fan(aid4, fid, name="Sam")
    spoke = "is that you babe"
    async with get_session() as s:
        s.add(Message(account_id=aid4, fan_id=fid, message_id=614800,
                      direction="in", body=words, created_at=_T0))
        s.add(Message(account_id=aid4, fan_id=fid, message_id=614801,
                      direction="out", body="Hey S-S-S-Sexy Sam ! !!",
                      automation_kind="welcome",
                      created_at=_T0 + timedelta(seconds=20)))
        s.add(Message(account_id=aid4, fan_id=fid, message_id=614802,
                      direction="in", body=f"<p>{spoke}</p>", media_count=1,
                      image_desc="a selfie of a man in a car",
                      created_at=_T0 + timedelta(seconds=40)))
    wc_c = (await wc._gather(aid4, {fid}))[fid]
    assert wc_c.turn.last_worded_in == spoke, wc_c.turn.last_worded_in
    # …and the describe is not LOST — it is in the history line, where it belongs.
    assert any("a selfie of a man in a car" in t for _, t in wc_c.messages), wc_c.messages


def case_turn_handoff_seam_is_one_object():
    """The whole engine side of the handoff is ONE object, and the engine
    carries it: the state, the two event hooks, and the admission.

    It used to be four free functions over two copies of the state, and the
    drift the payload key cannot survive lived in the copies.

    Both halves are pinned, because the REWRITE is not bookkeeping: downstream
    reads `last_body` gated on `last_dir`, so a candidate admitted without it
    hands the model our own welcome bubble as "what he said"."""
    from automations._common import MSG_CLIP, TurnHandoff

    # The engine's candidate carries the object.
    assert isinstance(_Candidate(61099).turn, TurnHandoff)

    def _turn(**kw) -> TurnHandoff:
        # His newest inbound of ANY kind is a caption-less selfie he sent AFTER
        # the words — the shape that used to make the admission diverge per lane.
        t = TurnHandoff()
        t.on_inbound("<p>" + kw.get("worded", "hey are you real") + "</p>",
                     kw.get("worded", "hey are you real"))
        t.on_outbound(took_the_turn=True, automation_kind="welcome")
        t.on_inbound("", "")                       # the selfie: wordless
        if not kw.get("window", True):
            t.on_outbound(took_the_turn=True, automation_kind="autoreply")
        return t

    # Admitted: named, he spoke WORDS, nothing but welcome bubbles since — and
    # the wordless row that landed on top of them changes nothing.
    assert _turn().admit(61099, {61099}) == "hey are you real"

    # Each of the three conditions refuses on its own.
    for kw, ids in (({}, set()),                          # not named
                    ({"worded": "   "}, {61099}),         # he said nothing
                    ({"window": False}, {61099})):        # answered
        assert _turn(**kw).admit(61099, ids) is None, (kw, ids)

    # "He said something" is HIS WORDS, not a per-lane message counter. An
    # emoji-only reply stops the burst (send_welcome's predicate is
    # `body != ''`), so it must also open the gate — on welcome_chatter_for_info
    # `fan_msg_n` never moves for one, which used to truncate his burst and
    # then silently refuse the rescue for it.
    assert _turn(worded="😍").admit(61099, {61099}) == "😍"

    # A tags-only row renders to "" — words to the SQL, so the burst really
    # was aborted for it — and must not wipe the words already held.
    t = _turn()
    t.on_inbound("<br>", "")
    assert t.last_worded_in == "hey are you real", t
    # …and the ledger's bare-tip row is OUR bookkeeping, not his words.
    from transaction_ingest import tip_ledger_body
    t.on_inbound(tip_ledger_body(500), tip_ledger_body(500))
    assert t.last_worded_in == "hey are you real", t

    # The stored words are clipped exactly like the history line, so the line
    # the handoff installs can never be longer than the one the prompt renders.
    t = TurnHandoff()
    t.on_inbound("x" * 1200, "x" * 1200)
    assert len(t.last_worded_in) == MSG_CLIP, len(t.last_worded_in)

    # The window rule: a row that did not take the turn is transparent; one that
    # did closes it unless it IS the welcome bubble that caused the handoff.
    def _after(open_: bool, **kw) -> bool:
        t = TurnHandoff(window_open=open_)
        t.on_outbound(**kw)
        return t.window_open
    assert _after(True, took_the_turn=False, automation_kind="image_reply") is True
    assert _after(True, took_the_turn=True, automation_kind="welcome") is True
    assert _after(True, took_the_turn=True, automation_kind=None) is False
    assert _after(True, took_the_turn=True, automation_kind="autoreply") is False
    # Once closed it stays closed — a later welcome bubble cannot reopen it.
    assert _after(False, took_the_turn=True, automation_kind="welcome") is False


async def case_turn_handoff_does_not_bypass_the_blacklist():
    """H5's negative: the handoff opens the TURN gate and nothing else. A
    blacklisted fan's job answers him nothing — the forced-turn payload must
    never become a way around a stop somebody made on purpose."""
    aid = "acc_c_handoff_black"
    fid = 61005
    await _seed_account(aid)
    await _seed_fan(aid, fid, name="Sam")
    await _seed_eaten_reply(aid, fid)
    async with get_session() as s:
        s.add(Blacklist(fan_id=fid, reason="manual"))
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload=_handoff_payload(fid))
    assert res["replies_sent"] == 0, res
    assert res["skipped_listed"] == 1 and res["turn_handoffs"] == 0, res
    assert fake.sent == [], fake.sent


async def case_image_reply_does_not_steal_the_turn_wcfi():
    """This lane owns the $0 fans — the population that actually sends photos —
    so the reaction-turn bug bites hardest here.

    `tip_reward._run_image_reply` (since removed; its rows remain) answered his
    photo within seconds with a picture and an empty caption. That row is NEWER than his message, and `_gather` moved
    `last_dir` to "out" on ANY outbound, so the gate below ("only answer when the
    fan spoke last") dropped the words she owed him — silently, on every sweep,
    for as long as he stayed quiet. The freebie stays in the history she reads
    (and is NAMED there, because the empty caption would otherwise render as a
    blank line); it just does not close the turn."""
    aid = "acc_imgreply_wcfi"
    await _seed_account(aid)
    await _seed_fan(aid, 9101)
    base = _T0
    await _add_msg_row(aid, 9101, "in", "", base,
                       media_count=1, image_desc="a photo of him shirtless")
    await _add_msg_row(aid, 9101, "out", "", base + timedelta(seconds=30),
                       automation_kind="image_reply")

    c = (await a05._gather(aid, {9101}))[9101]
    assert c.last_dir == "in", c.last_dir
    assert c.last_body == "[he sent: a photo of him shirtless]", c.last_body
    assert [d for d, _ in c.messages] == ["in", "out"], c.messages
    assert c.messages[1][1] == "[you sent him a pic back]", c.messages

    fake = _use_fake()
    _patch_llm()
    res = await run_once(aid, "welcome_chatter_for_info",
                         payload={"only_fan_ids": [9101]})
    assert res["skipped_not_turn"] == 0, res
    assert res["replies_sent"] == 1 and fake.sent, (res, fake.sent)

    # Control: a real reply of HERS still closes the turn.
    aid2 = "acc_imgreply_wcfi2"
    await _seed_account(aid2)
    await _seed_fan(aid2, 9102)
    await _add_msg_row(aid2, 9102, "in", "", base,
                       media_count=1, image_desc="a photo of him shirtless")
    await _add_msg_row(aid2, 9102, "out", "damn 😏", base + timedelta(seconds=30),
                       automation_kind="welcome_chatter_for_info")
    fake2 = _use_fake()
    res2 = await run_once(aid2, "welcome_chatter_for_info",
                          payload={"only_fan_ids": [9102]})
    assert res2["skipped_not_turn"] == 1, res2
    assert fake2.sent == [], fake2.sent


_harness.run(
    case_turn_handoff_answers_the_fan_our_welcome_talked_over,
    case_turn_handoff_reads_HIS_line_not_our_welcome_bubble,
    case_turn_handoff_answers_an_EMOJI_ONLY_reply_too,
    case_turn_handoff_without_the_key_answers_nobody,
    case_turn_handoff_stands_down_when_somebody_already_answered,
    case_turn_handoff_survives_an_UNDESCRIBED_wordless_photo,
    case_turn_handoff_line_is_his_words_not_the_newer_wordless_row,
    case_turn_handoff_rewrites_his_line_even_when_a_photo_made_it_his_turn,
    case_turn_handoff_still_refuses_a_fan_who_only_ever_tipped,
    case_words_predicate_matches_the_sql,
    case_turn_handoff_does_not_bypass_the_blacklist,
    case_turn_handoff_seam_is_one_object,
    case_content_ask_never_builds_a_tip_ask,
    case_core_facts_pursued_until_filled,
    case_name_capped_at_two_asks_then_drops,
    case_style_splits_line_into_three,
    case_length_drives_bubble_count,
    case_seeded_split_never_touches_the_global_rng,
    case_split_strategy_randomiser_varies,
    case_two_questions_never_drops_content,
    case_lead_reaction_dedup_stops_repeated_oof,
    case_echo_guard_drops_parroted_bubbles,
    case_question_order_age_first_boobs_last,
    case_graduation_closes_the_fan_to_every_bot,
    case_only_fan_ids_scopes_to_one_fan,
    case_mid_funnel_fan_skipped,
    case_history_tail_override_truncates_convo,
    case_reply_and_extract_use_separate_tails,
    case_eligible_chat_gets_one_reply,
    case_inline_fill_saves_facts_before_reply,
    case_nickname_pushed_on_reply,
    case_info_complete_keeps_gathering_if_questions_left,
    case_info_complete_handoff_regens_geninfo,
    case_reply_refreshes_stale_profile,
    case_refresh_dedups_pending_job,
    case_blacklist_and_skiplist_skipped,
    case_we_spoke_last_is_skipped,
    case_spend_gate_skiplists,
    case_tip_also_graduates,
    case_subscriber_is_not_graduated,
    case_too_long_skiplists,
    case_emoji_reactions_not_counted_toward_cap,
    case_fan_lease_blocks_reply,
    case_cooldown_skips_reply,
    case_reply_short_cooldown_releases_lease,
    case_dry_run_sends_nothing,
    case_cap_stops_run,
    case_rejected_key_stops_run_after_one_call,
    case_missing_key_skips_run_without_a_call,
    case_no_id_pauses_fan_no_double_reply,
    case_no_id_lapsed_sub_quarantines_a_week,
    case_turn_cap_ends_the_interview,
    case_failed_send_still_counts_a_turn,
    case_mark_read_after_send_not_on_skip,
    case_mark_read_failure_does_not_break_send,
    case_peer_creator_skipped_as_spam,
    case_labelled_fan_without_promo_replied,
    case_labelled_fan_with_history_replied,
    case_paying_peer_creator_still_replied,
    case_real_fan_other_source_replied,
    case_force_ids_overrides_spam_guard,
    case_muted_creator_not_replied,
    case_muted_creator_skip_persisted_and_honored,
    case_scrape_mute_flip_reconciles_skip,
    case_muted_non_creator_not_skiplisted,
    case_manual_restrict_blocks_and_lifts,
    case_extract_skips_saturated_profile,
    case_sticker_rides_after_reply,
    case_sticker_only_reply_welcome_chatter_for_info,
    case_skip_roll_strips_stray_marker_welcome_chatter_for_info,
    case_image_reply_does_not_steal_the_turn_wcfi,
)
