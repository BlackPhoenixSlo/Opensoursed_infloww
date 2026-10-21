# Phase 05 — OF settings writes with known bodies

**Objective.** In Single-Creator scope, the tracking-link and trial-link modals under OF settings > Subscription create a link through the Relay with a Known body. The promotion modal's "Start campaign" and the bundle modal's "Save" send nothing and show the Read-only note. The subscription price Save and the row kebab deletes send nothing, and get their Read-only note from Phase 6's click fallback; every other settings control keeps today's note.

## Problem Statement

An agency manager opens a Creator's OF settings > Subscription in the OF mirror, opens "Create new tracking link" or "Free trial link", fills in the modal and clicks Create. Nothing happens. A form may even reload the frame. In Infloww's OF Manager the same click creates the link on the Creator's OnlyFans account. The Relay can already create both (`POST /api/of/v2/campaigns`, `POST /api/of/v2/trials`), so the manager has to leave Inflowwww to do something the backend already supports. Some modals have no Known body ("Start campaign" on the free-trial promotion, the bundle "Save"). Today those buttons are Silent controls, so the manager can't tell a broken button from one that isn't supported.

## Solution

With a single Creator selected:

- **Tracking link.** "Create Link" turns on once a name is typed. Clicking it creates the link and goes back to the Tracking links tab.
- **Free trial link.** The Offer limit, Offer expiration and Free trial duration dropdowns open OnlyFans's own option lists. The visible choice is what gets sent. "Create link" creates the link and goes back to the Trial links tab.
- **Invalid modal.** An empty name or an option with no Known value sends nothing and shows a validation note next to the button.
- **Relay error.** A red `Could not create: <message>` note appears and the modal stays open.
- **Read-only buttons.** "Start campaign" (promotion modal) and the bundle modal's "Save" send nothing and show "Read-only in Inflowwww for now".

With all Creators selected, Create sends nothing and shows "Select a model to save changes". The read-only buttons keep the Read-only note.

## User Stories

1. As a manager with one Creator selected, I want to type a tracking link name and click "Create Link", so that the link is created on the Creator's OnlyFans account without leaving Inflowwww.
2. As a manager, I want "Create Link" to stay disabled until the name has non-blank text, as on OnlyFans, so that I can't create a nameless link.
3. As a manager, I want Enter in the tracking link name field to act like "Create Link", so that the frame never reloads from a native form submit.
4. As a manager, I want the trial link modal to send the name, offer limit, free trial duration and (when one is chosen) the expiration I see, so that the link matches what I picked.
5. As a manager, I want the trial link dropdowns to open OnlyFans's own option lists and to show my pick, so that I can choose the limit, expiration and duration.
6. As a manager, I want the dropdowns to show the captured selected option when the modal opens, not the scrubbed fake number, so that what I see is what will be sent.
7. As a manager, I want an empty trial link name to give "Enter a trial link name" and send nothing, so that I fix the form instead of getting an OnlyFans 400.
8. As a manager, I want an option with no Known value ("No limits" for the offer limit; "1 month", "3 months" or "6 months" for the duration) to send nothing and show a note saying that option is read-only, so that nothing guessed reaches OnlyFans.
9. As a manager, I want "No expiration" to create a link with no expiry, so that the default OnlyFans choice works.
10. As a manager, I want a successful create to follow the modal's own Cancel link back to its tab and refresh our OF settings queries, so that I land where OnlyFans would put me.
11. As a manager, I want a Relay error to show `Could not create: <message>` in red, re-enable the button and keep my input, so that I can retry.
12. As a manager, I want the button disabled while a create is in flight, so that a double click doesn't create two links.
13. As a manager, I want "Start campaign" on the promotion modal to show the Read-only note and send nothing, because the captured modal is the free-trial tab with no discount field and the Relay requires a discount.
14. As a manager, I want the bundle modal's "Save" to show the Read-only note and send nothing, because the Relay needs a price the modal doesn't have.
15. As a manager, I want editing the promotion modal's fields to keep giving the Read-only note (as today), so that it's clear nothing is saved.
16. As a manager with all Creators selected, I want "Create Link" or "Create link" to send nothing and show "Select a model to save changes", so that I never write to an unintended account.
17. As a manager with all Creators selected, I want the read-only buttons to show the Read-only note, so that they never stay silent.
18. As a manager, I want the stream schedule form to behave exactly as before, so that the generalisation breaks nothing.
19. As a manager, I want the subscription price Save, row kebab deletes and all other settings controls to stay read-only (as today), so that no unknown body is sent.
20. As a maintainer, I want one Mirror check that asserts the exact method, path, `X-Account-Id` and JSON the mocked Relay got for each wired modal, so that a recapture that moves a selector fails loudly.

## Implementation Decisions

- **Owns.** `ofMirrorWrites` (the `SUBMITS` table, `bindWrites`, `useOfWrites`, new collectors); its vitest file; the new Mirror check `settings_writes`; the check README; the OF settings row in `docs/routes.md`.

- **Interfaces.**
  - `SUBMITS` changes from page -> button selector to page -> `Submit`.
  - `Submit` is `{ button, collect, send, then }`:
    - `button`: the selector of the submit button.
    - `collect(doc, now)`: returns the body or a validation-note string.
    - `send`: the Relay path, always POST.
    - `then(doc)`: returns the href to navigate to after success.
    - An optional `invalidate` lists the query keys to refresh.
  - Entries:
    - `streaming/dashboard/create`: `collectStream`, `/api/of/v2/streams`, then `QUEUE`. Behaviour is unchanged.
    - `settings/subscription/tracking-links/modal-1`: `collectTrackingLink`, `/api/of/v2/campaigns`, then the modal's Cancel href.
    - `settings/subscription/trial-links/modal-1`: `collectTrialLink`, `/api/of/v2/trials`, then the modal's Cancel href.
  - This Phase owns the `ofMirrorWrites` key change for both tables. `useOfWrites` passes `bindWrites` the page's full path under `of-mirror/pages`. `SUBMITS` is keyed by that full path. `WRITABLE` keeps its settings-relative keys and is looked up only for `settings/` paths, after stripping that prefix and any `/state-*` suffix. Phase 6 widens binding to every page on these keys and changes none.
ASSUMPTION: rung 2 for the order (the plan puts the `SUBMITS` rework in Phase 5, before Phase 6) and rung 5 for a single owner of the key scheme. Overturned if Phase 5 lands without the change, in which case Phase 6 makes it.
  - New `READ_ONLY_SUBMITS: Record<page, selector>`:
    - `settings/subscription/promotion-campaign/modal-1`: "Start campaign", `.modal-footer button[type='submit']`.
    - `settings/subscription/promotion-campaign/modal-2`: bundle "Save", `.modal-footer button`.
  - `WriteHandlers.scheduleStream` is replaced by `submit(path, body)`. The handler POSTs with the scope's `accountId`, and success invalidates the entry's keys. Stream invalidates nothing (as today). The two link modals invalidate `["of-settings"]`.
  - New exported pure collectors `collectTrackingLink(doc)` and `collectTrialLink(doc, now)`, plus `optionOf(doc, label)`. `optionOf` returns the selected option's title of the dropdown whose `label.v-label` text equals `label`.

- **Schema.** None (no storage).

- **Contracts.** The Relay bodies are used exactly as they stand (no Relay change):
  - **Tracking link.** `POST /api/of/v2/campaigns {name}`. `_TrackingLinkBody`, server.py:6814. Name is verified live at of_client.py:2135-2145. `code` is never sent.
  - **Trial link.** `POST /api/of/v2/trials {name, subscribe_days, subscribe_counts, expired_at?}`. `_TrialLinkBody`, server.py:6835. `expired_at` is omitted for "No expiration" (of_client.py:2166 only sends it when it is set).
  - Every write carries the selected Creator's `X-Account-Id` (relay client `accountId`).

- **Measured label map.** Taken from the committed pages under `app/public/of-mirror/pages/settings/subscription/`.

  | Modal | Label text (exact) | Control | Body field / verdict |
  |---|---|---|---|
  | tracking-links/modal-1 "Create new tracking link" | Tracking link name | `input[name='name']`, maxlength 100, required | `name` (trimmed, non-empty) |
  | tracking-links/modal-1 | — | `.modal-footer button[type='submit']` "Create Link" (captured `disabled`) | submit |
  | trial-links/modal-1 "Free trial link" | Trial link name | `input` (no name attribute), maxlength 64 | `name` (trimmed, non-empty) |
  | trial-links/modal-1 | Offer limit | dropdown: No limits, 1 subscriber … 10 subscribers (captured selection), 50, 100 subscribers | `subscribe_counts` = N; "No limits" has no Known value, so a note |
  | trial-links/modal-1 | Offer expiration | dropdown: No expiration, 1 day … 7 days (captured selection) … | `expired_at` = `localIso(now + N days)`; "No expiration" omits it |
  | trial-links/modal-1 | Free trial duration | dropdown: 1 day, 3 days, 7 days (captured selection), 14 days, 1 month, 3 months, 6 months | `subscribe_days` = N for "N day(s)"; months give a note |
  | trial-links/modal-1 | — | `.modal-footer button[type='submit']` "Create link" | submit |
  | promotion-campaign/modal-1 "Promotion campaign for" | audience tabs New subscribers / Expired subscribers / Both new and expired; offer tabs Free trial (captured current) / First month discount | buttons | `type`: no measured mapping |
  | promotion-campaign/modal-1 | Offer limit; Offer expiration; Free trial duration; Message (optional) | dropdowns (state pages `state-promo-dropdowns-0..2`) and textarea | `subscribe_counts`, no `_PromoBody` field, `subscribe_days`, `message` |
  | promotion-campaign/modal-1 | (no discount input in the capture) | — | `_PromoBody.discount` is required, 1-100 (server.py:6792), so **the modal stays read-only** |
  | promotion-campaign/modal-2 "Add subscription bundle" | Discount percent; Discount duration | dropdowns | `_BundleBody.price` is required (server.py:6770) and there is no price input, so read-only |

- **Selected value source.** The scrubber replaces visible numbers with fakes, so the modal's `.v-select__selection` text is not trusted (the trial modal shows "12 subscribers", which is not an option). The selected value is the title of the `[role=option][aria-selected=true]` in the listbox that the slot's `aria-owns` names. That title matches the hidden input's unscrubbed `value` (10, 7, 7). On bind, each dropdown's visible selection is rewritten to that title. The number parsing accepts "N subscriber(s)" and "N day(s)", and nothing else. Every sendable option (1-100 subscribers, 1-14 days) is inside the Relay's bounds (`subscribe_counts >= 1`, `subscribe_days` 1-365, server.py:6835-6840), so no range note is needed.

- **Trial dropdown picker** (runtime DOM, ADR-0006).
  - A click on a trial modal dropdown's `.v-input__slot[aria-owns]` shows that listbox's `.v-menu__content`, which is captured with `display:none`. The menu is placed under the slot from its bounding rect, and the slot's `aria-expanded` is set.
  - A click on an option moves `aria-selected=true` to it, writes its title into the selection, and closes the menu.
  - A click elsewhere closes it.
  - Only `trial-links/modal-1` gets this. The promotion modal keeps its state-page links.

- **Submit flow.** The existing stream path, generalised:
  - **Clicking the button.**
    1. `preventDefault`.
    2. With no single Creator selected, nothing is sent and the button shows `SELECT_MODEL`.
    3. A disabled button does nothing.
    4. A `collect` result that is a string is shown as a red note.
    5. Otherwise the button is disabled, the note is cleared, and `submit(send, body)` is called. On success the page navigates to `then(doc)`. On error the button is re-enabled and the red note reads `Could not create: <message>`; the stream keeps `Could not schedule: <message>`.
  - **Native form submit.** A `submit` event from any form on a `SUBMITS` or `READ_ONLY_SUBMITS` page is prevented. On a `SUBMITS` page it runs the same path as the button.
  - **Enabling the button.** On `input`, a `SUBMITS` page whose button is captured `disabled` (tracking link) has the button re-enabled when `collect` returns a body, and disabled again when it doesn't.
  - **Field changes.** These never show the Read-only note on a `SUBMITS` page (as today for the stream form).

- **Read-only submits.** A click on a `READ_ONLY_SUBMITS` button calls `preventDefault`, sends nothing and shows `READ_ONLY`, in both scopes. Field changes on those modals keep today's `READ_ONLY` note in single scope.

- **Not touched here.** The subscription price Save and the row kebab deletes are not intercepted in this Phase. Today a click on them gives no note; the click fallback that Phase 6 adds gives them the Read-only note.

## Testing Decisions

There are two seams, both required by the plan's Check loop.

1. **`bindWrites` and the collectors in `ofMirrorWrites.test.ts` (vitest + jsdom).**
   - Runs on the committed pages, loaded the way the existing `loadPage` does, with mocked handlers.
   - **Tracking.** Valid name gives `{name}`. Blank name keeps the button disabled and sends nothing. Enter in the field calls `submit` once and doesn't navigate the document.
   - **Trial, defaults.** After bind, each dropdown's visible selection reads the captured option title ("10 subscribers", "7 days", "7 days"), not the scrubbed fake ("12 subscribers"). Sends `{name, subscribe_counts: 10, subscribe_days: 7, expired_at: localIso(now+7d)}`.
   - **Trial, picks.** Picking "No expiration" omits `expired_at`. Picking "50 subscribers" or "14 days" changes the body.
   - **Trial, notes.** An empty name gives its note. "No limits" and "1 month" each give their note and send nothing.
   - **Promotion and bundle.** "Start campaign" and bundle "Save" show `READ_ONLY` and send nothing. Changing the promotion modal's Message textarea in single scope shows `READ_ONLY` (story 15).
   - **All Creators** (handlers null). Both Creates show `SELECT_MODEL`.
   - **Errors and success.** A Relay rejection shows `Could not create: <message>` and re-enables the button. Success navigates to the Cancel href. A second click while the first `submit` is pending calls `submit` once (story 12).
   - **Stream.** The existing stream tests pass, with the handler renamed to `submit`.
   - **Tables.** The `SUBMITS` test checks that each entry's button exists once in its page. A new label test checks that every label in the measured map exists in its page, so a recapture that renames a label fails.
2. **Mirror check `scripts/of-mirror-check/settings_writes.py`** (Playwright, in the style of `writes.py`).
   - Mocked Relay. Unmocked `/api/**` returns `[]`. Any non-localhost request fails the check.
   - **Single scope.**
     - Exactly one `POST /api/of/v2/campaigns {"name":"Synthetic link"}`.
     - Exactly one `POST /api/of/v2/trials` whose body is the defaults above. `expired_at` is checked as a local ISO date 7 days ahead, with the minute tolerated.
     - Each write carries the scoped `X-Account-Id`.
     - The page lands on the tab after each create.
     - "Start campaign" and bundle "Save" send nothing and show `READ_ONLY`.
   - **All-models pass.** Nothing is sent and both Creates show `SELECT_MODEL`.
   - Screenshots go to `/tmp/of-mirror-shots/inapp-settings-writes-*.png`.
   - `writes.py` still exits 0.

Prior art: `app/lib/ofMirrorWrites.test.ts` (schedule-form tests on the real page) and `scripts/of-mirror-check/writes.py` (the stream POST, the all-models pass).

## Acceptance

```sh
cd app && npx vitest run lib/ofMirrorWrites.test.ts && cd ..
node scripts/of-mirror.mjs --check
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
# manual: start the dev server in another shell: cd app && npx next dev --webpack -p 3091
PORT=3091 python3 -I scripts/of-mirror-check/settings_writes.py
PORT=3091 python3 -I scripts/of-mirror-check/writes.py
# manual: Read /tmp/of-mirror-shots/inapp-settings-writes-*.png (OF's look kept, note visible, trial dropdown open)
```

## Depends on

None. It touches only `ofMirrorWrites` and is independent of the Post and Data Phases. Phase 0 also edits `ofMirrorWrites`, to export `note`, `READ_ONLY` and `SELECT_MODEL`. If Phase 0 lands first, this Phase uses those exports; neither order blocks the other. Phase 6 must land after this Phase, because it binds every page on the keys this Phase sets.

## Out of Scope

- **Promotion "Start campaign" write.** The captured modal is the Free-trial tab, which has no discount input, and `_PromoBody.discount` is required. The "First month discount" tab was not captured. The plan's rule says an unmappable input leaves the modal read-only.
- **Discount out-of-range note.** It only applies to a promotion collector, which is not built (above).
- **The bundle Save.** The Relay needs `price` and the modal has none (plan).
- **Subscription price Save and row kebab deletes.** There is no price write method, and the rows are scrubbed examples with no real ids (plan). Their click note comes from Phase 6's fallback.
- **Everything else.** All `/users/me/settings`, notification, security, story and streaming toggles have no Known body (plan); they keep today's note.
- **Tracking link `code`.** The modal has no code field, so OnlyFans picks the code.
- **Showing the created link in the tab's list.** No Data part loads `/campaigns` or `/trials`. That would be a new Data part the plan doesn't name.
- **Updating the trial modal's "Promotional subscription $0.00 for N days" help text when the duration changes.** It's cosmetic, and the help text is scrubbed copy.
- **Making the promotion modal's dropdown state pages selectable.** The modal is read-only.

## Further Notes

- The plan lists the promotion modal as wired, with the body `{discount, subscribe_counts, subscribe_days, message, type}`. Measured against the capture, there is no discount input, and the audience and offer tabs have no measured mapping to `type`, so the plan's own fallback ("an input the spec cannot map leaves that modal read-only") applies. The plan's settings_writes acceptance of "exactly the three bodies" becomes two bodies plus the promotion Read-only note (rung 1 observation, rung 2 the plan's rule).
- Observation: `create_trial_link` (of_client.py:2166) carries no "verified live" note, unlike the campaigns and promotions methods. ADR-0005's Known body definition asks for live confirmation or OnlyFans's JS. It stays wired because the plan's table says wire and the plan is binding.
  ASSUMPTION: the trial body is Known as the plan states; overturned if the human requires live confirmation first, in which case the trial modal moves to `READ_ONLY_SUBMITS`.
- ASSUMPTION: "Offer expiration: N days" is sent as `expired_at = localIso(now + N×24h)`, the same format as the stream's `scheduledDate` (rung 3, house precedent). Overturned if OnlyFans's JS shows another format or a day-boundary rule. Under review as needs-human (see Review); if the human rules it a guess, every expiration other than "No expiration" gives the option read-only note and sends nothing.
- ASSUMPTION: "No limits" (offer limit) and the month durations ("1 month", "3 months", "6 months") have no Known value, so they give the note "<option> is read-only in Inflowwww for now" and send nothing (rung 4: nothing guessed reaches a live account). Overturned by OnlyFans's JS showing their values.
- ASSUMPTION: the trial modal's dropdowns become pickable by showing OnlyFans's own hidden `v-menu__content` lists. Otherwise every trial link would go out at the captured 10 subscribers, 7 days and 7 days, and Phase 6 would mark the dropdowns read-only while their values are sent (rung 5, the smallest thing that meets "each input maps"). Overturned if the human prefers fixed captured defaults.
- ASSUMPTION: the selected value is read from the `aria-selected` option, not from the visible selection, because the scrubber fakes the visible number (rung 1: "12 subscribers" is not in the option list, and the hidden value is 10).
- ASSUMPTION: read-only submit buttons show `READ_ONLY` in all-Creators scope too, rather than being left alone (rung 5: the note is true in both scopes and no Silent control is left). Overturned if the human wants `SELECT_MODEL` there.
- ASSUMPTION: `scheduleStream` is folded into a generic `submit(path, body)` handler (rung 5, one path for all `SUBMITS`). Overturned if a reviewer wants the named handler kept; the behaviour is the same either way.

## Review

Reviewer: codex (gpt, `model_reasoning_effort=high`), 2026-10-12. Blind call (B) then draft call (D).

- B1 reject: explicit typed handlers per modal instead of the generic `{button, collect, send, then}` path. The plan fixes the generic shape (plan: Phase 5 Decisions, "SUBMITS ... generalises to page -> {button, collect, send, then}"); rung 2.
- B2 partial: trial-link evidence is weaker than campaigns/promotions (of_client.py:2166-2179 has no "verified live" note). The body keys are Known: ADR-0005 lists "trial link" among the Known bodies and the plan's table says wire. The value semantics of `expired_at` are the real gap, carried by D1.
- B3 reject: "app/public/of-mirror is absent, so labels can't be verified". It is absent only from the sparse review workspace; `ls app/public/of-mirror/pages/settings/subscription/` in the repo lists promotion-campaign, tracking-links, trial-links. The measured map comes from those pages and the new label test fails on a recapture.
- B4 partial: Relay bounds. Accepted as a sentence in Selected value source (every sendable option is inside server.py:6835-6840 bounds). Rejected: a Relay/of_client camelCase contract test; this Phase changes no Relay or of_client code (Contracts: "no Relay change") and the plan's Check loop places the seam at the mocked Relay.
- B5 partial: lifecycle cases. Failure, success navigation and invalidation were already specced; added a pending double-click test for story 12. List refresh after create stays Out of Scope (no Data part loads `/campaigns` or `/trials`).
- B6 accept (no change): the seam is `bindWrites` on the real page plus the Playwright Mirror check asserting method, path, body and `X-Account-Id`; the spec already tests there.
- B7 reject: falsifier "pages missing" is the workspace artifact of B3. A recapture that changes labels is caught by the label test.
- D1 needs-human: `expired_at = localIso(now + N days)` for "Offer expiration: N days". Reviewer: the value is a guess, ADR-0005 and the plan's "no guessed OF body" forbid sending it; only "No expiration" is safe. Spec: the key `expiredAt` is sent by of_client.py:2177-2178 as "ISO 8601", the plan wires `expired_at?`, and N×24h from now in the stream's ISO format is the plain reading. Settles it: OnlyFans's JS for the trial-link modal (how it computes `expiredAt` from the dropdown), or a live capture of one create. Interim: spec keeps the computed value; if the human rules it a guess, expirations other than "No expiration" give the option read-only note (Further Notes).
- D2 accept: the Objective promised the Read-only note for every other subscription control while price Save and kebab deletes stay silent until Phase 6. Objective rewritten to say so.
- D3 accept: story 15 had no test. Added the promotion Message-change `READ_ONLY` test.
- D4 accept: story 6 (visible selection) was not asserted. The trial-defaults test now checks each dropdown's visible title after bind.
- D5 partial: same as B2. ADR-0005's own list names the trial link as a Known body, so the write stays wired (rung 2, plan table); the residual doubt is the `expired_at` value, parked in D1.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- White, departure 3 (the promotion modal is read-only, so `settings_writes.py` asserts two bodies, not three): **accept** as fact. It stays on rung 1 plus the plan's own fallback rule (Further Notes). The plan is not edited, and the mismatch is listed under Open questions in `plan-review.md`.
- Red, the trial-link write uses circular logic: **accept** the point; the decision is not resolved here. ADR-0005 was written by this run (commit 6cf33add), and HEADER rung 2 says such text is never rung 2. So review lines B2 and D5 lose ADR-0005 as support. What remains is the plan's table, "trial-links | Create link | ... | wire" (plan:66), a real rung-2 instruction. ADR-0005's own Known-body test (live-confirmed or read from OF's JS) is unmet for this body (`create_trial_link` has no "verified live" note). Whether to keep the write is the human's call, listed under Needs the human in `plan-review.md` beside the `expired_at` question.
- Black, both Phase 5 and Phase 6 change `ofMirrorWrites` key paths, and "neither order blocks" can collide: **accept**. This Phase now owns the key change for `SUBMITS`, `WRITABLE` and the `bindWrites` path. Phase 6 changes no key and must land after this Phase (Interfaces, Depends on). The decision is made by the ladder and flagged.
- Black, `expired_at` is computed and no one has confirmed it: **needs-human** (already review D1); not re-decided.
- Black, the trial body has no live confirmation: **needs-human**, merged with the Red line above.
- Black, duplicated read-only handling (`READ_ONLY_SUBMITS`): **reject** for this Phase. Those buttons must also `preventDefault` a native form submit, which Phase 6's fallback does not do (it never prevents default). The table stays.
- Green, keep the trial modal read-only until it is confirmed live (this also removes the `expired_at` guess and the dropdown picker): **needs-human**, not resolved here. The plan says wire (plan:66), and only the human can override the plan. If the human rules for read-only, the trial modal moves to `READ_ONLY_SUBMITS`, and the picker and `expired_at` mapping go (Further Notes overturn clause).
