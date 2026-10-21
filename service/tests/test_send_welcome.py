#!/usr/bin/env python3
"""
A09 send_welcome — automation tests (spec 09_send_welcome.md).

Acceptance the spec calls out: a new sub yields EXACTLY one welcome (no dup on
restart), persisted and visible in chat. These cases run the automation through
the real `run_once` dispatcher (so registry wiring + automation_runs are
exercised) against a fake OFClient + a patched llm_client.chat — no network.

  case_new_subs_get_one_welcome_each:
      2 new subscribers → 2 welcomes sent, 2 welcome_sent rows, 2 outbound
      `messages` rows (direction='out', body persisted = "visible in chat"),
      automation_runs status=ok with stats.
  case_no_dup_on_restart:
      a second run over the SAME notifications feed welcomes nobody (welcome_sent
      dedup survives the "restart").
  case_dedup_skips_preexisting:
      a fan already in welcome_sent is skipped; only the truly-new one is welcomed.
  case_fan_lease_blocks_welcome:
      a live lease held by another automation makes that fan skip this cycle.
  case_dry_run_sends_nothing:
      dry_run generates but neither sends nor marks welcome_sent.
  case_cap_never_costs_a_welcome:
      llm_client raising LLMCapExceeded still welcomes everyone (bubble 2
      verbatim) — the welcome itself makes no LLM call.

Two knobs from plans/welcome-pacing have their own blocks below:
  `skip_time_bubble` — bubble 2 is DROPPED (not reworded), it outranks `time_only`
      and any pin.
  `human_pace` — the burst is paced and fans run concurrently.
  case_follow_back_under_human_pace  the H1 interaction: follow-back on the
      CONCURRENT path — one follow per landed welcome, none double, ledger stamped.
  case_follow_back_null_means_the_default_not_off  ⚠️ MONEY: a stored `null`
      (the one non-boolean the API lets through) means what ABSENT means, not
      False — `bool(payload.get(k, True))` read it as "lane off, gate off".
  case_run_stats_carry_the_follow_back_knobs  the run reports `follow_back` +
      `follow_back_gate` as it resolved them; five zero counters cannot be read
      without them.
  case_paced_run_cancelled_raises_not_returns  a cancelled child makes run()
      RAISE, so the executor parks + requeues instead of finalising 'ok'.
  case_paced_cancel_while_parked_takes_the_spawned_bursts_down  the OTHER half:
      cancelling while the admit loop sleeps on sem.acquire() must take the
      already-spawned bursts with it — no DM, no paid follow, after the cancel.
      ⚠️ EVERY pacing case must patch `send_welcome.hold_with_typing` with a
      recorder. CHATTERLY_TEST_MODE zeroes `typing_wpm` and the indicator, but it
      does NOT zero the sampler's quiet draws — an unpatched case really would
      sleep U(10,25)s per bubble. Use `async with recording_holds() as holds:`;
      it puts the real hold back on the way out, on every path.

Run: ./venv/bin/python service/tests/test_send_welcome.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automations import _run_pool, send_welcome, welcome_compose, welcome_turn  # noqa: E402
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, AutomationRun, Fan, FanLease,
    FanProfile, FollowPingState, Message, NudgeState, ScheduledJob, SkipList,
    WelcomeSent,
)
from llm_client import LLMCapExceeded  # noqa: E402
from transaction_ingest import tip_ledger_body  # noqa: E402

OWN_ID = "999"


# ── Fakes (no network) ────────────────────────────────────────────────

class FakeOF:
    """Serves a canned subscribe-notifications feed; records sends (+ any media)
    and echoes a real-looking OF message object (id/text/createdAt). Optionally
    serves a 'bot' vault folder + photos (vault=True)."""

    def __init__(self, subs: list[dict], user_id: str = OWN_ID, *, vault: bool = False):
        self.user_id = user_id
        self._subs = subs
        self.sent: list[tuple[int, str, list]] = []
        self.prices: list[float | None] = []   # each send's `price`, beside `sent`
        # GIF sends, recorded SEPARATELY: `sent` is unpacked as a 3-tuple by two
        # dozen cases, so the giphy id gets its own list rather than a 4th field.
        self.gifs: list[tuple[int, str, str]] = []
        self.gif_fails = False   # make the GIF send raise (bubble-4 failure case)
        self.fail_texts: set[str] = set()   # text bubbles whose send raises
        self._next_id = 9_000_000_000_000
        self._vault = vault
        # Follow-back seam: who we followed / re-subscribed, plus the profile
        # payloads get_user serves when the paid-profile gate is switched on.
        self.followed: list[int] = []
        self.resubscribed: list[int] = []
        self.profiles: dict[int, dict] = {}   # fan_id → get_user payload
        self.follow_fails: set[int] = set()   # fans whose follow_user raises
        # `paged`: serve the feed `limit` at a time from `offset` (OF's
        # list + hasMore); every offset asked is recorded.
        self.paged = False
        self.offsets: list[int] = []

    def follow_user(self, user_id):
        if int(user_id) in self.follow_fails:
            raise RuntimeError(f"follow refused: {user_id}")
        self.followed.append(int(user_id))
        return {"ok": True}

    def resubscribe_user(self, user_id):
        self.resubscribed.append(int(user_id))
        return {"ok": True}

    def get_user(self, user_id) -> dict:
        # Default: a free profile with no existing edge → a plain follow.
        return self.profiles.get(int(user_id), {"subscribePrice": 0})

    def notifications(self, *, limit: int = 10, offset: int = 0, type=None, **kw) -> dict:
        # A sub's `createdAt` (when a case sets one) is the notification's own stamp.
        self.offsets.append(int(offset))
        subs = self._subs[offset:offset + limit] if self.paged else self._subs
        more = self.paged and offset + limit < len(self._subs)
        return {"list": [{"user": {k: v for k, v in s.items() if k != "createdAt"},
                          **({"createdAt": s["createdAt"]} if s.get("createdAt") else {})}
                         for s in subs], "hasMore": more}

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        gid = kw.get("giphy_id")
        if gid and self.gif_fails:
            raise RuntimeError("giphy id rejected")
        if text in self.fail_texts:
            raise RuntimeError(f"send refused: {text!r}")
        self._next_id += 1
        self.sent.append((int(chat_id), text, list(media_files or [])))
        self.prices.append(kw.get("price"))
        if gid:
            self.gifs.append((int(chat_id), text, str(gid)))
        return {
            "id": self._next_id,
            "text": f"<p>{text}</p>",
            "createdAt": "2026-06-04T12:00:00+00:00",
        }

    # ── Seams the CHAT engines touch. Only the handoff case below drives a chat
    # engine against this fake (it runs the very job send_welcome enqueued), and
    # these are the calls that lane makes beyond `send_message`.
    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def vault_lists(self, **kw) -> dict:
        if not self._vault:
            return {"list": []}
        return {"list": [{"id": 77, "name": "Bot"}, {"id": 9, "name": "other"}]}

    def vault_media(self, *, list_id=None, **kw) -> dict:
        if not self._vault or list_id != 77:
            return {"list": []}
        return {"list": [{"id": 501}, {"id": 502}, {"id": 503},
                         {"id": 504}, {"id": 505}, {"id": 506}]}


def _use_fake(subs: list[dict], *, vault: bool = False) -> FakeOF:
    fake = FakeOF(subs, vault=vault)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "heyy so happy you're here 💕") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]


def _patch_llm_cap() -> None:
    async def _raise(**kw):
        raise LLMCapExceeded("acc", 100, 200)
    llm_client.chat = _raise  # type: ignore[attr-defined]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


def _sub(uid: int, name: str | None = None, username: str | None = None) -> dict:
    return {"id": uid, "name": name, "username": username or f"u{uid}"}


# ── 🔴 Acceptance: a new sub yields exactly one welcome ───────────────

async def case_new_subs_get_one_welcome_each():
    aid = "acc_w1"
    await _seed_account(aid)
    _use_fake([_sub(1001, name="Bob"), _sub(1002, username="mystery_guy")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={})
    assert res["status"] == "ok", res
    assert res["new_subscribers"] == 2, res
    assert res["welcomes_sent"] == 2, res
    assert res["errors"] == 0 and res["skipped_locked"] == 0, res

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert {w.fan_id for w in ws} == {1001, 1002}, [w.fan_id for w in ws]

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 2, f"two outbound rows, got {len(msgs)}"
        assert all(m.direction == "out" for m in msgs), [m.direction for m in msgs]
        # Visible in chat = body persisted.
        assert all(m.body for m in msgs), "welcome body persisted"

        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs


# ── No dup on restart ─────────────────────────────────────────────────

async def case_no_dup_on_restart():
    aid = "acc_w2"
    await _seed_account(aid)
    _use_fake([_sub(2001, name="Cara")])
    _patch_llm()

    r1 = await run_once(aid, "send_welcome", payload={})
    assert r1["welcomes_sent"] == 1, r1

    # Same feed again (simulate restart / next tick): welcome_sent dedups.
    r2 = await run_once(aid, "send_welcome", payload={})
    assert r2["status"] == "ok", r2
    assert r2["new_subscribers"] == 0, r2
    assert r2["welcomes_sent"] == 0, r2

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert len(ws) == 1, f"still exactly one welcome_sent row, got {len(ws)}"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 1, f"no duplicate message, got {len(msgs)}"


# ── Pre-existing welcome_sent row is skipped ──────────────────────────

async def case_dedup_skips_preexisting():
    aid = "acc_w3"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(WelcomeSent(account_id=aid, fan_id=3001, fan_username="old_fan"))
    _use_fake([_sub(3001, name="Old"), _sub(3002, name="New")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={})
    assert res["new_subscribers"] == 1, res
    assert res["welcomes_sent"] == 1, res

    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert {m.fan_id for m in msgs} == {3002}, [m.fan_id for m in msgs]


# ── A live fan-lease blocks the welcome this cycle ────────────────────

async def case_fan_lease_blocks_welcome():
    aid = "acc_w4"
    await _seed_account(aid)
    _use_fake([_sub(4001, name="Dee"), _sub(4002, name="Eve")])
    _patch_llm()

    # Another automation holds 4001's send-lease.
    assert await acquire_fan_lease(aid, 4001, "welcome_chatter_for_info", ttl_s=300) is True

    res = await run_once(aid, "send_welcome", payload={})
    assert res["skipped_locked"] == 1, res
    assert res["welcomes_sent"] == 1, res

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid)
        )).all()
        assert {r[0] for r in ws} == {4002}, ws  # 4001 not welcomed (was leased)


# ── W3: a fan on post-send cooldown is skipped (before the lease) ─────

async def case_cooldown_skips_welcome():
    aid = "acc_w4b"
    await _seed_account(aid)
    _use_fake([_sub(4101, name="Cool"), _sub(4102, name="Down")])
    _patch_llm()

    # Another automation messaged 4101 moments ago → it's resting.
    await ax.start_fan_cooldown(aid, 4101)

    res = await run_once(aid, "send_welcome", payload={})
    assert res["skipped_cooldown"] == 1, res
    assert res["welcomes_sent"] == 1, res
    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid)
        )).all()
        assert {r[0] for r in ws} == {4102}, ws  # 4101 rested, only 4102 welcomed


# ── W3: the lease is HANDED BACK on a send; the rest is the only brake ─

async def case_lease_released_on_send_so_the_rest_is_the_only_brake():
    """CHANGED 07-26. This sender used to keep the lease and let it expire, so the
    generic 15-minute `_LEASE_TTL_S` — not the 10-minute rest it deliberately set —
    decided when the chat engine could answer. Measured live: a new subscriber
    replied 50 SECONDS after his welcome and waited ~14 minutes, with every tick
    reporting `skipped_locked: 1`. A brand-new sub is the hottest lead there is.

    Now the rest is the single brake, and it is short (`_WELCOME_REST_S`, 2.5 min)
    so he gets answered while he is still typing."""
    aid = "acc_w4c"
    await _seed_account(aid)
    _use_fake([_sub(4201, name="Keep")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={})
    assert res["welcomes_sent"] == 1, res
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 4201)) is None, \
            "lease HANDED BACK after a confirmed send — it must not outlast the rest"
        assert await ax.fan_on_cooldown(aid, 4201) is True, "the rest is in force"
        f = await s.get(Fan, (aid, 4201))
    # ...and the rest is the SHORT one, not the 10-min drip default. Bounded on
    # both sides: too long and we are back to the bug, zero and we talk over the
    # welcome we just sent.
    left = (f.automation_paused_until - datetime.utcnow()).total_seconds()
    assert 0 < left <= welcome_turn.WELCOME_REST_S, f"{left}s left, cap {welcome_turn.WELCOME_REST_S}"
    assert welcome_turn.WELCOME_REST_S <= 180, "a new sub must not wait more than ~3 min"

    # dry_run never sends → the lease it took is released.
    _use_fake([_sub(4202, name="Drop")])
    res2 = await run_once(aid, "send_welcome", payload={"dry_run": True})
    assert res2["welcomes_sent"] == 1, res2  # would-send
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 4202)) is None, "lease released on dry run"


# ── dry_run: generate but neither send nor mark ───────────────────────

async def case_dry_run_sends_nothing():
    aid = "acc_w5"
    await _seed_account(aid)
    fake = _use_fake([_sub(5001, name="Fay")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"dry_run": True})
    assert res["welcomes_sent"] == 1, res  # counted as would-send
    assert fake.sent == [], "dry run must not call send_message"

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert ws == [], "dry run must not mark welcome_sent"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert msgs == [], "dry run writes no message row"


# ── Daily LLM cap can no longer cost anyone a welcome ─────────────────

async def case_cap_never_costs_a_welcome():
    """A capped account still welcomes EVERY fan, nameless ones included. The
    greeting and bubble 2 are both deterministic, so a cap has nothing to stop.

    This inverts the old contract: the no-name riff used to be an LLM call, so a
    cap trip broke out of the loop and those fans got nothing (welcomes_sent == 0,
    no welcome_sent rows). Deleting that call is what made the cap harmless."""
    aid = "acc_w6"
    await _seed_account(aid)
    await _seed_brain(aid)          # gives bubble 2
    fake = _use_fake([_sub(6001, username="gus_xo"), _sub(6002, username="hal_xo")])
    _patch_llm_cap()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["status"] == "ok", res
    assert res["welcomes_sent"] == 2, res
    assert fake.sent[0][1] == "Hey G-G-G-Gorgeous gus ! !!", fake.sent[0]
    assert fake.sent[1][1].startswith("doing "), fake.sent[1]   # verbatim activity

    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid)
        )).scalars().all()
        assert len(ws) == 2, f"both fans welcomed despite the cap, got {len(ws)}"


# ── with_image=True attaches a time-of-day bot-folder vault media id ──

async def case_with_image_attaches_bot_media():
    aid = "acc_w7"
    await _seed_account(aid)
    fake = _use_fake([_sub(7001, name="Ivy")], vault=True)
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": True})
    assert res["welcomes_sent"] == 1, res
    assert res["image_attached"] == 1, res
    assert len(fake.sent) == 1, fake.sent
    _, _, media = fake.sent[0]
    assert len(media) == 1 and 501 <= media[0] <= 506, media


# ── with_image=False (and no bot folder) still sends text-only ────────

async def case_text_only_when_with_image_false():
    aid = "acc_w8"
    await _seed_account(aid)
    fake = _use_fake([_sub(8001, name="Jay")], vault=True)  # folder exists…
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert res["image_attached"] == 0, res  # …but the knob is off
    assert len(fake.sent) == 1, fake.sent
    _, _, media = fake.sent[0]
    assert media == [], media  # text-only send carries no media


# ── Missing bot folder → graceful text-only even with_image=True ──────

async def case_with_image_no_bot_folder_sends_text():
    aid = "acc_w9"
    await _seed_account(aid)
    fake = _use_fake([_sub(9001, name="Kay")], vault=False)  # no vault folders
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": True})
    assert res["welcomes_sent"] == 1, res
    assert res["image_attached"] == 0, res
    _, _, media = fake.sent[0]
    assert media == [], media


# ── The picker is deterministic per hour (6-bucket → 0..5) ────────────

def case_photo_index_deterministic_per_hour():
    expected = {
        0: 5, 3: 5, 4: 5,          # pre-dawn / night
        5: 0, 8: 0,                # early morning
        9: 1, 11: 1,               # late morning
        12: 2, 14: 2,              # early afternoon
        15: 3, 17: 3,              # late afternoon
        18: 4, 20: 4,              # evening
        21: 5, 23: 5,              # night
    }
    for hour, idx in expected.items():
        got = welcome_compose._photo_index(hour)
        assert got == idx, f"hour {hour}: expected {idx}, got {got}"
    # Same hour always maps to the same index (deterministic, no clock/random).
    for hour in range(24):
        assert welcome_compose._photo_index(hour) == welcome_compose._photo_index(hour)


async def _seed_brain(aid: str) -> None:
    async with get_session() as s:
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Vancouver Island, Canada",
            time_activities_json=json.dumps(
                {k: f"doing {k} things" for k in
                 ("morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")}),
        ))


async def case_real_name_no_nick_proposes_stutter():
    """Real-name fan with NO stored nickname → deterministic 'precious' template as
    TWO bubbles: the stutter greeting, then the activity line (weekday/time-of-day/
    location). NO LLM call, and NO V1 'Will reply' third line."""
    aid = "acc_w11"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(11001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("LLM must not be called for the local template")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["errors"] == 0, res
    assert len(fake.sent) == 2, fake.sent                             # 2 bubbles, same fan
    assert {fid for fid, _, _ in fake.sent} == {11001}, fake.sent
    b1, b2 = fake.sent[0][1], fake.sent[1][1]
    assert b1 == "Hey S-S-S-Sexy Sofie ! !!", b1                      # stutter prefix + nickname
    assert b2.startswith("doing "), b2                   # verbatim activity
    # "…it's <weekday> <tod> in <location>" — no "By the way -", no parenthetical.
    # `where` carries its own " in ", so an account with no location degrades to
    # "…it's Sunday afternoon" rather than a dangling "in".
    assert "in Vancouver Island, Canada" in b2, b2                    # location/tod tag
    assert " in  in " not in b2 and b2.count("(") == b2.count(")"), b2
    assert "Will reply" not in b1 + b2, (b1, b2)                      # third line retired


async def case_name_resolved_from_db_still_stutters():
    """The notif only has a handle, but we know the fan's real name from the DB →
    we still generate the prefix+stutter from it (ALWAYS stutter), no LLM."""
    aid = "acc_w12"
    await _seed_account(aid)
    await _seed_brain(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=12001, real_name="Tom"))
    fake = _use_fake([_sub(12001, username="t_handle_88")])  # no display name
    async def _boom(**kw):
        raise AssertionError("LLM must not be called when a name is known")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    _, text, _ = fake.sent[0]
    assert text == "Hey T-T-T-Tasty Tom ! !!", text                   # name from DB, stutter prefix + nickname


async def case_welcome_name_resolution_matrix():
    """_resolve_welcome_name no longer has a chain of its own — it hands the row to
    _common.resolve_fan_name and only rides its two extra sources along (the gen_info
    profile nickname in the generated slot, the live notif name in the display slot).
    This pins the whole matrix so the delegation can't silently drift back."""
    aid = "acc_w_names"
    await _seed_account(aid)
    cases = [
        # (label, fan columns, profile nickname, notif name, expected)
        ("country label in both columns is not his name",
         dict(of_display_name="FanA577", generated_nickname="Canada/Office job/Spender",
              custom_nickname="Canada/Canada/office job", home_country="Canada"), None, None, ""),
        ("curated beats the raw OF display name",
         dict(of_display_name="Fan_e", custom_nickname="Tyren"), None, None, "Tyren"),
        ("HTML-escaped couple's account → the first name",
         dict(of_display_name="Chris&amp;Char", custom_nickname="Chris&amp;Char"),
         None, None, "Chris"),
        ("a handle is never minted into a name",
         dict(of_display_name="FanB10"), None, None, ""),
        ("curated 'First Last' greets by the FIRST name",
         dict(custom_nickname="Randy Lahey/Vancouver", of_display_name="RLdude"),
         None, None, "Randy"),
        ("a confirmed real_name still outranks everything",
         dict(real_name="Mike", custom_nickname="Garrett", of_display_name="zzz"),
         None, None, "Mike"),
        ("the gen_info profile nickname fills an empty row",
         dict(), "Sexy Sofie/Delta,Canada/30", None, "Sofie"),
        ("brand-new sub, no Fan row: the notification name is used",
         None, None, "Garrett Baydala", "Garrett"),
        ("...but not when that notif name is a handle",
         None, None, "u1000001", ""),
        ("his own city is not his name",
         dict(custom_nickname="Kelowna", home_city="Kelowna"), None, None, ""),
    ]
    for i, (label, cols, prof, notif, want) in enumerate(cases):
        fid = 14000 + i
        async with get_session() as s:
            if cols is not None:
                s.add(Fan(account_id=aid, fan_id=fid, **cols))
            if prof:
                s.add(FanProfile(account_id=aid, fan_id=fid, nickname=prof))
        got = await welcome_compose._resolve_welcome_name(
            aid, fid, {"name": notif} if notif else {})
        assert got == want, f"{label}: got {got!r}, want {want!r}"


async def case_random_handle_no_name_greets_deterministically():
    """No usable name anywhere → the greeting token comes from the HANDLE, with the
    same stutter a named fan gets and NO LLM call. A handle with no word in it —
    letterless OR a bare id — degrades to 'cutie'.

    🚨 A bare id used to become 'fan #N', and `_local_greeting` alliterates
    whatever it is handed as a name: 59 real subscribers opened their very first
    message to "Hey F-F-F-Flirty fan #800000704 ! !!" (last one 2026-08-21)."""
    aid = "acc_w13"
    await _seed_account(aid)
    fake = _use_fake([_sub(13001, username="xx_gamer_99")])  # name=None, no Fan row
    async def _boom(**kw):
        raise AssertionError("a nameless fan must NOT cost an LLM call")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert fake.sent[0][1] == "Hey G-G-G-Gorgeous gamer ! !!", fake.sent[0]

    # The token rules themselves, straight off the helper.
    assert welcome_compose._greet_token({"username": "u4471223"}) == "cutie"
    assert welcome_compose._greet_token({"username": "4471223"}) == "cutie"
    assert welcome_compose._greet_token({"username": "u4471223"}, "him") == "boy"
    # The whole point: an id must never reach the name template.
    assert "#" not in welcome_compose._local_greeting(
        welcome_compose._greet_token({"username": "u800000704"}))
    assert welcome_compose._greet_token({"username": "xx_rider_92"}) == "rider"
    assert welcome_compose._greet_token({"username": "bigdaddy69"}) == "bigdaddy"
    assert welcome_compose._greet_token({"name": "Zoe", "username": "zz"}) == "zoe"
    assert welcome_compose._greet_token({"username": "__99"}) == "cutie"
    assert welcome_compose._greet_token({}) == "cutie"


async def case_word_restriction_applied_to_sent_welcome():
    """V1 parity: every welcome bubble is run through apply_word_restriction before
    send — an OF-restricted word gets its first vowel doubled ('meet'→'meeet'). The
    activity bubble is the one that carries operator prose."""
    aid = "acc_w14"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Vancouver Island, Canada",
            time_activities_json=json.dumps(
                {k: "wanna meet up soon" for k in welcome_compose._SLOT_KEYS}),
        ))
    fake = _use_fake([_sub(14001, username="zz_handle_77")])

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    sent_text = fake.sent[1][1]  # bubble 2 — the operator's activity line
    assert "meeet" in sent_text and "meet " not in sent_text, sent_text


# ── per-slot hours ──

async def case_slot_hour_roundtrip():
    """Every slot's representative hour maps back to that slot (bucket sanity), and
    an unknown slot resolves to None (caller then falls back to 'now')."""
    for k in welcome_compose._SLOT_KEYS:
        h = welcome_compose._slot_hour(k)
        assert h is not None and welcome_compose._slot_key(h) == k, (k, h)
    assert welcome_compose._slot_hour("bogus") is None
    assert welcome_compose._slot_hour(None) is None


# ── W-pin: "reroll till I like one, then send THAT" (operator-pinned slot line) ──

async def _seed_pin(aid: str, pins: dict) -> None:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, aid)
        cfg.welcome_pinned_json = json.dumps(pins)


async def case_pinned_line_weekday_refresh():
    """_pinned_line returns the approved line with the stored weekday swapped to
    today; a line with no weekday token is returned untouched; an unpinned slot →
    None."""
    import re as _re
    today = welcome_compose._model_weekday(0)
    cfg = {"utc_offset": 0, "welcome_pins": {
        "afternoon_1": {"line": "just got back from the beach, Monday arvo lol",
                        "weekday": "Monday"},
        "night": {"line": "winding down, come say hi", "weekday": "Monday"},
    }}
    got = welcome_compose._pinned_line(cfg, 13)  # afternoon_1
    exp = ("just got back from the beach, Monday arvo lol" if today.lower() == "monday"
           else _re.sub(r"\bMonday\b", today, "just got back from the beach, Monday arvo lol"))
    assert got == exp, (got, exp)
    # No weekday token in the line → returned verbatim.
    assert welcome_compose._pinned_line(cfg, 22) == "winding down, come say hi"  # night
    # Unpinned slot → None.
    assert welcome_compose._pinned_line(cfg, 7) is None  # morning_1

    # Casing is PRESERVED: a lowercase day stays lowercase, ALL-CAPS stays ALL-CAPS
    # (not force-Title-cased mid-sentence). Force a replace with stored != today.
    stored = "Monday" if today != "Monday" else "Tuesday"
    lc = {"utc_offset": 0, "welcome_pins": {
        "afternoon_1": {"line": f"had a fun {stored.lower()} babe", "weekday": stored}}}
    assert welcome_compose._pinned_line(lc, 13) == f"had a fun {today.lower()} babe"
    uc = {"utc_offset": 0, "welcome_pins": {
        "afternoon_1": {"line": f"{stored.upper()} VIBES", "weekday": stored}}}
    assert welcome_compose._pinned_line(uc, 13) == f"{today.upper()} VIBES"


async def case_run_pin_ships_even_when_activity_blank():
    """A pinned slot with NO base activity line still ships the pinned line — the pin
    is authoritative, so bubble 2 is ADDED (not silently dropped)."""
    aid = "acc_w_pin_blank"
    await _seed_account(aid)
    async with get_session() as s:  # brain with NO time activities at all
        s.add(AccountAiConfig(account_id=aid, utc_offset=0, location="Argentina",
                              time_activities_json="{}"))
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(42001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("pinned slot must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 1, res
    assert len(fake.sent) == 2, fake.sent  # greeting + the added pinned bubble
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1] == line, fake.sent[1]


async def case_run_uses_pinned_line_no_llm():
    """A pinned slot makes send_welcome send the EXACT pinned line (no LLM),
    for the current slot regardless of wall-clock (all 6 slots pinned), and counts
    pinned_used. Greeting bubble stays the deterministic local template."""
    aid = "acc_w_pin"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"  # no weekday token → deterministic
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(40001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("pinned slot must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]  # greeting unchanged
    assert fake.sent[1][1] == line, fake.sent[1]                        # pinned line sent as-is


async def case_nameless_fan_gets_activity_bubble_and_pin():
    """A fan we can't name gets the LLM GREETING only — bubble 2 is the same
    deterministic activity line every named fan gets, so the operator's pinned line
    ships for them too. Before the greeting/activity split the LLM owned both
    bubbles and the pin was gated on a resolved name, so these fans silently
    bypassed it."""
    aid = "acc_w_pin_noname"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"  # no weekday token → deterministic
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(41001, username="xx_gamer_99")])  # no usable name
    async def _boom(**kw):
        raise AssertionError("pinned slot + nameless fan must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey G-G-G-Gorgeous gamer ! !!", fake.sent[0]
    assert fake.sent[1][1] == line, fake.sent[1]


# ── time_only: bubble 2 is the CLOCK, not the scene ──────────────────────

async def case_time_only_bubble_is_clock_without_activity():
    """`time_only` strips the activity half and keeps the clock: 'it's Thursday
    afternoon in Vancouver'. Three properties, because each has its own failure:
    the activity text is GONE, the line still ships on a slot the creator never
    filled in (the activity path returns [] there), and a location-less account
    degrades to the bare clock rather than a dangling ' in '."""
    today = welcome_compose._model_weekday(0)
    cfg = {"utc_offset": 0, "location": "Vancouver",
           "time_activities": {"afternoon_1": "just got back from the beach"}}

    long_ = welcome_compose._activity_bubble(cfg, 13)
    short = welcome_compose._activity_bubble(cfg, 13, time_only=True)
    assert long_ == [f"just got back from the beach... it's {today} afternoon in Vancouver"], long_
    assert short == [f"it's {today} afternoon in Vancouver"], short
    assert "beach" not in short[0], short

    # A slot with NO activity: the normal path has nothing to say, time-only does.
    assert welcome_compose._activity_bubble(cfg, 7) == []                       # morning_1
    assert welcome_compose._activity_bubble(cfg, 7, time_only=True) == [
        f"it's {today} morning in Vancouver"]
    # No location → no trailing "in".
    assert welcome_compose._activity_bubble(
        {"utc_offset": 0, "time_activities": {}}, 19, time_only=True) == [
        f"it's {today} evening"]


async def case_run_time_only_sends_short_second_bubble():
    """The rule's payload knob reaches the send: bubble 1 is the untouched stutter
    greeting, bubble 2 is the clock line with no activity in it."""
    aid = "acc_w_timeonly"
    await _seed_account(aid)
    await _seed_brain(aid)          # every slot has a "doing … things" activity
    fake = _use_fake([_sub(43001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "time_only": True})
    assert res["welcomes_sent"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    b2 = fake.sent[1][1]
    assert b2.startswith("it's "), b2
    assert "doing " not in b2, b2                       # the scene is gone
    assert "Vancouver Island, Canada" in b2, b2         # time AND place survive


async def case_time_only_outranks_a_pinned_line():
    """Every pin ever minted is a rerolled ACTIVITY line, so honouring one under
    `time_only` would keep shipping the long scene the operator just turned off —
    the checkbox would silently do nothing on precisely the slots someone cared
    enough to pin. time_only wins; unticking it restores the pin untouched."""
    aid = "acc_w_timeonly_pin"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(43101, name="Sofie"), _sub(43102, name="Mia")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "time_only": True, "test_fan": 43101,
                                  "test_name": "Sofie"})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 0, res
    assert fake.sent[1][1].startswith("it's "), fake.sent[1]
    assert fake.sent[1][1] != line, fake.sent[1]

    # Unticked, the SAME account + SAME pin ships the pinned line again.
    fake.sent.clear()
    res2 = await run_once(aid, "send_welcome",
                          payload={"with_image": False,
                                   "test_fan": 43102, "test_name": "Mia"})
    assert res2["welcomes_sent"] == 1 and res2["pinned_used"] == 1, res2
    assert fake.sent[1][1] == line, fake.sent[1]


async def case_time_only_always_opens_with_its():
    """The line must OPEN with "it's" — "it's monday morning in US" — for every fan."""
    aid = "acc_w_timeonly_its"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(43401, name="Nora"), _sub(43402, name="Owen")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "time_only": True})
    assert res["welcomes_sent"] == 2, res
    b2s = [t for i, (_, t, _) in enumerate(fake.sent) if i % 2]
    assert len(b2s) == 2 and all(t.startswith("it's ") for t in b2s), fake.sent


# ── question: the operator's own line, verbatim, as the THIRD bubble ─────

async def case_question_ships_verbatim_as_third_bubble():
    """The rule's `question` knob is the operator's exact words — bubble 3, sent
    word-for-word, never through the LLM. Three properties, each its own failure:
    it lands AFTER the greeting + activity line, its text is character-identical
    to what was saved, and it also rides a PINNED slot (a pin replaces the
    activity line, never the question)."""
    q = "so tell me, where are you from?"
    aid = "acc_w_question"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(44001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM — the question never does")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": q})
    assert res["welcomes_sent"] == 1, res
    assert len(fake.sent) == 3, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1].startswith("doing "), fake.sent[1]   # activity untouched
    assert fake.sent[2][1] == q, fake.sent[2]                   # verbatim, last
    assert fake.sent[2][2] == [], fake.sent[2]                  # text-only bubble

    # A pinned slot: [greeting, pinned line, question] — the pin doesn't eat it.
    aid2 = "acc_w_question_pin"
    await _seed_account(aid2)
    await _seed_brain(aid2)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid2, {k: {"line": line, "weekday": "Monday"}
                           for k in welcome_compose._SLOT_KEYS})
    fake2 = _use_fake([_sub(44002, name="Mia")])
    res2 = await run_once(aid2, "send_welcome",
                          payload={"with_image": False,
                                   "question": q})
    assert res2["welcomes_sent"] == 1 and res2["pinned_used"] == 1, res2
    assert [t for _, t, _ in fake2.sent[1:]] == [line, q], fake2.sent

    # Blank / whitespace-only = off: the classic two-bubble welcome, untouched.
    aid3 = "acc_w_question_blank"
    await _seed_account(aid3)
    await _seed_brain(aid3)
    fake3 = _use_fake([_sub(44003, name="Nora")])
    res3 = await run_once(aid3, "send_welcome",
                          payload={"with_image": False,
                                   "question": "   "})
    assert res3["welcomes_sent"] == 1, res3
    assert len(fake3.sent) == 2, fake3.sent


async def case_custom_message_replaces_the_burst():
    """The rule's `message` (Smart Messages' Delayed welcome text) IS the welcome:
    exactly one DM per fan, `{name}` filled with the resolved name (else "babe"),
    and nothing else rides with it — no time-of-day image, no activity line, no
    question, no GIF — even with every one of those knobs set. Blank keeps the
    generated burst."""
    aid = "acc_w_message"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45001, name="Sofie"), _sub(45002, username="x9_284")], vault=True)
    async def _boom(**kw):
        raise AssertionError("a custom welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome", payload={
        "with_image": True, "question": "what's yours?", "gif_id": "g123",
        "message": "  Hey {name}, so glad you're here!  "})
    assert res["welcomes_sent"] == 2, res
    assert res["image_attached"] == 0 and res["gifs_sent"] == 0, res
    assert sorted(fake.sent) == [
        (45001, "Hey Sofie, so glad you're here!", []),
        (45002, "Hey babe, so glad you're here!", []),
    ], fake.sent
    assert fake.gifs == [], fake.gifs

    # Blank = the generated burst, unchanged.
    aid2 = "acc_w_message_blank"
    await _seed_account(aid2)
    await _seed_brain(aid2)
    fake2 = _use_fake([_sub(45003, name="Nora")])
    res2 = await run_once(aid2, "send_welcome", payload={"with_image": False, "message": "   "})
    assert res2["welcomes_sent"] == 1, res2
    assert len(fake2.sent) == 2 and fake2.sent[0][1].startswith("Hey N-N-N-"), fake2.sent


def _stamp(minutes_ago: float) -> str:
    return (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat() + "+00:00"


async def _unsend_jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid,
            ScheduledJob.kind == "unsend_messages"))).scalars().all())


async def case_custom_message_carries_its_media_price_and_auto_unsend():
    """The Delayed welcome's media and price ride on `message` (a PPV, recorded
    at its price, never auto-unsent); a free one's Auto-unsend is queued; the
    generated burst ignores both and keeps its own image."""
    aid = "acc_w_msg_ppv"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45101, name="Sofie")], vault=True)
    res = await run_once(aid, "send_welcome", payload={
        "message": "Hey {name}!", "media_ids": [601, 602], "price_cents": 800,
        "unsend_minutes": 30})
    assert res["welcomes_sent"] == 1, res
    assert fake.sent == [(45101, "Hey Sofie!", [601, 602])] and fake.prices == [8.0], (
        fake.sent, fake.prices)
    async with get_session() as s:
        rows = (await s.execute(select(Message).where(
            Message.account_id == aid, Message.automation_kind == "welcome"))).scalars().all()
    assert [r.price_cents for r in rows] == [800], rows
    assert await _unsend_jobs(aid) == []

    aid = "acc_w_msg_free"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45102, name="Mia")])
    await run_once(aid, "send_welcome", payload={
        "message": "Hey {name}!", "media_ids": [603], "unsend_minutes": 30})
    assert fake.sent == [(45102, "Hey Mia!", [603])] and fake.prices == [None], fake.sent
    jobs = await _unsend_jobs(aid)
    assert len(jobs) == 1 and json.loads(jobs[0].payload_json)["targets"][0]["fan_id"] == 45102, jobs
    assert jobs[0].run_at > datetime.utcnow() + timedelta(minutes=29), jobs[0].run_at

    aid = "acc_w_burst_media"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45103, name="Nora")])
    await run_once(aid, "send_welcome", payload={
        "with_image": False, "media_ids": [604], "price_cents": 800, "unsend_minutes": 30})
    assert fake.sent and all(m == [] for _, _, m in fake.sent), fake.sent
    assert set(fake.prices) == {None} and await _unsend_jobs(aid) == [], fake.prices


async def case_the_effective_and_expiry_dates_bound_the_welcome():
    aid = "acc_w_window"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([{**_sub(45201, name="A"), "createdAt": _stamp(30)},
                      {**_sub(45202, name="B"), "createdAt": _stamp(5)},
                      _sub(45203, name="C")])
    later = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "+00:00"
    res = await run_once(aid, "send_welcome", payload={"message": "hi", "starts_at": later})
    assert res.get("reason") == "scheduled" and fake.sent == [], res
    res = await run_once(aid, "send_welcome", payload={"message": "hi", "ends_at": _stamp(1)})
    assert res.get("reason") == "expired" and fake.sent == [], res
    # The UI's "send test" is a force: it sends outside the window.
    await run_once(aid, "send_welcome", payload={"message": "hi", "starts_at": later,
                                                 "test_fan": 45299})
    assert [f for f, _, _ in fake.sent] == [45299], fake.sent
    # Effective 15 minutes ago: a subscribe from before it is never welcomed;
    # one with no readable stamp is.
    res = await run_once(aid, "send_welcome", payload={"message": "hi", "starts_at": _stamp(15)})
    assert sorted(f for f, _, _ in fake.sent) == [45202, 45203, 45299], fake.sent
    assert res["skipped_before_start"] == 1, res


async def case_the_random_delay_counts_from_the_subscribe():
    """Infloww's "after delay … a～b minutes": a sub not yet past his own draw is
    left for a later tick, unclaimed; one past it is welcomed."""
    aid = "acc_w_delay"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([{**_sub(45301, name="A"), "createdAt": _stamp(1)},
                      {**_sub(45302, name="B"), "createdAt": _stamp(10)}])
    payload = {"message": "hi", "delay_range": [2, 5]}
    res = await run_once(aid, "send_welcome", payload=payload)
    assert [f for f, _, _ in fake.sent] == [45302] and res["delayed"] == 1, (res, fake.sent)
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 45301)) is None
    # Ten minutes on he is past any draw in 2～5.
    fake._subs[0]["createdAt"] = _stamp(10)
    res = await run_once(aid, "send_welcome", payload=payload)
    assert sorted(f for f, _, _ in fake.sent) == [45301, 45302] and res["delayed"] == 0, res


async def case_with_a_delay_the_feed_is_read_back_past_the_longest_delay():
    """A held-back sub stays unclaimed; on a busy page he could slide out of the
    newest `limit` before he is due. With a delay set the feed is paged back
    until it is older than the longest delay (plus slack), so he is still found."""
    aid = "acc_w_delay_pages"
    await _seed_account(aid)
    await _seed_brain(aid)
    subs = [{**_sub(45501 + i, name=f"P{i}"), "createdAt": _stamp(m)}
            for i, m in enumerate((1, 2, 12, 13, 20, 30, 40))]
    fake = _use_fake(subs)
    fake.paged = True
    res = await run_once(aid, "send_welcome", payload={
        "message": "hi", "delay_range": [2, 5], "limit": 2, "max_welcomes": 10})
    # Pages 0, 2, 4: the third reaches past 5 + 10 minutes, so no fourth.
    assert fake.offsets == [0, 2, 4], fake.offsets
    welcomed = {f for f, _, _ in fake.sent}
    assert {45503, 45504, 45505, 45506} <= welcomed and 45501 not in welcomed, (res, fake.sent)
    assert 45507 not in welcomed, fake.sent
    # No delay: one page, as before.
    aid = "acc_w_no_delay_pages"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake(subs)
    fake.paged = True
    await run_once(aid, "send_welcome", payload={"message": "hi", "limit": 2})
    assert fake.offsets == [0], fake.offsets


async def case_a_paid_welcome_never_re_sells_media_the_fan_owns():
    aid = "acc_w_owner"
    await _seed_account(aid)
    await _seed_brain(aid)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=45601, message_id=45600, direction="out",
                      body="older set", price_cents=900, is_paid=True, media_ids="[702]",
                      created_at=datetime.utcnow() - timedelta(days=9)))
    fake = _use_fake([_sub(45601, name="Owns"), _sub(45602, name="New")])
    res = await run_once(aid, "send_welcome", payload={
        "message": "Hey {name}!", "media_ids": [701, 702], "price_cents": 800})
    assert res["welcomes_sent"] == 2, res
    by_fan = {f: (m, p) for (f, _, m), p in zip(fake.sent, fake.prices)}
    assert by_fan == {45601: ([], None), 45602: ([701, 702], 8.0)}, by_fan
    async with get_session() as s:
        rows = (await s.execute(select(Message).where(
            Message.account_id == aid, Message.automation_kind == "welcome"))).scalars().all()
    assert {r.fan_id: r.price_cents for r in rows} == {45601: 0, 45602: 800}, rows


async def case_a_failed_auto_unsend_queue_never_costs_the_welcome_claim():
    """Queuing the Auto-unsend fails: the welcome is still claimed (early claim
    or not), so the next tick never sends a second greeting."""
    real = ax.enqueue_followup

    async def boom(*a, **kw):
        raise RuntimeError("db locked")
    ax.enqueue_followup = boom
    try:
        for early in (True, False):
            aid = f"acc_w_unsend_boom_{early}"
            await _seed_account(aid)
            await _seed_brain(aid)
            fake = _use_fake([_sub(45701, name="Boom")])
            payload = {"message": "hi", "unsend_minutes": 30, "human_pace": False,
                       "stop_on_reply": early}
            res = await run_once(aid, "send_welcome", payload=payload)
            assert res["welcomes_sent"] == 1, res
            async with get_session() as s:
                assert await s.get(WelcomeSent, (aid, 45701)) is not None
            await run_once(aid, "send_welcome", payload=payload)
            assert len(fake.sent) == 1, fake.sent
    finally:
        ax.enqueue_followup = real


def case_the_rule_routes_hold_the_delayed_welcome_settings_to_the_contract():
    import automation_rules_api as rules_api
    from fastapi import HTTPException
    ok = rules_api._validate_payload_for_kind("send_welcome", {
        "message": "hi", "delay_range": [5, 5], "media_ids": [1, 1, 2],
        "price_cents": 300, "starts_at": "2026-07-01T10:00:00Z", "unsend_minutes": 0})
    assert (ok["delay_range"], ok["media_ids"], ok["starts_at"]) == (
        [5, 6], [1, 2], "2026-07-01T10:00:00+00:00"), ok
    for bad in ({"price_cents": 299, "media_ids": [1]}, {"price_cents": 500},
                {"price_cents": 20_001, "media_ids": [1]},
                {"delay_range": [1]}, {"unsend_minutes": 23 * 60 + 1}, {"ends_at": "later"},
                {"starts_at": "2026-07-02T00:00:00Z", "ends_at": "2026-07-01T00:00:00Z"}):
        try:
            rules_api._validate_payload_for_kind("send_welcome", bad)
        except HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"accepted {bad}")


# ── human_pace: the burst is paced, and fans run concurrently ────────────
#
# ⚠️ EVERY case below patches `send_welcome.hold_with_typing` with a RECORDER.
# CHATTERLY_TEST_MODE zeroes `typing_wpm` and forces the indicator off, but it does
# NOT zero the sampler's quiet draws — an unpatched paced case really would sleep
# U(10,25) seconds per bubble. The recorder is also the only way to assert on a
# hold's PHASES (quiet / think), which is most of what this feature is.

_REAL_HOLD = send_welcome.hold_with_typing
_REAL_SLEEP = _run_pool._sleep


async def _no_jitter(seconds: float) -> None:
    """`_run_pool._sleep` made instant: the paced pool sleeps a real U(0.5, 4.0)s
    start jitter per fan before its first bubble, and nothing in test mode
    zeroes that. Yields once so concurrent fans interleave here."""
    await asyncio.sleep(0)


def _record_holds(on_call=None) -> list[dict]:
    """Patch `hold_with_typing` with a recorder; return the list it fills.

    Each entry is the whole call — `(fan_id, seconds, typing_indicator, quiet_s,
    think_at_s, think_for_s)` — because the call COUNT and the phase split are
    both part of the contract (flags off must be exactly ONE flat hold per
    bubble). The recorder yields once so concurrent fans actually interleave at
    this point instead of each running straight through.

    The paced pool's START JITTER is recorded into the SAME list, as an entry
    with `fan_id: None` and `jitter: True` (`_run_pool._sleep` carries no fan),
    so a paced burst's timeline reads in order: its jitter, then its holds.

    `on_call(n, entry)` — awaited AFTER the entry is recorded and BEFORE the hold
    returns, i.e. exactly where a real hold is sleeping. That is the only
    deterministic seam for the `stop_on_reply` cases: it is where a mid-burst
    inbound row is written, so "he replied during the quiet phase" and "he replied
    while she was typing" are two different injection points rather than a race."""
    calls: list[dict] = []

    async def _rec(account_id, fan_id, seconds, *, typing_indicator=False,
                   quiet_s=0.0, think_at_s=0.0, think_for_s=0.0):
        calls.append({"fan_id": int(fan_id), "seconds": float(seconds),
                      "typing_indicator": bool(typing_indicator),
                      "quiet_s": float(quiet_s), "think_at_s": float(think_at_s),
                      "think_for_s": float(think_for_s)})
        await asyncio.sleep(0)
        if on_call is not None:
            await on_call(len(calls), calls[-1])

    async def _rec_jitter(seconds):
        calls.append({"fan_id": None, "seconds": float(seconds),
                      "typing_indicator": False, "quiet_s": 0.0,
                      "think_at_s": 0.0, "think_for_s": 0.0, "jitter": True})
        await asyncio.sleep(0)

    send_welcome.hold_with_typing = _rec  # type: ignore[assignment]
    _run_pool._sleep = _rec_jitter  # type: ignore[assignment]
    return calls


@asynccontextmanager
async def recording_holds(on_call=None):
    """`_record_holds`, with the un-patching attached to the block.

    Every case that records holds used to spell out its own
    `try: … finally: send_welcome.hold_with_typing = _REAL_HOLD`. Twenty of them,
    all correct — and the failure mode of the twenty-first is not a red test but
    a SILENT one: the recorder stays installed, every later case in the file
    records into a list nobody reads, and the paced ones (whose quiet draws test
    mode does NOT zero) start sleeping for real. That is a bug class, not a bug,
    and it is deleted by attaching the restore to the block instead of to the
    author's memory.

    (`case_follow_back_under_human_pace` still spells its own out — a third
    party's uncommitted follow-back work is interleaved in this file and its
    cases must survive this branch byte-for-byte.)"""
    calls = _record_holds(on_call)
    try:
        yield calls
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]


def case_hold_segments_are_the_four_shapes_and_they_sum():
    """`_hold_segments` is the one place that answers "may the fan interrupt
    here?", so the four shapes are pinned directly rather than only through a
    burst.

    The two things that matter and are easy to break silently:
      • the SUM. Splitting a hold must not add time to it — `Pace.total_s` is the
        only number in this subsystem that moves a clock, and every ceiling in
        the tree (the 900s fan lease, `rhythm.INLINE_MAX_S`) bounds it.
      • the CALL COUNT. A bubble that is not being checked is never split, which
        is what keeps an unflagged account's recorded holds byte-identical."""
    from automations.pacing import Pace
    seg = send_welcome._hold_segments

    # 1. UNPACED text — one hold, the flat typing time, no check after it: that
    #    hold IS the typing phase and she finishes what she started.
    out = seg(pace=None, typing_s=7.0, is_gif=False, typing_on=True,
              interruptible=True)
    assert len(out) == 1 and out[0].seconds == 7.0, out
    assert out[0].indicator is True and out[0].check_after is False, out

    # 2. UNPACED gif — the flat beat, indicator off, and the check goes AFTER it.
    out = seg(pace=None, typing_s=0.0, is_gif=True, typing_on=True,
              interruptible=True)
    assert len(out) == 1 and out[0].seconds == send_welcome._GIF_HOLD_S, out
    assert out[0].indicator is False and out[0].check_after is True, out
    # ...and with nothing being checked, nothing is checked.
    assert seg(pace=None, typing_s=0.0, is_gif=True, typing_on=True,
               interruptible=False)[0].check_after is False

    # 3. PACED text with a quiet lead-in, being checked — TWO holds that SUM.
    pace = Pace(total_s=30.0, quiet_s=18.0, think_at_s=4.0, think_for_s=6.0)
    out = seg(pace=pace, typing_s=12.0, is_gif=False, typing_on=True,
              interruptible=True)
    assert len(out) == 2, out
    assert abs(sum(x.seconds for x in out) - 30.0) < 1e-9, out
    dark, typing = out
    assert dark.seconds == 18.0 and dark.indicator is False, dark
    assert dark.check_after is True, dark          # the phase boundary
    assert dark.quiet_s == 0.0, ("the dark half is a plain dark hold", dark)
    assert typing.seconds == 12.0 and typing.indicator is True, typing
    assert typing.check_after is False, ("she finishes what she is typing", typing)
    assert (typing.think_at_s, typing.think_for_s) == (4.0, 6.0), typing

    # 4. The SAME pace, NOT being checked — one call, byte-identically today's.
    out = seg(pace=pace, typing_s=12.0, is_gif=False, typing_on=True,
              interruptible=False)
    assert len(out) == 1 and out[0].seconds == 30.0, out
    assert out[0].quiet_s == 18.0 and out[0].check_after is False, out
    # A paced bubble with NO quiet lead-in is never split either — there is no
    # dark phase for a reply to arrive in.
    flat = Pace(total_s=3.0, quiet_s=0.0)
    assert len(seg(pace=flat, typing_s=3.0, is_gif=False, typing_on=True,
                   interruptible=True)) == 1


async def case_flags_absent_every_hold_is_todays_flat_hold():
    """THE ADD-ON GATE for step 2. With `human_pace` absent, the recorded holds are
    exactly what this sender has always asked for: ONE call per bubble, the flat
    `typing_delay_seconds` total (0.0 under test mode), `_GIF_HOLD_S` for the GIF,
    zero quiet, zero think — and no start-jitter hold in front of the burst.

    Asserted on the CALL LIST, not on a stat, because every way this feature could
    leak into an unflagged account shows up here: an extra call, a non-zero quiet,
    or a sampler that ran when nobody asked it to."""
    aid = "acc_w_pace_off"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(47001, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    drew = {"n": 0}
    real_sampler = send_welcome.welcome_burst_pace
    def _tripwire(**kw):
        drew["n"] += 1
        return real_sampler(**kw)
    send_welcome.welcome_burst_pace = _tripwire  # type: ignore[assignment]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})
        send_welcome.welcome_burst_pace = real_sampler  # type: ignore[assignment]

    assert res["welcomes_sent"] == 1 and len(fake.sent) == 4, (res, fake.sent)
    assert drew["n"] == 0, f"the sampler ran {drew['n']} times with the flag off"
    assert res["human_pace"] is False, res
    assert res["deferred_budget"] == 0 and res["hold_overrun_max_s"] == 0.0, res
    # ONE hold per bubble, in order, and nothing in front of bubble 0.
    assert len(holds) == 4, holds
    assert all(h["fan_id"] == 47001 for h in holds), holds
    assert [h["seconds"] for h in holds] == [0.0, 0.0, 0.0, send_welcome._GIF_HOLD_S], holds
    assert all(h["quiet_s"] == 0.0 and h["think_at_s"] == 0.0
               and h["think_for_s"] == 0.0 for h in holds), holds


async def case_human_pace_hold_phases_match_the_table():
    """The recorded holds ARE the sampler's, bubble for bubble.

    Each hold is checked twice: against the band the plan's table specifies (so a
    mis-wired `idx`/`has_image`/`is_gif` argument shows up as a value from the
    wrong row), and against `welcome_burst_pace` re-run with the same seed (so the
    sender is provably passing the sampler's own numbers through, not numbers that
    merely look plausible). A start-jitter hold runs in front of the burst."""
    from random import Random
    from automations.pacing import welcome_burst_pace

    aid = "acc_w_pace_on"
    fid = 47101
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "human_pace": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["human_pace"] is True, res
    assert len(fake.sent) == 4, fake.sent
    assert res["image_attached"] == 1, res       # the image really was attempted
    # 1 start jitter + 4 bubbles.
    assert len(holds) == 5, holds
    jitter, b0, b1, b2, gif = holds
    assert all(h["fan_id"] == fid for h in holds[1:]), holds

    assert jitter.get("jitter") is True, jitter   # a plain sleep, not a hold
    assert 0.5 <= jitter["seconds"] <= 4.0, jitter

    # The sampler takes the bubble's ROLE; the SEED still keys on its index, so
    # both are passed and a mis-wired role shows up as a value from the wrong row.
    def _expect(idx, role, has_image, text):
        return welcome_burst_pace(
            role=role, has_image=has_image, typing_s=0.0, text=text,
            rng=Random(f"welcome_pace:{aid}:{fid}:{idx}"))

    e0 = _expect(0, "opener", True, fake.sent[0][1])
    assert 6.0 <= b0["quiet_s"] <= 18.0, b0        # she was picking a picture
    assert abs(b0["seconds"] - e0.total_s) < 1e-9, (b0, e0)
    assert abs(b0["quiet_s"] - e0.quiet_s) < 1e-9, (b0, e0)

    e1 = _expect(1, "gap", True, fake.sent[1][1])
    assert 10.0 <= b1["quiet_s"] <= 25.0, b1       # the gap before the second line
    assert b1["seconds"] > b1["quiet_s"], b1       # ...then the enter press
    assert abs(b1["seconds"] - e1.total_s) < 1e-9, (b1, e1)

    e2 = _expect(2, "tail", True, fake.sent[2][1])
    assert abs(b2["seconds"] - e2.total_s) < 1e-9, (b2, e2)
    assert b2["seconds"] < 25.0, b2                # the question is a short beat

    egif = _expect(3, "gif", True, "")
    assert 2.0 <= gif["seconds"] <= 6.0, gif       # picked, not typed
    assert abs(gif["quiet_s"] - gif["seconds"]) < 1e-9, gif   # ...so it is all quiet
    assert gif["typing_indicator"] is False, gif
    assert abs(gif["seconds"] - egif.total_s) < 1e-9, (gif, egif)

    # Nothing the burst asks for may reach the inline hold ceiling.
    from automations import rhythm as _rhythm
    assert all(h["seconds"] < _rhythm.INLINE_MAX_S for h in holds), holds


async def case_human_pace_the_question_keeps_its_own_beat_in_a_short_burst():
    """The burst is VARIABLE-LENGTH, so the question must be paced as the QUESTION
    however few bubbles ride in front of it.

    Two shipped shapes drop the middle bubble and slide the operator's question
    into position 1:

      • `skip_time_bubble` — the operator ticked the box;
      • an UNFILLED slot — `_activity_bubble` returns [] when the account has no
        activity for this time of day and `time_only` is off. Already live; it is
        the same shape `case_run_pin_ships_even_when_activity_blank` covers on
        the pinned side.

    Paced by POSITION, the question then inherited the time line's U(10,25) dark
    lead-in: up to twenty-five seconds of blank screen before five words, on a
    fan's first ever conversation. Nobody decided that — no comment, no test.

    Asserted as EQUALITY against the sampler's "tail" row rather than as a band,
    because the tail's own drift can land inside the gap band on some seeds: only
    the exact Pace tells the two rows apart."""
    from random import Random
    from automations.pacing import welcome_burst_pace

    q = "what's yours?"
    for shape, fid in (("skip_time_bubble", 47301), ("unfilled_slot", 47302)):
        aid = f"acc_w_role_{shape}"
        await _seed_account(aid)
        if shape == "skip_time_bubble":
            await _seed_brain(aid)
            payload = {"with_image": False, "human_pace": True,
                       "skip_time_bubble": True, "question": q}
        else:
            # A brain with NO activity for any slot: the activity bubble is [].
            async with get_session() as _s:
                _s.add(AccountAiConfig(account_id=aid, utc_offset=0,
                                       location="Argentina",
                                       time_activities_json="{}"))
            payload = {"with_image": False, "human_pace": True,
                       "question": q}
        fake = _use_fake([_sub(fid, name="Sofie")])
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        async with recording_holds() as holds:
            res = await run_once(aid, "send_welcome", payload=payload)

        # Greeting then question — the middle bubble really is gone.
        assert res["welcomes_sent"] == 1, (shape, res)
        assert len(fake.sent) == 2, (shape, fake.sent)
        assert fake.sent[1][1] == q, (shape, fake.sent)
        # start-jitter, the greeting, the question.
        assert len(holds) == 3, (shape, holds)

        seed = Random(f"welcome_pace:{aid}:{fid}:1")
        as_tail = welcome_burst_pace(role="tail", has_image=False, typing_s=0.0,
                                     text=q, rng=seed)
        as_gap = welcome_burst_pace(role="gap", has_image=False, typing_s=0.0,
                                    text=q, rng=Random(f"welcome_pace:{aid}:{fid}:1"))
        got = holds[2]
        assert abs(got["seconds"] - as_tail.total_s) < 1e-9, (shape, got, as_tail)
        assert abs(got["quiet_s"] - as_tail.quiet_s) < 1e-9, (shape, got, as_tail)
        # ...and the row it is NOT. Without this the case would still pass if the
        # two rows ever collapsed into the same numbers.
        assert 10.0 <= as_gap.quiet_s <= 25.0, (shape, as_gap)
        assert abs(got["seconds"] - as_gap.total_s) > 1.0, (shape, got, as_gap)


async def case_human_pace_test_fan_is_exempt():
    """H9: the UI's "send test" points this sender at one fan and waits for the
    result. Under `human_pace` that operator would sit through real quiet draws to
    see a message he asked for NOW — so a `test_fan` send keeps today's flat holds,
    the sampler is never called, and the run says so in its stats."""
    aid = "acc_w_pace_test"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True, "test_fan": 47201,
                                      "test_name": "Sofie"})

    assert res["welcomes_sent"] == 1 and res["human_pace"] is False, res
    assert len(fake.sent) == 2, fake.sent
    assert len(holds) == 2, holds                  # no jitter hold in front
    assert all(h["seconds"] == 0.0 and h["quiet_s"] == 0.0 for h in holds), holds


async def case_human_pace_runs_fans_concurrently():
    """Several fans' bursts are in flight at once, and one fan's escape does not
    kill the others.

    The concurrency proof is the ORDER of the recorded holds: the first three
    entries are three start jitters, which can only happen if three tasks were
    running before any of them finished its jitter. Serially the first three
    entries would be fan one's jitter and then fan one's holds. Per-fan state is
    checked afterwards: each welcomed fan rested, and every lease was handed
    back."""
    aid = "acc_w_pace_conc"
    await _seed_account(aid)
    await _seed_brain(aid)
    fans = [47301, 47302, 47303, 47304]
    fake = _use_fake([_sub(f, name=n) for f, n in
                      zip(fans, ("Ada", "Ben", "Cal", "Dee"))])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    # One fan blows up on the very first await of his task — before his lease is
    # taken, so nothing leaks — and must be counted without touching the rest.
    real_cooldown = ax.fan_on_cooldown
    async def _explode(account_id, fan_id, **kw):
        if int(fan_id) == 47304:
            raise RuntimeError("boom on the cooldown read")
        return await real_cooldown(account_id, fan_id, **kw)
    ax.fan_on_cooldown = _explode  # type: ignore[assignment]

    async with recording_holds() as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True})
        ax.fan_on_cooldown = real_cooldown  # type: ignore[assignment]

    assert res["welcomes_sent"] == 3, res
    assert res["errors"] == 1, f"the raising fan must be counted, not swallowed: {res}"
    assert res["run_wall_s"] >= 0.0, res
    # Three fans' start jitters land before any fan's first hold.
    first_three = [h.get("jitter") for h in holds[:3]]
    assert first_three == [True, True, True], f"the bursts ran serially: {holds[:3]}"
    # Every fan still got his own lease + rest, and the lease was handed back.
    async with get_session() as s:
        ws = {r[0] for r in (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()}
        assert ws == {47301, 47302, 47303}, ws
        for f in fans:
            assert await s.get(FanLease, (aid, f)) is None, f"lease leaked for {f}"
    for f in (47301, 47302, 47303):
        assert await ax.fan_on_cooldown(aid, f) is True, f"{f} did not rest"


async def case_human_pace_wall_budget_defers_and_the_next_run_reserves():
    """The wall budget is ADMISSION control, and a deferred fan is not a lost fan.

    A fake monotonic clock is advanced by every hold, so "the budget ran out" is
    deterministic rather than a race with the test runner. Concurrency is pinned
    to 1 so the boundary is observable: fan one is admitted and finishes, fan two
    is never started. He carries no `welcome_sent` claim, so the very next run —
    over the SAME notifications feed, which still serves him — welcomes him."""
    aid = "acc_w_pace_budget"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(47401, name="Ada"), _sub(47402, name="Ben")])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    class _Clock:
        def __init__(self): self.t = 0.0
        def monotonic(self): return self.t
    clock = _Clock()

    calls: list[dict] = []
    async def _rec(account_id, fan_id, seconds, **kw):
        calls.append({"fan_id": int(fan_id), "seconds": float(seconds)})
        clock.t += 200.0     # every hold burns 200 virtual seconds
        await asyncio.sleep(0)

    real_time = send_welcome.time
    real_conc = send_welcome._PACE_CONCURRENCY
    real_warn = send_welcome._HOLD_OVERRUN_WARN_S
    send_welcome.time = clock            # type: ignore[assignment]
    send_welcome._PACE_CONCURRENCY = 1   # type: ignore[assignment]
    send_welcome._HOLD_OVERRUN_WARN_S = 1e9  # the fake clock would WARN on every hold
    send_welcome.hold_with_typing = _rec  # type: ignore[assignment]
    _run_pool._sleep = _no_jitter  # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True})
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]
        send_welcome.time = real_time               # type: ignore[assignment]
        send_welcome._PACE_CONCURRENCY = real_conc  # type: ignore[assignment]
        send_welcome._HOLD_OVERRUN_WARN_S = real_warn  # type: ignore[assignment]

    assert res["new_subscribers"] == 2, res
    assert res["welcomes_sent"] == 1, res           # fan one finished his burst
    assert res["deferred_budget"] == 1, res         # fan two was never admitted
    assert res["run_wall_s"] > send_welcome._RUN_WALL_BUDGET_S, res
    # The instrumentation saw the (fake) overrun rather than reporting zero.
    assert res["hold_overrun_max_s"] > 0.0, res
    assert {c["fan_id"] for c in calls} == {47401}, calls
    async with get_session() as s:
        ws = {r[0] for r in (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()}
        assert ws == {47401}, ws
        assert await s.get(FanLease, (aid, 47402)) is None, "no lease for a deferred fan"

    # The next tick re-serves him off the same feed and welcomes him.
    async with recording_holds() as holds2:
        res2 = await run_once(aid, "send_welcome",
                              payload={"with_image": False,
                                       "human_pace": True})
    assert res2["new_subscribers"] == 1 and res2["welcomes_sent"] == 1, res2
    assert res2["deferred_budget"] == 0, res2
    assert {h["fan_id"] for h in holds2 if not h.get("jitter")} == {47402}, holds2
    async with get_session() as s:
        ws2 = {r[0] for r in (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()}
        assert ws2 == {47401, 47402}, ws2


# ── stop_on_reply: she stops when he speaks, and hands the turn back ─────
#
# Two rules decide every case below, and they are NOT the same rule:
#
#   WHEN the burst stops — at a phase boundary. Quiet phases and the GIF beat are
#   interruptible; a typing phase is not (she finishes the bubble she started).
#   WHOSE TURN it is afterwards — decided by the two ROWS, his newest worded
#   inbound against the last bubble of ours that landed. His is newer ⇒ the
#   engines pick him up on their own cadence. OURS is newer ⇒ a finishing bubble
#   ate his reply and the turn is handed back with an explicit job.
#
# ⚠️ `FakeOF.send_message` stamps EVERY send `2026-06-04T12:00:00+00:00`, so these
# cases express "his reply is older than the bubble that ate it" by dating the
# injected row just BEFORE that instant — not by sleeping. Same fixed clock, no
# flake, and the classification is exercised in both directions.
_OF_SEND_STAMP = datetime(2026, 6, 4, 12, 0, 0)


async def _inject_inbound(aid: str, fan_id: int, body: str, *, mid: int,
                          at: datetime, is_tip: bool = False) -> None:
    """Write one inbound `messages` row mid-burst — what the WS pump would do."""
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=mid,
                      direction="in", body=body, is_tip=is_tip, created_at=at))


async def _welcome_rule(aid: str, kind: str, *, enabled: bool = True) -> None:
    """An automation_rules row — how `_handoff_engine` learns an engine is live."""
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name=kind, kind=kind,
                             trigger_json=json.dumps({"every_seconds": 300}),
                             steps_json="{}", is_enabled=enabled))


async def _jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid)
        )).scalars().all())


async def case_stop_on_reply_quiet_phase_drops_the_bubble():
    """D1(a): he answers while the bar is DARK → that bubble is never sent, and
    nobody is asked to hand the turn back.

    The reply lands during bubble 1's quiet phase — before she has typed a
    character, which is exactly what the fan can observe (no indicator) — so
    stopping there is honest rather than a claim about our internal state. And
    because his row is then the newest thing on the thread, the turn is already
    his: both engines will pick him up on their own cadence once the welcome rest
    expires, so enqueueing anything would be a second voice, not a rescue."""
    aid = "acc_w_sor_quiet"
    fid = 48001
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")   # an engine IS available
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    # TWO coordinates, and both are load-bearing: `len(fake.sent) == 1` picks the
    # BUBBLE (the greeting is out, bubble 1 is not), and `seen["n"]` picks the
    # PHASE inside it. `seen` really is a hold-call ordinal — it is scoped to one
    # bubble's holds, which is the only reason a think-gap or a drift-free draw
    # elsewhere in the burst cannot move the target. `== 1` is the split's FIRST
    # call: the dark lead-in, before she has typed a character.
    seen = {"n": 0}
    async def _inject(n, entry):
        if len(fake.sent) != 1:
            return
        seen["n"] += 1
        if seen["n"] == 1:
            await _inject_inbound(aid, fid, "omg hey!! 😍", mid=770001,
                                  at=_OF_SEND_STAMP + timedelta(seconds=40))

    async with recording_holds(on_call=_inject) as holds:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "human_pace": True, "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    assert res["stop_on_reply"] is True, res
    # ONLY the greeting shipped: bubble 1 was never sent, and neither the question
    # nor the GIF rode after it.
    assert len(fake.sent) == 1, fake.sent
    assert fake.gifs == [], fake.gifs
    # The split really happened, and the burst stopped ON the phase boundary:
    # start-jitter, the greeting's hold, then bubble 1's quiet — and no fourth
    # hold, because the typing half of that split never ran.
    assert len(holds) == 3, holds
    quiet_first = holds[-1]
    assert quiet_first["fan_id"] == fid, quiet_first
    assert quiet_first["typing_indicator"] is False, quiet_first
    assert 10.0 <= quiet_first["seconds"] <= 25.0, quiet_first
    assert quiet_first["quiet_s"] == 0.0, \
        ("the quiet half is passed as a plain dark hold", quiet_first)
    # He IS welcomed (early claim), and nothing was handed off.
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, fid)) is not None, "welcomed"
    assert res["handoff_enqueued"] == 0 and res["handoff_no_engine"] == 0, res
    assert await _jobs(aid) == [], "the turn is HIS — no job"


async def case_stop_on_reply_typing_phase_finishes_then_hands_the_turn_back():
    """D1(b): he answers while she is TYPING → she finishes that bubble, and the
    turn is handed back explicitly.

    This is the case the whole handoff exists for. The finishing bubble lands on
    top of his reply and moves `last_dir` to "out", and BOTH engines gate their
    candidates on the fan having spoken last — so without a job nothing answers
    him until he double-texts. One job, for the engine that owns brand-new subs,
    due past our own 150s rest (both engines check `fan_on_cooldown`), carrying
    the three keys that scope it, force it, and open the turn gate."""
    aid = "acc_w_sor_typing"
    fid = 48101
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    # Same two coordinates as the quiet-phase case above, one ordinal along:
    # `seen["n"] == 2` is bubble 1's SECOND hold — the split's typing phase, past
    # the checkpoint, so the bubble finishes and ships. Dated 10s before the
    # stamp FakeOF puts on every send, so the bubble that follows it is provably
    # newer: that ordering is the whole classification.
    seen = {"n": 0}
    async def _inject(n, entry):
        if len(fake.sent) != 1:
            return
        seen["n"] += 1
        if seen["n"] == 2:
            await _inject_inbound(aid, fid, "hey gorgeous what u up to",
                                  mid=770101,
                                  at=_OF_SEND_STAMP - timedelta(seconds=10))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "human_pace": True, "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    # She FINISHED the bubble she was typing; the question and the GIF did not go.
    assert len(fake.sent) == 2, fake.sent
    assert fake.gifs == [], fake.gifs
    assert res["handoff_enqueued"] == 1 and res["handoff_no_engine"] == 0, res

    jobs = await _jobs(aid)
    assert len(jobs) == 1, [(j.kind, j.payload_json) for j in jobs]
    job = jobs[0]
    assert job.kind == "welcome_chatter_for_info", job.kind
    assert job.status == "pending", job.status
    # The WHOLE payload, key for key — this dict is the contract the two engines'
    # own handoff cases build by hand, and an extra key here would be a force
    # nobody reviewed.
    assert json.loads(job.payload_json) == {
        "only_fan_ids": [fid], "force_ids": [fid], "turn_handoff_ids": [fid],
    }, job.payload_json
    # Due AFTER the welcome rest, or the engines' own cooldown check eats it.
    due_in = (job.run_at - datetime.utcnow()).total_seconds()
    assert 150.0 < due_in <= 166.0, (due_in, job.run_at)


async def case_stop_on_reply_the_LAST_bubble_hands_the_turn_back_too():
    """The tail checkpoint (§C2.4) — the same blocker §C3 exists to fix, at the
    one place the in-loop checks structurally cannot reach.

    Every checkpoint in the burst loop runs BEFORE a send. None runs after the
    LAST one. So on the SHIPPED DEFAULT SHAPE — no `gif_id`, i.e. plan =
    [greeting, activity, question] — a reply that arrives while she is typing the
    QUESTION is seen by nobody: the question lands on top of it, the loop runs
    out, and without a tail check the burst reports a clean finish. His
    `last_dir` is then "out" and BOTH engines gate their candidates on the fan
    having spoken last, so nothing answers him until he double-texts.

    It is also the invisible version of the bug: the burst was never cut short,
    so `aborted_on_reply` stays 0 and the run looks perfect. That is why this
    case asserts the JOB, not a counter.

    Driven with `human_pace` off AND on. The paced (account, fan) pair is chosen
    so bubble 2's drift does not fire (asserted below via the hold count), which
    keeps its hold UNSPLIT — otherwise the split's own checkpoint would catch the
    reply and this case would silently stop testing the tail."""
    for paced, aid, fid in ((False, "acc_w_sor_tail", 48151),
                            (True, "acc_w_sor_tail_paced", 48151)):
        await _seed_account(aid)
        await _seed_brain(aid)
        await _welcome_rule(aid, "welcome_chatter_for_info")
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        # Two bubbles are out ⇒ this hold is the QUESTION's, the last of the
        # burst. Dated 10s before the stamp FakeOF puts on every send, so the
        # bubble that follows it is provably newer — which is the whole
        # classification: our row on top of his ⇒ hand the turn back.
        async def _inject(n, entry, _aid=aid, _fid=fid, _fake=fake):
            if len(_fake.sent) == 2:
                await _inject_inbound(_aid, _fid, "wait are you real??",
                                      mid=770400 + _fid % 100,
                                      at=_OF_SEND_STAMP - timedelta(seconds=10))

        async with recording_holds(on_call=_inject) as holds:
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": True,
                                          "human_pace": paced,
                                          "stop_on_reply": True,
                                          "question": "what's yours?"})

        # The whole burst shipped — she finished the question she was typing.
        assert res["welcomes_sent"] == 1, (paced, res)
        assert len(fake.sent) == 3, (paced, fake.sent)
        # ...so nothing was ABORTED. The counter staying 0 is the point: this
        # failure mode is invisible in the stats, and the job is the only proof.
        assert res["aborted_on_reply"] == 0, (paced, res)
        # Unpaced: one hold per bubble. Paced: start-jitter + bubble 0 + bubble
        # 1's SPLIT (two calls) + bubble 2 unsplit = 5. A sixth call would mean
        # bubble 2 split after all and the split's checkpoint, not the tail, is
        # what caught the reply.
        assert len(holds) == (5 if paced else 3), (paced, holds)

        assert res["handoff_enqueued"] == 1, (paced, res)
        assert res["handoff_no_engine"] == 0, (paced, res)
        jobs = await _jobs(aid)
        assert len(jobs) == 1, (paced, [(j.kind, j.payload_json) for j in jobs])
        assert jobs[0].kind == "welcome_chatter_for_info", (paced, jobs[0].kind)
        assert json.loads(jobs[0].payload_json) == {
            "only_fan_ids": [fid], "force_ids": [fid], "turn_handoff_ids": [fid],
        }, (paced, jobs[0].payload_json)
        due_in = (jobs[0].run_at - datetime.utcnow()).total_seconds()
        assert 150.0 < due_in <= 166.0, (paced, due_in)


async def case_stop_on_reply_a_finished_burst_he_never_answered_hands_off_nothing():
    """The tail check's OTHER half: it must stay silent when he said nothing.

    The default shape now reads the messages table once more after the last
    bubble, and the one thing that read must never do is invent a turn to hand
    over. No reply ⇒ no job, no counter, and the fan is left to the engines'
    ordinary cadence exactly as he is today."""
    aid = "acc_w_sor_tail_quiet"
    fid = 48161
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    # A pre-burst inbound, so the tail check has a row to find and the ANCHOR is
    # the only thing stopping it being read as a reply.
    await _inject_inbound(aid, fid, "hey just subbed", mid=770501,
                          at=_OF_SEND_STAMP - timedelta(minutes=5))

    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?"})

    assert res["welcomes_sent"] == 1 and len(fake.sent) == 3, (res, fake.sent)
    assert res["aborted_on_reply"] == 0, res
    assert res["handoff_enqueued"] == 0 and res["handoff_no_engine"] == 0, res
    assert await _jobs(aid) == [], "he never replied — nothing to hand over"


async def case_stop_on_reply_an_unstamped_send_hands_the_turn_back():
    """When OF does not tell us WHEN our bubble landed, we do not guess.

    The classification is one comparison — his row against ours — and it is only
    honest while both sides are OF's own numbers. His always is (the WS pump
    writes it from OF's payload). Ours is not, whenever the send answers 200 with
    a body we cannot read: `createdAt` missing leaves our WALL CLOCK on one side
    of a comparison with OF's, and a missing id used to be filled in as `0`,
    which loses every same-second tie to a real BigInteger message id. Both
    fabrications pointed the same way — "his turn" — so an id-less send silently
    declined the handoff and the fan was answered by nobody.

    A handoff we did not need costs at most one reply he was getting anyway; a
    handoff we needed and skipped costs him every reply until he double-texts.
    So an unreadable send hands the turn back."""
    aid = "acc_w_sor_unstamped"
    fid = 48601
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    # OF answers 200 with a body carrying NEITHER an id nor a createdAt. Real:
    # the wrapper has served `{"success": true}` shapes.
    def _blind_send(chat_id, text, *, media_files=None, **kw):
        fake.sent.append((int(chat_id), text, list(media_files or [])))
        return {"success": True}
    fake.send_message = _blind_send  # type: ignore[assignment]

    # He replies during bubble 1's hold, dated LATER than any bubble could be —
    # so under a timestamp comparison this is unambiguously "his turn". The
    # point is that no comparison may happen at all: our own row is unreadable.
    async def _inject(n, entry):
        if len(fake.sent) == 1:
            await _inject_inbound(aid, fid, "omg hi!!", mid=770601,
                                  at=_OF_SEND_STAMP + timedelta(hours=1))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 1, res
    assert res["handoff_enqueued"] == 1, ("an unreadable send may not be read as "
                                          "'his turn'", res)
    jobs = await _jobs(aid)
    assert len(jobs) == 1 and jobs[0].kind == "welcome_chatter_for_info", jobs


async def case_stop_on_reply_suppresses_the_gif_paced_and_unpaced():
    """The GIF is always suppressed on a detected reply, with `human_pace` on AND
    off. It has no typing phase to finish — she picked it, she did not write it —
    so there is no "she was mid-sentence" to honour, and an animation landing on
    top of a fan's message is the exact tell this feature exists to remove.

    The check runs AFTER the GIF's own beat so those seconds still count as
    interruptible time; injecting DURING that beat is what proves it."""
    for paced in (True, False):
        aid = f"acc_w_sor_gif_{'on' if paced else 'off'}"
        fid = 48201 if paced else 48202
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        # Three text bubbles are already out ⇒ this hold is the GIF's beat.
        async def _inject(n, entry, _aid=aid, _fid=fid, _fake=fake):
            if len(_fake.sent) == 3:
                await _inject_inbound(_aid, _fid, "haha hi", mid=770200 + _fid % 10,
                                      at=_OF_SEND_STAMP + timedelta(seconds=90))

        async with recording_holds(on_call=_inject):
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": True,
                                          "human_pace": paced,
                                          "stop_on_reply": True,
                                          "question": "what's yours?",
                                          "gif_id": "l0MYt5jPR6QX5pnqM"})

        assert res["welcomes_sent"] == 1, (paced, res)
        assert res["aborted_on_reply"] == 1, (paced, res)
        assert len(fake.sent) == 3, (paced, fake.sent)
        assert fake.gifs == [], (paced, fake.gifs)
        assert res["gifs_sent"] == 0, (paced, res)


async def case_stop_on_reply_anchor_is_a_snapshot_not_any_inbound_ever():
    """The anchor is a ROW taken at the top of his task, not "has he ever spoken".

    A brand-new sub who fired off a message BEFORE his welcome was composed is
    the common case (he subscribes and says hi in the same minute), and he must
    still get the whole burst — that is today's behaviour and the knob may only
    ever remove bubbles a fan interrupted."""
    aid = "acc_w_sor_anchor"
    fid = 48301
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    await _inject_inbound(aid, fid, "hi just subbed!", mid=770301,
                          at=_OF_SEND_STAMP - timedelta(minutes=5))

    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 0, res
    assert len(fake.sent) == 4, fake.sent
    assert len(fake.gifs) == 1, fake.gifs
    assert res["reply_guard_off"] == 0, ("the guard really ran for him", res)
    assert await _jobs(aid) == [], "no reply arrived DURING the burst"


async def case_stop_on_reply_words_decide_not_the_message_type():
    """§C4, the operator's own rule: *"dont stop on single tip only on text"*.

    WORDS decide, so `is_tip` is not the discriminator and the four shapes split
    two-and-two:

      text                → stops. The literal ask.
      tip WITH a note     → stops. The note is words addressed at her.
      BARE tip (ledger)   → does not. Applause, not a turn — and those rows are
                            written by a 5-minute poll, so they arrive late.
      media, NO caption   → does not. "only on text" admits no wordless message.

    Each shape is injected during bubble 1's hold, so an abort truncates the burst
    at 2 bubbles and a non-abort lets all 4 ride: the send count IS the verdict."""
    async def _burst(fid: int, body: str, *, is_tip: bool) -> tuple[dict, FakeOF]:
        aid = f"acc_w_sor_words_{fid}"
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]

        async def _inject(n, entry):
            if len(fake.sent) == 1 and n == 2:
                # Dated AFTER every bubble, so an abort here is unambiguously
                # "his turn" and no handoff noise enters this case.
                await _inject_inbound(aid, fid, body, mid=770400 + fid % 100,
                                      at=_OF_SEND_STAMP + timedelta(seconds=30),
                                      is_tip=is_tip)

        async with recording_holds(on_call=_inject):
            res = await run_once(aid, "send_welcome",
                                 payload={"with_image": True,
                                          "stop_on_reply": True,
                                          "question": "what's yours?",
                                          "gif_id": "l0MYt5jPR6QX5pnqM"})
        return res, fake

    res, fake = await _burst(48401, "hey you 🙈", is_tip=False)
    assert res["aborted_on_reply"] == 1 and len(fake.sent) == 2, (res, fake.sent)

    res, fake = await _burst(48402, "buy something nice babe", is_tip=True)
    assert res["aborted_on_reply"] == 1 and len(fake.sent) == 2, (res, fake.sent)

    # Built by the module that WRITES these rows, not retyped: a test carrying its
    # own copy of the string is exactly how a cosmetic edit in transaction_ingest
    # would ship "every bare tip aborts the burst" with this case still green.
    res, fake = await _burst(48403, tip_ledger_body(500), is_tip=True)
    assert res["aborted_on_reply"] == 0, ("a bare tip is applause, not a turn", res)
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent

    res, fake = await _burst(48404, "", is_tip=False)
    assert res["aborted_on_reply"] == 0, ("a wordless photo is not text", res)
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent


async def case_stop_on_reply_query_failure_finishes_the_burst():
    """The added query may only ever REMOVE bubbles — so when it raises, the
    welcome finishes. Both reads are covered, because they fail differently:

      the ANCHOR    → the knob is switched off for that fan. A None anchor would
                      mean "he had said nothing", and every pre-existing message
                      would then read as a brand-new reply and abort the burst on
                      the strength of a broken query.
      a CHECKPOINT  → reads as "no reply seen" and the burst carries on.
    """
    real = welcome_turn.newest_worded_inbound

    # 1. The anchor itself is unreadable.
    aid = "acc_w_sor_qfail_anchor"
    fid = 48501
    await _seed_account(aid)
    await _seed_brain(aid)
    await _inject_inbound(aid, fid, "hi from before the welcome", mid=770501,
                          at=_OF_SEND_STAMP - timedelta(minutes=9))
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    async def _always_raises(account_id, fan_id):
        raise RuntimeError("database is locked")
    welcome_turn.newest_worded_inbound = _always_raises  # type: ignore[assignment]
    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})
        welcome_turn.newest_worded_inbound = real  # type: ignore[assignment]
    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 0, res
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent
    # ...and the run SAYS the guard never ran for him. `stop_on_reply: true`
    # beside `aborted_on_reply: 0` otherwise reads as "nobody replied", which is
    # the one thing it does not mean here.
    assert res["stop_on_reply"] is True and res["reply_guard_off"] == 1, res

    # 2. The anchor reads fine; every CHECKPOINT after it blows up.
    aid = "acc_w_sor_qfail_check"
    fid = 48502
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    llm_client.chat = _boom  # type: ignore[attr-defined]
    n = {"calls": 0}
    async def _raises_after_the_anchor(account_id, fan_id):
        n["calls"] += 1
        if n["calls"] == 1:
            return await real(account_id, fan_id)
        raise RuntimeError("database is locked")
    welcome_turn.newest_worded_inbound = _raises_after_the_anchor  # type: ignore[assignment]
    async with recording_holds():
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})
        welcome_turn.newest_worded_inbound = real  # type: ignore[assignment]
    assert n["calls"] > 1, "the checkpoints must actually have run"
    assert res["welcomes_sent"] == 1 and res["aborted_on_reply"] == 0, res
    assert len(fake.sent) == 4 and len(fake.gifs) == 1, fake.sent


async def case_stop_on_reply_handoff_engine_precedence():
    """Who gets handed the turn, and what happens when nobody can take it.

    `welcome_chatter_for_info` owns brand-new subs, so the gatherer takes the turn
    whenever it is enabled. With it off there is nothing to hand it to, which is
    counted rather than logged into the dark: nothing would have answered him
    today either. A leftover config blob of the retired chat engine changes
    nothing."""
    async def _abort_and_read_stats(aid: str, fid: int) -> dict:
        fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]
        async def _inject(n, entry):
            if len(fake.sent) == 1 and n == 2:
                # Older than the bubbles ⇒ ours landed on top ⇒ handoff.
                await _inject_inbound(aid, fid, "hey!!", mid=770600 + fid % 100,
                                      at=_OF_SEND_STAMP - timedelta(seconds=20))
        async with recording_holds(on_call=_inject):
            return await run_once(aid, "send_welcome",
                                  payload={"with_image": True,
                                           "stop_on_reply": True,
                                           "question": "what's yours?"})

    # (a) no engine at all.
    aid = "acc_w_sor_engine_none"
    await _seed_account(aid)
    await _seed_brain(aid)
    res = await _abort_and_read_stats(aid, 48601)
    assert res["aborted_on_reply"] == 1, res
    assert res["handoff_no_engine"] == 1 and res["handoff_enqueued"] == 0, res
    assert await _jobs(aid) == [], "nothing to enqueue TO"

    # (b) the gatherer is enabled → it gets the turn.
    aid = "acc_w_sor_engine_wcfi"
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    res = await _abort_and_read_stats(aid, 48602)
    assert res["handoff_enqueued"] == 1, res
    assert [j.kind for j in await _jobs(aid)] == ["welcome_chatter_for_info"], \
        await _jobs(aid)

    # (c) a full brain row next to a disabled gatherer rule → still nobody to
    #     hand the turn to.
    aid = "acc_w_sor_engine_aic"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Vancouver Island, Canada",
            time_activities_json=json.dumps(
                {k: f"doing {k} things" for k in
                 ("morning_1", "morning_2", "afternoon_1", "afternoon_2",
                  "evening", "night")})))
    await _welcome_rule(aid, "welcome_chatter_for_info", enabled=False)
    res = await _abort_and_read_stats(aid, 48603)
    assert res["handoff_no_engine"] == 1 and res["handoff_enqueued"] == 0, res
    assert await _jobs(aid) == [], await _jobs(aid)


async def case_stop_on_reply_handoff_job_actually_gets_him_answered():
    """🔴 THE WHOLE PROMISE, both halves, one test.

    `stop_on_reply` says "she stops talking over you, and you get answered". The
    engine suites prove a handoff PAYLOAD is answered; the case above proves the
    right payload is WRITTEN. Neither on its own catches the two drifting apart —
    a renamed key here is a job the engines silently skip as `not_turn`, and
    every test still passes.

    So this one runs the abort, reads the row the sender actually queued, and
    feeds THAT payload straight into the real `welcome_chatter_for_info.run`.
    Nothing is retyped; the only clock the test fast-forwards is the welcome
    rest, which is exactly what the job's `run_at` waits out."""
    aid = "acc_w_sor_e2e"
    fid = 48901
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")
    fake = _use_fake([_sub(fid, name="Sofie")], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async def _inject(n, entry):
        if len(fake.sent) == 1 and n == 2:
            # He writes while she is typing bubble 1 — so she finishes it, and it
            # lands on top of him (older than FakeOF's send stamp).
            await _inject_inbound(aid, fid, "hey! whats your name",
                                  mid=770901,
                                  at=_OF_SEND_STAMP - timedelta(seconds=15))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "question": "what's yours?",
                                      "gif_id": "l0MYt5jPR6QX5pnqM"})

    assert res["aborted_on_reply"] == 1 and res["handoff_enqueued"] == 1, res
    welcome_sends = len(fake.sent)
    assert welcome_sends == 2 and fake.gifs == [], fake.sent

    jobs = await _jobs(aid)
    assert len(jobs) == 1, jobs
    job_payload = json.loads(jobs[0].payload_json)

    # The job is due PAST the 150s welcome rest, and the rest is `fans
    # .automation_paused_until`. Let it lapse, exactly as the wait would.
    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        fan.automation_paused_until = None
    _patch_llm("aww hey! im Sofie 😊 whats yours")

    res2 = await run_once(aid, jobs[0].kind, payload=job_payload)
    assert res2["status"] == "ok", res2
    assert res2["turn_handoffs"] == 1, res2
    assert res2["replies_sent"] == 1, res2
    assert len(fake.sent) > welcome_sends, ("he was answered on the wire",
                                            fake.sent)

    async with get_session() as s:
        rows = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.fan_id == fid,
                                  Message.direction == "out",
                                  Message.automation_kind == "welcome_chatter_for_info")
        )).scalars().all()
        assert rows and all(r.body for r in rows), ("a real reply row", rows)


async def case_stop_on_reply_handoff_belts_a_restricted_fan():
    """The handoff job carries `force_ids`, and force bypasses the chat engine's
    skip-list gate — so a fan somebody hand-restricted could be answered BY the
    rescue that was meant to stop him being ignored. The belt is a re-check of
    `load_hard_skip_ids` at the enqueue site.

    Reached here through `test_fan`, which is exactly the hole: the run's own
    hard-skip filter only guards the NOTIFICATION path, so a forced send walks
    past it and the enqueue site is the last place the restriction can bind."""
    aid = "acc_w_sor_belt"
    fid = 48801
    await _seed_account(aid)
    await _seed_brain(aid)
    await _welcome_rule(aid, "welcome_chatter_for_info")   # an engine IS available
    async with get_session() as s:
        s.add(SkipList(account_id=aid, fan_id=fid, reason="manual_restrict"))
    fake = _use_fake([], vault=True)
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    async def _inject(n, entry):
        if len(fake.sent) == 1 and n == 2:
            # Older than the bubbles ⇒ ours landed on top ⇒ this WOULD hand off.
            await _inject_inbound(aid, fid, "hey!!", mid=770801,
                                  at=_OF_SEND_STAMP - timedelta(seconds=20))

    async with recording_holds(on_call=_inject):
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": True,
                                      "stop_on_reply": True,
                                      "test_fan": fid, "test_name": "Sofie",
                                      "question": "what's yours?"})

    assert res["aborted_on_reply"] == 1, res
    assert res["handoff_skipped_restricted"] == 1, res
    assert res["handoff_enqueued"] == 0 and res["handoff_no_engine"] == 0, res
    assert await _jobs(aid) == [], "a restricted fan gets no forced turn"


async def case_stop_on_reply_claims_the_welcome_before_the_burst_can_die():
    """§C5 — the claim moves to the moment the greeting lands.

    A burst that may now stop early (or run for minutes) can die between bubble 0
    and the end of the loop, and the old placement wrote `welcome_sent` only after
    the loop. The next tick would then open with a SECOND greeting — the loudest
    possible bot tell, delivered by the anti-bot-tell feature. With either knob
    on, the claim is made as soon as the greeting is on the wire; with both off,
    the placement is exactly today's, which the same injected crash proves."""
    async def _crash_after_the_greeting(aid: str, fid: int, payload: dict) -> dict:
        await _seed_account(aid)
        await _seed_brain(aid)
        _use_fake([_sub(fid, name="Sofie")], vault=True)
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]
        calls = {"n": 0}
        async def _die(account_id, fan_id, seconds, **kw):
            calls["n"] += 1
            # The greeting's own hold(s) pass; the first hold AFTER it lands is
            # where the process "falls over".
            if calls["n"] > 1 and len(_fake_sent()) >= 1:
                raise RuntimeError("worker died mid-burst")
        def _fake_sent():
            return ax._make_client(aid).sent
        send_welcome.hold_with_typing = _die  # type: ignore[assignment]
        try:
            return await run_once(aid, "send_welcome",
                                  payload={"with_image": True,
                                           "question": "what's yours?", **payload})
        finally:
            send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]

    # With the knob on: the greeting landed, so he is welcomed and STAYS welcomed.
    aid = "acc_w_sor_earlymark_on"
    res = await _crash_after_the_greeting(aid, 48701, {"stop_on_reply": True})
    assert res["status"] == "error", res
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 48701)) is not None, \
            "the greeting landed — he must never be greeted twice"

    # Flags off: today's placement, unchanged. The claim is written after the
    # loop, so the same crash leaves him unclaimed and the next tick re-welcomes.
    aid = "acc_w_sor_earlymark_off"
    res = await _crash_after_the_greeting(aid, 48702, {})
    assert res["status"] == "error", res
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 48702)) is None, \
            "flags off must keep today's post-loop claim"


# ── skip_time_bubble: bubble 2 is DROPPED, not reworded ──────────────────

async def case_skip_time_bubble_drops_bubble_two_entirely():
    """`skip_time_bubble` removes bubble 2 rather than changing what it says.

    Four properties, each with its own failure mode: the activity/clock line is
    GONE (not shortened), the operator's question still ships verbatim right
    after the greeting, no LLM call is made, and the GIF still rides at the end."""
    aid = "acc_w_skipbubble"
    await _seed_account(aid)
    await _seed_brain(aid)          # every slot HAS an activity, so there is
    fake = _use_fake([_sub(46001, name="Sofie")])   # something real to drop
    calls = {"n": 0}
    async def _counting(**kw):
        calls["n"] += 1
        return SimpleNamespace(content="a line nobody should see")
    llm_client.chat = _counting  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "skip_time_bubble": True,
                                  "question": "what's yours?",
                                  "gif_id": "l0MYt5jPR6QX5pnqM"})
    assert res["welcomes_sent"] == 1, res
    assert calls["n"] == 0, f"the skipped bubble still cost {calls['n']} LLM call(s)"
    assert len(fake.sent) == 3, fake.sent          # greeting, question, GIF
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1] == "what's yours?", fake.sent[1]
    assert fake.sent[2][1] == "" and fake.gifs, fake.sent
    assert all("doing " not in t and not t.startswith("it's ")
               for _, t, _ in fake.sent), fake.sent


async def case_skip_time_bubble_outranks_time_only_and_a_pin():
    """Precedence: skip_time_bubble > time_only > pin > normal.

    A pin is a stored ACTIVITY line and `time_only` only rewords bubble 2, so
    neither can put back a bubble that has been removed. Both are set here at
    once, on every slot, so the assertion cannot pass by wall-clock luck."""
    aid = "acc_w_skip_pin"
    await _seed_account(aid)
    await _seed_brain(aid)
    line = "beach day vibes, come say hi"
    await _seed_pin(aid, {k: {"line": line, "weekday": "Monday"}
                          for k in welcome_compose._SLOT_KEYS})
    fake = _use_fake([_sub(46101, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("a dropped bubble must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "time_only": True,
                                  "skip_time_bubble": True,
                                  "question": "what's yours?"})
    assert res["welcomes_sent"] == 1 and res["pinned_used"] == 0, res
    assert [t for _, t, _ in fake.sent] == ["Hey S-S-S-Sexy Sofie ! !!",
                                            "what's yours?"], fake.sent

    # Untick it and the SAME account + SAME pin ships the pinned line again — the
    # knob removes a bubble, it never destroys what would have filled it.
    fake.sent.clear()
    res2 = await run_once(aid, "send_welcome",
                          payload={"with_image": False, "question": "what's yours?",
                                   "test_fan": 46102, "test_name": "Mia"})
    assert res2["welcomes_sent"] == 1 and res2["pinned_used"] == 1, res2
    assert [t for _, t, _ in fake.sent] == ["Hey M-M-M-Mighty Mia ! !!", line,
                                            "what's yours?"], fake.sent


async def case_skip_time_bubble_absent_composes_todays_bubbles():
    """THE ADD-ON GATE for step 1: a rule that never heard of the key composes
    byte-identically to today.

    Asserted as an equality between two real runs on twin accounts — one with the
    key absent, one with it explicitly false — and against the literal three-bubble
    shape this sender has always sent, so "identical to itself" cannot pass while
    both drifted."""
    shapes: list[list[str]] = []
    for i, extra in enumerate(({}, {"skip_time_bubble": False})):
        aid = f"acc_w_skip_off{i}"
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(46201 + i, name="Sofie")])
        async def _boom(**kw):
            raise AssertionError("the welcome must NOT call the LLM")
        llm_client.chat = _boom  # type: ignore[attr-defined]
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "question": "what's yours?", **extra})
        assert res["welcomes_sent"] == 1, res
        shapes.append([t for _, t, _ in fake.sent])
    assert shapes[0] == shapes[1], shapes
    assert len(shapes[0]) == 3, shapes[0]
    assert shapes[0][0] == "Hey S-S-S-Sexy Sofie ! !!", shapes[0]
    assert shapes[0][1].startswith("doing "), shapes[0]
    assert shapes[0][2] == "what's yours?", shapes[0]


async def case_extract_filters_non_subscribe_notifications():
    """OF dropped the type= filter, so the feed is mixed. _extract_new_subscribers
    must keep only subscribe-type items (and untyped ones for back-compat),
    dropping tips/comments/mentions."""
    feed = {"list": [
        {"type": "subscribed", "subType": "new_subscriber", "user": {"id": 111, "name": "Sub One"}},
        {"type": "tip",        "user": {"id": 222, "name": "Tipper"}},
        {"type": "comment",    "user": {"id": 333, "name": "Commenter"}},
        {"type": "subscribed", "subType": "returning_subscriber", "user": {"id": 444, "name": "Sub Two"}},
        {"user": {"id": 555, "name": "Untyped"}},  # no type → kept (back-compat)
    ]}
    got = {s["id"] for s in send_welcome._extract_new_subscribers(feed)}
    assert got == {111, 444, 555}, got  # tip/comment dropped


async def case_gif_ships_as_fourth_bubble():
    """The rule's `gif_id` knob rides as bubble 4 — its OWN send, after the
    question. Three properties: it lands LAST, it goes out as a top-level giphyId
    beside EMPTY text (the wire shape OF requires — text and giphyId are siblings,
    not a captioned GIF), and it does not disturb the three text bubbles."""
    aid = "acc_w_gif"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45001, name="Sofie")])
    async def _boom(**kw):
        raise AssertionError("a picked GIF must never reach the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": "what's yours?",
                                  "gif_id": "l0MYt5jPR6QX5pnqM"})
    assert res["welcomes_sent"] == 1, res
    assert res["gifs_sent"] == 1, res
    assert len(fake.sent) == 4, fake.sent
    assert fake.sent[0][1] == "Hey S-S-S-Sexy Sofie ! !!", fake.sent[0]
    assert fake.sent[1][1].startswith("doing "), fake.sent[1]
    assert fake.sent[2][1] == "what's yours?", fake.sent[2]
    # Bubble 4: empty text, no media, the giphy id on the send itself.
    assert fake.sent[3][1] == "", fake.sent[3]
    assert fake.sent[3][2] == [], fake.sent[3]
    assert fake.gifs == [(45001, "", "l0MYt5jPR6QX5pnqM")], fake.gifs

    # Blank/absent gif_id = off: back to the three text bubbles, no GIF send.
    aid2 = "acc_w_gif_off"
    await _seed_account(aid2)
    await _seed_brain(aid2)
    fake2 = _use_fake([_sub(45002, name="Sofie")])
    res2 = await run_once(aid2, "send_welcome",
                          payload={"with_image": False,
                                   "question": "what's yours?", "gif_id": "  "})
    assert res2["gifs_sent"] == 0, res2
    assert len(fake2.sent) == 3, fake2.sent
    assert fake2.gifs == [], fake2.gifs


async def case_gif_failure_never_costs_the_welcome():
    """A dead/refused giphy id must not un-welcome the fan. If the bubble-4 send
    were allowed to raise past the loop, `_mark_welcomed` would be skipped and the
    next tick would re-welcome him from scratch — a fan re-greeted every two
    minutes forever. The text bubbles landed, so he IS welcomed: the GIF is
    cosmetic, the claim is written, and the run reports the send as successful."""
    aid = "acc_w_gif_fail"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45101, name="Sofie")])
    fake.gif_fails = True
    async def _boom(**kw):
        raise AssertionError("the welcome must not call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": "what's yours?", "gif_id": "dead_id"})
    assert res["welcomes_sent"] == 1, res       # the welcome still counts
    assert res["gifs_sent"] == 0, res           # the GIF did not
    assert res["errors"] == 0, res              # a cosmetic loss is not an error
    assert len(fake.sent) == 3, fake.sent       # 3 text bubbles landed
    async with get_session() as s:
        rows = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid)
        )).scalars().all()
    assert list(rows) == [45101], rows          # claimed → never re-welcomed

    # And the fan is not re-welcomed on the next sweep.
    res2 = await run_once(aid, "send_welcome",
                          payload={"with_image": False,
                                   "question": "what's yours?", "gif_id": "dead_id"})
    assert res2["welcomes_sent"] == 0, res2
    assert len(fake.sent) == 3, fake.sent


async def case_burst_abort_takes_the_gif_with_it():
    """A failed text bubble STOPS the burst — and the GIF is part of that burst.

    The loop's standing policy for any bubble after the greeting is "stop the
    burst, still mark". A GIF sent after the loop instead of inside it obeyed only
    `landed > 0`, so a fan whose question bubble was refused still got the
    animation: a lone greeting, silence where the conversation should have been,
    then an unexplained GIF. Bubble 4 rides the same loop precisely so there is one
    burst policy rather than two that disagree."""
    aid = "acc_w_gif_abort"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(45301, name="Sofie")])
    fake.fail_texts = {"what's yours?"}    # bubble 3 is refused
    async def _boom(**kw):
        raise AssertionError("the welcome must not call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False,
                                  "question": "what's yours?",
                                  "gif_id": "l0MYt5jPR6QX5pnqM"})
    # Greeting + activity landed, so he IS welcomed and is not re-welcomed.
    assert res["welcomes_sent"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    # The burst was abandoned at bubble 3 → bubble 4 never happens.
    assert fake.gifs == [], fake.gifs
    assert res["gifs_sent"] == 0, res


async def case_unreachable_sub_claimed_not_retried():
    """A new sub whose account is already gone (send 404s 'User not found') is
    quarantined AND claimed in welcome_sent — send_welcome's own gate — so the
    next tick's sweep treats them as handled instead of re-composing a welcome
    (an LLM call on the no-name path) forever."""
    aid = "acc_w_unreach"
    await _seed_account(aid)
    fake = _use_fake([_sub(7501, name="Ghost")])
    def _raise(chat_id, text, **kw):
        raise Exception(
            f"404 for https://onlyfans.com/api2/v2/chats/{chat_id}/messages\n"
            '{"error":{"code":0,"message":"User not found"}}'
        )
    fake.send_message = _raise
    _patch_llm()

    r1 = await run_once(aid, "send_welcome", payload={})
    assert r1["welcomes_sent"] == 0 and r1["errors"] == 1, r1
    async with get_session() as s:
        ws = await s.get(WelcomeSent, (aid, 7501))
        assert ws is not None, "welcome_sent claimed → never retried"
        row = await s.get(SkipList, (aid, 7501))
        assert row is not None and row.reason == "unreachable", row

    r2 = await run_once(aid, "send_welcome", payload={})
    assert r2["new_subscribers"] == 0 and r2["errors"] == 0, r2
    assert r2["welcomes_sent"] == 0, r2


# ── 2-bubble send shape: image rides on bubble 1 only ────────────────────

async def case_two_bubbles_image_on_first_only():
    """Local-template welcome sends TWO paced bubbles; the time-of-day vault image
    is attached to the greeting bubble ONLY. Both land as outbound message rows;
    welcome_sent is claimed once."""
    aid = "acc_w_2bub"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(16001, name="Mia")], vault=True)
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": True})
    assert res["welcomes_sent"] == 1 and res["image_attached"] == 1, res
    assert len(fake.sent) == 2, fake.sent
    _, b1, media1 = fake.sent[0]
    _, b2, media2 = fake.sent[1]
    assert b1 == "Hey M-M-M-Mighty Mia ! !!", b1
    assert len(media1) == 1 and 501 <= media1[0] <= 506, media1  # image on bubble 1
    assert media2 == [], media2                                  # bubble 2 text-only
    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid))).scalars().all()
        assert len(msgs) == 2, f"both bubbles persisted, got {len(msgs)}"
        ws = (await s.execute(
            select(WelcomeSent).where(WelcomeSent.account_id == aid))).scalars().all()
        assert len(ws) == 1, ws


async def case_second_bubble_send_failure_still_marks_welcomed():
    """Bubble 1 (the greeting) lands, bubble 2's send blows up → the fan IS
    welcomed: welcome_sent claimed, welcomes_sent counted, no retry next tick."""
    aid = "acc_w_b2fail"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(20001, name="Sky")])
    _patch_llm()
    calls = {"n": 0}
    _orig_send = fake.send_message
    def _flaky(chat_id, text, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Exception("network blip")
        return _orig_send(chat_id, text, **kw)
    fake.send_message = _flaky

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1 and res["errors"] == 0, res
    assert len(fake.sent) == 1, fake.sent  # only the greeting landed
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 20001)) is not None, "claimed"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid))).scalars().all()
        assert len(msgs) == 1, msgs

    r2 = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert r2["new_subscribers"] == 0 and r2["welcomes_sent"] == 0, r2


# ── NOT-NEW gate: ESTABLISHED fans skipped, lightly-touched new fans kept ──

def _msgs(aid, fid, *, out=0, inn=0):
    """N outbound + M inbound message rows for a fan (unique message_ids)."""
    rows = []
    mid = fid * 1000
    for _ in range(out):
        mid += 1
        rows.append(Message(account_id=aid, fan_id=fid, message_id=mid, direction="out",
                            body="x", created_at=datetime(2026, 6, 1)))
    for _ in range(inn):
        mid += 1
        rows.append(Message(account_id=aid, fan_id=fid, message_id=mid, direction="in",
                            body="x", created_at=datetime(2026, 6, 1)))
    return rows


async def case_skips_established_keeps_lightly_touched_new():
    """The `type=subscribed` feed includes renewals/re-subs and welcome_sent has no
    row for pre-existing fans, so an ESTABLISHED fan must NOT be re-welcomed. But a
    genuinely new sub may carry a little history first (a mass blast → 1-2 outbound;
    their own opening DMs → a handful inbound) and MUST still be welcomed.

      6001: 3 outbound  → exceeds >2 tolerance        → established, skipped
      6002: 0 history   → brand new                   → welcomed
      6003: 2 out + 5 in → within tolerance (new sub mass-hit + chatted) → welcomed
      6004: 9 inbound   → exceeds >8 tolerance        → established, skipped
    """
    aid = "acc_w_hist"
    await _seed_account(aid)
    async with get_session() as s:
        for r in (_msgs(aid, 6001, out=3) + _msgs(aid, 6003, out=2, inn=5)
                  + _msgs(aid, 6004, inn=9)):
            s.add(r)
    _use_fake([_sub(6001, name="Whale"), _sub(6002, name="Newbie"),
               _sub(6003, name="Masshit"), _sub(6004, name="Chatty")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["skipped_existing"] == 2, res            # 6001 + 6004
    assert res["welcomes_sent"] == 2, res               # 6002 + 6003
    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()
        assert {r[0] for r in ws} == {6002, 6003}, ws   # established fans not welcomed


# ── Contact guard: a fan another automation just touched is skipped ──────

async def case_contact_guard_skips_recent_nudge():
    """Defense-in-depth: a fan with NO message history (so the not-new gate
    doesn't catch them) but a recent NudgeState touch is excluded by the
    cross-automation contact guard — counted skipped_guard, not welcomed."""
    aid = "acc_w_guard"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=7001, last_nudged_at=datetime.utcnow()))
    _use_fake([_sub(7001, name="Touched"), _sub(7002, name="Fresh")])
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["skipped_guard"] == 1, res
    assert res["skipped_existing"] == 0, res
    assert res["welcomes_sent"] == 1, res
    async with get_session() as s:
        ws = (await s.execute(
            select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).all()
        assert {r[0] for r in ws} == {7002}, ws

    # guard_hours=0 turns the guard off → the touched fan welcomes next tick.
    res2 = await run_once(aid, "send_welcome", payload={"with_image": False, "guard_hours": 0})
    assert res2["skipped_guard"] == 0 and res2["welcomes_sent"] == 1, res2


# ── Name fix: team-curated nickname beats the raw OF account name ────────

async def case_curated_nick_beats_raw_of_name():
    """The fan's raw OF account name is 'Kyle' (rides on the subscribe notif), but
    the team curated custom_nickname='Garrett/Kelowna,Canada/...'. The welcome must
    greet 'Garrett' (what the whole UI shows), NOT 'Kyle' — the raw OF notif name
    is now the LAST-resort fallback, below the curated nickname."""
    aid = "acc_w_name"
    await _seed_account(aid)
    await _seed_brain(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=8001,
                  custom_nickname="Garrett/Kelowna,Canada/Horny/CustomVideo"))
    # Notif carries the raw OF account name 'Kyle'; the seeded Fan has no message
    # history, so the not-new gate doesn't block it.
    fake = _use_fake([_sub(8001, name="Kyle")])
    async def _boom(**kw):
        raise AssertionError("LLM must not be called — a curated name resolves locally")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    _, text, _ = fake.sent[0]
    assert text.startswith("Hey G-G-G-Gorgeous Garrett ! !!"), text  # NOT 'Kyle'
    assert all("Kyle" not in t for _, t, _ in fake.sent), fake.sent


# ── test_fan forces past BOTH new-discovery gates (the live-driver path) ──

async def case_test_fan_bypasses_new_gates():
    """`test_fan` is an explicit force — the live drivers / UI 'send test' point it
    at a real fan that obviously HAS history and was recently touched. Neither the
    not-new history gate nor the contact guard may block it."""
    aid = "acc_w_force"
    await _seed_account(aid)
    async with get_session() as s:
        for r in _msgs(aid, 9001, out=5, inn=10):  # unambiguously established
            s.add(r)
        s.add(NudgeState(account_id=aid, fan_id=9001, last_nudged_at=datetime.utcnow()))
    _use_fake([])  # notification feed irrelevant when test_fan is set
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"test_fan": 9001, "test_name": "Sam", "with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert res["skipped_existing"] == 0 and res["skipped_guard"] == 0, res


# ── Follow-back on subscribe ──────────────────────────────────────────

async def case_follow_back_all_new_subs_by_default():
    """Every welcomed sub is followed back in the same tick — no knob needed —
    and the money gate is PRICE-CHECKING by default, so each one costs a profile
    read before the follow. Both frees here pass the check and get followed."""
    aid = "acc_w_fb1"
    await _seed_account(aid)
    fake = _use_fake([_sub(31001, name="Ann"), _sub(31002, name="Ben")])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), {"subscribePrice": 0})[1]
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 2, res
    assert res["follow_back_errors"] == 0, res
    assert sorted(fake.followed) == [31001, 31002], fake.followed
    assert sorted(reads) == [31001, 31002], \
        f"the gate is on by default and must read every profile, got {reads}"


async def case_follow_back_gate_defaults_ON_and_skips_a_priced_sub():
    """🔴 THE DEFAULT, in the shape the operator asked for: "we always skip
    subscribers who charge to follow". An EMPTY payload — every rule live in
    prod today — must price-check and skip the priced sub, not buy him.

    Pinned separately from the gate's own case (which passes the knob
    explicitly): that one would stay green through a flip of the read-default,
    and the read-default is the whole thing being promised here."""
    aid = "acc_w_fb_default_gate"
    await _seed_account(aid)
    fake = _use_fake([_sub(31701, name="Free"), _sub(31702, name="Paid")])
    fake.profiles = {31701: {"subscribePrice": 0}, 31702: {"subscribePrice": 15}}
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 1, res
    assert res["follow_back_paid_skipped"] == 1, res
    assert fake.followed == [31701], \
        f"a priced sub was followed on the default payload: {fake.followed}"


async def case_follow_back_gate_off_follows_blind_with_no_read():
    """The opt-out, which is what the default used to be: `follow_back_gate:
    false` spends NO profile read and follows everyone — including the priced
    creator, who charges this account. Kept green so the cheap path still works
    for an operator who chooses it."""
    aid = "acc_w_fb_ungated"
    await _seed_account(aid)
    fake = _use_fake([_sub(31801, name="Free"), _sub(31802, name="Paid")])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), {"subscribePrice": 15})[1]
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back_gate": False})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 2, res
    assert sorted(fake.followed) == [31801, 31802], fake.followed
    assert reads == [], f"ungated follow-back reads no profiles, got {reads}"


async def case_follow_back_null_means_the_default_not_off():
    """⚠️ MONEY. `null` used to be the one non-boolean that reached storage for
    these keys — `_validate_payload_for_kind` SKIPPED None instead of rejecting
    it — and it meant two different things on the two sides of the same rule.
    That boundary now POPS a null for a catalogued knob, so no NEW rule can store
    one; this case pins the reader that still has to answer for the rules written
    before that line, and stored nulls do not expire.

    `bool(payload.get("follow_back_gate", True))` is False for a stored `null`:
    the default never applies, because `.get` found the key. So a rule carrying
    `{"follow_back": null, "follow_back_gate": null}` ran with the lane OFF and
    the price-check OFF, while BrainPanel's `!== false` read drew both boxes
    TICKED and the catalog declared both True. Three sides, two answers, on the
    pair of keys where the wrong answer is either a silently dead lane or a blind
    PAID follow.

    A key that is present-but-null says nothing, so it now means exactly what
    absent means. Asserted through `run_once` rather than against `bool_knob`,
    because the defect was never in the helper — it was in which helper the
    sender reached for."""
    aid = "acc_w_fb_null"
    await _seed_account(aid)
    fake = _use_fake([_sub(31901, name="Free"), _sub(31902, name="Paid")])
    fake.profiles = {31901: {"subscribePrice": 0}, 31902: {"subscribePrice": 15}}
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={
        "with_image": False, "follow_back": None, "follow_back_gate": None})
    # The lane RAN (null is not "off")...
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 1, res
    # ...and it PRICE-CHECKED (null is not "gate off"), so the paid sub is a skip
    # and not a purchase.
    assert res["follow_back_paid_skipped"] == 1, res
    assert fake.followed == [31901], \
        f"a null gate bought a priced sub a subscription: {fake.followed}"
    # And the run reports the knobs as it resolved them, so a reader of the stats
    # cannot be told a different story than the fans were.
    assert res["follow_back"] is True and res["follow_back_gate"] is True, res


async def case_run_stats_carry_the_follow_back_knobs():
    """The five counters cannot be read without them. `followed_back: 0` is a
    switched-off lane, a tick where everyone was already followed, and a lane
    that silently broke — three meanings, one number. And `follow_back_gate` is
    the only thing in the bag that can say the follows went out UNPRICED:
    `follow_back_paid_skipped` is 0 both when there were no paid subs and when
    nothing looked. `app/lib/runStats.tsx`'s `welcomeStatsChunks` renders both."""
    aid = "acc_w_fb_stats"
    await _seed_account(aid)
    fake = _use_fake([_sub(32001, name="Ann")])
    fake.profiles = {32001: {"subscribePrice": 0}}
    _patch_llm()

    on = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert on["follow_back"] is True and on["follow_back_gate"] is True, on
    assert on["followed_back"] == 1, on

    aid2 = "acc_w_fb_stats_off"
    await _seed_account(aid2)
    _use_fake([_sub(32002, name="Ben")])
    _patch_llm()
    off = await run_once(aid2, "send_welcome", payload={
        "with_image": False, "follow_back": False})
    assert off["follow_back"] is False, off
    assert off["followed_back"] == 0, off


async def case_follow_back_off_when_switched_off():
    aid = "acc_w_fb2"
    await _seed_account(aid)
    fake = _use_fake([_sub(31101, name="Cal")])
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back": False})
    assert res["welcomes_sent"] == 1, res
    assert res["followed_back"] == 0, res
    assert fake.followed == [], fake.followed


async def case_follow_back_failure_never_costs_the_welcome():
    """The follow is a bonus notification. When it raises, the welcome still
    landed, welcome_sent is still claimed, and the next tick does NOT re-welcome
    (which would double-message the fan to retry a follow)."""
    aid = "acc_w_fb3"
    await _seed_account(aid)
    fake = _use_fake([_sub(31201, name="Dee")])
    fake.follow_fails = {31201}
    _patch_llm()

    res = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert res["welcomes_sent"] == 1, res
    assert res["followed_back"] == 0 and res["follow_back_errors"] == 1, res
    assert res["errors"] == 0, f"a failed follow is not a welcome error: {res}"
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 31201)) is not None, "still claimed"

    r2 = await run_once(aid, "send_welcome", payload={"with_image": False})
    assert r2["welcomes_sent"] == 0 and r2["followed_back"] == 0, r2


async def case_follow_back_dry_run_follows_nobody():
    aid = "acc_w_fb4"
    await _seed_account(aid)
    fake = _use_fake([_sub(31301, name="Eve")])
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "dry_run": True})
    assert res["followed_back"] == 0, res
    assert fake.followed == [], fake.followed


async def case_follow_back_gate_skips_paid_and_unreadable_profiles():
    """With `follow_back_gate` on, only a free profile is followed: a priced one
    is skipped (subscribe would CHARGE us) and so is one whose price we cannot
    read — never assume free. Both still get their welcome."""
    aid = "acc_w_fb5"
    await _seed_account(aid)
    fake = _use_fake([_sub(31401, name="Free"), _sub(31402, name="Paid"),
                      _sub(31403, name="Unknown")])
    fake.profiles = {
        31401: {"subscribePrice": 0},
        31402: {"subscribePrice": 9.99},
        31403: {},                        # no price field at all
    }
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back_gate": True})
    assert res["welcomes_sent"] == 3, res
    assert res["followed_back"] == 1, res
    assert res["follow_back_paid_skipped"] == 1, res
    assert res["follow_back_no_price"] == 1, res
    assert fake.followed == [31401], fake.followed


async def case_follow_back_gate_resubscribes_a_lapsed_edge():
    """A free profile we USED to follow (subscribedByExpireDate set) re-arms via
    /resubscribe, and one we already follow is left alone — neither is a plain
    follow_user call."""
    aid = "acc_w_fb6"
    await _seed_account(aid)
    fake = _use_fake([_sub(31501, name="Lapsed"), _sub(31502, name="Current")])
    fake.profiles = {
        31501: {"subscribePrice": 0, "subscribedByExpireDate": "2026-01-01T00:00:00+00:00"},
        31502: {"subscribePrice": 0, "subscribedBy": True},
    }
    _patch_llm()

    res = await run_once(aid, "send_welcome",
                         payload={"with_image": False, "follow_back_gate": True})
    assert res["welcomes_sent"] == 2, res
    assert res["followed_back"] == 1, res           # the re-arm counts as a notification
    assert res["follow_back_already"] == 1, res
    assert fake.resubscribed == [31501], fake.resubscribed
    assert fake.followed == [], fake.followed


async def case_follow_back_is_auto_follows_gate_not_a_copy_of_it():
    """🔴 ONE money gate, and this lane calls it.

    `send_welcome` used to carry `_follow_back_outcome` + `_follow_back`, which
    were `auto_follow._classify` + `gated_follow(unfollow_first=False)` with five
    labels renamed — proven identical over 255 profile shapes, 0 disagreements.
    It is the gate that decides whether OF's /subscribe CHARGES the account, and
    the copy ran fleet-wide on every new subscriber while the original carried the
    verified-live finding about which payload field means which edge and the
    measured cost data. A payload change from OF would have landed in one of them.

    Pinned two ways so a re-introduced copy cannot pass: the module must not carry
    the old names at all, and a `gated_follow` stub must be the thing the welcome
    path actually reaches."""
    from automations import send_welcome as sw
    from automations import auto_follow as af

    assert not hasattr(sw, "_follow_back_outcome"), \
        "the copied classifier is back"
    assert not hasattr(sw, "_follow_back"), "the copied follow body is back"
    assert sw.gated_follow is af.gated_follow

    aid = "acc_w_fb_shared"
    await _seed_account(aid)
    fake = _use_fake([_sub(31601, name="Free")])
    fake.profiles = {31601: {"subscribePrice": 0}}
    _patch_llm()

    seen: list[tuple] = []
    real = af.gated_follow

    async def _spy(client, fan_id, *, account_id, unfollow_first=False, money_gate=True):
        seen.append((int(fan_id), unfollow_first, money_gate))
        return await real(client, fan_id, account_id=account_id,
                          unfollow_first=unfollow_first, money_gate=money_gate)

    sw.gated_follow = _spy          # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "follow_back_gate": True})
    finally:
        sw.gated_follow = real      # type: ignore[assignment]

    assert res["welcomes_sent"] == 1 and res["followed_back"] == 1, res
    # …and it was called the one way this lane is allowed to call it: never
    # cycling an existing follow, so `_StrandedError` is unreachable here.
    assert seen == [(31601, False, True)], seen


async def case_an_unknown_follow_back_outcome_is_booked_under_its_own_name():
    """🔴 A CATCH-ALL `else` THAT MAKES A SPECIFIC, WRONG, CONFIDENT CLAIM.

    The follow-back lane once re-implemented `gated_follow`'s outcome enum as an
    if/elif chain ending in `else: follow_back_no_price += 1`. `gated_follow`
    returns SIX labels and this lane named four, so a seventh added over there
    landed here silently — and `runStats` renders `follow_back_no_price` as
    "N follow-back prices unreadable" on the operator's MONEY screen. A wrong
    specific claim is worse than no claim: it sends him to look at OF profiles
    that are fine.

    The tally is a `Counter` keyed by `_classify`'s own label, total for free
    (`auto_follow`'s own consumer does the same): an outcome this lane has never
    named lands under its own name in `follow_back_outcomes`, never under one
    of the three it has, and it is not an error either — the follow call
    returned normally."""
    from automations import send_welcome as sw
    from automations import auto_follow as af

    aid = "acc_w_fb_unknown"
    await _seed_account(aid)
    fake = _use_fake([_sub(31701, name="Free")])
    fake.profiles = {31701: {"subscribePrice": 0}}
    _patch_llm()

    real = af.gated_follow

    async def _stub(client, fan_id, *, account_id, unfollow_first=False, money_gate=True):
        return "shadow_banned"      # a label from some future gate

    sw.gated_follow = _stub         # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "follow_back_gate": True})
    finally:
        sw.gated_follow = real      # type: ignore[assignment]

    # The welcome is untouched — a follow-back never costs a fan his welcome.
    assert res["welcomes_sent"] == 1, res
    assert res["follow_back_errors"] == 0 and res["errors"] == 0, res
    # 🔴 THE POINT: not booked as a price we could not read — under its own name.
    assert res["follow_back_no_price"] == 0, res
    assert res["follow_back_already"] == 0, res
    assert res["follow_back_paid_skipped"] == 0, res
    assert res["follow_back_outcomes"] == {"shadow_banned": 1}, res


async def case_follow_back_on_fansly_follows_without_a_price_to_read():
    """🔴 The Fansly lane. `gated_follow` reads `subscribePrice` and the shim's
    `get_user` (`of_user`) carries none, so with the gate ON by default every new
    sub was booked `no_price` and never followed — a lane that worked the day
    before the flip. Fansly's follow is free by construction; on that platform
    the gate reads nothing and follows, and `auto_follow` gets the same row
    (`test_auto_follow.case_fansly_follow_is_free_so_the_gate_reads_nothing`)."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "fansly"))
    from fansly_shim import of_user
    aid = "acc_w_fb_fansly"
    await _seed_account(aid)
    fake = _use_fake([_sub(91001, name="Bob")])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), of_user(
        {"id": str(uid), "username": "bob", "displayName": "Bob",
         "subscriptionTiers": [{"id": "t1", "price": 5000}]}))[1]
    _patch_llm()
    real_platform = ax.account_registry.get_platform
    ax.account_registry.get_platform = lambda a: "fansly" if a == aid else "onlyfans"  # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome", payload={"with_image": False})
    finally:
        ax.account_registry.get_platform = real_platform  # type: ignore[assignment]
    assert res["welcomes_sent"] == 1, res
    assert fake.followed == [91001], (res, fake.followed)
    assert res["followed_back"] == 1 and res["follow_back_no_price"] == 0, res
    assert reads == [], ("no price to read on Fansly", reads)


async def case_pace_and_stop_default_ON_in_production_OFF_in_tests():
    """The two knobs the operator turned on by default (2026-09-06).

    Absent from a rule's payload they are ON in production — an existing welcome
    rule nobody has re-saved paces and stops on a reply. Under CHATTERLY_TEST_MODE
    they are OFF when absent, because their quiet draws are real wall-clock time
    that `load_typing_wpm`'s test-mode zero does not reach (H6), and 84 legacy
    cases here call `run_once` with no payload. An explicit value always wins in
    BOTH modes — which is what the UI writes, so a switched-OFF rule stays off.

    This pins the production default, which no other case can: every case in this
    file runs under test mode by construction (`_harness.py:49`).
    """
    saved = os.environ.get("CHATTERLY_TEST_MODE")
    try:
        # --- production: absent means ON ---
        os.environ.pop("CHATTERLY_TEST_MODE", None)
        for key in ("human_pace", "stop_on_reply"):
            assert send_welcome._on_unless_off({}, key) is True, key
            assert send_welcome._on_unless_off({key: False}, key) is False, key
            assert send_welcome._on_unless_off({key: True}, key) is True, key
            # An explicit null is "unset", not "off" — it must not disable the knob.
            assert send_welcome._on_unless_off({key: None}, key) is True, key

        # --- tests: absent means OFF, explicit still wins ---
        os.environ["CHATTERLY_TEST_MODE"] = "1"
        for key in ("human_pace", "stop_on_reply"):
            assert send_welcome._on_unless_off({}, key) is False, key
            assert send_welcome._on_unless_off({key: True}, key) is True, key
            assert send_welcome._on_unless_off({key: False}, key) is False, key

        # --- `=0` means "no" — for THIS reader and for `_common`'s alike ---
        # One parse (`_common.test_mode`) feeds every reader of the variable.
        # With four independent parses, `=0` once made this sender default its
        # knobs ON (production) while `load_typing_wpm` zeroed the typing time
        # (test mode) in the same process.
        from automations._common import _DEFAULT_TYPING_WPM, load_typing_wpm, test_mode
        for off in ("0", "false", "no", "off", ""):
            os.environ["CHATTERLY_TEST_MODE"] = off
            assert test_mode() is False, off
            for key in ("human_pace", "stop_on_reply"):
                assert send_welcome._on_unless_off({}, key) is True, (off, key)
            assert await load_typing_wpm("acc_w_no_such_account") == _DEFAULT_TYPING_WPM, off
        for on in ("1", "true", "yes"):
            os.environ["CHATTERLY_TEST_MODE"] = on
            assert test_mode() is True, on
            assert send_welcome._on_unless_off({}, "human_pace") is False, on
            assert await load_typing_wpm("acc_w_no_such_account") == 0.0, on
    finally:
        if saved is None:
            os.environ.pop("CHATTERLY_TEST_MODE", None)
        else:
            os.environ["CHATTERLY_TEST_MODE"] = saved


async def case_follow_back_under_human_pace():
    """THE H1 INTERACTION: follow-back was written for the serial loop; pacing
    then made the per-fan bodies run concurrently. Every follow-back assertion in
    this file runs on the serial path, and every concurrency assertion runs with
    follow-back's outcome unobserved — the two knobs had never co-occurred in one
    payload, which is the shape the review existed to find.

    `fake.followed` is asserted as a SET, deliberately: under pacing the fans
    finish in whatever order their draws land, so a sorted-list assertion here
    would be pinning nondeterminism, not behaviour."""
    aid = "acc_w_fb_paced"
    await _seed_account(aid)
    await _seed_brain(aid)
    fans = (32001, 32002, 32003)
    fake = _use_fake([_sub(f, name=n) for f, n in zip(fans, ("Ada", "Ben", "Cal"))])
    reads: list[int] = []
    fake.get_user = lambda uid: (reads.append(int(uid)), {"subscribePrice": 0})[1]
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    holds = _record_holds()
    try:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False,
                                      "human_pace": True, "follow_back": True})
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]

    assert res["human_pace"] is True, res
    assert res["welcomes_sent"] == 3, res
    # Every landed welcome bought exactly one follow — no fan double-followed by
    # two overlapping tasks, none lost to the concurrency.
    assert res["followed_back"] == 3, res
    assert res["follow_back_errors"] == 0 and res["errors"] == 0, res
    assert set(fake.followed) == set(fans), fake.followed
    assert len(fake.followed) == 3, f"a fan was followed twice: {fake.followed}"
    # One price-check per fan (the gate is on by default), and the concurrency
    # bought no extra reads either.
    assert sorted(reads) == sorted(fans), f"one gated read per fan, got {reads}"
    # Really concurrent, not accidentally serialised into passing: three start
    # jitters before any fan's first hold.
    assert [h.get("jitter") for h in holds[:3]] == [True] * 3, holds[:3]
    # And the shared cooldown ledger is stamped, so an auto_follow backfill tick
    # cannot notify the same fan a second time for the same relationship.
    async with get_session() as s:
        stamped = {int(r[0]) for r in (await s.execute(
            select(FollowPingState.fan_id)
            .where(FollowPingState.account_id == aid))).all()}
    assert stamped == set(fans), f"follow-back must stamp the ping ledger: {stamped}"


async def case_follow_back_ledger_write_failure_is_not_an_error():
    """The ledger stamp gets its OWN swallow, below the follow's.

    By the time the ledger is written the follow has LANDED and is already
    counted in `followed_back`. Folding the write into the outer swallow booked
    the same fan as both a success and a `follow_back_errors` — a run reporting
    `followed_back: 1, follow_back_errors: 1` for one fan and one follow. The
    real cost of a lost stamp is one duplicate notification from auto_follow
    later, and it must never cost the fan his welcome either."""
    aid = "acc_w_fb_ledger"
    await _seed_account(aid)
    fake = _use_fake([_sub(34001, name="Ann")])
    _patch_llm()
    real_stamp = send_welcome.stamp_ping
    async def _boom(account_id, fan_id):
        raise RuntimeError("db went away mid-stamp")
    send_welcome.stamp_ping = _boom  # type: ignore[assignment]
    try:
        res = await run_once(aid, "send_welcome", payload={"with_image": False})
    finally:
        send_welcome.stamp_ping = real_stamp  # type: ignore[assignment]

    assert res["welcomes_sent"] == 1, res
    assert fake.followed == [34001], fake.followed
    assert res["followed_back"] == 1, res
    assert res["follow_back_errors"] == 0, (
        f"a lost ledger write is not a failed follow: {res}")
    assert res["errors"] == 0, res


async def case_paced_run_cancelled_raises_not_returns():
    """A cancelled child must make `run()` RAISE, never return a stats dict.

    `asyncio.gather(return_exceptions=True)` captures BaseException, and
    CancelledError is not an Exception — so a cancelled child came back as an
    ordinary result and was counted as `errors += 1`, and `run()` returned
    normally. automation_executor only parks the run and requeues the job when
    CancelledError propagates out of run(); returning instead finalised a
    half-executed batch as `ok` and consumed the job. That is exactly what a
    uvicorn restart mid-tick does."""
    aid = "acc_w_pace_cancel"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(f, name=n) for f, n in
                      zip((33001, 33002), ("Ada", "Ben"))])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    # Cancel the fan's own task from inside its first hold — the same shape a
    # loop teardown produces, where children die before the parent's cancel.
    async def _cancel_me(account_id, fan_id, seconds, **kw):
        raise asyncio.CancelledError()
    send_welcome.hold_with_typing = _cancel_me  # type: ignore[assignment]
    _run_pool._sleep = _no_jitter  # type: ignore[assignment]

    raised = None
    try:
        await send_welcome.run(aid, {"with_image": False,
                                     "human_pace": True}, run_id=0)
    except asyncio.CancelledError as e:
        raised = e
    except BaseException as e:                      # pragma: no cover - diagnosis
        raised = e
    finally:
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]

    assert isinstance(raised, asyncio.CancelledError), (
        f"a cancelled child must propagate, got {raised!r}")
    assert fake.sent == [], f"nothing should have shipped: {fake.sent}"


async def case_paced_cancel_while_parked_takes_the_spawned_bursts_down():
    """Cancelling a paced run while the admit loop is PARKED on `sem.acquire()`
    must take the already-spawned bursts down with it.

    This is the half of the cancel fix `case_paced_run_cancelled_raises_not_returns`
    does not reach: that case cancels the CHILD from inside its own hold, so it
    only exercises the gather re-raise. Nothing exercised the parent parking on
    the semaphore — and with the `except asyncio.CancelledError` wrap removed
    the whole suite still passed while the defect was live.

    The defect: `_PACE_CONCURRENCY` tasks are already detached and mid-burst
    when the parent raises. Left alone they run to completion AFTER the
    executor has parked the run as cancelled — instrumented at 4 real DMs and
    3 real (paid) follows landing for a run the system believes it stopped.

    Shape: more fans than `_PACE_CONCURRENCY`, every burst held on an event that
    never fires, so slot 7's `sem.acquire()` is where the parent sleeps when the
    cancel arrives. Then: zero sends, zero follows, after the cancel point."""
    aid = "acc_w_pace_cancel_parked"
    await _seed_account(aid)
    await _seed_brain(aid)
    n = send_welcome._PACE_CONCURRENCY + 4        # must exceed the semaphore
    fans = [48401 + i for i in range(n)]
    fake = _use_fake([_sub(f, name=f"F{f}") for f in fans])
    async def _boom(**kw):
        raise AssertionError("the welcome must NOT call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]

    # Every burst parks on a gate that is never opened, so the admitted tasks
    # pin all `_PACE_CONCURRENCY` slots and the parent blocks on the next
    # acquire(). `admitted` counts arrivals so we can wait for a real park
    # rather than guessing at an event-loop turn count.
    #
    # ⚠️ The START JITTER (`_run_pool._sleep`) is made instant, not parked on.
    # Parking on it would pin the semaphore just as well, but it parks OUTSIDE
    # `_welcome_one` — before the fan lease is taken — so the lease assertion
    # below would pass no matter what the cancel path does. Parking on bubble
    # 0's hold instead is inside the lease.
    gate = asyncio.Event()
    admitted: list[int] = []
    async def _park(account_id, fan_id, seconds, **kw):
        admitted.append(int(fan_id))
        await gate.wait()
    send_welcome.hold_with_typing = _park  # type: ignore[assignment]
    _run_pool._sleep = _no_jitter  # type: ignore[assignment]

    task = asyncio.create_task(send_welcome.run(
        aid, {"with_image": False, "human_pace": True},
        run_id=0))
    try:
        # Let the loop admit its full concurrency and park on the next acquire.
        for _ in range(400):
            if len(admitted) >= send_welcome._PACE_CONCURRENCY:
                break
            await asyncio.sleep(0.01)
        assert len(admitted) >= send_welcome._PACE_CONCURRENCY, (
            f"the admit loop never filled the semaphore: {admitted}")
        assert len(admitted) == send_welcome._PACE_CONCURRENCY, (
            f"more tasks than slots — the parent is not parked: {admitted}")

        # THE CANCEL POINT. Everything recorded from here on is a send or a
        # follow the executor has already been told did not happen.
        sends_at_cancel = len(fake.sent)
        follows_at_cancel = len(fake.followed)
        task.cancel()

        raised = None
        try:
            await task
        except asyncio.CancelledError as e:
            raised = e
        except BaseException as e:                  # pragma: no cover - diagnosis
            raised = e
        assert isinstance(raised, asyncio.CancelledError), (
            f"a cancel while parked must propagate, got {raised!r}")

        # EVERY PARKED FAN'S LEASE IS ALREADY BACK — asserted HERE, before the
        # grace loop below, because that loop hands the event loop back and the
        # children would unwind on their own inside it. The point is that they
        # have unwound by the time `run()` raises.
        #
        # `task.cancel()` only SCHEDULES the CancelledError; each child's
        # `finally` — the one that starts the fan's rest and hands the lease
        # back, in that order, because ORDER IS LOAD-BEARING — runs on a later
        # loop turn. On the path this whole case models, a uvicorn restart
        # mid-tick, that turn never comes: `tasks` goes out of scope, the
        # interpreter prints "Task was destroyed but it is pending", and up to
        # `_PACE_CONCURRENCY` fans hold a 15-minute lease nobody will release —
        # un-messageable by EVERY automation until it expires.
        async with get_session() as s:
            held = (await s.execute(select(FanLease.fan_id)
                                    .where(FanLease.account_id == aid))).all()
            assert held == [], f"a cancelled run left leases behind: {held}"

        # Open the gate and give any SURVIVING task every chance to finish its
        # burst. If the spawned tasks were not taken down, this is where their
        # sends and follows land.
        gate.set()
        for _ in range(50):
            await asyncio.sleep(0.01)

        assert len(fake.sent) == sends_at_cancel, (
            f"{len(fake.sent) - sends_at_cancel} DM(s) shipped AFTER the run was "
            f"cancelled: {fake.sent[sends_at_cancel:]}")
        assert len(fake.followed) == follows_at_cancel, (
            f"{len(fake.followed) - follows_at_cancel} follow(s) fired AFTER the "
            f"run was cancelled: {fake.followed[follows_at_cancel:]}")
        # Belt: a cancelled run must not have claimed anybody as welcomed.
        async with get_session() as s:
            ws = (await s.execute(select(WelcomeSent.fan_id)
                                  .where(WelcomeSent.account_id == aid))).all()
            assert ws == [], f"a cancelled run claimed welcomes: {ws}"
    finally:
        gate.set()
        send_welcome.hold_with_typing = _REAL_HOLD  # type: ignore[assignment]
        _run_pool._sleep = _REAL_SLEEP  # type: ignore[assignment]


# ── Smart Messages on the welcome (06 P3): variants, follow-ups, OF's own ──

async def _welcome_follow_ups(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == "send_welcome",
            ScheduledJob.status == "pending",
            ScheduledJob.payload_json.contains('"follow_up"')).order_by(ScheduledJob.id))).scalars())


async def _take_welcome_follow_up(aid: str, fan_id: int) -> dict:
    """The pending follow-up job's payload, marked done, with the fan's welcome
    rest lifted — what the executor would run once the delay is up."""
    job = (await _welcome_follow_ups(aid))[0]
    async with get_session() as s:
        (await s.get(ScheduledJob, job.id)).status = "done"
        fan = (await s.execute(select(Fan).where(
            Fan.account_id == aid, Fan.fan_id == fan_id))).scalar_one_or_none()
        if fan is not None:
            fan.automation_paused_until = None
    return json.loads(job.payload_json)


async def case_a_message_list_is_its_variants_one_picked_per_fan():
    """`message` as a list is the Delayed welcome's variants: each fan gets ONE
    of them, picked per fan, as the whole welcome, {name} filled."""
    aid = "acc_w_variant"
    await _seed_account(aid)
    await _seed_brain(aid)
    names = ["Ann", "Bea", "Cat", "Dee", "Eve", "Fay", "Gia", "Hal", "Ivy", "Joy", "Kim", "Liv"]
    fake = _use_fake([_sub(46001 + i, name=n) for i, n in enumerate(names)])
    async def _boom(**kw):
        raise AssertionError("a written welcome must not call the LLM")
    llm_client.chat = _boom  # type: ignore[attr-defined]
    variants = ["hi {name}, so glad you're here", "welcome {name}!!", " "]

    res = await run_once(aid, "send_welcome", payload={
        "with_image": False, "question": "what's yours?", "message": variants})
    assert res["welcomes_sent"] == 12 and res["message_variants"] == 2, res
    got = {fid: t for fid, t, _ in fake.sent}
    assert len(fake.sent) == 12, fake.sent       # one DM each: no question bubble
    for i in range(12):
        picked = send_welcome.pick(variants[:2], "welcome", aid, 46001 + i)
        assert got[46001 + i] == picked.replace("{name}", names[i]), got
    assert len(set(got.values())) > 2 and {t.split()[0] for t in got.values()} == {"hi", "welcome"}


async def case_welcome_follow_ups_go_out_after_the_burst_and_stop_on_a_reply():
    """Follow-ups are queued once the burst lands, each queues the next, and a
    word from the fan ends the rest without a send."""
    aid = "acc_w_followups"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(46101, name="Mia")])
    _patch_llm()
    steps = [{"text": "still there?", "delay_minutes": 30},
             {"text": "miss u", "delay_minutes": 60}]

    res = await run_once(aid, "send_welcome", payload={
        "with_image": False, "follow_ups": steps})
    assert res["welcomes_sent"] == 1 and res["follow_ups_queued"] == 1, res
    jobs = await _welcome_follow_ups(aid)
    assert len(jobs) == 1, jobs
    wait = jobs[0].run_at - datetime.utcnow()
    assert timedelta(minutes=29) < wait <= timedelta(minutes=30), wait

    burst = len(fake.sent)
    r1 = await run_once(aid, "send_welcome", payload=await _take_welcome_follow_up(aid, 46101))
    assert r1["sent"] == 1, r1
    assert fake.sent[burst:] == [(46101, "still there?", [])], fake.sent
    assert len(await _welcome_follow_ups(aid)) == 1   # the second step waits

    await _inject_inbound(aid, 46101, "hey you", mid=46101_001, at=datetime.utcnow())
    r2 = await run_once(aid, "send_welcome", payload=await _take_welcome_follow_up(aid, 46101))
    assert r2["status"] == "skipped" and r2["reason"] == "stopped_on_reply", r2
    assert len(fake.sent) == burst + 1, fake.sent
    assert await _welcome_follow_ups(aid) == []


def _of_welcome(fake: FakeOF, *, on, text: str = "<p>hi, welcome!</p>", media=0) -> None:
    """OF's own welcome as /users/me/settings and the templates list serve it;
    `on=None` makes the settings read fail."""
    def settings():
        if on is None:
            raise RuntimeError("session dead")
        return {"replyOnSubscribe": on}
    fake.my_settings = settings  # type: ignore[attr-defined]
    fake.message_templates = lambda **kw: [  # type: ignore[attr-defined]
        {"id": 1, "template": None, "text": "saved reply"},
        {"id": 2, "template": "reply_on_subscribe", "text": text, "mediaCount": media}]


async def case_after_of_welcome_sends_nothing_while_ofs_welcome_is_on():
    """OF's own subscribe welcome is message 1: no send, the fan is claimed so
    the next tick skips him, and only the follow-ups are queued, anchored on his
    newest word as of now so an older message does not end them."""
    aid = "acc_w_after_of"
    await _seed_account(aid)
    await _seed_brain(aid)
    fake = _use_fake([_sub(46201, name="Nora")])
    _of_welcome(fake, on=True)
    _patch_llm()
    await _inject_inbound(aid, 46201, "hi there", mid=46201_001,
                          at=datetime.utcnow() - timedelta(minutes=5))
    payload = {"with_image": False, "after_of_welcome": True,
               "follow_ups": [{"text": "did you see my welcome?", "delay_minutes": 20}]}

    res = await run_once(aid, "send_welcome", payload=payload)
    assert (res["of_welcome_on"], res["after_of_welcome_fans"], res["welcomes_sent"],
            res["follow_ups_queued"]) == (True, 1, 0, 1), res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        assert await s.get(WelcomeSent, (aid, 46201)) is not None
    job = json.loads((await _welcome_follow_ups(aid))[0].payload_json)
    assert job["follow_up"]["anchor"][1] == 46201_001, job

    again = await run_once(aid, "send_welcome", payload=payload)
    assert again["new_subscribers"] == 0, again
    # The old message is not a reply: the follow-up goes out.
    r = await run_once(aid, "send_welcome", payload=await _take_welcome_follow_up(aid, 46201))
    assert r["sent"] == 1 and fake.sent == [(46201, "did you see my welcome?", [])], (r, fake.sent)


async def case_after_of_welcome_sends_our_own_when_ofs_is_off_empty_or_unreadable():
    """Only a welcome OF really sends is message 1: switched off, empty, a read
    that fails or a template it cannot parse, the fan gets this rule's welcome
    rather than silence."""
    for i, (on, text, media) in enumerate(((False, "hi", 0), (True, "<p> </p>", 0), (None, "hi", 0),
                                           (True, "", "lots"))):
        aid = f"acc_w_after_of_off{i}"
        fid = 46301 + i
        await _seed_account(aid)
        await _seed_brain(aid)
        fake = _use_fake([_sub(fid, name="Ida")])
        _of_welcome(fake, on=on, text=text, media=media)
        _patch_llm()
        res = await run_once(aid, "send_welcome", payload={
            "with_image": False, "after_of_welcome": True, "message": "hey {name}"})
        unread = on is None or media == "lots"
        assert (res["of_welcome_on"], res["after_of_welcome_fans"], res["welcomes_sent"]) \
            == (None if unread else False, 0, 1), (on, text, res)
        assert fake.sent == [(fid, "hey Ida", [])], fake.sent


_harness.run(
    case_follow_back_all_new_subs_by_default,
    case_follow_back_gate_defaults_ON_and_skips_a_priced_sub,
    case_follow_back_gate_off_follows_blind_with_no_read,
    case_follow_back_under_human_pace,
    case_follow_back_ledger_write_failure_is_not_an_error,
    case_paced_run_cancelled_raises_not_returns,
    case_paced_cancel_while_parked_takes_the_spawned_bursts_down,
    case_follow_back_null_means_the_default_not_off,
    case_run_stats_carry_the_follow_back_knobs,
    case_follow_back_off_when_switched_off,
    case_follow_back_failure_never_costs_the_welcome,
    case_follow_back_dry_run_follows_nobody,
    case_follow_back_gate_skips_paid_and_unreadable_profiles,
    case_follow_back_gate_resubscribes_a_lapsed_edge,
    case_follow_back_is_auto_follows_gate_not_a_copy_of_it,
    case_an_unknown_follow_back_outcome_is_booked_under_its_own_name,
    case_extract_filters_non_subscribe_notifications,
    case_skips_established_keeps_lightly_touched_new,
    case_contact_guard_skips_recent_nudge,
    case_curated_nick_beats_raw_of_name,
    case_test_fan_bypasses_new_gates,
    case_new_subs_get_one_welcome_each,
    case_no_dup_on_restart,
    case_dedup_skips_preexisting,
    case_fan_lease_blocks_welcome,
    case_cooldown_skips_welcome,
    case_lease_released_on_send_so_the_rest_is_the_only_brake,
    case_dry_run_sends_nothing,
    case_cap_never_costs_a_welcome,
    case_with_image_attaches_bot_media,
    case_text_only_when_with_image_false,
    case_with_image_no_bot_folder_sends_text,
    case_photo_index_deterministic_per_hour,
    case_two_bubbles_image_on_first_only,
    case_second_bubble_send_failure_still_marks_welcomed,
    case_real_name_no_nick_proposes_stutter,
    case_name_resolved_from_db_still_stutters,
    case_welcome_name_resolution_matrix,
    case_random_handle_no_name_greets_deterministically,
    case_word_restriction_applied_to_sent_welcome,
    case_slot_hour_roundtrip,
    case_pinned_line_weekday_refresh,
    case_run_uses_pinned_line_no_llm,
    case_run_pin_ships_even_when_activity_blank,
    case_nameless_fan_gets_activity_bubble_and_pin,
    case_time_only_bubble_is_clock_without_activity,
    case_run_time_only_sends_short_second_bubble,
    case_time_only_outranks_a_pinned_line,
    case_time_only_always_opens_with_its,
    case_follow_back_on_fansly_follows_without_a_price_to_read,
    case_pace_and_stop_default_ON_in_production_OFF_in_tests,
    case_hold_segments_are_the_four_shapes_and_they_sum,
    case_flags_absent_every_hold_is_todays_flat_hold,
    case_human_pace_hold_phases_match_the_table,
    case_human_pace_the_question_keeps_its_own_beat_in_a_short_burst,
    case_human_pace_test_fan_is_exempt,
    case_human_pace_runs_fans_concurrently,
    case_human_pace_wall_budget_defers_and_the_next_run_reserves,
    case_stop_on_reply_quiet_phase_drops_the_bubble,
    case_stop_on_reply_typing_phase_finishes_then_hands_the_turn_back,
    case_stop_on_reply_the_LAST_bubble_hands_the_turn_back_too,
    case_stop_on_reply_a_finished_burst_he_never_answered_hands_off_nothing,
    case_stop_on_reply_an_unstamped_send_hands_the_turn_back,
    case_stop_on_reply_suppresses_the_gif_paced_and_unpaced,
    case_stop_on_reply_anchor_is_a_snapshot_not_any_inbound_ever,
    case_stop_on_reply_words_decide_not_the_message_type,
    case_stop_on_reply_query_failure_finishes_the_burst,
    case_stop_on_reply_handoff_engine_precedence,
    case_stop_on_reply_handoff_job_actually_gets_him_answered,
    case_stop_on_reply_handoff_belts_a_restricted_fan,
    case_stop_on_reply_claims_the_welcome_before_the_burst_can_die,
    case_skip_time_bubble_drops_bubble_two_entirely,
    case_skip_time_bubble_outranks_time_only_and_a_pin,
    case_skip_time_bubble_absent_composes_todays_bubbles,
    case_question_ships_verbatim_as_third_bubble,
    case_custom_message_replaces_the_burst,
    case_custom_message_carries_its_media_price_and_auto_unsend,
    case_the_effective_and_expiry_dates_bound_the_welcome,
    case_the_random_delay_counts_from_the_subscribe,
    case_with_a_delay_the_feed_is_read_back_past_the_longest_delay,
    case_a_paid_welcome_never_re_sells_media_the_fan_owns,
    case_a_failed_auto_unsend_queue_never_costs_the_welcome_claim,
    case_the_rule_routes_hold_the_delayed_welcome_settings_to_the_contract,
    case_gif_ships_as_fourth_bubble,
    case_gif_failure_never_costs_the_welcome,
    case_burst_abort_takes_the_gif_with_it,
    case_unreachable_sub_claimed_not_retried,
    case_a_message_list_is_its_variants_one_picked_per_fan,
    case_welcome_follow_ups_go_out_after_the_burst_and_stop_on_a_reply,
    case_after_of_welcome_sends_nothing_while_ofs_welcome_is_on,
    case_after_of_welcome_sends_our_own_when_ofs_is_off_empty_or_unreadable,
)
