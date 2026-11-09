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
| `lib/vault_describe_relay.py` | DeepInfra's OpenAI-compatible wire on its own loopback port, inert until the run wrote `deepinfra.json` and armed it (`arm_run`, `POST /__slop/vault-describe/arm`; 409 under `SLOP_LIVE=1`): answers describe prompts by each item's outcome (ok; refuse: 30b refuses, 235b answers; blank: both ""), flags prompts with flags JSON plus a hostile description / tags, bills each answer at `llm_models.MODELS`' listed price; re-points the still stores into the run's temp dir. `GET /__slop/vault-describe/calls`, `/count`. |
| `lib/vault_describe_faults.py` | The describe sweep's check names and its faults (below). |
| `lib/vault_relay.py` | OnlyFans' side of a vault import (upload claim, carrier post, `GET /__slop/vault/fake`), for `2026-10-30-vault-import-reducer` (below). |
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
| `lib/vault_download_faults.py` | Vault Pro download's check names and its fault (below). |
| `scenarios/2026-11-08-vault-download.py` | Download selected / folder / whole vault, direct vs relay; its `Disk` (the picker stub's far side). |

## Scenarios

- `2026-11-08-vault-download`: `flat_agency` (2 Creators), `OF_WIRE` + `lib/vault_wire.py` (`ip_bound`, `full_mp4`:
  a video's `files.full` is its source mp4), mirror by SQL (`seed/vault_week`), CDN armed (exact seeded bytes).
  Creator A no proxy (urls signed for "direct"), B on a `ProxyWire` proxy (urls signed for it). Stage relay-load
  (also --no-ui): `--users` concurrent `GET /admin/vault-ai/download` of B's whole vault. UI (1440x900): on A,
  Download selected (3 photos + 1 video), the rail's Download folder, Download whole vault with `STALE` urls signed
  for a proxy A left; on B, Download selected. Screenshots `vault-download-<select|folder|vault|proxied>-trigger` /
  `-settled`. Checks (`lib/vault_download_faults.py`): `SELECT`, `FOLDER`, `VAULT` (stale ones: 403, one by-id
  re-sign each, then direct 200), `PROXIED` (0 browser CDN fetches), `RELAY_LOAD`; files read off disk (path, a
  .jpg's exact bytes, an .mp4's size = served + ftyp), the panel's data-* counts, the relay's `vault_download` log
  lines; p95 of the relay download vs last green. Fault `vault-download-direct-ignores-proxy` (default, client:
  `sourceFor` drops the proxy rule) turns only `PROXIED` and `PHONE_SHARE` red. Phone stage (B, 390x844 Chromium
  mobile emulation, `touch`): `PHONE_CAP` (Select all > 20 off with "Phone: up to 20 at a time", 20 on, 21 off,
  folder / whole vault off with their reason) and `PHONE_SHARE` (3 photos + 2 videos padded to 110 MB,
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
  `PHONE_LINKS` red. Bypasses: the browser's CDN
  requests answered at its network boundary (Playwright route) by img_relay's fake with S3's CORS (ACAO `*` on
  200/206, none on 403); the native folder picker stubbed (init script; each chunk over a binding to
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
