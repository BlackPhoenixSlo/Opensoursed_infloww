"""Composable seeders. One file per entity; each takes the World, a size and a
named RNG stream, writes rows, and returns what later seeders/actors need.

Bulk rows go straight into the run's temp SQLite (same as scripts/demo-shots/seed.py,
fast enough for 50k fans); anything the relay validates goes through its API.
Determinism: World.rng(name) is seeded from (--seed, name), so adding a new
seeder never shifts the numbers an existing one draws.
"""
from __future__ import annotations

import hashlib
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Sizes per --scale. Seeders read the base keys; a flow's scenario reads its own FLOW_SIZES keys.
SCALES: dict[str, dict[str, int | float]] = {
    "small":  {"creators": 3,  "fans_per_creator": 50,   "thread_frac": 0.6, "history_msgs": 4,
               "big_fans_per_creator": 2_000, "fm_walkers_per_creator": 6,
               "paid_captions_per_owner": 4, "of_chats_per_creator": 50,
               "caption_import_rows": 1_000},
    "medium": {"creators": 10, "fans_per_creator": 500,  "thread_frac": 0.5, "history_msgs": 6,
               "big_fans_per_creator": 10_000, "fm_walkers_per_creator": 20,
               "paid_captions_per_owner": 8, "of_chats_per_creator": 150,
               "caption_import_rows": 5_000},
    "huge":   {"creators": 10, "fans_per_creator": 5000, "thread_frac": 0.4, "history_msgs": 6,
               "big_fans_per_creator": 50_000, "fm_walkers_per_creator": 36,
               "paid_captions_per_owner": 8, "of_chats_per_creator": 300,
               "caption_import_rows": 5_000},
}

# A flow's own sizes, key: (small, medium, huge). Read by that scenario; its CLI knob overrides.
# Key prefix rule: slop/README.md "Scales".
FLOW_SIZES: dict[str, tuple[int, int, int]] = {
    # vault-collect / vault-thumbs (the vault week cache)
    "vault_collect_creators": (6, 16, 40), "vault_collect_items": (400, 600, 2_000),
    "vault_thumbs_creators": (3, 6, 10), "vault_thumbs_items": (120, 300, 1_000),
    # vault-download (media per vault: the whole-vault download's size)
    "vault_download_items": (40, 300, 1_000),
    # priority-mass-5k
    "priority_mass_roster_a": (400, 7_000, 7_000),
    # welcome-burst
    "welcome_burst_new": (8, 20, 40), "welcome_burst_welcomed": (4, 8, 12),
    "welcome_burst_established": (4, 8, 12),
    # smart-lists-50k
    "smart_lists_storm_extra": (5, 20, 20), "smart_lists_whale_fans": (20, 100, 500),
    # inbox-unread-fan-burst
    "inbox_unread_per_fan": (3, 5, 10),
    # dm-flood-relay-crash
    "dm_flood_per_fan": (10, 10, 20),
    # shifts-clock-crowd
    "shifts_clock_employees": (50, 200, 400), "shifts_clock_series": (40, 200, 400),
    "shifts_clock_open_n": (3, 10, 20), "shifts_clock_race_rounds": (4, 8, 12),
    "shifts_clock_race_n": (8, 16, 16), "shifts_clock_storm": (4, 4, 4),
    "shifts_clock_readers": (3, 6, 8), "shifts_clock_edits": (8, 16, 16),
    "shifts_clock_cancel_series": (4, 12, 16),
    # vault-pro-20k; huge 20_000 = seed/vault_items.COLLECT_CAP (a literal: importing it is circular)
    "vault_pro_items": (2_000, 20_000, 20_000),
    # s4s-requests-race
    "s4s_requests_agencies": (5, 10, 10), "s4s_requests_creators_per_agency": (3, 5, 8),
    "s4s_requests_blocks": (4, 12, 20), "s4s_requests_race_groups": (16, 80, 150),
    "s4s_requests_racers": (4, 5, 6), "s4s_requests_limit_targets": (4, 12, 20),
    "s4s_requests_bookings": (6, 20, 30), "s4s_requests_burst": (8, 12, 12),
    "s4s_requests_read_rounds": (3, 4, 5),
    # notifications-feed-volume
    "notifications_feed_rows": (1_000, 10_000, 50_000),
    # mass-placeholder-echo
    "mass_placeholder_per_run": (10, 60, 150), "mass_placeholder_stale": (4, 20, 40),
    "mass_placeholder_both": (2, 10, 20), "mass_placeholder_excluded": (2, 2, 2),
    # tracking-links-clicks
    "tracking_links_links": (4, 10, 20), "tracking_links_campaigns": (6, 12, 24),
    "tracking_links_claimed": (30, 150, 1_000), "tracking_links_clicks": (600, 8_000, 30_000),
    # sales-attribution-tips-ppv
    "sales_attribution_episodes": (30, 120, 300),
    # vault-describe-sweep
    "vault_describe_items": (200, 2_000, 20_000),
    # runtime-switches
    "runtime_switches_dm_fans": (5, 20, 40), "runtime_switches_burst_fans": (10, 40, 80),
    # ledger-reports-volume
    "ledger_reports_rows": (10_000, 200_000, 1_000_000), "ledger_reports_runs": (4, 8, 12),
    "ledger_reports_recipients": (40, 300, 1_000),
    # state-reducers
    "state_reducers_unsend_copies": (3, 8, 8),
    # fan-info-sweep: seed/fan_info_history.py fans per Creator (<= the sweep's 200 cap)
    "fan_info_fans": (12, 60, 150),
    # img-chat-media: seed/chat_media.py CDN assets (a photo = thumb + source); small 120: the quiet probe needs
    # >= 20 cacheable tiles (P95_VS_LAST_MIN_N) besides the herd's chats
    "img_chat_assets": (120, 400, 1_200),
    # of-upload-wire: Composer files (all Creators), of them multipart (> 5 MiB); per Creator, a vault
    # import's fresh files and its already-uploaded ones
    "of_upload_files": (12, 400, 1_000), "of_upload_big_files": (2, 6, 12),
    "of_upload_import_files": (3, 5, 8), "of_upload_import_dupes": (1, 2, 3),
    # mass-placeholder-echo's dry-run tail: per Creator, its OF list's fresh / guard fans, the fans on
    # each fence (MASSdmEXCLUDE, AUTOFENCE), the excluded_users of each dry run
    "mass_dry_run_fresh": (6, 20, 40), "mass_dry_run_guard": (3, 10, 20),
    "mass_dry_run_fence": (2, 5, 10), "mass_dry_run_excluded": (2, 3, 4),
    # auto-exclude-25k: the big Creators' pre-made Auto_Exclude (past the 20k backstop, and its guard alone
    # too: 90% of it, so the list stays past 20k once its stale members go), how many big Creators, and the
    # control Creator's list (under it)
    "auto_exclude_members": (24_000, 26_000, 60_000), "auto_exclude_big_creators": (1, 2, 2),
    "auto_exclude_control_members": (400, 1_000, 3_000),
    # os-ping-push: Creators in multi_agency_big_models (5 Agencies), steady-phase frames per Creator
    "os_ping_creators": (10, 20, 20), "os_ping_frames": (12, 24, 40),
    # slow-connections: seed/chat_media.py CDN assets, the picker Creator's OF vault page items
    "slow_conn_chat_assets": (40, 120, 400), "slow_conn_vault_media": (48, 200, 1_000),
    # rich-text-sends: Creators made Fansly accounts (the last ones), formatted-script sends to their fans
    "rich_text_fansly_creators": (1, 3, 3), "rich_text_sends": (100, 2_000, 5_000),
    # scripts-library: an Infloww library's sequences on one Creator, ~17 steps each like the real one (44
    # sequences / 764 scripts, 2026-11-06): medium ≈ 2.3x it (~1.7k scripts), huge ≈ 7x
    "scripts_library_sequences": (24, 100, 300),
    # sweep-pacing: OF's side per Creator: promotions (under the prewarm's 12-page cap), active
    # subscribers (50 a page), ledger rows of the last 6 days
    "sweep_pacing_promos": (350, 1_150, 1_150), "sweep_pacing_subscribers": (500, 2_400, 5_000),
    "sweep_pacing_transactions": (400, 1_000, 2_000),
    # consent-required-notice: media sends through the real send route over every Creator's fans
    "consent_sends": (120, 2_000, 5_000),
    # ws-pump-evict: Creators (each its real WS pump) when one proxy edit evicts every pooled client
    "ws_pump_evict_creators": (5, 50, 50),
}


def merge_sizes(sizes: dict[str, tuple[int, int, int]]) -> None:
    """A flow's sizes (key: (small, medium, huge)) into SCALES; a key already there with another value is an error."""
    per = {s: {k: v[i] for k, v in sizes.items()} for i, s in enumerate(("small", "medium", "huge"))}
    clash = sorted({k for s, d in per.items() for k, v in d.items() if SCALES[s].get(k, v) != v})
    if clash:
        raise SystemExit(f"slop: sizes {clash} already in SCALES with other values")
    for s, d in per.items():
        SCALES[s].update(d)


merge_sizes(FLOW_SIZES)


@dataclass
class World:
    db: Path
    sessions: Path
    seed: int
    scale: str
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    user_id: str | None = None        # the Agency's users.id (seed/agency.py)
    owner: object | None = None       # lib.client.Http signed in as the owner
    data: dict = field(default_factory=dict)  # seeder outputs: creators, fans, threads, ...
    stream: str = ""                  # a fleet shard's id: its own RNG streams (seed/profiles/fleet.py)
    user_prefix: str = "slop"         # usernames seed/agency.py registers

    @property
    def size(self) -> dict[str, int | float]:
        return SCALES[self.scale]

    def rng(self, name: str) -> random.Random:
        key = f"{self.seed}:{self.stream}:{name}" if self.stream else f"{self.seed}:{name}"
        h = hashlib.sha256(key.encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def sql(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db, timeout=30)
        con.execute("PRAGMA foreign_keys=ON")
        return con


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
