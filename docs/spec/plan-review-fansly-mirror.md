# Fansly Manager mirror — plan review

Plan: `.scratch/fansly-manager-mirror/map.md`. Specs: `phase-01-fansly-mirror-never-public.md`, `phase-02-fansly-mirror-capture.md`, `phase-03-fansly-mirror-generator.md`, `phase-04-fansly-mirror-app.md`. Glossary `CONTEXT.md`; ADRs 0065 (capture gate), 0066 (own generator), 0067 (Never-public path). Reviewed 2026-11-27: one codex adversary per spec, then six hats on the set; the coordinator accepted the Green cuts and the Reorder.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 1 — Never-public gates for `app/public/fansly-mirror` | `phase-01-fansly-mirror-never-public.md` | none |
| 2 | 2 — minimal Capture gate, self-test, `drive.py` mirror verbs | `phase-02-fansly-mirror-capture.md` | none for the build; ships after Phase 1 (order, not code) |
| 2b | Live tracer (coordinator, manual): 5 pages + 1 State, audited, Tracer facts into `fansly/capture/RECIPES.md` | Phase 2 stories 38-39 | Phase 2 merged; signed-in :9231, zero-unread fan thread, fan account id, light theme |
| 3 | 3 + 4 — generator and guard, app integration, one PR | `phase-03-fansly-mirror-generator.md`, `phase-04-fansly-mirror-app.md` | 1 merged; Tracer facts recorded (before any code); full capture `complete: true` before the coordinator's real generator run, committed in the same PR |
| 3b | AE flag-on (coordinator, manual, after AE deploy) | Phase 4 story 29 | Phase 3+4 deployed to AE; ae-deploy DB backup |

Ship order: Phase 1 → Phase 2 → live tracer + Tracer facts → Phase 3+4 code (empty table first) → remaining capture sessions → `gate.py manifest` complete → real generator run committed → PR merged → AE deploy → flag on for AE + WATCH.md line.

ASSUMPTION: the full capture (beyond the tracer) can run while Phase 3+4 code is written, since it changes only files outside the repo (rung 4). Overturned if the tracer shows the plan or gate needs changing, which then lands as a Phase 2 follow-up PR before the full capture.

## Adversary
- Phase 1 (`phase-01-fansly-mirror-never-public.md`): codex; 6 accept, 6 partial, 7 reject (D8 split: wording accepted, fixture point rejected); needs-human none.
- Phase 2 (`phase-02-fansly-mirror-capture.md`): codex; 13 accept, 6 partial, 2 reject; needs-human none. Story numbers in its lines refer to the pre-trim draft.
- Phase 3 (`phase-03-fansly-mirror-generator.md`): codex; 17 accept, 4 partial, 1 reject (B5, B6, D6 carry split-off reject/reject/partial parts); needs-human none. D3's rollback and D8's `--absent-ok` accepts were later cut by the six-hats trim (recorded in that spec's Six hats subsection).
- Phase 4 (`phase-04-fansly-mirror-app.md`): codex; 8 accept, 7 partial, 4 reject; needs-human none. B6's "slow A → B switch" proof now runs in `navigate.py` only.

## Six hats
Set-level bullets only; per-spec bullets are in each spec's `### Six hats (plan review, 2026-11-27)` subsection.
- White, 1,024 lines / 150 stories for a static copy — **accept**: trimmed to 50 + 45 + 29 stories over Phases 2-4 (Phase 1 unchanged); Phase 2's self-test 18 → 5 cases.
- White, unresolved guesses across Phases 3/4 (dark marker, banner field, class names, opener syntax, telemetry halts) — **accept**: one live tracer measures all five into RECIPES "Tracer facts" before Phase 3/4 code (Phase 2 story 39).
- White, missing pieces (flag-on for AE, refresh plan, asset size budget) — **accept** flag (Phase 4 story 29) and refresh (Phase 2 story 50); **partial** asset budget (summary prints total bytes, per-file 2 MB cap only; no total cap, OF has none).
- Red, the rig is larger than the product — **accept**: the Phase 2 trim and the Phase 4 scope cuts.
- Black, Phases 3/4 built on guesses — **accept**: Reorder puts the tracer before their code.
- Black, telemetry halts stop the tracer — **partial**: halts stay (ADR-0065); each costs one re-run plus a local `204` fake recorded in RECIPES.
- Yellow, Phase 1 cheap and guards the irreversible step; default-deny is right; keeping the four Built pages is no regression — **accept**, no change.
- Green, cuts per Phase — **accept**: deleted from the specs and listed under each spec's Out of Scope as "deferred (YAGNI, six-hats)".
- Blue, merge Phase 1 now, run the trim, tracer records facts, a line on who turns the flag on — **accept**: Workstreams above; flag-on is the coordinator's after the AE deploy.
- Recommendation, ship Phase 1; minimal gate + tracer; then Phases 3+4 trimmed as one PR — **accept**: Workstreams and each spec's Depends on.

## Cut (YAGNI)
Phase 2:
- `tclick` commit-word refusal list — the gate denies every write anyway.
- `drive.py` output redaction — its output reaches only the coordinator's terminal.
- Unread pagination rules (every unread group present at the end, first observation before first save, 30 s settle) — audit compares groups present in both observations.
- Three-session stage machinery (stages, per-stage audits, quarantine, merge, bundle-mismatch merge refusal) — one capture root, re-runnable per entry; Phase 3 refuses mixed bundle hashes.
- 13 self-test cases (cross-origin PUT, `POST→303`, `sendBeacon`, form POST, popup, cross-site iframe, sockets before/after arming, arming failure, watchdog SIGKILL, `drive.py` round trip) — behaviours stay specced; unit tables and the tracer audit cover them.
- `--ws-stub` flag and `ws_stub_needed` measurement — stub always armed.
- Automated refresh — re-run capture and generator by hand.

Phases 2 and 3:
- Nested States (Edit Post from the own-post menu, composer sub-pickers, profile "+ New" → Create New Album, State-in-State keys) — left out of the plan, `REQUIRED` and the generator.

Phase 3:
- Swap rollback code and `FANSLY_MIRROR_FAIL_AT` failpoint tests — a crash mid-swap leaves `<out>.old`, which the next run refuses.
- Two-run idempotence check — determinism rules stay.
- `--check --absent-ok` and the bootstrap split — plain `--check` passes an absent dir.
- `raw.py` as its own script — merged into Phase 4's `render.py`.
- A total asset size cap — summary prints total bytes; per-file cap stays.

Phase 4:
- Second seeded Fansly Creator and `/img` cache seeding in verify-app — switch proven in `navigate.py` with mocked accounts.
- Expired-pick SessionGone, OnlyFans-id pick and Watcher-pick stories — `known` holds Fansly Creators only; anything else is "no pick".
- Shim `header` when the tracer records no banner field.

Kept on purpose (named by the coordinator): default deny on all hosts, socket block + reload, WS stub fallback, watchdog blanking, `gate.jsonl` audit of zero continued writes, the unread-drop check, the planted-leak self-test, the unreviewed-long-text failure, the URL sink allowlist.

## Not yet specified
- Real Fansly data rows and writes in the mirror pages (map "Not yet specified", phase 2 of the effort).
- The nested States deferred above, if the owner wants them: each needs a plan entry, an opener inside a State page and a State-in-State key.
- A dark copy if the tracer records "stylesheet swap" (would need a dark capture; Phase 3 parks it).

## Open questions
Sharpest first; each with what falls if wrong.
1. ASSUMPTION (Phase 2, inferred): a killed gate lets requests through only until the watchdog blanks, and no POST lands in that window. Falls: the whole no-write promise; the `gate_sigkill_watchdog` case measures it, and a fail adds the watchdog's own deny-writes Fetch before any live run.
2. ASSUMPTION (Phase 2, rung 2): telemetry writes halt with no standing exception. Falls: tracer runnability; if halts repeat beyond a few re-runs, ADR-0065 needs an amendment.
3. ASSUMPTION (Phase 2, guess): Fansly's theme is client-side. Falls: the live run parks for the owner if light theme needs a write.
4. ASSUMPTION (Phases 3/4): the dark marker is a root class/attribute read from collected CSS. Falls: the dark copy; "stylesheet swap" parks dark before Phase 3/4 code.
5. ASSUMPTION (Phase 2, evidence blocked): `/notifications/ack`, `/mediastory/view` and (until copied) `/it/pis` fake replies are `{"success":true}`, marked `unverified`. Falls: look only, never a write.
6. ASSUMPTION (Phase 4, rungs 1/3/4): flag turned on by the coordinator for every AE Agency holding a Fansly Creator. Falls: who sees Fansly Manager on AE; per-Agency toggle back off.
7. ASSUMPTION (Phase 3): the tracer's class hooks and opener forms carry over to pages beyond the tracer. Falls: only grows the text rule table / opener matcher at the real run (red run, not a leak).
8. ASSUMPTION (Phase 3): unmatched text of 20+ chars or 3+ words fails the run; shorter is left to people needles and screenshots. Falls: short private text could ship; threshold drops.
9. ASSUMPTION (Phase 2): one capture root, failed sessions' saves left out of the manifest rather than quarantined. Falls: quarantine returns if a failed session's file must be kept apart physically.
10. ASSUMPTION (Phase 3): `--check` passes an absent mirror dir. Falls: a mirror deleted on private main/AE is caught only by Phase 4's `render.py` and Acceptance.
11. ASSUMPTION (Phase 2): WS stub always armed. Falls: a page that breaks under the stub needs the measured on-demand mode back.
12. ASSUMPTION (Phase 2): nested States are the four read from ticket 01. Falls: the plan; the tracer may put one back.
13. ASSUMPTION (Phase 4, rung 5): a dead Fansly pick falls back to the first live Creator with the hint. Falls: chrome only; OF's SessionGone panel if the owner wants it.
14. ASSUMPTION (Phase 4, rung 2): A → B switch proven in `navigate.py` with mocks, not the real app. Falls: proof depth only; the second seed returns on owner request.
15. ASSUMPTION (plan review, rung 4): the full capture runs in parallel with Phase 3+4 code. Falls: ordering only, if the tracer forces gate changes.
16. ASSUMPTION (Phase 2): the watchdog blanks every http(s) tab in the creator Chrome. Falls: unrelated tabs in that profile get blanked.
17. ASSUMPTION (Phase 2): only AWS WAF challenge POSTs are excepted; Cloudflare halts. Falls: tracer re-run plus a WAF-style exception if Cloudflare challenges.
18. ASSUMPTION (Phase 2): fan identity read only from the creator session. Falls: manifest stays `complete: false` until the owner allows a gated :9232 read.
19. ASSUMPTION (Phase 3): mixed bundle hashes fail. Falls: a re-capture across a Fansly release.
The remaining ASSUMPTION lines (test style, ports, venv, `key` without Enter, legacy `drive.py` verbs, route slugs, attribute quoting, guard message policy, asset blanking, close-control matching, nav/redirect/watch choices, Phase 1's `$lock`, replay and selftest lines) are lower-stakes and stay in their specs' Further Notes.

## Needs the human
- OF mirror (397 files) on public/main and twin/main against its NOTICE: add `^app/public/of-mirror` to NEVER_PATHS and remove it from public? Blocks nothing here (map, Phase 1 Out of Scope).
- Live tracer prerequisites only the owner can provide: creator Chrome on :9231 signed in, a zero-unread thread with the fan test account, that account's id, light theme showing without a write.
- Veto window on the AE flag-on scope (every AE Agency holding a Fansly Creator vs only the client Agency vs leave off).
