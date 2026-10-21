# Phase 05 — The Google Drive import goes below the file drop, behind a configured key

**Objective.** On the Vault import card, the file drop comes first. The Google Drive link paste is a collapsed section below it, labelled "Inflowwww extra", and it opens only when the deployment has `GOOGLE_DRIVE_API_KEY` set in Setup → Keys. Without the key, the section is one line that says where to add it. `service/gdrive.py` is unchanged.

## Problem Statement

An operator who opens Growth → Vault Pro to put media into a Creator's vault sees a card that offers the file picker and a Google Drive link box side by side. The header says "Files from this computer, or public Google Drive links". Infloww's upload screen has only the drop area, and the Drive import works only when the deployment owner has made a Google Cloud API key and pasted it into Setup → Keys. Many deployments never will. On those deployments the Drive box looks like it works: the operator pastes a folder link, presses Start import, and only after the run starts does it fail with "No GOOGLE_DRIVE_API_KEY configured" (`service/gdrive.py:101-105`, surfaced through the run's error). A reviewer comparing the card with Infloww also sees a control Infloww lacks, sitting next to Infloww's own control and carrying no label.

## Solution

The card reads like Infloww's upload area, as the Layout capture `docs/infloww-layouts/growth-vault-pro.md` records it: the file drop leads, and the header copy no longer mentions Drive. Directly below the file drop sits one collapsed section, "Import from Google Drive", marked "Inflowwww extra". It has two states:

- **Key configured.** The section is closed when the card loads. Opening it shows the existing Drive link box, unchanged in behaviour: one link per line, a folder link works, and the links go out with the same Start import as the dropped files.
- **Key not configured.** The section is one line and has no link box: it names the extra, says the deployment's `GOOGLE_DRIVE_API_KEY` is not set, and says to add it in Setup → Keys, the "Server keys" card on Creators → Manage creators. Nothing on the card can send a Drive link.

The card learns which state it is in from the relay's existing import-status read, which gains one true/false field. The key itself never leaves the relay.

## User Stories

1. As an operator, I want the file drop to be the first control on the Vault import card, so that the card reads like Infloww's upload area.
2. As an operator, I want to drag files from my computer onto the drop area as well as pick them, so that the drop area does what Infloww's own drop area says it does ("You can drag and drop media file(s) here or select them from your computer").
3. As an operator, I want the card's header copy to describe only what the Infloww area offers, so that the card does not promise Drive links on a deployment that cannot fetch them.
4. As an operator on a deployment with `GOOGLE_DRIVE_API_KEY` set, I want a collapsed "Import from Google Drive" section below the file drop, so that the Drive import is still one click away.
5. As an operator on a deployment with the key set, I want the section to be closed when the card loads, so that the default view matches Infloww.
6. As an operator on a deployment with the key set, I want opening the section to show the same link box as today (one link per line, folder links allowed), so that nothing I relied on is lost.
7. As an operator, I want Drive links and dropped files to go out together with the one Start import, so that a mixed batch still lands in one run and one folder.
8. As an operator on a deployment with the key set, I want links I typed to stay in the box if I close the section and open it again, so that collapsing it does not lose my work.
9. As an operator on a deployment without the key, I want the section to be one line saying the key is not set and that it goes in Setup → Keys (the "Server keys" card on Creators → Manage creators), so that I know who must act and where.
10. As an operator on a deployment without the key, I want no Drive link box at all, so that I cannot start a run that is bound to fail.
11. As the deployment owner, I want the card to change state on its next load after I paste the key into Setup → Keys, with no relay restart, so that turning the extra on is one paste (the store is read on each call, `service/secrets_store.py:5-8`).
12. As the deployment owner, I want the card to learn only whether the key is set, never the key or a masked hint of it, so that the house key stays as private as `/admin/secrets` keeps it.
13. As a reviewer, I want the Drive section to carry the "Inflowwww extra" label as visible text and as its tooltip, so that I can tell the improvement from a mismatch (ADR-0003).
14. As a reviewer, I want everything else on the card to match `docs/infloww-layouts/growth-vault-pro.md`, or carry the "Inflowwww extra" label, so that I can reject any other difference.
15. As a chatter whose role grants Vault Pro, I want to see the same two states as an owner, so that the card behaves the same for everyone who can import.
16. As a reviewer, I want this Phase's section of the Vault Pro recheck record (`.scratch/infloww-parity-round-2/rechecks/growth-vault-pro.md`) to give the §3.5.4 row text naming the moved Drive import and its Labelled improvements line, so that Phase 6, which alone edits the matrix, grades it as an intentional extra.
17. As a maintainer, I want tests for both states that never contact Google, so that the suite runs offline and costs nothing.
18. As a maintainer, I want the card rechecked against the bundle with REA before the ticket closes, so that the layout claim rests on Infloww's shipped code, not on memory.

## Implementation Decisions

- **Owns.** `VaultImportCard` (`app/components/vault/VaultImportCard.tsx`) and its test file; the relay's Vault import status route (`of_vault_upload_status` in `service/server.py`, `GET /api/of/v2/vault/upload/status`); one new relay test file; the `## Phase 5` section of `.scratch/infloww-parity-round-2/rechecks/growth-vault-pro.md`, holding the proposed §3.5.4 row text and one Labelled improvements line (Phase 2's Vault Pro ticket writes its own section in the same file); one relay-test step in the effort suite. The Vault Pro page around the card (`app/app/growth/vault-pro/page.tsx`, its folder rail and media chips) belongs to Phase 2's Vault Pro ticket. This Phase does not move the card on the page.
- **No Parity matrix edit.** Phase 6 alone edits `docs/infloww-parity-matrix.md` (coordinator ruling, 2026-10-17). The ticket writes the proposed §3.5.4 row text under `### Matrix row` and the Drive import line under `### Labelled improvements` in its recheck section, and Phase 6 applies both.
- **Interfaces.**
  - The status route's response gains `drive_import_configured: boolean` on **every** path. That includes the early `{"running": false, "run": null}` answer for an account with no run yet, which is the answer a fresh card gets first. The value is computed once per request, before the run lookup, by calling `gdrive.api_key()` and catching `gdrive.GDriveError`. True means it returned. This uses the key's own reader, so store-first then environment, as the house rule in `secrets_store.status()` requires ("Resolve the way the key's READER does"). `service/gdrive.py` is called, not edited. `service/server.py` imports nothing from `gdrive` today (`grep -n gdrive service/server.py` is empty; `service/vault_upload.py:66` is the one importer), so the route adds `import gdrive`. The call reads only the store file and the environment, never the network.
  - `VaultImportCard`'s `RunStatus` type gains `drive_import_configured?: boolean`. The exported pure helpers `itemLabel`, `runSummary` and `showsError` are unchanged.
- **Schema.** None. No table, no store key: `GOOGLE_DRIVE_API_KEY` is already in `secrets_store.KNOWN` under the group "Vault import" (`service/secrets_store.py:95`).
- **Contracts.** `GET /api/of/v2/vault/upload/status` (account-scoped, `assert_account_owned` unchanged) adds the field `drive_import_configured` (boolean). Nothing else on the wire changes. `POST /api/of/v2/vault/upload/batch` is unchanged and still accepts `drive_links`. A request that sends links to a keyless deployment fails as it does today, inside the run.
- **Card order.** The card's Infloww elements (the file drop's wording and any title or copy around it) come from the Items of `growth-vault-pro.md`, cited by item ID. The Drive sentence leaves the header. The card keeps four things the capture may not have, because they are the card's own safety rules: the target model in the title ("Import to …'s vault"), the re-encode and "nothing is posted" sentences, "Put into folder", and the run's progress and warnings. Each of the four that has no matching item in the capture carries `title={EXTRA_LABEL}` (ADR-0003's tooltip form, as `app/components/home/CompetitorReports.tsx:447` does), and the ticket lists them with the item IDs it compared, so a reviewer can reject anything else (plan Phase 5, ADR-0013). The order is the file drop, the Drive section, "Put into folder", and the Start import row, followed by the run's progress and warnings as today. The Drive section goes directly under the file drop and above the folder and Start row because it feeds the same Start (rung 5: one Start, one batch route).
- **File drop.** The existing file input (images, video, audio, multiple) sits inside a drop area that also accepts dropped files. The drop area fills the same `picked` state as the picker, and it is disabled while a run is live. Its wording, size, border and colours come from `growth-vault-pro.md`. The bundle's upload guide says "You can drag and drop media file(s) here or select them from your computer" (`~/Downloads/infloww-remote-web/index.9f50f370.js`, byte offset 12945046 of the string, from `LC_ALL=C grep -boF` during the review; it is step 1 of the bundle's Vault upload guide, whose step 0 says "the Vault will automatically upload media files").
- **Drive section, key set.** A native `<details>`, closed by default. Its `<summary>` reads "Import from Google Drive" followed by a small tag whose text is `EXTRA_LABEL` ("Inflowwww extra", `app/lib/openinflowwwwExtras.ts`). The summary's `title` is the same constant. The body is the existing link textarea, with its placeholder, `disabled` while running, and the same `links` state. `<details>` keeps its children mounted, so typed links survive a collapse (story 8).
- **Drive section, key not set.** It renders one `<p>` and no textarea: "Import from Google Drive (Inflowwww extra) is off: this server's GOOGLE_DRIVE_API_KEY is not set. The server's owner adds it in Setup → Keys, the "Server keys" card on Creators → Manage creators." It names the server's owner as the one who acts, because the Server keys card renders only for `me?.is_admin` (`app/app/creators/page.tsx:74`), so an agency owner or chatter cannot add the key. The text is plain, with no link, for the same reason. The line carries the same `title`.
- **Which state.** Only `drive_import_configured === true` in a status answer opens the section. A status answer with the field false or absent (an older relay) shows the one line. Before the first answer, and when the status read has failed with no earlier answer, the Drive slot renders nothing: no line and no textarea. The card stays fail-closed (no state can send links without `true`), and it never tells a deployment that has the key that the key is missing.
- **Start.** `nothingToDo` and the batch form count `links` only when the section is configured, so a keyless card can never send `drive_links`.
- **No new route, no permission change.** The flag rides on the status read the card already polls. So the page map in `service/permissions.py` and `service/tests/test_role_enforcement.py` are not touched, and nothing becomes reachable that was not before.
- **Disclosure.** Any caller who can read an account's import status learns one deployment-wide boolean: whether Drive import is on. It reveals no part of the key. `/admin/secrets` stays master-only for the masked hint (`service/server.py:567-583`).
- **Bundle recheck before close.** The ticket serves the bundle on 127.0.0.1 only (`python3 -I -m http.server --bind 127.0.0.1 <port> --directory ~/Downloads/infloww-remote-web`, started outside the bundle). It compares the card with `docs/infloww-layouts/growth-vault-pro.md` and the bundle using REA (`inspect_web_page`, `capture_web_screenshot`; `grep -F` on chunks if the SPA will not render). It records the result in its recheck section (`### REA`, `### Differences`), and the proposed row's Visual evidence cell cites it. Nothing is copied out of the bundle beyond the labels and measurements the capture already cites.

## Testing Decisions

- **Seam 1, the card (vitest, `app/components/vault/VaultImportCard.test.tsx`, extended).** Render `VaultImportCard` in a `QueryClientProvider`. Mock `relay.get` and `relay.uploadForm` through `vi.mock("@/lib/relay")`, and mock `useVaultAccount` / `useVaultAccountId` to a fixture account with a placeholder nickname. `relay.get` answers by path (the status route and the folder lists), so no case reaches `fetch` at all. The cases:
  1. With `drive_import_configured: true`: the file input comes before the Drive section in document order. The `<details>` is closed, and its summary contains "Import from Google Drive" and `EXTRA_LABEL`, with `title === EXTRA_LABEL`. After the summary is clicked, the textarea is visible. Typing a link and pressing Start import sends a form with `drive_links`.
  2. With `drive_import_configured: false` and with the field absent: exactly one line mentions `GOOGLE_DRIVE_API_KEY` and "Setup → Keys". No textarea is rendered, and Start import stays disabled with no files.
  2b. While the status read is still pending (a `relay.get` promise that does not resolve): neither the line nor a textarea is rendered.
  2c. Every card element the ticket listed as kept without a capture item has `title === EXTRA_LABEL`.
  3. A file dropped on the drop area counts as picked (the "1 file" line appears).
  4. The header copy no longer contains "Google Drive".

  The existing pure-helper cases stay as they are. Prior art: `app/components/settings/AutomationSwitch.test.tsx` (relay mock, query client, `userEvent`).
- **Seam 2, the status route (relay, new `service/tests/test_vault_drive_configured.py`, house style: `_harness` first, plain checks, exit 0 = green).** It uses the shared two-agency fixture (`_agency_fixtures.seed_two_agencies`, `login_owner`) and the harness's throwaway secrets store. The vault spool is repointed at a `tempfile.mkdtemp` directory: set `VAULT_SPOOL_DIR` before the server import, or `vault_upload.SPOOL_ROOT` as `test_vault_upload.py` does. `GOOGLE_DRIVE_API_KEY` is removed from the process environment at the start. The cases:
  1. The key is unset: Owner A's status for A's Creator returns 200 with `drive_import_configured` false, on the no-run path.
  2. A fake key is set in the store (`secrets_store.set_many`, value `test-drive-key-not-real`): the field is true, and the response text does not contain the fake value or its last four characters.
  3. The key is set only in the environment: the field is true (the reader's fallback).
  4. With a seeded finished run on the spool, the field is still present (the run path).
  5. Negative control: Owner B asking for A's Creator still gets 403, so the field did not open the route.

  No case calls `gdrive.resolve` or `gdrive.download`, and no case reaches the network. A tripwire replaces `gdrive._session` (the module's one per-thread `requests.Session` factory, which every Drive call goes through) with a function that raises. Prior art: `service/tests/test_creators_tenancy.py` (fixture, owners) and `service/tests/test_vault_upload.py` (spool repoint).
- **Unchanged and still green.** `service/tests/test_vault_upload.py` (Drive link parsing, key redaction) and `service/tests/test_secrets_store.py`.
- **Suite.** The ticket adds a `relay` step to `.scratch/infloww-parity-round-2/suite.sh` that runs `test_vault_drive_configured.py` and `test_vault_upload.py` with `./venv/bin/python`, in the house pattern of `.scratch/infloww-parity-next-steps/suite.sh` (`relay_tests`). If another Phase has already added the step, the ticket appends to its list instead.

## Acceptance

```sh
cd <repo>
# the capture this Phase transcribes exists (Phase 0)
test -f docs/infloww-layouts/growth-vault-pro.md
# the relay seam, both states, offline
./venv/bin/python service/tests/test_vault_drive_configured.py
./venv/bin/python service/tests/test_vault_upload.py
./venv/bin/python service/tests/test_secrets_store.py
# the card seam
env ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/vault/VaultImportCard --testTimeout=20000
# the effort suite (typecheck, lint, vitest, and the relay step this Phase adds)
sh .scratch/infloww-parity-round-2/suite.sh
grep -qF "test_vault_drive_configured" .scratch/infloww-parity-round-2/suite.sh
# service/gdrive.py is unchanged against the plan's base
git diff --quiet fda942e0 -- service/gdrive.py
# the card uses the shared label, and the field reaches every status answer
grep -qF "EXTRA_LABEL" app/components/vault/VaultImportCard.tsx
grep -qF "drive_import_configured" app/components/vault/VaultImportCard.tsx
test "$(grep -cF "drive_import_configured" service/server.py)" -ge 2
# no test talks to Google
! grep -nF "googleapis.com" service/tests/test_vault_drive_configured.py app/components/vault/VaultImportCard.test.tsx
# the recheck record's Phase 5 section proposes the row and the Labelled improvements line (Phase 6 alone edits the matrix)
R=$(sed -n '/^## Phase 5 /,/^## Phase /p' .scratch/infloww-parity-round-2/rechecks/growth-vault-pro.md)
echo "$R" | sed -n '/^### Matrix row/,/^### /p' | grep -qF "Google Drive"
echo "$R" | sed -n '/^### Labelled improvements/,/^### /p' | grep -qF "Google Drive import"
# manual: before closing, serve the bundle on 127.0.0.1 and recheck the card against docs/infloww-layouts/growth-vault-pro.md with REA (inspect_web_page / capture_web_screenshot); list every kept non-capture element with its `title={EXTRA_LABEL}`; note the result in the recheck record's Phase 5 section
# manual: on the dev server (http://127.0.0.1:3001/growth/vault-pro) with no key, see the one line; paste a fake key in Setup → Keys as founder, reload, see the closed section; clear the key afterwards
```

## Depends on

- **Phase 0** provides `docs/infloww-layouts/growth-vault-pro.md`, the REA capture of the Vault Pro upload area: the drop area's wording, its order and its spacing and colours, each with its chunk and offset. This Phase transcribes the card from it.
- Phase 2's Vault Pro ticket also edits `/growth/vault-pro`, but only the page around the card. Neither Phase waits for the other, and if both land in one tree the card stays where the page puts it.

## Out of Scope

- Changing `service/gdrive.py`, or how Drive files are resolved, downloaded, size-checked or redacted. The plan says unchanged.
- Refusing `drive_links` in the batch route when the key is missing. The card can no longer send them, and the run already fails with the reader's message. A second check adds nothing (YAGNI).
- A per-agency Drive key in `tenant_keys`. The key is a house key today and the plan names Setup → Keys.
- A link from the one line to `/creators`. Only the founder sees the Server keys card, so the link would mislead everyone else.
- Adding the Drive section to the `EXTRAS` catalogue in `app/lib/openinflowwwwExtras.ts`. That catalogue and its audit cover Messages Pro Regions only (`Host` type), and only the label constant is reused.
- Putting the section behind the Legacy flag. It is not an automation (ADR-0003), and the gate the owner chose is the key.
- Remembering the section's open or closed state across loads. Infloww has no such section, and the default is closed.
- OAuth, private Drive files and shared drives (`service/gdrive.py` docstring, "WHAT THIS CANNOT DO").
- Live Drive or OnlyFans traffic in any test.

## Further Notes

ASSUMPTION: the flag rides on the existing status read rather than a new route (rung 5, and the plan's "or reuse the existing keys-status read"; `/admin/secrets` is master-only, `service/server.py:578-583`, so it cannot serve a chatter or an agency owner). Overturned if a later card needs the flag without an account in scope.

ASSUMPTION: the Drive section goes directly under the file drop and above "Put into folder" and Start, not at the bottom of the card (rung 5: it feeds the same Start). Overturned if the owner reads "below the file drop" as below the whole card.

ASSUMPTION: the label is visible text in the summary as well as the tooltip, because the plan says "labelled" and ADR-0003's house form is the tooltip, so both are used (rung 3 plus rung 2). Overturned if the owner wants the tooltip only.

ASSUMPTION: before the first status answer, and after a failed read with none, the Drive slot renders nothing; only a status answer with the field false or absent shows the one line (rung 4: fail closed either way; the review found that showing the line while loading tells a keyed deployment its key is missing). Overturned if the owner wants the line shown whenever the section is not open.

ASSUMPTION: if `growth-vault-pro.md` shows that Infloww's own upload area has a link or cloud import, the owner's decision still binds (below the file drop, collapsed, labelled, gated by the key), and the ticket records the disagreement in the capture's Notes for the human rather than re-placing the section (rung 2, the plan's owner decision). Overturned by the owner.

ASSUMPTION: the Server keys card is `hidden md:block` (`app/app/creators/page.tsx:74`), so on a phone-width window the place the line names is not shown. The line is not changed for that (rung 5); the founder sets keys on a desktop. Overturned if Phase 4 makes the key cards visible on small screens, or the owner wants the line to say so.

ASSUMPTION: the file drop accepts dropped files, not only the picker, because the plan says "file drop" and the bundle's upload guide offers drag and drop (rung 1, `index.9f50f370.js` offset 12945046; rung 2, the plan's wording). Overturned if `growth-vault-pro.md` records no drop area on the upload screen, in which case the picker alone stays.

ASSUMPTION: the one line's wording, "Setup → Keys, the "Server keys" card on Creators → Manage creators", names the place by the plan's term and by the page that hosts it today (`app/app/creators/page.tsx:1-14`, `app/components/setup/KeysCard.tsx:4`) (rung 3). Overturned if Phase 4 moves the Server keys card. That ticket then updates this line.

ASSUMPTION: this Phase makes no matrix edit; its row text and Labelled improvements line go to its section of `rechecks/growth-vault-pro.md`, and Phase 6 alone applies them (coordinator ruling 2, 2026-10-17, adopting six-hats 13; rung 4, since the matrix holds the owner's uncommitted Sign-off and Phase 6 regrades every row anyway). Overturned once the owner commits the matrix and wants each Phase to regrade its own row.

ASSUMPTION: the bundle's Vault Pro upload area lives in `index.9f50f370.js`, and the offset above is from one `grep -F` during this spec, not from a REA capture (rung 1, partial). Phase 0's capture overrules it if the two disagree.

Glossary terms this Phase needs that CONTEXT.md lacks (for the coordinator, not CONTEXT.md): **Vault import card** (the card at the top of Vault Pro that uploads files into a Creator's vault); **file drop** (its drop and picker area); **Drive import** (the extra that pulls public Google Drive links into the same run). CONTEXT.md's **Inflowwww extra** says "a Messages Pro control", and this Phase uses the label outside Messages Pro, so the entry needs widening.

## Review

weaker (devils-advocate), 2026-10-17. The codex preflight passed (`codex login status`: logged in), but the blind call failed its postflight with exit 1 and no output file. Its log ends with "You've hit your usage limit … try again at Nov 11th, 2026". The HEADER forbids spawning sub-agents, so this reviewer ran both calls in the devils-advocate persona itself, confined to the workspace (plus `service/server.py` and the bundle, read locally to check claims the workspace cannot). The blind call was therefore not structurally blind: this reviewer had read the spec first. Ran green: `./venv/bin/python service/tests/test_vault_upload.py` (exit 0), `service/tests/test_secrets_store.py` (exit 0).

Blind call (alternatives, missing requirements, seam, falsifiers):
- B1 Alternatives: a new key-status route, reusing `/admin/secrets`, or removing the Drive box. **reject**: the spec already weighs all three. `/admin/secrets` is master-only (`service/server.py:567-583`), a new route would touch the permission page map, and the owner ruled out removal ("collapsed, not removed", plan Phase 5).
- B2 Falsifier: Infloww's own upload area may have a link or cloud import (Phase 0 story 28 asks the capture to record "any link import"). If it does, the "extra" premise is false. **accept**: added an ASSUMPTION. The owner decision binds, and the disagreement goes into the capture's Notes for the human.
- B3 Missing requirement: the plan says "matrix row updated", but `docs/infloww-parity-matrix.md` is uncommitted owner state and off limits (HEADER; coordinator note). **accept**: Owns, story 16 and Acceptance now defer the edit. The ticket edits the matrix only when `git diff --quiet HEAD -- docs/infloww-parity-matrix.md` holds. Otherwise it parks both lines for Phase 6, as Phases 0, 1, 4 and 6 do.
- B4 Seam: the relay status route (field on every 200 path) and the card (vitest with a mocked relay) are the right seams. `gdrive.api_key()` reads only the store and the environment (`service/gdrive.py:91-105`). **reject** as a change: the spec already tests at these seams.
- B5 Missing requirement: `service/server.py` does not import `gdrive` today (`grep -n gdrive service/server.py` is empty; `service/vault_upload.py:66` is the one importer). **accept**: Interfaces now says the route adds the import.

Draft call (where the spec is wrong):
- D1 Card order contradicted ADR-0013 and the plan ("A reviewer rejects any other difference from the capture without an 'Inflowwww extra' label"). It took "the copy from the capture" but kept the title, the re-encode and "nothing is posted" sentences, "Put into folder" and the run warnings with no label. Story 14 promised otherwise, and no check enforced it. **accept**: Card order rewritten. The Infloww elements come from the capture's Items by ID. Each kept element with no matching item gets `title={EXTRA_LABEL}` (precedent `app/components/home/CompetitorReports.tsx:447`), the ticket lists them, and vitest case 2c and the manual REA line check them.
- D2 "Which state" showed "this server's GOOGLE_DRIVE_API_KEY is not set" while loading and after a failed read. That is a false statement on every first load of a keyed deployment (the status query starts empty, `VaultImportCard.tsx:199`). **accept**: the decision is now three-valued. With no answer yet the slot is empty. False or absent shows the line. Only true opens the section. Still fail-closed. Vitest case 2b added, and the ASSUMPTION rewritten.
- D3 The key-not-set line told every reader "Add it in Setup → Keys", but the Server keys card renders only for `me?.is_admin` (`app/app/creators/page.tsx:74`). An agency owner or chatter cannot act on it, which breaks story 9 ("who must act"). **accept**: the line now says "The server's owner adds it in Setup → Keys …".
- D4 Vitest's `fetch` spy for Google hosts is vacuous, because `relay` is mocked and the card never calls `fetch`. **accept**: removed. The relay tripwire on `gdrive._session` (`service/gdrive.py:181`) stays, because it guards a real regression (a "validate the key with Google" call).
- D5 `! grep -nF "googleapis.com"` over the test files is near-vacuous. **partial**: kept as a cheap guard against a test that hardcodes the host. It is not counted as evidence of offline behaviour; the relay tripwire and the mocks are.
- D6 `test "$(grep -cF drive_import_configured service/server.py)" -ge 2` passes with a comment plus one return. **reject**: relay cases 1 (no-run path) and 4 (run path) prove the field on both 200 paths. The grep is a redundant smoke check, not the gate.
- D7 The bundle offset was wrong: `LC_ALL=C grep -boF "You can drag and drop media file(s) here or select them from your computer" ~/Downloads/infloww-remote-web/index.9f50f370.js` gives 12945046, not 12945032. Context (`dd` around it) shows step 1 of the Vault upload guide. **accept**: offset corrected in File drop and the ASSUMPTION.
- D8 Drag-and-drop is scope the plan did not ask for. **reject**: the plan says "file drop", and the bundle's Vault upload guide offers drag and drop (D7). The ASSUMPTION already drops it if the capture records no drop area.
- D9 The Server keys card is `hidden md:block` (`app/app/creators/page.tsx:74`), so the place the line names does not show on a phone-width window. **partial**: no change to the line (rung 5), but a flagged ASSUMPTION was added.
- D10 Depends on: Phase 2 also touches Vault Pro. **reject**: Phase 2 leaves the card's contents to Phase 5 (`phase-02-growth-pages.md:116,179`), and Phase 4 keeps the key cards on `/creators` (`phase-04-creators-pages.md:20`), so the line's "Creators → Manage creators" stays true. The Depends on is correct as written. `docs/infloww-layouts/` does not exist yet (`ls` fails), which is what Phase 0 provides.
- D11 `git diff --quiet fda942e0 -- service/gdrive.py` names "the plan's base" loosely. **reject**: no commit since touches `gdrive.py`, so the check is equivalent for any base on this line.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH9 **accept.** One recheck location: the result goes to this Phase's section of `.scratch/infloww-parity-round-2/rechecks/growth-vault-pro.md`, not to the ticket (Bundle recheck, Acceptance).
- SH13 **accept.** No matrix edit and no Acceptance line on the matrix file; the row text and Labelled improvements line go to the recheck record (story 16, Owns, the matrix decision, Acceptance, ASSUMPTION). B3's deferral becomes a drop.

No needs-human. Counts: 8 accept, 2 partial, 6 reject (before six hats).
