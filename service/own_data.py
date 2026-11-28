#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

TABLES = {
    "account_ai_config": ("account_id",
        "account_id persona welcome_rules utc_offset timezone location persona_facts_json model_notes "
        "language voice time_activities_json day_log_json time_images_json welcome_pinned_json "
        "daily_cost_cap_cents model model_by_purpose reasoning_effort nudge_config_json webhook_config_json "
        "full_ai_config_json autoreply_config_json style_config_json audience_mode audience_list_id "
        "audience_auto_add cotag_tag_videos cotag_username split_inbox_json updated_at",
        ""),
    "account_health": ("",
        "",
        "account_id session_dead_at session_dead_reason last_probe_at deactivated_at"),
    "accounts": ("",
        "id nickname color proxy_label is_active_default created_at last_used_at",
        "x_of_rev static_param user_agent"),
    "actions": ("account_id",
        "id employee_id account_id action target_type target_id payload_json at via",
        ""),
    "agency_notifications": ("",
        "",
        "id agency_user_id kind text account_id employee_id data_json dedupe_key created_at read_at "
        "dismissed_at"),
    "agency_copy_gate": ("",
        "",
        "open"),
    "agency_copy_repair": ("",
        "",
        "pending"),
    "agency_copy_sections": ("",
        "",
        "name sha256"),
    "agency_copy_missing_owners": ("",
        "",
        "user_id since"),
    "agency_copy_version": ("",
        "",
        "epoch version grant_gen"),
    "ai_decisions": ("account_id",
        "id account_id fan_id mode trigger_kind trigger_key parent_id anchor_message_id anchor_created_at arm "
        "salt_ver route heat route_row question_version router_model writer_model jev_json jev_ms jev_error "
        "status created_at updated_at reply_json offer_price_cents offer_list_cents offer_media_json "
        "offer_item_ref offer_message_id outcome outcome_at join_src offer_attempt_at",
        ""),
    "alembic_version": ("",
        "",
        "version_num"),
    "app_errors": ("",
        "",
        "id occurred_at source kind message stack url account_id employee_id user_agent context_json"),
    "assistant_turns": ("",
        "",
        "id ts user_id chatter_id account_id thread_id role question answer error model provider "
        "cost_millicents latency_ms"),
    "automation_rules": ("account_id",
        "id account_id name kind trigger_json steps_json is_enabled quiet_hours_json frequency_caps_json "
        "created_at",
        ""),
    "automation_runs": ("account_id",
        "id account_id kind started_at completed_at status stats_json error_text",
        ""),
    "autoreply_state": ("account_id",
        "account_id fan_id spell_inbound_at nudges_sent last_nudge_at updated_at",
        ""),
    "bio_custom_domains": ("",
        "id profile_id domain status token checked",
        ""),
    "bio_daily": ("",
        "day profile_id link_id country in_app code views clicks",
        ""),
    "bio_links": ("",
        "id profile_id link_id title destination default_tracking_code mode icon background_image v1_key geo "
        "is_adult tracking sort_order bot_check created_at updated_at",
        ""),
    "bio_profiles": ("",
        "id owner_user_id account_id username display_name bio avatar background_image mode v1_key verified "
        "slot created_at updated_at",
        ""),
    "bio_spare_domains": ("",
        "id domain",
        ""),
    "blacklist": ("",
        "fan_id reason added_at",
        ""),
    "catalog_items": ("account_id",
        "id account_id script_id position kind label description_for_ai media_ids preview_media_ids "
        "duration_sec band_lo band_hi price_cents tip_unlock_cents is_free_teaser tags enabled created_at "
        "updated_at",
        ""),
    "chats": ("account_id",
        "hidden_locally",
        "account_id fan_id last_message_id last_message_at last_message_preview unread_count is_pinned "
        "is_priority list_ids preview_updated_at"),
    "chatter_account_access": ("",
        "chatter_id user_id account_id created_at",
        ""),
    "chatter_folder_access": ("",
        "chatter_id account_id folder_id folder_name created_at",
        ""),
    "chatter_users": ("",
        "chatter_id user_id created_at",
        ""),
    "chatters": ("",
        "id username password display_name color is_active created_at last_seen_at sessions_valid_after "
        "totp_secret totp_enabled_at totp_recovery totp_last_step",
        ""),
    "chatters_invites": ("",
        "token user_id created_at expires_at used_at used_by_chatter_id setup_json",
        ""),
    "clock_events": ("",
        "id agency_user_id employee_id account_id shift_id in_utc out_utc close_reason last_seen_utc",
        ""),
    "cell_meta": ("",
        "",
        "data_gen copy_epoch copy_version section_sha applied_at confirmed_at grant_gen last_data_gen "
        "reconcile_since restored_at peek_until gap_confirmed_by gap_confirmed_at"),
    "cell_holds": ("",
        "",
        "id scope platform account why blocks op set_by set_at released_by released_at"),
    "creator_handoff_ops": ("", "", "op batch"),
    "creator_reservations": ("",
        "",
        "account_id platform cell state expires_at handoff_op handoff_batch"),
    "content_offers": ("account_id",
        "id account_id fan_id item_id script_id mode price_cents tip_unlock_cents offer_message_id status "
        "resolved_by tips_accum_cents delivery_message_id offered_at resolved_at updated_at",
        ""),
    "data_migrations": ("",
        "",
        "name applied_at"),
    "employee_account_access": ("",
        "employee_id account_id",
        ""),
    "employee_groups": ("",
        "id agency_user_id parent_id name created_at",
        ""),
    "employee_floor": ("",
        "",
        "pending"),
    "employee_floor_reports": ("",
        "",
        "cell epoch max_emp reported_at"),
    "employees": ("",
        "id display_name color is_active created_at user_id chatter_id group_id",
        ""),
    "event_inbox": ("",
        "",
        "id account_id source provider_event_id event_type payload_json received_at processed_at "
        "processed_status processed_error"),
    "fan_lease": ("account_id",
        "account_id fan_id automation_kind leased_until acquired_at",
        ""),
    "fan_media_syncs": ("",
        "",
        "account_id fan_id synced_at last_attempt_at pages complete"),
    "fan_profiles": ("account_id",
        "account_id fan_id original_name message_count_at_gen total_spend_at_gen_cents nickname short_bio "
        "bullet_points q1 q2 q3 tease1 tease2 tease3 applied_notes notes_applied_successfully last_applied_at "
        "last_applied_nickname last_applied_notes last_generated_at generated_by_grok_call_id",
        ""),
    "fans": ("account_id",
        "custom_nickname generated_nickname fan_chosen_nickname real_name is_name_real his_age birthday "
        "salary salary_frequency last_pay_date home_country home_city hobbies fetishes recent_events "
        "recent_events_timeline self_description description likes_boobs likes_ass timezone language "
        "language_source occupation employer relationship_status partner_name has_kids family_names pets "
        "mood_at_last_message sentiment_trend relationship_stage communication_style automation_paused_until "
        "questions_asked persona_claims_json persona_age_claimed persona_location_claimed persona_job_claimed "
        "grok_facts_updated_at notes applied_notes applied_notes_at customs_owed_at customs_cleared_at "
        "gather_close_at gather_close_sending_at tags custom_fields is_bot turn_counter follow_examined_at deep_convo_state "
        "deep_convo_skip_level deep_convo_skip_remaining deep_convo_updated_at deep_convo_q_text "
        "deep_convo_tease_text",
        "account_id fan_id of_username of_display_name avatar_url profile_last_synced_at lifetime_spend_cents "
        "total_likes last_message_received_at last_message_sent_at last_online_at subscribed_at "
        "subscription_expires_at subscription_status is_followed "
        "is_muted joined_date source raw_json created_at updated_at"),
    "follow_log": ("account_id",
        "id account_id fan_id followed_at",
        ""),
    "follow_ping_state": ("account_id",
        "account_id fan_id last_pinged_at ping_count",
        ""),
    "followup_state": ("account_id",
        "account_id fan_id phase cycle silence_started_at fan_last_reply_at cooldown_until messages_sent "
        "completed stopped_at sending_at sending_ctx unconfirmed_at updated_at",
        ""),
    "funnel_account_media": ("account_id",
        "funnel_id account_id opening_media_ids steps_media_json created_at updated_at",
        ""),
    "funnel_responders": ("account_id",
        "account_id funnel_id fan_id mass_run_id first_replied_at",
        ""),
    "funnel_state": ("mass_run_id>mass_runs.id",
        "mass_run_id fan_id current_step next_check_at check_count status last_error last_ppv_sent_at hops "
        "last_sent_step confirmed_sent_at sending_at sending_ctx unconfirmed_at updated_at",
        ""),
    "grok_calls": ("",
        "",
        "id purpose account_id fan_id model endpoint temperature prompt_id prompt_json response_json "
        "response_text latency_ms tokens_in tokens_out cost_cents provider cache_hit_tokens status "
        "was_dry_run error_text called_at"),
    "grok_daily_cost": ("",
        "",
        "day account_id provider cost_cents call_count is_capped updated_at"),
    "grok_user_daily_cost": ("",
        "",
        "day user_id provider cost_cents call_count is_capped updated_at"),
    "leak_tracker_tenant": ("",
        "agency_user_id tenant_id bound_at",
        ""),
    "leak_watch": ("",
        "id agency_user_id account_id watch_id on platform username verified display_name aliases_json instagram x "
        "consent_at consent_by synced_at synced_paused offer_snoozed_until created_at updated_at",
        ""),
    "leak_watch_tombstone": ("",
        "watch_id agency_user_id account_id tenant_id requested_at attempts last_error created_at",
        ""),
    "lifecycle_message_claims": ("account_id",
        "account_id kind fan_id event_key created_at message_idx",
        ""),
    "link_claimers": ("",
        "",
        "id account_id kind of_id fan_id name username subscribe_at first_seen_at lifetime_total_cents "
        "lifetime_subs_cents lifetime_posts_cents lifetime_messages_cents lifetime_streams_cents "
        "lifetime_tips_cents"),
    "link_meta": ("account_id",
        "id account_id kind of_id promo_cost_cents source tags_json campaign_id list_id list_name updated_at",
        "claim_count walked_at checked_at list_added_count"),
    "link_shares": ("account_id",
        "id secret account_id kind name of_ids_json include_earnings rows_json snapshot_at created_by "
        "created_at expires_at revoked_at",
        ""),
    "list_members": ("list_id>lists.id",
        "added_by_employee_id",
        "list_id fan_id added_at"),
    "lists": ("account_id",
        "id account_id of_list_id name kind query_json is_system synced_at sync_meta_json created_at",
        ""),
    "mass_broadcast_cache": ("",
        "",
        "account_id queue_id sent_at body_text raw_text giphy_id is_free is_tip media_count media_json "
        "previews_json sent_count viewed_count is_canceled can_unsend unsend_seconds template fetched_at"),
    "mass_message_funnels": ("",
        "id name description opening_message vault_folder media_indices opening_vault_folder "
        "opening_media_indices steps_json created_at updated_at",
        ""),
    "mass_runs": ("account_id",
        "id account_id funnel_id started_by_employee_id audience_filter recipient_count queue_id "
        "automation_kind started_at completed_at status discovery_closed_at body sent_at unsent_at "
        "recipients_json crawl_outcome",
        ""),
    "message_media": ("",
        "",
        "account_id fan_id message_id media_id type width height thumb_url source_url duration_ms ingested_at "
        "updated_at"),
    "messages": ("account_id",
        "unsent_by_employee_id unsent_reason is_promise promise_due_date sent_by_employee_id mass_run_id "
        "funnel_step automation_kind image_desc",
        "account_id fan_id message_id direction sender_name body media_ids media_count price_cents is_paid "
        "is_tip purchased_at is_unsent unsent_at temp_id raw_json created_at ingested_at"),
    "nudge_state": ("account_id",
        "account_id fan_id last_seen_online_at last_nudged_at nudge_count no_reply_streak pending_job_id "
        "last_variation_idx last_slot updated_at",
        ""),
    "of_consent_accepts": ("account_id",
        "id account_id enabled user_id username employee_id at",
        ""),
    "of_earnings_daily": ("",
        "",
        "account_id day category net_cents gross_cents sales fetched_at"),
    "of_stats_daily": ("",
        "",
        "account_id day visitors new_subs renewals active_fans renew_on fetched_at attempts attempted_at"),
    "owner_tokens": ("",
        "id user_id name token_sha256 hint created_at expires_at last_used_at revoked_at",
        ""),
    "perf_events": ("",
        "",
        "id tab_id parent_tab_id op_id kind phase client_ts_ms received_at employee_id account_id meta_json"),
    "posts": ("account_id",
        "id account_id temp_id status text price_cents media_ids label_ids scheduled_for failed_reason "
        "excluded_list_ids created_by_employee_id created_at",
        "of_post_id posted_at raw_json updated_at"),
    "priority_mass_recipients": ("run_id>priority_mass_runs.id",
        "run_id fan_id status reason message_id updated_at",
        ""),
    "priority_mass_runs": ("account_id",
        "id account_id created_by_employee_id status text media_json previews_json price_cents locked_text "
        "audience_json resolved_count excluded_count capped_count last_error created_at completed_at",
        ""),
    "promo_campaigns": ("account_id",
        "id account_id of_promo_id name discount_percent price_cents subscribe_counts subscribe_days message "
        "promo_type status subscriber_count auto_reactivate reactivate_count last_reactivated_at finish_days "
        "expires_at recreates_left keep_host_id keep_warning keep_warning_at keep_ticked_at preempt "
        "created_at",
        ""),
    "promo_create_reservations": ("account_id",
        "id account_id campaign_id source state terms_json pre_ids_json replaced_of_promo_id claims_seen "
        "first_claims host_id of_promo_id listed_at error_class retry_after_s not_before reconcile_reads "
        "created_at sent_at settled_at",
        ""),
    "promo_keep_state": ("account_id",
        "account_id kept_of_promo_id first_claims last_claims seen_below finished_at read_at recheck_at "
        "recheck_job_id skew_s wait_reason",
        ""),
    "promo_list_settings": ("account_id",
        "account_id enabled list_id list_name updated_at",
        ""),
    "proxies": ("",
        "label scheme host port username password_encrypted notes assigned_account_id",
        "verified_ip verified_at"),
    "purchase_followup_claims": ("account_id",
        "account_id fan_id purchased_message_id silent created_at",
        ""),
    "purchase_notices": ("account_id",
        "account_id fan_id message_id notified_at",
        ""),
    "push_sent": ("",
        "",
        "sub_id tag sent_at"),
    "push_subscriptions": ("",
        "id endpoint p256dh auth principal_kind principal_id issued_ms types platforms created_at updated_at",
        ""),
    "reconcile_peeks": ("", "", "platform account target data_gen peeked_at unmatched"),
    "runtime_switches": ("",
        "name value_json updated_by updated_at",
        ""),
    "s4s_blocks": ("account_id",
        "id agency_user_id account_id projection_json created_at",
        ""),
    "s4s_media": ("account_id",
        "id account_id post_id vault_media_id media_type file_name size_bytes created_at",
        ""),
    "s4s_posts": ("account_id",
        "id account_id caption is_primary created_at updated_at",
        ""),
    "s4s_profiles": ("account_id",
        "id account_id opted_in discovery_visible daily_limit display_name username avatar_url created_at "
        "updated_at",
        ""),
    "s4s_requests": ("from_account_id+to_account_id",
        "id from_account_id to_account_id slot_at from_caption to_caption from_projection_json "
        "to_projection_json from_media_json to_media_json status cancel_reason created_at answered_at",
        ""),
    "s4s_schedule": ("post_id>posts.id",
        "id request_id poster_account_id partner_account_id text slot_at status reason job_id post_id "
        "of_post_id posted_at remove_at",
        ""),
    "saved_replies": ("account_id",
        "id account_id title text price_cents locked_text media_json tagged_users_json previews_json gif_id "
        "gif_url script_id script_step tags_json notes conditional sent_count created_at updated_at",
        ""),
    "saved_reply_sequences": ("account_id",
        "id account_id name position created_by description created_at updated_at",
        ""),
    "scheduled_jobs": ("account_id",
        "id account_id kind payload_json run_at status attempts last_error rule_id created_by_employee_id "
        "created_at",
        ""),
    "scrape_history": ("",
        "",
        "account_id fan_id last_message_id last_message_text last_scrape_at history_deferred_at gap_after_id "
        "gap_before_id"),
    "send_ops": ("",
        "",
        "account op_id kind target digest epoch data_gen state upstream_id result attempts created_at updated_at "
        "resolved_by resolved_at"),
    "sensitive_words": ("",
        "id agency_user_id word word_key created_at",
        ""),
    "sessions": ("",
        "",
        "id account_id captured_at cookies_json x_of_rev signing_rules_json is_latest"),
    "settings_versions": ("",
        "id user_id tab effective_from config_json created_at",
        ""),
    "shift_assignments": ("",
        "shift_id employee_id account_id",
        ""),
    "shifts": ("",
        "id agency_user_id start_utc end_utc tz repeat_days repeat_until cancelled_dates status created_by "
        "created_at updated_at cancelled_at",
        ""),
    "skip_list": ("account_id",
        "account_id fan_id reason added_at",
        ""),
    "smart_lists": ("account_id",
        "id account_id name rules_json created_at updated_at of_list_id of_list_name is_active",
        "sync_state sync_error synced_at member_count"),
    "subscriber_crawl": ("", "", "account_id crawled_at"),
    "subscriber_snapshot": ("",
        "",
        "account_id fan_id subscribe_at expired_at renew_on seen_at resubscribed_at"),
    "tracking_clicks": ("tracking_link_id>tracking_links.id",
        "id tracking_link_id clicked_at referer user_agent ip country in_app ref verified",
        ""),
    "tracking_links": ("account_id",
        "id account_id name slug target_url click_count bot_check created_at",
        ""),
    "transaction_scan_history": ("",
        "",
        "account_id last_scan_at last_marker oldest_seen_occurred_at newest_seen_occurred_at fully_backfilled "
        "backfill_floor current_status last_error consecutive_failures paused_until last_full_at "
        "backfill_stalls full_walk_failures rows_inserted_total rows_patched_total updated_at"),
    "transactions": ("account_id",
        "attributed_employee_id credit_employee_id credit_rule credit_automation_kind credit_sender_id "
        "credit_converter_id credit_converter_at",
        "id account_id fan_id kind message_id amount_cents currency occurred_at raw_json ingested_at "
        "provider_transaction_id status cleared_at payout_pending_days net_cents fee_cents vat_cents "
        "description source"),
    "translation_cache": ("",
        "",
        "text_hash target src_lang source_text translated created_at"),
    "trial_link_mirrors": ("",
        "",
        "id account_id of_trial_id name subscribe_days subscribe_counts url claim_counts created_at"),
    "tx_daily": ("",
        "",
        "account_id day kind status linked employee_id rule automation_kind gross_cents net_cents net_missing "
        "net_or_80_cents sales fee_cents vat_cents"),
    "tx_hourly": ("",
        "",
        "account_id hour kind status linked employee_id rule automation_kind gross_cents net_cents "
        "net_missing net_or_80_cents sales fee_cents vat_cents"),
    "ultra_plans": ("",
        "id owner_user_id source plan_json plan_sha256 status step_states created_at approved_at finished_at",
        ""),
    "user_accounts": ("",
        "user_id account_id created_at",
        ""),
    "user_llm_keys": ("",
        "user_id provider api_key updated_at",
        ""),
    "user_settings": ("",
        "user_id tab config_json updated_at",
        ""),
    "users": ("",
        "id username password created_at last_seen_at is_admin sessions_valid_after totp_secret "
        "totp_enabled_at totp_recovery totp_last_step",
        ""),
    "vault_account_settings": ("account_id",
        "account_id folder_price_final standard_folders solo_sequences updated_at",
        ""),
    "vault_cache_runs": ("",
        "",
        "id account_id status phase total_seen upserted pages_done error started_at finished_at"),
    "vault_folder_items": ("account_id",
        "account_id folder_id media_id manual_order added_at",
        ""),
    "vault_folder_prices": ("account_id",
        "account_id folder_ref price_cents updated_at",
        ""),
    "vault_folders": ("account_id",
        "id account_id name of_list_id created_by deleted_at created_at",
        ""),
    "vault_items": ("account_id",
        "folder_id description suggested_price_cents default_price_cents tags notes manual_order "
        "video_description explicitness_tier story_suitable story_score tip_vault_flag tip_vault_score "
        "suggested_caption suggested_script describe_status describe_generated_at describe_model "
        "describe_call_id frames_sampled ai_fields_json operator_overrides_json locked_fields_json "
        "review_state reviewed_at reviewed_by",
        "account_id media_id kind duration_seconds width height thumb_url full_url send_count last_sent_at "
        "raw_json created_at search_text of_terms of_folder_ids content_hash content_hash_kind updated_at_of "
        "last_seen_run_id removed_at updated_at"),
    "vault_of_query_log": ("",
        "",
        "account_id query match_count fetched_at"),
    "vault_response_cache": ("",
        "",
        "account_id query_key response_json fetched_at"),
    "vault_sends": ("account_id",
        "id account_id fan_id media_id message_id price_cents sent_at was_purchased",
        ""),
    "wall_media": ("",
        "",
        "account_id media_id post_id post_published_at price_cents first_seen_at"),
    "wall_scan_state": ("",
        "",
        "account_id newest_post_published_at oldest_post_published_at fully_backfilled last_scan_at "
        "scanned_posts_total"),
    "welcome_sent": ("account_id",
        "account_id fan_id fan_username sent_at",
        ""),
}

_PARENT_ACCOUNT = "account_id"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _live_tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND substr(name, 1, 7) != 'sqlite_' ORDER BY name")]


def _columns(con: sqlite3.Connection, table: str) -> list[tuple[str, int]]:
    return [(r[1], r[5]) for r in con.execute(f"PRAGMA table_info({_q(table)})")]


def unclassified(con: sqlite3.Connection) -> list[str]:
    out = []
    for table in _live_tables(con):
        spec = TABLES.get(table)
        if spec is None:
            out.append(table)
            continue
        known = set(spec[1].split()) | set(spec[2].split())
        out += [f"{table}.{c}" for c, _ in _columns(con, table) if c not in known]
    return out


def _bare(account: str) -> str:
    return account.partition(":")[2] if ":" in account else account


def _enc(v):
    return {"hex": v.hex()} if isinstance(v, (bytes, bytearray, memoryview)) else v


def _line(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_enc).encode() + b"\n"


def _table_query(con, table, link, own, live, bare):
    cols = _columns(con, table)
    names = {c for c, _ in cols}
    pk = [c for c, k in sorted((x for x in cols if x[1]), key=lambda x: x[1])]
    key = pk or ["rowid"]
    values = [c for c in own.split() if c in names and c not in pk]
    join = ""
    if "+" in link:
        accts = link.split("+")
        if not set(accts) <= names:
            return None
        exprs = [f"t.{_q(a)}" for a in accts]
    elif ">" in link:
        fk, _, target = link.partition(">")
        parent, _, ppk = target.partition(".")
        if fk not in names or parent not in live or _PARENT_ACCOUNT not in {c for c, _ in _columns(con, parent)}:
            return None
        exprs = [f"p.{_q(_PARENT_ACCOUNT)}"]
        join = f" LEFT JOIN {_q(parent)} p ON p.{_q(ppk)} = t.{_q(fk)}"
    else:
        if link not in names:
            return None
        exprs = [f"t.{_q(link)}"]
    where, args = "", []
    if bare is not None:
        marks = ",".join("?" * len(bare))
        where = " WHERE " + " OR ".join(f"{e} IN ({marks})" for e in exprs)
        args = sorted(bare) * len(exprs)
    sel = ", ".join(exprs + [f"t.{_q(c)}" for c in key + values])
    order = ", ".join(f"t.{_q(c)}" for c in key)
    sql = f"SELECT {sel} FROM {_q(table)} t{join}{where} ORDER BY {order}"
    return sql, args, len(exprs), len(key), [table, key, values]


def _account_key(aid: str, session_accounts: Path | None) -> str:
    platform = None
    if session_accounts is not None and Path(aid).name == aid and aid not in (".", ".."):
        try:
            meta = json.loads((session_accounts / aid / "meta.json").read_text())
            platform = meta.get("platform") if isinstance(meta, dict) else None
        except (OSError, ValueError):
            pass
    return f"{platform if isinstance(platform, str) and platform else '?'}:{aid}"


def checksums(db_path, accounts=None, *, session_accounts: Path | None = None) -> dict[str, str]:
    db_path = Path(db_path).resolve()
    asked = None if accounts is None else {str(a): _bare(str(a)) for a in accounts}
    bare = None if asked is None else set(asked.values())
    con = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    sums: dict[str, list] = {}
    try:
        con.execute("BEGIN")
        live = set(_live_tables(con))
        if bare is None and "accounts" in live:
            for (aid,) in con.execute("SELECT id FROM accounts"):
                if aid is not None:
                    sums.setdefault(str(aid), [hashlib.sha256(), None])
        for table in sorted(TABLES):
            link, own, _ = TABLES[table]
            if not link or not own or table not in live:
                continue
            q = _table_query(con, table, link, own, live, bare)
            if q is None:
                continue
            sql, args, n_acct, n_key, header = q
            for row in con.execute(sql, args):
                payload = None
                for aid in dict.fromkeys(str(a) for a in row[:n_acct] if a is not None):
                    if bare is not None and aid not in bare:
                        continue
                    s = sums.setdefault(aid, [hashlib.sha256(), None])
                    if s[1] != table:
                        s[0].update(_line(header))
                        s[1] = table
                    payload = payload or _line([list(row[n_acct:n_acct + n_key]), list(row[n_acct + n_key:])])
                    s[0].update(payload)
        con.execute("ROLLBACK")
    finally:
        con.close()
    empty = hashlib.sha256().hexdigest()
    if asked is None:
        return {_account_key(a, session_accounts): sums[a][0].hexdigest() for a in sorted(sums)}
    return {a: sums[b][0].hexdigest() if b in sums else empty for a, b in asked.items()}


def checksum(db_path, account: str) -> str:
    return checksums(db_path, [account])[str(account)]


def main(argv: list[str]) -> int:
    if argv and argv[0] == "checksum":
        parser = argparse.ArgumentParser(prog="own_data.py checksum")
        parser.add_argument("db")
        parser.add_argument("accounts", nargs="*")
        parser.add_argument("--sessions", type=Path)
        args = parser.parse_intermixed_args(argv[1:])
        print(json.dumps(checksums(args.db, args.accounts or None, session_accounts=args.sessions), sort_keys=True))
        return 0
    if len(argv) == 2 and argv[0] == "unclassified":
        con = sqlite3.connect(Path(argv[1]).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            missing = unclassified(con)
        finally:
            con.close()
        for name in missing:
            print(name)
        return 1 if missing else 0
    print("usage: own_data.py checksum <db> [--sessions <dir>] [account ...] | unclassified <db>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
