#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import contextlib  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from itertools import count  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import automation_registry  # noqa: E402
import fansly_shim  # noqa: E402
import llm_client  # noqa: E402
import platforms  # noqa: E402
import promo_create_guard  # noqa: E402
import tenant_keys  # noqa: E402
import test_platform_lift_table as lift_table  # noqa: E402
from _kind_verdict_seeds import (  # noqa: E402
    FAKE_STATE, FAN, HOST, SEEDS, WORLDS, OFStandIn, canned_llm, no_key, session_for,
)
from of_client import OFClient  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRun, MassRun, ScheduledJob  # noqa: E402

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
        "auto_follow": {"run": "same"},
        "auto_posts": {"run": "same", "media": "owner:42"},
        "auto_stories": {"story": "gated:platform_lacks:post_story_from_url"},
        "autoreply": {"run": "same"},
        "birthday_message": {"run": "same"},
        "customs_watch": {"owed": "same"},
        "expired_message": {"run": "same"},
        "expiry_message": {"run": "owner:44"},
        "full_ai_chat": {"shadow": "same", "live": "same"},
        "gen_info": {"local": "same", "push": "owner:55"},
        "mass_premade": {"drip": "gated:platform_lacks:send_mass_message"},
        "nudge_online": {"run": "owner:50"},
        "nudge_online_fire": {"run": "same"},
        "priority_mass": {"list": "owner:30"},
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
        "smart_list_sync": {"sync": "gated:platform_lacks:list_users_in"},
        "unsend_messages": {"mass": "gated:platform_lacks:mass_message_history", "chat": "same"},
        "welcome_chatter_for_info": {"run": "same"},
    },
    "onlyfans": {
        "apply_profiles": {"local": "same", "push": "same"},
        "auto_follow": {"run": "same"},
        "auto_posts": {"run": "same", "media": "same"},
        "auto_stories": {"story": "same"},
        "autoreply": {"run": "same"},
        "birthday_message": {"run": "same"},
        "customs_watch": {"owed": "same"},
        "expired_message": {"run": "same"},
        "expiry_message": {"run": "same"},
        "full_ai_chat": {"shadow": "same", "live": "same"},
        "gen_info": {"local": "same", "push": "same"},
        "mass_premade": {"drip": "same"},
        "nudge_online": {"run": "same"},
        "nudge_online_fire": {"run": "same"},
        "priority_mass": {"list": "same"},
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
        "smart_list_sync": {"sync": "same"},
        "unsend_messages": {"mass": "same", "chat": "same"},
        "welcome_chatter_for_info": {"run": "same"},
    },
}

PAYLOADS = {
    "apply_profiles": {"local": {}, "push": {"push_to_of": True}},
    "auto_follow": {"run": {"action": "follow", "dry_run": False}},
    "auto_posts": {"run": {"posts": [{"text": "new post", "hours_to_live": 24}]},
                   "media": {"posts": [{"text": "new post", "media_files": [901], "hours_to_live": 24}]}},
    "auto_stories": {"story": {"media_files": [901]}},
    "autoreply": {"run": {}},
    "birthday_message": {"run": {}},
    "customs_watch": {"owed": {}},
    "expired_message": {"run": {}},
    "expiry_message": {"run": {}},
    "full_ai_chat": {"shadow": {}, "live": {}},
    "gen_info": {"local": {"force_ids": [int(FAN)]}, "push": {"force_ids": [int(FAN)]}},
    "mass_premade": {"drip": {"messages": [
        {"text": "m1", "online_only": True, "media_folder_id": 5, "price": 10},
        {"text": "m2", "online_only": True, "delay_minutes": 15}]}},
    "nudge_online": {"run": {}},
    "nudge_online_fire": {"run": {"fan_id": FAN, "with_image": False}},
    "priority_mass": {"list": {}},
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
    "smart_list_sync": {"sync": {}},
    "unsend_messages": {"mass": {"policy": {"mass_text_hours": 8}}, "chat": {"policy": {"text_hours": 1}}},
    "welcome_chatter_for_info": {"run": {}},
}

SAME_REASONS = {"reply_mass_funnel": {"landed": "no_active_funnel_runs"}}

SAME_EFFECTS = {
    "fansly": {
        "apply_profiles": {"local": ("table:fan_profiles", "table:fans")},
        "auto_follow": {"run": ("POST /account/900000000000000002/followers", "table:follow_log", "table:follow_ping_state")},
        "auto_posts": {"run": ("POST /post", "job:unsend_messages", "table:posts")},
        "autoreply": {"run": ("POST /message", "table:autoreply_state", "table:chats", "table:fans", "table:messages")},
        "birthday_message": {"run": ("POST /message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages")},
        "customs_watch": {"owed": ("table:fans",)},
        "expired_message": {"run": ("POST /account/900000000000000007/followers", "POST /group", "POST /message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "full_ai_chat": {"shadow": ("table:ai_decisions",),
                         "live": ("POST /message", "POST /message/ack", "table:ai_decisions", "table:chats", "table:fans", "table:messages")},
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
        "auto_follow": {"run": ("follow_user", "table:follow_log", "table:follow_ping_state")},
        "auto_posts": {"run": ("create_post", "job:unsend_messages", "table:posts"),
                       "media": ("create_post", "job:unsend_messages", "table:posts")},
        "auto_stories": {"story": ("post_story_from_url",)},
        "autoreply": {"run": ("send_message", "table:autoreply_state", "table:chats", "table:fans", "table:messages")},
        "birthday_message": {"run": ("send_message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages")},
        "customs_watch": {"owed": ("table:fans",)},
        "expired_message": {"run": ("follow_user", "send_message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "expiry_message": {"run": ("send_message", "table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages", "table:subscriber_snapshot")},
        "full_ai_chat": {"shadow": ("table:ai_decisions",),
                         "live": ("mark_chat_read", "send_message", "table:ai_decisions", "table:chats", "table:fans", "table:messages")},
        "gen_info": {"local": ("table:fan_profiles", "table:fans"),
                     "push": ("set_fan_note", "table:fan_profiles", "table:fans")},
        "mass_premade": {"drip": ("job:mass_premade", "send_mass_message", "table:mass_runs")},
        "nudge_online": {"run": ("job:nudge_online_fire", "table:nudge_state")},
        "nudge_online_fire": {"run": ("send_message", "table:chats", "table:messages", "table:nudge_state")},
        "priority_mass": {"list": ("job:priority_mass", "send_message", "table:chats", "table:fans", "table:messages", "table:priority_mass_recipients", "table:priority_mass_runs")},
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
        "smart_list_sync": {"sync": ("add_users_to_lists", "create_list", "table:smart_lists")},
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
        "nudge_online": {"run": ("ok", None, ("job:nudge_online_fire", "table:nudge_state"), None)},
        "priority_mass": {"list": ("ok", "audience_unresolved", (), None)},
        "process_old_fans": {"push": ("ok", None, ("table:fan_profiles", "table:fans", "table:skip_list"), None)},
        "promo_reactivate": {"run": ("ok", None, ("table:promo_keep_state",), None)},
        "purchase_followup": {"run": ("ok", None, (), None)},
        "resubscribe_message": {"run": ("ok", None, ("table:subscriber_snapshot",), None)},
        "s4s_check": {"text_baseline": ("error", None, (), "GET /post"), "empty_baseline": ("error", None, (), "GET /post")},
        "s4s_post": {"media": ("ok", "media_fetch_failed", ("table:actions", "table:s4s_media", "table:s4s_schedule"), "GET /media")},
    },
}

MARKER_ALLOWLIST: dict[str, dict[str, str]] = {
    "priority_mass": {"list_users_in": "the run catches the refusal and stores an error row; owner:30 refuses first"},
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
        return ("skipped", tail, (), None)
    if head == "noop":
        return ("ok", tail, (), None)
    if head == "same":
        return ("ok", SAME_REASONS.get(kind, {}).get(branch), SAME_EFFECTS[platform][kind][branch], None)
    return None


async def observe(platform: str, kind: str, branch: str, *, job_kind: str | None = None) -> tuple:
    aid = str(next(_ACCOUNT_IDS))
    async with get_session() as s:
        s.add(Account(id=aid, nickname=aid))
    if platform == "fansly":
        account_registry.save_meta(aid, {"id": aid, "nickname": aid, "platform": "fansly"})
        fake = StatefulFansly()
        if shape := FAKE_STATE.get((kind, branch)):
            shape(fake)
    else:
        fake = OFStandIn(aid)

    def factory(_aid):
        return fake.client() if platform == "fansly" else fake
    seed = SEEDS.get((kind, branch))
    extra = await seed(aid, platform) if seed else None
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
                WORLDS.get((kind, branch), contextlib.nullcontext)():
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
        run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == aid))).scalar_one()
        claimed = await s.get(ScheduledJob, job_id)
    assert claimed.status == "done" or run.status == ERROR_STATUS, f"{where}: job {claimed.status} ({result})"
    if platform == "fansly":
        writes = {f"{m} {p}" for m, p, _b, _q in fake.calls if m != "GET"}
    else:
        writes = {c for c in fake.calls if c in OFStandIn.WRITES}
    tables = effect_tables(before, after, _shapes())
    jobs = {f"job:{k}" for k in await _new_jobs(aid, job_id)}
    reason = json.loads(run.stats_json or "{}").get("reason")
    return run.status, reason, tuple(sorted(writes | tables | jobs)), uncited[0] if uncited else None


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
    for table in (SAME_EFFECTS, OWNER_RUNS):
        for platform, kinds in table.items():
            for kind, branches in kinds.items():
                for branch in branches:
                    assert branch in KIND_VERDICTS[platform][kind], (platform, kind, branch)


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


_harness.run()
