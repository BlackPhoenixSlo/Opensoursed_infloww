# Phase 02a — Primitives (Relay only)

**Objective.** The Relay has the shared primitives every later Fansly lane builds on: a Live-check grant read from `PLATFORM_LIVE_CHECK`, one `send_refusal`, neutral Platform markers, a Platform key that refuses when unknown and validates before any write, five new unused Lack members, a KIND_VERDICTS harness with a marker-call recorder over a Stateful fake, a Lift table kept honest by a drift test, Provenance and Coverage columns in the parity doc, and two WATCH checks. No Fansly behaviour changes for a fan in this Phase.

## Problem Statement
An owner running a Fansly Creator next to OnlyFans Creators cannot trust what the Relay says it did. A Fansly send with tagged users or locked text goes out without them and reports success. A Fansly send creates a chat group before it finds out the send is refused. Three Shim methods (mark unread, pin, unpin) answer `{"success": true}` when nothing happened. An account whose stored Platform key is a typo or a Platform this build does not know is treated as OnlyFans and gets an OnlyFans client. A write with an unknown key saves files before it fails. No one can turn on a single real write for one owner-chosen fan without a code change, so nothing built can be checked live. Nothing counts which automation kinds really work on Fansly, which refuse, and which do nothing. Each refusal has no written path to being lifted. Markers are named after Fansly, so a third Platform would copy the Fansly name or miss the scan.

## Solution
Every refusal has one name, one place it is decided, and one row that says how it is lifted. A Fansly send carrying tagged users or locked text answers 501 (route) or persists a skipped run with `platform_lacks:tagged_users` / `platform_lacks:locked_text` (automation), before any group is made, any Cell send claim is taken or any write is done. An unknown Platform key refuses with `platform_unknown:<key>`, loads no client and writes no file. The owner can name one account, one method and one fan in `PLATFORM_LIVE_CHECK` on a local Relay to run a Live check, and nothing else changes; the variable is not passed through on deploy, so it is off in every deployed stack. A test harness drives every registered automation kind on Fansly and OnlyFans and asserts its Verdict. The parity doc shows how each built thing was proven and how much of it is covered. WATCH alerts when the Live-check variable is set somewhere or when an unknown key reaches an automation.

## User Stories
1. As an owner, I want a Live-check grant written as `<aid>:<method>:fan=<id>` (or `<aid>:delete_list:list=<id>`) in `PLATFORM_LIVE_CHECK`, so that I can run one real write on one fan of my choosing.
2. As an owner, I want a Live-check name (Shim `platform_live_check` method or a `LIVE_CHECK_LANES` lane) to refuse with `platform_lacks:<method>` unless a grant names this account, this method and a target that matches the whole effective audience — `fan=` only when the Complete audience is exactly that fan, `list=` only when the list id matches, its fresh read is Complete and every member is a `fan=` target granted on that account — so that a grant can never reach a second fan or a wrong list.
3. As an owner, I want a grant without a target, an empty audience or an unknown audience to refuse, so that a typo never widens the grant.
4. As an owner, I want the grant read on every call, so that unsetting the variable takes effect without a restart.
5. As an owner, I want the grant checked at the caller before any Cell send claim, group, enqueue or write, so that a refused Live check leaves no business row and no request behind (the executor's own job claim and run row are bookkeeping).
6. As an operator, I want `PLATFORM_LIVE_CHECK` absent from every compose file, so that a Live check is off on every deploy.
7. As an owner, I want the Capability test to print how many methods sit behind a Live check, next to the built, unsupported and blocked counts, so that I can see what is waiting on me.
8. As an owner, I want the parity doc's Phase 1b tables to show Provenance (M/W/I/B) and Coverage for every built row, so that I can tell a measured method from a guessed one.
9. As an owner, I want a row built behind a Live check to read 🔬 "live check pending", and to read ✅ `Live check <date>, Relay <sha>` only after my pass, so that the doc never claims a check that did not happen.
10. As a maintainer, I want the markers named `platform_unsupported`, `platform_blocked` and `platform_live_check`, so that a third Platform reuses them instead of copying a Fansly name.
11. As a maintainer, I want a marker to reject at import a `returns=` that is callable or a mapping with truthy `success`, and mark unread, pin and unpin on Fansly to raise instead of answering `{"success": true}`, so that no route reports a write that did not happen.
12. As a maintainer, I want the registry scan built from every non-OnlyFans Platform's key, label and entry name, probed with `meta.get("platform") == "<key>"`, so that a new Platform is scanned without editing the test.
13. As a maintainer, I want an account with no stored key, or a None key, to stay OnlyFans, so that every existing account keeps working.
14. As an owner, I want an account whose stored key is a non-empty string the registry does not know to resolve to the Unknown platform, so that it is never driven as OnlyFans.
15. As an owner, I want dispatch, client loads and automations on an Unknown platform account to refuse with `platform_unknown:<key>` and load zero clients, so that no OnlyFans request is made in that account's name.
16. As an owner, I want the roster and per-account sweeps to keep listing an Unknown platform account instead of crashing, so that one bad key does not take down the agency view.
17. As a maintainer, I want saving an account, claiming its Platform and saving a Fansly credential to validate both the requested key and the stored key before any Cell reservation, early return or file write, so that an unknown key — fresh id or a stored `myspace` relinked as Fansly — raises with zero reservations and unchanged credential and metadata bytes.
18. As a maintainer, I want the drift test to report "table keys != registry keys" for a dummy third key, and a new assertion that every non-OnlyFans row has a Backend, so that a half-registered Platform fails CI.
19. As a maintainer, I want the myspace and other unknown-key tests updated to expect the Unknown platform, so that the suite states the new rule instead of the old fallback.
20. As a maintainer, I want one neutral-marked refusal driven through `run_once` in acceptance, failing if the rename is reverted, so that the rename is proven on the automation path.
21. As a maintainer, I want one pure `send_refusal(platform, payload)` used by the composer send route, both schedule routes and the scheduled send automation, so that every send path refuses the same payloads with the same reason.
22. As a chatter on a Fansly Creator, I want a send or schedule with tagged users to answer 501 `platform_lacks:tagged_users`, so that a fan never gets a message missing its tags.
23. As a chatter, I want a send or schedule with locked text to answer 501 `platform_lacks:locked_text`, so that a locked message is never sent unlocked.
24. As an owner, I want a scheduled send that carries tags, or that would really get media co-tags (automated purpose, co-tag switch on, media that `needs_cotag`), to persist a skipped run with `platform_lacks:tagged_users` at fire time before the audience fire check, any client or any Cell send claim, so that the queue says why it did not send; a text-only or co-tag-free media job still sends.
25. As an owner, I want the Shim to validate a send before it resolves or creates a chat group, and the composer route to refuse before it resolves or creates an outbound employee, so that a refused send leaves zero new groups and zero new rows.
26. As an owner, I want the OnlyFans side of every send path unchanged, so that tags and locked text still work there.
27. As a maintainer, I want `KIND_VERDICTS[platform][kind][branch]` for every registered kind (34 today), its kind keys checked for set equality against `registered_kinds()` after `load_automation_plugins()` with `failed_plugins()` empty, and each `LEGACY_KINDS` alias (`of_ai_chat`) driven separately through `get_automation`, so that a new kind without a Verdict fails CI.
28. As a maintainer, I want each Verdict row driven through job claiming and `run_once` with the real Shim over the Stateful fake, asserting run outcome, job disposition, provider calls and row deltas, so that a Verdict is observed, not asserted by hand.
29. As a maintainer, I want the seeded branches (reply_mass_funnel landed send, customs_watch owed flag) driven with their seeds, so that a kind that only acts on a seed is not graded on its empty path.
30. As a maintainer, I want an OnlyFans control for every branch, so that a Fansly refusal is never a broken test fixture.
31. As a maintainer, I want every Fansly branch to prove the branch-specific effect its row names (a provider write by method and path, or a write to the lane's own output table), a Declared no-op, or a persisted refusal with zero business writes, with reads, error-status rows and bookkeeping never counting as an effect and an unmarked `{}` failing, so that silence never passes as support.
32. As a maintainer, I want a marker-call recorder that records every marked-method call during a run — decorated wrappers and the directly marked `send_mass_message` alike — and any call outside a reasoned allowlist to fail, so that a lane cannot reach a marked method unnoticed.
33. As a maintainer, I want a required per-branch payload table, so that every kind is driven with a payload that reaches its writes.
34. As a maintainer, I want a Stateful fake of Fansly built only from `_source` fixtures and recipes, comparing method, path and body values, with read-back, repeat and undo, and raising on any unmodelled request, so that a built method is proven against the evidence bar.
35. As a maintainer, I want a `run_once` test with the gate open and the grant missing showing a persisted skipped `platform_lacks:` run with zero provider requests, business writes and follow-ups (executor bookkeeping allowed), so that the missing-grant path is proven.
36. As a maintainer, I want Lack members TIP_LEDGER, PURCHASE_LINKAGE, RENEWAL_STATE, LAPSE_DETECTION and RETURN_DETECTION added with no consumer, so that the lanes that need them land without editing the registry.
37. As a maintainer, I want a `## Lift table` in the parity doc with columns Reason | Where it refuses | Grade + evidence | Lifted by | Owner action | Follow-up PR | Ticket, so that every refusal has a written lift path.
38. As a maintainer, I want a drift test asserting the Lift table's reasons equal Shim markers plus Lack members plus KIND_VERDICTS `gated:` reasons plus route-only reasons, branch suffixes included and one trailing `:<digits>` stripped, so that a new refusal without a row fails CI.
39. As an operator, I want a `platform_live_check_env` WATCH check that alerts when `PLATFORM_LIVE_CHECK` is set and answers `unknown` when the Relay's process env could not be read, so that a forgotten grant on a deployed stack is caught within a sweep and never reported clear by guess.
40. As an operator, I want a `platform_refusals` WATCH check that alerts on any skipped run with a `platform_unknown:` reason and reports `platform_lacks:` counts, proven on a row the executor itself wrote, so that an unknown key on prod is caught and refusal volume is visible.

## Implementation Decisions
- **Owns.** `platforms` (Lack members, Unknown platform, key validation), `side_effect_gate` (live_check, send_refusal, marker classification), the Fansly Shim (marker rename, recorder, send validation order, removal of `returns=` success values), `accounts` and the Fansly backend's credential save (validate before write), `client_pool`, `automation_executor` (client factory refusal, unknown-key run outcome), `run_decide` (prefix), the Relay's client loader, composer send route and both schedule routes, the scheduled send automation, the Stateful fake and its test, the KIND_VERDICTS harness, the Live-check test, the Lift-table test, the platform registry / drift / capability / dispatch tests, the proxy-health WATCH table and its tests, the parity doc, the platform recipe doc, ADR 0068 status, and the strip patches for `platforms` and the platform recipe.
- **Interfaces.**
  - `platforms.Lack` gains `TIP_LEDGER`, `PURCHASE_LINKAGE`, `RENEWAL_STATE`, `LAPSE_DETECTION`, `RETURN_DETECTION`. FANSLY's `lacks=frozenset(Lack)` takes them automatically. `platforms.lack_reason(lack) -> "platform_lacks:<value lower>"`.
  - `platforms.UnknownPlatform` is a frozen Platform value carrying the raw key, label "Unknown platform", no Backend and every Lack. `platforms.get(key)` strips and lower-cases the key before lookup (so `'OnlyFans'` and `' onlyfans '` keep resolving): missing, None or empty → ONLYFANS; registered → its Platform; any other string → UnknownPlatform(key). `platforms.require(key)` raises `UnknownPlatformKey` (a ValueError) for anything `get` would make Unknown. `refusal_for_account` answers `platform_unknown:<key>` for any name on an Unknown account.
  - `side_effect_gate.PLATFORM_UNKNOWN_PREFIX = "platform_unknown:"`. `classify` gains the verdict `live_check`; `refusal` returns its reason, so routes refuse it unchanged.
  - The one grant API (every later Phase cites these names; no Phase adds a second reader):
    - `Target = FanTarget(fan_id) | ListTarget(list_id)`; `ListAudience(list_id, member_ids: frozenset[str], complete: bool)`.
    - `side_effect_gate.live_check_targets(account_id, method) -> frozenset[Target]`: pure env read on every call, the only presence probe.
    - `side_effect_gate.live_check_methods(account_id) -> frozenset[str]`: methods with at least one valid entry for the account (02g's `/admin/accounts` field).
    - `side_effect_gate.live_check(account_id, method, audience) -> str | None`: None means proceed; `audience` is `frozenset[fan_id]` or `ListAudience`. A `fan=` grant passes only when the audience is Complete and equals exactly `{fan}` (a `ListAudience` counts by its `member_ids` and needs `complete`); a `list=` grant passes only when `audience` is a `ListAudience` with that `list_id`, `complete`, and `member_ids` ⊆ the union of `fan=` targets granted on that account (empty passes). Anything else, including an empty or incomplete audience, answers `platform_lacks:<method>`.
    - `side_effect_gate.LIVE_CHECK_LANES: frozenset[str]` (caller-side lanes with no single Shim method) ships empty; 02b adds `priority_mass`, 02c adds `nudge_online`.
    - `side_effect_gate.is_live_check_name(platform: Platform, name) -> bool` = name is a Shim `platform_live_check` method of that Platform's Backend or in `LIVE_CHECK_LANES`; it takes a `Platform` value only and reads `platform.backend` (the `platforms` import is type-only, since `platforms.py:9` imports the gate). Lanes apply only on a Platform with a Backend module: on ONLYFANS or an Unknown platform it is False for every name, lanes included. A name for which it is False falls through to `refusal_for_account`.
  - `side_effect_gate.send_refusal(platform, payload, *, would_cotag=False) -> str | None`, pure. Reads the Shim class mapping `SEND_REFUSALS`. Order: Unknown platform → `platform_unknown:<key>`; no Backend → None; non-empty `tagged_users` → `platform_lacks:tagged_users`; `would_cotag` → `platform_lacks:tagged_users`; non-empty `locked_text` → `platform_lacks:locked_text`. The caller computes `would_cotag` the way the send would: `auto_tag` as the caller derives it (scheduled_send: `send_purpose != "manual"`; composer and both schedule routes: False) and `media_cotag.enabled()` and media present and `media_cotag.needs_cotag(aid, media_files)`.
  - Shim decorators `platform_unsupported(reason, returns=…)`, `platform_blocked(reason)`, `platform_live_check(reason)`; attributes of the same names. The error classes `FanslyUnsupported` / `FanslyBlocked` keep their names and 501 status. A `returns` that is callable, or a mapping with truthy `success`, raises at import (the `returns=list` / `returns=lambda: {...}` call sites become plain values or drop `returns`). `platform_live_check` does not block inside the Shim; the caller authorises.
  - Shim marker-call recorder: a contextvar holding a list or None (default None, zero cost); every marked wrapper appends its method name when set, and `send_mass_message` (marked by direct assignment, guard inside its body) appends on entry. Its `confirm_live_broadcast` guard is unchanged in 02a.
  - `automation_executor._make_client` and `client_pool.get` raise a platform refusal for an Unknown platform account before building any client. `run_once`, after the claim, opens the run and finalises it skipped `platform_unknown:<key>`, job done, without calling the kind.
  - `run_decide.outcome` treats a `platform_unknown:` reason like `platform_lacks:` (skipped, done).
- **Schema.** None — reasons live in the existing `automation_runs.stats_json`; no migration.
- **Contracts.**
  - `PLATFORM_LIVE_CHECK`: comma-separated entries `<aid>:<method>:fan=<id>` or `<aid>:<method>:list=<id>`, whitespace trimmed. `list=` is valid only for `delete_list`; every other method (nudge_online, block_user, priority_mass, send/schedule/cancel mass) takes `fan=`. A bare, target-less or wrong-kind entry is ignored with one warning log and never matches (ADR 0070 allows a bare entry in the grammar; 02a makes it inert).
  - Every Live-check refusal reason is `platform_lacks:<method>`.
  - Refusal reasons are lower case: `platform_lacks:<method>`, `platform_lacks:<lack>`, `platform_lacks:tagged_users`, `platform_lacks:locked_text`, `platform_unknown:<key>`. Branch-specific reasons keep the `<method>:<branch>` suffix.
  - Route refusals answer 501 with the reason in `detail` (existing `raise_if_refused`); `_load_client` answers 501 for `platform_unknown:` before its ValueError → 503 mapping.
  - Parity doc: Phase 1b tables gain `Provenance` and `Coverage` columns; Live-check rows use 🔬 `live check pending` / ✅ `Live check <date>, Relay <sha>`; `## Lift table` with the seven columns above.
  - WATCH: `platform_live_check_env` (env `PLATFORM_LIVE_CHECK`; alert when set; `unknown` when unread) and `platform_refusals` (SQL over skipped `automation_runs` grouped by reason prefix; alert on `platform_unknown:`, ok with `platform_lacks:` counts). The collector (`remote_db.py`) adds `env.source` = `proc1` or `self` when `/proc/1/environ` was unreadable and it fell back to its own env; `platform_live_check_env` raises `LookupError` (→ `unknown`) on `self`. Existing env checks keep today's reading.
- Live check authorisation runs where the caller already holds the audience (fan ids, or the fresh Complete read of a list-bound method's list); no 02a caller exists, so the path is proven with a test-only Shim subclass and a test-registered kind inside the test file, never in `service/`. The grant binds account, method and target; Branch eligibility (ticket 00 item 7: only the single include-list branch) is the caller's Branch gate, run before `live_check`.
- No Shim method is marked `platform_live_check` and `LIVE_CHECK_LANES` is empty in 02a, so the Capability count (marked methods ∪ lanes) prints 0.
- `send_refusal` is called in the composer send route first, before `resolve_outbound_employee_id` (which can insert a mirror Employee), `_reject_if_resale`, `send_ops.dispatch` and the Cell op id; in both schedule routes before `_enqueue_scheduled` (and its employee resolve) or `schedule_message`; in scheduled_send before `audience_include.check_at_fire`, `_make_client` and the send claim. The executor's job claim before the plugin is bookkeeping. The Shim's `send_message` runs `check_sendable` and the same `SEND_REFUSALS` checks before `_group_for_send`, as a second line for callers outside the four paths.
- `ensure_platform` first runs `platforms.require(key)` and, when meta exists, `platforms.require` on the stored key, both before `creator_reservations.admit`; a stored Unknown key raises `PlatformCollision` (409) explicitly, because `UnknownPlatform` is not in `platforms.ALL` and the existing collision loop would miss it. It stays refused until the key is fixed by hand. The Fansly credential save runs the stored-key check before writing the session file; `upsert_account` calls `platforms.require` on the resolved key (argument or stored) before `save_meta`.
- Until 02d's 09 C, the roster emits the raw Unknown key and the app's `accountPlatform` shows it as OnlyFans with OnlyFans controls; every Relay path those controls reach refuses with 501 `platform_unknown:<key>`, so the interim is a wrong label with no wrong write. 02a does not touch `app/`.
- The registry scan, drift test and lift-table test derive their sets from the registry, Shim attributes and the KIND_VERDICTS literal (read by `ast.literal_eval`, not import), so adding a Platform or kind needs no test edit.
- KIND_VERDICTS rows: `same`, `gated:<reason>`, `noop:<reason>`, or `owner:NN`. Every row records the observed (status, reason, effect set) and the harness asserts equality; `same` rows name their branch-specific effect. A row whose run shows none of effect / Declared no-op / refusal (today `priority_mass`'s audience read + error row with zero sends) may only be `owner:` and so fails 02h. `owner:` cells are allowed in 02a and fail only in Phase 02h's final acceptance. Branch keys per kind must equal between KIND_VERDICTS and the per-branch payload table (story 33), both seeded from ticket 12's verdict table; one harness self-check swaps one kind's send for a plugin returning `{}` and must fail the harness (one mutation per harness; the branch-key equality is a plain assertion, not a mutation).
- Lift-table drift test reason sources: Shim markers, Lack members, KIND_VERDICTS `gated:` reasons, and the route-only reasons (`platform_lacks:tagged_users`, `platform_lacks:locked_text`, `platform_unknown:<key>` as one row). Before comparing, each reason has one trailing `:<digits>` stripped, so a counted reason (02f's `…:contact_guard:<n>`) is one row.
- File rules from ticket 11 bind: this Phase's PR is the only one editing `platforms`, the Relay server module or the Shim while it is open; the M0 mirror message goes out before the first Shim edit; verdict and parity rows move with their branch.
- **Two PRs, one spec (D2).** Linear order: 02a-1 merges before 02a-2 opens; both precede 02b.
  - **02a-1 — behaviour** (branch `feat/mp2-02a1-primitives`). Stories 1–7, 10–26, 35–36. Files: `service/platforms.py` (Unknown platform, key normalisation, `require`, Lack members, `lack_reason`), `service/side_effect_gate.py` (grant API, `send_refusal`, `PLATFORM_UNKNOWN_PREFIX`, `live_check` verdict), `fansly/fansly_shim.py` (marker rename, `returns=` ban, recorder, validate-before-group, mark unread/pin/unpin raise), `service/accounts.py`, `service/fansly_backend.py`, `service/client_pool.py`, `service/automation_executor.py`, `service/run_decide.py`, `service/server.py` (client loader, composer send, both schedule routes), `service/automations/scheduled_send.py`, `service/tests/test_platform_registry.py`, `service/tests/test_platform_table_drift.py`, `service/tests/test_platform_capability.py`, `service/tests/test_platform_dispatch.py`, `service/tests/test_live_check.py`, `service/tests/test_send_refusal.py`, the myspace/unknown-key test updates (story 19), `docs/platform-recipe.md` (ADR-0068 lines), ADR 0068 status, strip patches for `platforms` and the recipe.
  - **02a-2 — tests and docs only** (branch `feat/mp2-02a2-harness`). Stories 8–9, 27–34, 37–40. Files: `fansly/stateful_fake.py`, `fansly/test_stateful_fake.py`, `service/tests/test_platform_kind_verdicts.py` (harness skeleton + remaining verdict rows), `fansly/test_lift_table.py`, `fansly/FANSLY_PARITY_STATUS.md` (Provenance/Coverage, `## Lift table`), `scripts/proxy-health/watch.py`, `scripts/proxy-health/remote_db.py`, `scripts/proxy-health/test_watch.py`. No `service/` runtime file changes in 02a-2.
  - WATCH.md: the `platform_refusals` line is added at the first prod deploy that contains 02a-1 (the check itself lands in 02a-2; if that deploy precedes 02a-2, the line is added at the first deploy containing both). No prod read audit runs (owner: never prod DB).
- ADR 0068 moves from proposed to accepted in the 02a-1 merge PR. Strip patches for `platforms` and the platform recipe are regenerated with the public-sync strip-regen script.

## Testing Decisions
- **Seam 1: `automation_executor.run_once` and its persisted run row.** The KIND_VERDICTS harness, the Live-check test, the scheduled-send refusal and the unknown-key refusal all drive queued fixtures through job claiming and `run_once`, asserting run status and reason, job disposition, exact provider calls on the Stateful fake (or the OnlyFans recording stand-in), zero Cell send claims (`send_ops` rows) and exact business-row deltas. This is the highest seam that holds every automation outcome.
- **Seam 2: Relay routes through the test client, Cells on.** Composer send (with `x-op-id` anchor and a missing mirror Employee), both schedule routes and the client loader are asserted on status, reason, and exact deltas: zero `send_ops` rows, zero jobs, zero Employee rows, zero requests on the Stateful fake (no `/group`). Each case has an OnlyFans control that still sends tags and locked text.
- `send_refusal` table: explicit tags, locked text, legacy text-only job, automated media with co-tag switch off, automated media that `needs_cotag` is False for, automated media that needs a co-tag, manual media — only explicit tags, locked text and the needs-co-tag row refuse.
- Live-check table: no grant, bare entry, `list=` on a non-`delete_list` method, grant for another account / method / fan, audience of two fans, `ListAudience` whose Complete read holds two fans or only another fan under a `fan=` grant, incomplete `ListAudience`, `list=` grant with the wrong list id, `list=` with a member outside the granted `fan=` targets, `list=` on an empty Complete list, exact single fan, unset between calls; `live_check_targets` and `live_check_methods` over the same env values; `is_live_check_name` with a test-added lane.
- Unknown-key writes: fresh id with `myspace`, stored `myspace` relinked through the Fansly prove/save path with Cells on — zero reservations, credential and meta bytes unchanged.
- Marker recorder: a decorated marker and `send_mass_message` both recorded; a callable `returns` and `returns={"success": True}` both raise at import.
- WATCH: env set / unset / unreadable (`source=self` → `unknown`); `platform_refusals` SQL fed a row written by `_finalize_run` from a real `run_once` refusal.
- **Seam 3: Shim over the Stateful fake.** Built Fansly methods are proven by method, path and body value, with read-back, repeat and undo; unmodelled requests raise.
- **Seam 4: pure functions and the scan/drift tables.** `send_refusal`, the grant API, `platforms.get/require` (`'OnlyFans'` and `' onlyfans '` → ONLYFANS), registry scan, table drift, Lift-table drift, capability counts.
- Prior art: `service/tests/test_fansly_automation_gates.py` (`_Recorder`, `_Fansly`, `_OF`, patched `_make_client`), `fansly/test_har_replay.py` (RecordingHTTP body compare), `service/tests/test_platform_capability.py` (per-lane payload table at line 21, verdict counts), `service/tests/test_platform_registry.py`, `service/tests/test_platform_table_drift.py`, `service/tests/test_automation_executor_decide.py`, `service/tests/test_scheduled_send.py`, `scripts/proxy-health/test_watch.py` (`_w_env` / `tx_recent_window_env` row).
- Tests are plain scripts (repo rule); no test hook goes into `service/`; the Stateful fake lives beside the Fansly tests.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# 02a-1 PR runs this block minus test_platform_kind_verdicts, test_stateful_fake, test_lift_table, the proxy-health line and the Lift/Provenance/WATCH greps; 02a-2 PR runs all of it
for t in \
  service/tests/test_platform_registry.py \
  service/tests/test_platform_table_drift.py \
  service/tests/test_platform_capability.py \
  service/tests/test_platform_dispatch.py \
  service/tests/test_live_check.py \
  service/tests/test_send_refusal.py \
  service/tests/test_platform_kind_verdicts.py \
  service/tests/test_fansly_automation_gates.py \
  service/tests/test_fansly_unsupported_writes.py \
  service/tests/test_scheduled_send.py \
  service/tests/test_automation_executor_decide.py \
  service/tests/test_of_stats_daily.py \
  service/tests/test_screens_api.py \
  service/tests/test_session_ingest_identity.py \
  service/tests/test_of_live_window.py \
  service/tests/test_chat_read_changed_sse.py \
  fansly/test_stateful_fake.py \
  fansly/test_lift_table.py \
  fansly/test_automation_methods.py \
  fansly/test_fansly_capability.py; do
  nice -n 10 venv/bin/python "$t"
done
nice -n 10 venv/bin/python service/tests/test_platform_capability.py | grep -E 'live_check[^0-9]*[0-9]+'
nice -n 10 venv/bin/python scripts/run_tests_parallel.py --pytest scripts/proxy-health -j 8
grep -q '^## Lift table' fansly/FANSLY_PARITY_STATUS.md
grep -q 'Provenance' fansly/FANSLY_PARITY_STATUS.md && grep -q 'Coverage' fansly/FANSLY_PARITY_STATUS.md
if git grep -n -E 'fansly_unsupported|fansly_blocked' -- service fansly docs/platform-recipe.md; then exit 1; fi
if git grep -n 'PLATFORM_LIVE_CHECK' -- '*compose*.yml' '*compose*.yaml'; then exit 1; fi
git grep -q -E 'platform_live_check_env|platform_refusals' -- scripts/proxy-health/watch.py
grep -q -i 'status.*accepted' docs/adr/0068-*.md
venv/bin/python scripts/comment_budget.py --check
nice -n 10 scripts/run-tests.sh
nice -n 10 bash -c 'cd app && pnpm test:run'
# manual: owner runs each Live check locally with PLATFORM_LIVE_CHECK=<aid>:<method>:<own fan id>, then flips the row to ✅ in a follow-up PR (ADR 0070, two PRs)
```

## Depends on
No Phase — 02a is the base Phase; every other Phase depends on it. 02a-1 precedes 02a-2 (D2).
Linear PR order (D8): 02a-1 → 02a-2 → 02b → 02c → 02d → 02e → 02f → 02h → 02g (02g last, gated on the mirror filter).
Precondition: ticket 11 item 5 M0 — the mirror thread ("Fansly Manager Feature Coverage") has received our file list and the first-Shim-edit reservation by `t3_thread_send` before the first `fansly/fansly_shim.py` edit; the implementer cites the sent message in the PR body.

## Out of Scope
- 00 c (re-keying `confirm_live_broadcast` / the mass-send gate onto a Live-check grant) — plan assigns it to 02f.
- 09 C (the app rendering "Unknown platform") — plan assigns it to 02d.
- Any consumer of the five new Lack members — they are added unused here; their lanes are 02b and 02c.
- `branch_refusal`, media send refusals, 12 c/d and 13 A — plan assigns them to 02c.
- Direct `OFClient.from_account` caller in apply_profiles (12 item 7) — plan assigns it to 02c.
- Marking any method `platform_live_check` and lifting any refusal — each lift is its own lane PR in a later Phase.
- WATCH.md line for `platform_live_check_env` — added only after a prod deploy (repo rule); the `platform_refusals` line follows the 02a-1 deploy rule in Implementation Decisions.
- A prod read audit of stored Platform keys — owner: never prod DB.
- `pnpm typecheck` in `scripts/run-tests.sh` — cut (D6); the drift tests and vitest scans cover key drift.
- Running a Live check — owner-only, against a real Fansly account (floor 2).
- Failing on `owner:` placeholders in the Lift table or KIND_VERDICTS — Phase 02h's final acceptance.
- Slop run — no volume or concurrency change; repo rule makes it opt-in.

## Further Notes
ASSUMPTION: Unknown platform is a Platform value, not an exception, so roster and sweeps keep listing the account (rung 4); overturned if the owner wants such accounts hidden.
ASSUMPTION: `platforms.get` maps the empty string to OnlyFans like None (rung 3, `accounts.get_platform` uses `or "onlyfans"`); overturned by a stored empty key that must refuse.
ASSUMPTION: the Unknown platform refusal is enforced in `client_pool.get`, `_make_client` and `_load_client`, covering every OnlyFans client load except the direct `from_account` call left to 02c (rung 5); overturned if 02c's spec moves that call here.
ASSUMPTION: `ensure_platform` on an Unknown account raises `PlatformCollision` (409) explicitly, before any Cell reservation, rather than overwriting the key (rung 4; rung 1 that the existing loop misses it, `accounts.py:291` iterates `platforms.ALL`); overturned by an owner repair flow.
ASSUMPTION: a target-less `PLATFORM_LIVE_CHECK` entry is inert with a warning (rung 4); overturned if a list-free method needs an account-wide grant.
ASSUMPTION: a `fan=` grant needs the Complete audience to be exactly that fan; `list=` binds list id, Completeness, and members ⊆ granted `fan=` targets (coordinator D1 + D9, rung 4); overturned by a lane that needs a two-fan check, or an owner-asked combined `list=<id>,fan=<id>` grant.
ASSUMPTION: send refusal reasons are `platform_lacks:tagged_users` / `platform_lacks:locked_text` as the tickets wrote, not `<method>:<branch>` (rung 2 for the strings, rung 3 for treating them as Lift-table rows); overturned by the plan renaming them.
ASSUMPTION: the auto co-tag branch refuses only when the send would really co-tag — derived `auto_tag`, `media_cotag.enabled()`, media present and `needs_cotag` (rung 1 for the predicate, `media_cotag.py:235-244`, `scheduled_send.py:43-59`; rung 4 for refusing it, ticket 12 item 5); overturned if Fansly ever co-tags text or the owner accepts untagged sends.
ASSUMPTION: mark unread, pin and unpin drop their `returns=` and raise, because only routes via `_platform_call` reach them (rung 1 grep, rung 4); overturned by a service caller that needs a quiet None.
ASSUMPTION: the live_check path is proven with a test-only Shim subclass and kind inside the test file, since no method is marked in 02a (rung 5); overturned if the plan names a first Live-check method for 02a.
ASSUMPTION: the OnlyFans control uses a recording client stand-in, not a stateful OnlyFans fake (rung 3, `_OF` in the gates test); overturned if a control row needs read-back.
ASSUMPTION: the Stateful fake lives beside the Fansly tests and is covered by its own test file (rung 3, `fansly/test_har_replay.py`); overturned by a shared fixtures package.
ASSUMPTION: the Lift-table test reads KIND_VERDICTS by `ast.literal_eval`, so the harness file stays a literal (rung 5); overturned if verdicts need computed keys.
ASSUMPTION: a Lift-table Reason cell may hold several backticked reasons (rung 3, parity doc "Blocked by group" rows); overturned by a one-reason-per-row rule.
ASSUMPTION: `platform_refusals` alerts on any `platform_unknown:` run and only reports `platform_lacks:` counts (rung 4); overturned by an owner threshold on lacks volume.
ASSUMPTION: the send and scheduled-send refusal tests live in a new `service/tests/test_send_refusal.py`, and the Live-check tests in `service/tests/test_live_check.py` (rung 6); overturned if the implementer folds them into existing files, in which case the Acceptance list follows.
ASSUMPTION: Acceptance includes `pnpm test:run` because ticket 11 requires it on every merge candidate, even with no app change (rung 2 for the rule); overturned by an app-free exemption.
ASSUMPTION: a Live-check grant binds account, method and target only; Branch eligibility is the caller's Branch gate before `live_check` (rung 5, no 02a caller); overturned if a lane needs one method granted per Branch, then the grammar gains a Branch field.
ASSUMPTION: the collector marks `env.source` instead of failing every env read on fallback, so existing env checks keep today's reading (rung 4); overturned if all env checks should go `unknown` on fallback.
ASSUMPTION: the interim Unknown-as-OnlyFans label until 02d is acceptable because every reachable Relay path refuses (rung 2 for the phase split, ticket 11 item 1; rung 4); overturned if a prod account carries an unknown key before 02d, which `platform_refusals` alerts on.

## Review
Reviewer: codex (blind + draft), 2026-11-27
- P1 alt 1 (Live check at caller, not Shim; keep broadcast guard) — **reject**: already the decision (story 5, Live-check bullet, Out of Scope 00 c); guard preservation now stated in the recorder bullet.
- P1 alt 2 (strict dispatch, explicit unknown display row; app OnlyFans fallback) — **partial**: UnknownPlatform-as-value already avoids roster/stats aborts (`chatters.py:631`, `of_stats_daily.py:233` skips non-OnlyFans); app fallback handled as in P2 M5.
- P1 missing 1 (`outcome` gives ok/done for `platform_unknown:`; validate before Cell reservation) — **accept**: `run_decide.py:144` only checks `PLATFORM_LACKS_PREFIX`; prefix bullet kept, `ensure_platform` now validates before `creator_reservations.admit` (`accounts.py:280-284`).
- P1 missing 2 (co-tag predicate undefined) — **accept**: `auto_tag` is derived at fire time (`scheduled_send.py:43,59`) and `cotags_for` gates on switch + `needs_cotag` (`media_cotag.py:235-244`); `send_refusal` takes `would_cotag`, story 24 and test table rewritten.
- P1 missing 3 (omitted target, Branch binding, WATCH evidence + env fallback) — **partial**: target-less stays inert (Contracts); Branch binding → caller's Branch gate + ASSUMPTION; WATCH fallback accepted (`remote_db.py:180-183` falls back to `os.environ`), `env.source` + executor-written refusal row added.
- P1 seam (routes + due job with Cells, exact deltas, `/group` falsifier) — **accept**: Seam 2 rewritten with Cells on, `x-op-id`, exact `send_ops`/job/Employee/request deltas, OnlyFans control.
- P1 falsifier (lane-specific effects, branch inventory, mutation) — **partial**: branch-specific effect required and reads/error rows excluded; mutation self-check added; no mechanical branch source exists, so branches are pinned to ticket 12's table on both literals.
- P2 B1 (list id as audience proves identity only) — **accept**: ADR 0070 requires a Complete read holding only the Fan, re-read before the write; `live_check` now takes fan ids only, list callers pass the fresh read; mismatch cases in the Live-check table.
- P2 B2 (job claimed before plugin; employee created before refusal) — **accept**: `automation_executor.py:567-571` claims first, `server.py:3207-3208` resolves the employee (insert path `employees.py:955-984`) before send; story 24 and route order rewritten, zero `send_ops` and Employee rows asserted.
- P2 M3 (co-tag misses legacy, overblocks) — **accept**: same change as P1 missing 2.
- P2 M4 (`require(FANSLY.key)` cannot see corrupt stored meta; reservation precedes check) — **accept**: `fansly_backend.py:109,126-128` pass the constant, `accounts.py:284` admits before reading meta, and `UnknownPlatform` is outside `platforms.ALL` so the collision loop misses it; stored-key check before admit and before the session write, with relink test.
- P2 M5 (Unknown shown as OnlyFans until 02d) — **partial**: 09 C stays in 02d (binding, ticket 11 item 1); interim stated as wrong label, no wrong write (every path refuses 501) + ASSUMPTION.
- P2 M6 (any-effect scoring, kind equality, `of_ai_chat` outside `registered_kinds()`) — **partial**: `of_ai_chat` accepted (`automation_registry.py:13-16,48-49`), story 27 fixed; effect and mutation parts as P1 falsifier; `priority_mass` may stay only `owner:04`, which 02h fails.
- P2 M7 (`send_mass_message` marked by assignment; callable success stand-ins) — **accept**: `fansly_shim.py:1910` assigns the attribute and `:1544,1812,1816` use `lambda: {"success": True}`; recorder covers it, callable `returns` raises at import.
- P2 M8 (WATCH false green) — **accept**: same change as P1 missing 3 WATCH part.
- P2 M9 (`!` under `set -e` does not fail) — **accept**: bash exempts `!` pipelines from `errexit`; both lines now `if …; then exit 1; fi`.
- P2 m10 (Depends on omits M0) — **accept**: M0 is a precondition under Depends on, cited in the PR body; the comment line left Acceptance.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- White · four grant shapes, split target, lanes vs stand-in attribute — **accept**: one grant API in Interfaces (`live_check_targets`, `live_check_methods`, `live_check` with `ListAudience`, `is_live_check_name`, empty `LIVE_CHECK_LANES`), grammar `fan=` / `list=` (D1); stories 1–2, Contracts and the Live-check table rewritten.
- Red · consumers' "if 02a lacks" ASSUMPTIONs — **accept**: every name a later Phase needs is defined here; 02b–02g cite them.
- Yellow · fail-closed refusals — **accept**: kept as is (no compose passthrough, check before side effect, OnlyFans control).
- Yellow · drift test + KIND_VERDICTS auditable — **accept**: kept; drift test gains route-only reasons and the digit strip.
- Green · one grant shape in `side_effect_gate` — **partial**: accepted with D1's names; six-hats' `granted_targets` is `live_check_targets`, its `grants()` is not added (`live_check_targets` + `live_check_methods` cover every reader); a `ListAudience` under `fan=` must equal `{fan}`, and `list=` stays only for `delete_list`.
- Blue · amend Interfaces/Testing; parameterised-reason rule and route-only source now — **accept**: D7; drift-test bullet and story 38.
- Blue · one codex draft review on the grant seam, then M0 — **reject** here: this step runs no network or model calls beyond the adversary already done, and M0 stays the 02a-1 implementer's precondition (Depends on).
- Recommendation · single grant module before the first Shim edit — **accept**: lives in `side_effect_gate`, lands in 02a-1.
- Coordinator D2 · split into 02a-1 (behaviour) / 02a-2 (tests and docs) — **accept**: "Two PRs, one spec" bullet with file lists; key strip + lower-case normalisation added to `platforms.get`; `platform_refusals` WATCH line at the first deploy containing 02a-1; no prod read audit.
- Coordinator D6 · one mutation self-check per harness — **accept**: the branch-drop mutation dropped; the `{}` swap stays.
Counts (plan review): accept 8 · partial 1 · reject 1 · needs-human 0.

