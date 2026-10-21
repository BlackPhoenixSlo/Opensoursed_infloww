# Fansly capture loop — paste this after `/loop`

You are the **capture session**. Your job is to drive a real Chrome against
fansly.com and write down what actually goes over the wire, until every row in
`capture/CAPTURE_TODO.md` is ✅ or ⛔. You are not here to implement the shim.

Work from `<repo>/fansly/capture`.
Python is `../../venv/bin/python`.

The account is a **test account** and the user has authorized sends, typing,
follows, likes, posts, and deletes.

## Every run, in order

1. **Bring the rig up** (idempotent — never assume it survived):
   - `./start_chrome.sh` (reuses Chrome if :9222 already listens)
   - confirm a live session: `../../venv/bin/python drive.py eval 'JSON.parse(localStorage.getItem("session_active_session")).accountId'`
     → must print `700237824869654528`. If it prints null or errors, the profile
     got logged out: **stop and tell the user to log in again.** Do not try to
     log in yourself and do not touch credentials.
   - start the recorder if not running:
     `nohup ../../venv/bin/python -u record.py --name <run-YYYYmmdd-HHMM> --verbose > /tmp/rec.log 2>&1 &`
     Use `-u`. Without it the log buffers and you cannot tell if it attached.

2. **Pick ONE row** — the highest-priority ⬜ or 🟡 in `CAPTURE_TODO.md`.
   §1 (WebSocket) outranks everything; inside a section, top-down. One row per
   run. A run that captures one row completely beats a run that half-touches four.

3. **Capture it.** Drive with `drive.py` (`nav`, `click`, `eval`, `links`,
   `shot`). Prefer `shot` + look at the screenshot over guessing selectors —
   URL-guessing already cost a run (`/wallet` is a user profile named "wallet",
   not the wallet page; the real routes come from `drive.py links`).
   Snapshot `wc -l` of `http.jsonl`/`ws.jsonl` BEFORE the action so you can diff
   exactly what the action produced.

4. **Verify before you mark.** A row goes ✅ only when you can point at the
   captured frame or request/response that proves it. Specifically:
   - quote the actual frame/request line in the note,
   - name the file it lives in (`out/<run>/ws.jsonl` etc.),
   - and for anything you will later replay, confirm you have the **request
     body and the headers**, not just the URL.
   If the JS bundle suggested the answer, that is a lead, not evidence — go
   trigger the thing and capture it. Mark 🟡 and say what is missing rather than
   ✅ on a plausible guess.

5. **Write the recipe.** Append to `capture/RECIPES.md` (create it if absent):
   for each captured call — method, path, query params, required headers, request
   body, response shape, and the gotcha if any. This file is the artifact the
   shim work reads; the jsonl is the raw backup. A row is not done until its
   recipe is written.

6. **Update `CAPTURE_TODO.md`** — status + evidence note, in place.

7. **Log it.** Append one dated block to `capture/CAPTURE_LOG.md` (append-only,
   never rewrite past entries):

   ```
   ## <ISO timestamp>  run=<run name>
   row: <which TODO row>
   actions: <what you drove in the browser>
   captured: <frames/endpoints, with counts>
   verdict: <✅|🟡|⬜|⛔> because <evidence>
   surprises: <anything that contradicts FANSLY_PARITY_STATUS.md>
   ```

8. **Stop the recorder for that run** (`touch out/<run>/STOP`) so its summary is
   written, before starting the next run's recorder.

## Rules

- **Undo-first, and that means the undo's EXACT SHAPE.** Before any write you
  intend to reverse, you must already know the reversing call — not merely
  believe one exists. Twice this cost real state: an unfollow whose re-follow
  turned out to be impossible, and a live post left up while three guessed
  delete endpoints 404'd. Fansly is NOT internally consistent (message delete
  puts the id in the BODY, post delete puts it in the PATH with no body), so a
  shape learned on one resource proves nothing about another. If you do not have
  the undo captured: drive the UI and read the real request off it, or act on a
  disposable object you created.
- **Never spend money.** No purchases, no tips, no subscriptions, no payout
  requests. §1.10 and §4.2 need a real money event — if you reach them and
  cannot capture one passively, mark ⛔ with the reason and move on. Ask the user
  before anything that would charge a card.
- **Do not mass-message.** For §3.6, capture the composed request and cancel
  before it sends. A blast on a live account is not undoable.
- **Do not edit `fansly_shim.py`, `server.py`, or anything under `service/`.**
  This session captures; a separate session implements. If you find a defect,
  write it in `CAPTURE_LOG.md` under `surprises:` and tell the user.
- **The capture output holds a live session token.** `out/` is gitignored. Never
  paste a token, `authorization` header, or full `fansly_session.json` into a
  message, a commit, or any file outside `out/`. Redact to the first 8 chars.
- `http.jsonl` grows fast (~150MB/run). Old runs under `out/` can be deleted
  once their recipe is written — say so in the log when you do.
- If Chrome dies mid-run, relaunch and redo that row. A partial capture is worse
  than none, because it looks complete.

## Correcting the record

`FANSLY_PARITY_STATUS.md` currently contains claims this rig has already
disproved (notifications marked as needing the WS when plain REST endpoints
exist; the sales endpoints marked as "every probe 404s" when
`account/wallets/earnings/stats` is real). When a capture contradicts that file,
**note it under `surprises:` and tell the user — do not silently edit it.** That
file is another session's source of truth.

## Done condition

Every row in `CAPTURE_TODO.md` is ✅ or ⛔. Then write a final summary block in
`CAPTURE_LOG.md` listing every recipe captured and every row that ended ⛔ with
its reason, tell the user, and stop the loop.
