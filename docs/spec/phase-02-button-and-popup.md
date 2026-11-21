# Phase 02 — Button and popup (app)

**Objective.** On a Creator's Growth > Scripts page one press on "Fill with content" fills the open Sequence through
`fill/apply` and leaves a Fill notice with Undo; when a Fill cannot run, one Fill dialog says why and, for
`not_enough_content`, offers a Describe sweep to the Describe target, proven on the slop stack down to the fake send.

**Wave** (plan review, 2026-11-21): wave 3, with Phase 3b, after Phase 1b ships and the fit check passes. The
owner asked for the button and popup in the same message, so this Phase is not deferred (SH-6).

## Problem Statement
An agency's Sequences sit as text with no media and no prices, while the Creator's described vault sits unused one
page away. Attaching media by hand is a step-by-step editor job per Option, and nothing tells the chatter whether the
vault is described enough to fill a Sequence at all, or how to get it there.

## Solution
A "Fill with content" pill on the Sequence header, before "Add step". One press writes the Fill; the Sequence's cards
show the media and prices at once, under a notice "Added {n} items to {m} steps · Undo". When the server answers
anything but `ok`, a dialog opens instead: the describe offer (up to 1,000 items), live describe progress that
survives closing it, the server's refusal sentence, "Ready to fill" once a fresh Fill plan is `ok`, or the one reason
the Sequence cannot be filled and what to fix. Nothing fills itself after a describe: the user presses again.

## User Stories
1. As an owner, I want a "Fill with content" button on the open Sequence's header before "Add step", in the same pill style, so that filling sits where I build the Sequence.
2. As an owner, I want the button titled with the Inflowwww-extra label, so that I know it is ours, not Infloww's.
3. As an owner, I want one press to fill the Sequence with no preview step, so that the owner's one button stays one click.
4. As an owner, I want the cards to show the new media and prices as soon as the Fill lands, so that I see what was written without reloading.
5. As an owner, I want a notice on that Sequence reading "Added {n} items to {m} steps · Undo" ({n} distinct media ids written, previews included; {m} distinct Steps written), so that I know the size of the change and can take it back.
6. As an owner, I want Undo to clear exactly what the Fill wrote and keep a saved price the Fill did not set, so that a Fill I dislike costs nothing.
7. As an owner, I want Undo to leave a step whose media, previews or Fill-set price I changed after the Fill, or that I moved out of the Sequence or deleted, and tell me how many it left and why ("changed since the Fill" / "moved or deleted"), so that my edits are never wiped. A text-only edit does not protect the step's Fill media (ADR-0046 compares media, previews, price and membership only).
8. As an owner, I want the notice to stay until I dismiss it, switch Creator or reload, and to come back when I reopen that Sequence, so that browsing other Sequences does not lose my Undo.
9. As an owner, I want the notice to repeat the gap warning when the Sequence skips a step number, so that I know the chat's next-step suggestion stops there.
10. As an owner, I want the button busy while its Fill runs, so that a double press sends one request.
10a. As an owner, I want the button disabled with "Save or close the open step first" while I am editing an existing step of this Sequence, so that saving a stale draft (a whole-row PUT) never wipes a Fill.
10b. Cut in plan review (SH-5): no kept-steps line on the notice; kept Options stay visible in the editor.
11. As a folder-limited chatter, I want the button disabled with "Ask the owner: filling uses the whole vault", so that I know why I cannot use it.
12. As an owner in All creators, I want no Fill button, so that nothing writes to a Creator I am not looking at.
13. As an owner, I want Reserved sequences never to show the button, so that generated FM scripts are not filled.
14. As an owner, I want `not_enough_content` with describable items left to offer "Describe content first? … Describe up to 1,000 items for this Creator? {described} of {target} done." [Cancel · Describe content], so that I can fix the shortage from here.
15. As an owner, I want `not_enough_content` with nothing left to describe to say so with the described count and no Describe button, so that I am not offered a button that cannot help.
16. As an owner, I want "Describe content" to start describe-all with `target: 1000`, so that the Creator is brought up to the Describe target, not 1,000 more per press.
17. As an owner, I want a refused start (Describe cap, missing key, no whole-vault access, a role without the Vault Pro grant, any HTTP error) to show the server's sentence — the cap's `blocked_reason`, the key payload's message and fix, the role sentence — never raw JSON or an "HTTP 429" prefix, so that I know what to fix. Jev not ready reaches me as the plan's `blocked_reason` before any start (describe-all does not refuse on it, `vault_ai_vision.py:1070-1091`).
17a. As a Scripts-only chatter with whole-vault access, I want Fill to work and Describe to show "Your role does not allow Vault Pro", so that I know Describe needs the Vault Pro grant (issue 04 assumption).
18. As an owner, I want a start that hits an already running sweep to show that sweep's progress ("starting…" until its first snapshot), so that a second tab or a double press is not an error.
19. As an owner, I want "Checked {done} of {total}. Keeps going if you close this." with failures and the stop note while describing, so that I can leave and come back.
20. As an owner, I want the described count in the dialog taken from a fresh Fill plan, not from the sweep's `done`, so that failures are not counted as described.
21. As an owner, I want pressing Fill during a sweep to reopen the dialog on its progress (apply answers non-`ok` and writes nothing), and pressing it after the sweep to be the explicit press that fills when the plan is `ok`, so that progress survives closing the dialog and the one press still fills.
22. As an owner, I want a sweep that stopped early (breaker, key, server stop, death) to show its stop note after it settles, above the plan's state, and a cap stop to show the plan's cap sentence, with Describe offered again when items remain and nothing blocks, so that I can resume.
23. As an owner, I want "Ready to fill." [Fill with content] once the sweep settles and a fresh plan is `ok`, and never an automatic Fill, so that I decide when media is written.
24. As an owner, I want `no_fit` to say "No single set in this Creator's described content fits these steps.", with no describe offer, so that I do not describe in vain.
25. As an owner, I want `no_paid_steps` to say "No step in this sequence sells anything yet. Put a price on the steps that sell, then fill again.", so that I know the fix.
26. As an owner, I want `price_conflict` and `price_out_of_range` to name each step and rule ("Step 3 is priced below step 2", "Step 4: $2 is under OnlyFans' $3 minimum") and end "fix the price, then fill again", so that I can fix it in the editor.
27. As an owner, I want `already_filled` to say "Every step already has its content.", so that a re-press is explained, not silent.
28. As an owner, I want a `reserved` answer to get its own line, so that a server-side refusal is never a blank dialog.
29. As an owner, I want no dollar estimate or total in the dialog (a price-rule line may quote that step's own saved price, story 26), so that it never shows an estimate the plan does not return.
30. As an owner, I want an answer for another Creator or Sequence never to open a dialog or a notice over the one I am looking at, and a late `ok` only to refresh the cards, so that late answers cannot mislead me.
31. Cut in plan review (SH-5): a Fill that lands after I moved to another Sequence leaves no notice anywhere; its cards refresh and its Undo list is dropped.
32. As the owner, I want slop proof on the guarded stack: one-press Fill, DB read-back, the picker's fake send carrying media, free previews and PPV price, a second Creator with a same-named Sequence untouched, the describe offer settling without auto-fill, a blocked offer and a refused start each showing the cap sentence, and Undo restoring the cards, so that the feature is proven on the real path.
33. As the owner, I want the describe-sweep scenario to check `target` (zero work at the target, Terminal failures walked past), so that the 1,000 limit is proven where sweeps are.
34. As the owner, I want screenshots of the trigger, the filled cards with notice, the describe offer, reopened progress, the blocked offer, the cap refusal, Ready, and the restored cards after Undo, so that the UI proof is visible.

## Implementation Decisions
- **Owns.** `scriptFillState` (new reducer module beside the page) with its vitest; `ScriptFillDialog` (new, one
  `IfModal`); `ScriptsPage` (button, notice, dialog mount); `scriptsPageState` (one overlay entry); `useSavedReplies`
  (three fill hooks); `useVaultSweep` (`start` returns the refusal); relay types for the fill routes; the new slop
  scenario `script-fill` with its faults module, its vault seeder `slop/seed/script_fill_vault.py` and README entry;
  one `TARGET` check added to `vault-describe-sweep`.
- **Interfaces.**
  - `scriptsPageState`: `Modal` gains `{ kind: "fill"; sequence: string }`; opening it replaces any other overlay,
    and `reset` / `allModels` close it as they close the rest. No other change.
  - `scriptFillState`: `scriptFillReducer(state, action)` over typed actions `press {account, sequence, req}`,
    `applied {account, sequence, req, result}`, `answered {account, sequence, req, status, plan}` (any non-`ok`
    apply status), `failed {account, sequence, req, message}`, `describeRefused {account, sequence, req, message}`,
    `undoPress {account, sequence, req}`, `undone {account, sequence, req, result}`, `dismiss {sequence}`, `close`,
    `reset {account}`. Every async result carries the Creator, Sequence and request id it was made for and is
    dropped when the Creator differs or the request id is not the one in flight for that Sequence. State:
    `account`, the in-flight `req` per Sequence (Fill and Undo share it, so a Sequence runs one at a time), the
    open dialog's Sequence and last apply status or refusal, and `notices`, a map from Sequence name to
    `{undo, n, m}`. Pure helpers: `dialogFor({status, plan, sweep, refusal})` → the dialog's copy and
    buttons; `canDescribe(plan)`; `noticeCounts(applied)` → `{n, m}` (distinct media ids written, previews
    included, so Options of one Step sharing a Slice count once; distinct Steps); `conflictLines(options)` → one sentence per flagged
    Option; `undoPayload(notice)` → `{sequence, undo}` with apply's `undo` list passed verbatim (Phase 1
    `UndoEntry {id, media_ids, previews, price_cents, price_set}`: `price_cents` is the row's price after apply,
    always compared; `price_set: false` on a saved price the Fill did not set, so it survives Undo); `leftNote(result)` → counts of
    `kept` by reason (`edited` → "changed since the Fill", `moved` / `missing` → "moved or deleted");
    `refusalText(err)` → the sentence to show (below).
  - `useSavedReplies`: `useFillPlan(accountId, sequence, enabled)` (POST read under `["saved-replies", accountId,
    "fill-plan", sequence]`, `staleTime` 0, so every saved-replies invalidation refetches it, as `/sequences` does);
    `useFillApply(accountId)` and `useFillUndo(accountId)`, each invalidating `["saved-replies", accountId]` on
    success **and on error** (a committed write whose answer was lost still reaches the cards; the re-press then
    answers `already_filled`). A non-`ok` apply answer seeds the fill-plan query with its `plan` (`setQueryData`),
    so the dialog opens on it without a second read or a flash.
  - `useVaultSweep`: `start(body)` resolves to `null` when the sweep started, a met target answered zero work, or a
    409 says one is already running, else to `refusalText(err)`. Existing callers ignore the value; nothing else
    changes.
  - `refusalText(err)`: an `ApiKeyError` → its payload's `message` + " " + `fix`; a `RelayError` whose
    `body.detail.blocked_reason` is a non-empty string (the 429 `daily_cap_reached`, `vault_ai_vision.py:1061-1063`)
    → that sentence; `body.detail.error == "folder_not_allowed"` → "Ask the owner: filling uses the whole vault";
    any other `RelayError` → its `message` (the relay already flattens string details and `{error, message}`,
    `lib/relay.ts:131-166`, e.g. "Your role does not allow Vault Pro"); else "Could not reach the relay." Never
    `extractError`, which prefixes "HTTP n —" and JSON-dumps object details (`extractError.ts:5-15`).
- **Schema.** None — no migration (issue 04 item 11).
- **Contracts.** Phase 1's routes, account in the `account_id` query parameter on every Fill call:
  `POST /admin/saved-replies/fill/plan {sequence}` → `FillPlan`; `POST …/fill/apply {sequence}` (no fingerprint
  from the button) → `{status, plan, applied, undo}`; `POST …/fill/undo {sequence, undo}` → `{undone, kept:[{id,
  reason}]}`. Describe keeps its own wire: `POST /admin/vault-ai/describe-all` with `account_id` in the JSON body
  (`useVaultSweep.ts:213` merges it) plus `target: 1000` (`DESCRIBE_TARGET`), and `GET …/describe-all/status?
  account_id=`.
- **Press.** The button dispatches `press` with a fresh request id and calls apply; it is busy (disabled) while that
  Sequence has a request in flight. Every answer — `ok`, any other status, or an HTTP error — acts only while the
  same Creator, Sequence and request id are current: `ok` records the notice, the rest open the dialog. Otherwise it
  is dropped; `useFillApply` has already invalidated `["saved-replies", accountId]`, so the cards of the Sequence it
  wrote refresh when shown, and that Fill's Undo list is gone (as after a lost response, ADR-0046). A press during a sweep runs apply like any press; its non-`ok` answer opens the dialog, whose running
  sweep wins the precedence below.
- **Editor guard.** The button and the notice's Undo are disabled, titled "Save or close the open step first", while
  the page's draft edits an existing row of this Sequence (`draft.id` among the Sequence's row ids); a new-step
  draft does not block. If an edit draft is opened on a touched row while a Fill or Undo is in flight, the answer
  closes that draft (`setDraft(null)`) so its stale media, previews and price cannot be saved over the write.
- **Dialog states** come from `dialogFor`, precedence: a refusal sentence; sweep running → describing ("Checked
  {done} of {total}. Keeps going if you close this." with counts and the failure / first-error lines from
  `describeSweepText`, "starting…" before the first snapshot); otherwise the fresh Fill plan's status, with the
  settled `sweepAbortedNote` line (stop, key, death, or recent failures) above it when present. A cap stop is
  covered by the plan: its `blocked_reason` is then the cap sentence. `not_enough_content` maps by the plan's
  `describe`: `remaining > 0` and `can_describe` → offer; `remaining > 0` and a `blocked_reason` → that sentence;
  `remaining == 0` → nothing left. Plan `ok` after this dialog started a sweep → "Ready to fill." whose button runs
  the same press path. `reserved` → "This sequence is generated by a script source and is not filled." All other
  copy is issue 05 item 3 verbatim.
- **Sweep wiring.** The dialog mounts `useVaultSweep({kind: "describe-all", accountId, settleKeys: [fill-plan key,
  ["vault-describe-plan", accountId]]})`; the fill plan query is enabled while the dialog is open, so opening and
  reopening read a fresh plan (`staleTime` 0). The settle edge fires only on an observed running → idle change
  (`useVaultSweep.ts:185-198`), so after `start` resolves `null` the dialog also invalidates the fill-plan key: a
  zero-work answer, or a sweep that ended between polls, still reaches readiness.
- **Price lines.** `conflictLines` reads prices from the plan's Options (Fixed and planned). A flagged Option with a
  Fixed price → "Step {j} is priced below step {i}" (i = nearest earlier Step whose price is higher) or, for
  `price_out_of_range`, "Step {j}: ${amount} is under OnlyFans' $3 minimum" / "is over the $200 cap"; a flagged unpriced
  Option (its earlier floor above a later Fixed ceiling) → "Step {i} is priced above step {k}" (i = the earlier
  Step setting the floor, k = the later Fixed Step). Each line ends "fix the price, then fill again".
- **Access.** Disabled state reuses Vault's reading: `dlAccess(useChatterFolderAccess(accountId))`; `"folders"` or
  `"unknown"` disables the button with the "Ask the owner" title (house: the vault download gate waits on unknown).
  A role without the Vault Pro grant is not detected client-side: Fill works, Describe shows the middleware's
  sentence through `refusalText` (`service/permissions.py:403-407`, issue 04 assumption).
- **Hidden cases need no code.** All creators renders `AllModelsView` instead of the list, so the header is never
  drawn (`ScriptsPage.tsx:438`); the page's rows already drop script-source Sequences
  (`components/settings/TemplatesTab.tsx:55`), so a plugin-source Sequence never reaches the header. Where no
  script source is installed (`lib/chatSlots.ts:102-104`), an `FM<digits>` Sequence shows the button and the
  server's `reserved` answer gets its line.
- **Gap.** The notice appends the page's existing gap sentence from `firstGap` when the Sequence has a gap.
- **Notice.** "Added {n} items to {m} steps · Undo", then the gap sentence. Plan flags (`kept_existing`,
  `kept_unpriced`, `removed_media`, `free_unfilled`) are not shown; the editor shows those Options as they are.
- **Undo.** Notice "Undo" dispatches `undoPress` and posts `undoPayload`; `undone` clears the notice; if rows were
  left, a one-line note on the Sequence gives `leftNote`'s counts. Dismiss (×) drops the notice and its Undo list.

## Testing Decisions
- **Seam 1, `scriptFillState` vitest table** (repo reducer rule): action sequences → state, and `dialogFor` per
  status × describe block × sweep state (running, settled with each `sweepAbortedNote` kind, none) × refusal;
  late `answered` / `failed` / `describeRefused` / `undone` for another Creator, Sequence or request id dropped;
  `applied` for a non-open Sequence dropped; second `press` while one is in flight ignored; `reset` clears notices;
  `conflictLines` per flag shape (Fixed descend, floor over a later Fixed ceiling, under $3, over $200);
  `noticeCounts` with two Options sharing a Slice; `leftNote` per reason; `undoPayload` passes each entry's
  `price_cents` and `price_set` verbatim; `refusalText` table (424 key payload, 429 with `blocked_reason`, 403 `folder_not_allowed`, 403
  role string, 500 string, network error).
- **Seam 2, `ScriptsPage.test.tsx`** (relay mocked with deferred answers, two Creators, existing harness): button
  before "Add step" with `EXTRA_LABEL`; double press while apply is pending → exactly one POST `fill/apply` with
  `account_id` and `{sequence}`; notice text with counts and gap sentence; switch to another Sequence and
  back → notice still there; an apply answered after switching Sequence → no dialog, no notice on either Sequence,
  saved-replies refetched;
  Undo → POST `fill/undo` with the returned list verbatim, left note shown; `not_enough_content` → offer → POST
  describe-all body `{account_id, target: 1000}`; 429 with `blocked_reason` → that sentence, not JSON; 403 role
  string → that sentence; `reserved` answer → its line; open edit draft of a row in the Sequence → button disabled
  with "Save or close the open step first"; restricted chatter → disabled with the title; All creators → no button.
- **Seam 3, `useVaultSweep.test.tsx`**: `start` resolves `null` on 200 (running and zero-work `done`) and 409, the
  `refusalText` sentence on 429 / 424 / 403; existing callers' behaviour unchanged.
- **Seam 4, slop `script-fill`** (guarded stack, fake describe and Jev arms, two Creators holding a same-named
  Sequence). Its own seeder `slop/seed/script_fill_vault.py` writes Shoots Phase 1 can fill — solo readings
  (`people_count` 1, `partner_visible` false, which `vault_flags_partial` / `vault_ai_sets` omit, so
  `sellability().solo` is None there, `service/vault_ai_brief.py:580-589`), Rungs, a folder price, free-safe
  stills — plus decoys that rank first in the winning Shoot but are not Fillable (partner, Jev-held, REVIEW folder).
  Checks: `FILL_ONE_PRESS` (UI press → cards show media, notice shown), `FILL_READ_BACK` (every written media id a
  Fillable item of that Creator, no decoy, prices only on Options saved at 0, timestamps bumped only on written
  rows), `FILL_SEND` (picker → fake send of a free and a paid step; the fake's recorded send body
  (`slop/lib/of_wire.py` `fake.sends[…]["body"]`) carries the written media ids, the free previews and the PPV
  price, no decoy), `FILL_ISOLATION` (second Creator's rows byte-equal), `FILL_UNDO` (rows back to empty, saved
  prices kept, cards restored), `DESCRIBE_OFFER` (short vault → offer → sweep → Ready, zero fill writes until
  pressed), `DESCRIBE_BLOCKED` (valid key, describe cap row at the cap before the dialog opens → the plan's cap
  sentence, no Describe button, zero describe-all POSTs), `DESCRIBE_REFUSED` (cap row written after the offer
  renders, before the press → POST 429 → `blocked_reason` shown, no JSON). `FAULT` `script-fill-skips-eligibility`
  (Phase 1's `fillable` patched to pass everything in the throwaway relay) targets `FILL_READ_BACK` and
  `FILL_SEND`: the decoys make both flip. Screenshots by `ui.shot` per story 34. `vault-describe-sweep` gains
  `TARGET`.
- Prior art: `scriptsPageState.test.ts`, `fanDrawerForm.test.ts`, `ScriptsPage.test.tsx`, `useVaultSweep.test.tsx`;
  slop `2026-11-06-scripts-library.py` (`UI_SEND`), `2026-11-01-vault-describe-sweep.py`, `2026-11-11-ai-daily-cap.py`.

## Acceptance
```sh
set -euo pipefail
nice -n 10 sh -c 'cd app && pnpm typecheck && pnpm lint && pnpm exec vitest run \
  components/growth/scriptFillState.test.ts components/growth/scriptsPageState.test.ts \
  components/growth/ScriptsPage.test.tsx hooks/useVaultSweep.test.tsx && pnpm test:run'
# slop runs go through the slop-runner agent
slop/run script-fill --scale=small
GREEN="$(ls -td slop/evidence/*-script-fill-* | grep -v -- -break- | head -1)"   # the folder that run just wrote
slop/run script-fill --break --baseline="$GREEN"          # must print CAUGHT
slop/run vault-describe-sweep --scale=small
DESCRIBE="$(ls -td slop/evidence/*-vault-describe-sweep-* | grep -v -- -break- | head -1)"
# every check PASS, none SKIP (a SKIP leaves the run at exit 0, slop/lib/report.py:70-73)
python3 - "$GREEN/invariants.json" "$DESCRIBE/invariants.json" <<'PY'
import json, sys
want = [{"FILL_ONE_PRESS", "FILL_READ_BACK", "FILL_SEND", "FILL_ISOLATION", "FILL_UNDO",
         "DESCRIBE_OFFER", "DESCRIBE_BLOCKED", "DESCRIBE_REFUSED"}, {"TARGET"}]
for need, path in zip(want, sys.argv[1:]):
    checks = json.load(open(path))
    bad = [c["name"] for c in checks if c["status"] != "pass"]
    missing = need - {c["name"] for c in checks}
    if bad or missing:
        sys.exit(f"{path}: not pass {bad}, missing {sorted(missing)}")
PY
slop/run --changed
# manual: owner opens $GREEN's screenshots (trigger, filled + notice, offer, progress, blocked, refusal, ready, undo)
```

## Depends on
- **Phase 1b — Fill engine** (and 1a's describe-all `target`, already shipped in wave 1): `fill/plan`,
  `fill/apply` (with `plan` in its non-`ok` answer), `fill/undo`. Seams 1–3 run against mocks without it; seam 4 and the `TARGET`
  check need it landed.
- Existing, unchanged: the Vault Pro grant on `/admin/vault-ai` (`service/permissions.py:403-404`) and
  `assert_owner_scope` on describe-all — story 17a shows their refusals; nothing in this Phase changes them.

## Out of Scope
- A preview before applying — owner's one button (issue 05 item 2); the plan route already serves one if overturned.
- A dollar estimate in the dialog — issue 05 item 3 supersedes issue 03 item 5's "popup shows the estimate".
- Undo after a reload or an "undo last fill" list — ADR-0046.
- Folder-scoped Fill for chatters — Whole-vault access only in v1 (issue 03 item 6).
- Writing step text, keeping media from repeating across Sequences — map "Not yet specified".
- Any change to the Vault Pro describe button, the describe recipe or walk order — map Out of scope.
- The rollout driver, journal and watch checks — Phase 3.
- A separate demo-shots capture — `ui.shot` in the slop scenario is the screenshot proof (rung 5).

## Further Notes
Decided (rung 2, issue 05 item 4 "a late answer for another sequence is dropped", plus coordinator ruling 5): a
late `ok` for a Sequence not in view is dropped with its Undo list; only the cache invalidation reaches it.
ASSUMPTION: the dialog reads describe counts and readiness from the fill-plan query, seeded from apply's non-`ok`
`plan` and refetched on open, reopen, `start` and the settle edge (rung 5: one cache entry, no second read on
open). Overturned if Phase 1 drops `plan` from the non-`ok` apply answer; then the dialog reads `fill/plan`.
ASSUMPTION: `conflictLines` reads Fixed and planned prices from the plan's Options and names Steps by the rule in
Price lines (rung 5). Overturned if the Phase 1 build puts the Step pair and rule in the flag itself.
ASSUMPTION: the undo reply is Phase 1's `{undone, kept:[{id, reason}]}`; the app shows counts by reason only.
ASSUMPTION: `reserved` copy reads "This sequence is generated by a script source and is not filled." (rung 5).
ASSUMPTION: access `"unknown"` disables the button like the vault download gate (rung 3). Overturned if owners see a
flash of disabled; owners never load the query, so access reads `"all"` at once for them.
ASSUMPTION: the editor guard disables Fill and Undo while an existing-row draft of the Sequence is open, and closes
a touched draft opened mid-request (rung 4: losing an unsaved draft opened in that second beats a whole-row PUT
silently wiping the Fill). Overturned by the owner preferring the draft be refreshed in place.
ASSUMPTION: the scenario file is dated the day it lands (`slop/scenarios/<YYYY-MM-DD>-script-fill.py`, README rule),
is picked by the substring `script-fill`, and its evidence folder matches `*-script-fill-*` (house naming,
`slop/evidence/<stamp>-<scenario>-<hash>`).
ASSUMPTION: the scenario gets its own seeder because the existing vault seeders write no solo reading (rung 1
observation; rung 5 for a new file over widening shared seeders other scenarios pin). Overturned if Phase 1 treats
`solo` None as solo.

## Review
codex — 2026-11-21. Blind call (B1–B12) and draft call (D1–D12), `codex exec` high effort, sparse workspace.

- B1 three click flows; direct apply needs refusal detail — **partial**: one press is owner-binding (issue 05 item 2
  supersedes issue 03 item 3's preview); apply's non-`ok` answer carries `plan` (Phase 1 contract), now seeded into
  the fill-plan query (Interfaces, `useSavedReplies`).
- B2 one describe contract; Terminal failures; estimate conflict — **reject**: settled — goal = min(target,
  Describable − Terminal failures) is Phase 1's; estimate dropped in Out of Scope (issue 05 supersedes 03 item 5).
- B3 three permission cases incl. Scripts-only role — **accept**: story 17a, Access names the Vault Pro case,
  seam 2 403 role string, Depends on lists the existing grant.
- B4 409-before-snapshot, 4xx, zero work, between-poll finish, restart — **accept**: Sweep wiring invalidates the
  fill plan after `start`; `start` treats zero-work as `null`; seam 3 covers 200 `done`; restart reads the plan.
- B5 Undo zeroes a Fixed price — **partial**: Phase 1's `UndoEntry` null price already keeps it; `undoPayload` now
  passes the list verbatim, story 6, seam 1 and `FILL_UNDO` assert the saved price stays.
- B6 double press, A→B→A, lost response strand Undo — **accept**: per-Sequence in-flight id shared by Fill and Undo,
  notices keyed by Sequence (seam 2 switch-and-back), apply/undo invalidate on error so cards reconcile; the lost
  Undo after a lost response is ADR-0046's accepted cost.
- B7 stale editor overwrites a Fill — **accept** (verified `TemplatesTab.tsx` save sends media, previews, price):
  Editor guard section, story 10a, seam 2.
- B8 kept flags, `reserved`, shared-bundle counts — **accept**: Notice kept line + `keptCounts`, story 10b;
  `reserved` line was already there; `noticeCounts` counts distinct media ids.
- B9 test at the relay boundary with deferred answers — **partial**: seam 2 now uses deferred answers for double
  press and late answers; hooks stay real in the page test, reducer tables stay the unit seam.
- B10 prove at the fake's wire — **partial**: issue 04 item 13 names a new `<date>-script-fill.py`; kept, reusing
  `UI_SEND`'s picker path; `FILL_SEND` now reads `fake.sends[…]["body"]` (`of_wire.py:690-699`).
- B11 falsify the describe premise by paired plans — **reject** for this Phase: the Shoot-fit rate is measured by
  Phase 3's canary (issue 06); `DESCRIBE_OFFER` proves the path, not the AE rate.
- B12 falsify direct apply with operator review — **reject**: owner-binding one press; the ASSUMPTION in issue 05
  stands with the plan route as the fallback.
- D1 reopening fills immediately after a sweep — **partial**: a header press after the sweep is the explicit press
  issue 05 asks for (one press fills); story 21 rewritten so "reopen" covers only a running sweep.
- D2 keeping late `ok` and missing request ids contradict issue 05 — **partial**: request ids added to
  `describeRefused` / `undone` / `undoPress` and every answer pinned; a late `ok` stays stored under its own
  Sequence, never shown over another (ASSUMPTION, rung 4 — Undo of a real write).
- D3 cap test misses the refused POST; `extractError` shows JSON — **accept** (verified 429 detail has no
  `message`, `relay.ts:150-162` JSON-dumps it): `refusalText`, `DESCRIBE_BLOCKED` vs `DESCRIBE_REFUSED`, seam 1/2.
- D4 stop note vanishes on settle — **accept**: precedence now shows the settled `sweepAbortedNote` above the plan
  state; a cap stop surfaces as the plan's `blocked_reason` (`vault_sweep.py:196-197` sets only `capped`).
- D5 describe wire differs; mount omits `accountId` — **partial**: `start` already puts `account_id` in the JSON
  body (`useVaultSweep.ts:213`); mount now passes `accountId`, Contracts state both wires, seam 2 asserts the body.
- D6 Undo overpromises; `kept` includes moved/missing — **accept**: story 7 rewritten to ADR-0046's compared fields;
  `leftNote` splits "changed since the Fill" / "moved or deleted".
- D7 price helper cannot name generated-floor conflicts; story 29 vs 26 — **accept**: Price lines read Fixed and
  planned prices, floor-over-ceiling wording; story 29 allows a step's own saved price.
- D8 Vault Pro grant missing — **partial**: not a Phase dependency (existing, unchanged); listed under Depends on as
  existing, with story 17a and a seam 2 case.
- D9 seeds yield `solo=None` — **accept** (verified `vault_flags_partial.py:30-50` writes no `people_count`;
  `vault_ai_brief.py:580-589`): own seeder with solo readings and non-Fillable decoys so the FAULT flips both checks.
- D10 stories without seams (double press, reopen notice, gap, reserved) — **accept**: seam 2 additions.
- D11 green with skipped checks; `--break` flips two — **accept**: Acceptance asserts every named check `pass` in
  both runs' `invariants.json` (`report.py:70-73` passes SKIPs); the FAULT's two targets stay the bug class it claims.
- D12 placeholder parse error; no fail-fast — **accept**: `set -euo pipefail`, `$GREEN` derived from the run's
  folder; block passes `bash -n` and `zsh -n`.

### Six hats (plan review, 2026-11-21)

Reconciled from coordinator rulings on the six-hats report (`/tmp/sfc-sixhats.txt` was absent when this pass ran;
bullets named by ruling). Set-level lines: `docs/spec/plan-review-script-fill-content.md`.

- SH-1 Undo contract drifts between Phases (this spec relied on a null `price_cents`) — **accept** (ruling 1):
  `undoPayload` passes Phase 1's `UndoEntry {id, media_ids, previews, price_cents (after apply), price_set}`
  verbatim; null-price wording removed from Interfaces and Seam 1. Supersedes B5's "null price already keeps it".
- SH-2 order — **accept** (ruling 2): this Phase is wave 3, after 1b and the fit check; Depends on names 1b.
- SH-5a late `ok` kept under a Sequence not in view is machinery for a rare case — **accept** (ruling 5): dropped
  like every other late answer, cards refreshed by invalidation, Undo list lost; story 31 cut, story 30 widened,
  Press, Seam 1 and Seam 2 rewritten, ASSUMPTION replaced by a rung-2 decision (issue 05 item 4). Supersedes D2's
  late-`ok` half.
- SH-5b kept-line notice — **accept** (ruling 5): story 10b cut, `keptCounts` and the notice's second line removed,
  ASSUMPTION removed. Supersedes B8's kept-line half; `noticeCounts` and `reserved` stay.
- SH-5c editor guard — **reject** the cut (ruling 5 keeps it): a whole-row PUT from a stale draft silently wipes a
  Fill (verified under B7); story 10a and the guard stay.
- SH-6 defer Phase 2 entirely — **reject** (ruling 6): the owner asked for the button and popup in the same message
  (map ## Notes, owner's words).
- SH-7 story count — **partial** (ruling 7): only stories 10b and 31, which the cuts remove, are cut; numbering kept.
