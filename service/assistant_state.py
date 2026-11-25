from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from assistant_evidence import clean_label, humanize
from db.engine import get_session
from db.models import (
    AccountAiConfig, AccountHealth, AutomationRule, AutomationRun)

log = logging.getLogger("of-relay.assistant_state")


TIMEOUT_S = 1.0
CAP_CHARS = 4000
_FAILURE_HOURS = 24
_FAILING_KINDS = 3
HEADER = (
    "LIVE STATE for this account (wins over the manual for current values):")
FAIL_NOTE = (
    "\n\n(I couldn't read this account's live rules and switches just now, so "
    "anything above about what is turned ON came from the manual, not from "
    "this account.)")

# Strict whitelist: only each blob's `enabled` key is serialized; these blobs sit beside agency LLM keys and prompts leave the box.
_CONFIG_FLAGS: tuple[tuple[str, str], ...] = (
    ("autoreply", "autoreply_config_json"),
    ("reply_instant", "webhook_config_json"),
)


def _human_every(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"every {seconds // 3600}h"
    if seconds % 60 == 0:
        return f"every {seconds // 60}m"
    return f"every {seconds}s"


def _human_age(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    mins = max(0, int((datetime.utcnow() - then).total_seconds() // 60))
    return f"{humanize(mins)} ago"


def _last_run_detail(row: dict[str, Any]) -> str:
    # _serialize reads the run by KIND, not rule id: with two rules of a kind only _fetch_state keeps them apart.
    last = row.get("last_run")
    if not last:
        return "never run"
    age = _human_age(last.get("started_at"))
    status = last.get("status") or "?"
    detail = f"last run {age} {status}" if age else f"last run {status}"
    if status not in ("ok", "running") and last.get("error_text"):
        detail += f": {str(last['error_text'])[:120]}"
    return detail


def _rule_head(row: dict[str, Any], kinds: Counter) -> str:
    # clean_label, not the raw name: rule names are free text in a prompt and could forge block lines.
    kind = row["kind"]
    if kinds[kind] < 2:
        return kind
    name = clean_label(row.get("name"))
    return f'{kind} #{row["id"]}' + (f' "{name}"' if name else "")


def _rule_line(row: dict[str, Any], head: str, run: str) -> tuple[str, str]:
    if row["is_enabled"]:
        bits = [f"{head}: ON"]
        if row.get("every_seconds"):
            # The tick, not a send rate: "every 1m" read as "sends every minute".
            bits.append("checks " + _human_every(int(row["every_seconds"])))
        if not row.get("kind_registered", True):
            bits.append("no runner registered — inert")
    else:
        bits = [f"{head}: OFF"]
    short = ", ".join(bits)
    return (", ".join(bits + [run]) if run else short), short


async def _fetch_state(account_id: str) -> list[tuple[str, str]]:
    import automation_rules_api

    async with get_session() as s:
        health = await s.get(AccountHealth, account_id)
        failing = (await s.execute(
            select(AutomationRun.kind, func.count(), func.max(AutomationRun.started_at))
            .where(AutomationRun.account_id == account_id,
                   AutomationRun.status == "error",
                   AutomationRun.started_at >= datetime.utcnow()
                   - timedelta(hours=_FAILURE_HOURS))
            .group_by(AutomationRun.kind)
            .order_by(func.count().desc())
            .limit(_FAILING_KINDS)
        )).all()
        rules = (await s.execute(
            select(AutomationRule)
            .where(AutomationRule.account_id == account_id)
            .order_by(AutomationRule.kind, AutomationRule.id)
        )).scalars().all()
        rows = [await automation_rules_api._serialize(s, r) for r in rules]
        cfg = await s.get(AccountAiConfig, account_id)

    if health is not None and health.session_dead_at is not None:
        reason = f" ({health.session_dead_reason})" if health.session_dead_reason else ""
        paused = (f"paused: yes — OF session dead since "
                  f"{health.session_dead_at:%Y-%m-%d}{reason}; every automation "
                  f"is skipped until the session is re-linked")
    else:
        # Not "paused: no": the marker lags a dying session by days, and a bare "no" was read as proof the session was alive.
        paused = ("paused: no session-dead marker (its absence is NOT proof the "
                  "OnlyFans session is alive)")

    body: list[tuple[str, str]] = []

    # Failing kinds first so they outlive the cap; a kind with no rule (scrape_chats is global) has no rule line.
    for kind, count, last in failing:
        line = (f"FAILING {kind}: {count} errored run(s) in the last "
                f"{_FAILURE_HOURS}h, latest {_human_age(str(last))}")
        body.append((line, line))

    if not rows:
        # Say absence out loud: with no rules the bot read the config flags as switches someone turned off.
        empty = ("automation rules: NONE — this account has no rule of any "
                 "kind, so no scheduled sender can run on it at all")
        body.append((empty, empty))

    # Run is per KIND: shown on the rule line only where rule and kind coincide, else on its own line.
    kinds = Counter(row["kind"] for row in rows)
    for kind in sorted(kinds):
        group = [row for row in rows if row["kind"] == kind]
        solo = len(group) < 2
        if not solo:
            # Run line goes BEFORE its rules: the cap is a prefix, so what follows a long group is what gets lost.
            short = f"{kind}: {len(group)} rules, sharing one run history"
            body.append((f"{short} — {_last_run_detail(group[0])}", short))
        for row in group:
            body.append(_rule_line(row, _rule_head(row, kinds),
                                   _last_run_detail(row) if solo else ""))

    for label, column in _CONFIG_FLAGS:
        try:
            blob = json.loads(getattr(cfg, column, None) or "{}")
            enabled = bool(blob.get("enabled")) if isinstance(blob, dict) else False
        except (TypeError, ValueError):
            enabled = False
        line = f"{label} (config): enabled={'true' if enabled else 'false'}"
        body.append((line, line))
    return [(paused, paused)] + body


async def build(account_id: str, label: str | None = None) -> str | None:
    try:
        pairs = await asyncio.wait_for(
            _fetch_state(account_id), timeout=TIMEOUT_S)
    except Exception:  # noqa: BLE001 — ANY failure degrades, never errors
        log.warning("assistant: state fetch failed for account=%s",
                    account_id, exc_info=True)
        return None
    # Same reason as _rule_head: a nickname is free text entering a prompt.
    name = clean_label(label)
    who = f"account {account_id}" + (f" ({name})" if name else "")
    lines = [f"this is {who}"] + [full for full, _ in pairs]
    if len("\n".join(lines)) + len(HEADER) > CAP_CHARS:
        lines = [lines[0]] + [short for _, short in pairs]
    out, used = [HEADER], len(HEADER)
    for line in lines:
        if used + len(line) + 1 > CAP_CHARS:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)
