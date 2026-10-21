# Phase 02 — Upload from disk

**Objective.** On the `new-post` Mirror page, OnlyFans's "Add media" button opens a file picker, the picked file uploads through the Relay's `POST /api/of/v2/upload`, and its `send_with` entries join the Post draft's media so the next Post sends them.

## Problem Statement

A Creator's manager on `/of-manager/new-post` sees OnlyFans's own "Add media" button (the picture icon at the left of the composer toolbar). Today it does nothing: there is no file input in the captured page, nothing uploads, and the only way to attach media is the vault (Phase 1). New material on disk, which is the usual case for a fresh post, cannot be posted from the OF mirror, although the Relay already uploads files to OnlyFans for chat and vault work.

## Solution

In Single-Creator scope, clicking "Add media" opens the system file picker (images and videos, one file per pick). The file uploads through the Relay at once. While it uploads, "Post" stays disabled. When the Relay accepts it, a thumb of the file appears in the composer's attached-media strip next to any vault picks, and the next Post sends it in `media_files` along with the text. If the Relay refuses the file (`ready:false`) or the request fails, a red note under the composer gives the Relay's reason, and nothing is attached. In All-Creators scope the button opens no picker and shows the Select-model note.

## User Stories

1. As a manager in Single-Creator scope, I want "Add media" on `new-post` to open a file picker, so that I can attach new material from my computer.
2. As a manager, I want the picker to offer images and videos only, so that I do not pick a file OnlyFans cannot post.
3. As a manager, I want one file per pick, so that each upload succeeds or fails on its own and I can see which one failed.
4. As a manager, I want the picked file to upload through the Relay with the selected Creator's account, so that it lands in that Creator's OnlyFans account and nowhere else.
5. As a manager, I want "Post" to stay disabled while an upload is in flight, so that I cannot post before the media is attached.
6. As a manager, I want "Post" to become enabled again once all uploads finish (when the editor has text), so that I can post as soon as the media is ready.
7. As a manager, I want an accepted upload's `send_with` entries added to the Post draft's media, after media already attached and in the order the uploads finish, so that the post carries every file I chose and nothing I did not.
8. As a manager, I want a file OnlyFans already has (a dedupe hit, whose `send_with` is a vault id) to be attached the same way as a fresh claim, so that I do not need to know which case happened.
9. As a manager, I want every `send_with` entry appended as the Relay returned it, even a vault id already attached, so that the post carries exactly what the Relay said to send.
10. As a manager, I want a thumb of the uploaded file in the composer's attached-media strip, so that I can see what the post will carry.
11. As a manager, I want the thumb shown from my own browser's copy of the file, so that no image is fetched from OnlyFans or any other host to show it.
12. As a manager, I want a thumb that cannot be shown (a video, or a page reload since the pick) shown as a plain grey square while the media stays attached, so that the strip never shows a broken image icon and never loses media.
13. As a manager, I want the uploaded media kept in the Post draft when I visit a State page (schedule, tag people, vault) and come back, so that I do not upload it again.
14. As a manager, I want a `ready:false` reply to show a red note with the Relay's `note`, so that I know why the file was not accepted.
15. As a manager, I want a failed upload request (Relay error, network error) to show a red note with the error message, so that I know the file was not attached.
16. As a manager, I want a failed or refused upload to attach nothing and leave the rest of the draft untouched, so that the post I send is exactly what I see.
17. As a manager, I want to pick the same file again after a failure, so that I can retry without renaming it.
18. As a manager in All-Creators scope, I want "Add media" to open no picker, upload nothing and show "Select a model to save changes", so that nothing is written to an unknown Creator.
19. As a manager, I want the Post that follows an upload to send the Relay's `send_with` entries unchanged in `media_files` with `X-Account-Id` of the selected Creator, so that OnlyFans can claim the uploaded file for the post.
20. As a maintainer, I want the "Add media" button marked as a Wired control (`data-oi-wired`), so that the Phase 6 click fallback leaves it alone.
21. As a maintainer, I want a Mirror check that drives the picker against a mocked Relay and asserts the exact multipart upload and the following post body, so that a recapture that changes the button's markup fails loudly.
22. As a maintainer, I want the upload merge rule covered by vitest, so that the order and mixed id/claim handling cannot regress silently.
23. As a maintainer, I want `docs/routes.md` and the check README to say that "Add media" uploads through the Relay, so that the docs list what writes.

## Implementation Decisions

- **Owns.** `ofMirrorPost` (the module Phase 0 creates; this Phase adds the upload part of `bindPost` and one pure helper). No other module changes. The Relay, `of_client`, `relay.ts` and `mediaUrl.ts` are used as they are.
- **Interfaces.**
  - `ofMirrorPost` exports a pure `mergeSendWith(mediaFiles, sendWith)` over `Array<number | Record<string, unknown>>`: returns a new array of `mediaFiles` followed by `sendWith`, order kept, nothing skipped or altered (plan Phase 2: "`send_with` entries are appended to `media_files`").
  - `bindPost` (Phase 0's binder) gains, on `new-post` only, the "Add media" wiring below. Its signature and unbind are unchanged; the unbind also removes the hidden input and its listeners.
  - The upload uses the existing `relay.uploadFile("/api/of/v2/upload", file, "file", { accountId })` typed with the existing `VaultUploadResp` (`ready`, `send_with`, `note`). No new relay method or type.
- **Schema.** None — the Post draft (Phase 0's `sessionStorage` key `oi:new-post:<accountId>`) already holds `media_files` and thumbs; uploaded entries are stored there like vault picks.
- **Contracts.**
  - Upload: `POST /api/of/v2/upload`, multipart, one part named `file` carrying the file with its own name and type; header `X-Account-Id: <accountId>` (from `relay.uploadFile`'s context). Relay route and `of_client.upload_media` exist and are not touched.
  - Response read: `ready` (boolean), `send_with` (array of vault ids and/or claim dicts `{processId, host, name, ...}`, read only when `ready === true`; on refusal the Relay sends `send_with: null` (`of_client.py:2973`) although `VaultUploadResp` types it as an array, so the code never touches it then), `note` (string, on refusal). Nothing else is read; a dedupe hit's `hidden` flag (`of_client.py:2742`) is ignored and the vault id attached like any other.
  - Post: unchanged Phase 0 body; `media_files` now may hold claim dicts, which `_CreatePostBody.media_files: list[int | dict]` accepts.
- **The control.** OnlyFans's `button.attach_file[aria-label='Add media']` in `.b-make-post__actions__btns` on `new-post` (index). The capture has no `type=file` input, so `bindPost` creates one hidden `<input type=file accept="image/*,video/*">` (no `multiple`) in the frame document and marks the button `data-oi-wired`. A click on the button, in Single-Creator scope, clicks the hidden input; in All-Creators scope it shows `SELECT_MODEL` via `note` and does nothing else.
- **On change.** One file is taken; the input's value is cleared at once (so the same file can be picked again). An in-flight counter goes up and Post is disabled; Post's enablement rule is Phase 0's (non-empty text) AND counter is 0. When the request settles the counter goes down and Post's state is recomputed.
- **Accept.** `ready === true` and a non-empty `send_with`: the draft's `media_files` becomes `mergeSendWith(draft.media_files, send_with)`, one thumb is added for the file, the draft is saved and the attached-media strip (Phase 1) is re-rendered.
- **Refuse / fail.** `ready` not true: red `note` with `Could not upload: <note>` (or `Could not upload: upload not ready` when the Relay gave no note). A thrown request: red note `Could not upload: <error message>`. The draft is not touched and no post is sent (plan Phase 2 acceptance: "a `ready:false` reply shows its note and sends no post").
- **Thumb.** `URL.createObjectURL(file)` called in the app's top window (the frame's document is replaced on every State page, the app's is not), passed through `proxyImage` (which returns `blob:` URLs unchanged), shown with Phase 1's 64px thumb markup. An `<img>` whose load fails (a video file, or a `blob:` URL dead after a full reload) is shown as a 64px grey square; its media stays in `media_files`. Object URLs are not revoked while the draft holds them; they die with the app tab.
- **Cross-document File.** The `File` comes from the frame's realm; code must not use `instanceof File` on it (fails across realms). `FormData.append` and `URL.createObjectURL` accept it.
- The State pages' copies of "Add media" (present on all nine `new-post/state-*` pages under the open dialog) are not wired by this Phase; see Further Notes.

## Testing Decisions

Two seams, both public: the Mirror check drives the real page against a mocked Relay (the highest seam, it covers wiring, scope, draft and post), and vitest covers the one pure rule the check cannot vary cheaply.

- **`ofMirrorPost.test.ts` (vitest, `mergeSendWith`).** Mixed ids and claim dicts appended in order; existing entries first; a number already present is still appended; empty `sendWith` returns an equal array; the input arrays are not mutated.
- **`scripts/of-mirror-check/post_upload.py` (Mirror check).** Same harness as `writes.py` (login mocks, "Tim" card for Single-Creator scope, scope key cleared before every load for All-Creators). Additionally every request whose host is not `localhost` fails the check. The script writes a 1x1 PNG to `/tmp` with stdlib `zlib`/`struct`. The multipart body is read from `request.post_data_buffer` and parsed with stdlib `email.parser.BytesParser` (no `cgi`, removed in Python 3.13). Prints one `{"check","want","got"}` line per check, exits 1 on any failure. Checks:
  1. Single-Creator: clicking "Add media" fires a file chooser (`page.expect_file_chooser`) whose element has `accept="image/*,video/*"` and no `multiple`; the button carries `data-oi-wired`.
  2. With the upload route held (the route object is kept and fulfilled later), after typing "Synthetic post": Post is disabled; after fulfilling `{"ready":true,"deduped":false,"vault_id":null,"send_with":[{"processId":"p1","host":"h","name":"n"}]}` Post is enabled and the strip shows one thumb whose `src` starts with `blob:`.
  3. The mock received exactly one `POST /api/of/v2/upload` with `X-Account-Id: 1`, one multipart part named `file`, filename the PNG's name, bytes equal to the PNG.
  4. Post sends exactly one `POST /api/of/v2/posts` with `X-Account-Id: 1` and JSON `{"text":"Synthetic post","media_files":[{"processId":"p1","host":"h","name":"n"}],"price":0}`.
  5. With text "Synthetic post" typed and one accepted upload already attached (claim `p2`), a second pick answered `{"ready":false,"send_with":null,"note":"Synthetic refusal"}`: red `#oi-note` contains `Synthetic refusal`; the strip still shows exactly one thumb; the editor still holds "Synthetic post"; the `oi:new-post:1` draft's `media_files` is still `[{"processId":"p2",...}]`; no `POST /api/of/v2/posts` is sent within 1s (Post is not clicked).
  6. Upload answered with HTTP 502: red `#oi-note` starts with `Could not upload:`, no thumb added; then the same PNG path is set on the input again and the mock receives a second `POST /api/of/v2/upload` (retry of the same file).
  7. All-Creators: clicking "Add media" fires no file chooser within 1s, sends no request to `/api/of/v2/upload`, and `#oi-note` reads `Select a model to save changes`.
  8. No console errors; no request left localhost.
  9. Dedupe hit: with vault id 42 already in the draft (seeded in `sessionStorage` before load), an upload answered `{"ready":true,"deduped":true,"vault_id":42,"send_with":[42]}`; Post sends `media_files: [42, 42]`.
  10. State-page round trip: after an accepted upload, navigate to `new-post/state-schedule` and back to `new-post`; the strip shows one thumb and Post sends the claim in `media_files`.
  11. Dead thumb: after an accepted upload, a full page reload leaves the strip with one 64px grey square (no `<img>` with `naturalWidth` 0 left visible) and the claim still in the draft's `media_files`.
  Screenshots to `/tmp/of-mirror-shots/inapp-post-upload*.png` (attached thumb, refusal note, all-Creators note), Read by the implementer, never committed.

Prior art: `scripts/of-mirror-check/writes.py` (mock harness, recorded non-GET bodies, scope passes, JSON check lines); Phase 0's `post.py` and Phase 1's `post_vault.py` once they land; `app/lib/ofMirrorWrites.test.ts` for lib vitest style.

## Acceptance

```sh
# Prerequisite (Check loop): the dev server on $PORT (default 3091).
export PORT="${PORT:-3091}"
(cd app && npx next dev --webpack -p "$PORT" > /tmp/of-mirror-next.log 2>&1 &)
until curl -fsS "http://localhost:$PORT/of-manager/new-post" > /dev/null; do sleep 2; done

pnpm -C app exec vitest run lib/ofMirrorPost.test.ts
python3 -I scripts/of-mirror-check/post_upload.py
python3 -I scripts/of-mirror-check/post.py
python3 -I scripts/of-mirror-check/post_vault.py
python3 -I scripts/of-mirror-check/writes.py
node scripts/of-mirror.mjs --check
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
grep -q "post_upload.py" scripts/of-mirror-check/README.md
grep -n "/api/of/v2/upload" docs/routes.md | grep -qi 'add media'
git diff --quiet -- app/public/of-mirror service
# manual: Read /tmp/of-mirror-shots/inapp-post-upload*.png — OnlyFans's composer look kept, thumb in the strip, notes visible.
```

## Depends on

- **Phase 0 — New post: text, schedule, tagged users.** Provides `ofMirrorPost` and `bindPost` mounted in `OfMirrorFrame`, the Post draft in `sessionStorage` (`media_files`, thumbs), Post's enablement and send, and `note` / `READ_ONLY` / `SELECT_MODEL` exported from `ofMirrorWrites`.
- **Phase 1 — media from the vault, thumbnails that load.** Provides the composer's attached-media strip (64px thumbs above `.b-make-post__actions`) that renders the draft's thumbs; uploads add to the same strip.

## Out of Scope

- A warning for a hidden dedupe hit (`hidden: true`) — attached like any vault id; see ASSUMPTION below.
- Several files per pick (`multiple`) — the plan says one file per pick; a second pick covers it.
- Removing an attached upload from the strip — no plan line asks for it; YAGNI.
- Upload progress bar or percentage — the disabled Post is the plan's in-flight signal.
- Video poster frames for thumbs — would need decoding in the browser; the grey square is enough.
- Waiting for OnlyFans's transcoder or polling the vault for the new id — the Relay's `send_with` claim is what the post body takes (server.py `_CreatePostBody`).
- Priced posts and previews from uploads — no price control exists in the capture (plan Phase 0).
- Reusing the stories upload route — the plan says posts do not reuse it; Add to story is Phase 3.
- Any Relay, `of_client` or `relay.ts` change — the route, method and response type already exist (Constraints: no new endpoint or body).
- Wiring the "Add media" copies on `new-post/state-*` pages — see Further Notes.
- Drag-and-drop onto the composer — not a captured control.

## Further Notes

- Ground truth check: `relay.ts:762` holds only an orphaned doc comment for the upload response; the type itself is `VaultUploadResp` at `app/lib/relay.ts:851` (`ready`, `deduped`, `vault_id`, `send_with`, `note`). All other cited lines verified: `relay.uploadFile` :171, `proxyImage` `blob:` pass-through `mediaUrl.ts:22-23`, `_CreatePostBody.media_files: list[int | dict]` `server.py:6161-6165`, `POST /api/of/v2/upload` `server.py:7661`, `upload_media` `of_client.py:2679` (dedupe hit `send_with: [vault_id]` :2747-2748, claim `send_with: [claim]` :2987-2988, `ready:false` + `note` :2967-2980). No app code calls `/api/of/v2/upload` today (grep over `app/`).
- Errors from the Relay arrive as HTTP 502 via `_proxy` (`server.py:1823`) and throw in `relay.ts`; a `ready:false` reply is HTTP 200, hence the two paths.

ASSUMPTION: the refusal note reads `Could not upload: <note>`, following Phase 0's `Could not post: <message>` wording (rung 3); overturned if the human wants the Relay's note verbatim.

- Open risk (not a decision): a dedupe hit for a vault id already attached appends it a second time, as the plan's "appended" rule requires; whether OnlyFans rejects a post with a duplicate `mediaFiles` id is unknown and needs a live post to observe (floor 2: not done here).

ASSUMPTION: a dedupe hit flagged `hidden` is attached with no warning (rung 5, the plan names only `ready:false` and errors as note cases); overturned if a live post with a hidden vault id fails or posts invisible media, in which case a hidden hit gets a red note and is not attached.

ASSUMPTION: the thumb is a `blob:` URL made in the app's top window, and a thumb that fails to load (video, or after a full reload) shows as a grey 64px square with its media still attached (rung 5, smallest thing that keeps the draft honest without storing file bytes in `sessionStorage`); overturned if OnlyFans's own attached-media strip is captured with a video or file placeholder to copy.

ASSUMPTION: only `new-post` (index) wires "Add media"; its copies on the nine `new-post/state-*` pages sit under the open dialog's backdrop and are left to the Phase 6 click fallback (rung 5); overturned if Phase 6's `dead.py` can click them at all (the fallback's Read-only note there would contradict the composer's working copy), in which case they get the same wiring (the draft is shared, so it is the same code path).

ASSUMPTION: Post stays disabled while any upload is in flight via a counter, and further picks are allowed meanwhile (rung 5, no extra UI); overturned if concurrent uploads prove to reorder `media_files` in a way the human objects to (merge happens in completion order).

## Review

codex, 2026-10-12 (blind call + draft call, `model_reasoning_effort=high`, read-only sparse workspace).

Blind call:
- B1 upload call lacks Creator context (`plan:165-167` two-arg call; `relay.ts:54-64,171-175`) — **accept**; already decided in Interfaces/Contracts (`{ accountId }` ctx), asserted by check 3.
- B2 Phase 0 `ofMirrorPost`/`bindPost` absent in this checkout — **accept**; already in Depends on (Phase 0, Phase 1).
- B3 Phase acceptance omits Check-loop items (exact headers, all-models pass, screenshots, README/routes) — **accept**; already covered by checks 3, 4, 7, the screenshots and the Acceptance greps.
- B4 thumbnail lifecycle across State pages unspecified — **accept**; already decided (top-window `blob:` URL, grey-square fallback); now tested by checks 10 and 11.
- B5 dedupe-hit and hidden-hit outcomes undefined; browser check only covers a fresh claim — **accept**; dedupe now tested (check 9); hidden hit decided as attach-without-warning, flagged ASSUMPTION and listed in Out of Scope.
- B6 `accept` is not server validation; test an upload exception, not only `ready:false` — **partial**; check 6 already covers the thrown (502) path; type validation stays with the Relay, which this Phase does not touch (plan Constraints: no new endpoint or body).
- B7 test seam is the browser-to-relay Playwright check — **accept**; that is the spec's Mirror check.
- B8 also test that claim dicts reach `create_post` unchanged (`of_client.py:2368` annotates `list[int]`) — **reject**; Relay and `of_client` are untouched and `_CreatePostBody.media_files: list[int | dict]` (`server.py:6161-6165`) already accepts dicts; a service test is scope the plan never asked for.

Draft call:
- D1 check 5 clicks Post after a refusal and expects a post, contradicting plan "a `ready:false` reply shows its note and sends no post" (`plan:171-176`) — **accept**; check 5 rewritten to assert no post request; Refuse/fail now says no post is sent.
- D2 refusal fixture's `send_with: null` contradicts the array contract (`of_client.py:2965-2980`, `relay.ts:851-859`) — **accept**; Contracts now say `send_with` is read only when `ready === true` and is null on refusal.
- D3 skipping an already-attached vault id contradicts the plan's "appended" and Story 19's "unchanged" (`plan:165-167`, `of_client.py:2744-2749`) — **accept**; `mergeSendWith` is now a plain append (plan constraint, rung 2); Story 9, the vitest list and the old ASSUMPTION rewritten; OnlyFans's handling of duplicate ids recorded as an open risk in Further Notes.
- D4 refusal check cannot prove the draft is preserved — **accept**; check 5 now seeds text and an attached upload and asserts both survive.
- D5 Stories 17, 13, 8, 12 have no seam assertion — **accept**; check 6 (retry same file), 10 (State round trip), 9 (dedupe hit), 11 (dead thumb) added.
- D6 docs greps only prove strings exist (`plan:100-101`) — **partial**; the routes grep now requires the upload row to mention "Add media"; the remaining prose stays with Check loop step 3 (implementer writes and Reads it), since grep cannot judge prose.
- Depends on: reviewer found it neither missing nor false — no change.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- Black, "Add media" is wired on the composer but read-only on its 9 State page copies: **partial**. The copies sit under the open dialog, and the decision stays (rung 5). The overturn clause is tightened: if `dead.py` can click a copy at all, it gets the same wiring, because a Read-only note there would contradict the working composer copy (Further Notes).
- Black, a dedupe hit appends a duplicate media id, which can't be undone once posted: **reject** as a change. The plan says `send_with` entries are "appended" (plan:166-167), and the codex D3 finding already settled that on rung 2. Whether OnlyFans accepts a duplicate id is parked under Needs the human in `plan-review.md`.
