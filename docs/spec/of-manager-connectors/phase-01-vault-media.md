# Phase 01 — media from the vault, thumbnails that load

**Objective.** In Single-Creator scope, the `new-post/state-vault` Mirror page shows the Creator's vault media with thumbnails loaded through the Relay, a tile click picks or unpicks that media in the Post draft, and the picked media show as thumbs in the composer and go out as `media_files` with the post.

## Problem Statement
On the OF Manager's New post page, "Add media from vault" opens a vault dialog full of grey placeholder tiles from the capture. Clicking a tile does nothing, search does nothing, and there is no way to attach the Creator's own photos or videos to a post. The Creator's real vault media are already loaded on the Vault page, but not here.

## Solution
"Add media from vault" opens the same dialog, now showing the Creator's vault (newest first) in OnlyFans's own tile markup, each picture loaded through the Relay's image proxy. Clicking a tile marks it selected with OnlyFans's own check mark; clicking it again unmarks it. Typing in the dialog's search box hides the tiles that don't match. "Close" returns to the composer, which shows the picked media as a row of small thumbs above the toolbar; "Post" sends them with the text. With all Creators selected the dialog keeps its example tiles and a tile click only says "Select a model to save changes".

## User Stories
1. As an operator in Single-Creator scope, I want "Add media from vault" to show the Creator's real vault media, so that I attach real content and not the capture's placeholders.
2. As an operator, I want every vault tile's picture to load through the Relay's `/img` proxy (or the Relay's own stored square), so that pictures render despite OnlyFans's IP-signed CDN URLs and no request goes to the OnlyFans CDN from the browser.
3. As an operator, I want each tile to show its date label as on the Vault page, so that I recognise recent media.
4. As an operator, I want a tile click to mark the tile with OnlyFans's selected state, so that I see what I picked.
5. As an operator, I want a second click on a picked tile to unpick it, so that I can correct a mistake.
6. As an operator, I want picks to survive leaving the dialog and coming back, so that tiles I picked earlier are still marked when I reopen it.
7. As an operator, I want picks recorded in the Post draft's `media_files` in click order, so that the post carries them in the order I chose.
8. As an operator, I want typing in the dialog's search box to hide tiles that do not match and clearing it to show all again, so that I find media in a long vault without a new request.
9. As an operator, I want "Close" to take me back to the composer with my text intact (Phase 0's draft restore) and the picked media shown as 64px thumbs above the toolbar, so that I see what will be attached.
10. As an operator, I want "Post" to send `media_files: [<id1>, <id2>]` as integer vault ids alongside my text, so that the post goes out with those media.
11. As an operator, I want the thumbs strip cleared after a successful post (Phase 0 clears the draft), so that the next post starts empty.
12. As an operator in All-Creators scope, I want the dialog to keep its example tiles and a tile click to send nothing and show "Select a model to save changes", so that nothing is attached for an unknown Creator.
13. As an operator, I want a Relay error on the vault list to leave the example tiles in place (existing `useOfData` behaviour), so that the dialog still renders.
14. As a maintainer, I want the vault dialog's data to reuse the Vault page's Data part, query and tile builder, so that there is one vault tile implementation.
15. As a maintainer, I want a Mirror check that proves the thumbs load, the picks reach the post body and nothing leaves localhost, so that a regression is caught headlessly.

## Implementation Decisions
- **Owns.** `ofMirrorData` (vault Data part on the vault dialog, tile id stamping, picked marks, the toggle helper); the vault-dialog part of `ofMirrorPost` (Phase 0's module: tile click, search filter, composer thumbs strip); a new Mirror check `post_vault.py`; the check README and `docs/routes.md` rows for this dialog.
- **Interfaces.**
  - `ofMirrorData.DATA_PAGES` gains `"new-post/state-vault": ["vaultMedia"]` (exact key; `partsOf("new-post/state-vault")` returns `["vaultMedia"]`, `partsOf("new-post")` stays `[]`). `vaultLists` is not added: the dialog's folder rows keep their examples (Out of Scope).
  - `MirrorData` gains `picked?: (number | string)[]` — vault ids currently in the draft. `applyVaultMedia` stamps every cloned tile with `data-oi-media="<id>"` and gives a tile whose id is in `picked` OnlyFans's `selected` class on the tile (`.b-photos__item.m-checkbox-control`) and on its `.checkbox-item` (both rules observed in the mirror's `app.css`). Selection is re-derived from `picked` on every apply, because `applyData` restores and rebuilds the grid on each data change.
  - `ofMirrorData` exports `toggleTile(tile: Element): boolean`: flips `selected` on the tile and its `.checkbox-item`, returns the new state.
  - `useOfData` reads `picked` from the Post draft (Phase 0's reader for `oi:new-post:<accountId>`) when the page is `new-post/state-vault`; the img builder stays `(u) => proxyImage(u, accountId)`; the vault media query (`/api/of/v2/vault/media?limit=24`, same query key as the Vault page) is reused unchanged.
  - `ofMirrorPost.bindPost` on `new-post/state-vault`: one delegated click listener on the frame document for `.b-photos__item`. Single-Creator scope and the tile has `data-oi-media`: `toggleTile`, then add or remove `Number(id)` in the draft's `media_files` and its thumb (the tile's own `<img>` `src`, already proxied) in the draft's thumbs, and save the draft. Example tile (no `data-oi-media`) or All-Creators scope: send nothing, `note(SELECT_MODEL)`. Tiles carry `data-oi-wired`.
  - Search: an `input` listener on `input[name='media_vault_search']` hides (`display:none`) every `[data-oi-media]` tile whose haystack does not contain the trimmed, case-folded query; empty query shows all. Haystack: the tile's date label text plus the media's `_ai.description` and `_ai.tags` when the Relay sends them (local mirror path). No Relay call, no new query param. Search only sets `display`; it never touches the draft, so a picked tile hidden by a query stays in `media_files` and stays marked when the query is cleared.
  - Composer thumbs: on every `new-post/*` load with a non-empty draft, `bindPost` inserts one row (`data-oi-data`, removed and rebuilt on each load) directly before `.b-make-post__actions`, holding one 64px square per draft thumb built by cloning a vault tile's `<img class="b-photos__item__img">` markup with `src` from the draft.
- **Schema.** None in any database. Post draft (Phase 0 owns the key and the rest of the shape); this Phase relies on:
  ```ts
  media_files: (number | Record<string, unknown>)[]  // vault ids here; Phase 2 appends upload claims
  thumbs: string[]                                    // thumbs[i] is the picture for media_files[i]
  ```
- **Contracts.** Reads `GET /api/of/v2/vault/media?limit=24` with `X-Account-Id` (existing, server.py `of_vault_media`), response `{list: VaultMedia[]}` or a bare array (`rowsOf`). Images via `GET /img?u=<OF url>&account_id=<id>` (server.py `proxy_image`) or the Relay's own `_thumb` (`/admin/vault-ai/thumb?account_id=…&media_id=…`, vault_ai_api.py `_overlay`), both same-origin through Next rewrites. Write: Phase 0's `POST /api/of/v2/posts` body with `media_files` filled, e.g. `{"text":"Synthetic post","media_files":[61,62],"price":0}`; `_CreatePostBody.media_files` is `list[int | dict]`, so vault ids go as integers.
- The dialog's own "Close" link (`/of-manager/new-post`) is the only way back; no "Add" button is added (the capture has none).
- A media with no usable picture (no `_thumb` and no `files.thumb|squarePreview|preview` URL) keeps the cloned tile's captured grey `data:image/svg+xml` placeholder src (existing `applyVaultMedia` only sets `src` when `tileThumb` returns one, ofMirrorData.ts:421-422); it is still pickable and its composer thumb is that placeholder. An empty vault list hides the examples and leaves the grid empty, as on the Vault page (`fill` with no clones, ofMirrorData.ts:111-123). A Relay error keeps the examples (story 13).
- Videos render with the photo tile (the dialog's capture has no video tile with a duration; `applyVaultMedia` already falls back to the photo template).
- No price, preview or paid-media options: Phase 0 sends `price: 0`.

## Testing Decisions
- **Seam 1 — `ofMirrorData` public interface (`partsOf`, `applyData`, `toggleTile`) in `app/lib/ofMirrorData.test.ts`**, against the captured `new-post/state-vault.html`:
  - `partsOf("new-post/state-vault")` is `["vaultMedia"]`; `partsOf("new-post")` is `[]`.
  - The existing "no data leaves the page as captured" `it.each` covers the new key automatically.
  - `applyData` with 3 synthetic media and an `/img?u=` builder: exactly 3 visible tiles, each with `data-oi-media` and an `/img?u=` src, no example tile visible; `restore` brings the examples back.
  - With `picked: [62]`: only tile 62 (and its `.checkbox-item`) has `selected`; re-applying with `picked: []` clears it.
  - `toggleTile` on an unselected tile returns `true` and marks it, again returns `false` and unmarks it.
  - Each applied tile on `new-post/state-vault` shows its media's `createdAt` day in `.b-element-label.m-timestamp` (story 3; asserted on this capture, not only the Vault page's).
  - A medium with no picture fields keeps a `data:` src and still carries `data-oi-media`; `applyData` with `[]` leaves no visible tile.
- **Seam 2 — Mirror check `scripts/of-mirror-check/post_vault.py`** (Playwright route mocks in the style of `data.py` and `writes.py`; scope `model:1`; unmocked `/api/**` returns `[]`; a `**/*` route fails the check on any non-localhost host): mock `GET /api/of/v2/vault/media` (3 synthetic items without `_thumb`, CDN URLs on `cdn.example.invalid`, one with `_ai.description` "synthetic beach") and `GET /img*` (a 1x1 PNG generated by the script). Checks, one JSON line each: every tile `<img>` has `naturalWidth > 0` and an `/img?` src carrying `account_id=1`; the vault request carries `X-Account-Id: 1`; search "beach" leaves 1 tile visible, clearing leaves 3; type "Synthetic post", open the dialog, pick 2 tiles, unpick and re-pick one (order follows clicks); search "beach" hiding a picked tile, then clearing, leaves both picks marked; Close shows 2 composer thumbs with `naturalWidth > 0` whose `src`s equal the picked tiles' `src`s in click order; reopen the dialog: exactly those 2 tiles carry `selected` (story 6), Close again; Post sends exactly one `POST /api/of/v2/posts` `{"text":"Synthetic post","media_files":[<id1>,<id2>],"price":0}` with `X-Account-Id: 1`; All-Creators pass: example tiles kept, no vault request, a tile click sends nothing and shows `SELECT_MODEL`; no console errors. Screenshots `/tmp/of-mirror-shots/post-vault-*.png`.
- Prior art: `app/lib/ofMirrorData.test.ts` (vault grid test, lines ~121-160), `scripts/of-mirror-check/data.py` (vault media and `/img` mocks), `scripts/of-mirror-check/writes.py` (recording non-GET bodies, all-models pass).
ASSUMPTION: Seam 1 also includes `ofMirrorPost.bindPost`'s public interface in `app/lib/ofMirrorPost.test.ts` (the vault dialog's tile click, search and composer thumbs, against the captured `new-post/state-vault.html` and `new-post` pages), since this Phase owns the vault-dialog part of `ofMirrorPost` (rung 3: tickets 08-10 put those tests there, beside Phase 0's `bindPost` tests). Overturned if the human wants the ofMirrorPost tests moved or the seam list left at `ofMirrorData.test.ts` only.

## Acceptance
```sh
cd <worktree root>/
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
node scripts/of-mirror.mjs --check
# manual: start the dev server in another shell first: cd app && npx next dev --webpack -p 3091
PORT=3091 python3 -I scripts/of-mirror-check/post_vault.py
PORT=3091 python3 -I scripts/of-mirror-check/post.py
PORT=3091 python3 -I scripts/of-mirror-check/data.py
PORT=3091 python3 -I scripts/of-mirror-check/writes.py
# manual: Read /tmp/of-mirror-shots/post-vault-*.png (OF's look kept, picked marks and composer thumbs visible)
```

## Depends on
- Phase 0 — provides `ofMirrorPost` (`bindPost` mounted in `OfMirrorFrame`), the Post draft in `sessionStorage` key `oi:new-post:<accountId>` with `media_files` and thumbs, draft restore on every `new-post/*` load, the Post button sending `POST /api/of/v2/posts`, draft clear on success, and `note`/`SELECT_MODEL` exported from `ofMirrorWrites`.

## Out of Scope
- Real folder rows in the dialog's left list (`vaultLists`) and filtering by folder — the plan names only `vaultMedia` for this page; folder rows link to the Vault page and would leave the composer (YAGNI).
- Server-side search via the Relay's `query=` param — the plan says client-side, no new query param.
- The dialog's type tabs (All / Photo / GIF / Video / Audio), sort, and "Retry" — not in the plan; Phase 6 gives silent ones the read-only note.
- Paging beyond the first 24 media — the Vault page shows the same 24; no infinite scroll (YAGNI).
- Removing a thumb from the composer strip directly — unpicking in the dialog does it (YAGNI).
- Upload from disk and its `send_with` claims — Phase 2.
- Price, previews, paid posts — the capture has no price control; Phase 0 sends `price: 0`.
- Story from vault — plan Constraints exclude it.

## Further Notes
- ASSUMPTION: OF's attached-media strip was not captured; the composer shows picked media as a row of 64px thumbs above `.b-make-post__actions`, built from the vault tile's own `<img>` markup (rung 2: decided in the plan, which flagged it). Overturned by a capture of OF's real attached-media markup.
- ASSUMPTION: the selected mark is OF's `selected` class on `.b-photos__item.m-checkbox-control` and its `.checkbox-item` (rung 1 for the classes existing in the mirror's `app.css`; rung 3 for which elements OF puts them on, since no selected state was captured). Overturned by a capture of a picked tile.
- ASSUMPTION: a tile whose media carries the Relay's `_thumb` keeps that src (existing `tileThumb` prefers it, ofMirrorData.ts:387-391). The plan says both "reuses `applyVaultMedia` and `tileThumb`" and "every `<img>` src is `/img?u=...`" (plan Phase 1 Decisions); those two conflict only when `_thumb` is present. Reuse wins because `_thumb` is a same-origin Relay path carrying `account_id`, which meets the sentence's purpose clause "never an OF CDN URL"; the check's synthetic items carry no `_thumb`, so every tile it sees is `/img?` (rung 3, house precedent `tileThumb`). Overturned if the human wants `/img` literally for every tile.
- Live thumbnail resolution is unverified: the check mocks `/img` with a 1x1 PNG, which proves the src is proxied and the page renders, not that real vault CDN URLs pass `proxy_image`'s host allowlist (server.py:3287-3297). Verifying that needs live OF (floor 2) and is left to the human.
- ASSUMPTION: the search haystack is the tile's date label plus `_ai.description` and `_ai.tags` (rung 5: the only text fields `VaultMedia` can carry; the live OF path has none, so search then only matches dates). Overturned by a wish for OF-native search (`query=`).
- ASSUMPTION: draft `thumbs` is index-aligned with `media_files` (rung 5: works for both vault ids and Phase 2's claim dicts without a key). Overturned if Phase 0's spec fixes another thumbs shape; this Phase then follows Phase 0.
- ASSUMPTION: `picked` is passed into `applyData` via `MirrorData` so selection survives `applyData`'s restore-and-rebuild on every data change (rung 3, house precedent: `chat`/`list` are passed the same way). Overturned if Phase 0 exposes the draft through another channel.

## Review
codex (gpt via `codex exec`, reasoning high), 2026-10-12. Blind call then draft call; workspace was the coordinator's sparse worktree.

Blind call:
- B1 alternatives (picker-specific renderer, React `VaultPicker`): **reject** — the plan's Phase 1 Decisions fix reuse of `applyVaultMedia`/`tileThumb` (constraint, not a choice); ADR-0006 wires the Mirror at runtime, not with React pickers.
- B2 whole-vault reach / server-side `query=` / paging past 24: **reject** — plan says "filters the loaded tiles client-side (no new query param)"; already in Out of Scope.
- B3 eligibility and missing/failed previews unspecified: **accept** — Implementation Decisions now state the no-picture tile keeps the captured `data:` placeholder and stays pickable; Seam 1 asserts it. Videos already covered.
- B4 selection details (order, duplicates, deselect, state across search): **partial** — order and toggle were specified; added that search never touches the draft and a hidden pick survives; Seam 2 now asserts it. Duplicates are impossible under toggle.
- B5 loading/empty/error states: **partial** — error keeps examples (story 13, existing); empty vault now stated (grid empty, as Vault page) and unit-tested. A loading indicator is not added: the Vault page has none (house precedent, YAGNI).
- B6 all-models not in acceptance: **reject** — Seam 2 already has the All-Creators pass (no vault request, examples kept, `SELECT_MODEL`).
- B7 test at the real iframe lifecycle seam with non-vacuous asserts: **accept** — Seam 2 is that seam; added reopen-after-Close, ordered thumb-src equality (see D2, D3).
- B8 falsifier: capture lacks the selectors `applyVaultMedia` needs: **reject** — observed: `grep -o` on `app/public/of-mirror/pages/new-post/state-vault.html` finds `vue-recycle-scroller__item-wrapper` 1x, `b-photos__item` 90x, `b-photos__item__img` 45x, `media_vault_search` 1x (codex could not see `app/public`).
- B9 falsifier: mocked 1x1 PNG does not prove real CDN URLs pass `/img`: **partial** — true; live OF is out of bounds (floor 2). Recorded as an unverified-live note in Further Notes for the human.
- B10 falsifier: selection lost across route transition: **accept** — Seam 2 now reopens the dialog and asserts the marks.

Draft call:
- D1 `_thumb` src contradicts the plan's "every src is `/img?`": **partial** — the plan contradicts itself (reuse `tileThumb`, which returns `_thumb` first, ofMirrorData.ts:387-391); kept reuse, rewrote the ASSUMPTION to name the conflict and the purpose clause it satisfies.
- D2 story 6 (picks survive reopen) untested: **accept** — Seam 2 reopens the dialog and asserts exactly the 2 picked tiles carry `selected`.
- D3 composer thumbs could be wrong-but-loaded: **accept** — Seam 2 asserts composer thumb `src`s equal the picked tiles' `src`s in click order.
- D4 date label (story 3) not asserted on the dialog capture: **accept** — Seam 1 asserts the timestamp label on `new-post/state-vault`.
- D5 Depends on: confirmed correct by reviewer; no change.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- White, departure 5 (tiles keep the Relay's `_thumb` src, not strictly `/img?`): **accept** as fact. The decision stays (Further Notes: the plan contradicts itself, and reuse of `tileThumb` is the plan's own); the plan is not edited, and the mismatch is listed under Open questions in `plan-review.md`.
- White, the live thumbnail allowlist is unverified: **accept**. Parked under Needs the human in `plan-review.md` (floor 2).
