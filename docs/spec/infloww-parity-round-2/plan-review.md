# Plan review — infloww-parity-round-2

2026-10-17. Plan: `docs/plans/infloww-parity-round-2.md`. Specs: `docs/spec/infloww-parity-round-2/phase-*.md`. Inputs: the six-hats report (`.scratch/infloww-parity-round-2/review/six-hats.md`), Phase 2b's devils-advocate (`.scratch/infloww-parity-round-2/review/02b-devils-advocate.md`), and the coordinator's rulings 1–8 of 2026-10-17. Rulings that are not rung 1 or 2 are flagged ASSUMPTION in the spec that applies them.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 0 | `phase-00-baseline-layout-capture.md` | none (the merge `5fb64b78` and `7f0b1c04` are on `main`) |
| 1 | 4 (prefactor ticket only) | `phase-04-creators-pages.md`, Order | none: the `/health?all_accounts=1` clamp needs no capture (ruling 4) |
| 2 | 1 | `phase-01-dashboard.md` | Phase 0 |
| 2 | 2b | `phase-02b-auto-mass-messages.md` | Phase 0 |
| 2 | 3 | `phase-03-creator-reports.md` | Phase 0 |
| 2 | 4 | `phase-04-creators-pages.md` | Phase 0 (all tickets but the prefactor) |
| 2 | 5 | `phase-05-drive-import.md` | Phase 0 |
| 2 | 2 (Scripts, Vault Pro, Tracking links tickets) | `phase-02-growth-pages.md` | Phase 0 |
| 3 | 2 (Smart Messages ticket) | `phase-02-growth-pages.md` | Phase 0, Phase 2b (the page frame and its two slots) |
| 4 | 6 | `phase-06-sign-off.md` | Phases 0–5 and 2b; the owner's commit of the matrix `## Sign-off` (matrix ticket only, steps 7–8) |

Merge order for shared files. Phases 1, 3 and 2 (Smart Messages ticket) each add one entry to `PAGE_MAP` (`service/permissions.py`) and its `service/tests/test_role_enforcement.py` cases: Phase 1 the `/` entry, Phase 3 the Creator reports entry, Phase 2 the Smart Messages entry. Each Phase touches only its own page's entry. They merge in wave order, then by label (1, then 3, in wave 2; 2 in wave 3), and a later one rebases on the earlier. Phases 2b, 4 and 5 make no page-map edit. Phase 3 owns `CompetitorReports`' insides; Phase 1 treats it as a black box and mocks it, so 1 and 3 do not order each other. `SmartMessagesPage.tsx` is 2b's frame first, then Phase 2's slots. Phase 5 and Phase 2's Vault Pro ticket share `/growth/vault-pro`, but the card and the page around it are separate.

## Adversary

Counts are every accept, partial and reject line in the spec's `## Review`, including the six-hats lines added by this plan review.

- **Phase 0** — blind call `codex` (exit 0), draft call `weaker (devils-advocate)`. 12 accept, 3 partial, 13 reject. needs-human: none; D8's owner action is superseded by ruling 2 (SH1).
- **Phase 1** — `weaker (devils-advocate)` (codex quota). 13 accept, 5 partial, 4 reject. needs-human: none.
- **Phase 2** — `weaker (devils-advocate)` (codex quota). 15 accept, 5 partial, 5 reject. needs-human: N1 Delayed welcome binding, N2 Message on purchase.
- **Phase 2b** — `weaker (devils-advocate, top-level, blind first call)`, 2026-10-17; earlier self-check findings kept. 20 accept, 10 partial, 2 reject. needs-human: none blocking; the placement, the fallback's chatter loss and Premade Mass are FYIs for the owner's veto.
- **Phase 3** — `weaker (devils-advocate)` (codex postflight exit 1). 10 accept, 5 partial, 1 reject. needs-human: none (codex rerun wanted).
- **Phase 4** — `weaker (devils-advocate)` (codex refresh token revoked). 14 accept, 4 partial, 4 reject. needs-human: N1 single-account `/health`.
- **Phase 5** — `weaker (devils-advocate)` (codex postflight exit 1). 10 accept, 2 partial, 6 reject. needs-human: none.
- **Phase 6** — `weaker (devils-advocate)` (codex refresh token revoked). 17 accept, 4 partial, 3 reject. needs-human: the owner's matrix commit; codex rerun.

## Six hats

Per-spec bullets went to each spec's `## Review`. Phase 0: SH1, SH9, SH10, SH13. Phase 1: SH7, SH9, SH12, SH13, SH15(e). Phase 2: SH3, SH8, SH9, SH13, SH14, SH18. Phase 2b: SH2, SH3, SH5, SH8, SH9, SH13, SH14. Phase 3: SH7, SH9, SH13. Phase 4: SH6, SH9, SH13, SH15(d). Phase 5: SH9, SH13. Phase 6: SH1, SH7, SH9, SH13, SH18. The set-level bullets and the set-level parts of split bullets are below.

- **SH1** (set part) **accept.** Ruling 2 removed the matrix from Phases 0–5 and 2b. Only Phase 6's matrix ticket (steps 7–8) waits on the owner's commit. Phase 0 parks its baseline in `.scratch/infloww-parity-round-2/baseline.md`, and its Acceptance pins the next-steps suite's one known red.
- **SH2** **accept.** The review strengths are as stated, now corrected: Phase 0 had a real codex blind call; 1, 2, 3 and 5 hit the quota or failed postflight; 4 and 6 had a revoked refresh token; 2b now has a top-level devils-advocate (blind first call, then a draft call), reconciled in its Review. Every non-codex review is labelled `weaker`, and the reruns are listed under Needs the human.
- **SH3** (set part) **partial.** ADR-0014 is amended in place: its title and decision now say Smart Messages' trigger list holds only per-fan triggers and mass messages sit in the bundle's Mass Messages tab, with My Automations as the fallback. The offsets are corrected in 2b, Phase 2 and ADR-0014. CONTEXT.md is not edited (another session owns it). `glossary-pending.md` still carries the pre-amendment "Auto mass messages tab" and "Auto delete" entries; the corrected terms go in this run's report for CONTEXT.md's owner.
- **SH4** **accept.** The owner's one commit is now the first and only blocking human step, and it blocks only Phase 6's matrix ticket. It is first under Needs the human.
- **SH9** (set part) **accept.** The order is now agreed. `CompetitorReports`: Phase 3 owns its insides, Phase 1 treats it as a black box (both Depends on lines agree). `PAGE_MAP`: each Phase adds only its own page's entry, merged in wave order (Workstreams). One recheck location: `.scratch/infloww-parity-round-2/rechecks/<page>.md`, format in Phase 0's Contracts, and Phase 6's Acceptance checks each page's record.
- **SH11** **accept, no change.** The weaker reviews found real defects; their reconcile lines stand.
- **SH16** **accept.** Every needs-human item is in one place, below.
- **SH17** **partial.** The top-level devils-advocate on 2b ran and is reconciled. The cross-spec review asked for (grading rule, `CompetitorReports` order, `PAGE_MAP` merge order) is this plan review, by coordinator rulings 3, 5 and the Workstreams merge order. It is not an independent second model: codex reruns stay open (Nov 11th, 2026, or after `codex login`). Nothing waits for them.
- **SH18** (set part) **accept.** Phase 6 accepts `intentionally improved` for rows whose every difference is a labelled extra (ruling 3), the 2b offsets in Phase 2 are corrected, ADR-0014 is amended by this run (it wrote it), and the CONTEXT.md amendments are parked for their owner.
- **Recommendation** **partial.** The owner's matrix commit is asked for first (accept). The owner's call on 2b's placement is an FYI with a veto, not a blocker: the plan's own exception (line 10) is a rung-2 instruction to follow the bundle, and the bundle was observed (ruling 1). The `/health` fix is not a separate effort; its `all_accounts` branch is Phase 4's first ticket, a prefactor that can land in wave 1 (ruling 4), and the single-account branch is needs-human. The top-level adversary on 2b and the cross-spec grading fix are done (accept).

## Cut (YAGNI)

- **Pushing, deleting the worktree `t3code-42e075ae`, committing the bundle, live sends.** Floors 1–2 and the plan's Out of scope.
- **Matrix edits by Phases 0–5 and 2b; per-Phase matrix regrades** (plan lines 63, 74, 95, 108, 122, 133). Ruling 2: Phase 6 regrades all eight rows anyway, and the matrix holds the owner's uncommitted Sign-off. Regrades go to the recheck records.
- **Capture paths in the matrix's Visual evidence cells during Phase 0.** Phase 6 writes them from the recheck records.
- **A My Automations route, nav item and page-map entry for mass messages** (plan step 2 Work 4, 2b Work 1). The bundle places them on Smart Messages; the route is only the fallback if the owner vetoes.
- **Premade Mass, Mass funnels, Online Blast in the Mass Messages tab.** The plan's move list names four modules; they stay on the flag-only `/automations` page (ASSUMPTION, owner veto).
- **New Relay endpoints and new senders** (Message on purchase, Priority mass message). The plan forbids new sending paths; a Trigger with no existing send is Not wired.
- **Rewriting `ScheduledTab` and `MassMessagesTab`.** They move and are relabelled, not rebuilt.
- **The Smart Message wizard, collections and per-message Analytics.** Not wired where the capture shows them.
- **Scripts' tag and sequence fields.** No store exists; Not wired.
- **Tracking-link metrics the read does not return.** Not wired; CVR is derived client-side.
- **Per-tab permissions on Smart Messages.** One page-map entry per page (ADR-0007).
- **The Referrals feed on the Dashboard.** No relay kind; the tile is Not wired.
- **Renaming or moving `CompetitorReports`.** Rebuilt in place by Phase 3.
- **The Dashboard's own copy of Infloww colours.** ADR-0010 keeps the App accent.
- **Creator deactivate and Creator tags.** No field exists.
- **Moving the Server keys cards; showing the Relay's egress IP.** No page needs it; a new read would be required.
- **Changing `gdrive.py`, a per-Agency Drive key, Drive OAuth.** The owner's decision is the existing server key.
- **A pixel-diff gate and a committed walk harness.** Visual evidence is the capture plus REA screenshots in `/tmp`.
- **Fixing the run-tests legacy tests** (next-steps issue 44) **and the translator LLM tier** (ticket 28). Out of this plan.
- **Walk or harness changes and TODO-comment repointing in Phase 0.** The moved file's first line resolves the comments.
- **Clone edits outside Phase 0.**

## Not yet specified

- **Plan line 1's title ("move auto mass messages to My Automations").** Superseded, not specified: the plan's exception (line 10) and the bundle put them in Smart Messages' Mass Messages tab. ADR-0014 records it; the plan file is the owner's and is not edited.
- **Plan › Needs the human: delete the worktree.** Not specced by design (floor 2).
- **Plan › Needs the human: the pluggable translate provider, Google Translate default.** A later plan by the plan's own words.

Every other plan line maps to a spec.

## Open questions

Every ASSUMPTION in the specs, sharpest first. "Falls" is what has to be redone if it is wrong. Bracketed numbers are spec line numbers on 2026-10-17.

Placement, ownership and order
1. [2b:162] Phase 0's `growth-smart-messages.md` records the Mass Messages tab on Smart Messages that 2b observed. Falls: 2b's whole layout, ADR-0014's decision, Phase 2's frame slots and Phase 6's 3.5.1 grading; the My Automations fallback runs.
2. [2b:168, 2:210] 2b owns the Smart Messages frame (header, parent tabs, Create message pop-up) and Phase 2 fills two slots. Falls: the wave-3 order of Phase 2's Smart Messages ticket and both specs' Owns if the tickets merge into one change.
3. [2:196] Delayed welcome is wired to the OnlyFans welcome slot, not `send_welcome`. Falls: the Delayed welcome row's editor and test, and the Scripts welcome move (needs-human Phase 2 N1).
4. [2:200] "Existing per-fan send path" means an existing automation must already send on that Trigger, so Message on purchase is Not wired. Falls: a new purchase-triggered automation, `AUDIENCE_SENDER_CLASSIFICATION`, relay tests (needs-human N2).
5. [2b:171] Premade Mass, Mass funnels and Online Blast stay on the flag-only `/automations` page. Falls: 2b's Mass Messages tab gains a `ReadyMadePanel only=...` mount and Phase 6's 3.5.1 Labelled improvements.
6. [2b:169] Mass Nudge renders for owner sessions only and `/admin/mass-nudge` stays under Auto Post. Falls: the Smart Messages page-map entry and 2b seam 3's 403 case becomes a 200.
7. [2b:170] The hourly sweep's Save is disabled while no class is on. Falls: story 27 and seam 1; the empty-policy per-chat sweep needs its own labelled control.
8. [6:299] Mass messages are graded inside row 3.5.1, not a separate row. Falls: Phase 6 adds an "Auto mass messages" row if the fallback runs.
9. [2:206] A capture's mass tab mounts 2b's surface or links to it, per 2b's recorded placement. Falls: Phase 2's Smart Messages layout if the owner wants mass tabs hidden under the fallback.
10. [2b:172] Until Phase 2 lands, Mass Messages is the only parent tab. Falls: an interim page state, if the tickets merge.
11. [2:198] Automated Messages' key is `automated` and is the default tab; `mass` is 2b's. Falls: default tab, links and redirects, if the capture opens on Mass Messages.
12. [2b:167] Our sent history sits under the "OF mass message" child tab. Falls: 2b's child-tab strip, if the capture has one list.
13. [4:253] The `/health?all_accounts=1` clamp lands first as a prefactor with no capture. Falls: Phase 4's Order and wave 1, if the owner wants it as a separate security change.
14. [4:254] The clamp copies `admin_proxies_list`'s filter and a signed-out call gets 401. Falls: the signed-out answer becomes an empty `accounts` list if an unauthenticated monitor depends on it.
15. [1:177] `CompetitorReports` is a black box to Phase 1, rebuilt by Phase 3. Falls: Phase 3 adds a `variant` prop and Phase 1 mounts a frozen embed.
16. [3:144] The Dashboard embed changes with the shared module. Falls: same as 15.
17. [3:142] Creator reports' body is the existing `CompetitorReports`, rebuilt. Falls: a new module under `app/components/analytics/`.

Grading and matrix
18. [6:285] Labelled-extras-only rows read `intentionally improved`; `matched` means no difference. Falls: Phase 6's Acceptance grade case and every row's grade.
19. [1:171] §3.1 is `not wired` while any tile is Not wired. Falls: Phase 1's target grade.
20. [3:162] Creator reports' target grade is `intentionally improved`. Falls: Phase 3's Labelled improvements lines, if Phase 6 regrades.
21. [6:295] Phase 6 edits the matrix only after the owner commits the run-8 Sign-off. Falls: nothing if the owner commits; otherwise the matrix ticket stays parked.
22. [6:297, 1:179, 2:208, 3:154, 4:249, 5:146] Phase 6 alone edits the matrix, reading the recheck records. Falls: each Phase regrades its own row if the owner commits early and wants that.
23. [0:300] Phase 0's baseline lives in `baseline.md`; Phase 6 pastes it. Falls: Phase 0 §1 and §3 go back to the matrix and `set -e`.
24. [0:302] Phase 0 closes with the next-steps suite red on exactly the missing round-2 block. Falls: Phase 0 cannot close until the owner commits and the paste moves to Phase 0.
25. [0:304] The recheck record format is coined in Phase 0. Falls: every Phase's recheck section, if Phase 6 needs a missing field.
26. [4:247] The effort directory, not the capture, holds the rechecks. Falls: the path in every Acceptance.
27. [6:283] "A REA capture of the same page" is the Layout capture plus a `/tmp` REA screenshot cited by sha256. Falls: committed screenshots, or rows without one stay `unverified`.
28. [6:301] The §3.7 container row reads the worst child grade. Falls: one row's grade.
29. [6:287] The run-8 Sign-off is replaced, with a pointer to `7f0b1c04`. Falls: the next-steps suite's one-section check widens.
30. [6:303] The next-steps and route-walk Sign-off lines come from a rerun after grading. Falls: the run order; grading moves before step 1.
31. [6:289] "Nothing changed since" excludes the matrix and the effort directory. Falls: only the matrix is excluded.
32. [6:281, 0:308] Six suite lines, not five. Falls: one line moves to the notes.
33. [6:293] The Labelled improvements file check covers `app/components`, `app/lib`, `app/app` since `7f0b1c04`, with skips. Falls: a wider scan.
34. [0:336] Phase 0 does not add capture paths to Visual evidence cells. Falls: a Phase 6 step moves to Phase 0.
35. [0:306] The round-2 baseline is a new paragraph on top of `## Baseline run`. Falls: old entries removed.
36. [0:314] The Acceptance accepts any SHA descended from `7f0b1c04` with equal `app`, `service`, `scripts`. Falls: the baseline must sit on the recording commit.
37. [0:312] A merge-caused red is fixed in Phase 0, others parked. Falls: Phase 0's scope grows.
38. [1:165] An Infloww element we cannot have is an omission with a reason, not an unlabelled difference. Falls: on-page labels for omissions.

Bundle reading and capture mechanics
39. [3:166] (evidence blocked) Creator reports' section list comes from the Inventory and the Clone until the capture exists. Falls: Phase 3's section list.
40. [0:320] A rendered capture only if REA aborts every off-host request; else static. Falls: capture method (fonts allowed by the owner relaxes it).
41. [0:316] The bundle is served from a `/tmp/infloww-serve/` symlink tree. Falls: the serve recipe.
42. [0:330] Item IDs `<page>#<n>`, the Kind vocabulary and section names are coined in Phase 0. Falls: citation form in every later spec.
43. [0:328] The `layouts` step fails only on violations in existing files and counts missing ones. Falls: the step can require all eight.
44. [0:334] The capture records English strings and their offsets, not i18n keys. Falls: captures add keys.
45. [4:251] Creators components use translator keys, some with no `defaultValue`. Falls: label transcription until the capture resolves keys.
46. [5:148] Vault Pro's upload offset is from one `grep -F`, not REA. Falls: overruled by the capture.
47. [0:332] Leak-guard thresholds (40-char base64 run, 200-char span) are unmeasured. Falls: thresholds loosen on a false positive.
48. [0:310] "The OF Manager click-through" is `navigate.py` alone. Falls: the Acceptance adds `render.py`.
49. [0:322] Plan lines 62, 64, 66 are the rows citing `phone-composer-overflow`; 31, 40, 41, 67 too. Falls: fewer rows touched.
50. [0:324] The moved feedback file replaces three numeric ids and the sandbox name. Falls: the Acceptance's `[0-9]{8}` line.
51. [0:326] Code comments citing "TODO.md A1–B2" stay. Falls: a mechanical repoint ticket.
52. [0:318] Port 3401 for the bundle server. Falls: any free port.

Page details
53. [1:159] Employee sales joins the Dashboard's page-map entry, so a Dashboard-only chatter loads it. Falls: the tile becomes owner-only.
54. [1:173] The Dashboard header is Agency-wide and ignores the ScopeSwitcher. Falls: the header sends `account_id`.
55. [1:155] The Dashboard keeps `?window=` in the URL; the reports pages do not. Falls: the reports pages share it.
56. [1:157] Channel mapping (stream tips under Streams, `custom` under Messages, Referrals Not wired). Falls: tiles, per the capture.
57. [1:161] "Phase 2 cards" are the previous plan's shift cards. Falls: which cards the Dashboard keeps.
58. [1:163] Removing the developer strip and status card deletes no feature. Falls: they return as a labelled extra.
59. [1:169] The Dashboard keeps house colours and App accent. Falls: ADR-0010 amendment first.
60. [1:175] The default period is Today. Falls: the capture's default.
61. [1:167] `clone-dashboard.png` becomes a `ui-shots.sh` output. Falls: a one-off shot.
62. [1:181] Signed-out Dashboard reads are already 401. Falls: the ticket parks, no auth change.
63. [3:146] "Show net earnings" uses OF's `net_cents`, not ×0.8. Falls: a configurable fee rate.
64. [3:156] With net on, Creator statistics' per-kind columns, Pending, LTV, ARPU are Not wired and only Total switches. Falls: a per-kind fan-out or a new relay field.
65. [3:160] Net earnings shows `net_cents` with no VAT deduction, plus a disclosure. Falls: Net after VAT.
66. [3:148] Platform fee and VAT collected are Not wired. Falls: a combined "fees" row.
67. [3:158] Chargeback ratio stays Not wired. Falls: wired to OF's fixed 30-day read.
68. [3:152] Creator reports' `PAGE_MAP` entry gains `/admin/stats/revenue`. Falls: the money reads tie to the Dashboard grant.
69. [3:150] `?tab=` seeds via `useTabParam` and clicks write back with `replaceState`. Falls: in-memory tab only.
70. [3:164] The Route walk mock gains one synthetic "Creator A". Falls: a shared populated fixture in Phase 6.
71. [2:212] The Smart Messages page map gains nudge and welcome routes; Scripts keeps its welcome routes. Falls: Scripts' map trimmed.
72. [2:202] Status maps on to "Active" and off to "Canceled". Falls: the capture's status field.
73. [2:204] Scripts' "ladders" are the bundle's Sequences, Not wired. Falls: the script cursor counts as a sequence store.
74. [2:214] Subscription CVR and totals are computed client-side. Falls: a per-period CVR.
75. [4:237] "The extension in front" means first in the Add flow, not above the table. Falls: a page-head status line.
76. [4:235] "Probe unchanged" means same fetch, URL and console message on page load. Falls: the probe moves into the Add flow.
77. [4:239] No capture step is dropped; missing relay means Not wired. Falls: the modal is a launcher only.
78. [4:241] The status-label mapping is ours. Falls: a capture-pinned mapping.
79. [4:256] The flag outranks the probe; "—" is ours. Falls: a capture label for unknown.
80. [4:258] Extras go in one Extras overflow; the banner stays outside. Falls: banner inside.
81. [4:243] No Creator tag or deactivate field exists. Falls: a ticket finds one.
82. [4:245] Infloww's per-creator automatic proxy has no counterpart. Falls: a new egress-IP read.
83. [4:260] Bulk paste labels rows by `host:port`. Falls: a label field.
84. [4:262] The page is the card's only host. Falls: a second host needs the optional prop.
85. [5:138] If Infloww's upload area has link import, the owner's Drive decision still binds. Falls: owner.
86. [5:130] The Drive flag rides on the existing status read. Falls: a new route.
87. [5:136] Before a status answer, the Drive slot renders nothing. Falls: the line shows when closed.
88. [5:132] The Drive section sits under the file drop, above "Put into folder". Falls: placement at card bottom.
89. [5:134] The label is visible text and tooltip. Falls: tooltip only.
90. [5:142] The file drop accepts dropped files. Falls: picker only, if the capture shows no drop area.
91. [5:144] The setup line names "Setup → Keys, the Server keys card". Falls: wording, if Phase 4 moves the card.
92. [5:140] The Server keys card is hidden on phones; the line is not changed. Falls: wording.
93. [6:291] Walks use 127.0.0.1:3001. Falls: 3091 if free and wanted.

ADR-0014 also carries two: the capture agrees with the amendment (same as 1), and ADR-0003's Legacy-flag amendment does not govern the Growth pages, so the Nudge message and Mass Nudge show with the flag off (falls: both go flag-only).

## Needs the human

Phase 6
- Commit the uncommitted `## Sign-off` (+25 lines) in `docs/infloww-parity-matrix.md`. This unparks Phase 6's matrix ticket (steps 7–8). It is the only blocking human step.

Phase 2b (FYIs with a veto, not blockers)
- Placement: mass messages go in the bundle's "Mass Messages" tab on Smart Messages, per the plan's exception (line 10, "If REA shows Infloww puts them somewhere else, follow the bundle, and record where it was found"). Evidence in `~/Downloads/infloww-remote-web/index.9f50f370.js`: `var MessageSendTitle` @14654355 (parent tabs "Automated Messages" and "Mass Messages"), `changeSendType({parentTab:MessageSendType.Mass` @15747892 (child tabs Priority mass message and OF mass message), `var massMsgList` @14707943, the one Create message pop-up @14716722. Veto means the My Automations fallback (ADR-0014).
- Under that fallback, chatters lose the mass UI they have on Smart Messages today (My Automations is owner-only).
- Premade Mass, Mass funnels and Online Blast are Out of Scope, staying on the flag-only `/automations` page.

Phase 2
- N1: Delayed welcome is bound to the OnlyFans welcome slot (spec) or to `send_welcome`, or is Not wired. Settled by the owner's reading of "existing automation".
- N2: Message on purchase ships Not wired (spec) or gets a purchase-triggered automation over the existing send path.

Phase 4
- N1: the single-account `GET /health` returns a Creator's OnlyFans name and id, proxy URL with credentials and egress IP to unauthenticated callers. A fix may break bare `/health` probes (`scripts/start.sh:47,87`, `reload.sh:85`, `setup-caddy.sh:166`, `diag.sh:69`).

Phase 0
- None. D8's owner action is resolved by ruling 2.

All Phases
- Rerun the adversary with `codex exec` after the quota resets (Nov 11th, 2026) or after `codex login` (refresh token revoked) for Phases 0 (draft call), 1, 2, 2b, 3, 4, 5 and 6, if an independent second model is wanted.
- CONTEXT.md glossary: its owning session merges `.scratch/infloww-parity-round-2/glossary-pending.md`, correcting the "Auto mass messages tab" (now the Mass Messages tab on Smart Messages) and "Auto delete" (Infloww has per-message Auto-unsend; our sweep is the extra) entries.

Plan
- Delete the worktree `<worktree>` when no longer needed.
- The pluggable translate provider (Google Translate default) as a later plan.
