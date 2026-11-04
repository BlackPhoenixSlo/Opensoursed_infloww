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

## Scenarios

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
