"""service/automation_rules_api.py — CRUD over `automation_rules` for the
Automations control surface (the standalone /automations page).

The executor already runs the loop: `_materialize_due_rules` reads every
`is_enabled` rule each 30s tick and, when its `trigger_json={"every_seconds":N}`
cadence is due (and no job is already pending/running for that account+kind),
enqueues a `scheduled_jobs` row that the worker runs via `run_once`. This module
is just the operator's hands on that table — it never runs an automation inline.

Routes (all owner-gated via `auth`):

  GET    /admin/automation-kinds                  catalog of registered kinds + payload hints
  GET    /admin/automation-rules?account_id=      list rules (enriched: last run + next-due + pending)
  POST   /admin/automation-rules                  create a rule
  PATCH  /admin/automation-rules/{rule_id}        update name/enabled/interval/payload
  DELETE /admin/automation-rules/{rule_id}        delete a rule
  POST   /admin/automation-rules/{rule_id}/run-now  enqueue one immediate job (bypasses cadence)

A "rule" in the UI maps 1:1 to an `automation_rules` row. `every_seconds` is the
edited cadence (stored as `trigger_json`); `payload` is the per-run knob bag
(stored verbatim as `steps_json`). Both are validated here so a bad value can
never reach the executor.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from auth import assert_account_owned, clamp_account_filter
from automation_registry import (canonical_kind, is_registered, kind_family,
                                 load_automation_plugins, registered_kinds)
from automations import _customs
from db.engine import get_session
from db.models import AutomationRule, AutomationRun, Message, ScheduledJob
from permissions import require_opt_in_kind

log = logging.getLogger("of-relay.automation.rules_api")

router = APIRouter()

# Executor tick is 30s, so a cadence below that just wastes materialize passes.
# Cap the high end at 30 days — beyond that it's effectively "off, but enabled".
_MIN_EVERY_S = 30
_MAX_EVERY_S = 30 * 24 * 60 * 60
# Only reachable for a kind with no catalog entry below — the same number the
# editor falls back to, so a rule born from a settings tab and one built by hand
# get the same cadence.
_FALLBACK_EVERY_S = 300


# ── Kind catalog ──────────────────────────────────────────────────────
#
# Static metadata layered over the live registry. Drives the editor: each
# `knob` is a typed field spec — `type` picks the input widget (int→number,
# bool→switch, str→text/dropdown, ids→id-list, json→sub-editor) and optional
# `min`/`max`/`default`/`enum` constrain it (enforced both client-side and by
# `_validate_payload_for_kind`). `recurring` flags loops vs. action-style kinds
# so the UI can warn that an action kind does nothing on a bare timer without a
# payload. An optional kind-level `composer` ("mass_message" | "premade") tells
# the editor to build that kind's whole payload with the matching rich composer
# (MassMessageComposer / PremadeForm) instead of the per-knob fields — the knobs
# remain as the raw-JSON fallback. Unknown/future kinds still appear (from the
# registry) with no knobs
# (so their payload falls back to the raw-JSON escape hatch).
_CATALOG: dict[str, dict[str, Any]] = {
    "welcome_chatter_for_info": {
        "label": "Get to know fans (AI info-gather)", "recurring": True, "surface": "rules",
        "cadence_default_s": 60,
        "summary": "Opens and continues conversations to learn about a fan and "
                   "build his profile (one gentle question at a time; feeds "
                   "Generate fan profiles). It never pitches. When the chat ends "
                   "— his info is gathered or he hits the message cutoff, "
                   "whichever comes first — it can send ONE closing PPV (the "
                   "caption and price below, the media you pick), then your team "
                   "takes over. Leave media empty to just stop when the chat ends.",
        "example": "every 60s · limit 200 · max_replies 25 · history_tail 40",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "hint": "Chats scanned per tick"},
            {"key": "max_replies", "type": "int", "min": 1, "hint": "Max replies sent per tick"},
            {"key": "history_tail", "type": "int", "min": 1, "default": 40, "hint": "Recent messages the AI reads"},
            {"key": "model", "type": "str", "hint": "LLM override (else account default)"},
            {"key": "dry_run", "type": "bool", "hint": "generate but don't send"},
            {"key": "force_ids", "type": "ids", "hint": "[fan_id,…] target specific fans (bypasses gates)"},
            {"key": "only_fan_ids", "type": "ids", "hint": "[fan_id,…] scope the sweep to these fans (gates still apply)"},
            {"key": "max_fan_messages", "type": "int", "min": 3, "max": 100, "default": 10,
             "hint": "Message cutoff: stop after this many fan messages if his info is still not gathered"},
            # The closing PPV — off until media is picked. Sent once per fan, as
            # written, when this lane is finished with him. `prefill`: the editor
            # seeds the field with `default` so the operator only picks media;
            # the engine reads the same default when the key is absent.
            {"key": "closing_ppv_media_ids", "type": "ids", "widget": "vault_media",
             "hint": "Closing PPV media from the vault. Leave media empty to just stop when the chat ends."},
            {"key": "closing_ppv_text", "type": "str", "prefill": True,
             "default": "loved getting to know u 🙈 made u a lil something, open it when ur alone 😘",
             "hint": "Closing PPV caption, sent word-for-word as his last message from this chat"},
            {"key": "closing_ppv_price_cents", "type": "int", "min": 300, "max": 20_000,
             "default": 1000, "prefill": True,
             "hint": "Closing PPV price in cents, $3-$200 (1000 = $10)"},
        ],
    },
    "autoreply": {
        "label": "Auto Convo (reply when the team is slow)", "recurring": True, "surface": "rules",
        "cadence_default_s": 180,
        "summary": "Continue the chat with a known low-spend fan when nobody answered his message in time. Never-PPV, no info-gather. Gates (silence window, spend caps, info-complete) live in the Settings → Auto Convo tab.",
        "example": "every 3m · limit 200 · max_sends 25",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "default": 200, "hint": "candidate sweep ceiling per tick"},
            {"key": "max_sends", "type": "int", "min": 1, "default": 25, "hint": "replies sent per tick"},
            {"key": "model", "type": "str", "hint": "LLM override (else account default)"},
            {"key": "dry_run", "type": "bool", "hint": "generate but don't send"},
            {"key": "only_fan_ids", "type": "ids", "hint": "[fan_id,…] scope the sweep to these fans (gates still apply)"},
        ],
    },
    "auto_follow": {
        # `surface: internal` on purpose — this kind is raw-JSON-only today and
        # has no typed editor. The entry exists so `_validate_payload_for_kind`
        # TYPES the knobs at save: without it `money_gate: "false"` (the string)
        # saved fine and evaluated truthy, leaving the money gate ON when the
        # operator had meant to switch it off. Give it a UI surface the day
        # someone builds the editor.
        "label": "Auto-follow", "recurring": True, "surface": "internal",
        "cadence_default_s": 14400,
        "summary": "Notification-only nudge: follow / re-follow fans so OF pushes "
                   "a 'started following you'. Never sends a DM.",
        "example": "every 4h · action follow · daily_cap 30 · dry_run off",
        "knobs": [
            # The only action. The engine SKIPS a rule whose action is missing or
            # anything else (`{"skipped": "bad_action"}`); it never defaults to
            # follow, which can buy a priced profile.
            {"key": "action", "type": "str", "default": "follow", "enum": ["follow"],
             "hint": "the nudge to fire (follow is the only one)"},
            {"key": "daily_cap", "type": "int", "min": 0, "max": 1000, "default": 50,
             "hint": "max notifications this RUN (0 = the operator's stop switch)"},
            {"key": "dry_run", "type": "bool", "default": True,
             "hint": "plan only, no OF mutation — the preview runs the gate too"},
            {"key": "money_gate", "type": "bool", "default": True,
             "hint": "⚠️ MONEY: price-check before following. "
                     "FALSE follows blind and BUYS every priced profile in the "
                     "pool (~3% of a stored audience, ≈$177 per 711 fans)"},
            {"key": "min_days_between_pings", "type": "int", "min": 1, "max": 365, "default": 14,
             "hint": "per-fan notification cooldown in days — one shared ledger, "
                     "and the backfill pool's only progress marker"},
            {"key": "targets", "type": "json",
             "hint": '{"source": "all_stored"|"expired"|"recent_active"|"smart_list"|"fan_ids"} '
                     "or a list of those"},
        ],
    },
    "smart_list_sync": {
        "label": "Smart list sync", "recurring": True, "surface": "internal",
        "cadence_default_s": 1800,
        "summary": "Mirrors every active Smart List into its OnlyFans list "
                   "(full crawl, diff, paced writes under a per-run budget). "
                   "Created by Growth → Smart Lists → Sync to OnlyFans.",
        "example": "every 30m · list membership only, never a message",
        "knobs": [],
    },
    "send_welcome": {
        "label": "Welcome new subscribers", "recurring": True, "surface": "brain",
        "summary": "Send a generated welcome to fans who haven't been welcomed.",
        "example": "every 60s · limit 30 · max_welcomes 25 · with image",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "default": 30, "hint": "fans scanned per tick"},
            {"key": "max_welcomes", "type": "int", "min": 1, "default": 25, "hint": "cap sends per tick"},
            {"key": "with_image", "type": "bool", "default": True, "hint": "attach the time-of-day welcome image"},
            {"key": "time_only", "type": "bool", "default": True, "hint": "2nd bubble says only the day/time + location (no activity)"},
            {"key": "skip_time_bubble", "type": "bool", "default": False, "hint": "drop the 2nd bubble entirely — greeting, then the question, then the GIF (outranks time_only and any pinned line)"},
            {"key": "human_pace", "type": "bool", "default": True, "hint": "pace the burst like a person (quiet gaps before the bubbles) and welcome several fans at once — a UI 'send test' is exempt and stays instant"},
            {"key": "stop_on_reply", "type": "bool", "default": True, "hint": "stop the welcome as soon as he replies — she finishes the bubble she's typing, and the chat engine answers him instead"},
            {"key": "follow_back", "type": "bool", "default": True, "hint": "follow each new sub back in the same tick — OF pushes them a 'started following you' on top of the welcome"},
            {"key": "follow_back_gate", "type": "bool", "default": True, "hint": "⚠️ MONEY: price-check each fan before following back and SKIP the ones who charge. ON by default (costs +1 read per sub); OFF follows blind, so a new sub who is themself a PAID creator charges you their price"},
            {"key": "message", "type": "json", "hint": "your own welcome, sent as ONE message instead of the whole burst (no image, question or GIF): \"text\", or [\"text\",…] variants, one picked per fan; {name} = the fan's name (blank = the generated burst)"},
            {"key": "question", "type": "str", "default": "what's yours?", "hint": "3rd bubble: this exact question, sent word-for-word (blank = off)"},
            {"key": "gif_id", "type": "str", "hint": "4th bubble: giphy id of a GIF sent after the question (blank = off)"},
            {"key": "dry_run", "type": "bool", "hint": "generate but don't send"},
            {"key": "follow_ups", "type": "json", "hint": '[{"text": "…", "delay_minutes": 30},…] sent after the welcome, each that long after the last; any reply from the fan ends them'},
            {"key": "after_of_welcome", "type": "bool", "default": False, "hint": "OnlyFans' own welcome is message 1: while it is on, send no welcome, only the follow-ups"},
        ],
    },
    "send_followup": {
        "label": "Follow up quiet fans", "recurring": True, "surface": "rules",
        "cadence_default_s": 3600,
        "summary": "Re-engage fans who went silent after a prior message.",
        "example": "every 1h · with_image on · limit 100",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "hint": "fans scanned per tick"},
            {"key": "with_image", "type": "bool", "default": True, "hint": "attach an image"},
            {"key": "step_hours", "type": "json", "hint": "[h1,h2,…] override per-step silence thresholds (hours); must be under 168 — the drip stops at a week of silence"},
            {"key": "exclude_replied_hours", "type": "int", "min": 0, "default": 12, "hint": "contact guard: hold a due step while ANY automation/chatter touched the fan in the last N hours (0 = off)"},
            {"key": "model", "type": "str", "hint": "LLM override"},
            {"key": "dry_run", "type": "bool", "hint": "generate but don't send"},
        ],
    },
    "gen_info": {
        "label": "Generate fan profiles", "recurring": True, "surface": "rules",
        "cadence_default_s": 86400,
        "summary": "Build/refresh fan profiles from chat history via the LLM; writes the OF nickname + Fan notes.",
        "example": "daily · limit 200",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "default": 200, "hint": "fans per tick"},
            {"key": "model", "type": "str", "hint": "LLM override"},
            {"key": "force_ids", "type": "ids", "hint": "[fan_id,…] re-profile specific fans"},
            {"key": "refill_ids", "type": "ids", "hint": "[fan_id,…] refresh just these (still gated by staleness)"},
        ],
    },
    "apply_profiles": {
        "label": "Apply profiles (nick + notes)", "recurring": True, "surface": "rules",
        "cadence_default_s": 3600,
        "summary": "Materialise generated nickname + sticky note onto fans; optionally push to OF.",
        "example": "every 1h · limit 200 · push_to_of on",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "hint": "fans swept per tick"},
            {"key": "force_ids", "type": "ids", "hint": "[fan_id,…] bypass the 24h cooldown"},
            {"key": "push_to_of", "type": "bool", "hint": "write nickname + note onto OnlyFans (not just our DB)"},
        ],
    },
    "customs_watch": {
        "label": "Customs owed (tip → voice note)", "recurring": True, "surface": "rules",
        "cadence_default_s": 900,
        "summary": ("Tag fans who tipped for a custom and haven't got it yet, and "
                    "stop the AI selling to them until it ships."),
        "example": f"every 15 min · min_cents {_customs.MIN_CENTS} · lookback 72h",
        "knobs": [
            # THE knob. What a big DM tip MEANS is per-account: on the male
            # accounts it is an order, on the female ones it was generosity five
            # times last month. Set it too low and the bot stops selling to a
            # generous fan until a human notices. The default is the engine's
            # own fallback floor, imported so the two cannot be edited apart.
            {"key": "min_cents", "type": "int", "min": 1, "default": _customs.MIN_CENTS,
             "hint": ("cents — a tip BURST totalling at least this counts as a custom "
                      f"order (${_customs.MIN_CENTS // 100} = {_customs.MIN_CENTS}). "
                      f"On an account that SELLS customs keep it ≤ {_customs.ASK_MIN_CENTS} "
                      f"(${_customs.ASK_MIN_CENTS // 100}, the bottom of the quoted band) "
                      "or a fan can pay the quoted price and never be marked — the "
                      "watch warns every run while that holds")},
            {"key": "lookback_hours", "type": "int", "min": 1, "default": 72,
             "hint": "how far back to scan for tips; keep short so switching on doesn't mark old ones"},
            {"key": "limit", "type": "int", "min": 1,
             "hint": ("tips scanned per tick — EVERY settled DM tip counts "
                      "(sub-floor burst halves too), so a tip-heavy account "
                      "covers fewer hours per tick than the number suggests")},
            {"key": "only_fan_ids", "type": "ids", "hint": "[fan_id,…] restrict to these fans"},
            {"key": "dry_run", "type": "bool", "hint": "report what it would mark, write nothing"},
        ],
    },
    "scrape_chats": {
        "label": "Backfill chat history", "recurring": True, "surface": "rules",
        "cadence_default_s": 86400, "group": "advanced",
        "summary": "Fill message/chat gaps from OF (complements the WS pump).",
        "example": "daily · limit 50 · max_pages 40",
        "knobs": [
            {"key": "fan_ids", "type": "ids", "hint": "[fan_id,…] limit to these chats"},
            {"key": "limit", "type": "int", "min": 1, "default": 50, "hint": "Chats to backfill per run"},
            {"key": "max_pages", "type": "int", "min": 1, "default": 40, "hint": "History pages pulled per chat"},
        ],
    },
    "process_old_fans": {
        "label": "Onboard pre-AI fans", "recurring": False, "surface": "rules",
        "group": "advanced",
        "summary": "Flag old fans out of the AI chatter, then profile + apply them.",
        "example": "one-shot · fan_ids [..] · flag_only off",
        "knobs": [
            {"key": "fan_ids", "type": "ids", "hint": "[fan_id,…] the old-fan batch"},
            {"key": "usernames", "type": "json", "hint": '["@user",…] resolved via of_username'},
            {"key": "recent_limit", "type": "int", "min": 1, "hint": "no fan_ids/usernames → take the N most-recent fans"},
            {"key": "recent_by", "type": "str", "enum": ["subscribed", "messaged"],
             "hint": "order the recent_limit fallback: subscribed | messaged"},
            {"key": "flag_only", "type": "bool", "hint": "--no-scrape: only flip flags"},
            {"key": "reprocess", "type": "bool", "hint": "re-run already-onboarded fans"},
            {"key": "push_to_of", "type": "bool", "hint": "also write nicknames + notes onto OnlyFans"},
            {"key": "limit", "type": "int", "min": 1, "hint": "cap batch size (forwarded to gen_info + apply_profiles)"},
            {"key": "model", "type": "str", "hint": "LLM override forwarded to gen_info"},
        ],
    },
    "send_mass_message": {
        "label": "Mass message", "recurring": False, "surface": "ready_made",
        "summary": "Send one message to an audience. Usually driven from the composer.",
        "example": "one-shot · text + media · price 0 (free) · → list ids",
        # The full payload (text/audience/media/price/online-targeting) is built
        # by the rich MassMessageComposer in the editor — `composer` tells the UI
        # which one to launch instead of the per-knob JSON box. The knobs below
        # stay as the raw-JSON fallback for power users.
        "composer": "mass_message",
        "knobs": [
            {"key": "text", "type": "str", "hint": "message body"},
            {"key": "price", "type": "int", "min": 0, "hint": "PPV price (cents); 0 = free"},
            {"key": "list_ids", "type": "json", "hint": "audience OF list ids"},
        ],
    },
    "reply_mass_funnel": {
        # The reply-WALKER. Funnels send the opener (send_mass_message), but the
        # reply/PPV steps only advance while an ENABLED rule of this kind polls for
        # fans who replied. With a blank `mass_run_id` it walks EVERY active funnel
        # broadcast — so ONE recurring rule per account makes all funnels work. The
        # Mass-funnels tab surfaces/toggles this rule; it's also creatable here.
        "label": "Walk mass-funnel replies", "recurring": True, "surface": "rules",
        "cadence_default_s": 120, "group": "advanced",
        "summary": "Poll fans who replied to a funnel broadcast and advance them "
                   "through the funnel's reply / PPV steps. Funnels need this enabled "
                   "to move past the opener. Leave mass_run_id blank to walk every "
                   "active funnel broadcast.",
        "example": "every 2m · all active funnels · max_chats 40",
        "knobs": [
            {"key": "mass_run_id", "type": "int", "min": 1, "hint": "limit to ONE mass run (blank = all active funnel broadcasts)"},
            {"key": "max_chats", "type": "int", "min": 1, "default": 40, "hint": "max fans advanced per tick"},
            {"key": "model", "type": "str", "hint": "LLM override"},
            {"key": "dry_run", "type": "bool", "hint": "generate but don't send"},
        ],
    },
    "unsend_messages": {
        "label": "Unsend messages", "recurring": False, "surface": "ready_made",
        "summary": "Unsend targeted messages or sweep per-policy.",
        "example": 'one-shot · policy {"mass_text_hours": 4}',
        "knobs": [
            {"key": "targets", "type": "json", "hint": "[{message_id, fan_id}|{queue_id, mass_run_id}|{post_id}|{story_id}]"},
            {"key": "policy", "type": "json", "hint": '{"text_hours": N} sweep window'},
        ],
    },
    "auto_posts": {
        "label": "Auto posts (self-cleaning feed)", "recurring": False, "surface": "ready_made",
        "summary": "Post a list of ready posts one by one; each optionally auto-deletes after N hours.",
        "example": "one-shot · posts [..] · hours_to_live 24 · resend_count 0",
        # `posts:[…]` is built by the PremadeForm composer in the editor.
        "composer": "premade",
        "knobs": [
            {"key": "posts", "type": "json",
             "hint": '[{text|texts:[..], media_files:[id]|media_folder_id, media_count, price, hours_to_live, delay_minutes}] — random text+image(s) per fire'},
            {"key": "resend_after_hours", "type": "int", "min": 1, "hint": "re-post the whole list this long after it finishes"},
            {"key": "resend_count", "type": "int", "min": 0, "hint": "extra full cycles (0 = post the list once)"},
            {"key": "dry_run", "type": "bool", "hint": "plan only — no post, no delete"},
        ],
    },
    "auto_stories": {
        "label": "Auto stories (from a vault folder)", "recurring": True, "surface": "settings",
        "summary": "On a schedule, post random photos from a vault folder as stories, auto-deleting each after N hours.",
        "example": "daily · folder_id 99 · per_run 1 · hours_to_live 24",
        "knobs": [
            {"key": "folder_id", "type": "int", "min": 1, "hint": "vault folder/list id to pull photos from"},
            {"key": "per_run", "type": "int", "min": 1, "default": 1, "hint": "stories to post per trigger"},
            {"key": "hours_to_live", "type": "int", "min": 0, "hint": "auto-delete each story after N hours (0 = keep)"},
            {"key": "watermark_text", "type": "str", "hint": "optional watermark stamped on re-upload"},
            {"key": "dry_run", "type": "bool", "hint": "resolve picks, post nothing"},
        ],
    },
    "nudge_online": {
        "label": "Nudge online (message a fan when they come online)", "recurring": True, "surface": "ready_made",
        "summary": "Every ~60s, detect fans who just came online and send a personalized nudge after a short delay. Rich config (delays, caps, quiet hours, tease pools) lives in the Settings → Nudge online tab.",
        "example": "every 60s · limit 200 · with_image on",
        "knobs": [
            {"key": "limit", "type": "int", "min": 1, "default": 200, "hint": "online fans to scan per tick"},
            {"key": "with_image", "type": "bool", "default": True, "hint": "attach the per-slot image"},
        ],
    },
    "nudge_online_fire": {
        "label": "Nudge online — fire (internal)", "recurring": False, "surface": "internal",
        "summary": "Internal one-shot enqueued by nudge_online; re-validates the fan is still online and sends. Not scheduled directly.",
        "example": "internal · fan_id set by the detector",
        "knobs": [
            {"key": "fan_id", "type": "int", "min": 1, "hint": "the fan to nudge (set by the detector)"},
        ],
    },
    "mass_premade": {
        "label": "Premade mass (send / resend / unsend)", "recurring": False, "surface": "ready_made",
        "summary": "Send ready-made broadcasts on a timer — resend later and/or auto-unsend.",
        "example": "one-shot · messages [..] · resend_after_hours 24 · unsend_after_hours 6",
        # `messages:[…]` is built by the PremadeForm composer in the editor.
        "composer": "premade",
        "knobs": [
            {"key": "messages", "type": "json",
             "hint": '[{text|texts:[..], media_files|media_folder_id, media_count, online_only, unsend_after_hours, resend_after_hours, resend_count, delay_minutes}] — random text+image(s) per fire'},
            {"key": "dry_run", "type": "bool", "hint": "plan only — no send, no enqueue"},
        ],
    },
}

# Maps a knob `type` to the UI input widget the editor renders. A knob may set
# `widget` explicitly to override (e.g. a future `str` enum → "select").
_WIDGET_FOR_TYPE: dict[str, str] = {
    "int": "number",
    "bool": "switch",
    "str": "text",
    "ids": "ids",
    "json": "json",
}


def _decorate_knob(kn: dict[str, Any]) -> dict[str, Any]:
    """Inject the derived `widget` (unless explicit) so the editor can render a
    typed field per knob instead of one raw-JSON box for the whole payload."""
    widget = kn.get("widget") or _WIDGET_FOR_TYPE.get(kn["type"], "text")
    return {**kn, "widget": widget}


# What a rule CREATED for a kind starts with, when its caller sends no payload.
# Writing the nickname and note onto OnlyFans is what "apply profiles" means to
# an operator, and what that kind's catalog example already advertises.
#
# It lives out here, and is not a knob `default`, for one reason: both `_CATALOG`
# (spread onto the wire) and a knob default are DISPLAY, and the editor applies
# defaults when it OPENS a rule as well as when it makes one. Either would let a
# row created without the key acquire it on the next unrelated save — turning an
# account's silence into a decision it never made. Only a create reads this.
_CREATE_PAYLOAD: dict[str, dict[str, Any]] = {
    "apply_profiles": {"push_to_of": True},
    # The Auto-follow list's switch (Infloww: "Automatically follow fans whose
    # subscriptions have expired"): OF's recently-expired list, live, money gate
    # on by default. An account that already has a rule keeps its own payload.
    "auto_follow": {"action": "follow", "targets": {"source": "expired"}, "dry_run": False},
}


def _kind_catalog() -> list[dict[str, Any]]:
    load_automation_plugins()  # ensure every @register has run
    out: list[dict[str, Any]] = []
    for kind in registered_kinds():
        meta = _CATALOG.get(kind)
        if meta is None:
            # Unknown/future kind (registered but not catalogued): default it to
            # the internal surface so it never leaks into the rules dropdown.
            out.append({"kind": kind, "label": kind, "recurring": True,
                        "summary": "", "surface": "internal", "knobs": []})
        else:
            knobs = [_decorate_knob(kn) for kn in meta.get("knobs", [])]
            out.append({"kind": kind, **meta, "knobs": knobs})
    return out


# Kind validity is automation_registry.is_registered — the ONE predicate
# (canonicalizes legacy names, knows scrape_chats). No local copy.


# ── Validation helpers ────────────────────────────────────────────────

def _validate_every(every_seconds: Any) -> int:
    if not isinstance(every_seconds, (int, float)) or isinstance(every_seconds, bool):
        raise HTTPException(422, "every_seconds must be a number")
    n = int(every_seconds)
    if n < _MIN_EVERY_S:
        raise HTTPException(422, f"every_seconds must be ≥ {_MIN_EVERY_S} (executor ticks every 30s)")
    if n > _MAX_EVERY_S:
        raise HTTPException(422, f"every_seconds must be ≤ {_MAX_EVERY_S}")
    return n


def _validate_trigger(trigger: Any) -> dict:
    """Normalize a rich trigger into the stored `trigger_json` dict. Accepts:

      • {"every_seconds": N}                 — interval (existing behavior)
      • {"daily_at": ["HH:MM", ...],         — clock times (one fire per slot/day)
         "tz_offset_minutes": <int>}            local zone offset (UTC+min)
      • optional "max_runs": N on either     — auto-disable after N total runs

    Raises 422 on a malformed shape."""
    if not isinstance(trigger, dict):
        raise HTTPException(422, "trigger must be a JSON object")
    out: dict[str, Any] = {}

    daily_at = trigger.get("daily_at")
    if daily_at is not None:
        if not isinstance(daily_at, list) or not daily_at:
            raise HTTPException(422, "daily_at must be a non-empty list of 'HH:MM'")
        norm: list[str] = []
        for t in daily_at:
            if not isinstance(t, str) or ":" not in t:
                raise HTTPException(422, f"bad time {t!r} (want 'HH:MM')")
            try:
                hh, mm = (int(x) for x in t.split(":", 1))
            except ValueError:
                raise HTTPException(422, f"bad time {t!r} (want 'HH:MM')")
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise HTTPException(422, f"time out of range: {t!r}")
            norm.append(f"{hh:02d}:{mm:02d}")
        out["daily_at"] = norm
        tz = trigger.get("tz_offset_minutes", 0)
        if not isinstance(tz, (int, float)) or isinstance(tz, bool) or not (-720 <= tz <= 840):
            raise HTTPException(422, "tz_offset_minutes must be between -720 and 840")
        out["tz_offset_minutes"] = int(tz)
    elif trigger.get("every_seconds") is not None:
        out["every_seconds"] = _validate_every(trigger["every_seconds"])
    else:
        raise HTTPException(422, "trigger needs every_seconds or daily_at")

    max_runs = trigger.get("max_runs")
    if max_runs is not None:
        if not isinstance(max_runs, (int, float)) or isinstance(max_runs, bool) or max_runs < 1:
            raise HTTPException(422, "max_runs must be a positive integer")
        out["max_runs"] = int(max_runs)
    return out


def _validate_payload(payload: Any) -> dict:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "payload must be a JSON object")
    # Round-trips cleanly (rejects NaN/Infinity and non-serialisable values).
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"payload is not JSON-serialisable: {e}")
    return payload


def _coerce_whole(key: str, val: Any) -> int:
    """A JSON number that is a whole int (rejects bools, fractions, strings)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise HTTPException(422, f"{key} must be a whole number")
    n = int(val)
    if n != val:
        raise HTTPException(422, f"{key} must be a whole number")
    return n


def _validate_payload_for_kind(kind: str, payload: Any) -> dict:
    """`_validate_payload` (object + JSON-serialisable) PLUS per-knob value
    checks from the kind's catalog so the typed editor's contract is enforced
    server-side: int `min`/`max` bounds, `enum` membership, bool/str types, and
    id-list coercion (each id → int). Keys NOT in the catalog pass through
    untouched — forward-compat with payload fields newer than the catalog, and
    with the raw-JSON escape hatch. Returns the (coerced) payload dict."""
    payload = _validate_payload(payload)
    knobs = {k["key"]: k for k in _CATALOG.get(kind, {}).get("knobs", [])}
    out = dict(payload)
    for key, val in payload.items():
        kn = knobs.get(key)
        if kn is None:
            continue  # unknown/future knob — leave as-is
        if val is None:
            # ⚠️ A NULL FOR A CATALOGUED KNOB IS DROPPED AT THE BOUNDARY, not
            # stored and resolved later.
            #
            # `null` used to be waved through here as "an explicit null — leave
            # as-is", which made it the ONE non-boolean that reached storage for
            # a `bool` knob, and every reader downstream then had to know that
            # `null` means "absent" rather than "false". That knowledge landed at
            # eight Python read sites, at `app/lib/boolKnob.ts`, and at a
            # source-regex test that has to know every way a module might spell a
            # payload read — a lint written in `assert`s, whose own docstring
            # admits "a new spelling is a red here".
            #
            # A key that says nothing IS an absent key. Popping it makes that
            # true in the store instead of true by convention, and covers `int`,
            # `str` and `ids` at the same time — the same hole existed for all
            # four, and only the bool one had a defence built for it. `bool_knob`
            # and `boolKnob` keep their null clause: a rule written before this
            # line still carries stored nulls, so it is now a defence against
            # history rather than the contract.
            out.pop(key, None)
            continue
        t = kn["type"]
        if t == "int":
            n = _coerce_whole(key, val)
            lo, hi = kn.get("min"), kn.get("max")
            if lo is not None and n < lo:
                raise HTTPException(422, f"{key} must be ≥ {lo}")
            if hi is not None and n > hi:
                raise HTTPException(422, f"{key} must be ≤ {hi}")
            out[key] = n
        elif t == "bool":
            if not isinstance(val, bool):
                raise HTTPException(422, f"{key} must be true or false")
        elif t == "str":
            if not isinstance(val, str):
                raise HTTPException(422, f"{key} must be text")
            enum = kn.get("enum")
            if enum and val not in enum:
                raise HTTPException(422, f"{key} must be one of {', '.join(map(str, enum))}")
        elif t == "ids":
            if not isinstance(val, list):
                raise HTTPException(422, f"{key} must be a list of ids")
            out[key] = [_coerce_whole(key, x) for x in val]
        # "json": structured free-form — already proven serialisable above.
    if kind == "welcome_chatter_for_info":
        # The closing PPV: media with no price/caption uses the defaults (the
        # engine's `_CLOSING_PPV_DEFAULT_*`); the price bounds are the knob's.
        import smart_message_extras as extras
        media = out.get("closing_ppv_media_ids") or []
        if len(media) > extras.MEDIA_MAX:
            raise HTTPException(422, f"closing_ppv_media_ids: at most {extras.MEDIA_MAX} media")
    if kind == "send_welcome":
        # The Delayed welcome's Smart Message settings (media, price, dates,
        # Auto-unsend, the random delay), held to the same contract as the
        # other Triggers' config routes.
        import smart_message_extras as extras
        out.update(extras.validate(payload, delay=True))
        extras.check(out)
    return out


def _validate_quiet_hours(qh: Any) -> list[int] | None:
    """Opt-in quiet-hours band → `[start, end]` (creator-LOCAL hours, 0-23) or None.
    DEFAULT OFF: None / `[0, 0]` / equal start==end → None (rule fires 24/7). The
    band [start, end) wraps midnight when start > end. Same convention the executor
    enforces (`automation_executor._in_quiet_hours`) and nudge_online uses."""
    if qh is None:
        return None
    if not isinstance(qh, (list, tuple)) or len(qh) != 2:
        raise HTTPException(422, "quiet_hours must be [start_hour, end_hour]")
    try:
        start, end = int(qh[0]), int(qh[1])
    except (TypeError, ValueError):
        raise HTTPException(422, "quiet_hours must be two integers")
    if not (0 <= start < 24 and 0 <= end < 24):
        raise HTTPException(422, "quiet_hours must be hours 0-23")
    return None if start == end else [start, end]


def _every_seconds_of(rule: AutomationRule) -> int | None:
    try:
        trig = json.loads(rule.trigger_json or "{}")
    except (TypeError, ValueError):
        return None
    v = trig.get("every_seconds")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _safe_json(raw: str | None) -> Any:
    """Parse a JSON column to a dict, else None (for last_run.stats display)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _trigger_of(rule: AutomationRule) -> dict:
    """Parsed trigger_json (interval/clock + max_runs) for the editor."""
    try:
        t = json.loads(rule.trigger_json or "{}")
        return t if isinstance(t, dict) else {}
    except (TypeError, ValueError):
        return {}


def _payload_of(rule: AutomationRule) -> dict:
    try:
        p = json.loads(rule.steps_json or "{}")
    except (TypeError, ValueError):
        return {}
    return p if isinstance(p, dict) else {}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def _last_run(s, account_id: str, kind: str) -> AutomationRun | None:
    return (
        await s.execute(
            select(AutomationRun)
            .where(AutomationRun.account_id == account_id, AutomationRun.kind == kind)
            .order_by(AutomationRun.started_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def _has_pending_job(s, account_id: str, kind: str) -> bool:
    """True iff a job for (account, kind) is due now. Future-dated one-shots
    (e.g. auto_stories' delete-later cleanup, which shares the `unsend_messages`
    kind) are excluded so a recurring rule's badge isn't falsely flagged
    "queued" by an unrelated cleanup scheduled hours out — mirrors the
    materialize guard in automation_executor._materialize_due_rules, including
    its kind_family match (a pre-rename pending job still counts as queued)."""
    row = (
        await s.execute(
            select(ScheduledJob.id)
            .where(
                ScheduledJob.account_id == account_id,
                ScheduledJob.kind.in_(kind_family(kind)),
                ScheduledJob.status.in_(("pending", "running")),
                ScheduledJob.run_at <= datetime.utcnow(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _serialize(s, rule: AutomationRule) -> dict[str, Any]:
    """One rule + live status (last run, next-due estimate, pending job).

    A legacy-kind row (migration 0062 not yet run on its DB) serializes under
    its CANONICAL name: runs and jobs are written canonical now, so querying
    status by the stored token would show a live rule as never-ran — and the
    UI's kind catalog only knows live names."""
    kind = canonical_kind(rule.kind)
    every = _every_seconds_of(rule)
    last = await _last_run(s, rule.account_id, kind)
    next_due: str | None = None
    if rule.is_enabled and every:
        # Anchor on the rule's OWN jobs, like the materializer: a test or one-shot
        # run of the same kind must not move the displayed next fire. A rule that
        # never fired is due on the next tick.
        from automation_executor import rule_last_fired_at  # local: avoid load cycle
        fired = await rule_last_fired_at(s, rule.id)
        next_due = _iso(fired + timedelta(seconds=every) if fired else datetime.utcnow())
    return {
        "id": rule.id,
        "account_id": rule.account_id,
        "name": rule.name,
        "kind": kind,
        # False = no runner: the rule is INERT however `is_enabled` reads (a
        # retired engine's leftover, or a plugin that failed to load). THE
        # kind-validity predicate — same one create/enqueue validate with, so
        # a creatable kind can never badge as unregistered. API-ready; no UI
        # consumer reads it yet.
        "kind_registered": is_registered(kind),
        "is_enabled": rule.is_enabled,
        "every_seconds": every,
        "trigger": _trigger_of(rule),
        "payload": _payload_of(rule),
        "quiet_hours": json.loads(rule.quiet_hours_json) if rule.quiet_hours_json else None,
        "created_at": _iso(rule.created_at),
        "last_run": None if last is None else {
            "status": last.status,
            "started_at": _iso(last.started_at),
            "completed_at": _iso(last.completed_at),
            "error_text": last.error_text,
            "stats": _safe_json(last.stats_json),
        },
        "next_due_at": next_due,
        "has_pending_job": await _has_pending_job(s, rule.account_id, kind),
    }


# ── Request bodies ────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    account_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    name: str | None = None
    every_seconds: int = 300
    # Rich trigger (clock times / run-limit). When present it wins over
    # `every_seconds`; otherwise we store {"every_seconds": every_seconds}.
    trigger: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    # Opt-in quiet hours: [start, end] creator-local hours. Omit / [0,0] = off (24/7).
    quiet_hours: list[int] | None = None
    is_enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    every_seconds: int | None = None
    trigger: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    quiet_hours: list[int] | None = None   # pass [0,0] to clear, [s,e] to set
    is_enabled: bool | None = None


# ── OFF / DELETE reach the queue ──────────────────────────────────────

async def _cancel_queued(s, ids) -> int:
    """Cancel the still-PENDING jobs these rules queued.

    Switching a rule off used to stop only the NEXT materialization: a job it
    had already queued (a retry in backoff, one waiting out the in-flight lock,
    a drip's follow-on) still ran. Filtered by `rule_id`, never by kind — a
    rule-less one-shot of the same kind (auto_stories' delete-later cleanup,
    an "Unsend this" press) is not this rule's work and must survive. A job
    already `running` is left to finish; the executor won't requeue it.
    Callers own the transaction. Returns the number cancelled."""
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return 0
    res = await s.execute(
        update(ScheduledJob)
        .where(ScheduledJob.rule_id.in_(ids), ScheduledJob.status == "pending")
        .values(status="cancelled", last_error="rule switched off")
    )
    if res.rowcount:
        log.info("automation_rule_jobs_cancelled rules=%s jobs=%s", ids, res.rowcount)
    return res.rowcount or 0


# ── The rule behind a settings tab ────────────────────────────────────

async def ensure_kind_rule(
    s, account_id: str, kind: str, *, enable: bool,
    name: str | None = None, every_seconds: int | None = None,
    trigger: dict[str, Any] | None = None,
    steps: dict[str, Any] | None = None,
    persist_off: bool = False,
) -> str:
    """Find-or-create the account's rule for `kind` and set its switch.

    A settings tab's "Enabled" box writes that engine's CONFIG blob; what makes
    the engine tick is a row in this table, and the two used to be separate
    controls in separate panels — so a fully-configured engine could read
    "Enabled" on its own tab and never run. Every config endpoint that grew a
    fix for that hand-rolled its own find-or-create (four of them say "mirrors
    nudge_config_api._ensure_rule" in the docstring). This is that policy, once,
    in the module that owns the table.

    `enable=False` parks EVERY row of the kind: with two rows, parking one would
    leave the engine sending under a box that reads off. `enable=True` wakes the
    running-or-first row and parks (+ cancels the queue of) any other running
    duplicate, or creates one when the account has none — never a second ticker
    for the same kind.

    `name` / `every_seconds` / `steps` are written when given and left ALONE when
    not. `trigger` (a whole trigger dict, e.g. a `daily_at` clock) wins over
    `every_seconds` when both are given. A caller that owns the schedule (nudge,
    vault-ai) passes it on every save; one whose cadence the operator tunes in the rules editor
    passes nothing and keeps it. A CREATE takes its name and cadence from the
    catalog and its payload from `_CREATE_PAYLOAD` — which is NOT the editor's
    form output, so the two create paths deliberately differ; see that constant.
    An EXISTING row is never re-seeded with any of it.

    Queries `kind_family` — a pre-rename row still carries its retired name, and
    matching only the canonical one would silently create a duplicate beside it.
    Callers own the transaction; nothing here commits.

    `persist_off` (bulk roll-outs): an OFF still writes name / cadence / steps
    into the kept (parked) row — created parked when there is none — so the
    schedule an operator saved survives until the next ON.

    Returns "created" | "updated" | "parked" | "unchanged" (for the log line).
    """
    kind = canonical_kind(kind)
    rules = list((await s.execute(
        select(AutomationRule).where(
            AutomationRule.account_id == str(account_id),
            AutomationRule.kind.in_(kind_family(kind)),
        ).order_by(AutomationRule.id)
    )).scalars())

    if trigger is not None:
        trigger_json = json.dumps(trigger)
    elif every_seconds is not None:
        trigger_json = json.dumps({"every_seconds": int(every_seconds)})
    else:
        trigger_json = None

    meta = _CATALOG.get(kind) or {}

    def _new_row(on: bool) -> AutomationRule:
        return AutomationRule(
            account_id=str(account_id), kind=kind,
            name=(name or meta.get("label") or kind),
            trigger_json=trigger_json or json.dumps({"every_seconds": int(
                meta.get("cadence_default_s") or _FALLBACK_EVERY_S)}),
            steps_json=json.dumps(steps if steps is not None
                                  else _CREATE_PAYLOAD.get(kind, {})),
            is_enabled=on)

    if not enable:
        running = [r for r in rules if r.is_enabled]
        for r in running:
            r.is_enabled = False
        # Every parked row's queue, not just the ones that were running: a row
        # parked earlier can still own a pending Run-now or drip job.
        await _cancel_queued(s, [r.id for r in rules])
        if persist_off:
            if not rules:
                s.add(_new_row(False))
                return "created"
            keep = running[0] if running else rules[0]
            if name:
                keep.name = name
            if trigger_json is not None:
                keep.trigger_json = trigger_json
            if steps is not None:
                keep.steps_json = json.dumps(steps)
        return "parked" if running else "unchanged"

    if not rules:
        s.add(_new_row(True))
        return "created"

    # Keep ONE row on — the running one (lowest id), else the oldest — and park
    # every other running duplicate with its queue: two live rows of one kind
    # are two tickers, and the next OFF would have to find both.
    rule = next((r for r in rules if r.is_enabled), rules[0])
    dupes = [r for r in rules if r is not rule and r.is_enabled]
    for r in dupes:
        r.is_enabled = False
    if dupes:
        await _cancel_queued(s, [r.id for r in dupes])
    changed = not rule.is_enabled or bool(dupes)
    rule.is_enabled = True
    if name and rule.name != name:
        rule.name = name
        changed = True
    if trigger_json is not None:
        changed = changed or rule.trigger_json != trigger_json
        rule.trigger_json = trigger_json
    if steps is not None:
        payload = json.dumps(steps)
        changed = changed or rule.steps_json != payload
        rule.steps_json = payload
    return "updated" if changed else "unchanged"


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/admin/automation-kinds")
async def list_kinds() -> dict[str, Any]:
    """The registered automation kinds + payload hints — drives the editor."""
    return {"kinds": _kind_catalog()}


# Smart Messages' Sent column: the rule kinds it counts, by the
# `messages.automation_kind` each one's sender stamps on its outbound rows.
_SENT_KINDS: dict[str, str] = {
    "send_welcome": "welcome",
    "purchase_followup": "purchase_followup",
    "expiry_message": "expiry_message",
    "expired_message": "expired_message",
    "resubscribe_message": "resubscribe_message",
    "birthday_message": "birthday_message",
}


async def _sent_counts(s, account_ids: list[str]) -> dict[tuple[str, str], int]:
    """{(account, kind): messages it really sent} for the `_SENT_KINDS`: the
    outbound rows each sender writes only after OnlyFans accepted the send,
    read through `ix_messages_automation_kind`. A welcome is a burst of several
    rows, so it counts the fans welcomed; the others send one row per fan."""
    if not account_ids:
        return {}
    to_kind = {v: k for k, v in _SENT_KINDS.items()}
    rows = (await s.execute(
        select(Message.account_id, Message.automation_kind, func.count(),
               func.count(func.distinct(Message.fan_id)))
        .where(Message.account_id.in_(account_ids),
               Message.automation_kind.in_(list(to_kind)))
        .group_by(Message.account_id, Message.automation_kind))).all()
    return {(acc, to_kind[ak]): int(fans if ak == "welcome" else n)
            for acc, ak, n, fans in rows}


@router.get("/admin/automation-rules")
async def list_rules(account_id: str | None = Query(None)) -> dict[str, Any]:
    account_ids = clamp_account_filter(account_id)
    async with get_session() as s:
        q = select(AutomationRule)
        if account_ids is not None:
            q = q.where(AutomationRule.account_id.in_(account_ids))
        q = q.order_by(AutomationRule.kind, AutomationRule.id)
        rules = (await s.execute(q)).scalars().all()
        sent = await _sent_counts(s, sorted({
            r.account_id for r in rules if canonical_kind(r.kind) in _SENT_KINDS}))
        out = []
        for r in rules:
            row = await _serialize(s, r)
            if row["kind"] in _SENT_KINDS:
                row["sent"] = sent.get((r.account_id, row["kind"]), 0)
            out.append(row)
        return {"rules": out}


class KindSwitch(BaseModel):
    account_id: str
    kind: str
    enable: bool


def _refuse_config_route_kind(kind: str, *, turning_off: bool = False) -> None:
    """purchase_followup is owner-only to switch on and restamps `enabled_at` on
    every off→on; only its own config route does both, so these writes refuse it.
    Switching it OFF (and nothing else) stays open here, so the Automations
    panel's toggle still stops it."""
    if canonical_kind(kind) == "purchase_followup" and not turning_off:
        raise HTTPException(409, "purchase_followup is set at /admin/purchase-followup-config")
    # The Smart Messages lifecycle Triggers: the same rule, at their own route.
    from automations.lifecycle_messages import KINDS as _LIFECYCLE
    if canonical_kind(kind) in _LIFECYCLE and not turning_off:
        raise HTTPException(409, f"{kind} is set at /admin/lifecycle-message-config")


@router.post("/admin/automation-rules/switch")
async def switch_kind(body: KindSwitch = Body(...)) -> dict[str, Any]:
    """Turn an automation KIND on or off for an account, in one write.

    The switch a settings tab shows. Its callers do not want to know whether the
    account already has a row, how many, or what cadence a new one gets — and a
    client that DID know parked two rules with two requests, so a failure between
    them left the account half-off. `ensure_kind_rule` is that decision, made once
    and applied inside a single transaction.
    """
    assert_account_owned(body.account_id)
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    await require_opt_in_kind(kind, body.account_id)
    _refuse_config_route_kind(kind, turning_off=not body.enable)
    async with get_session() as s:
        action = await ensure_kind_rule(s, body.account_id, kind, enable=body.enable)
    log.info("automation_kind_switch account=%s kind=%s enable=%s action=%s",
             body.account_id, kind, body.enable, action)
    return {"account_id": body.account_id, "kind": kind,
            "enable": body.enable, "action": action}


@router.post("/admin/automation-rules")
async def create_rule(body: RuleCreate = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    # Canonical at the write boundary: a caller still sending a retired kind
    # name gets the live rule, never a fresh legacy row.
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    # A My Automations kind (auto_posts, mass_premade…) needs its page, opt-in.
    await require_opt_in_kind(kind, body.account_id)
    _refuse_config_route_kind(kind)
    trigger = (_validate_trigger(body.trigger) if body.trigger is not None
               else {"every_seconds": _validate_every(body.every_seconds)})
    payload = _validate_payload_for_kind(kind, body.payload)
    quiet = _validate_quiet_hours(body.quiet_hours)
    name = (body.name or "").strip() or kind

    async with get_session() as s:
        rule = AutomationRule(
            account_id=body.account_id,
            name=name,
            kind=kind,
            trigger_json=json.dumps(trigger),
            steps_json=json.dumps(payload),
            quiet_hours_json=json.dumps(quiet) if quiet else None,
            is_enabled=bool(body.is_enabled),
        )
        s.add(rule)
        await s.flush()
        out = await _serialize(s, rule)
    log.info("automation_rule_created id=%s account=%s kind=%s enabled=%s",
             out["id"], body.account_id, body.kind, body.is_enabled)
    return out


async def _load_owned(s, rule_id: int) -> AutomationRule:
    """The rule, if the session owns its Creator and, for a My Automations
    kind, may use that page (every caller writes or runs it)."""
    rule = await s.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found")
    assert_account_owned(rule.account_id)
    await require_opt_in_kind(canonical_kind(rule.kind), rule.account_id)
    return rule


@router.patch("/admin/automation-rules/{rule_id}")
async def update_rule(rule_id: int, body: RulePatch = Body(...)) -> dict[str, Any]:
    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        _refuse_config_route_kind(rule.kind, turning_off=body.is_enabled is False and all(
            getattr(body, f) is None for f in RulePatch.model_fields if f != "is_enabled"))
        if body.name is not None:
            nm = body.name.strip()
            if not nm:
                raise HTTPException(422, "name cannot be blank")
            rule.name = nm
        if body.trigger is not None:
            rule.trigger_json = json.dumps(_validate_trigger(body.trigger))
        elif body.every_seconds is not None:
            rule.trigger_json = json.dumps({"every_seconds": _validate_every(body.every_seconds)})
        if body.payload is not None:
            rule.steps_json = json.dumps(
                _validate_payload_for_kind(canonical_kind(rule.kind), body.payload))
        if body.quiet_hours is not None:   # [0,0] clears, [s,e] sets
            quiet = _validate_quiet_hours(body.quiet_hours)
            rule.quiet_hours_json = json.dumps(quiet) if quiet else None
        if body.is_enabled is not None:
            rule.is_enabled = bool(body.is_enabled)
            if not rule.is_enabled:
                await _cancel_queued(s, [rule.id])
        await s.flush()
        out = await _serialize(s, rule)
    log.info("automation_rule_updated id=%s enabled=%s", rule_id, out["is_enabled"])
    return out


@router.delete("/admin/automation-rules/{rule_id}")
async def delete_rule(rule_id: int) -> dict[str, Any]:
    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        # Before the delete: the FK nulls `rule_id` on its jobs, after which
        # nothing could tell them apart from a rule-less one-shot.
        await _cancel_queued(s, [rule.id])
        await s.delete(rule)
    log.info("automation_rule_deleted id=%s", rule_id)
    return {"deleted": rule_id}


@router.post("/admin/automation-rules/{rule_id}/run-now")
async def run_now(rule_id: int) -> dict[str, Any]:
    """Enqueue one immediate job for this rule, bypassing the cadence. The
    supervisor is woken right after enqueue so it drains and runs the job
    immediately (~5ms) instead of waiting up to a 30s poll tick. No-op-safe if
    a job is already pending for this (account, kind) — the executor dedups."""
    from automation_executor import enqueue_job, wake_supervisor  # local: avoid load cycle

    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        # Canonical, matching _serialize — a legacy rule must not LIST as the
        # live kind and then answer run-now with the retired token.
        account_id, kind = rule.account_id, canonical_kind(rule.kind)
        payload = _payload_of(rule)

    job_id = await enqueue_job(account_id, kind, payload=payload, rule_id=rule_id)
    wake_supervisor()  # drain NOW (W7 pattern) — don't wait for the 30s poll tick
    log.info("automation_rule_run_now id=%s job=%s account=%s kind=%s",
             rule_id, job_id, account_id, kind)
    return {"enqueued_job_id": job_id, "account_id": account_id, "kind": kind}


class EnqueueBody(BaseModel):
    account_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    payload: dict[str, Any] | None = None
    run_at: datetime | None = None  # default: now (immediate)


@router.post("/admin/automation/enqueue")
async def enqueue_one_shot(
    request: Request, body: EnqueueBody = Body(...)
) -> dict[str, Any]:
    """Fire a single one-shot automation job WITHOUT a persistent rule — the
    trigger seam for action-style kinds the UI launches by hand (auto_posts,
    mass_premade, unsend_messages, the chat ↻ refresh's scrape_chats). For an
    immediate job (no `run_at`) the supervisor is woken right after enqueue so it
    drains and runs in ~5ms instead of waiting up to a 30s poll tick.
    `run_at` schedules it for the future; omitted = immediate."""
    assert_account_owned(body.account_id)
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    await require_opt_in_kind(kind, body.account_id)
    payload = _validate_payload_for_kind(kind, body.payload)
    # Attribute the job to the acting employee when the picker piped a header.
    employee_id: int | None = None
    try:
        raw = request.headers.get("x-employee-id")
        employee_id = int(raw) if raw else None
    except (TypeError, ValueError):
        employee_id = None

    from automation_executor import enqueue_job, wake_supervisor  # local: avoid load cycle
    job_id = await enqueue_job(
        body.account_id, kind,
        payload=payload, run_at=body.run_at,
        created_by_employee_id=employee_id,
    )
    # Drain NOW for immediate jobs (W7 pattern). A wake with only a future-dated
    # job pending is a harmless no-op — the supervisor only claims due jobs.
    if body.run_at is None:
        wake_supervisor()
    log.info("automation_enqueue_one_shot job=%s account=%s kind=%s by_emp=%s",
             job_id, body.account_id, kind, employee_id)
    return {"enqueued_job_id": job_id, "account_id": body.account_id, "kind": kind}
