#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import contextlib  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from itertools import count  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import requests  # noqa: E402
from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import automation_registry  # noqa: E402
import fansly_shim  # noqa: E402
import llm_client  # noqa: E402
import platforms  # noqa: E402
import promo_create_guard  # noqa: E402
import side_effect_gate as gate  # noqa: E402
import tenant_keys  # noqa: E402
import test_platform_lift_table as lift_table  # noqa: E402
from _kind_verdict_seeds import (  # noqa: E402
    CHAT_RULES, FAKE_STATE, FAN, HOST, LAPSED, SEEDS, WORLDS, ListsOF, OFStandIn, _lists, canned_llm, fan_ids, fansly_list,
    no_key, session_for, tagged_lists,
)
from _kind_verdicts_priority_mass import priority_run  # noqa: E402
from of_client import OFClient  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRun, MassRun, PriorityMassRecipient, PriorityMassRun, ScheduledJob, SmartList,
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
        "apply_profiles": {"local": "same", "push": "owner:55"},
        "auto_posts": {"run": "same", "media": "owner:42"},
        "auto_stories": {"story": "gated:platform_lacks:post_story_from_url"},
        "birthday_message": {"run": "same"},
        "customs_watch": {"owed": "same"},
        "expired_message": {"run": "same"},
        "expiry_message": {"run": "owner:44"},
        "full_ai_chat": {"shadow": "same", "live": "same"},
        "gen_info": {"local": "same", "push": "owner:55"},
        "mass_premade": {"drip": "gated:platform_lacks:send_mass_message"},
        "nudge_online_fire": {"run": "same"},
        "process_old_fans": {"local": "same", "push": "owner:55"},
        "promo_reactivate": {"run": "owner:48"},
        "purchase_followup": {"run": "owner:47"},
        "reply_mass_funnel": {"idle": "noop:no_active_funnel_runs", "landed": "same"},
        "resubscribe_message": {"run": "owner:44"},
        "s4s_check": {"text_baseline": "owner:54", "empty_baseline": "owner:54"},
        "s4s_post": {"run": "same", "media": "owner:42"},
        "scheduled_send": {"text": "same",
                           "tags": "gated:platform_lacks:tagged_users",
                           "locked": "gated:platform_lacks:locked_text"},
        "scrape_chats": {"sweep": "same"},
        "scrape_fan": {"run": "same"},
        "send_followup": {"run": "same"},
        "send_mass_message": {"broadcast": "gated:platform_lacks:send_mass_message"},
        "send_welcome": {"run": "same"},
        "unsend_messages": {"mass": "gated:platform_lacks:mass_message_history", "chat": "same"},
        "welcome_chatter_for_info": {"run": "same"},
    },
    "onlyfans": {
        "apply_profiles": {"local": "same", "push": "same"},
        "auto_posts": {"run": "same", "media": "same"},
        "auto_stories": {"story": "same"},
        "birthday_message": {"run": "same"},
        "customs_watch": {"owed": "same"},
        "expired_message": {"run": "same"},
        "expiry_message": {"run": "same"},
        "full_ai_chat": {"shadow": "same", "live": "same"},
        "gen_info": {"local": "same", "push": "same"},
        "mass_premade": {"drip": "same"},
        "nudge_online_fire": {"run": "same"},
        "process_old_fans": {"local": "same", "push": "same"},
        "promo_reactivate": {"run": "same"},
        "purchase_followup": {"run": "same"},
        "reply_mass_funnel": {"idle": "noop:no_active_funnel_runs", "landed": "same"},
        "resubscribe_message": {"run": "same"},
        "s4s_check": {"text_baseline": "same", "empty_baseline": "same"},
        "s4s_post": {"run": "same", "media": "same"},
        "scheduled_send": {"text": "same", "tags": "same", "locked": "same"},
        "scrape_chats": {"sweep": "same"},
        "scrape_fan": {"run": "same"},
        "send_followup": {"run": "same"},
        "send_mass_message": {"broadcast": "same"},
        "send_welcome": {"run": "same"},
        "unsend_messages": {"mass": "same", "chat": "same"},
        "welcome_chatter_for_info": {"run": "same"},
    },
}

PAYLOADS = {
    "apply_profiles": {"local": {}, "push": {"push_to_of": True}},
    "auto_posts": {"run": {"posts": [{"text": "new post", "hours_to_live": 24}]},
                   "media": {"posts": [{"text": "new post", "media_files": [901], "hours_to_live": 24}]}},
    "auto_stories": {"story": {"media_files": [901]}},
    "birthday_message": {"run": {}},
    "customs_watch": {"owed": {}},
    "expired_message": {"run": {}},
    "expiry_message": {"run": {}},
    "full_ai_chat": {"shadow": {}, "live": {}},
    "gen_info": {"local": {"force_ids": [int(FAN)]}, "push": {"force_ids": [int(FAN)]}},
    "mass_premade": {"drip": {"messages": [
        {"text": "m1", "online_only": True, "media_folder_id": 5, "price": 10},
        {"text": "m2", "online_only": True, "delay_minutes": 15}]}},
    "nudge_online_fire": {"run": {"fan_id": FAN, "with_image": False}},
    "process_old_fans": {"local": {"fan_ids": [int(FAN)], "flag_only": True},
                         "push": {"fan_ids": [int(FAN)], "push_to_of": True}},
    "promo_reactivate": {"run": {"dry_run": False}},
    "purchase_followup": {"run": {}},
    "reply_mass_funnel": {"idle": {}, "landed": {}},
    "resubscribe_message": {"run": {}},
    "s4s_check": {"text_baseline": {}, "empty_baseline": {}},
    "s4s_post": {"run": {}, "media": {}},
    "scheduled_send": {
        "text": {"fan_id": FAN, "text": "hey", "send_purpose": "manual"},
        "tags": {"fan_id": FAN, "text": "hey", "send_purpose": "manual", "tagged_users": [46901]},
        "locked": {"fan_id": FAN, "text": "hey", "send_purpose": "manual", "locked_text": True, "price": 5},
    },
    "scrape_chats": {"sweep": {}},
    "scrape_fan": {"run": {"fan_ids": [FAN]}},
    "send_followup": {"run": {"with_image": False}},
    "send_mass_message": {"broadcast": {
        "text": "hey all", "user_lists": ["fans"], "exclude_replied_hours": 0, "exclude_inbound_hours": 0}},
    "send_welcome": {"run": {"message": ["welcome babe"], "with_image": False}},
    "unsend_messages": {"mass": {"policy": {"mass_text_hours": 8}}, "chat": {"policy": {"text_hours": 1}}},
    "welcome_chatter_for_info": {"run": {}},
}

SAME_REASONS = {"reply_mass_funnel": {"landed": "no_active_funnel_runs"}}

SAME_EFFECTS = {
    "fansly": {
        "apply_profiles": {"local": ("table:fan_profiles", "table:fans")},
        "auto_posts": {"run": ("POST /post", "job:unsend_messages", "table:posts")},
        "birthday_message": {"run": ("POST /message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages")},
        "customs_watch": {"owed": ("table:fans",)},
        "expired_message": {"run": ("POST /account/900000000000000007/followers", "POST /group", "POST /message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "full_ai_chat": {"shadow": ("table:ai_decisions",),
                         "live": ("POST /message/ack", "POST /message×2", "table:ai_decisions", "table:chats", "table:fans", "table:messages")},
        "gen_info": {"local": ("table:fan_profiles", "table:fans")},
        "nudge_online_fire": {"run": ("POST /message", "table:chats", "table:messages", "table:nudge_state")},
        "process_old_fans": {"local": ("table:skip_list",)},
        "reply_mass_funnel": {"landed": ("table:funnel_state",)},
        "s4s_post": {"run": ("POST /post", "job:s4s_check", "job:unsend_messages", "table:actions", "table:posts", "table:s4s_schedule")},
        "scheduled_send": {"text": ("POST /message", "table:chats", "table:fans", "table:messages")},
        "scrape_chats": {"sweep": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "scrape_fan": {"run": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "send_followup": {"run": ("POST /message", "table:chats", "table:fans", "table:followup_state", "table:messages")},
        "send_welcome": {"run": ("POST /account/900000000000000002/followers", "POST /message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state", "table:messages", "table:welcome_sent")},
        "unsend_messages": {"chat": ("POST /message/delete", "table:actions", "table:messages")},
        "welcome_chatter_for_info": {"run": ("POST /message", "POST /message/ack", "table:chats", "table:fans", "table:messages")},
    },
    "onlyfans": {
        "apply_profiles": {"local": ("table:fan_profiles", "table:fans"),
                           "push": ("set_fan_custom_name", "set_fan_note", "table:fan_profiles", "table:fans")},
        "auto_posts": {"run": ("create_post", "job:unsend_messages", "table:posts"),
                       "media": ("create_post", "job:unsend_messages", "table:posts")},
        "auto_stories": {"story": ("post_story_from_url",)},
        "birthday_message": {"run": ("send_message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages")},
        "customs_watch": {"owed": ("table:fans",)},
        "expired_message": {"run": ("follow_user", "send_message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "expiry_message": {"run": ("send_message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "full_ai_chat": {"shadow": ("table:ai_decisions",),
                         "live": ("mark_chat_read", "send_message×2", "table:ai_decisions", "table:chats", "table:fans", "table:messages")},
        "gen_info": {"local": ("table:fan_profiles", "table:fans"),
                     "push": ("set_fan_note", "table:fan_profiles", "table:fans")},
        "mass_premade": {"drip": ("job:mass_premade", "send_mass_message", "table:mass_runs")},
        "nudge_online_fire": {"run": ("send_message", "table:chats", "table:messages", "table:nudge_state")},
        "process_old_fans": {"local": ("table:skip_list",),
                             "push": ("set_fan_custom_name", "set_fan_note", "table:fan_profiles", "table:fans", "table:skip_list")},
        "promo_reactivate": {"run": ("create_promo", "job:promo_reactivate", "table:link_meta", "table:promo_campaigns", "table:promo_create_reservations", "table:promo_keep_state")},
        "purchase_followup": {"run": ("send_message", "table:chats", "table:fans", "table:messages", "table:purchase_followup_claims")},
        "reply_mass_funnel": {"landed": ("table:funnel_state",)},
        "resubscribe_message": {"run": ("send_message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "s4s_check": {"text_baseline": ("table:actions", "table:s4s_schedule"),
                      "empty_baseline": ("table:actions", "table:s4s_schedule")},
        "s4s_post": {"run": ("create_post", "job:s4s_check", "job:unsend_messages", "table:actions", "table:posts", "table:s4s_schedule"),
                     "media": ("create_post", "job:s4s_check", "job:unsend_messages", "table:actions", "table:posts", "table:s4s_media", "table:s4s_schedule", "upload_media")},
        "scheduled_send": {"text": ("send_message", "table:chats", "table:fans", "table:messages"),
                           "tags": ("send_message", "table:chats", "table:fans", "table:messages"),
                           "locked": ("send_message", "table:chats", "table:fans", "table:messages")},
        "scrape_chats": {"sweep": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "scrape_fan": {"run": ("table:chats", "table:fans", "table:messages", "table:scrape_history")},
        "send_followup": {"run": ("send_message", "table:chats", "table:fans", "table:followup_state", "table:messages")},
        "send_mass_message": {"broadcast": ("send_mass_message", "table:mass_runs")},
        "send_welcome": {"run": ("follow_user", "send_message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state", "table:messages", "table:welcome_sent")},
        "unsend_messages": {"mass": ("cancel_scheduled", "table:actions", "table:mass_broadcast_cache"),
                            "chat": ("table:actions", "table:messages", "unsend_message")},
        "welcome_chatter_for_info": {"run": ("mark_chat_read", "send_message", "table:chats", "table:fans", "table:messages")},
    },
}

OWNER_RUNS = {
    "fansly": {
        "apply_profiles": {"push": ("ok", None, ("table:fan_profiles", "table:fans"), None)},
        "auto_posts": {"media": ("error", None, (), None)},
        "expiry_message": {"run": ("ok", None, ("table:subscriber_snapshot",), None)},
        "gen_info": {"push": ("ok", None, ("POST /notes", "table:fan_profiles", "table:fans"), "POST /notes")},
        "process_old_fans": {"push": ("ok", None, ("table:fan_profiles", "table:fans", "table:skip_list"), None)},
        "promo_reactivate": {"run": ("ok", None, ("table:promo_keep_state",), None)},
        "purchase_followup": {"run": ("ok", None, (), None)},
        "resubscribe_message": {"run": ("ok", None, ("table:subscriber_snapshot",), None)},
        "s4s_check": {"text_baseline": ("error", None, (), "GET /post"), "empty_baseline": ("error", None, (), "GET /post")},
        "s4s_post": {"media": ("ok", "media_fetch_failed", ("table:actions", "table:s4s_media", "table:s4s_schedule"), "GET /media")},
    },
}

PARTIAL_RUNS: dict[str, dict] = {}

MARKER_ALLOWLIST: dict[str, dict[str, str]] = {
    "promo_reactivate": {"promotions": "the run catches the refusal as of_unreachable; owner:48 names it"},
}

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
    MARKER_ALLOWLIST.update(getattr(_extra, "MARKER_ALLOWLIST", {}))

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
            return ("ok", f"partial:{tail}", effects, None)
        return ("skipped", tail, (), None)
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
                 fake=None, world=None, extra: dict | None = None) -> tuple[tuple, "StatefulFansly | OFStandIn", str]:
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
    async with get_session() as s:
        job = ScheduledJob(account_id=aid, kind=job_kind or kind,
                           payload_json=json.dumps({**PAYLOADS[kind][branch], **(extra or {})}),
                           run_at=datetime.utcnow(), status="pending")
        s.add(job)
        await s.flush()
        job_id = job.id
    before = _tables()
    markers: list[str] = []
    token = fansly_shim.marker_calls.set(markers)
    ax._make_client, ax.of_write_paced = factory, _unpaced
    try:
        with patch.object(llm_client, "_fire", canned_llm), \
                patch.object(OFClient, "from_account", session_for(platform, fake)), \
                patch.dict("os.environ", {promo_create_guard.HOST_ENV: HOST}), \
                patch.object(tenant_keys, "typesafe_key_for", no_key), \
                (world or WORLDS.get((kind, branch), contextlib.nullcontext))():
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
    assert got == ("ok", "partial:platform_lacks:tip_ledger",
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
    assert got == ("ok", "partial:platform_lacks:tip_ledger", ("table:smart_lists",), None), got
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
    assert await _list_rows(aid) == {"Chatty": ("pending", lid, 49, "1 OnlyFans writes failed — retried next sync")}

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
    assert await _list_rows(aid) == {"Chatty": ("pending", lid, 49, "1 OnlyFans writes failed — retried next sync")}


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


async def case_a_list_gone_on_fansly_stays_error_and_is_never_recreated():
    gone = 900_000_000_000_009_999
    seed = tagged_lists([], [int(FAN)], {"name": "Chatty", "of_list_id": gone, "of_list_name": "Chatty"})
    aid = await _account("fansly", seed)
    got, fake, _aid = await _drive("fansly", "smart_list_sync", "chat", aid=aid)
    assert got == ("ok", None, ("table:smart_lists",), None), got
    want = {"Chatty": ("error", gone, None, f"list {gone} is not on Fansly")}
    assert await _list_rows(aid) == want
    await _drive("fansly", "smart_list_sync", "chat", aid=aid, fake=fake)
    assert [(m, p) for m, p, _b, _q in fake.calls] == [("GET", "/lists/account")] * 2, fake.calls
    assert await _list_rows(aid) == want

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
            assert _bodies(fake.calls) == [*_READ, ("POST", "/lists/remove", {"listId": str(lid)})], fake.calls
            assert str(lid) not in fake.lists and await _list_rows(aid) == {}, fake.lists
        else:
            assert got == ("ok", "partial:platform_lacks:delete_list", (), None), got
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


async def case_no_grant_refuses_every_priority_mass_leg_with_zero_requests_and_leaves_the_run():
    legs = {"queued": ("resolving", None), "resumed": ("running", {int(FAN): "pending"}),
            "running": ("running", {int(FAN): "pending", _OTHER: "claimed"})}
    for leg, (status, recipients) in legs.items():
        fake = StatefulFansly()
        aid, extra = await _pm_seeded("fansly", fansly_list(fake, [int(FAN)]), status=status, recipients=recipients)
        got, fake = await _pm_fansly(aid, extra, fake, grant=False)
        assert got == ("skipped", _PM_LACKS, (), None), (leg, got)
        assert fake.calls == [], (leg, fake.calls)
        assert await _pm_state(extra["run_id"]) == (status, None, recipients or {}), leg


async def case_priority_mass_to_following_refuses_first_even_with_a_grant():
    aid, extra = await _pm_seeded("fansly", "following")
    with _pm_grant(aid):
        got, fake, _aid = await _drive("fansly", "priority_mass", "following", aid=aid, extra=extra)
    assert got == ("skipped", "platform_lacks:following", (), None), got
    assert fake.calls == [] and (await _pm_state(extra["run_id"]))[0] == "resolving"


async def case_a_list_without_exactly_the_proof_fan_reads_members_ends_the_run_and_sends_nothing():
    for members in ([_OTHER], [int(FAN), _OTHER]):
        fake = StatefulFansly()
        aid, extra = await _pm_seeded("fansly", fansly_list(fake, members))
        got, fake = await _pm_fansly(aid, extra, fake)
        assert got == ("skipped", _PM_LACKS, (), None), (members, got)
        assert _bodies(fake.calls) == list(_READ), (members, fake.calls)
        assert await _pm_state(extra["run_id"]) == ("error", _PM_LACKS, {}), members


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
    assert await _pm_state(extra["run_id"]) == ("running", None, recipients)

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
        assert await _pm_state(extra["run_id"]) == ("running", None, {int(FAN): "pending"})
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
