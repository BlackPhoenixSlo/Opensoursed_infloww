"""service/automation_catalog.py — the automation kind catalog: static metadata
layered over the live registry, which the Automations editor renders and
`automation_rules_api` validates payloads against. Data, `_decorate_knob` (pure)
and `_kind_catalog` (loads the automation plugins, then reads the registry).
`automation_rules_api` re-exports every name here.
"""
from __future__ import annotations

from typing import Any

from automation_registry import load_automation_plugins, registered_kinds
from automations import _customs

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
        "label": "Auto-reply (reply when the team is slow)", "recurring": True, "surface": "rules",
        "cadence_default_s": 180,
        "summary": "Continue the chat with a known low-spend fan when nobody answered his message in time. Never-PPV, no info-gather. Gates (silence window, spend caps, info-complete) live on My Automations → Auto-reply.",
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
