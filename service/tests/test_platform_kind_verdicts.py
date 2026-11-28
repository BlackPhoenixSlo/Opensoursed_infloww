#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import collections  # noqa: E402
import contextlib  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

os.environ.pop("OI_CELL_MAP", None)
import sqlite3  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from itertools import count  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import NamedTuple  # noqa: E402
from unittest.mock import patch  # noqa: E402

import requests  # noqa: E402
from sqlalchemy import select  # noqa: E402

import account_page  # noqa: E402
import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import automation_registry  # noqa: E402
import fansly_shim  # noqa: E402
import llm_client  # noqa: E402
import platforms  # noqa: E402
import promo_create_guard  # noqa: E402
import run_decide  # noqa: E402
import send_ops  # noqa: E402
import side_effect_gate as gate  # noqa: E402
import tenant_keys  # noqa: E402
import test_platform_lift_table as lift_table  # noqa: E402
import webhook_dispatch  # noqa: E402
from _kind_verdict_seeds import (  # noqa: E402
    CHAT_RULES, FAKE_STATE, FAN, HOST, LAPSED, LLM_REPLY, PLATFORM_MESSAGE, SEEDS, WORLDS, ListsOF, OFStandIn, _NUDGE_CFG, _ai, _fan,
    _in, _lists, _out, _rows, _rule, _seen,
    canned_llm, fan_groups, fan_ids, fansly_list, _s4s, no_key, session_for, tagged_lists, threadless,
)
from _kind_verdicts_autoreply import BANNED, LEAK_REPLY, WireOF, typing_on  # noqa: E402
from _kind_verdicts_lifecycle import ONE_SEND  # noqa: E402
from _kind_verdicts_nudge_online import hold_latch, nudge_grant, online_beside  # noqa: E402
from _kind_verdicts_purchase_followup import _thanked  # noqa: E402
from _kind_verdicts_send_welcome import OTHER_FAN, LostReply  # noqa: E402
from _kind_verdicts_s4s_check import EMPTY_POST, IDLESS_POST, POST_ERROR, answers_post  # noqa: E402
from _kind_verdicts_priority_mass import priority_run  # noqa: E402
from automations import _voice, customs_watch, lifecycle_messages, purchase_followup  # noqa: E402
from of_client import OFAPIError, OFClient  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AiDecision, AutomationRun, Fan, FanProfile, FollowupState, MassRun, Message, NudgeState, PriorityMassRecipient, PriorityMassRun, S4SMedia, S4SSlot,
    ScheduledJob, SkipList, SmartList, WelcomeSent,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))
from stateful_fake import StatefulFansly  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="platform_kind_verdicts_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

KIND_VERDICTS = {
    "fansly": {
        "auto_stories": {"story": "gated:platform_lacks:post_story_from_url"},
        "mass_premade": {"drip": "gated:platform_lacks:send_mass_message"},
        "scheduled_send": {"text": "same",
                           "tags": "gated:platform_lacks:tagged_users",
                           "locked": "gated:platform_lacks:locked_text"},
        "scrape_chats": {"sweep": "same"},
        "scrape_fan": {"run": "same"},
        "send_mass_message": {"broadcast": "gated:platform_lacks:send_mass_message"},
        "unsend_messages": {"mass": "gated:platform_lacks:unsend_mass_message", "chat": "same"},
        "welcome_chatter_for_info": {"run": "same", "spanish": "same"},
    },
    "onlyfans": {
        "auto_stories": {"story": "same"},
        "mass_premade": {"drip": "same"},
        "scheduled_send": {"text": "same", "tags": "same", "locked": "same"},
        "scrape_chats": {"sweep": "same"},
        "scrape_fan": {"run": "same"},
        "send_mass_message": {"broadcast": "same"},
        "unsend_messages": {"mass": "same", "chat": "same"},
        "welcome_chatter_for_info": {"run": "same", "spanish": "same"},
    },
}

PAYLOADS = {
    "auto_stories": {"story": {"media_files": [901]}},
    "mass_premade": {"drip": {"messages": [
        {"text": "m1", "online_only": True, "media_folder_id": 5, "price": 10},
        {"text": "m2", "online_only": True, "delay_minutes": 15}]}},
    "scheduled_send": {
        "text": {"fan_id": FAN, "text": "hey", "send_purpose": "manual"},
        "tags": {"fan_id": FAN, "text": "hey", "send_purpose": "manual", "tagged_users": [46901]},
        "locked": {"fan_id": FAN, "text": "hey", "send_purpose": "manual", "locked_text": True, "price": 5},
    },
    "scrape_chats": {"sweep": {}},
    "scrape_fan": {"run": {"fan_ids": [FAN]}},
    "send_mass_message": {"broadcast": {
        "text": "hey all", "user_lists": ["fans"], "exclude_replied_hours": 0, "exclude_inbound_hours": 0}},
    "unsend_messages": {"mass": {"policy": {"mass_text_hours": 8}}, "chat": {"policy": {"text_hours": 1}}},
    "welcome_chatter_for_info": {"run": {}, "spanish": {}},
}

SAME_REASONS = {"reply_mass_funnel": {"landed": "no_active_funnel_runs"}}

SAME_EFFECTS = {
    "fansly": {
        "scheduled_send": {"text": ("POST /message", "table:chats", "table:fans", "table:messages")},
        "scrape_chats": {"sweep": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "scrape_fan": {"run": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "unsend_messages": {"chat": ("POST /message/delete", "table:actions", "table:messages")},
        "welcome_chatter_for_info": dict.fromkeys(("run", "spanish"), (
            "POST /message", "POST /message/ack", "table:chats", "table:fans", "table:messages")),
    },
    "onlyfans": {
        "auto_stories": {"story": ("post_story_from_url",)},
        "mass_premade": {"drip": ("job:mass_premade", "send_mass_message", "table:mass_runs")},
        "scheduled_send": {"text": ("send_message", "table:chats", "table:fans", "table:messages"),
                           "tags": ("send_message", "table:chats", "table:fans", "table:messages"),
                           "locked": ("send_message", "table:chats", "table:fans", "table:messages")},
        "scrape_chats": {"sweep": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "scrape_fan": {"run": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "send_mass_message": {"broadcast": ("send_mass_message", "table:mass_runs")},
        "unsend_messages": {"mass": ("cancel_scheduled", "table:actions", "table:mass_broadcast_cache"),
                            "chat": ("table:actions", "table:messages", "unsend_message")},
        "welcome_chatter_for_info": dict.fromkeys(("run", "spanish"), (
            "mark_chat_read", "send_message", "table:chats", "table:fans", "table:messages")),
    },
}

OWNER_RUNS: dict[str, dict] = {}

PARTIAL_RUNS: dict[str, dict] = {}

DECLARED_WRITES: dict[str, dict] = {}

JOB_SEEDS: dict = {}

MARKER_ALLOWLIST: dict[str, dict[str, str]] = {}

BOOKKEEPING = {
    "automation_runs": "the run row the executor opens and finalises",
    "scheduled_jobs": "the claimed job's disposition; a new job row is still an effect",
    "grok_calls": "the model-call ledger; a model reply is spend, not an effect",
    "grok_daily_cost": "the model-spend counter",
    "fan_lease": "the per-fan send lock; the send it guards is the effect",
}

ERROR_STATUS = "error"
ERROR_COLUMNS = {"ai_decisions": "jev_error"}
UNCITED = ": no captured request"
TYPING_SENDERS = {("autoreply", "run"): {"autoreply.hold_with_typing", "autoreply.apply_typo_throttle"},
                  ("full_ai_chat", "live"): {"full_ai_live.hold_with_typing", "full_ai_turn.apply_typo_throttle"},
                  ("send_welcome", "run"): {"send_welcome.hold_with_typing"},
                  ("welcome_chatter_for_info", "run"): {"welcome_chatter_for_info.hold_with_typing",
                                                       "welcome_chatter_for_info.apply_typo_throttle"},
                  ("reply_mass_funnel", "walk"): {"reply_mass_funnel.hold_with_typing"}}
TYPING_CALLS = {"hold_with_typing": ["autoreply", "full_ai_live", "reply_mass_funnel", "send_welcome",
                                     "welcome_chatter_for_info"],
                "apply_typo_throttle": ["autoreply", "full_ai_turn", "welcome_chatter_for_info"]}
PAID_REFUSALS = {("send_welcome", "paid"): {"send_welcome.hold_with_typing"},
                 ("reply_mass_funnel", "locked"): {"reply_mass_funnel.hold_with_typing"}}
REFUSED_READS = {"send_welcome": {("GET", "/notifications"), ("GET", "/account")}}
LIFTED: dict = {}

for _path in sorted(Path(__file__).parent.glob("_kind_verdicts_*.py")):
    _extra = importlib.import_module(_path.stem)
    for _platform, _kinds in _extra.VERDICTS.items():
        KIND_VERDICTS[_platform] = dict(sorted({**KIND_VERDICTS[_platform], **_kinds}.items()))
    for _platform, _kinds in _extra.SAME_EFFECTS.items():
        SAME_EFFECTS[_platform].update(_kinds)
    PAYLOADS.update(_extra.PAYLOADS)
    SEEDS.update(_extra.SEEDS)
    FAKE_STATE.update(getattr(_extra, "FAKE_STATE", {}))
    WORLDS.update(getattr(_extra, "WORLDS", {}))
    for _platform, _kinds in getattr(_extra, "OWNER_RUNS", {}).items():
        OWNER_RUNS.setdefault(_platform, {}).update(_kinds)
    for _platform, _kinds in getattr(_extra, "PARTIAL_RUNS", {}).items():
        PARTIAL_RUNS.setdefault(_platform, {}).update(_kinds)
    for _platform, _kinds in getattr(_extra, "DECLARED_WRITES", {}).items():
        DECLARED_WRITES.setdefault(_platform, {}).update(_kinds)
    JOB_SEEDS.update(getattr(_extra, "JOB_SEEDS", {}))
    MARKER_ALLOWLIST.update(getattr(_extra, "MARKER_ALLOWLIST", {}))
    TYPING_SENDERS.update(getattr(_extra, "TYPING_SENDERS", {}))
    PAID_REFUSALS.update(getattr(_extra, "PAID_REFUSALS", {}))
    LIFTED.update(getattr(_extra, "LIFTED", {}))
    for _name, _mods in getattr(_extra, "TYPING_CALLS", {}).items():
        TYPING_CALLS.setdefault(_name, []).extend(_mods)

_ACCOUNT_IDS = count(88_220_001)
_REAL_PACED = ax.of_write_paced
_REAL_MAKE_CLIENT = ax._make_client


async def _unpaced(account_id, fn, **kw):
    return await _REAL_PACED(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})


def _tables() -> dict[str, set]:
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        names = [n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n: set(con.execute(f'SELECT * FROM "{n}"').fetchall()) for n in names}
    finally:
        con.close()


def _shapes() -> dict[str, tuple[int | None, int | None, tuple[int, ...]]]:
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        out = {}
        for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            cols = con.execute(f'PRAGMA table_info("{n}")').fetchall()
            names = [c[1] for c in cols]
            out[n] = (names.index("status") if "status" in names else None,
                      names.index(ERROR_COLUMNS[n]) if n in ERROR_COLUMNS else None,
                      tuple(i for i, c in enumerate(cols) if c[5]) or tuple(range(len(cols))))
        return out
    finally:
        con.close()


def effect_tables(before: dict[str, set], after: dict[str, set], shapes: dict) -> set[str]:
    out = set()
    for t, rows in after.items():
        old = before.get(t, set())
        if t in BOOKKEEPING or rows == old:
            continue
        status, error, pk = shapes[t]
        added, removed = rows - old, old - rows
        keys = {tuple(r[i] for i in pk) for r in added}
        failed = [r for r in added if (status is not None and r[status] == ERROR_STATUS)
                  or (error is not None and r[error] is not None)]
        if added and len(failed) == len(added) and all(tuple(r[i] for i in pk) in keys for r in removed):
            continue
        out.add(f"table:{t}")
    return out


async def _new_jobs(aid: str, job_id: int) -> list[str]:
    async with get_session() as s:
        return sorted((await s.execute(select(ScheduledJob.kind).where(
            ScheduledJob.account_id == aid, ScheduledJob.id != job_id))).scalars())


def unlisted_marker_calls(kind: str, calls: list[str], allowlist: dict[str, dict[str, str]]) -> list[str]:
    allowed = allowlist.get(kind, {})
    return [c for c in calls if c not in allowed]


def inventory_drift(verdicts: dict, kinds: list[str]) -> list[str]:
    drift = []
    for platform, rows in verdicts.items():
        drift += [f"{platform}: {k} has no Verdict" for k in sorted(set(kinds) - set(rows))]
        drift += [f"{platform}: {k} is not a registered kind" for k in sorted(set(rows) - set(kinds))]
    return drift


def expected_run(platform: str, kind: str, branch: str) -> tuple | None:
    head, _, tail = KIND_VERDICTS[platform][kind][branch].partition(":")
    if head == "gated":
        if (effects := PARTIAL_RUNS.get(platform, {}).get(kind, {}).get(branch)) is not None:
            return ("partial", f"partial:{tail}", effects, None)
        return ("skipped", tail, tuple(sorted(DECLARED_WRITES.get(platform, {}).get(kind, {}).get(branch, {}))), None)
    if head == "noop":
        return ("ok", tail, (), None)
    if head == "same":
        return ("ok", SAME_REASONS.get(kind, {}).get(branch), SAME_EFFECTS[platform][kind][branch], None)
    return None


async def observe(platform: str, kind: str, branch: str, *, job_kind: str | None = None) -> tuple:
    return (await _drive(platform, kind, branch, job_kind=job_kind))[0]


async def _account(platform: str, seed=None) -> str:
    aid = str(next(_ACCOUNT_IDS))
    async with get_session() as s:
        s.add(Account(id=aid, nickname=aid))
    if seed:
        await seed(aid, platform)
    return aid


async def _drive(platform: str, kind: str, branch: str, *, job_kind: str | None = None, aid: str | None = None,
                 fake=None, world=None, extra: dict | None = None,
                 job_id: int | None = None) -> tuple[tuple, "StatefulFansly | OFStandIn", str]:
    if aid is None:
        aid = await _account(platform)
        if seed := SEEDS.get((kind, branch)):
            extra = await seed(aid, platform)
    if platform == "fansly":
        account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": "fansly"})
        if fake is None:
            fake = StatefulFansly()
            if shape := FAKE_STATE.get((kind, branch)):
                shape(fake)
    elif fake is None:
        fake = OFStandIn(aid)

    def factory(_aid):
        return fake.client() if platform == "fansly" else fake
    if job_id is None:
        async with get_session() as s:
            job = ScheduledJob(account_id=aid, kind=job_kind or kind,
                               payload_json=json.dumps({**PAYLOADS[kind][branch], **(extra or {})}),
                               run_at=datetime.utcnow(), status="pending")
            s.add(job)
            await s.flush()
            job_id = job.id
        if job_seed := JOB_SEEDS.get((kind, branch)):
            await job_seed(aid, job_id)
    before = _tables()
    markers: list[str] = []
    token = fansly_shim.marker_calls.set(markers)
    ax._make_client, ax.of_write_paced = factory, _unpaced
    try:
        with patch.object(llm_client, "_fire", canned_llm()), \
                patch.object(OFClient, "from_account", session_for(platform, fake)), \
                patch.dict("os.environ", {promo_create_guard.HOST_ENV: HOST}), \
                patch.object(tenant_keys, "typesafe_key_for", no_key), \
                (world or WORLDS.get((kind, branch), contextlib.nullcontext))(aid):
            result = await ax.run_once(aid, job_kind or kind)
    finally:
        ax._make_client, ax.of_write_paced = _REAL_MAKE_CLIENT, _REAL_PACED
        fansly_shim.marker_calls.reset(token)
    after = _tables()
    where = f"{platform}/{kind}/{branch}"
    uncited = [u.removesuffix(UNCITED) for u in fake.unmodelled if u.endswith(UNCITED)]
    assert len(uncited) == len(fake.unmodelled), f"{where}: unmodelled provider calls {fake.unmodelled}"
    assert not (bad := unlisted_marker_calls(kind, markers, MARKER_ALLOWLIST)), f"{where}: marked calls {bad}"
    async with get_session() as s:
        run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == aid)
                               .order_by(AutomationRun.id.desc()).limit(1))).scalar_one()
        claimed = await s.get(ScheduledJob, job_id)
    assert claimed.status == "done" or run.status == ERROR_STATUS, f"{where}: job {claimed.status} ({result})"
    if platform == "fansly":
        writes = {f"{m} {p}" for m, p, _b, _q in fake.calls if m != "GET"}
        send_effect = "POST /message"
        recipients = [str(fake.groups.get(body["groupId"], {}).get("partnerAccountId"))
                      for method, path, body, _query in fake.calls if (method, path) == ("POST", "/message")]
    else:
        writes = {c for c in fake.calls if c in OFStandIn.WRITES}
        send_effect = "send_message"
        recipients = fake.send_recipients
    expected_recipient = str(LAPSED) if kind == "expired_message" else FAN
    assert all(recipient == expected_recipient for recipient in recipients), (where, expected_recipient, recipients)
    if len(recipients) > 1:
        writes.remove(send_effect)
        writes.add(f"{send_effect}×{len(recipients)}")
    tables = effect_tables(before, after, _shapes())
    jobs = {f"job:{k}" for k in await _new_jobs(aid, job_id)}
    reason = json.loads(run.stats_json or "{}").get("reason")
    return (run.status, reason, tuple(sorted(writes | tables | jobs)), uncited[0] if uncited else None), fake, aid


def _observed_rows():
    for platform, kinds in KIND_VERDICTS.items():
        for kind, branches in kinds.items():
            for branch in branches:
                if (want := expected_run(platform, kind, branch)) is not None:
                    yield platform, kind, branch, want


def case_kind_verdicts_is_a_literal():
    assert lift_table.kind_verdicts() == KIND_VERDICTS


def case_every_registered_kind_has_a_verdict_on_every_platform():
    automation_registry.load_automation_plugins()
    assert automation_registry.failed_plugins() == frozenset(), automation_registry.failed_plugins()
    kinds = automation_registry.registered_kinds()
    assert inventory_drift(KIND_VERDICTS, kinds) == [], inventory_drift(KIND_VERDICTS, kinds)
    assert set(KIND_VERDICTS) == {p.key for p in platforms.ALL}, set(KIND_VERDICTS)


def case_inventory_drift_names_a_kind_without_a_row_and_a_row_without_a_kind():
    assert inventory_drift({"fansly": {"a": {}, "b": {}}}, ["a", "b"]) == []
    assert inventory_drift({"fansly": {"a": {}}}, ["a", "b"]) == ["fansly: b has no Verdict"]
    assert inventory_drift({"fansly": {"a": {}, "b": {}}}, ["a"]) == ["fansly: b is not a registered kind"]


def case_branch_keys_equal_between_verdicts_and_payloads():
    for platform, kinds in KIND_VERDICTS.items():
        for kind, branches in kinds.items():
            assert set(branches) == set(PAYLOADS[kind]), (platform, kind, set(branches), set(PAYLOADS[kind]))
    assert set(PAYLOADS) == set(KIND_VERDICTS["fansly"]), set(PAYLOADS) ^ set(KIND_VERDICTS["fansly"])
    assert all(branch in PAYLOADS.get(kind, {}) for kind, branch in SEEDS), set(SEEDS)


def case_every_row_is_observed_or_owned():
    for platform, kinds in KIND_VERDICTS.items():
        for kind, branches in kinds.items():
            for branch, verdict in branches.items():
                head, _, tail = verdict.partition(":")
                effects = SAME_EFFECTS.get(platform, {}).get(kind, {}).get(branch)
                where = (platform, kind, branch, verdict)
                owned = OWNER_RUNS.get(platform, {}).get(kind, {}).get(branch)
                if head == "same":
                    assert not tail and effects and owned is None, where
                    assert not any(e.startswith("GET ") for e in effects), where
                else:
                    assert head in {"owner", "gated", "noop"} and tail and effects is None, where
                    assert head != "owner" or (tail.isdigit() and owned), where
                    assert head == "owner" or owned is None, where
    for platform, kinds in DECLARED_WRITES.items():
        for kind, branches in kinds.items():
            for branch, writes in branches.items():
                assert KIND_VERDICTS[platform][kind][branch].startswith("gated:"), (platform, kind, branch)
                assert writes and all(w.startswith("table:") and r.strip() for w, r in writes.items()), writes
    for table in (SAME_EFFECTS, OWNER_RUNS, PARTIAL_RUNS):
        for platform, kinds in table.items():
            for kind, branches in kinds.items():
                for branch in branches:
                    assert branch in KIND_VERDICTS[platform][kind], (platform, kind, branch)
    for platform, kinds in PARTIAL_RUNS.items():
        for kind, branches in kinds.items():
            for branch, effects in branches.items():
                assert KIND_VERDICTS[platform][kind][branch].startswith("gated:") and effects, (platform, kind, branch)


async def case_every_owner_row_matches_its_recorded_run():
    misses = []
    for platform, kinds in OWNER_RUNS.items():
        for kind, branches in kinds.items():
            for branch, recorded in branches.items():
                where = f"{platform}/{kind}/{branch}"
                assert len(recorded) == 4 and recorded[0] != "skipped", where
                if (got := await observe(platform, kind, branch)) != recorded:
                    misses.append(f"{where}: observed {got}, recorded {recorded}")
    assert not misses, "\n".join(misses)


def case_reads_and_error_rows_are_not_effects():
    shapes = {"mass_runs": (1, None, (0,)), "fans": (None, None, (0,)), "ai_decisions": (1, 2, (0,))}
    base = {"mass_runs": {(1, "ok")}, "fans": {(1,)}, "ai_decisions": set()}
    assert effect_tables(base, base, shapes) == set()
    assert effect_tables(base, {**base, "mass_runs": {(1, "ok"), (2, "error")}}, shapes) == set()
    assert effect_tables(base, {**base, "mass_runs": {(1, "error")}}, shapes) == set()
    assert effect_tables(base, {**base, "mass_runs": {(1, "ok"), (2, "sent")}}, shapes) == {"table:mass_runs"}
    assert effect_tables(base, {**base, "mass_runs": set()}, shapes) == {"table:mass_runs"}
    assert effect_tables(base, {**base, "fans": {(1,), (2,)}}, shapes) == {"table:fans"}
    assert effect_tables(base, {**base, "ai_decisions": {(1, "planned", "no TypeSafe key")}}, shapes) == set()
    assert effect_tables(base, {**base, "ai_decisions": {(1, "planned", None)}}, shapes) == {"table:ai_decisions"}


def case_every_observed_fansly_branch_has_an_onlyfans_control():
    for platform, kind, branch, _ in _observed_rows():
        if platform == "fansly":
            assert expected_run("onlyfans", kind, branch) is not None, f"{kind}/{branch} has no OnlyFans control"


def case_unlisted_marker_call_fails_and_a_reasoned_one_passes():
    allow = {"k": {"hide_vault_media": "the lane catches the refusal and records it"}}
    assert unlisted_marker_calls("k", ["hide_vault_media"], allow) == []
    assert unlisted_marker_calls("k", ["send_mass_message"], allow) == ["send_mass_message"]
    assert unlisted_marker_calls("other", ["hide_vault_media"], allow) == ["hide_vault_media"]
    assert all(r.strip() for rows in MARKER_ALLOWLIST.values() for r in rows.values())


async def case_every_observed_row_matches_its_run():
    misses = []
    for platform, kind, branch, want in _observed_rows():
        got = await observe(platform, kind, branch)
        if got != want:
            misses.append(f"{platform}/{kind}/{branch}: observed {got}, row says {want}")
    assert not misses, "\n".join(misses)


async def case_legacy_alias_is_driven_through_get_automation():
    assert automation_registry.LEGACY_KINDS == {"of_ai_chat": "welcome_chatter_for_info"}
    for legacy, live in automation_registry.LEGACY_KINDS.items():
        assert automation_registry.get_automation(legacy) is automation_registry.get_automation(live)
        for platform in KIND_VERDICTS:
            branch = next(iter(PAYLOADS[live]))
            got = await observe(platform, live, branch, job_kind=legacy)
            want = await observe(platform, live, branch)
            assert got == want, (platform, legacy, got, want)


async def case_a_send_swapped_for_reads_and_an_error_row_turns_the_harness_red():
    async def reads_only(aid, _payload, *, run_id):
        ax._make_client(aid).list_chats()
        async with get_session() as s:
            s.add(MassRun(account_id=aid, automation_kind="scheduled_send", status=ERROR_STATUS))
        return {}

    for platform in KIND_VERDICTS:
        with patch.dict(automation_registry._REGISTRY, {"scheduled_send": reads_only}):
            got = await observe(platform, "scheduled_send", "text")
        assert got == ("ok", None, (), None), (platform, got)
        assert got != expected_run(platform, "scheduled_send", "text"), f"{platform}: reads and an error row matched: {got}"


async def _observed_with_rows(platform: str, kind: str, branch: str) -> tuple[tuple, list, dict, dict, dict]:
    got, fake, aid = await _drive(platform, kind, branch)
    async with get_session() as s:
        run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == aid))).scalar_one()
        rows = (await s.execute(select(SmartList).where(SmartList.account_id == aid))).scalars().all()
    by_name = {r.name: (r.sync_state, r.of_list_id, r.member_count, r.sync_error, r.is_active) for r in rows}
    return got, fake.calls, json.loads(run.stats_json or "{}"), by_name, {r.name: r.id for r in rows}


async def case_refused_auto_follow_source_sends_no_request():
    for branch in ("expired", "refused_list", "full_pool"):
        got, fake, _aid = await _drive("fansly", "auto_follow", branch)
        assert got == expected_run("fansly", "auto_follow", branch), (branch, got)
        assert fake.calls == [], (branch, fake.calls)


async def case_welcome_toggle_refuses_before_client_lease_or_read_and_onlyfans_reads_its_setting():
    touched: list[str] = []

    def spy(name):
        async def record(*_a, **_k):
            touched.append(name)
            return True
        return record

    class Counted(StatefulFansly):
        def client(self):
            touched.append("client")
            return super().client()

    fake = Counted()
    FAKE_STATE[("send_welcome", "toggle")](fake)
    with patch.object(ax, "acquire_fan_lease", spy("lease")), patch.object(ax, "fan_on_cooldown", spy("cooldown")):
        got, fake, _aid = await _drive("fansly", "send_welcome", "toggle", fake=fake)
    assert got == ("skipped", "platform_lacks:my_settings", (), None), got
    assert (fake.calls, touched) == ([], []), (fake.calls, touched)
    got, fake, _aid = await _drive("onlyfans", "send_welcome", "toggle")
    assert fake.calls[:2] == ["my_settings", "message_templates"] and "send_message" not in fake.calls, fake.calls


_FOLLOW_BACK = ("POST", f"/account/{FAN}/followers")


def _writes(calls: list) -> list[tuple]:
    return [(c[0], c[1]) for c in calls if c[0] != "GET"]


def _sent_to(calls: list) -> list[tuple]:
    return [(b["groupId"], b["content"]) for m, p, b, _q in calls if (m, p) == ("POST", "/message")]


async def _welcomed(aid: str) -> list[int]:
    async with get_session() as s:
        return list((await s.execute(select(WelcomeSent.fan_id).where(WelcomeSent.account_id == aid))).scalars())


_SEEN = ("subscribers_seen", "new_subscribers", "welcomes_sent", "errors", "skipped_cooldown")


async def _welcome_stats(aid: str) -> list[tuple]:
    async with get_session() as s:
        rows = [json.loads(js) for js in (await s.execute(select(AutomationRun.stats_json).where(
            AutomationRun.account_id == aid).order_by(AutomationRun.id))).scalars()]
    return [(*(st[k] for k in _SEEN), sum(v for k, v in st.items() if k.startswith("skipped_") or k == "delayed"))
            for st in rows]


def _threadless(branch: str, fake=None):
    fake = fake or StatefulFansly()
    FAKE_STATE[("send_welcome", branch)](fake)
    threadless(fake)
    return fake


async def case_a_follow_a_free_trial_or_both_welcome_once_in_one_new_group_and_the_next_tick_sends_nothing():
    for branch in ("follow", "run", "both"):
        fake = _threadless(branch)
        t = await _turn("fansly", "send_welcome", branch, fake=fake)
        groups = fan_groups(fake)
        assert t.got[:2] == t.again[:2] == ("ok", None), (branch, t.got, t.again)
        assert _writes(t.calls) == [("POST", "/group"), ("POST", "/message"), _FOLLOW_BACK], (branch, t.calls)
        assert (len(groups), [(b["groupId"], b["content"]) for p, b in t.wire if p == "/message"]) == (
            1, [(groups[0], "welcome babe")]), (branch, groups, t.wire)
        assert (_writes(t.later), t.frames) == ([], []), (branch, t.later)
        assert await _welcomed(t.aid) == [int(FAN)], branch
        assert await _welcome_stats(t.aid) == [(1, 1, 1, 0, 0, 0), (1, 0, 0, 0, 0, 0)], branch
        assert await _runs_and_jobs(t.aid) == ([("ok", None)] * 2, [("send_welcome", "done")] * 2), branch


async def case_a_trigger_past_limit_on_a_partial_page_is_never_welcomed_because_only_page_one_is_read():
    got, fake, aid = await _drive("fansly", "send_welcome", "partial")
    first = list(fake.calls)
    again, _fake, _aid = await _drive("fansly", "send_welcome", "partial", aid=aid, fake=fake)
    page = fake.client().notifications(limit=1, type="subscribed")
    assert ([str(row["user"]["id"]) for row in page["list"]], page["hasMore"]) == ([FAN], True), page
    assert got[:2] == again[:2] == ("ok", None), (got, again)
    assert [p for m, p, _b, _q in first if m == "GET"].count("/notifications") == 2, first
    assert (await _welcomed(aid), _writes(fake.calls[len(first):])) == ([int(FAN)], []), fake.calls
    assert OTHER_FAN not in {fake.groups[g]["partnerAccountId"] for g, _t in _sent_to(fake.calls)}
    assert await _welcome_stats(aid) == [(1, 1, 1, 0, 0, 0), (1, 0, 0, 0, 0, 0)]


async def case_a_lost_welcome_response_in_cell_mode_leaves_one_message_an_uncertain_claim_and_a_retry_sends_nothing():
    fake, aid = _threadless("follow", LostReply()), await _account("fansly")
    env = {"OI_CELL_MAP": "/nonexistent/placement.json", "OI_ACCOUNTS": f"fansly:{aid}", "OI_EPOCH": "1"}
    skipped: list = []
    real_skip = send_ops.skip_fan

    def spy(e, **kw):
        skipped.append(real_skip(e, **kw))
        return skipped[-1]
    with patch.object(send_ops, "_path", None), patch.object(send_ops, "skip_fan", spy), patch.dict(os.environ, env):
        send_ops.install(f"sqlite:///{_harness.DB_PATH}")
        got, _fake, _aid = await _drive("fansly", "send_welcome", "follow", aid=aid, fake=fake)
        first = list(fake.calls)
        with contextlib.closing(sqlite3.connect(_harness.DB_PATH)) as db:
            claims = db.execute("SELECT kind, target, state FROM send_ops WHERE account=?", (aid,)).fetchall()
        tick1 = list(skipped)
        again, _fake, _aid = await _drive("fansly", "send_welcome", "follow", aid=aid, fake=fake)
    retry = _writes(fake.calls[len(first):])
    assert _writes(first) == [("POST", "/group"), ("POST", "/message")] and len(fan_groups(fake)) == 1, first
    assert claims == [("send_welcome", FAN, "uncertain")], claims
    assert (tick1, skipped[len(tick1):]) == ([None], ["op_uncertain"]), skipped
    assert (retry.count(("POST", "/message")), retry.count(("POST", "/group"))) == (0, 0), retry
    assert await _welcomed(aid) == [], (got, again)
    assert await _runs_and_jobs(aid) == ([("ok", None)] * 2, [("send_welcome", "done")] * 2)
    assert await _welcome_stats(aid) == [(1, 1, 0, 1, 0, 0), (1, 1, 0, 0, 0, 0)]


async def _due_follow_up(aid: str) -> int:
    async with get_session() as s:
        job = (await s.execute(select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                                          ScheduledJob.status == "pending"))).scalar_one()
        job.run_at = datetime.utcnow()
        for fan in (await s.execute(select(Fan).where(Fan.account_id == aid))).scalars():
            fan.automation_paused_until = None
        return job.id


async def case_a_welcome_follow_up_lands_in_the_welcome_thread_and_a_fan_reply_stops_the_next_step():
    steps = [{"text": "still there?", "delay_minutes": 60}, {"text": "miss you", "delay_minutes": 60}]
    fake, aid = _threadless("follow"), await _account("fansly")
    got, _fake, _aid = await _drive("fansly", "send_welcome", "follow", aid=aid, fake=fake, extra={"follow_ups": steps})
    (thread, _text), = _sent_to(fake.calls)
    welcomed = len(fake.calls)
    with typing_on(aid, "fansly", fake):
        step1, _fake, _aid = await _drive("fansly", "send_welcome", "follow", aid=aid, fake=fake,
                                          job_id=await _due_follow_up(aid))
        await _rows(_in(timedelta(0)))(aid, "fansly")
        replied = len(fake.calls)
        step2, _fake, _aid = await _drive("fansly", "send_welcome", "follow", aid=aid, fake=fake,
                                          job_id=await _due_follow_up(aid))
    assert "job:send_welcome" in got[2] and step1[:2] == ("ok", None), (got, step1)
    assert _calls("fansly", fake.calls[welcomed:replied]) == [_GROUPS_READ, ("POST", "/message", "still there?")], \
        fake.calls[welcomed:replied]
    assert _sent_to(fake.calls[welcomed:replied]) == [(thread, "still there?")], fake.calls[welcomed:replied]
    assert (step2[:2], fake.calls[replied:]) == (("ok", "stopped_on_reply"), []), (step2, fake.calls[replied:])
    assert await _runs_and_jobs(aid) == ([("ok", None)] * 2 + [("ok", "stopped_on_reply")], [("send_welcome", "done")] * 3)


_LIFECYCLE = {"expiry_message": "platform_lacks:renewal_state", "expired_message": "platform_lacks:lapse_detection",
              "resubscribe_message": "platform_lacks:return_detection"}


@contextlib.contextmanager
def _lifecycle_probe():
    touched: list[str] = []

    def spy(name):
        async def record(*_a, **_k):
            touched.append(name)
            return True
        return record

    class Counted(StatefulFansly):
        def client(self):
            touched.append("client")
            return super().client()

    with patch.object(ax, "acquire_fan_lease", spy("lease")), patch.object(ax, "fan_on_cooldown", spy("cooldown")):
        yield touched, Counted


async def case_fansly_lifecycle_run_forced_and_dry_refuse_before_client_cooldown_lease_or_any_request():
    with _lifecycle_probe() as (touched, Counted):
        for kind, reason in _LIFECYCLE.items():
            for branch in ("run", "forced", "dry"):
                touched.clear()
                got, fake, _aid = await _drive("fansly", kind, branch, fake=Counted())
                assert got == ("skipped", reason, (), None), (kind, branch, got)
                assert (fake.calls, touched) == ([], []), (kind, branch, fake.calls, touched)


async def case_lifecycle_refusal_follows_disabled_and_comes_before_no_text_and_the_discount_refusal():
    discount = [{"variants": ["renew for 20% off"], "discount": {"percent": 20, "months": 2}}]
    table = [
        ("fansly", {"enabled": False}, ("ok", "disabled", (), None)),
        ("onlyfans", {"enabled": False}, ("ok", "disabled", (), None)),
        ("fansly", {"messages": []}, ("skipped", "platform_lacks:renewal_state", (), None)),
        ("onlyfans", {"messages": []}, ("ok", "no_text", (), None)),
        ("fansly", {"messages": discount}, ("skipped", "platform_lacks:renewal_state", (), None)),
    ]
    for platform, steps, want in table:
        aid = await _account(platform, _rows(_fan(), _rule("expiry_message", **steps)))
        got, fake, _aid = await _drive(platform, "expiry_message", "run", aid=aid)
        assert got == want, (platform, steps, got)
        assert fake.calls == [], (platform, steps, fake.calls)


async def case_a_follow_up_the_lane_queued_refuses_on_fansly_before_client_cooldown_lease_or_any_request():
    steps = [{"text": "still there?", "delay_minutes": 60}]
    table = [("fansly", kind, ("skipped", reason, (), None)) for kind, reason in _LIFECYCLE.items()]
    table += [(platform, kind, ("ok", None, ONE_SEND[platform], None))
              for platform, kind in (("onlyfans", "expiry_message"), ("onlyfans", "expired_message"),
                                     ("onlyfans", "resubscribe_message"), ("fansly", "birthday_message"))]
    for platform, kind, want in table:
        fan = LAPSED if kind == "expired_message" else int(FAN)
        aid = await _account(platform, SEEDS[(kind, "run")])
        await lifecycle_messages.schedule_follow_ups(aid, kind, fan, steps, None, event="e1")
        async with get_session() as s:
            job = (await s.execute(select(ScheduledJob).where(ScheduledJob.account_id == aid))).scalar_one()
            job.run_at, job_id = datetime.utcnow(), job.id
        if want[0] != "skipped":
            got, _fake, _aid = await _drive(platform, kind, "follow_up", aid=aid, job_id=job_id)
            assert got == want, (platform, kind, got)
            continue
        with _lifecycle_probe() as (touched, Counted):
            got, fake, _aid = await _drive(platform, kind, "follow_up", aid=aid, job_id=job_id, fake=Counted())
        assert got == want, (platform, kind, got)
        assert (fake.calls, touched) == ([], []), (platform, kind, fake.calls, touched)


@contextlib.contextmanager
def _customs_reads():
    reads: list[str] = []
    real = customs_watch.get_session

    def counted():
        reads.append("session")
        return real()
    with patch.object(customs_watch, "get_session", counted):
        yield reads


async def case_fansly_customs_watch_refuses_before_any_read_and_keeps_the_owed_flag():
    table = [("fansly", ("skipped", "platform_lacks:tip_ledger", (), None), False, False),
             ("onlyfans", ("ok", None, ("table:fans",), None), True, True)]
    for platform, want, read, cleared in table:
        with _customs_reads() as reads:
            got, fake, aid = await _drive(platform, "customs_watch", "owed")
        async with get_session() as s:
            owed = (await s.get(Fan, {"account_id": aid, "fan_id": int(FAN)})).customs_owed_at
        assert got == want, (platform, got)
        assert fake.calls == [], (platform, fake.calls)
        assert (bool(reads), owed is None) == (read, cleared), (platform, reads, owed)


async def case_an_inbound_tip_on_fansly_enqueues_no_customs_watch_job_and_reads_no_watch_flags():
    flags_read: list[str] = []
    real = customs_watch.watch_flags

    async def counted(aid):
        flags_read.append(aid)
        return await real(aid)
    for platform, want_jobs, reads_flags in (("fansly", [], False), ("onlyfans", ["customs_watch"], True)):
        aid = await _account(platform, _rows(_fan(), _rule("customs_watch")))
        account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": platform})
        flags_read.clear()
        with patch.object(customs_watch, "watch_flags", counted):
            await webhook_dispatch.on_inbound_tip(aid, int(FAN), 1, 20_000)
        async with get_session() as s:
            jobs = list((await s.execute(select(ScheduledJob.kind).where(ScheduledJob.account_id == aid))).scalars())
        assert (jobs, flags_read) == (want_jobs, [aid] if reads_flags else []), (platform, jobs, flags_read)


_PURCHASE_LINKAGE = ("skipped", "platform_lacks:purchase_linkage", (), None)


@contextlib.contextmanager
def _purchase_probe():
    touched: list[str] = []

    def spy(name):
        real = getattr(purchase_followup, name)

        async def record(*a, **k):
            touched.append(name)
            return await real(*a, **k)
        return record
    with contextlib.ExitStack() as stack:
        for name in ("_purchases", "_claimed", "_thanked_recently", "_claim"):
            stack.enter_context(patch.object(purchase_followup, name, spy(name)))
        yield touched


async def case_purchase_linkage_refuses_after_the_config_reasons_and_before_any_purchase_read_claim_fold_or_call():
    paid = _out(timedelta(hours=2), price_cents=500, is_paid=True, purchased_at=datetime.utcnow() - timedelta(hours=1))
    unpaid = _out(timedelta(hours=2))
    thanked = (paid, _thanked)
    reads = ["_purchases", "_claimed", "_thanked_recently"]
    sent = ("send_message", "table:chats", "table:fans", "table:messages", "table:purchase_followup_claims")
    dry = {"dry_run": True}
    table = [
        ("fansly", (paid,), {"enabled": False}, {}, ("ok", "disabled", (), None), [], []),
        ("fansly", (paid,), {"text": ""}, {}, ("ok", "no_text", (), None), [], []),
        ("fansly", (paid,), {"enabled_at": None}, {}, ("ok", "no_enabled_at", (), None), [], []),
        ("fansly", (paid,), {"ends_at": "2026-01-02T00:00:00"}, {}, ("ok", "expired", (), None), [], []),
        ("fansly", (paid,), {"starts_at": "2099-01-01T00:00:00"}, {}, ("ok", "scheduled", (), None), [], []),
        ("fansly", (paid,), {}, {}, _PURCHASE_LINKAGE, [], []),
        ("fansly", (unpaid,), {}, {}, _PURCHASE_LINKAGE, [], []),
        ("fansly", thanked, {}, {}, _PURCHASE_LINKAGE, [], []),
        ("fansly", (paid,), {}, dry, _PURCHASE_LINKAGE, [], []),
        ("onlyfans", (paid,), {}, {}, ("ok", None, sent, None), [*reads, "_claim"], ["send_message"]),
        ("onlyfans", (unpaid,), {}, {}, ("ok", None, (), None), reads, []),
        ("onlyfans", thanked, {}, {}, ("ok", None, ("table:purchase_followup_claims",), None), [*reads, "_claim"], []),
        ("onlyfans", (paid,), {}, dry, ("ok", None, (), None), reads, []),
    ]
    for platform, rows, cfg, extra, want, steps, calls in table:
        aid = await _account(platform, _rows(_fan(), _rule("purchase_followup", **{"text": "thanks babe", **cfg}), *rows))
        with _purchase_probe() as touched:
            got, fake, _aid = await _drive(platform, "purchase_followup", "run", aid=aid, extra=extra)
        assert (got, touched, fake.calls) == (want, steps, calls), (platform, cfg, extra, got, touched, fake.calls)


async def case_cell_mode_holds_a_due_purchase_followup_with_zero_provider_calls_and_ends_done():
    for platform in ("fansly", "onlyfans"):
        with _purchase_probe() as touched, patch.dict(os.environ, {"OI_CELL_MAP": "/nonexistent/placement.json"}):
            got, fake, _aid = await _drive(platform, "purchase_followup", "run")
        assert (got, touched, fake.calls) == (("skipped", "no_anchor", (), None), [], []), (platform, got, touched)


def _wire(platform: str, fake) -> list[tuple]:
    if platform == "fansly":
        return [(p, b) for m, p, b, _q in fake.calls if m == "POST"]
    return [(p.split("/api2/v2", 1)[1], b) for _m, p, b in fake.wire]


def _calls(platform: str, calls: list) -> list:
    if platform == "fansly":
        return [(m, p, b.get("content", b) if b else b) for m, p, b, _q in calls]
    return list(calls)


class Turn(NamedTuple):
    aid: str
    got: tuple
    calls: list
    wire: list
    again: tuple
    later: list
    frames: list


async def _turn(platform: str, kind: str = "autoreply", branch: str = "run", seed=None, world=None,
                fake=None) -> Turn:
    aid = await _account(platform)
    extra = await seed(aid, platform) if (seed := seed or SEEDS.get((kind, branch))) else None
    fake = fake or (StatefulFansly() if platform == "fansly" else WireOF(aid))
    world = world or WORLDS.get((kind, branch))
    with typing_on(aid, platform, fake) as frames:
        got, _fake, _aid = await _drive(platform, kind, branch, aid=aid, fake=fake, extra=extra, world=world)
        calls = list(fake.calls)
        wire = _wire(platform, fake)
        again, _fake, _aid = await _drive(platform, kind, branch, aid=aid, fake=fake, extra=extra, world=world)
    return Turn(aid, got, _calls(platform, calls), wire, again, _calls(platform, fake.calls[len(calls):]), frames)


_FAN_GROUP = "900000000000000101"
_GROUPS_READ = ("GET", "/messaging/groups", None)
_TYPING = {"fansly": ("POST /message/typing",), "onlyfans": ()}
_TYPING_POST = ("POST", "/message/typing", {"groupId": _FAN_GROUP})
_FRAME = {"act": "typing", "typing_to": int(FAN)}


def _of_body(text: str) -> dict:
    return {"text": f"<p>{text}</p>", "lockedText": False, "mediaFiles": [], "price": 0, "previews": [],
            "rfTag": [], "rfGuest": [], "rfPartner": [], "isForward": False}


def _of_send(text: str) -> tuple:
    return (f"/chats/{FAN}/messages", _of_body(text))


def _fansly_send(text: str) -> tuple:
    return ("/message", {"type": 1, "attachments": [], "likes": [], "content": text, "groupId": _FAN_GROUP,
                         "inReplyTo": None, "scheduledFor": 0})


def _unstamped(wire: list[tuple]) -> list[tuple]:
    return [(p, {k: v for k, v in b.items() if k != "createdAt"}) for p, b in wire]


def _visible(platform: str, wire: list[tuple]) -> list[str]:
    if platform == "fansly":
        return [b["content"] for p, b in wire if p == "/message"]
    return [b["text"].removeprefix("<p>").removesuffix("</p>") for _p, b in wire]


def _typed(platform: str, want: tuple) -> tuple:
    return (*want[:2], tuple(sorted(want[2] + _TYPING[platform])), None)


async def _runs_and_jobs(aid: str) -> tuple[list, list]:
    async with get_session() as s:
        runs = (await s.execute(select(AutomationRun.status, AutomationRun.stats_json)
                                .where(AutomationRun.account_id == aid).order_by(AutomationRun.id))).all()
        jobs = (await s.execute(select(ScheduledJob.kind, ScheduledJob.status)
                                .where(ScheduledJob.account_id == aid).order_by(ScheduledJob.id))).all()
    return [(st, json.loads(js or "{}").get("reason")) for st, js in runs], [tuple(j) for j in jobs]


async def case_one_autoreply_turn_sends_the_same_visible_text_on_both_platforms_each_on_its_own_wire():
    bubbles = ["hey you", "tell me more"]
    want_wire = {"fansly": [("/message/typing", {"groupId": _FAN_GROUP}), *map(_fansly_send, bubbles)],
                 "onlyfans": list(map(_of_send, bubbles))}
    want_calls = {"fansly": [_GROUPS_READ, _TYPING_POST, _GROUPS_READ,
                             ("POST", "/message", "hey you"), ("POST", "/message", "tell me more")],
                  "onlyfans": ["send_message", "send_message"]}
    want_frames = {"fansly": [], "onlyfans": [_FRAME] * 2}
    for platform in ("fansly", "onlyfans"):
        t = await _turn(platform)
        assert t.got == _typed(platform, expected_run(platform, "autoreply", "run")), (platform, t.got)
        assert (_visible(platform, t.wire), _unstamped(t.wire)) == (bubbles, want_wire[platform]), (platform, t.wire)
        assert (t.calls, t.frames) == (want_calls[platform], want_frames[platform]), (platform, t.calls, t.frames)
        assert (t.again[:2], t.later) == (("ok", None), []), (platform, t.again, t.later)
        assert await _runs_and_jobs(t.aid) == ([("ok", None)] * 2, [("autoreply", "done")] * 2), platform


async def _no_anchor_in_cell_mode(platform: str, kind: str, branch: str) -> list:
    real = ax.run_once
    returned = []

    async def spy(*a, **k):
        returned.append(await real(*a, **k))
        return returned[-1]
    aid = await _account(platform)
    extra = await SEEDS[(kind, branch)](aid, platform)
    fake = StatefulFansly() if platform == "fansly" else WireOF(aid)
    if platform == "fansly" and (shape := FAKE_STATE.get((kind, branch))):
        shape(fake)
    where = (platform, kind, branch)
    with typing_on(aid, platform, fake) as frames, patch.object(ax, "run_once", spy), \
            patch.dict(os.environ, {"OI_CELL_MAP": "/nonexistent/placement.json"}):
        got, _fake, _aid = await _drive(platform, kind, branch, aid=aid, fake=fake, extra=extra)
    async with get_session() as s:
        run_ids = (await s.execute(select(AutomationRun.id).where(AutomationRun.account_id == aid))).scalars().all()
    assert returned == [{"status": "skipped", "reason": "no_anchor", "run_id": run_ids[0]}], (where, returned)
    assert (got, fake.calls, frames) == (("skipped", "no_anchor", (), None), [], []), (where, got, fake.calls)
    assert await _runs_and_jobs(aid) == ([("skipped", "no_anchor")], [(kind, "done")]), where
    return fan_groups(fake) if platform == "fansly" else []


async def case_cell_mode_autoreply_returns_no_anchor_with_zero_provider_calls_on_both_platforms():
    for platform in ("fansly", "onlyfans"):
        await _no_anchor_in_cell_mode(platform, "autoreply", "run")


async def case_a_banned_word_in_the_autoreply_sends_and_types_nothing_on_both_platforms():
    for platform in ("fansly", "onlyfans"):
        t = await _turn(platform, seed=BANNED)
        async with get_session() as s:
            stats = [json.loads(j) for j in (await s.execute(select(AutomationRun.stats_json).where(
                AutomationRun.account_id == t.aid).order_by(AutomationRun.id))).scalars()]
        assert (t.got, t.calls, t.wire, t.later, t.frames) == (("ok", None, (), None), [], [], [], []), (platform, t)
        assert [st["skipped_banned"] for st in stats] == [1, 1], (platform, stats)
        assert (await _runs_and_jobs(t.aid))[1] == [("autoreply", "done")] * 2, platform


async def case_a_leaking_autoreply_sends_one_canned_deflection_on_both_platforms():
    sent = {}
    for platform in ("fansly", "onlyfans"):
        t = await _turn(platform, "autoreply", "leak")
        sent[platform] = _visible(platform, t.wire)
        assert len(sent[platform]) == 1 and sent[platform][0] in _voice.HER.off_deflections, (platform, sent)
        want_calls = {"fansly": [_GROUPS_READ, _TYPING_POST, _GROUPS_READ, ("POST", "/message", sent[platform][0])],
                      "onlyfans": ["send_message"]}
        assert t.got == _typed(platform, expected_run(platform, "autoreply", "leak")), (platform, t.got)
        assert not any("snap" in json.dumps(b) for _p, b in t.wire), (platform, t.wire)
        assert (t.calls, t.frames) == (want_calls[platform], [] if platform == "fansly" else [_FRAME]), (platform, t)
        assert (t.again[:2], t.later) == (("ok", None), []), (platform, t.again, t.later)
        assert await _runs_and_jobs(t.aid) == ([("ok", None)] * 2, [("autoreply", "done")] * 2), platform
    assert sent["fansly"] == sent["onlyfans"], (sent, LEAK_REPLY)


async def case_the_spanish_welcome_sends_the_same_restricted_spanish_text_on_both_platforms():
    text = "estás doormida? cuéntame más"
    ack = ("/message/ack", {"messageIds": ["900000000000000304"], "type": 2})
    want_wire = {"fansly": [("/message/typing", {"groupId": _FAN_GROUP}), _fansly_send(text), ack],
                 "onlyfans": [_of_send(text)]}
    want_calls = {"fansly": [_GROUPS_READ, _TYPING_POST, _GROUPS_READ, ("POST", "/message", text),
                             ("GET", "/message", None), ("POST", *ack)],
                  "onlyfans": ["send_message", "mark_chat_read"]}
    for platform in ("fansly", "onlyfans"):
        t = await _turn(platform, "welcome_chatter_for_info", "spanish")
        assert t.got == _typed(platform, expected_run(platform, "welcome_chatter_for_info", "spanish")), (platform, t.got)
        assert (_visible(platform, t.wire), _unstamped(t.wire)) == ([text], want_wire[platform]), (platform, t.wire)
        assert (t.calls, t.frames) == (want_calls[platform], [] if platform == "fansly" else [_FRAME]), (platform, t)
        assert (t.again[:2], t.later) == (("ok", None), []), (platform, t.again, t.later)
        assert await _runs_and_jobs(t.aid) == ([("ok", None)] * 2, [("welcome_chatter_for_info", "done")] * 2), platform


_FOLLOWUP_STATS = ("eligible", "followups_sent", "skipped_cooldown", "skipped_locked", "skipped_guard",
                   "state_advanced", "errors")
_FOLLOWUP_TICKS = [(1, 1, 0, 0, 0, 1, 0), (1, 0, 0, 0, 0, 0, 0)]


async def _followup_ticks(aid: str) -> tuple[list, list, str, bool]:
    async with get_session() as s:
        stats = [json.loads(js) for js in (await s.execute(select(AutomationRun.stats_json).where(
            AutomationRun.account_id == aid).order_by(AutomationRun.id))).scalars()]
        state = await s.get(FollowupState, (aid, int(FAN)))
    return ([tuple(st[k] for k in _FOLLOWUP_STATS) for st in stats], sorted(json.loads(state.messages_sent)),
            state.phase, await ax.fan_on_cooldown(aid, int(FAN)))


async def case_send_followup_sends_once_to_an_anchored_paying_fan_and_the_next_tick_is_held_by_its_step_not_a_cooldown():
    want_calls = {"fansly": [_GROUPS_READ, ("POST", "/message", LLM_REPLY)], "onlyfans": ["send_message"]}
    want_wire = {"fansly": [_fansly_send(LLM_REPLY)], "onlyfans": [_of_send(LLM_REPLY)]}
    for platform in ("fansly", "onlyfans"):
        t = await _turn(platform, "send_followup", "run")
        assert t.got == expected_run(platform, "send_followup", "run"), (platform, t.got)
        assert (_unstamped(t.wire), t.calls, t.frames) == (want_wire[platform], want_calls[platform], []), (platform, t)
        assert (t.again[:2], t.later) == (("ok", None), []), (platform, t.again, t.later)
        assert await _runs_and_jobs(t.aid) == ([("ok", None)] * 2, [("send_followup", "done")] * 2), platform
        assert await _followup_ticks(t.aid) == (_FOLLOWUP_TICKS, ["1"], "tracking", True), platform


async def case_send_followup_with_no_group_mints_one_fansly_group_sends_once_and_the_next_tick_is_held_on_both_platforms():
    fake = StatefulFansly()
    FAKE_STATE[("send_followup", "no_group")](fake)
    assert fan_groups(fake) == []
    mint = {"users": [{"userId": fake.account_id, "permissionFlags": 0}, {"userId": FAN, "permissionFlags": 0}],
            "recipients": [], "lastMessage": None, "userSettings": None, "type": 1}
    want_calls = {"fansly": [_GROUPS_READ, ("POST", "/group", mint), ("POST", "/message", LLM_REPLY)],
                  "onlyfans": ["send_message"]}
    for platform in ("fansly", "onlyfans"):
        t = await _turn(platform, "send_followup", "no_group", fake=fake if platform == "fansly" else None)
        assert t.got == expected_run(platform, "send_followup", "no_group"), (platform, t.got)
        assert (t.calls, t.frames) == (want_calls[platform], []), (platform, t)
        if platform == "fansly":
            groups = fan_groups(fake)
            assert (len(groups), [(b["groupId"], b["content"]) for p, b in t.wire if p == "/message"]) == (
                1, [(groups[0], LLM_REPLY)]), (groups, t.wire)
        else:
            assert _unstamped(t.wire) == [_of_send(LLM_REPLY)], t.wire
        assert (t.again[:2], t.later) == (("ok", None), []), (platform, t.again, t.later)
        assert await _runs_and_jobs(t.aid) == ([("ok", None)] * 2, [("send_followup", "done")] * 2), platform
        assert await _followup_ticks(t.aid) == (_FOLLOWUP_TICKS, ["1"], "tracking", True), platform


async def case_cell_mode_send_followup_returns_no_anchor_with_zero_provider_calls_anchored_or_not_on_both_platforms():
    for platform in ("fansly", "onlyfans"):
        assert await _no_anchor_in_cell_mode(platform, "send_followup", "run") == (
            [_FAN_GROUP] if platform == "fansly" else []), platform
        assert await _no_anchor_in_cell_mode(platform, "send_followup", "no_group") == [], platform


_PROMOTIONS = ("skipped", "platform_lacks:promotions", (), None)


async def case_promo_reactivate_refuses_before_recheck_state_stand_down_wait_note_or_any_call():
    created = SAME_EFFECTS["onlyfans"]["promo_reactivate"]["run"]
    table = [
        ("fansly", "run", _PROMOTIONS, []),
        ("fansly", "recheck", _PROMOTIONS, []),
        ("onlyfans", "run", ("ok", None, created, None), ["promotions", "create_promo"]),
        ("onlyfans", "recheck", ("ok", None, created, None), ["promotions", "create_promo"]),
    ]
    for platform, branch, want, calls in table:
        got, fake, _aid = await _drive(platform, "promo_reactivate", branch)
        assert (got, fake.calls) == (want, calls), (platform, branch, got, fake.calls)


def _of_post(answer):
    def get_post(self, _post_id):
        self.calls.append("get_post")
        if isinstance(answer, Exception):
            raise answer
        return answer
    return get_post


async def case_a_fansly_read_gap_is_inconclusive_under_both_baselines_and_never_moves_the_slot():
    inconclusive = ("ok", "inconclusive", (), None)
    for branch in ("text_baseline", "empty_baseline"):
        for answer, status in ((EMPTY_POST, 200), (IDLESS_POST, 200), (POST_ERROR, 200), (POST_ERROR, 404)):
            fake = StatefulFansly()
            answers_post(answer, status)(fake)
            got, fake, _aid = await _drive("fansly", "s4s_check", branch, fake=fake)
            assert (got, _bodies(fake.calls)) == (inconclusive, [("GET", "/post", None)]), (answer, status, branch, got)
    deleted = ("ok", None, SAME_EFFECTS["onlyfans"]["s4s_check"]["text_baseline"], None)
    for branch in ("text_baseline", "empty_baseline"):
        for answer, want in ((OFAPIError("500 upstream"), inconclusive), ({}, inconclusive),
                             (OFAPIError("404 Not Found"), deleted)):
            got, of, _aid = await _drive("onlyfans", "s4s_check", branch,
                                         world=lambda _aid, a=answer: patch.object(OFStandIn, "get_post", _of_post(a)))
            assert (got, of.calls) == (want, ["get_post"]), (branch, answer, got, of.calls)


@contextlib.contextmanager
def _counting_of_builds(built: list):
    inner = OFClient.from_account

    def from_account(aid, **kw):
        built.append(aid)
        return inner(aid, **kw)
    with patch.object(OFClient, "from_account", from_account):
        yield


async def _push_outcome(platform: str, kind: str) -> tuple:
    built: list = []
    got, fake, aid = await _drive(platform, kind, "push", world=lambda _aid: _counting_of_builds(built))
    async with get_session() as s:
        run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == aid))).scalar_one()
        prof = (await s.execute(select(FanProfile).where(FanProfile.account_id == aid))).scalar_one()
    stats = json.loads(run.stats_json)
    applied = stats if kind == "apply_profiles" else stats["apply_profiles"]
    pushed = (applied["pushed_to_of"], applied["pushed_nick"], applied["pushed_note"])
    return got, fake, aid, built, pushed, prof


async def case_a_fansly_profile_push_reaches_the_backend_client_and_builds_no_onlyfans_client():
    for kind in ("apply_profiles", "process_old_fans"):
        got, fake, _aid, built, pushed, prof = await _push_outcome("fansly", kind)
        notes = [(b["contentType"], b["note"]) for m, p, b, _q in fake.calls if (m, p) == ("POST", "/notes")]
        assert built == [], (kind, built)
        assert got == expected_run("fansly", kind, "push"), (kind, got)
        assert pushed == (True, 1, 1), (kind, pushed)
        assert (12002, prof.last_applied_nickname) in notes and (12000, prof.applied_notes) in notes, (kind, notes)
        assert prof.applied_notes and prof.last_applied_nickname == "Tom/Gym", (kind, prof.last_applied_nickname)
    for kind in ("apply_profiles", "process_old_fans"):
        got, of, aid, built, pushed, _prof = await _push_outcome("onlyfans", kind)
        assert built == [aid], (kind, built)
        assert got == expected_run("onlyfans", kind, "push"), (kind, got)
        assert pushed == (True, 1, 1), (kind, pushed)
        assert {"set_fan_custom_name", "set_fan_note"} <= set(of.calls), (kind, of.calls)


_MEDIA = "platform_lacks:create_post:media"
_MEDIA_POSTS = {
    "media": [{"text": "new post", "media_files": [901]}],
    "folder": [{"text": "new post", "media_folder_id": 5}],
    "preview": [{"text": "new post", "preview_media_files": [902], "price": 5}],
    "price": [{"text": "new post", "price": 5}],
    "later_item": [{"text": "new post"}, {"text": "next post", "media_files": [901]}],
}


async def _free_page(_aid):
    return False


async def case_every_fansly_media_post_refuses_with_zero_requests_dry_run_included_and_onlyfans_posts():
    for name, posts in _MEDIA_POSTS.items():
        for dry in (False, True):
            got, fake, _aid = await _drive("fansly", "auto_posts", "media", extra={"posts": posts, "dry_run": dry})
            assert got == ("skipped", _MEDIA, (), None), (name, dry, got)
            assert fake.calls == [], (name, dry, fake.calls)
    with patch.object(account_page, "is_paid_page", _free_page):
        for name in ("media", "folder", "preview"):
            got, of, _aid = await _drive("onlyfans", "auto_posts", "media", extra={"posts": _MEDIA_POSTS[name]})
            assert got[:2] == ("ok", None) and of.calls.count("create_post") == 1, (name, got, of.calls)
        got, of, _aid = await _drive("onlyfans", "auto_posts", "media", extra={"dry_run": True})
    assert got == ("ok", None, (), None) and of.calls == [], (got, of.calls)
    got, fake, _aid = await _drive("fansly", "auto_posts", "run", extra={"dry_run": True})
    assert got == ("ok", None, (), None) and _bodies(fake.calls) == [("GET", "/account/me", None)], (got, fake.calls)


async def case_a_free_post_with_stale_preview_media_posts_its_text_on_both_platforms():
    stale = {"posts": [{"text": "new post", "preview_media_files": [902], "price": 0, "hours_to_live": 24}]}
    for platform in ("fansly", "onlyfans"):
        got, _fake, _aid = await _drive(platform, "auto_posts", "media", extra=stale)
        assert got == expected_run(platform, "auto_posts", "run"), (platform, got)


async def _orphan_media() -> int:
    aid = await _account("onlyfans")
    async with get_session() as s:
        row = S4SMedia(account_id=aid, vault_media_id=909, media_type="photo")
        s.add(row)
        await s.flush()
        return row.id


async def case_a_refused_fansly_s4s_media_slot_prunes_nothing_and_onlyfans_still_prunes():
    orphan = await _orphan_media()
    got, fake, aid = await _drive("fansly", "s4s_post", "media")
    assert got == ("skipped", _MEDIA, (), None), got
    assert fake.calls == [], fake.calls
    async with get_session() as s:
        assert await s.get(S4SMedia, orphan) is not None
        slot = (await s.execute(select(S4SSlot).where(S4SSlot.poster_account_id == aid))).scalar_one()
        assert (slot.status, slot.post_id) == ("scheduled", None), (slot.status, slot.post_id)
    await _drive("onlyfans", "s4s_post", "media")
    async with get_session() as s:
        assert await s.get(S4SMedia, orphan) is None


async def case_a_fansly_media_slot_keeps_not_the_poster_and_done_reasons():
    for reason, owner, seed in (("not_the_poster", False, _s4s(media=True)),
                                ("posted", True, _s4s(posted={"id": 5501}, media=True))):
        poster = await _account("fansly")
        extra = await seed(poster, "fansly")
        aid = poster if owner else await _account("fansly")
        got, fake, _aid = await _drive("fansly", "s4s_post", "media", aid=aid, extra=extra)
        assert got[:2] == ("ok", reason) and fake.calls == [], (reason, got, fake.calls)


async def case_refused_smart_list_sync_sends_no_request_and_leaves_every_row():
    for branch in ("sync", "money", "renewal", "sub_start"):
        got, calls, _stats, rows, _ids = await _observed_with_rows("fansly", "smart_list_sync", branch)
        assert got == expected_run("fansly", "smart_list_sync", branch), (branch, got)
        assert calls == [], (branch, calls)
        assert [state for state, *_ in rows.values()] == [None], (branch, rows)


async def case_stale_smart_list_sync_syncs_the_row_and_holds_the_ungranted_tombstone():
    got, calls, _stats, rows, _ids = await _observed_with_rows("fansly", "smart_list_sync", "stale")
    assert got == expected_run("fansly", "smart_list_sync", "stale"), got
    assert [(m, p) for m, p, _b, _q in calls] == [("POST", "/lists"), ("GET", "/lists/account"),
                                                  ("GET", "/lists/itemsnew"), ("POST", "/lists/commands")], calls
    assert rows["Chatty"][0:3:2] == ("ok", 1) and rows["Gone (deleting #1)"] == ("deleting", 703, None, None, False), rows
    got, _calls, _stats, rows, _ids = await _observed_with_rows("onlyfans", "smart_list_sync", "stale")
    assert rows == {"Chatty": ("ok", 701, 1, None, True)}, rows


async def case_mixed_smart_list_sync_syncs_chat_rows_and_leaves_refused_rows():
    got, calls, stats, rows, ids = await _observed_with_rows("fansly", "smart_list_sync", "mixed")
    assert got == ("partial", "partial:platform_lacks:tip_ledger",
                   ("POST /lists", "POST /lists/commands", "table:smart_lists"), None), got
    assert rows["Whales"] == (None, None, None, None, True), rows
    chatty = rows["Chatty"]
    assert chatty[0] == "ok" and chatty[2] == 1, rows
    lid = str(chatty[1])
    assert [(m, p, b) for m, p, b, _q in calls] == [
        ("POST", "/lists", {"label": "Chatty", "description": ""}),
        ("GET", "/lists/account", None),
        ("GET", "/lists/itemsnew", None),
        ("POST", "/lists/commands", {"listCommands": [{"type": 1, "listItem": {"id": FAN, "listId": lid}}]}),
    ], calls
    assert stats["refused_rows"] == [ids["Whales"]] and stats["ok"] == 1, stats
    got, _calls, stats, rows, _ids = await _observed_with_rows("onlyfans", "smart_list_sync", "mixed")
    assert "refused_rows" not in stats and stats["ok"] == 2, stats
    assert {r[0] for r in rows.values()} == {"ok"}, rows


async def case_refused_rows_beside_a_tombstone_finish_the_tombstone_as_partial():
    got, calls, stats, rows, ids = await _observed_with_rows("fansly", "smart_list_sync", "money_tombstone")
    assert got == ("partial", "partial:platform_lacks:tip_ledger", ("table:smart_lists",), None), got
    assert calls == [], calls
    assert rows == {"Whales": (None, None, None, None, True)}, rows
    assert stats["refused_rows"] == [ids["Whales"]] and stats["deleted"] == 1 and stats["ok"] == 0, stats
    got, _calls, stats, rows, _ids = await _observed_with_rows("onlyfans", "smart_list_sync", "money_tombstone")
    assert "refused_rows" not in stats and stats["deleted"] == 1 and stats["ok"] == 1, stats
    assert rows == {"Whales": ("ok", 701, 1, None, True)}, rows


_BASE = 900_000_000_000_001_000


async def _list_rows(aid: str) -> dict:
    async with get_session() as s:
        rows = (await s.execute(select(SmartList).where(SmartList.account_id == aid))).scalars().all()
    return {r.name: (r.sync_state, r.of_list_id, r.member_count, r.sync_error) for r in rows}


def _bodies(calls: list) -> list[tuple]:
    return [(m, p, b) for m, p, b, _q in calls]


def _add(lid: int, fid: int) -> tuple:
    return ("POST", "/lists/commands", {"listCommands": [{"type": 1, "listItem": {"id": str(fid), "listId": str(lid)}}]})


def _remove(lid: int, fid: int) -> tuple:
    return ("POST", "/lists/commands", {"listCommands": [{"type": 2, "listId": str(lid), "itemIds": [str(fid)]}]})


_READ = (("GET", "/lists/account", None), ("GET", "/lists/itemsnew", None))


async def case_a_target_above_49_errors_before_create_rename_or_read():
    fake, big = StatefulFansly(), fan_ids(_BASE, 50)
    old = fansly_list(fake, big[:3])
    seed = tagged_lists(big[:3], big, {"name": "Big new"},
                        {"name": "Big old", "of_list_id": old, "of_list_name": "Old name"})
    aid = await _account("fansly", seed)
    got, fake, _aid = await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    assert got == ("ok", None, ("table:smart_lists",), None), got
    assert fake.calls == [], fake.calls
    over = "50 fans match — lists above 49 are not synced"
    assert await _list_rows(aid) == {"Big new": ("error", None, None, over), "Big old": ("error", old, None, over)}


async def case_a_failed_removal_at_49_bounds_adds_and_resumes_under_capacity():
    kept, leaving, joining = fan_ids(_BASE, 47), fan_ids(_BASE + 100, 2), fan_ids(_BASE + 200, 2)
    fake = StatefulFansly()
    lid = fansly_list(fake, kept + leaving)
    fake.refused_removes.add(str(leaving[0]))
    seed = tagged_lists(kept + leaving, kept + joining, {"name": "Chatty", "of_list_id": lid, "of_list_name": "Chatty"})
    aid = await _account("fansly", seed)
    got, fake, _aid = await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    assert got == ("ok", None, ("POST /lists/commands", "table:smart_lists"), None), got
    assert _bodies(fake.calls) == [*_READ, _remove(lid, leaving[0]), _remove(lid, leaving[1]),
                                   _add(lid, joining[0])], fake.calls
    assert sorted(map(int, fake.members[str(lid)])) == sorted(kept + [leaving[0], joining[0]]), fake.members
    assert await _list_rows(aid) == {"Chatty": ("pending", lid, 49, "1 list writes failed — retried next sync")}

    fake.refused_removes.clear()
    seen = len(fake.calls)
    await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    assert _bodies(fake.calls[seen:]) == [*_READ, _remove(lid, leaving[0]), _add(lid, joining[1])], fake.calls[seen:]
    assert sorted(map(int, fake.members[str(lid)])) == sorted(kept + joining), fake.members
    assert await _list_rows(aid) == {"Chatty": ("ok", lid, 49, None)}


def _status(code: int) -> requests.Response:
    r = requests.Response()
    r.status_code = code
    return r


def _remove_404(*_a, **_k):
    raise fansly_shim.FanslyAPIError("404 for /lists/commands", response=_status(404))


async def case_a_fansly_404_on_remove_at_49_frees_no_slot():
    kept, leaving, joining = fan_ids(_BASE, 48), fan_ids(_BASE + 100, 1), fan_ids(_BASE + 200, 1)
    fake = StatefulFansly()
    lid = fansly_list(fake, kept + leaving)
    aid = await _account("fansly", tagged_lists(kept + leaving, kept + joining,
                                                {"name": "Chatty", "of_list_id": lid, "of_list_name": "Chatty"}))
    with patch.object(fansly_shim.FanslyShimClient, "remove_user_from_list", _remove_404):
        got, fake, _aid = await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    assert got == ("ok", None, ("table:smart_lists",), None), got
    assert _bodies(fake.calls) == list(_READ), fake.calls
    assert len(fake.members[str(lid)]) == 49, fake.members
    assert await _list_rows(aid) == {"Chatty": ("pending", lid, 49, "1 list writes failed — retried next sync")}


class _Crash(BaseException):
    pass


def _crash(*_a, **_k):
    raise _Crash("process died after the removes")


async def case_an_interrupted_sync_resumes_without_repeating_a_write():
    kept, leaving, joining = fan_ids(_BASE, 45), fan_ids(_BASE + 100, 4), fan_ids(_BASE + 200, 4)
    fake = StatefulFansly()
    lid = fansly_list(fake, kept + leaving)
    seed = tagged_lists(kept + leaving, kept + joining, {"name": "Chatty", "of_list_id": lid, "of_list_name": "Chatty"})
    aid = await _account("fansly", seed)
    try:
        with patch.object(fansly_shim.FanslyShimClient, "add_users_to_lists", _crash):
            await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    except _Crash:
        pass
    else:
        raise AssertionError("the first add must crash the run")
    assert _bodies(fake.calls) == [*_READ, *(_remove(lid, f) for f in leaving)], fake.calls
    assert (await _list_rows(aid))["Chatty"][0] == "syncing"

    seen = len(fake.calls)
    got, fake, _aid = await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    assert got[:2] == ("ok", None), got
    assert _bodies(fake.calls[seen:]) == [*_READ, *(_add(lid, f) for f in joining)], fake.calls[seen:]
    assert sorted(map(int, fake.members[str(lid)])) == sorted(kept + joining), fake.members
    assert await _list_rows(aid) == {"Chatty": ("ok", lid, 49, None)}


async def case_a_list_gone_on_fansly_and_onlyfans_is_recreated_on_next_run():
    gone = 900_000_000_000_009_999
    seed = tagged_lists([], [int(FAN)], {"name": "Chatty", "of_list_id": gone, "of_list_name": "Chatty"})
    aid = await _account("fansly", seed)
    got, fake, _aid = await _drive("fansly", "smart_list_sync", "chat", aid=aid)
    assert got == ("ok", None, ("table:smart_lists",), None), got
    assert (await _list_rows(aid))["Chatty"][:2] == ("error", None)
    await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    state, new_id, count, reason = (await _list_rows(aid))["Chatty"]
    assert state == "ok" and new_id != gone and count == 1 and reason is None
    assert list(fake.lists) == [str(new_id)] and fake.members[str(new_id)] == [str(FAN)], fake.members

    aid = await _account("onlyfans", seed)
    of = ListsOF(aid, {})
    await _drive("onlyfans", "smart_list_sync", "chat", aid=aid, fake=of)
    assert (await _list_rows(aid))["Chatty"][:2] == ("error", None)
    await _drive("onlyfans", "smart_list_sync", "chat", aid=aid, fake=of)
    assert of.calls.count("create_list") == 1 and await _list_rows(aid) == {"Chatty": ("ok", 701, 1, None)}


async def case_a_granted_tombstone_deletes_only_a_proof_fan_list():
    for members, deleted in (([int(FAN)], True), ([int(FAN), _OTHER], False)):
        fake = StatefulFansly()
        lid = fansly_list(fake, members)
        aid = await _account("fansly", _lists(("Gone (deleting #4)", CHAT_RULES,
                                                {"is_active": False, "sync_state": "deleting", "of_list_id": lid})))
        grants = f"{aid}:delete_list:list={lid},{aid}:priority_mass:fan={FAN}"
        with patch.dict(os.environ, {gate.LIVE_CHECK_ENV: grants}):
            got, fake, _aid = await _drive("fansly", "smart_list_sync", "tombstone", aid=aid, fake=fake)
        if deleted:
            assert got == ("ok", None, ("POST /lists/remove", "table:smart_lists"), None), got
            assert _bodies(fake.calls) == [*_READ, *_READ, ("POST", "/lists/remove", {"listId": str(lid)})], fake.calls
            assert str(lid) not in fake.lists and await _list_rows(aid) == {}, fake.lists
        else:
            assert got == ("skipped", "platform_lacks:delete_list", (), None), got
            assert _bodies(fake.calls) == list(_READ), fake.calls
            assert await _list_rows(aid) == {"Gone (deleting #4)": ("deleting", lid, None, None)}


async def case_onlyfans_sync_adds_in_100_chunks_then_removes_with_no_49_cap():
    target, leaving = fan_ids(_BASE, 150), fan_ids(_BASE + 500, 2)
    seed = tagged_lists(leaving, target, {"name": "Chatty", "of_list_id": 800, "of_list_name": "Chatty"},
                        {"name": "Big new"})
    aid = await _account("onlyfans", seed)
    got, of, _aid = await _drive("onlyfans", "smart_list_sync", "chat", aid=aid, fake=ListsOF(aid, {800: leaving}))
    assert got == ("ok", None, ("add_users_to_lists", "create_list", "remove_user_from_list", "table:smart_lists"),
                   None), got
    assert of.bodies == [("add", {"800": target[:100]}), ("add", {"800": target[100:]}),
                         ("remove", 800, leaving[0]), ("remove", 800, leaving[1]),
                         ("add", {"702": target[:100]}), ("add", {"702": target[100:]})], of.bodies
    assert await _list_rows(aid) == {"Chatty": ("ok", 800, 150, None), "Big new": ("ok", 702, 150, None)}


_OTHER = 900_000_000_000_002_222
_PM_LACKS = "platform_lacks:priority_mass"


def _pm_grant(aid: str | None):
    return patch.dict(os.environ, {gate.LIVE_CHECK_ENV: f"{aid}:priority_mass:fan={FAN}" if aid else ""})


async def _pm_seeded(platform: str, *lists, status: str = "resolving", recipients: dict | None = None):
    aid = await _account(platform)
    extra = await priority_run(*lists, status=status)(aid, platform)
    if recipients:
        async with get_session() as s:
            s.add_all([PriorityMassRecipient(run_id=extra["run_id"], fan_id=int(f), status=st,
                                             updated_at=datetime.utcnow()) for f, st in recipients.items()])
    return aid, extra


async def _pm_state(rid: int) -> tuple[str, str | None, dict]:
    async with get_session() as s:
        run = await s.get(PriorityMassRun, rid)
        rows = (await s.execute(select(PriorityMassRecipient).where(PriorityMassRecipient.run_id == rid))).scalars()
        return run.status, run.last_error, {int(r.fan_id): r.status for r in rows}


async def _pm_fansly(aid: str, extra: dict, fake=None, grant: bool = True):
    fake = fake or StatefulFansly()
    with _pm_grant(aid if grant else None):
        got, fake, _aid = await _drive("fansly", "priority_mass", "list", aid=aid, extra=extra, fake=fake)
    return got, fake


async def case_no_grant_refuses_every_priority_mass_leg_with_zero_requests_and_ends_the_run():
    legs = {"queued": ("resolving", None), "resumed": ("running", {int(FAN): "pending"}),
            "running": ("running", {int(FAN): "pending", _OTHER: "claimed"})}
    for leg, (status, recipients) in legs.items():
        fake = StatefulFansly()
        aid, extra = await _pm_seeded("fansly", fansly_list(fake, [int(FAN)]), status=status, recipients=recipients)
        got, fake = await _pm_fansly(aid, extra, fake, grant=False)
        assert got == ("skipped", _PM_LACKS, (), None), (leg, got)
        assert fake.calls == [], (leg, fake.calls)
        assert await _pm_state(extra["run_id"]) == ("error", _PM_LACKS, recipients or {}), leg


async def case_priority_mass_to_following_refuses_first_even_with_a_grant():
    aid, extra = await _pm_seeded("fansly", "following")
    with _pm_grant(aid):
        got, fake, _aid = await _drive("fansly", "priority_mass", "following", aid=aid, extra=extra)
    assert got == ("skipped", "platform_lacks:following", (), None), got
    assert fake.calls == [] and await _pm_state(extra["run_id"]) == ("error", "platform_lacks:following", {})


async def case_a_list_without_exactly_the_proof_fan_reads_members_ends_the_run_and_sends_nothing():
    for members in ([_OTHER], [int(FAN), _OTHER]):
        fake = StatefulFansly()
        aid, extra = await _pm_seeded("fansly", fansly_list(fake, members))
        got, fake = await _pm_fansly(aid, extra, fake)
        assert got == ("skipped", _PM_LACKS, (), None), (members, got)
        assert _bodies(fake.calls) == list(_READ), (members, fake.calls)
        assert await _pm_state(extra["run_id"]) == ("error", _PM_LACKS, {}), members


async def case_autoreply_refused_folder_run_is_stored_as_skipped():
    got, fake, _aid = await _drive("fansly", "autoreply", "gone_folder")
    assert got == ("skipped", "platform_lacks:list_users_in:unknown_list", (), None), got
    assert [method for method, *_ in fake.calls] == ["GET"], fake.calls


async def case_a_refused_priority_mass_read_ends_the_run_with_its_reason_and_no_recipients():
    fake = StatefulFansly()
    aid, extra = await _pm_seeded("fansly", fansly_list(fake, fan_ids(int(FAN), 50)))
    got, fake = await _pm_fansly(aid, extra, fake)
    reason = "platform_lacks:list_users_in:incomplete"
    assert got == ("skipped", reason, (), None), got
    assert _bodies(fake.calls) == list(_READ), fake.calls
    assert await _pm_state(extra["run_id"]) == ("error", reason, {})


async def case_a_priority_mass_list_gone_on_fansly_ends_the_run_unread_and_unsent():
    aid, extra = await _pm_seeded("fansly", 900_000_000_000_009_999)
    got, fake = await _pm_fansly(aid, extra)
    reason = "platform_lacks:list_users_in:unknown_list"
    assert got == ("skipped", reason, (), None), got
    assert _bodies(fake.calls) == [_READ[0]], fake.calls
    assert await _pm_state(extra["run_id"]) == ("error", reason, {})


async def case_wrong_persisted_recipients_refuse_before_the_stale_claim_update():
    recipients = {int(FAN): "pending", _OTHER: "claimed"}
    aid, extra = await _pm_seeded("fansly", "fans", status="running", recipients=recipients)
    got, fake = await _pm_fansly(aid, extra)
    assert got == ("skipped", _PM_LACKS, (), None), got
    assert fake.calls == [], fake.calls
    assert await _pm_state(extra["run_id"]) == ("error", _PM_LACKS, recipients)

    aid, extra = await _pm_seeded("onlyfans", "fans", status="running", recipients=recipients)
    got, of, _aid = await _drive("onlyfans", "priority_mass", "fans", aid=aid, extra=extra)
    assert got[:2] == ("ok", None) and of.calls == ["send_message"], (got, of.calls)
    assert (await _pm_state(extra["run_id"]))[2] == {int(FAN): "sent", _OTHER: "unknown"}


async def case_a_priority_mass_grant_revoked_after_a_leg_refuses_before_the_lease():
    fake = StatefulFansly()
    aid, extra = await _pm_seeded("fansly", fansly_list(fake, [int(FAN)]))
    assert await ax.acquire_fan_lease(aid, int(FAN), "held_elsewhere")
    try:
        got, fake = await _pm_fansly(aid, extra, fake)
        assert got[:2] == ("ok", None) and _bodies(fake.calls) == list(_READ), (got, fake.calls)
        assert await _pm_state(extra["run_id"]) == ("running", None, {int(FAN): "pending"})
        got, fake = await _pm_fansly(aid, extra, fake, grant=False)
        assert got == ("skipped", _PM_LACKS, ("job:priority_mass",), None), got
        assert _bodies(fake.calls) == list(_READ), fake.calls
        assert await _pm_state(extra["run_id"]) == ("error", _PM_LACKS, {int(FAN): "pending"})
    finally:
        await ax.release_fan_lease(aid, int(FAN))


async def case_exactly_the_proof_fan_gets_exactly_one_priority_mass_send():
    fake = StatefulFansly()
    aid, extra = await _pm_seeded("fansly", fansly_list(fake, [int(FAN)]))
    got, fake = await _pm_fansly(aid, extra, fake)
    assert got[:2] == ("ok", None) and "POST /message" in got[2], got
    sends = [b for m, p, b, _q in fake.calls if (m, p) == ("POST", "/message")]
    assert len(sends) == 1, fake.calls
    assert _bodies(fake.calls)[:2] == list(_READ), fake.calls
    assert await _pm_state(extra["run_id"]) == ("running", None, {int(FAN): "sent"})


_NUDGE_LACKS = "platform_lacks:nudge_online"
_ROSTER_READS = {("GET", "/subscribers"), ("GET", "/account")}


async def _nudge_rows(aid: str) -> tuple[set[int], list[int]]:
    async with get_session() as s:
        seen = set((await s.execute(select(NudgeState.fan_id).where(NudgeState.account_id == aid))).scalars())
        jobs = (await s.execute(select(ScheduledJob.payload_json).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == "nudge_online_fire"))).scalars()
        return seen, [json.loads(p)["fan_id"] for p in jobs]


async def _nudge(seed, *grants: str, extra: dict | None = None, fake=None):
    fake = fake or StatefulFansly()
    aid = await _account("fansly", seed)
    with nudge_grant(aid, *grants):
        got, fake, _aid = await _drive("fansly", "nudge_online", "run", aid=aid, fake=fake, extra=extra)
    return got, fake, await _nudge_rows(aid)


async def case_nudge_keeps_disabled_and_bad_test_fan_first_then_refuses_ungranted_before_the_roster():
    off = _rows(_ai(nudge_config_json=json.dumps({"enabled": False})))
    warm = SEEDS[("nudge_online", "run")]
    for seed, extra, want in ((off, {}, ("ok", None, (), None)),
                              (warm, {"test_fan": "x"}, ("ok", None, (), None)),
                              (warm, {}, ("skipped", _NUDGE_LACKS, (), None))):
        fake = StatefulFansly()
        online_beside(fake, str(_OTHER))
        got, fake, rows = await _nudge(seed, extra=extra, fake=fake)
        assert got == want, (extra, got)
        assert fake.calls == [] and rows[1] == [], (extra, fake.calls, rows)


async def case_a_granted_nudge_scan_writes_presence_and_queues_only_for_the_granted_fan():
    for warmed in (True, False):
        fake = StatefulFansly()
        online_beside(fake, str(_OTHER))
        seed = SEEDS[("nudge_online", "run")] if warmed else _rows(_NUDGE_CFG)
        got, fake, (seen, jobs) = await _nudge(seed, FAN, fake=fake)
        effects = ("job:nudge_online_fire", "table:nudge_state") if warmed else ("table:nudge_state",)
        assert got == ("ok", None, effects, None), (warmed, got)
        assert {(m, p) for m, p, _b, _q in fake.calls} <= _ROSTER_READS, (warmed, fake.calls)
        assert seen == ({1, int(FAN)} if warmed else {int(FAN)}), (warmed, seen)
        assert jobs == ([int(FAN)] if warmed else []), (warmed, jobs)


async def case_test_fan_and_forced_nudge_refuse_without_that_fans_grant_before_any_presence_row():
    warm = SEEDS[("nudge_online", "run")]
    for force in (False, True):
        extra = {"test_fan": FAN, "test_force": force}
        for grants in ((), (str(_OTHER),)):
            got, fake, rows = await _nudge(warm, *grants, extra=extra)
            assert got == ("skipped", _NUDGE_LACKS, (), None), (force, grants, got)
            assert fake.calls == [] and rows == ({1}, []), (force, grants, fake.calls, rows)
        got, fake, rows = await _nudge(warm, FAN, extra=extra)
        assert got == ("ok", None, ("job:nudge_online_fire", "table:nudge_state"), None), (force, got)
        assert fake.calls == [] and rows == ({1, int(FAN)}, [int(FAN)]), (force, fake.calls, rows)
        aid = await _account("onlyfans", warm)
        got, _of, _aid = await _drive("onlyfans", "nudge_online", "run", aid=aid, extra=extra)
        assert got == ("ok", None, ("job:nudge_online_fire", "table:nudge_state"), None), (force, got)


_NEWER_JOB = 2_000_000_001


async def _latch(aid: str) -> int | None:
    async with get_session() as s:
        return (await s.get(NudgeState, (aid, int(FAN)))).pending_job_id


async def _newer_latch(aid: str, _job_id: int) -> None:
    await hold_latch(aid, _NEWER_JOB)


async def case_a_refused_nudge_fire_sends_nothing_and_clears_only_its_own_latch():
    for job_seed, effects, latch in ((hold_latch, ("table:nudge_state",), None), (_newer_latch, (), _NEWER_JOB)):
        with patch.dict(JOB_SEEDS, {("nudge_online_fire", "run"): job_seed}):
            got, fake, aid = await _drive("fansly", "nudge_online_fire", "run")
        assert got == ("skipped", _NUDGE_LACKS, effects, None), (job_seed, got)
        assert fake.calls == [] and await _latch(aid) == latch, (job_seed, fake.calls)


async def case_nudge_fire_keeps_bad_fan_id_and_disabled_first_then_refuses_before_its_rule_and_presence_reads():
    off = _ai(nudge_config_json=json.dumps({"enabled": False}))
    seen = _seen(int(FAN), timedelta(0))
    for makers, extra, want in (((_NUDGE_CFG, _rule("nudge_online"), seen), {"fan_id": "x"}, ("ok", None, (), None)),
                                ((off, _rule("nudge_online"), seen), {}, ("ok", None, ("table:nudge_state",), None)),
                                ((_NUDGE_CFG, seen), {}, ("skipped", _NUDGE_LACKS, ("table:nudge_state",), None)),
                                ((_NUDGE_CFG, _rule("nudge_online"), _seen(int(FAN), timedelta(days=1))), {},
                                 ("skipped", _NUDGE_LACKS, ("table:nudge_state",), None))):
        aid = await _account("fansly", _rows(*makers))
        got, fake, _aid = await _drive("fansly", "nudge_online_fire", "run", aid=aid, extra=extra)
        assert got == want, (extra, got)
        assert fake.calls == [], (extra, fake.calls)


async def case_a_grant_revoked_after_the_scan_refuses_the_queued_fire():
    for kept in (True, False):
        fake = StatefulFansly()
        FAKE_STATE[("nudge_online", "run")](fake)
        aid = await _account("fansly", _rows(_NUDGE_CFG, _rule("nudge_online"), _seen(1, timedelta(days=1))))
        with nudge_grant(aid, FAN):
            got, _fake, _aid = await _drive("fansly", "nudge_online", "run", aid=aid, fake=fake)
        assert got == ("ok", None, ("job:nudge_online_fire", "table:nudge_state"), None), (kept, got)
        async with get_session() as s:
            job = (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == "nudge_online_fire"))).scalar_one()
            job.run_at = datetime.utcnow()
            job_id = job.id
        assert await _latch(aid) == job_id
        with nudge_grant(aid, *((FAN,) if kept else ())):
            got, fake, _aid = await _drive("fansly", "nudge_online_fire", "run", aid=aid, job_id=job_id)
        want = (("ok", None, ("POST /message", "job:nudge_online", "table:chats", "table:messages",
                              "table:nudge_state"), None) if kept
                else ("skipped", _NUDGE_LACKS, ("job:nudge_online", "table:nudge_state"), None))
        assert got == want, (kept, got)
        assert kept or fake.calls == [], fake.calls
        assert await _latch(aid) is None, kept


async def case_cell_mode_holds_a_due_fansly_fire_with_zero_provider_calls():
    aid = await _account("fansly", SEEDS[("nudge_online_fire", "granted")])
    account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": "fansly"})
    async with get_session() as s:
        job = ScheduledJob(account_id=aid, kind="nudge_online_fire", payload_json=json.dumps(PAYLOADS[
            "nudge_online_fire"]["granted"]), run_at=datetime.utcnow(), status="pending")
        s.add(job)
        await s.flush()
        job_id = job.id
    await hold_latch(aid, job_id)
    fake = StatefulFansly()
    before = _tables()
    ax._make_client = lambda _aid: fake.client()
    try:
        with nudge_grant(aid, FAN), patch.dict(os.environ, {"OI_CELL_MAP": "/nonexistent/placement.json"}):
            result = await ax.run_once(aid, "nudge_online_fire")
    finally:
        ax._make_client = _REAL_MAKE_CLIENT
    assert result["status"] == "skipped" and result["reason"] == "no_anchor", result
    assert fake.calls == [] and effect_tables(before, _tables(), _shapes()) == set(), fake.calls
    assert await _latch(aid) == job_id
    async with get_session() as s:
        assert (await s.get(ScheduledJob, job_id)).status == "done"


_SEND_LACKS = "platform_lacks:send_message"
_MIXED_FAN = 900_000_000_000_000_011


def _live_send():
    return patch.object(gate, "LIVE_CHECK_LANES", gate.LIVE_CHECK_LANES | {"send_message"})


async def _typos_on(_aid):
    return collections.defaultdict(lambda: True)


@contextlib.contextmanager
def _typing_spies():
    seen: list[str] = []
    with contextlib.ExitStack() as stack:
        for mod in ("autoreply", "welcome_chatter_for_info"):
            stack.enter_context(patch.object(importlib.import_module(f"automations.{mod}"), "load_typo_flags",
                                             _typos_on))
        for name, mods in TYPING_CALLS.items():
            for mod in mods:
                module = importlib.import_module(f"automations.{mod}")

                async def spy(*a, _real=getattr(module, name), _tag=f"{mod}.{name}", **k):
                    seen.append(_tag)
                    return await _real(*a, **k)
                stack.enter_context(patch.object(module, name, spy))
        yield seen


def _message_posts(fake) -> list:
    return [c for c in fake.calls if (c[0], c[1]) == ("POST", "/message")]


def _unexpected_calls(kind: str, fake) -> set:
    return {(m, p) for m, p, _b, _q in fake.calls} - REFUSED_READS.get(kind, set())


async def _refused_senders(gate_patch) -> None:
    for (kind, branch), spied in TYPING_SENDERS.items():
        lifted, _refused = LIFTED.get((kind, branch), (None, None))
        with gate_patch(), _typing_spies() as seen:
            got, fake, _aid = await _drive("fansly", kind, branch, world=lifted)
        assert got[:2] == ("skipped", _SEND_LACKS), (kind, got)
        assert (seen, _unexpected_calls(kind, fake)) == ([], set()), (kind, seen, fake.calls)
        with gate_patch(), _typing_spies() as seen:
            got, _fake, _aid = await _drive("onlyfans", kind, branch, world=lifted)
        assert (got, set(seen)) == (expected_run("onlyfans", kind, branch), spied), (kind, got, seen)


async def case_an_ungranted_live_check_refuses_every_typing_sender_before_hold_typo_or_hop():
    await _refused_senders(_live_send)


async def case_a_marked_send_message_refuses_every_typing_sender_before_hold_typo_or_hop():
    await _refused_senders(lambda: patch.object(platforms.FANSLY.backend.Shim.send_message, "platform_blocked",
                                                "send_message is blocked", create=True))


async def _seeded(platform: str, kind: str, branch: str) -> tuple[str, dict | None]:
    aid = await _account(platform)
    return aid, await SEEDS[(kind, branch)](aid, platform)


async def case_an_unknown_platform_refuses_the_burst_before_any_other_check():
    aid = await _account("onlyfans")
    account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": "myspace"})
    paid = [{"media_files": [901], "price": 10}]
    assert [gate.burst_refusal(aid, int(FAN)), gate.burst_refusal(aid, int(FAN), paid)] == [
        "platform_unknown:myspace"] * 2


async def case_a_live_check_marked_send_message_sends_to_its_granted_fan_and_refuses_the_rest():
    marked = patch.object(platforms.FANSLY.backend.Shim.send_message, "platform_live_check",
                          "send_message needs a grant", create=True)
    for granted in (True, False):
        aid, extra = await _seeded("fansly", "autoreply", "run")
        grant = {gate.LIVE_CHECK_ENV: f"{aid}:send_message:fan={FAN}" if granted else ""}
        with marked, patch.dict("os.environ", grant), _typing_spies() as seen:
            got, _fake, _aid = await _drive("fansly", "autoreply", "run", aid=aid, extra=extra)
        if granted:
            want = (expected_run("fansly", "autoreply", "run"), TYPING_SENDERS[("autoreply", "run")])
            assert (got, set(seen)) == want, (got, seen)
        else:
            assert (got[:2], seen) == (("skipped", _SEND_LACKS), []), (got, seen)


async def case_a_mixed_grant_run_sends_to_the_granted_fan_and_stays_ok_and_enabled():
    aid, extra = await _seeded("fansly", "autoreply", "run")
    async with get_session() as s:
        s.add_all([Fan(account_id=aid, fan_id=_MIXED_FAN),
                   Message(account_id=aid, fan_id=_MIXED_FAN, message_id=PLATFORM_MESSAGE["fansly"] + 9,
                           direction="in", body="you there", created_at=datetime.utcnow() - timedelta(hours=1))])
    with _live_send(), patch.dict("os.environ", {gate.LIVE_CHECK_ENV: f"{aid}:send_message:fan={FAN}"}):
        got, _fake, _aid = await _drive("fansly", "autoreply", "run", aid=aid, extra=extra)
    partial = f"partial:{_SEND_LACKS}"
    assert got == ("ok", partial, SAME_EFFECTS["fansly"]["autoreply"]["run"], None), got
    assert run_decide.outcome("ok", None, plugin_reason=partial) == ("ok", "done", None)
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, aid)
    assert json.loads(cfg.autoreply_config_json)["enabled"] is True


async def _turns(aid: str) -> int | None:
    async with get_session() as s:
        return (await s.get(Fan, (aid, int(FAN)))).turn_counter


async def case_welcome_chatter_refuses_before_cooldown_lease_and_attempt_bump_and_onlyfans_keeps_them():
    asked: list[str] = []

    async def yes(*_a, **_k):
        asked.append("fan_on_cooldown")
        return True

    async def no(*_a, **_k):
        asked.append("acquire_fan_lease")
        return False

    for name, held, stat in (("fan_on_cooldown", yes, "skipped_cooldown"), ("acquire_fan_lease", no, "skipped_locked")):
        for platform, want in (("fansly", ("skipped", _SEND_LACKS, 0)), ("onlyfans", ("ok", None, 1))):
            asked.clear()
            aid, _extra = await _seeded(platform, "welcome_chatter_for_info", "run")
            with _live_send(), patch.object(ax, name, held):
                got, fake, _aid = await _drive(platform, "welcome_chatter_for_info", "run", aid=aid)
            async with get_session() as s:
                run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == aid))).scalar_one()
            assert (*got[:2], json.loads(run.stats_json).get(stat, 0)) == want, (platform, name, got)
            assert asked == ([] if platform == "fansly" else [name]), (platform, asked)
    for platform, want in (("fansly", 0), ("onlyfans", 1)):
        aid, _extra = await _seeded(platform, "welcome_chatter_for_info", "run")
        before = await _turns(aid) or 0
        with _live_send():
            got, _fake, _aid = await _drive(platform, "welcome_chatter_for_info", "run", aid=aid)
        assert (await _turns(aid) or 0) - before == want, (platform, got)


_CLOSING = {"max_fan_messages": 3, "closing_ppv_text": "one more for you", "closing_ppv_media_ids": [901],
            "closing_ppv_price_cents": 1000}


async def case_an_ungranted_closing_cut_fan_gets_no_typing_ppv_or_skiplist_row():
    for platform in ("fansly", "onlyfans"):
        aid, _extra = await _seeded(platform, "welcome_chatter_for_info", "run")
        async with get_session() as s:
            s.add_all([Message(account_id=aid, fan_id=int(FAN), message_id=PLATFORM_MESSAGE[platform] + 10 + i,
                               direction="in", body=f"msg {i}",
                               created_at=datetime.utcnow() - timedelta(minutes=50 - i)) for i in range(3)])
        with _live_send(), _typing_spies() as seen:
            got, fake, _aid = await _drive(platform, "welcome_chatter_for_info", "run", aid=aid, extra=_CLOSING)
        async with get_session() as s:
            listed = (await s.execute(select(SkipList).where(SkipList.account_id == aid))).scalars().all()
            run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == aid))).scalar_one()
        closed = json.loads(run.stats_json).get("closing_ppvs_sent", 0)
        if platform == "fansly":
            assert (got, closed) == (("skipped", _SEND_LACKS, (), None), 0), got
            assert (seen, _unexpected_calls("welcome_chatter_for_info", fake), listed) == ([], set(), []), fake.calls
        else:
            assert (got[:2], closed, seen) == (("ok", None), 1, []), (got, closed, seen)


async def case_a_refused_paid_part_holds_nothing_before_it_and_onlyfans_holds_and_sends():
    for (kind, branch), spied in PAID_REFUSALS.items():
        lifted, refused = LIFTED.get((kind, branch), (None, None))
        for platform in ("fansly", "onlyfans"):
            with _typing_spies() as seen:
                got, fake, _aid = await _drive(platform, kind, branch, world=lifted)
            want = ("skipped", refused, (), None) if refused and platform == "fansly" else None
            assert got == (want or expected_run(platform, kind, branch)), (platform, kind, got)
            if platform == "fansly":
                assert (seen, _message_posts(fake)) == ([], []), (kind, seen)
            else:
                assert set(seen) == spied, (kind, seen)


_PRIOR_TYPOS = {"at": "2026-11-26T00:00:00", "since": 7}


async def case_a_refused_full_ai_ppv_burst_holds_types_and_commits_no_typo_and_onlyfans_does():
    for branch in ("ppv", "preview_ppv"):
        for platform in ("fansly", "onlyfans"):
            aid, extra = await _seeded(platform, "full_ai_chat", branch)
            async with get_session() as s:
                s.add(AiDecision(account_id=aid, fan_id=int(FAN), mode="live", trigger_kind="inbound",
                                 trigger_key="prior", route="chat", heat=2, route_row="otherwise",
                                 question_version="v", status="no_send",
                                 created_at=datetime.utcnow() - timedelta(days=1),
                                 reply_json=json.dumps({"typo_state": _PRIOR_TYPOS})))
            with _typing_spies() as seen:
                got, fake, _aid = await _drive(platform, "full_ai_chat", branch, aid=aid, extra=extra)
            assert got == expected_run(platform, "full_ai_chat", branch), (platform, branch, got)
            async with get_session() as s:
                row = (await s.execute(select(AiDecision).where(AiDecision.account_id == aid)
                                       .order_by(AiDecision.id.desc()).limit(1))).scalar_one()
            typos = json.loads(row.reply_json).get("typo_state")
            holds = [t for t in seen if t.endswith(".hold_with_typing")]
            if platform == "fansly":
                assert (holds, typos, _message_posts(fake)) == ([], _PRIOR_TYPOS, []), (branch, holds, typos)
            else:
                assert holds and typos and typos != _PRIOR_TYPOS, (branch, seen, typos)


async def case_two_sends_change_the_effect_signature():
    async def send(aid, _payload, *, run_id):
        client = ax._make_client(aid)
        for _ in range(count):
            client.send_message(FAN, "hi")
        return {}

    for platform, effect in (("onlyfans", "send_message"), ("fansly", "POST /message")):
        effects = []
        with patch.dict(automation_registry._REGISTRY, {"scheduled_send": send}):
            for count in (1, 2):
                effects.append((await observe(platform, "scheduled_send", "text"))[2])
        assert effects == [(effect,), (f"{effect}×2",)], (platform, effects)


_harness.run()
