# Phase 03 — Add to story

**Objective.** In Single-Creator scope, clicking "Add to story" in the story strip of `home` or `new-post` opens an image picker and publishes the picked image as a Story through the Relay's `POST /api/of/v2/stories/upload`; every other story-strip button answers with the Read-only note.

## Problem Statement

A manager working a Creator's OF Manager sees OnlyFans's story strip on Home and New post, with its "Add to story" tile, exactly as on OnlyFans. Clicking it does nothing: there is no picker, no upload, no feedback. The other tiles in the strip (fans' stories on Home; "Go live", "Send message", "Start profile promotion", "Create new trial link" on New post; "Story archive", "Create highlight", "Go live" on My profile) are equally silent, so the manager cannot tell a broken control from one that Inflowwww deliberately does not perform. Infloww's OF Manager lets the manager post a story on the Creator's behalf.

## Solution

"Add to story" becomes a Wired control. With one Creator selected, a click opens the system file picker filtered to images; picking an image uploads it through the Relay, which publishes it as that Creator's Story (the Relay already does the upload, convert and publish in one call). While it uploads, the tile is disabled. On success a grey "Added to story" note appears under the strip and fades; on failure a red "Could not add: <message>" note stays. With All Creators selected, a click opens no picker, sends nothing and shows "Select a model to save changes". Every other button in the story strip, in either scope, sends nothing and shows "Read-only in Inflowwww for now". OnlyFans's look is untouched.

## User Stories

1. As a manager in Single-Creator scope, I want clicking "Add to story" on `home` to open a file picker, so that I can choose an image for the Creator's Story.
2. As a manager in Single-Creator scope, I want the same on `new-post` (and its State pages, which carry the same strip), so that I can add a Story while composing a post without leaving the page.
3. As a manager, I want the picker to offer images only, so that I do not pick a video the Relay's story path does not document.
4. As a manager, I want a picked image to be uploaded as one multipart `POST /api/of/v2/stories/upload` with field `file` and the Creator's `X-Account-Id`, so that the Story lands on the selected Creator's account and no other.
5. As a manager, I want the "Add to story" tile disabled while the upload is in flight, so that a double click does not publish the same Story twice.
6. As a manager, I want a grey "Added to story" note under the story strip on success, so that I know the Story was published.
7. As a manager, I want a red "Could not add: <message>" note with the Relay's error text on failure, and the tile re-enabled, so that I can see why and try again.
8. As a manager, I want picking a file that is not an image to send nothing and show a red "Could not add: choose an image" note, so that a mis-pick never reaches the Creator's account.
9. As a manager, I want cancelling the picker to send nothing and show nothing, so that backing out is harmless.
10. As a manager, I want to pick the same file twice in a row and have the second pick upload again, so that a retry after an error works.
11. As a manager in All-Creators scope, I want "Add to story" to open no picker, send nothing and show "Select a model to save changes", so that a Story never goes to an unspecified Creator.
12. As a manager, I want "Create highlight" (My profile's strip) to send nothing and show the Read-only note, so that I know highlights are not performed by Inflowwww.
13. As a manager, I want every other story-strip button on `home`, `new-post` and `profile` (fans' story tiles, "Go live", "Send message", "Start profile promotion", "Create new trial link", "Story archive") to send nothing and show the Read-only note, so that no tile in the strip is a Silent control.
14. As a manager, I want no caption, mention, question sticker or story-from-vault option added, so that the OnlyFans markup is unchanged and only Known bodies are sent.
15. As a maintainer, I want a Mirror check `story.py` that proves exactly one multipart upload per click with the right field and header, the read-only and all-Creators behaviour, and that no request leaves localhost, so that a recapture that moves the selector fails loudly (ADR-0006).
16. As a maintainer, I want vitest coverage of the story binding against the real committed `home`, `new-post` and `profile` pages, so that the selectors are proven against the captured markup.
17. As a maintainer, I want `docs/routes.md` and the check README to say that "Add to story" writes and the rest of the strip is read-only, so that the docs match the wiring.

## Implementation Decisions

- **Owns.** `ofMirrorPost` (the module Phase 0 creates; this Phase adds its story block), `OfMirrorFrame` (mounts the new hook), the Mirror check `story.py`, and the OF Manager rows of `docs/routes.md` plus `scripts/of-mirror-check/README.md`.
- **Interfaces.**
  - `ofMirrorPost` gains `STORY` (the measured selectors: own tile `.b-story-item.m-story-item-own`, any tile `.b-story-item`, strip `.stories-list`), `StoryHandlers { addStory(file: File): Promise<unknown> }`, `bindStory(doc, handlers: StoryHandlers | null): () => void` (returns an unbind that also removes the hidden input), and a React hook `useOfStory(frameRef, src)` with the same mount pattern as `useOfWrites` (bind on frame load and when already complete; rebind on scope change).
  - `OfMirrorFrame` calls `useOfStory(ref, src)` alongside the other hooks. Nothing else in the frame changes.
  - Uses, does not copy, `note`, `READ_ONLY` and `SELECT_MODEL` exported from `ofMirrorWrites` (exported by Phase 0, per the plan).
- **Schema.** None — no table or stored state; a Story upload is stateless in the app.
- **Contracts.** One request, an existing Relay route, unchanged: `POST /api/of/v2/stories/upload`, multipart, single field `file` (the picked `File`, its own name and type), header `X-Account-Id: <single Creator's id>`, sent by `relay.uploadFile(path, file, "file", { accountId })`. The response body is ignored; a non-2xx reply surfaces as the `RelayError` message. No JSON body, no caption, mention or question fields (the Relay's `/stories` JSON route is not used). Relay side: `of_create_story_upload` -> `OFClient.post_story` (fresh upload, then `/stories` with the convert claim) — a Known body (ADR-0005).
- **Where it binds.** Selector-keyed, not page-keyed: `useOfStory` binds on every Mirror page load and `bindStory` acts only on clicks inside `.b-story-item`. Measured: the own tile exists only on `home`, `home/state-*`, `new-post` and `new-post/state-*`; `profile`, `profile/media` and `profile/state-more-menu` carry a strip without it ("Story archive", "Create highlight", "Go live").
- **Click on the own tile.** `preventDefault`; All-Creators scope (`handlers` null): `note(strip, SELECT_MODEL)`, no picker. Single-Creator scope: if the tile is disabled, ignore; else `click()` a hidden `<input type="file" accept="image/*">` that `bindStory` appends once to the frame document's body (`display:none`, `data-oi-wired`). The own tile also gets `data-oi-wired` (glossary: Wired control).
- **Input change.** No file (cancel): nothing. A file whose type does not start with `image/` (an empty `type` included): red `Could not add: choose an image`, nothing sent. Else: tile `disabled = true`, stale note removed, `handlers.addStory(file)`; resolve -> grey `Added to story` (fades, `note`'s default); reject -> red `Could not add: <message>`; either way the tile is re-enabled and the input's value reset to `""` so the same file can be picked again.
- **Other strip tiles.** A click on any `.b-story-item` that is not the own tile: `preventDefault`, `note(strip, READ_ONLY)`, nothing sent, in both scopes.
- **Note placement.** The anchor is the tile's closest `.stories-list` (a non-button), so `note` inserts the shared `#oi-note` line directly after the strip, keeping it out of the recycle scroller's transformed item views.
- **Hook.** `useOfStory` reads `accountId` from `useScope`; `addStory` is a `useMutation` over `relay.uploadFile("/api/of/v2/stories/upload", file, "file", { accountId })`; handlers are `null` when no single Creator is selected. No query is invalidated (no mirror page shows the Creator's stories).
- **Generated pages.** No committed Mirror page is edited; all of the above is runtime DOM (ADR-0006).

## Testing Decisions

Two seams, both already used by the mirror:

1. **`bindStory` (vitest, jsdom), in `ofMirrorStory.test.ts`.** Load the real committed `home/index`, `new-post/index` and `profile/index` pages the way `ofMirrorWrites.test.ts` does (`loadPage`), bind with a mock `addStory`, and assert external behaviour only: on every committed page that carries `.m-story-item-own` (found by a glob over `app/public/of-mirror/pages/**`, so `home/state-*` and `new-post/state-*` are covered and a recapture that adds or drops one is caught), a click on the own tile clicks the hidden `input[type=file][accept="image/*"]` (spy on its `click`); dispatching `change` with an image `File` calls `addStory` once with that file, disables the tile until it settles, then shows `Added to story`; a rejected `addStory` shows `Could not add: <message>` and re-enables; a `text/plain` file calls nothing and shows the choose-an-image note; null handlers shows `SELECT_MODEL` and never clicks the input; a click on every non-own `.b-story-item` of `home/index`, `new-post/index` and `profile/index` (fan tiles, "Go live", "Send message", "Start profile promotion", "Create new trial link", "Story archive", "Create highlight") calls nothing and shows `READ_ONLY`, in both scopes; a `change` with an empty file list (cancel) calls nothing and adds no `#oi-note`; after `addStory` settles (resolved and rejected) the input's `value` is `""`, and a second `change` with the same file calls `addStory` again; `profile/index` gets no hidden input action from its tiles; unbind removes the input and listeners.
2. **Mirror check `story.py` (Playwright, mocked Relay), the highest seam.** Session and mocks as `writes.py` (scope init script `model:1`, login mocks, unmocked `/api/**` -> `[]`). Records every non-GET `/api/**` request with its method, path, `X-Account-Id` and, for multipart, the part names and filename; records any request to a non-localhost host. A 1x1 PNG is written to `/tmp` by the script. Single-Creator pass: on `home` and on `new-post`, click "Add to story" inside `expect_file_chooser`, set the PNG; assert exactly one `POST /api/of/v2/stories/upload` with one part named `file`, `X-Account-Id: 1`, and the note `Added to story`. Error: the mock answers 500 `{"detail":"synthetic failure"}` once; the note reads `Could not add: synthetic failure`. Non-image: a `.txt` file sends nothing. Read-only: "Create highlight" on `profile`, a fan tile on `home`, "Go live" on `new-post` send nothing and show `READ_ONLY`. All-Creators pass (scope key removed before every load): clicking "Add to story" raises no file chooser within 1s, sends nothing, shows `SELECT_MODEL`. Prints one `{"check","want","got"}` line per check; exit 1 on any failure or any non-localhost request. Screenshots `inapp-story-home.png`, `inapp-story-new-post.png`, `inapp-story-readonly.png`, `inapp-story-all-models.png` to `/tmp/of-mirror-shots`.

Prior art: `app/lib/ofMirrorWrites.test.ts` (real committed pages loaded into jsdom, mock handlers, note assertions); `scripts/of-mirror-check/writes.py` (mocked Relay, recorded writes, all-models pass).

## Acceptance

```sh
pnpm -C app exec vitest run lib/ofMirrorPost.test.ts lib/ofMirrorStory.test.ts
node scripts/of-mirror.mjs --check
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
(cd app && exec npx next dev --webpack -p 3091) > /tmp/of-mirror-dev.log 2>&1 &
DEV=$!
until curl -fs -o /dev/null http://localhost:3091/of-manager/home; do sleep 2; done
PORT=3091 python3 -I scripts/of-mirror-check/story.py
PORT=3091 python3 -I scripts/of-mirror-check/writes.py
kill $DEV
grep -q "stories/upload" docs/routes.md
grep -qi "story.*read-only\|read-only.*story" docs/routes.md
grep -qi "story.*read-only\|read-only.*story" scripts/of-mirror-check/README.md
grep -q "story.py" scripts/of-mirror-check/README.md
# manual: Read /tmp/of-mirror-shots/inapp-story-*.png — OF's strip looks unchanged, the note sits under it.
```

## Depends on

- **Phase 0 — New post: text, schedule, tagged users.** Creates `ofMirrorPost` (where this Phase's story block lives, per the plan) and exports `note`, `READ_ONLY` and `SELECT_MODEL` from `ofMirrorWrites`.

## Out of Scope

- Caption, @mention and question-sticker overlays (the Relay supports them on `/stories`): plan says YAGNI, and they need UI OnlyFans's strip does not have.
- Story from vault or from a URL (`/stories` with `media_url`): plan says no story from vault.
- Video stories: the Relay documents image stories; `accept="image/*"` only.
- Create highlight, Story archive, viewing fans' stories, and the strip's "Go live" / "Send message" / "Start profile promotion" / "Create new trial link" tiles: no write method (highlights) or not a write; Read-only note per the plan.
- Deleting a Story (`delete_story` exists): the plan adds no delete of posts or stories.
- Hiding the vault copy that a fresh story upload leaves (`post_story`'s `return_upload` path, used by `auto_stories`): not asked for; the Relay route does not expose it.
- Showing the Creator's current stories in the strip: no Data part for stories in the plan.
- The page-wide Silent-control fallback: Phase 6.

## Further Notes

- The plan's Phase 3 Acceptance places "Create highlight" on `home` and `new-post`; measured in the committed pages it is only on `profile`, `profile/media` and `profile/state-more-menu` (home's strip: own tile, three fan tiles, "Start profile promotion"; new-post's: own tile, "Go live", "Send message", "Start profile promotion", "Create new trial link"). `story.py` therefore checks "Create highlight" on `profile`, and a fan tile and "Go live" on home and new-post. (Rung 1: Python scan of `.b-story-item` buttons across `app/public/of-mirror/pages/**`.)

ASSUMPTION: the strip's non-own tiles show the Read-only note rather than navigating ("Go live" to `streaming`, "Create new trial link" to the trial-links modal), following the plan's "other story-strip buttons ... READ_ONLY" (rung 5); overturned if the human wants those tiles to become links.

ASSUMPTION: the non-own tiles show the Read-only note in All-Creators scope too, unlike `bindWrites`, which leaves non-writable controls alone there (rung 5: the note is true in both scopes and leaves no Silent control); overturned if Phase 6's fallback is meant to own all-Creators behaviour.

ASSUMPTION: binding is selector-keyed on every Mirror page, not a page list, so `home/state-*` and `new-post/state-*` get "Add to story" too (rung 5: no list to keep in step with recaptures); overturned if a State page's dialog should block the strip.

ASSUMPTION: a picked non-image file is refused client-side with a red note (rung 4: a refused send is reversible, an unexpected upload to a live account is not); overturned if the Relay is shown to accept video stories.

ASSUMPTION: the story code is a separate `useOfStory` hook in `ofMirrorPost`, not folded into Phase 0's new-post hook, because it must also run on `home` and `profile` (rung 5); overturned if Phase 0's hook already binds on every page.

ASSUMPTION: the check's single-Creator scope is `chatterly:scope` = `model:1` so the header is `X-Account-Id: 1` (rung 3: navigate.py/writes.py set scope this way; the plan fixes the id at 1).

## Review

codex — 2026-10-12 (blind call, then draft call; both exit 0)

Blind call:
- B1 Alternatives (two-call `/upload` + `/stories`, story from vault, keep read-only): **reject** — the plan fixes the one-call `stories/upload` route and excludes vault (plan:182-187); codex itself notes `post_story` needs a fresh non-deduped claim (of_client.py:3461-3475), which only the one-call route guarantees.
- B2 Enforce image-only; empty or missing MIME type: **partial** — client refusal was already decided; Input change now states an empty `type` is refused too. No Relay-side check added (Relay is out of this Phase's ownership).
- B3 No size policy or in-flight behaviour: **partial** — in-flight disable already in the spec (User Story 5); a size cap is rejected (YAGNI, rung 5): an oversize upload fails upstream and surfaces as `Could not add: <message>`.
- B4 Vault side effect of the fresh upload undefined: **reject** — already decided in Out of Scope (vault copy left as-is, route does not expose `return_upload`).
- B5 READ_ONLY on Create highlight must be tested, not just "nothing sent": **reject** — already in both seams (vitest and `story.py` assert the `READ_ONLY` note).
- B6 All-models file pick must show SELECT_MODEL: **reject** — already decided: in All-Creators scope no picker opens, so there is no file to pick; both seams assert `SELECT_MODEL`.
- B7 Cancel, `ready:false`, retry untested: **accept** — vitest now covers cancel and same-file retry (see D4); `ready:false` raises `OFAPIError` in `post_story` (of_client.py:3476-3477) and reaches the client as a non-2xx, already covered by the 500 error case.
- B8 Test at the iframe/Relay boundary: **accept** — already the spec's highest seam (`story.py`); unchanged.
- B9 Premise unverified (captures absent from the workspace; upstream may reject images): **reject** — captures were measured in this worktree (rung 1, Further Notes; every own/other tile is a plain `<button>` outside any `a[href]`, HTMLParser scan of home/new-post/profile index); a live upstream test is barred by floor 2 and the route choice is a plan constraint.

Draft call:
- D1 Blanket READ_ONLY on non-own tiles contradicts Phase 6's link/state-opener exclusion (plan:249-255): **reject** — measured: every non-own `.b-story-item` on home, new-post and profile is a `<button type=button>` with no `href` and no `a[href]` ancestor, so none is a link or state opener and Phase 6's fallback would give them `READ_ONLY` anyway.
- D2 State pages untested: **accept** — the vitest own-tile case now runs on every committed page carrying `.m-story-item-own` (13 pages: home index + 2 states, new-post index + 9 states), found by glob.
- D3 Not all read-only tiles tested: **accept** — the vitest read-only case now clicks every non-own tile on the three index pages, in both scopes; `story.py` keeps its three samples.
- D4 Cancel and same-file retry untested: **accept** — vitest asserts cancel adds no note and calls nothing, the input value is reset after resolve and reject, and a second same-file change uploads again.
- D5 Doc greps prove nothing about read-only wording: **partial** — Acceptance now also greps both docs for story + read-only; full prose correctness stays a review matter, not a grep.
- D6 Depends on: codex confirms it matches the plan (plan:103); no change.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- White, departure 4 ("Create highlight" exists only on `profile`): **accept** as fact. `story.py` checks it where it exists (Further Notes, rung 1); the plan is not edited, and the mismatch is listed under Open questions in `plan-review.md`.
- Black, duplicated read-only handling (the non-own tiles' note duplicates Phase 6's fallback): **partial**. The handler stays, because plan:187 names it in this Phase and `story.py` asserts it before Phase 6 exists. It carries no `data-oi-wired`. Phase 6 removes it once its fallback gives the same note (phase-06 Owns).
