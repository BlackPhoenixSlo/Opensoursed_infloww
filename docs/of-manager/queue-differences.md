# OF Manager Queue: open differences from live OnlyFans

As of 2026-10-17, commit `7484f5c9` (branch `omf-queue-edit`, also `of-manager-fixes` and `omf-final`).
The edit-post, edit-message, reschedule and save-for-later request shapes were captured live from the sandbox account (80000112).

## Blocking: Save doesn't work on the owner's app yet

- The :8787 relay runs `main`'s code, which doesn't have the new routes:
  - `PUT /api/of/v2/queue/posts/{id}`
  - `GET` and `PUT /api/of/v2/messages/queue/{id}`
  - `POST /api/of/v2/messages/queue/later`
- So on :3093, Edit post, Edit message, reschedule and Save for later fail with 404/405 and send nothing to OnlyFans.
- To fix: merge `of-manager-fixes` into `main` (38+ commits, not only Queue), then restart :8787 (a host uvicorn run from the main checkout, no `--reload`; kill it by PID).
- A relay run from the branch saved edits for real end to end, so the code path has worked once.
- Still to check: whether a failed save shows an error in the UI or fails silently.

## UI differences

- Edit reuses the New post and New message composers with a summary line ("Editing a scheduled post · Scheduled for …"). OnlyFans has its own "EDIT POST" / "EDIT MESSAGE" page. Since page-parity 05 both show OF's "Scheduled for" piece (PostScheduleForItem from chunk 45507) above the editor. A click on it opens the schedule; its × stays disabled, because an edit keeps its date.
- The date in Add to queue and in New message's schedule dialog opens OF's own day popup (`ofMirrorDatepicker`, days from today on). The time is still the browser's time input.
- The "+" on the Scheduled events widget is hidden once the widget lists events, as on OnlyFans.
- Edit message can change the media, price and tags: New message's price and vault dialogs are captured, and the Relay's edit body has them.
- In Edit message, recipients picked one by one are kept and shown ("2 users picked") but can't be edited.
- The auto-publish switch on the saved-for-later pages is disabled.
- On a phone, New message shows the lists and hides the composer; live OnlyFans does the same.

## Not verified live (still guesses)

- **Half-tinted day bars** for days with saved-for-later items (`queue-saved-month.json`). Saved items reach the calendar only after auto-publish gives them a date, and auto-publish was off during capture. The bars are computed from the month's items, not OnlyFans' counters call.
- The "Unpin from your profile page" row-menu item.
- The confirm texts for delete and for publish.
- "Publish now" and "Send message right now" were never run live, because they would publish or send.

## Request-format differences (OnlyFans accepted ours)

- The relay sends post and message text as plain text; OnlyFans' own UI sends `<p>…</p>` HTML.
- The relay sends dates with a timezone offset; OnlyFans' own UI sends UTC with `.000Z`.

## Unrelated failures seen during the work

- `service/tests/test_mass_exclude` fails 12 cases with a 401 "sign in required". It fails the same way on the base commit.
- `ComposerToolbar.test.tsx` sometimes times out under a full vitest run. It passes 39/39 on its own.
