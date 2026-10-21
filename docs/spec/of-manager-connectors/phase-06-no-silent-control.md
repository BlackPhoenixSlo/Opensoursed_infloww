# Phase 06 — Sign-off: no Silent control

**Objective.** On every Mirror page, clicking any visible, enabled control that isn't a link, a Wired control or a State page opener shows the Read-only note, in both scopes. `dead.py` proves this across the signed-off pages, and the full Mirror check suite, the generator guard, typecheck, lint and vitest are all green.

## Problem Statement
An operator in the OF Manager clicks a button on a Mirror page (a post kebab, a queue row action, "Create new list", a notification filter, a statement button, a subscription tab button) and nothing happens: there is no write, no navigation and no message. They can't tell a broken page from a feature we don't support, so they click again, reload or report a bug. Today the Read-only note covers only changed *settings* fields in Single-Creator scope (`bindWrites` change path, `app/lib/ofMirrorWrites.ts:208-228`). `useOfWrites` binds nothing outside settings and the one SUBMITS page (`ofMirrorWrites.ts:285`, `:305`). Every other click on every other Mirror page is a Silent control.

## Solution
Every click on a Mirror page now gives visible feedback. A link or State page opener navigates. A Wired control from Phases 0–5 writes or shows its own note. Every other button, `[role=button]` or checkbox shows "Read-only in Inflowwww for now", and a toggle flips back. This works in Single-Creator and All-Creators scope alike, because neither scope can write such a control. A headless sweep (`dead.py`) clicks every visible control on the signed-off pages and fails on any Silent control. `docs/routes.md` and the check README state plainly what writes, what shows data and what is read-only, using the plan's Ground truth table.

## User Stories
1. As an operator, I want a click on an unwired OF button on any Mirror page to show the Read-only note, so that I know the feature isn't supported here and the page isn't broken.
2. As an operator, I want a click on an unwired `[role=button]` element (a row kebab, a tab-like chip) to show the same note, so that non-`<button>` controls behave the same way.
3. As an operator, I want an unwired checkbox or toggle on any Mirror page, not only settings, to show the note and flip back, so that the page never shows a state that wasn't saved.
4. As an operator in All-Creators scope, I want unwired controls to show the Read-only note too, so that this scope has no Silent controls either.
5. As an operator in All-Creators scope, I want Wired controls to keep showing the Select-model note and send nothing, so that the existing scope rule (`ofMirrorWrites.ts:14-16`) still holds.
6. As an operator, I want links and State page openers (OF buttons the generator turned into `a[href]`, and the `of-state-link` / `of-state-backdrop` overlays) to navigate as they do today, with no note, so that opening a dialog isn't mistaken for a read-only action.
7. As an operator, I want Wired controls from Phases 0–5 (Post, schedule Next, Co-tag rows, vault tiles and search, Add media, Add to story, the three subscription modal buttons) to never also show the Read-only note, so that a control that works never claims it doesn't.
8. As an operator, I want video-player controls left alone, so that playing a sample video in a feed isn't interrupted by a note.
9. As an operator, I want the existing settings behaviour unchanged: profile Save and the welcome-message switch write, Dark mode switches our theme, and the stream SCHEDULE form keeps its own path. That way nothing that works today regresses.
10. As an operator, I want the profile page's more-menu State page (`profile/state-more-menu`) not to pick up the settings profile page's write map, so that a Mirror page outside settings never binds a settings write.
11. As a maintainer, I want a single Mirror check, `dead.py`, that clicks every visible enabled `button`, `[role=button]` and checkbox on new-post/*, home, profile/*, queue/*, collections/*, notifications/*, statements/* and settings/subscription*, and that within 1s records a Relay write, a navigation or the Read-only note. It prints the count per page and exits 1 on a Silent control.
12. As a maintainer, I want `dead.py` to fail when a control without `data-oi-wired` sends a Relay write, so that a write that bypasses the Wired-control contract (ADR-0005) is caught.
13. As a maintainer, I want `dead.py` to fail when a Wired control from the plan's Ground truth table is missing its `data-oi-wired` mark, so that a forgotten mark can't make a working control show the Read-only note as well.
14. As a maintainer, I want `dead.py` to run an All-Creators pass that makes no Relay write at all, so that the scope rule is proven across every signed-off page.
15. As a maintainer, I want `dead.py` to fail on any request to a non-localhost host and to mock every Relay path it hits, so that the sign-off never touches live OnlyFans.
16. As a maintainer, I want every earlier Mirror check (`render.py`, `navigate.py`, `settings_values.py`, `writes.py`, `dark.py`, `data.py`, `post.py`, `post_vault.py`, `post_upload.py`, `story.py`, `feeds.py`, `settings_writes.py`) to still exit 0 next to `dead.py`, so that the fallback breaks no wiring.
17. As a maintainer, I want `node scripts/of-mirror.mjs --check`, `pnpm -C app typecheck`, `pnpm -C app lint` (0 errors) and `ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run` green, so that the effort closes with a clean suite.
18. As a maintainer, I want `docs/routes.md`'s OF Manager rows to say what writes, what shows data and what is read-only, matching the Ground truth table, so that the route docs describe how the app behaves today.
19. As a maintainer, I want `scripts/of-mirror-check/README.md` to describe `dead.py` and list, page by page, the writes, Data parts and read-only controls, so that the next person knows what each check proves.
20. As an implementer, I want to Read the `dead.py` screenshots in `/tmp/of-mirror-shots` and confirm that OF's look is kept and the note is visible, so that the fallback doesn't visually break the mirror.

## Implementation Decisions
- **Owns.** `app/lib/ofMirrorWrites.ts` (`bindWrites`, `useOfWrites`), `app/lib/ofMirrorWrites.test.ts`, the new `scripts/of-mirror-check/dead.py`, `scripts/of-mirror-check/README.md`, and `docs/routes.md` (OF Manager rows). Phase 06 also edits any Phase 0–5 binder that fails `dead.py`'s mark check, adding only the missing `data-oi-wired` attribute. It also removes any Phase 0–5 read-only handler that its fallback or change path now duplicates (same note, same flip-back), so each control has exactly one read-only handler and a toggle never flips twice.
- **Interfaces.**
  - `bindWrites(doc, path, handlers)`: unchanged from Phase 5, which owns the key change. `path` is the page's path under `of-mirror/pages` (for example `settings/profile`, `new-post/state-vault`, `streaming/dashboard/create`). `WRITABLE` keeps its settings sub-path keys and is looked up only for `settings/` paths after stripping that prefix and any `/state-*` suffix. `SUBMITS` keeps its full-path keys. This Phase relies on those keys and changes none.
  - `useOfWrites(frameRef, src)` binds on every Mirror page, not only settings and SUBMITS pages. The handlers rule stays the same: `null` when no single Creator is selected.
  - The return value is still an unbind. No new export is needed. The mark is the literal attribute `data-oi-wired`, as the glossary defines it.
- **Schema.** None — this Phase has no storage. The fallback is in-page DOM listening, and no `sessionStorage` key is added.
- **Contracts.**
  - **The `data-oi-wired` mark.** The plan names the mark only in Phase 6 (plan:253), so Phase 6 applies it: it adds the attribute to each Phase 0–5 binder that lacks it. Phases 0–5 may set it earlier; the contract is the same either way. A Wired control, and every form field whose value a Wired control sends, gets `data-oi-wired` on the element itself (never on a page-wide container). Its binder sets the mark at bind time in both scopes. The change path skips any change target whose `closest('[data-oi-wired]')` is set; the click fallback skips a control with the mark at or inside it (see Click fallback). `bindWrites` marks its own Wired controls at bind time: the `WRITABLE` fields of the page, profile Save, and the `SUBMITS` button and its form fields.
  - **The Read-only note.** It is the existing `note()` element `#oi-note` (`role=status`) with the exact text `Read-only in Inflowwww for now`. A Mirror check reads this element and nothing else.
- **Click fallback (new branch at the end of `bindWrites`'s click listener).** It runs after the profile Save and `SUBMITS` branches have returned for their own targets. For the click target `t`:
  - Do nothing when `t` is inside an `a[href]` (links, State page openers, `of-state-link` / `of-state-backdrop` overlays, inert `#` links) or inside `.video-js`.
  - Do nothing when `[data-oi-wired]` or a form field (`input` that is not `readonly`, `label`, `textarea`, `select`, `[contenteditable]`) is at or inside the clicked control: `t.closest(...)` of that set is the control itself or one of its parts. The binder owns a Wired control and the change path owns form fields. A dropdown's readonly `<input>` is no form field, and a button nested in a Wired row or a `label` (Story 2's row kebab) still gets the note.
  - Otherwise take `t.closest('button, [role=button]')`. If there is one, `note(doc, control, READ_ONLY)`. It doesn't `preventDefault` and doesn't depend on listener order, because skips are decided by markup, not by `defaultPrevented`.
- **Change path (kept, widened).** The existing read-only branch (`ofMirrorWrites.ts:223-227`: note, and a checkbox flips back) now runs on every Mirror page and in both scopes. Its condition loses `handlers &&` and gains "target not inside `[data-oi-wired]`". It keeps its existing exclusions: `SUBMITS` pages' own fields and the Dark mode switch. In All-Creators scope, the `WRITABLE` branch (Select-model note, flip back) is unchanged. This is how checkboxes meet the plan's "button, `[role=button]` or checkbox" coverage: one owner per kind of control, so a toggle never flips twice.
- **Video-player exclusion.** The selector is `.video-js`, measured: the `video-js` and `vjs-*` classes appear on `collections/post-labels/archived.html`.
- **No new UI.** The note is the existing one, placed by `note()`'s existing rules (before a `<button>`, after the closest `.g-input__wrapper` / `.b-menu-list__el` otherwise). No committed page under `app/public/of-mirror/` is edited (ADR-0006).

## Testing Decisions
Seams, highest first:
1. **`dead.py`, through the mounted frame, as a Mirror check (primary seam).** It runs against `/of-manager/<page>` with Playwright route mocks in the style of `writes.py`'s `session()`.
   - **Mocks.** Login mocks as in `writes.py`. `/api/of/v2/users/me` returns synthetic values. `GET /posts/tagged-friend-users` and `GET /vault/media` each return one synthetic row ("Alpha One"). `GET /img*` returns a 1x1 PNG the script generates. Every other `GET /api/**` returns `[]`. Every non-GET `/api/**` is recorded (method, path, `X-Account-Id`, body) and answered `200 {}`. Any non-localhost request is recorded as a failure.
   - **Pages.** All pages under the plan's prefixes, read from `app/lib/of-mirror-pages.ts`: new-post/*, home and its states, profile/*, queue/*, collections/*, notifications/*, statements/*, and settings/subscription plus its tabs, modals and states. `sessionStorage` is cleared before each page.
   - **Controls.** Visible, enabled `button`, `[role=button]` and `input[type=checkbox]` in the frame, excluding `.video-js` descendants. A hidden checkbox input is clicked through its visible `label` (ancestor or `label[for]`). Elements inside `a[href]` count as links. They're clicked too, and must navigate or stay inert if their href is `#`.
   - **Outcomes, polled for 1s after each click.** Before each click `dead.py` removes any existing `#oi-note`, so only a note the click caused counts (`note()` reuses the element, `ofMirrorWrites.ts:93-108`). Accepted outcomes: a recorded Relay write on the allow-list below; a change of the top page URL to a localhost `/of-manager/` URL (the frame is reloaded at its page afterwards); a fresh `#oi-note` with the Read-only text (for unmarked controls); for `[data-oi-wired]` controls, a fresh `#oi-note` whose text is **not** the Read-only text, a Playwright file chooser, or a change to the control's own `outerHTML` (a selected mark).
   - **Failures.** No outcome is a Silent control. A Relay write from an unmarked control fails. A marked control that shows the Read-only note fails (Story 7). Any Relay write whose method and path are not on the Ground truth "wire" allow-list (`POST /api/of/v2/posts`, `/upload`, `/stories/upload`, `/campaigns`, `/trials`, `/promotions`) fails; exact bodies stay asserted by each Phase's own check (`post.py`, `story.py`, `settings_writes.py`, …), which run in the same Acceptance loop. A plan Wired control without the mark fails, using a table of selectors measured in Ground truth 5: `button[at-attr='submit_post']`, `[aria-label='Add media']`, `.b-story-item.m-story-item-own`, `input[name='media_vault_search']`, the `.b-photos` tiles, the `state-tag-people` rows, `state-schedule`'s Next, and the subscription modals' "Create Link" / "Create link" / "Start campaign".
   - **Output.** One JSON line per check (`{"check","want","got"}`) and a per-page line with counts `{page, controls, links, wired, readonly}`.
   - **All-Creators pass.** The same pages with the scope key removed before every load. Zero non-GET `/api/**` requests across the pass; unmarked controls give the Read-only note or a navigation; no marked control gives the Read-only note; and the send controls (Post, Add to story, "Create Link" / "Create link" / "Start campaign") give exactly the Select-model note, "Select a model to save changes" (Story 5, plan:81-83).
   - **Screenshots.** One per page with a note showing: `/tmp/of-mirror-shots/inapp-dead-<page>.png`.
2. **`ofMirrorWrites.test.ts` (vitest, jsdom) on `bindWrites`.** Tests cover:
   - Click fallback: notes on a `<button>` and a `[role=button]` of a loaded non-settings page (for example `queue/index`, `collections/index`).
   - Silence where it should be silent: no note inside `a[href]` or `.video-js`, and none for a control with `[data-oi-wired]` or a form field at or inside it. A dropdown's readonly input and a button nested in a Wired row or a `label` do get the note.
   - All-Creators scope: an unmapped toggle now gets the note and flips back. This inverts the current test "leaves an unmapped toggle alone".
   - Change-path marks: a checkbox inside `[data-oi-wired]` gets no note and no flip.
   - One flip-back: with `bindPost` and `bindWrites` both bound on `new-post/state-labels`, one click on a label checkbox leaves it in its captured state and shows the Read-only note once.
   - Path keys: `bindWrites(doc, "profile/state-more-menu", …)` binds no `WRITABLE` field, and `"settings/profile"` keeps today's Save behaviour.
   - Existing tests move to full paths and stay green. These are the profile Save, the welcome switch, the stream form and Dark mode.

Prior art: `scripts/of-mirror-check/writes.py` (mocked Relay, write recording, two-scope passes, `#oi-note` reads); `app/lib/ofMirrorWrites.test.ts` (`loadPage` over committed pages, `handlers()` stubs, `fire`).

## Acceptance
```sh
node scripts/of-mirror.mjs --check
pnpm -C app typecheck
pnpm -C app lint
pnpm -C app exec vitest run lib/ofMirrorWrites.test.ts
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
# Mirror checks need the dev server on $PORT (run it in another shell): cd app && npx next dev --webpack -p 3091
export PORT=3091
for c in render navigate settings_values writes dark data post post_vault post_upload story feeds settings_writes dead; do
  python3 -I "scripts/of-mirror-check/$c.py" || { echo "FAIL $c"; exit 1; }
done
grep -q "dead.py" scripts/of-mirror-check/README.md
grep -q "Create new list" scripts/of-mirror-check/README.md   # the read-only inventory is listed
grep -q "dead.py" docs/routes.md
! grep -q "other controls are not intercepted" docs/routes.md   # today's All-Creators wording is gone
grep -q "data-oi-wired" app/lib/ofMirrorWrites.test.ts           # the new vitest seams exist
# manual: Read /tmp/of-mirror-shots/inapp-dead-*.png — OF's look kept, the note visible, never committed
```

## Depends on
Phases 0–5 provide the Wired controls; the `data-oi-wired` marks on them are Phase 6's to add where missing (the plan names the mark only at plan:253).
- **Phase 0 — New post: text, schedule, tagged users.** Provides `ofMirrorPost.ts`'s Wired controls (Post, schedule Next, Co-tag rows), the exported `note` / `READ_ONLY` / `SELECT_MODEL`, and `post.py`.
- **Phase 1 — Media from the vault.** Provides vault tiles and search as Wired controls, and `post_vault.py`.
- **Phase 2 — Upload from disk.** Provides "Add media" as a Wired control (file chooser), and `post_upload.py`.
- **Phase 3 — Add to story.** Provides "Add to story" as a Wired control, Create highlight as read-only, and `story.py`.
- **Phase 4 — Real data.** Provides the Data parts whose row actions are read-only, and `feeds.py`.
- **Phase 5 — OF settings writes with Known bodies.** Provides the generalised `SUBMITS` (the three subscription modals as Wired controls), and `settings_writes.py`.

## Out of Scope
- **Inert `#` links** (scrubbed OF links, made inert by `OfMirrorFrame`). The plan defines a control as a button, `[role=button]` or checkbox outside an `a[href]`, so links are excluded.
- **Text inputs, selects and `[contenteditable]` editors in `dead.py`.** A click focuses them, which is their response. An unwired one's change still gets the note through the change path.
- **Video-player controls.** Excluded by the plan.
- **Pages outside the plan's `dead.py` list** (messages, vault, statistics, bank, streaming, settings other than subscription) in `dead.py`. The fallback still runs on them, because it binds on every page. `writes.py` and `settings_values.py` keep covering settings.
- **New Wired controls, Data parts, Relay routes or bodies.** That is Phases 0–5's work, and ADR-0005 rules out guessed bodies.
- **Disabling or restyling unwired controls.** ADR-0005 rejects this, because it changes OF's look.
- **A shared JS helper for setting the mark.** The attribute literal is the whole contract (YAGNI).
- **Keyboard-only activation tests.** Enter or Space on a focused button dispatches the same `click` the fallback handles, so there is nothing separate to test.

## Further Notes
- The fallback and the widened change path apply in All-Creators scope too. The plan says "on every mirror page" with no scope qualifier, and the Read-only note is true in both scopes. This inverts the existing vitest "leaves an unmapped toggle alone".
  ASSUMPTION: rung 4 (an additive note, undone by restoring `handlers &&`); overturned if the human wants All-Creators scope to leave unwired controls untouched, in which case `dead.py`'s All-Creators pass checks only "no write".
- `bindWrites` takes the full path under `of-mirror/pages`, and `WRITABLE` is looked up only for `settings/` paths. Observed: `basePage("profile/state-more-menu")` gives `"profile"`, which would collide with `WRITABLE.profile` once the hook binds every page.
  ASSUMPTION: rung 2 for the order (Phase 5 precedes Phase 6 in the plan) and rung 5 for one owner: Phase 5 makes this key change and this Phase relies on it. Overturned if Phase 5 lands without it, in which case this Phase makes it.
- Checkboxes reach the Read-only note through the existing change path, not the click fallback, so a toggle flips back exactly once.
  ASSUMPTION: rung 3 (house precedent `ofMirrorWrites.ts:223-227`); overturned if a captured checkbox fires no `change` on click.
- `dead.py` also clicks Wired controls and accepts a note, a file chooser or a change to the control's own markup from them, so it doesn't hard-code each Phase's success shape.
  ASSUMPTION: rung 5; overturned if a Phase's Wired control has a response none of these detect.
- `dead.py`'s mark-check selectors are the plan's measured ones (Ground truth 5).
  ASSUMPTION: rung 3; where a Phase 0–5 spec binds a different element for the same control, that spec's selector replaces the plan's.
- `dead.py` mocks `tagged-friend-users` and `vault/media` with one synthetic row each, so that the Co-tag rows and vault tiles exist in Single-Creator scope (unmocked `[]` would leave none to check).
  ASSUMPTION: rung 5; overturned if the human prefers the mark check in the All-Creators pass only.
- `dead.py` has no runtime budget. It short-circuits on the first outcome and waits the full 1s only for a Silent control.
  ASSUMPTION: rung 6; overturned if it exceeds the dev loop's patience, in which case it gains a page-filter argument as `render.py` has.

## Review
codex — 2026-10-12. Blind call (B) then draft call (D).
- B1 alternatives (explicit control inventory; disabling/annotating markup): **reject** — the plan decides the `bindWrites` fallback (plan:253-255) and ADR-0005/0006 reject the other two; a constraint, not a choice.
- B2 `dead.py` covers only part of the 153 pages: **reject** — the page list is the plan's own Acceptance (plan:260-263); the fallback still binds on every page (Out of Scope).
- B3 radios, selects, submit, keyboard not defined: **reject** — the plan defines the control set as `button`, `[role=button]`, checkbox (plan:254); text inputs/selects and keyboard are already argued in Out of Scope, and unwired fields still get the note through the change path.
- B4 navigation destination unchecked: **accept** — a navigation now counts only if the top URL lands on a localhost `/of-manager/` URL (Testing → Outcomes).
- B5 a stale `#oi-note` could satisfy the check: **accept** — `dead.py` removes `#oi-note` before each click and only a fresh note counts (Testing → Outcomes).
- B6 All-Creators distinction not checked across the inventory: **accept** — merged with D3.
- B7 seam = runtime frame with mocked Relay: **reject** (agreement, no change) — already the primary seam.
- B8 an unsupported control could write before the note: **reject** — already a failure (Story 12, Failures); D2 tightens it further.
- B9 `dead.py` doesn't exist yet: **reject** — it is this Phase's deliverable.
- D1 any `#oi-note` passes a marked control, including the Read-only note: **accept** — a marked control showing the Read-only note now fails (Outcomes, Failures).
- D2 any Relay write is accepted, guessed bodies included: **partial** — writes outside the Ground truth "wire" (method, path) allow-list now fail; exact bodies stay with each Phase's check in the same loop, since `dead.py` clicking with empty forms can't assert a body.
- D3 All-Creators pass doesn't prove Story 5's Select-model note: **accept** — send controls must show exactly "Select a model to save changes"; no marked control may show the Read-only note.
- D4 Depends on claims Phases 0–5 provide marks the plan never assigns them: **accept** — `grep -n data-oi-wired` on the plan hits only line 253; Depends on and the mark contract now say Phase 6 adds missing marks (already in Owns).
- D5 doc greps pass today (`Read-only in Inflowwww for now` is already in routes.md): **accept** — replaced by `dead.py` in routes.md, `! grep` of today's "other controls are not intercepted" wording, and a README grep for the read-only "Create new list"; content match to Ground truth stays a manual read.
- D6 Acceptance would pass without the new vitest seams: **partial** — added `grep -q data-oi-wired app/lib/ofMirrorWrites.test.ts`; a grep can't prove each listed case, so the test list in Testing Decisions stays the contract.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- Black, the generic fallback duplicates what Phases 0, 3, 4 and 5 wire by hand (four extra code paths): **partial**. The per-Phase handlers stay until this Phase lands, because the plan names them in their Phases (plan:122, 187, 212, 237) and each Phase's check asserts the note before this Phase exists. This Phase now removes each duplicated handler (Owns). A vitest case proves a read-only toggle flips back once, not twice (Testing Decisions, seam 2). `READ_ONLY_SUBMITS` stays (phase-05 Six hats).
- Black, both Phase 5 and this Phase re-key `ofMirrorWrites`: **accept**. Phase 5 owns the key change, and this Phase changes no key (Interfaces, Further Notes).
- Black, `data-oi-wired` ownership split between Phase 0 and Phase 6: **accept**. This Phase owns the contract (plan:253; rung 2). Phases 0–3 set the mark early on their own Wired controls only. Phase 4's read-only row actions no longer carry it, and this Phase adds any mark a binder misses (Contracts).
- Green, land the fallback first: **reject**. The plan's Phase order is the user's. The plan places the fallback in this sign-off Phase (plan:247-255), and its acceptance needs every Phase 0–5 check (plan:264-266), so the plan does not allow landing it early.
