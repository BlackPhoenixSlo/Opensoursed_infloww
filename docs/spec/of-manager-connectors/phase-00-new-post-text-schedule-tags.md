# Phase 00 — New post: text, schedule, Co-tags

**Objective.** On the `new-post` Mirror page in Single-Creator scope, a Creator's operator can write a post, schedule it in the captured calendar dialog, pick Co-tags from the Relay's list, and press Post to send exactly one `POST /api/of/v2/posts` with the Known body. Every other new-post control this Phase touches answers with the Read-only note.

## Problem Statement

The OF Manager's New post page looks like OnlyFans's composer but does nothing. The editor takes text, but "Post" stays disabled. "Schedule post" opens a calendar whose days, Next and Save for Later are dead. "Tag other creators" lists 50 scrubbed example rows, not the Creator's real taggable creators. "Add labels", poll, quiz, expiration, target, format, voice and video do nothing and give no reason. An operator who uses Infloww's OF Manager to post "on behalf of the Creator" (docs/infloww-screens.md §3.2) cannot do it here. The only way to post is the app's separate PostComposer.

## Solution

On `new-post` and every `new-post/state-*` page, with one Creator selected:
- Typing in OnlyFans's editor enables Post, and the text survives moves to and from the State pages as the Post draft.
- The schedule dialog shows a working calendar for the current month. Clicking a day selects it, the time tab takes a typed time, and Next stores the schedule and returns to the composer. The composer then shows a one-line summary with a Clear link.
- The tag dialog lists the Creator's taggable creators from the Relay. A checked row adds that creator as a Co-tag.
- Post sends the Known body. An immediate post lands on My profile, and a scheduled one lands on the Queue. On failure, Post is enabled again, a red note shows the error, and the draft is kept.
- Labels rows, Save for Later, the poll, quiz, expiration, target and format panels, and Record voice and Record video send nothing and show "Read-only in Inflowwww for now".

In All-Creators scope nothing is sent. Post, Next and the tag rows show "Select a model to save changes", and the tag dialog keeps its Example rows.

## User Stories

1. As an operator, I want typing in the New post editor to enable Post, so that I can publish without leaving the OF Manager.
2. As an operator, I want Post to stay disabled while the editor is empty or whitespace only, so that I cannot send an empty post.
3. As an operator, I want the editor's placeholder to disappear once I type and come back when I clear it, so that the composer behaves like OnlyFans's.
4. As an operator, I want Post to send `POST /api/of/v2/posts` with `{text, media_files: [], price: 0}` for the selected Creator, so that the post goes out through our Relay on that Creator's session.
5. As an operator, I want multi-line text sent as its paragraphs joined by newlines, with outer whitespace trimmed, so that the post reads as I typed it.
6. As an operator, I want no price control and `price: 0` always, so that a subscription page is never refused for a priced post (the capture has no price control).
7. As an operator, I want my text kept when I open Schedule, Tag other creators, Add labels or any other State page and come back, so that I do not retype it.
8. As an operator, I want the Post draft kept per Creator, so that switching Creators does not mix drafts.
9. As an operator, I want the schedule dialog to show the current month with past days disabled, so that I pick a real future date even though the capture is from another month.
10. As an operator, I want the calendar's previous and next arrows to change the month (never before the current month), so that I can schedule beyond this month.
11. As an operator, I want clicking an enabled day to mark it selected and update the dialog's header date, year and date tab, so that I see what I picked.
12. As an operator, I want to type a time such as "6:30 pm" or "18:30" into the time tab, so that I can set the hour without OnlyFans's uncaptured time picker.
13. As an operator, I want Next to store the chosen moment as local ISO with offset and take me back to the composer, so that the post is scheduled.
14. As an operator, I want Next to refuse a moment less than a minute ahead, or an unreadable time, with a red validation note, so that I never schedule into the past.
15. As an operator, I want the composer to show "Scheduled for <date time>" with a Clear link once a schedule is set, so that I know the post will be scheduled and can undo it.
16. As an operator, I want Cancel and the backdrop in the schedule dialog to return without changing the stored schedule, as OnlyFans does.
17. As an operator, I want Save for Later to show the Read-only note and send nothing, because the Relay has no write for it.
18. As an operator, I want the tag dialog to list the Creator's taggable creators from `GET /api/of/v2/posts/tagged-friend-users` in OnlyFans's own row markup, so that I tag real creators.
19. As an operator, I want each tag row to show the creator's name and @username and to be checked if it is already a Co-tag in the draft, so that the dialog reflects my picks.
20. As an operator, I want checking a row to add that creator's OnlyFans user id to the draft's `tagged_users`, and unchecking it to remove the id, so that Post tags exactly the creators I picked.
21. As an operator, I want the composer summary to name my Co-tags, so that I can see who is tagged before posting.
22. As an operator, I want the Example rows kept, with checking one giving the Read-only note, when the Relay list fails or is still loading, so that no scrubbed example is sent as a tag.
23. As an operator, I want Post with a schedule and Co-tags to send `posted_at` and `tagged_users` along with the text, so that one request does it all.
24. As an operator, I want an immediate post to land on `/of-manager/profile` and a scheduled one to land on `/of-manager/queue`, so that I see where it went.
25. As an operator, I want the draft cleared after a successful post, so that the next post starts empty.
26. As an operator, I want Post disabled while the request is in flight, so that a double click sends only one post.
27. As an operator, I want a failed post to show a red "Could not post: <message>" note, enable Post again and keep my draft, so that I can retry.
28. As an operator, I want Post to re-check that a stored schedule is still at least a minute ahead, so that a stale draft is not sent into the past.
29. As an operator, I want "Add labels" rows to show the Read-only note and flip back, because `create_post` has no labels field.
30. As an operator, I want the poll, quiz, expiration, target and format panels' fields and buttons to show the Read-only note, because their bodies are unknown.
31. As an operator, I want Record voice and Record video to show the Read-only note.
32. As an operator in All-Creators scope, I want Post, Next and the tag rows to send nothing and show "Select a model to save changes" (a row flips back), and the tag dialog to keep its Example rows with no Relay call, so that nothing is posted to an unknown Creator.
33. As a maintainer, I want every committed Mirror page unchanged and all wiring done at runtime, so that `node scripts/of-mirror.mjs --check` stays green (ADR-0006).
34. As a maintainer, I want a Mirror check `post.py` to assert the exact method, path, `X-Account-Id` and JSON the mocked Relay got, to cover All-Creators scope, and to fail on any non-localhost request, so that a recapture that breaks a selector fails loudly.
35. As a maintainer, I want the check README and `docs/routes.md` to say what New post writes and what is read-only.

## Implementation Decisions

- **Owns.**
  - New module `ofMirrorPost` (app lib): the Post draft, the composer, schedule and tag bindings, and the `useOfPost` hook.
  - `ofMirrorWrites`: exports only, no behaviour change.
  - `OfMirrorFrame`: mounts `useOfPost`.
  - Mirror check `post.py` and the check README.
  - The OF Manager rows of `docs/routes.md`.
- **Interfaces.**
  - `ofMirrorWrites` additionally exports `note`, `READ_ONLY`, `SELECT_MODEL` and `textOf`. `parseTime`, `localIso` and `QUEUE` are already exported. None of them is copied.
  - `ofMirrorPost` exports:
    - `PostDraft`: `{ text: string; posted_at?: string; tagged_users: number[]; media_files: Array<number | Record<string, unknown>>; thumbs: string[] }`. `media_files` and `thumbs` stay empty in this Phase and are filled by Phase 1 and Phase 2.
    - `CreatePostBody`: `{ text: string; media_files: Array<number | Record<string, unknown>>; price: 0; posted_at?: string; tagged_users?: number[] }`. Absent keys are omitted, never `null`.
    - `draftKey(accountId)` returns `"oi:new-post:<accountId>"`. `loadDraft(storage, accountId)`, `saveDraft(storage, accountId, draft)` and `clearDraft(storage, accountId)` take a `Storage`, so tests pass their own.
    - `collectPost(text, draft, now?)` returns `CreatePostBody` or a validation string. Empty trimmed text gives the string. A `posted_at` less than 60 s ahead gives "Pick a time at least a minute from now".
    - `collectSchedule(doc, now?)` returns a local ISO string or a validation string. It reads the selected calendar day, the shown month and year, and `parseTime` of the time tab.
    - `renderCalendar(doc, month, selected, now)` rebuilds the day grid from a captured day cell.
    - `applyTagRows(doc, items, picked)` clones the first captured tag row per item and hides the examples.
    - `PostHandlers`: `{ createPost(body): Promise<unknown>; navigate(href): void }`.
    - `bindPost(doc, page, ctx)` returns an unbind function. `ctx` is `{ handlers: PostHandlers | null; storage: Storage | null; accountId: string | null; tagItems?: TaggedFriendUser[] }`. A `null` handlers value means All-Creators scope.
    - `useOfPost(frameRef, src)` binds on every frame load of `new-post` and `new-post/state-*`.
- **Schema.** None. The draft is `sessionStorage` JSON of the shape `PostDraft`, under `draftKey`.
- **Contracts.**
  - Write: `POST /api/of/v2/posts` through `relay.post` with `{ accountId }`, so it carries `X-Account-Id`. The body is the Relay's `_CreatePostBody` subset above, as PostComposer sends it. `posted_at` is `localIso` (for example `2026-10-13T18:30:00+02:00`). `tagged_users` holds OnlyFans user ids.
  - Read: `GET /api/of/v2/posts/tagged-friend-users?limit=50&offset=0`, typed by the existing `TaggedFriendUsersResp`. Only on `new-post/state-tag-people`, only in Single-Creator scope, through react-query (`staleTime` 60 s, `retry: false`, as `useOfData`). The row id is `user.id ?? id`, the same rule as TagCreatorsPicker. The row name is `user.name ?? name ?? user.username`, and the @line is `@<user.username>`.
  - No new Relay route or field, and no new OnlyFans endpoint (ADR-0005).
- **Composer (every `new-post/*` page).**
  - The editor is `[contenteditable][aria-label='Textbox field']`.
  - On load, the draft's text is restored as one `<p>` per line.
  - On every input, the draft is saved, `data-is-empty` and the wrapper's `m-empty` are kept in step, and Post (`button[at-attr='submit_post']`) is enabled exactly when the trimmed text is non-empty.
  - Post click (default prevented):
    - All-Creators scope: the `SELECT_MODEL` note.
    - Invalid: the red validation note.
    - Otherwise Post is disabled, `createPost` is called, and on success the draft is cleared and the browser navigates to `QUEUE` if `posted_at` is set, else to `/of-manager/profile`.
    - On error: Post is enabled again, a red `Could not post: <message>` note shows, and the draft is kept. The message is the Relay's own text, so OnlyFans's `Please allow 10 seconds` throttle (service/of_client.py:80-84) reaches the operator verbatim.
    - No idempotency key exists on the route (service/server.py `_CreatePostBody`), so a failure after OnlyFans accepted the post cannot be told apart from a real failure; a retry may post twice.
ASSUMPTION: rung 5. No new Relay field (ADR-0005, plan YAGNI). Overturned if live use shows ambiguous failures are common, in which case the Relay grows a dedupe key in its own Phase.
  - With `posted_at` or Co-tags in the draft, a one-line summary shows under the editor:
    - Shape: "Scheduled for Tue, Oct 13, 6:30 PM · Tagged: Alpha One · Clear".
    - Styling: `note`'s grey style, persistent, id `oi-post-summary`.
    - Clear removes `posted_at` and `tagged_users` from the draft.
  - Post, Next and the cloned tag rows (those with `data-oi-user`) carry `data-oi-wired`. Example tag rows and this Phase's read-only controls do not: a marked control must never show the Read-only note (Phase 6's `dead.py` fails it).
- **Schedule (`new-post/state-schedule`).**
  - The capture is a vue-datetime popup with a static October 2026 grid and tabs "Oct 12, Mo" and "5:15 AM". Its only text input is vue-datetime's empty trigger field `input.vdatetime-input`, not a typed date or time field (observation: `grep -o '<input[^>]*>' app/public/of-mirror/pages/new-post/state-schedule.html`). It is left untouched.
  - On load the grid is re-rendered for the month of the draft's `posted_at`, or else the current month. The rules:
    - Sunday-first leading blanks, as the captured weekday row.
    - Days before today get `--disabled`.
    - The selected day gets `--selected`.
  - The navigation arrows move one month, and never before the current month.
  - The time tab becomes `contenteditable`, pre-filled with the draft's time or, failing that, now plus one hour, formatted `h:mm AM`.
  - Next:
    - All-Creators scope: the `SELECT_MODEL` note.
    - Otherwise `collectSchedule` runs. A string result gives the red note. An ISO result is saved as `posted_at`, and the browser navigates to `/of-manager/new-post`.
  - Save for Later gives the `READ_ONLY` note. Cancel and the overlay keep their captured links.
- **Tag people (`new-post/state-tag-people`).**
  - In Single-Creator scope with items loaded, `applyTagRows` fills the list. Each clone carries `data-oi-user="<id>"`, and its checkbox reflects the draft. An empty list hides all rows.
  - A row's change event toggles its id in `tagged_users` (operator order kept, no duplicates).
  - A change on an example row, which has no `data-oi-user` (the Relay failed or is still loading), gives `READ_ONLY` and flips back.
  - In All-Creators scope a row change gives `SELECT_MODEL` and flips back.
- **Read-only controls.**
  - On `new-post/state-labels`, row checkboxes give `READ_ONLY` and flip back.
  - On `state-poll`, `state-quiz`, `state-expiration`, `state-target` and `state-format-text`, a `change` on a field other than the editor resets it and gives `READ_ONLY`. A click on a non-link button inside the open panel or dialog ("+ Add another option", Reset, Done) gives `READ_ONLY`.
  - On every `new-post/*` page, Record voice and Record video give `READ_ONLY`.
  - These read-only handlers are interim. When Phase 6's click fallback and widened change path land, Phase 6 removes any of them that gives the same note and flip-back, so a toggle flips back exactly once. `post.py`'s read-only asserts stay unchanged; after Phase 6 the note comes from `bindWrites`.
- **Mounting.** `useOfPost` is mounted in `OfMirrorFrame` next to `useOfWrites`. Like `useOfWrites` (app/lib/ofMirrorWrites.ts:303-319), its effect depends on `accountId`, so a scope change while a `new-post/*` page is open unbinds and rebinds: the editor then shows the new Creator's draft (or empty in All-Creators scope), and the old Creator's draft stays under its own key. It uses the parent window's `sessionStorage` and `useRouter().push` for navigation. `useOfWrites` and `useOfData` do not match `new-post/*` today (`useOfWrites` binds only settings pages and SUBMITS pages, and `DATA_PAGES` has no new-post entry), so the bindings do not overlap.

## Testing Decisions

- **Seam 1, `ofMirrorPost` pure exports plus `bindPost` (vitest, jsdom).** Test file: `app/lib/ofMirrorPost.test.ts`. Fixtures are the committed captures `new-post/index.html`, `state-schedule.html`, `state-tag-people.html` and `state-labels.html`, loaded with `readFileSync` the way `ofMirrorWrites.test.ts` does. The tests cover:
  - `collectPost`: text only gives exactly `{text, media_files: [], price: 0}`. Scheduled adds `posted_at`. Tagged adds `tagged_users`. Empty or whitespace text gives the validation string. A past `posted_at` gives the note.
  - Draft round-trip through an in-memory `Storage`, keyed per account, and `clearDraft`.
  - `bindPost` on index: typing enables Post, and clearing disables it. Post calls `createPost` once with the body, then calls `navigate("/of-manager/profile")` and clears the draft. A scheduled draft navigates to `QUEUE`. A rejection enables Post again, shows a red note starting `Could not post:` and keeps the draft. `handlers: null` gives the `SELECT_MODEL` note and no call.
  - Schedule: `renderCalendar` for a fixed `now` disables past days. The previous arrow on the current month stays on it, and the next arrow shows the following month. Clicking a day marks it `--selected` and updates the header date, year and date tab. Picking tomorrow, typing "6:30 pm" and pressing Next saves `localIso` of tomorrow 18:30. A time one minute ago gives the note, and an unreadable time ("abc") gives the note and saves nothing.
  - Stale schedule: a draft whose `posted_at` is now past makes Post show the note and call `createPost` zero times.
  - Tags: `applyTagRows` hides the examples and renders one row per item with its id, with the row of an id already in the draft rendered checked. Checking a row adds the id to the draft, and unchecking removes it. With no `tagItems`, checking an example row gives `READ_ONLY`, flips back and leaves `tagged_users` empty. With `handlers: null`, a row change gives `SELECT_MODEL` and flips back.
  - Summary: a draft with `posted_at` and tag 901 ("Alpha One") shows `#oi-post-summary` containing "Scheduled for" and "Alpha One"; its Clear empties both.
  - Read-only, one case per fixture: on `state-labels` a checkbox change, and on each of `state-poll`, `state-quiz`, `state-expiration`, `state-target` and `state-format-text` a field change and a non-link button click inside the open panel, each give `READ_ONLY` and call no handler. On `index`, Record voice and Record video give `READ_ONLY`. The fixtures for these pages join the list above.
- **Seam 2, Mirror check `scripts/of-mirror-check/post.py`.** It drives the real app frame against a mocked Relay in the style of `writes.py` and `data.py`, with scope `model:1`, synthetic tag items "Alpha One" (901) and "Beta Two" (902), and every unmocked `/api/**` returning `[]`. Any request to a host other than localhost is aborted and fails the check. It prints one JSON line per check. The cases:
  - **Run 1.** Post is disabled at first. Type "Synthetic post" and press Post. Exactly one `POST /api/of/v2/posts` arrives with `{"text":"Synthetic post","media_files":[],"price":0}` and `X-Account-Id: 1`, the page lands on `/of-manager/profile`, and the draft key is gone.
  - **Run 2.** Type the text, then open Schedule, move to tomorrow, click it, type "6:30 pm" and press Next. Back on the composer the text is restored and the summary is shown. Open Schedule again and press Cancel: the summary is unchanged. Open Tag other creators: it shows Alpha One and Beta Two and no `List ` example text. Check Alpha One and Close: the summary contains "Alpha One". Press Post. Exactly one POST arrives with `posted_at` equal to Python's `datetime(...,18,30).astimezone().isoformat()` and `tagged_users: [901]`, and the page lands on `/of-manager/queue`.
  - **Validation.** Next with a time already past sends nothing and shows the note.
  - **Tag list failure.** With `tagged-friend-users` mocked to 502, the tag dialog keeps its Example rows, and checking one shows `READ_ONLY`, flips back, and a following Post carries no `tagged_users`.
  - **Error.** With the mock returning 502, the page shows the red `Could not post:` note, Post is enabled again, and the draft is kept.
  - **Read-only.** A labels checkbox, Save for Later and a poll option each send nothing and show `READ_ONLY`.
  - **All-Creators scope** (scope key removed). Post and Next send nothing and show `SELECT_MODEL`. The tag dialog keeps its Example rows, checking one shows `SELECT_MODEL` and flips back, and no `tagged-friend-users` request is made.
  - Screenshots go to `/tmp/of-mirror-shots/inapp-post-*.png`.
- **Prior art.** `app/lib/ofMirrorWrites.test.ts` (capture fixtures, `bindWrites` with mocked handlers, `collectStream` past-time note), `app/lib/ofMirrorData.test.ts` (template row cloning), `scripts/of-mirror-check/writes.py` (write recording, all-models pass, tomorrow 6:30 pm ISO) and `scripts/of-mirror-check/data.py` (`model:1`, `X-Account-Id` assertion).

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
export PORT="${PORT:-3091}"
pnpm -C app exec vitest run lib/ofMirrorPost.test.ts lib/ofMirrorWrites.test.ts
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
node scripts/of-mirror.mjs --check
test -z "$(git status --porcelain -- app/public/of-mirror)"   # no Mirror page hand-edited
(cd app && npx next dev --webpack -p "$PORT" >/tmp/oi-next-post.log 2>&1 &)
until curl -sf "http://localhost:$PORT/" >/dev/null; do sleep 2; done
python3 -I scripts/of-mirror-check/post.py
python3 -I scripts/of-mirror-check/writes.py
grep -q "post.py" scripts/of-mirror-check/README.md
grep -A40 "post.py" scripts/of-mirror-check/README.md | grep -qi "read-only"
grep -q "api/of/v2/posts" docs/routes.md
grep -q "tagged-friend-users" docs/routes.md
grep -i "new-post" docs/routes.md | grep -qi "read-only"
# manual: Read the README's post.py section and the routes.md new-post rows; they must name what Post writes and each read-only control
# manual: Read /tmp/of-mirror-shots/inapp-post-*.png (OF's look kept, summary line and notes visible; never committed)
```

## Depends on

None. This is the first Phase. Phase 1 and Phase 2 extend `PostDraft.media_files` and `thumbs`, and Phase 3's story code lives in `ofMirrorPost`.

## Out of Scope

- **Price control and paid posts, and `previews`.** The capture has no price control, and a paid page refuses priced posts.
- **Media from the vault and from disk.** Those are Phase 1 and Phase 2. "Add media" (disk) is left untouched here so that Phase 2 owns it.
- **Labels, Save for Later, poll, quiz, expiration, target, format, voice and video writes.** There is no Known body for them, so they are read-only (ADR-0005).
- **The tag dialog's search, Sort, "Release form" tab, "Invite new user" and row "More" menus.** There is no Known body for them and the plan does not name them. Phase 6's click fallback gives them the Read-only note.
- **Tag-row avatars through `/img`.** The rows keep the capture's grey placeholder avatar (YAGNI). Real thumbs are Phase 1's concern for vault media only.
- **A tag search query (`search=`).** The first 50 rows match the capture's 50. Paging is not needed for the stated goal.
- **Refreshing profile or queue data after posting.** Those Data parts are Phase 4's.
- **An all-Creators fan-out post.** Writes happen only in Single-Creator scope.
- **Editing, deleting or pinning existing posts.** Excluded by the plan's YAGNI constraint.

## Further Notes

**The Post draft.** It is stored only in Single-Creator scope. In All-Creators scope, text typed and then left for a State page is lost.
ASSUMPTION: rung 5. Nothing can be sent there, so a draft key with no account buys nothing. Overturned if operators draft in All-Creators scope and then pick a Creator.

**The plan says the schedule dialog's "date and time fields" are parsed with `parseDate` and `parseTime`.** The capture has no date or time input (observation: `new-post/state-schedule.html` has only the vue-datetime calendar, with tabs "Oct 12, Mo" and "5:15 AM"). So the date comes from the selected calendar day and the shown month, and only `parseTime` is used, on the time tab.
ASSUMPTION: rung 5 against the plan's wording. Overturned if a recapture shows typed date and time inputs, in which case `parseDate` is used on them.
The plan's line 118 ("date and time fields are parsed with `parseDate`/`parseTime`") still says otherwise; the coordinator reconciles the plan's wording to this decision, since the plan named fields the capture does not have (rung 1 beats the plan's premise, not its goal).

**A mocked Relay proves the request, not that OnlyFans publishes or queues the post.** Live verification of one immediate and one scheduled post with a Co-tag is parked for the human (floor 2); `of_client.create_post` maps `posted_at` and tags upstream (service/of_client.py:2368-2399).

**The calendar is re-rendered at runtime for the current month.** The captured grid is a fixed October 2026, with days before the 12th disabled.
ASSUMPTION: rung 5 (runtime DOM per ADR-0006, cloned from the captured day cell). Overturned if the human wants the captured month kept and only its days wired.

**The time tab is made `contenteditable`.** OnlyFans's own time picker was not captured.
ASSUMPTION: rung 5, the smallest piece the plan's "time field" needs. Overturned by a capture of OF's time body, which would then be wired instead.

**The composer summary line ("Scheduled for … · Tagged: … · Clear") is new UI outside OF's markup.** OnlyFans's scheduled-post chip was not captured.
ASSUMPTION: rung 5. Without it the user cannot see or undo a schedule before posting. Overturned by a capture of OF's chip.

**A checked example tag row (Relay failed or loading) gives `READ_ONLY` and flips back.**
ASSUMPTION: rung 4. Never send a scrubbed example's missing id. Overturned if an error note is preferred.

**The tag row id is `user.id ?? id`.**
ASSUMPTION: rung 3 (TagCreatorsPicker `toChoice`). Overturned if the Relay's top-level `id` differs from `user.id` for a tag.

**Text is trimmed, and keys with no value are omitted rather than sent as `null` (PostComposer sends `posted_at: null`).**
ASSUMPTION: rung 3 and the plan's exact body `{"text":"Synthetic post","media_files":[],"price":0}`. Overturned if the Relay's handling differs (it defaults both).

**This Phase's Wired controls carry `data-oi-wired` already.** Phase 6 owns the mark's contract (plan:253 names it only there) and adds any mark a binder misses; this Phase sets it early, on its own Wired controls only.
ASSUMPTION: rung 4, additive. Overturned if Phase 6 chooses another marker.

**The tag list request is `limit=50&offset=0`.**
ASSUMPTION: rung 5. 50 is the Relay's maximum, and the capture shows 50 rows. Overturned if paging is wanted.

**`textOf` is exported from `ofMirrorWrites`, alongside the plan's `note`, `READ_ONLY` and `SELECT_MODEL`.**
ASSUMPTION: rung 5. The plan cites it for the body text, and copying it would duplicate code. Overturned by none expected.

## Review

codex (gpt via `codex exec`, reasoning high), 2026-10-12. Blind call then draft call; both exited 0 with fresh output.

Blind call:
- B1 Alternatives (reuse PostComposer; leave posting read-only): **reject**. The plan binds the runtime `ofMirrorPost` hook (plan:103-125) and ADR-0006 runtime wiring; the reviewer itself names it the fit.
- B2 When the draft is saved before navigation is unspecified: **reject**. Composer saves on every input, tag rows on every change, and Next saves `posted_at` before navigating (Implementation Decisions).
- B3 Co-tag search and paging left out: **reject**. Already Out of Scope with reason (first 50 match the capture's 50).
- B4 Double submit and ambiguous failure, 10 s OF throttle: **partial**. In-flight disable was already story 26; accepted a written decision that the throttle text surfaces verbatim and that no dedupe key is added (new ASSUMPTION under Composer).
- B5 Scope change while the page is open: **accept**. Mounting now states the `accountId`-keyed rebind, as `useOfWrites` (app/lib/ofMirrorWrites.ts:303-319).
- B6 Schedule DST and invalid dates: **reject**. Dates come only from enabled calendar cells, and `localIso` takes the offset at the chosen moment; unreadable time is now tested (D1).
- B7 Test at the iframe-to-mocked-Relay seam: **reject** (no change). Seam 2 already is that seam; Seam 1 stays for pure logic.
- B8 New-post captures absent, so selectors unverifiable: **reject**. Workspace artifact: the sparse set omitted `app/public`; `git ls-files app/public/of-mirror/pages/new-post/state-schedule.html` lists it. One correction made: the capture has an empty `input.vdatetime-input` trigger, now stated instead of "no input".
- B9 Mock cannot prove OF publishes or queues: **partial**. True and unfixable under floor 2; live check parked for the human in Further Notes.

Draft call:
- D1 Stories 10, 11, 14, 16, 28 untested (arrows, header update, unreadable time, Cancel, stale schedule): **accept**. Seam 1 gains arrow, header, unreadable-time and stale-`posted_at` cases; Run 2 gains Schedule→Cancel keeps the summary.
- D2 Stories 19, 21, 22, 32 tag cases untested: **accept**. Seam 1 gains precheck, example-row `READ_ONLY`, All-Creators `SELECT_MODEL` and summary cases; Seam 2 gains a 502 tag-list case, the "Alpha One" summary assert and the All-Creators row note.
- D3 Read-only coverage narrower than stories 30-31: **accept**. Seam 1 now runs one case per state fixture (labels, poll, quiz, expiration, target, format-text) plus Record voice/video.
- D4 Doc greps pass without the docs saying what writes: **partial**. Greps tightened (README post.py section and a routes.md new-post row must say read-only; `tagged-friend-users` named) plus a manual Read; a grep cannot verify prose.
- D5 Schedule parsing departs from plan:118: **partial**. Decision kept on observation (the capture has no date/time fields); Further Notes now says the plan's wording is to be reconciled by the coordinator.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- White, departure 1 (no date/time fields, so no `parseDate`): **accept** as fact. The decision stays on rung 1 (Further Notes); the plan is not edited, and the mismatch is listed under Open questions in `plan-review.md`.
- Red, "heavy for its goal" (35 stories, calendar, time field, summary line): **partial**. The calendar re-render and the editable time tab stay: the plan's own acceptance schedules "tomorrow 6:30 pm" (plan:132), and the captured grid is a static October 2026 with no time input. The summary line is new UI the plan does not name (plan:90-91 allows only the minimal pieces a Phase names). It stays because it is the only way to see or clear a schedule, and the tension is listed under Open questions. The story count is not a decision.
- Black, duplicated read-only handling: **partial**. This Phase keeps its read-only handlers, because the plan names them here (plan:122) and `post.py` must assert them before Phase 6 exists. Accepted: Example tag rows and read-only controls carry no `data-oi-wired` (Composer), and Phase 6 removes any handler its fallback duplicates (Read-only controls), so a label toggle never flips twice.
- Black, `data-oi-wired` ownership split: **accept**. Phase 6 owns the contract (plan:253), and this Phase sets the mark early on its own Wired controls only (Further Notes).
- Black, no dedupe key, so a retry may post twice: **reject** for this Phase. A dedupe key is a new Relay field, which the plan forbids ("this plan adds none", plan:78-79), and the error text is the plan's own (plan:124-125). The double-post risk is parked under Needs the human in `plan-review.md` with the live check that would size it.
- Green, run Phase 4 before Phase 0 so posts land on real rows: **reject**. The plan's Phase order is the user's, and Phase 4 needs this Phase's `note`/`READ_ONLY` exports (phase-04 Depends on).
