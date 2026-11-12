# slop/: Vault Pro

Vault Pro's mirror reads, duplicate review and hide on a big vault (`/admin/vault-ai/*`), its AI describe sweep
(`service/vault_ai_vision.py` `describe-all`, then `flags-all`) and Add media's import pick list, in the slop harness. The harness, its knobs and its
rules are in `README.md`; this file is only what this flow adds. Each scenario's docstring is its spec (load,
oracles, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/vault_items.py` | `seed(w, creators, n)` (`n`: {account_id: items}): `vault_items` rows by SQL as Collect sweeps leave them, then the passes on top (thumb hash, describe, flags, operator grades, OF's search harvest, sends, earlier hides), two finished `vault_cache_runs` per Creator, 6 OF folders (`listStates`) and 3 AI folders. About a fifth of the hashed media are planted re-upload groups of 2 to 5 (exact bytes or 0-7 bits off, at most one video decoy edit per group) and a few flagged rows planted review suspects. `COLLECT_CAP` (20,000) is the most one Collect sweep mirrors. Returns per Creator `of_folders`, `folders`, `copies` (planted distances), `iffy`. |
| `lib/vault_pro_relay.py` | OnlyFans' `PUT /vault/media/hidden` (`OFClient.hide_vault_media`), only when the run wrote `of-vault-pro.json`: records each call's ids in order, answers success; `GET /__slop/vault-pro/fake` (`FAKE_PATH`) answers them. |
| `lib/vault_pro_faults.py` | Every correctness check of vault-pro-20k and its faults (below). |
| `seed/vault_items_describe.py` | In two steps around the relay arm: `plan(w, creators, n)` (per Creator its share of `n` photos, clips of 6 / 9 / 12 frames and a few audio files; 15% described by an earlier sweep, of the rest a deterministic refuse set and blank set, each at least one per Creator), then `seed(w, items, armed)` (the `vault_items` rows, a cached row with its `grok_calls` row, and the stills `vault_frames.collect` reads, plus a 300px grid stand-in; each item's picture its own pixel size). |
| `lib/vault_describe_relay.py` | DeepInfra's OpenAI-compatible wire on its own loopback port, inert until the run wrote `deepinfra.json` and armed it (`arm_run`, `POST /__slop/vault-describe/arm`; 409 under `SLOP_LIVE=1`): answers describe prompts by each item's outcome (ok; refuse: 30b refuses, 235b answers; blank: both ""), flags prompts with flags JSON plus a hostile description / tags, the Jev-fed describe prompts (`recipe` v6: the ok JSON; prose: the marker plus every lane-critical claim, `PROSE_CLAIMS`, and `PROSE_GARMENTS`), bills each answer at `llm_models.MODELS`' listed price; re-points the still stores into the run's temp dir. `GET /__slop/vault-describe/calls`, `/count`. |
| `lib/vault_describe_faults.py` | The describe sweep's check names and its faults (below). |
| `lib/vault_jev_relay.py` | TypeSafe's System One wire for the vault Jev v8 pass (`service/vault_jev.py`), as a `lib/typesafe_relay.py` `HANDLERS` entry (claims only the SDK's multipart body, once the run wrote `typesafe-vault.json` and armed it, `arm_jev`, `POST /__slop/vault-jev/arm`; 409 under `SLOP_LIVE=1`): answers each photo by its profile (`PROFILES`) and the question set (pass 1 / 2 / L), bills `TOKENS[pass] + id % 89` input tokens. `GET /__slop/vault-jev/calls`, `/count`. |
| `lib/vault_jev_faults.py` | The Jev scenario's check names and faults (below). |
| `scenarios/2026-11-11-vault-jev-flags.py` | The Jev v8 pass in describe-all / flags-all, per-Creator opt-in, and the Jev-fed describe recipes it routes to. |
| `lib/vault_relay.py` | OnlyFans' side of a vault import (upload claim, carrier post, `GET /__slop/vault/fake`), for `2026-10-30-vault-import-reducer` (below), and of a folder publish (create list, add media, list read-back; `made`) for `2026-11-11-vault-tag-chips`. |
| `lib/vault_faults.py` | That import's check names and its client fault `import-sends-unselected`. |
| `lib/vault_import_faults.py` | That import's relay-side fault (below; its check name from `lib/vault_faults.py`). |
| `lib/picker_faults.py` | That scenario's restricted-chatter phase: check `RESTRICTED_MENU` and client fault `picker-ignores-folder-access` (the picker's restricted branch off). |
| `lib/picker_ts.mjs` | The same phase in node (`lib/app_ts.py`): `vaultPickerFolders.folderSelectItems` on the chatter's folder access and vault lists. |
| `scenarios/2026-11-01-vault-pro-20k.py` | Vault Pro at 20k; its `_oracle` (what `GET /duplicates` must answer at a strictness, from the planted copies). |
| `scenarios/2026-11-01-vault-describe-sweep.py` | The describe sweep. |
| `scenarios/2026-10-30-vault-import-reducer.py` | Add media's pick list and the restricted chatter's picker. |
| `lib/vault_wire.py` | OnlyFans' vault at its wire for the vault flows (week cache, Refresh): `VaultWire(fake, seed, items, sizes=)` joins `of_wire.FakeOF.extra_routes`; per Creator (made on first sight of its User-ID) `items` media in 6 folders; `/vault/lists`, `/vault/media` (list / type / sort / offset / limit), `/vault/media/{id}` (re-signed); urls signed by `seed/chat_media.sign`; `assets()` for `img_relay.arm_run`, `rotate()`, `add(uid, name, k)` (a folder + k media made on OF now); records `fake.vault_calls`. |
| `lib/vault_collect_relay.py` | With RELAY_ENV `SLOP_VAULT_STILLS=1`: vault_stills / storyboard dirs into `$DEMO_SHOTS_TMP/vault-stills/`, the collector's periodic started (test mode skips `_start_event_pumps`). |
| `lib/vault_collect_faults.py` | The week-cache flows' check names and faults (below). |
| `seed/vault_week.py` | `mirror(w, wire, uids)`: vault_items + one `auto:done` run; `hot_paused(w, wire, uids, *, at, exp)`: the collector's partial hot-set mirror, with All page 0 / prefetch and every folder page 0 cached; `set_urls` expires or re-signs stored urls. |
| `seed/vault_cache.py` | `LISTS_KEY`, `PICKER_KEY`, `media_key`, product-shaped cache rows and folder grants. |
| `lib/vault_ui.py` | Shared picker / Vault Pro navigation, proxy binding, CDN counts, and browser error capture. |
| `seed/profiles/flat_agency.py` | One Agency, N Creators (`w.data["flat_creators"]`), each with an OF session right away. |
| `scenarios/2026-11-05-vault-collect.py` | The background collector under load. |
| `scenarios/2026-11-05-vault-thumbs.py` | Durable picker thumbs. |
| `lib/vault_refresh_faults.py` | Vault Refresh's check names and faults (below). |
| `scenarios/2026-11-05-vault-refresh.py` | Vault Pro's Refresh and the picker's broken-thumb reload. |
| `scenarios/2026-11-10-nudge-day-images.py`, `lib/nudge_day_faults.py` | Nudge online's day picker, vault-only slot images and Share to models, its check names and faults (below). |
| `lib/vault_download_faults.py` | Vault Pro download's check names and its fault (below). |
| `scenarios/2026-11-08-vault-download.py` | Download selected / folder / whole vault, direct vs relay; its `Disk` (the picker stub's far side). |
| `lib/vault_manual_collect_faults.py` | Manual Collect's check names and faults (below). |
| `scenarios/2026-11-10-vault-manual-collect.py` | Manual Collect (POST /admin/vault-ai/collect) under picker load. |
| `seed/vault_flags_partial.py` | A described vault the flags pass reached only part of (planted $10 / $50 / unflagged classes). |
| `lib/vault_ai_folders_faults.py` | Build AI folders' check names and faults (below). |
| `scenarios/2026-11-10-vault-ai-folders-partial-flags.py` | Build AI folders on a partly flagged vault. |
| `seed/vault_feet.py` | A described, flagged vault for the feet pack picker (planted keeper / bystander / mention / ambiguous / measured classes, some keepers pre-filed). |
| `lib/vault_feet_picker_faults.py` | The feet pack picker's check names and faults (below). |
| `scenarios/2026-11-11-vault-feet-picker.py` | Feet pack picker: ranked, prefilled, keyboard, phone. |
| `seed/vault_tag_chips.py` | A tagged vault: feet / lace planted across the column, ai tags and primary_folder, plus decoys, removed and malformed rows; the AND match and facet oracle. |
| `lib/vault_tag_chips_faults.py` | The tag chips' check names and fault (below). |
| `scenarios/2026-11-11-vault-tag-chips.py` | The grid's tag chips and Save as folder. |

## Scenarios

- `2026-11-10-nudge-day-images`: Nudge online's per-day editor and Share to models (`NudgeSlotPools`,
  `nudgeDayBuckets`, `NudgeOnlineTab` `share`; PUT `/admin/nudge-config/bulk` `_with_own_images`) on the real UI and
  relay (one owner, 1440x900, `agency_inbox`). By SQL: Creator 0's `nudge_config_json` and a complete vault mirror
  (3 `vault_items` + one finished manual walk, so the picker lists `/admin/vault-ai/items`, no OF read); Creator 1
  its own config (other lines and delay, image 9101); Creator 2 nothing. Day chip Sat clicked in the page and the
  chips' border colours read at once (`nudge-day-trigger`); Night "Add from vault", tile 9002, Attach
  (`nudge-day-night-picked`); Evening "Edit for Saturdays" + first line retyped; Creators 1 and 2 switched on,
  "Share to 2 models" (`nudge-day-settled`). Checks (`lib/nudge_day_faults.py`): `DAY_CHIP` (Every day == Mon !=
  Sat), `VAULT_ONLY` (no Upload / image file input on Night, no `/vault/upload/*` POST), `DAY_SAVED` (Creator 0's
  `slots.saturday`, `default` unchanged), `SHARE_SAVED` (PUT config answered before the one bulk PUT; targets'
  settings and lines = Creator 0's, images their own, no Creator 0 id, nudge_online rules on), `DAY_PREVIEW`
  (23:00 Saturday = every-day line + 9002, Monday = 9001), `DAY_NO_5XX`. Layout flow, no budget. Faults
  `nudge-share-copies-source-images` (default, relay: bulk writes the source's slots as sent) turns only
  `SHARE_SAVED` red; `nudge-day-chip-fades` (client: the chips' `transition-colors` back) only `DAY_CHIP`.

- `2026-11-08-vault-download`: `flat_agency` (2 Creators), `OF_WIRE` + `lib/vault_wire.py` (`ip_bound`, `full_mp4`:
  a video's `files.full` is its source mp4), mirror by SQL (`seed/vault_week`), CDN armed (exact seeded bytes).
  Creator A no proxy (urls signed for "direct"), B on a `ProxyWire` proxy (urls signed for it). Stage relay-load
  (also --no-ui): `--users` concurrent `GET /admin/vault-ai/download` of B's whole vault. UI (1440x900): on A,
  Download selected (3 photos + 1 video), the rail's Download folder, the Extras drawer's (header ⋯) Download full vault with `STALE` urls
  signed for a proxy A left, then rail folder 2 selected and the drawer's Download full folder; on B, Download selected.
  Screenshots `vault-download-<select|folder|vault|header-folder|proxied>-trigger` / `-settled`. Checks
  (`lib/vault_download_faults.py`): `SELECT`, `FOLDER`, `VAULT` (stale ones: 403, re-signed by
  listing window, one OF read per window, 0 by-id, then direct 200), `HEADER_SCOPE` (the drawer item's label per scope; the browser's download listing
  requests, told apart from the grid's by page size, carry no folder id for the vault and that folder's id for the
  folder; fault `vault-download-header-ignores-folder`, client: the drawer item starts the whole vault under a selected
  folder, turns only it red), `PROXIED` (0 browser CDN fetches), `RELAY_LOAD`; files read off disk (path, a
  .jpg's exact bytes, an .mp4's size = served + ftyp), the panel's data-* counts, the relay's `vault_download` log
  lines; p95 of the relay download vs last green. Fault `vault-download-direct-ignores-proxy` (default, client:
  `sourceFor` drops the proxy rule) turns only `PROXIED` and `PHONE_SHARE` red. Phone stage (B, 390x844 Chromium
  mobile emulation, `touch`): `PHONE_CAP` (Select all > 20 off with "Phone: up to 20 at a time", 20 on, 21 off,
  folder / whole vault off with their reason), `PHONE_HEADER` (the Extras drawer's Download shown, icon + label, off with
  the desktop-only reason; `vault-download-phone-header`) and `PHONE_SHARE` (3 photos + 2 videos padded to 110 MB,
  `img_relay.padded_mp4` via `arm_run(mp4_sizes=)`, so >= 2 share batches; one sheet dismissed keeps the button;
  every file shared once with name / MIME / exact size; each share inside a user activation; no 5xx); screenshots
  `vault-download-phone-<cap|links|trigger|ready|settled>`. Fault `vault-download-share-batch-drops-item` (client:
  `addToBatches` drops the file that opens a batch) turns only `PHONE_SHARE` red. Links file: `LINKS` (each
  desktop phase writes `links-valid-*.txt/.html` first in `<creator>/[<folder>/]`, the picker stub's open order;
  one line / row per item, every id once; A's lines its CDN urls unexpired, B's the app relay url; the html opened
  in Chromium, `vault-download-links-html[-proxied]`, A's CDN link clicked (popup 200 through the CDN boundary,
  `-opened`), B's app link fetched with the session: 200 attachment, exact bytes) and `PHONE_LINKS` ("Save links"
  first, its own share inside the tap, txt + html, app urls). Copies `links-<phase>.txt/.html` in the run folder.
  Fault `vault-download-links-cdn-for-proxied` (client: `linkRows` drops the direct rule) turns only `LINKS` and
  `PHONE_LINKS` red. `SWITCH` (fresh browser on A: the Extras drawer's Download full vault, Creator B picked in the creator column
  mid-run; A's files all on disk with exact bytes, card done / 0 failed / titled with A, B's grid shown with its
  Extras drawer item "Add full vault to queue" on; `vault-download-switch-trigger` / `-settled`). Queue stage (fresh browser
  on B, root `queue`): 3 photos selected, the middle one's CDN response stalled (img_relay `stall`), A picked and its
  biggest non-first folder "Add folder to queue"d: `QUEUE_STALL` (B ends total 3 / done 2 / stalled 1 / failed 0,
  no file or .crswap for it, A's job starts by itself), `QUEUE_NAV` (A held mid-run; sidebar Dashboard and back by
  the card's Open Vault Pro: same job, no reload, then done), `QUEUE_CREATORS` (each job's files under its own
  Creator, exact bytes, nothing dropped or stray); `vault-download-queue-<trigger|stalled|away|settled>`. Faults:
  `vault-download-switch-aborts-run` (client: the run's unmount cleanup re-runs on a Creator pick) turns only
  `SWITCH` + `QUEUE_*` red; `vault-download-no-stall-watchdog` (STALL_MS 10 min) only `QUEUE_STALL`;
  `vault-download-nav-kills-run` (the run stopped once the path leaves its page) only `QUEUE_NAV` +
  `QUEUE_CREATORS` (main's keyed-subtree fault patched VaultProPage's page-level provider, gone now: one
  app-level provider). The download modules ship in 2 dev chunks (layout + Vault Pro page): their faults set
  `browser_files=DL_FILES`. Bypasses: the browser's CDN
  requests answered at its network boundary (Playwright route) by img_relay's fake with S3's CORS (ACAO `*` on
  200/206, none on 403; switch / queue stage: A's download fetches after the first 3 / 2 held until the stage
  releases them, a deterministic slow CDN; none held within 60 s is red, never a hang); queue stage: one of B's CDN
  responses sends headers + 1 KB then nothing for 45 s (img_relay `stall`, a sleep in the fake, relay side), re-armed
  without it after; the native folder picker stubbed (init script; each chunk over a binding to
  `<tmp>/downloads/<phase>/`, `.crswap` then rename, as Chromium); phone: `showDirectoryPicker` deleted and
  `navigator.canShare` / `share` stubbed by an init script that records the shared Files (no WebKit, no real sheet).
  Knob `--items=` (`vault_download_items` 40 / 300 / 1,000).

- `2026-11-05-vault-refresh`: `OF_WIRE` (`seed/of_sessions`) + `lib/vault_wire.py`, `agency_pool` plus in-scenario `_seed_world` (`seed/vault_week.mirror` for Refresh Creators, `seed/vault_week.hot_paused` for picker Creators, and `seed/vault_cache` keys), `lib/img_relay.py`
  armed with `pictures`. UI: Vault Pro on Creator 0 (desktop) and 1 (phone): a folder + 5 media made on OF after
  load, Refresh (screenshots `vault-refresh-<dev>-trigger` / `-settled`), then Refresh with OF's vault listing failing
  (`-fail`: the "Couldn't reach OnlyFans" note); the chat Vault picker on Creator 2 / 3 with page 1 cached and its
  thumbs 403 (its invalidate held for `picker-thumbs-<dev>-trigger`, then `-settled`). While Refresh is pending,
  repeated picker presses produce one POST; a later OF 500 yields a 502 and the failure note
  (`picker-refresh-<dev>-trigger`, `-settled`, `-failure-settled`). Stage `sync` (also --no-ui):
  150 media made on OF per load Creator (4+), `--users` concurrent `POST /admin/vault-ai/sync`. Checks
  (`lib/vault_refresh_faults.py`): `REFRESH_FOLDER`, `REFRESH_MEDIA`, `REFRESH_WIRE`, `REFRESH_FAIL_SHOWN`, `THUMBS_RELOAD`, `PICKER_FAILURE`,
  `SYNC_LOAD`, `SYNC_COALESCED`; budget sync p95 and vs the last green run. Faults: `vault-refresh-cache-only`
  (default, client: the pre-fix Refresh), `vault-refresh-fail-silent` (client: a failed sync reads as ok),
  `vault-thumbs-no-auto-refresh` (client), `vault-sync-no-coalesce` (relay; `--no-ui`).
- `2026-11-01-vault-pro-20k`: `agency_inbox` plus `seed/vault_items`: Creator 0 the big vault (`--vault_items=`,
  capped at `COLLECT_CAP`), every other a twentieth (at least 50). Stage `read`: `--users` owner sessions
  (`ctx.owner.share`) take tasks off one shared list, 1-3 s think after each: every 40-item page of every items
  walk per Creator (newest / oldest, each type, three searches, photo + search, each OF folder, each AI folder;
  page counts from SQL), plus `/cache/summary`, `/of-folders`, `/flags-review` (all, only_iffy). Stage `dupes`:
  per Creator `GET /duplicates` at strictness 0, 2, 4, 6, all at once. Stage `hide`: per Creator but the UI's, one
  `POST /duplicates/hide` (strictness 2) of up to 150 unsent copies plus a keeper, two sent copies, a non-copy and
  a copy only at 6; summary again. Stage `hide-strict0`: one hide at strictness 0 of a copy that is one only at 2.
  With UI, Creator 1's Extras > Duplicates, Remove > Yes, remove them (screenshots `vault-pro-dupes-trigger`,
  `vault-pro-dupes-settled`). Checks (`lib/vault_pro_faults.py`): `PAGING`, `FILTERS`, `DUPES` (== the planted
  groups; needs Creator 0's sets at 0 < 2 < 6), `HIDE`, `HIDE_STRICT0`, `SUMMARY_BEFORE`, `SUMMARY_AFTER`,
  `OF_FOLDERS`, `FLAGS` (needs planted live suspects), `UI_HIDE`; budgets (items and duplicates p95, p95 vs the
  last green run) are the scenario's. `KNOWN_RED` (SKIP with the reason when red): only the duplicates budget
  from a 20k vault. Faults: `vault-items-page-overlap` (default; swaps the items route's
  endpoint; targets `PAGING`), `vault-dupes-ignores-strictness` (`DUPES`, `HIDE_STRICT0`: the hide at 0
  re-clusters through it), `vault-hide-threshold-or-default` (`HIDE_STRICT0`). Knobs: `--vault_items=` (SCALES `vault_pro_items`; huge 20,000 (=
  `COLLECT_CAP`; the `min()` clamp caps overrides)).
- `2026-11-01-vault-describe-sweep`: `agency_inbox` plus `seed/vault_items_describe` (`--items=`), the Agency's
  dummy DeepInfra key through `PUT /admin/my-llm-keys`, `lib/vault_describe_relay.py` armed. Each phase runs its
  presses while `--users` owner tabs poll its status route every 2.5 s, and ends once every Creator's sweep settled
  and the fake went quiet: pass 1 (plan, then describe-all for every Creator at once; with UI the UI Creator's from
  Extras, "Describe all (N)", screenshots `describe-trigger` / `describe-settled`), flags (`flags-all {force}` for
  every Creator), pass 2 (must retry only the blank ones), pass 3 (describe-all pressed by 3 tabs at once per
  Creator). Checks (`lib/vault_describe_faults.py`): `EXACTLY_ONCE`, `PLAN`, `CACHE`, `ESCALATE`, `COST`,
  `COST_INCL_FLAGS`, `FLAGS`, `ONE_SWEEP`, `UI_SETTLED`; budgets
  (the status routes' p95 over pass 1, flags and pass 2, p95 vs the last green run) are the scenario's.
  `SLOP_LIVE=1`: every check SKIPs. Faults: `vault-describe-ignores-cache` (default; targets `CACHE`, `PLAN`),
  `vault-describe-cost-last-attempt` (`COST`, `COST_INCL_FLAGS`), `vault-describe-claim-after-budget` (the start
  claims the Creator only after awaiting the budget, so concurrent presses all start a sweep; `ONE_SWEEP`),
  `vault-describe-drops-flags-cost` (`COST_INCL_FLAGS`). Knobs: `--items=` (SCALES `vault_describe_items`),
  `--llm_latency_s=` (0.05 per call).
- `2026-11-11-vault-jev-flags`: `agency_inbox` plus `seed/vault_items_describe` (`--items=`, SCALES `vault_jev_items` 90 / 600 / 2,000; photos resized to unique 280-448 px edges and given a Jev profile each, a planted set one profile), both fakes armed. Jev switched on for Creator 0 and on-then-off for Creator 1 through the config route as VaultJevToggle saves it (GET, PUT back with `vault_jev_enabled`), the rest untouched; the plan's `jev` must say ready (NudeNet `NUDENET_640M_PATH`, default /tmp/nn-weights/640m.onnx) or the run stops. Phases (the describe sweep's `_phase`, loaded from its file): describe-all, then flags-all {force}, for every Creator at once. UI last (changes no check above): Vault Pro > Extras on Creator 2, the "Jev v8 flags" switch off (screenshot `vault-jev-toggle-off-trigger`), one click, settled on (`vault-jev-toggle-on-settled`), then config route, plan `jev` and account_ai_config row all on (`JEV_UI_TOGGLE`, SKIP with --no-ui). Planned lanes by profile (none free, pen $100, vulva $50, nipple $10, lower $50 via pass L, p2_clear $10 via pass 2, unsure free settled, pen_unsure $100 settled; NudeNet detects nothing on the flat stills: veto / promote never fire, declared). Checks (`lib/vault_jev_faults.py`): `JEV_ONLY_WHEN_ON`, `JEV_LANES`, `JEV_BEFORE_DESCRIBE`, `JEV_COST` (sweep `jev_cost_millicents` and total, `typesafe` grok_daily_cost row, grok_calls rows vs the fake's tokens at $0.042/M rounded up per photo), `JEV_COPY`, `JEV_DESCRIBE_PROSE` / `JEV_DESCRIBE_REVIEW` / `JEV_DESCRIBE_OFF` (the Jev-fed describe, D51: coin flips get the v6 recipe @960 with the hedge, every other on-Creator photo the prose recipe @640 whose hostile fake prose must be scrubbed to exactly the claims its answers spell, everything else V2 unchanged; `_describe` stamps), the describe sweep's status p95 budgets + p95 vs last green. Faults: `vault-jev-ignores-setting` (default; `JEV_ONLY_WHEN_ON`), `vault-jev-no-settle` (`JEV_LANES`), `vault-jev-after-describe` (`JEV_BEFORE_DESCRIBE`), `vault-jev-describe-ignores-review` (`JEV_DESCRIBE_REVIEW`). Knobs: `--items=`, `--set jev_latency_s=` (0.1), `--set llm_latency_s=` (0.05).
- `2026-10-30-vault-import-reducer`: Vault Pro > Add media's pick list
  (`app/components/vault/importPickReducer.ts`) on the real UI and relay route (one owner,
  1440x900, `agency_inbox`, Creator 0's vault mirror one SQL `vault_items` row): 4 tiny ffmpeg
  files picked, details typed, one deselected, one deleted, Start import. Checks
  (`lib/vault_faults.py`): the browser sends exactly the two chosen files with their own meta
  (`/vault/upload/batch` then one `/batch/append`), the relay's run lists them done, OnlyFans got
  their bytes (sha256), their `vault_items` rows carry the typed details, the card settles with the
  deselected file still listed (screenshots `import-trigger`, `import-settled`). No volume:
  `--users` and `--scale` change nothing, no budget. OnlyFans' side is `lib/vault_relay.py` (on
  when the run writes `of-vault.json`; `GET /__slop/vault/fake` answers `{claims, carriers,
  lists, minted}`; the upload claim in-process, the carrier post at OF's REST shape, the product's
  `materialize_to_vault`; the vault spool in the run's temp dir). Fault `import-sends-unselected`
  (client: `chosenOf` ignores the selection) turns every import check red. Then a folder-restricted chatter's
  picker (also `--no-ui`): one `chatter_folder_access` row to 1 of Creator 1's 3 OF folders; its folder access and
  vault lists through `vaultPickerFolders.folderSelectItems` in node (`lib/picker_ts.mjs`) and, with UI, its real
  picker must list exactly that folder (`RESTRICTED_MENU`); fault `picker-ignores-folder-access`
  (`lib/picker_faults.py`) turns only that check red. Relay-side fault `vault-import-status-drops-items`
  (`lib/vault_import_faults.py`: the status route's `items` lose the run's last one, the counts unchanged) turns
  only `RUN_ITEMS` red.
- `2026-11-05-vault-collect`: `flat_agency` (`vault_collect_creators` 6 / 16 / 40, `vault_collect_items` 400 /
  600 / 2,000), `OF_WIRE` + `lib/vault_wire.py`, CDN armed. 60% of Creators busy (pickers with refresh=1,
  chatters, fan DMs), the rest quiet; one relay stop/start mid-walk. Checks: `collect_pacing`,
  `collect_one_at_a_time`, `collect_skips_busy`, `collect_fills_mirror`, `collect_thumbs_warm`, `collect_resume`,
  `user_read_p95` (+ stock p95 vs last green). Faults: `collect-unpaced` (default; `collect_pacing`),
  `collect-ignores-user` (`collect_skips_busy`). Bypasses: fake OF + CDN at the wire, stills dirs by env, RELAY_ENV
  tick 2 s / first 1 s / GAP 1 s / USER_QUIET 20 s, the periodic started by the relay part, httpx pickers.
- `2026-11-05-vault-thumbs`: `flat_agency` (`vault_thumbs_creators` 3 / 6 / 10, `vault_thumbs_items`), mirror by
  SQL (`seed/vault_week`), collector off. `VaultWire(ip_bound, mp4)`: urls signed for the egress that listed them
  (`AWS:SourceIp`, `proxy_wire.egress_of`), videos with a playable 240p clip; the fake CDN 403s a url through any
  other egress. Phases cold / second / rotation / dead link / restricted chatter / proxy change / stale IP (mirror
  video urls signed for proxy A, account on B: /img/scrub + poster with media_id re-sign once through B); UI
  (small) shots `vault-thumbs-trigger`, `vault-thumbs-settled`, then a hover on a stale-IP video tile
  `vault-hover-trigger`, `vault-hover-frames-a/-b`, then gifs (`vault-gif-*`). Checks: `thumbs_second_open_zero_cdn`,
  `thumbs_survive_rotation`, `thumbs_dead_link_refreshed_once`, `thumbs_restricted_chatter_404`,
  `proxy_change_invalidates`, `proxy_change_previews_resign`, `ui_hover_scrub_after_proxy_change`,
  `ui_gif_tiles_loop_while_on_screen`, `ui_gif_details_loops_inline`, `ui_gif_clip_crosses_cdn_once` (each gif clip
  one CDN call across every UI open: /img's small-clip Range cache). Faults: `thumb-keyed-by-signed-url`
  (default; `thumbs_survive_rotation`), `thumb-no-resign` (`thumbs_dead_link_refreshed_once` + both stale-IP
  checks), `preview-no-resign` (both stale-IP checks), `gif-range-cache-off` (`ui_gif_clip_crosses_cdn_once`). Bypasses: as above plus OF's re-sign / expiry / old-proxy
  listing as mirror url rewrites (SQL) + the fake's gen, dead-link tiles fetched by id (persisted tiles), the CDN's
  egress = the proxy curl was handed (a header), one ffmpeg testsrc clip for every mp4.
- `2026-11-10-vault-manual-collect` (volume): `flat_agency` (`vault_manual_creators` 3 / 6 / 10,
  `vault_manual_items` 450 / 1,500 / 5,000), `OF_WIRE` + `VaultWire(mp4=True)`, CDN armed, collector off. Owner
  presses Collect on every Creator at once and polls status; `--users` pickers (typed media, items, status).
  Checks: `collect_newest_first` (desc page, folder list + page 0s, asc walk; clips after the walk newest first),
  `collect_first_batch_early`, `collect_complete`, `collect_once`, `collect_status_p95` (+ p95 vs last green).
  Faults: `manual-collect-asc-first` (default; newest_first + first_batch_early), `manual-collect-warm-at-end`
  (first_batch_early). Bypasses: fake OF + CDN at the wire, stills dirs by env, storyboards pre-warmed on disk for
  all but the newest 4 videos per Creator.
- `2026-11-10-vault-ai-folders-partial-flags` (UI): `agency_inbox` + `seed/vault_flags_partial` (`vault_ai_items`
  60 / 400 / 2,000), thumbs written into the still store. Checks: `ai_folders_plan_partial_flags`,
  `create_enabled_partial_flags`, `ai_folders_desk_only_phone` (Build AI folders is a desk-only tool),
  `ai_folders_created_from_ui`, `ai_folders_paid_flagged_only` (DB). Faults: `ai-folders-create-blocked-on-flags`
  (default, client; create_enabled), `ai-folders-guess-unflagged` (server; plan + paid_only). Bypasses: vault by
  SQL (no OF / LLM), "Also create on OnlyFans" switched off, collector off.
- `2026-11-11-vault-feet-picker` (UI): `agency_inbox` + `seed/vault_feet` (`vault_feet_items` 300 / 2,000 /
  12,000), full images written into the still store. Checks: `feet_ranked_above_like_baseline` (precision@N vs
  the old LIKE / media_id order), `feet_prefill_matches_flags` (incl. `_jev` lane5 / feet_subject rows),
  `feet_no_free_prefill_without_tier` (unknown tier never on the free rung), `feet_keyboard_confirm_members`
  (Enter x3, x, 1, Save; POST + DB members), `feet_phone_layout_tap_save` (390px: 2 columns, 44px taps, no
  overflow; tap + Save; DB), `feet_candidates_p95` (budget). Faults: `feet-rank-like-only` (default, server; ranked
  + prefill + keys), `feet-free-prefill-unknown-tier` (server; no-free + prefill),
  `feet-keys-enter-ignores-suggestion` (client; keys). Bypasses: vault by SQL (no OF / LLM), collector off,
  Publish not pressed.

- `2026-11-11-vault-tag-chips` (UI): `agency_inbox` + `seed/vault_tag_chips` (`vault_tag_items` 80 / 2,000 /
  12,000), thumbs written into the still store, `of-vault.json` (lib/vault_relay.py answers the publish). API stage
  (also --no-ui): `/tag-facets` unfiltered and with both chips, the items walk with `tags=feet&tags=lace`, p95 of
  both reads vs last green. Desktop 1440x900: tap feet then lace, Save as folder (default name), the saved row
  "Saved locally · name · N items", Publish, confirm, "Published to OnlyFans". Phone 390x844 (touch): the same up to
  the saved row, Publish's confirm opened and cancelled. Screenshots `vault-tag-chips[-phone]-trigger` /
  `-settled`, `-publish-confirm`, `-published`, `-phone-confirm`. Checks: `tag_facets_counts`,
  `tag_filter_and_three_sources`, `tag_chips_desktop`, `tag_chips_phone_fit`, `tag_folder_saved_from_ui`,
  `tag_folder_published` (OF got one list == the match set; the folder's of_list_id), `tag_folder_members_exact`
  (DB: each saved folder, operator-made, == the match set), `tag_chips_no_5xx`. Fault `tag-filter-ignores-ai-tags`
  (default, server: the filter skips `ai_fields_json.tags`) turns the filter, saved, published and members checks
  red. Bypasses: vault by SQL (no OF / LLM), OF's list calls in-process (lib/vault_relay.py), collector off.
