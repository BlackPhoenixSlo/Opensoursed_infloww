Formerly TODO.md at the repo root (moved 2026-10-17, infloww-parity-round-2 Phase 0). Code and script comments cite its items as "TODO.md A1"–"B2".

# TODO: Messages Pro feedback (2026-10-16, from live use at http://127.0.0.1:3002)

Screenshots: `(owner screenshot, not in the repo)`
Reference UI: the earlier in-OF overlay composer.

## A. Composer (agent A)

- [x] **A1. Emoji picker Save doesn't add emojis.** The gear (⚙) next to 😊 opens the emoji grid with Cancel/Save. Picking emojis and pressing Save adds nothing. Fix it so the picked emojis are saved as quick emojis and persist.
  - Done in d90e424f: Save did write them, but the quick row ignored them. The row after ⚙ now shows the saved list (8 defaults until first Save) and updates live.
- [x] **A2. Drop the composer "+" button** (bottom right, the popover with FREE PREVIEWS / SEND AT / QUICK EMOJIS). Move its contents:
  - Free previews: show inline immediately whenever media is attached, as the earlier overlay composer did. Don't hide them behind a button.
  - Send at (+5m … +60m): move to the clock (⏰) button.
  - Quick emojis: move to the left side, next to the 😊 / ⚙ buttons, as a row you can add to (via A1).
  - Done in d90e424f.
- [x] **A3. Attaching an image or video opens the price (PPV) automatically.** A price of 0 means the message sends for free.
  - Done in d90e424f: it already did; now pinned by tests, and the price tooltip says 0 = free.
- [x] **A4. Upload + send fails every time.** Find the cause in `/tmp/oi-42e075ae-relay.log` and `/tmp/oi-42e075ae-app.log` and the code, then fix it. If the cause is only "no account logged in on this fresh local DB", say so and make the error message say that clearly.
  - [~] Partial, 2b724d16. It's a real bug, not a missing account (account <account id> is logged in). After S3 accepts the bytes, OF's `convert.onlyfans.com/file/upload` claim answers 400 "Invalid input." The chip now says "OnlyFans refused the file (Invalid input.)", and the relay logs the claim's geoUploadArgs keys. Which field OF rejects is unconfirmed: that needs one live retry, which was not allowed here. Suspects: the full geoUploadArgs sent for photos, and the real-filename change in 9f485dcf.
  - Done in a86ad044. OF's `signed/create` now returns its own `key` and an `uploadToken`; the convert claim must name that key (`upload/<account>/…`) and carry `file[uploadToken]`. Chat and vault share `_claim_uploaded`; large videos take part 1's URL. Pinned by `service/tests/test_upload_convert_claim.py`. Live: image sent in the owner's sandbox chat (<chat id>) 2026-10-17; a video uploaded live but no video send yet.
- [x] **A5. Tagging: replace "Mention this fan" (@) with tagging.** Remove the separate tag icon and make the @ icon do creator tagging. There should be no "mention this fan".
  - Done in d90e424f.

## B. Chat sidebar and header (agent B)

- [x] **B1. The "Buys & tips" panel toggle does nothing.** (3044778) The switch (`span.w-6.5.h-3.5.rounded-lg … bg-accent`) should hide/show that panel's notifications. Make it work and persist.
- [x] **B2. Drop the top "+" icon** (64fc313d, a7146808) next to the SFW toggle (its menu: All Models / Group chat / Scope switcher / Errors).
  - All Models: always active, so the toggle is no longer needed.
  - Scope switcher: remove it from here, since it's already in Creators.
  - Group chat and Errors (count badge): keep them reachable from their nearest existing place, and report where they went.
  - Done: Group chat stays in the Chat header's Extras overflow (Kebab > "Inflowwww extras" > Group chat). Errors is the 🐞 count badge inline in the Window header before SFW (hidden at 0).
  - Follow-up (a7146808): All Models is a permanent tab right after Home, first in the Creator tabs strip, with the Legacy flag off and on, so the scope can always go back to every Creator.

## Done when

Each item has a test in the repo's existing style, typecheck, eslint and vitest pass, and the item is ticked here with its commit SHA.
