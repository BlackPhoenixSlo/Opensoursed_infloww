# Plan review: Infloww parity next steps

This is the plan review for `docs/plans/infloww-parity-next-steps.md`. A file named `docs/spec/plan-review.md` already exists and belongs to the earlier messages-pro-parity effort. It is left untouched, and this review is written to `docs/spec/plan-review-infloww-parity-next-steps.md` instead.

Review of the seven Phase specs, 2026-10-16. Inputs:
- the specs `docs/spec/phase-00-merge-stale-docs-route-matrix.md`, `phase-01-agency-context-employee-identity.md`, `phase-02-shifts-time-tracking.md`, `phase-03-share-for-share.md`, `phase-04-apply-stored-settings.md`, `phase-05-remaining-parity-gaps.md` and `phase-06-sign-off-matrix.md`. The other `phase-NN` files in `docs/spec` belong to an earlier effort.
- their codex adversary reviews;
- the six-hats report on the set (`.scratch/infloww-parity-next-steps/review/six-hats.md`).

The six-hats report was reconciled into each spec, in a `### Six hats` subsection at the end of its `## Review`. Two entries were added to the plan's `## Needs the human`. This is design only: no code, no migration and no network access.

## Workstreams

Waves follow each spec's Depends on. A Phase sits in the first wave after every Phase it depends on, and Phases in the same wave can be built in parallel.

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 0 | 0. Merge, stale docs, route matrix | `docs/spec/phase-00-merge-stale-docs-route-matrix.md` | none |
| 1 | 1. Agency context and employee identity | `docs/spec/phase-01-agency-context-employee-identity.md` | Phase 0 |
| 2 | 2. Shifts and time tracking | `docs/spec/phase-02-shifts-time-tracking.md` | Phases 0 and 1 |
| 2 | 3. Share for Share | `docs/spec/phase-03-share-for-share.md` | Phases 0 and 1. Its only shared point with Phase 2 is the Alembic head. Neither side's reversibility check uses a relative step any more |
| 3 | 4. Apply the stored Settings | `docs/spec/phase-04-apply-stored-settings.md` | Phases 1 and 2 (and 0 through them) |
| 4 | 5. Remaining parity gaps | `docs/spec/phase-05-remaining-parity-gaps.md` | Phases 0, 2 and 4. Not Phase 3, so Phase 3 may still be open while Phase 5 is built |
| 5 | 6. Sign-off matrix | `docs/spec/phase-06-sign-off-matrix.md` | Phases 0–5 |

## Adversary

- **Phase 0:** codex (blind and draft calls). 6 accepted, 5 partial, 5 rejected. Needs-human: none. Six hats: 3 accepted, 1 partial, 1 rejected.
- **Phase 1:** codex (blind and draft calls). 7 accepted, 2 partial, 5 rejected. Needs-human: none. Six hats: 2 accepted.
- **Phase 2:** codex (blind and draft calls). 4 accepted, 6 partial, 9 rejected. Needs-human: none. Six hats: 3 accepted.
- **Phase 3:** codex (gpt, `model_reasoning_effort=high`, blind and draft calls). 7 accepted, 2 partial, 6 rejected. Needs-human: none beyond the plan's existing S4S policy entry (fields, lifecycle, disable behaviour), which this spec proceeds on by ASSUMPTION. Six hats: 2 accepted, 2 rejected.
- **Phase 4:** codex (blind and draft calls). 6 accepted, 3 partial, 11 rejected. Needs-human: D2, the LLM spend of the translator prompt tier. Codex's reviewer rejected it as a finding but asked for a Needs the human entry, and that entry is now in the plan. Six hats: 4 accepted, 2 rejected.
- **Phase 5:** codex (gpt, `model_reasoning_effort=high`, read-only sparse worktree, blind and draft calls). 9 accepted, 3 partial, 12 rejected. Needs-human: none. Six hats: 2 accepted, 3 rejected.
- **Phase 6:** codex (blind and draft calls). 7 accepted, 2 partial, 4 rejected. The six-hats review later withdrew D4 (the eight-fault self-test). Needs-human: none. Six hats: 3 accepted, 1 partial.

## Six hats

Reconcile lines for the bullets about the set as a whole. Bullets that name a spec are reconciled in that spec's `### Six hats`.

- **White (Set facts):** the specs add about 2,100 lines in the roadmap's suggested order, nothing has been run and nothing has been ticketed. **Accept** as fact, no change. At this step nothing is expected to be ticketed or run.
- **White (Set / phase-00):** the merge is only assumed, and `ff715056` sits past the pinned tip. **Accept.** The second merge is now on the plan's Needs the human list. Phase 0's own line is in its spec.
- **White (Set gaps):** Creators/proxy tenancy, churn/LTV, and keyboard/focus have no Phase. **Partial**, decided by rung 5:
  - The Creators/proxy tenancy check is cheap and is folded into Phase 5 as item 9 (one matrix row and one negative test).
  - Churn/LTV needs per-Fan subscription history that is not stored, and a new analytics read. It goes to Not yet specified.
  - Keyboard/focus walks are not cheap. Phase 6 still tags keyboard differences from the existing harnesses, and the improvement itself goes to Not yet specified.
- **Red (Set):** too much spec for a deployment of 2–5 agencies; each Phase grew past the plan. **Partial.** Two cuts were applied where the plan never asked for the item: Phase 4's reports "This week" preset, and Phase 6's committed route walk with its self-test. Four growths stay, because plan text or the plan's Baseline requires them: Phase 3 publishing, Phase 4's LLM tier, Phase 5's Batch actions, and the view revision behind Sales records. Each is reasoned in its spec.
- **Black (phase-04/05/06, cross-cutting ownership):**
  - Ownership of `suite.sh` is settled once, in the same words in Phase 0 and Phase 6. Phase 0 creates it, Phases 1–5 leave it alone, and Phase 6 alone extends it.
  - The relative `downgrade` steps in Phase 3 and Phase 5 now target named revisions.
  - Phase 5's one line in Phase 4's permissions module stays, because the plan puts it there.
- **Green (Set, do less first):** ticket only Phase 0, and hold Phases 3–6 until the owner rules on S4S policy, the role rollout and LLM spend. **Rejected on constraint.** The invocation (`--execute --tickets 999`) already chose to execute the whole plan, and the plan's order binds. Its owner questions remain on the plan's Needs the human list, where Phase 3, Phase 4 and the translator tier proceed on flagged ASSUMPTIONs until vetoed. The YAGNI cuts were kept wherever the plan never asked for the item:
  - **The translator LLM tier: not cut.** Plan Phase 4 Work requires the prompt to be applied ("passed to `/admin/translate` as its instruction"). The spend goes to Needs the human.
  - **The "This week" preset: cut**, rung 5.
  - **Batch actions: not cut.** The plan's Baseline row names the gap (plan:69).
  - **The view-revision migration: not cut.** Plan item 3's per-sale Reassign needs a transaction id, and the view is the single definition of attribution (rung 3).
  - **The committed route walk and its self-test: cut.** Rung 2: plan:305 says "with the existing harnesses".
- **Blue (Set):** fix the two contract mismatches first and settle `suite.sh` ownership. **Accept.**
  - The `agency_context` signature follows Phase 1: `agency_context(*, account_id=None)`. Phase 2 is rewritten (rung 3).
  - The Timesheet and "clocked-in now" stay owner and Master only (Phase 2), and Phase 4 drops Data scope on them (rungs 4 and 5).
  - Ownership of `suite.sh` is settled as described under Black.
- **Blue (Plan):** add the LLM-spend decision to Needs the human, and record that `ff715056` needs a second merge. **Accept.** Both are now in the plan's `## Needs the human`.
- **Recommendation:** fix the mismatches and the missing LLM-spend entry, run Phase 0 alone, and hold Phases 3–6. **Partial.**
  - The fixes and the entry are done.
  - Holding Phases 3–6 is rejected on constraint, as under Green.
  - Of the Green trims, two are applied and three rejected by rung 2 or rung 3, as listed under Green.

## Cut (YAGNI)

The specs' Out of Scope, deduplicated. "→ Phase n" marks an item that moved to another Phase rather than being cut.

**Floors and live systems**
- Pushing `main` or the branch, or any remote tracker write (Phases 0, 6). Floor 2. The owner decides when to push.
- Live OnlyFans checks and guessed bodies: connectors 06, 12, 19, 31, 38 and 46, S4S live posting, the trial-link create and the promotion create (Phases 0, 3, 5, 6). Floor 2, and the roadmap's "do not guess a request body". Each is parked with a question.
- Running any Alembic migration against a real database (Phase 0). The merge brings files only.
- Fresh authenticated Infloww captures (Phase 6). The account is banned, so saved evidence is used with its uncertainty marked.

**Merge and docs (Phase 0)**
- `ff715056` and any later commit on the branch. They are not part of the finished runs, so a second merge is the owner's call (now on Needs the human).
- Scrubbing the absolute home paths that `scripts/check-public-export.sh` flags. The settings-tabs RUN.md leaves this to the human.
- Editing `archive/` or `ui-redesign/infloww-exact/` notes that say S4S was dropped. They are July evidence, not current docs.
- Re-grading Messages Pro or Settings visuals (also Phase 6). Both are signed off by their parity docs.
- Grading rows beyond what current evidence supports. Such a row is `unverified`.

**Harnesses and screenshots**
- A committed route-walk harness, its self-test, new screenshot sets and committed PNGs (Phases 0, 6). The plan says "with the existing harnesses", and PNGs stay in `/tmp`. The six-hats review cut Phase 6's committed walk.
- Walking `legacy: true` routes (Phase 6). The flag is off (ADR-0003), so they are listed from code.
- A Chatter-session walk (Phase 6). It duplicates `nav.test.ts` and Phase 4's Relay seams.
- Loading-state shots and keyboard walks (Phase 6). Loading is timing-dependent, and keyboard paths are owned by ui-shots and the Settings walk.
- A pixel-diff tool or any new dependency (Phase 6). Grading is by eye against the Clone.

**Identity and auth**
- New auth, 2FA, password change, sessions, picture upload, Billing, invoices, wallet and Your Balance payouts (Phases 1, 4). No backend exists, and the roadmap says to keep them unavailable.
- Changing the owner `X-Employee-Id` pick for chat-send attribution, or the unauthenticated cron fallback (Phase 1). The plan keeps both.
- An owner-to-Employee link, so owners cannot clock in as themselves (Phases 1, 2). It needs a new identity model the plan does not ask for.
- A "whoami" endpoint for the Agency context (Phase 1). `/auth/me` and `/chatter/me` suffice.
- Retrofitting Settings and roster routers onto `agency_context` (Phase 1). This is churn with no change in behaviour.
- Agency selection by a raw agency id (Phase 1). The plan forbids it.

**Shifts (Phase 2)**
- Payroll, pay rates and payouts. The roadmap forbids claiming to pay employees.
- Platform split of hours. Infloww itself does not split them.
- Native desktop, email or push notifications, and any OnlyFans send. The reminder is in-app only.
- A scheduler for auto clock-out. The plan forbids a new scheduler, so the sweep is lazy.
- Non-weekly repeats and single-occurrence exceptions. The Inventory shows weekly repeats only.
- Owners creating a Clock event from scratch. It is neither in the plan nor in the Inventory, and owner edit covers corrections.
- A per-Shift history screen. The existing audit views cover it.
- A Master view of every Agency's schedule. It is additive later.
- Moved, not cut:
  - attribution rules applied to the Timesheet → Phase 4;
  - Clocked hours and the shift history columns on Employees → Phase 5;
  - permissions and the week start → Phase 4.

**S4S (Phase 3)**
- Any cross-deployment or public directory, and Infloww's community. The roadmap and ADR-0011 forbid both.
- Importing, scraping or fabricating Creators. Existing records only.
- Media on S4S posts. No known body moves media between accounts.
- Operating or posting on another Agency's account (ADR-0011).
- Fan data in S4S. It is outside the projection.
- S4S analytics. The plan cuts it.
- Chatter or Employee access to S4S. It waits for Phase 4 roles to grant it.
- Recurring or multi-slot requests. The reference shows single posts.
- Notifications to the partner owner. The Received tab is the inbox.

**Settings (Phase 4)**
- Language Settings. There is no UI translation layer.
- Rewriting historical attribution rows. ADR-0012 limits attribution to the read path.
- Showing the Agency name. No consumer is buildable in this Phase. See Not yet specified.
- Per-operation permissions. The stored role has one boolean per page.
- A Deployment-wide kill switch for enforcement. The per-Agency switch already rolls back.
- A `roles` table or role column. ADR-0007's YAGNI holds at 2–5 Agencies.
- Applying the regular time zone to other times. The Inventory names only the top bar label.
- Auditing enforcement denials. A refused request changes nothing.
- The reports' "This week" preset. It was invented with no evidence, and the six-hats review cut it.
- Moved, not cut: employee groups and real "Self and subordinates" → Phase 5.

**Remaining gaps (Phase 5)**
- Leaderboard and Referrals (intentionally different), the Fansly / mym / Fanvue selector, Idle mode and the update prompt, and Help center content. Each is parked with a question.
- A new analytics service, rebuilding Smart Messages, Scripts or Vault Pro, and removing any Inflowwww-only workflow. Plan Out of scope.
- xlsx export. It would need a new dependency, so export is CSV only.
- The Fan reports retention table. Per-Fan subscription periods are not stored.
- Baseline "partly" rows outside the ranked list: Fan reports' New/Total fans, Employee reports' other tabs, Message dashboard filters, Creators' clone extras, Sensitive Words / AI Copilot. The matrix carries them.
- New Smart list rules. Item 8 only checks and lists them.
- "+ Add employee" Email, Phone, Role and Group fields. There are no columns for them and no invite flow.
- "Performance (all-time)", the Creator tag filter, and group rename or drag-move. They are unconfirmed or have no data.
- The bell's click behaviour and the Tips `type` value. Ticket 31 stays parked.

## Not yet specified

Lines in the plan, and in the roadmap it was derived from (`nestStepsInflowCopy.txt`), that no spec covers:

- **The Creators surface as a whole** (roadmap:233-234: "manage/link/deactivate creators, account status and recovery, custom proxies, and creator filters/actions"). Phase 5 item 9 now covers only the tenancy check.
- **Churn and LTV fan analytics** (roadmap:124). There is no per-Fan subscription history, which Phase 5's retention cut already found, and the plan's Phase 5 rules out a new analytics service.
- **Accessible keyboard and focus states as an improvement** (roadmap:159, :166). Phase 6 tags keyboard differences in the matrix from the existing harnesses, but no Phase walks or improves keyboard paths.
- **"Reports start on its week start day"** (plan Phase 4 Work). The reports have no weekly grouping. The six-hats review cut the invented "This week" preset, so the week start reaches only the Shift schedule and "My shifts".
- **"The agency name shows where Infloww shows it"** (plan Phase 4 Work). Phase 4 points it to the Organization Chart root in Phase 5 item 4, but the Phase 5 spec never shows the Agency name. Its Leaderboard consumer is parked.

## Open questions

Every ASSUMPTION in the seven specs, sharpest first. The first block is ranked by what falls if it is wrong. The rest follow by spec, and each line ends with what falls (the spec's own "Overturned" clause). References are `phase:line`.

**Sharpest**
1. **00:257, the merge itself.** The merge takes the pinned `4c9c7160`, and the plan assumes the owner wants it at all. If the owner declines, every Phase runs on the branch, and every spec's file references and Depends on Phase 0 have to be re-based.
2. **04:321, the translator LLM tier.** If the owner vetoes per-message spend, Phase 4's prompt stories, the prompt-tier tests and the cache-key work are cut. The prompt stays "Not applied yet", with its note.
3. **03:194, :208, :210, the S4S projection, lifecycle and opt-out cascade.** These rest on the owner's policy, which the roadmap says to confirm first. If it is wrong, Phase 3's schema columns, its Lifecycle rules and the cascade tests change. It is on Needs the human.
4. **01:160, the `agency_context(*, account_id=None)` signature.** If a later Phase needs the request object, every call site in Phases 2–5 gains a first positional `request`. It was settled against Phase 2 by the six-hats review.
5. **02:210, the Timesheet and clocked-in now are owner and Master only.** If the owner wants chatters to see them, both open, and Phase 4's Data scope has to be re-added to both endpoints, the reverse of the six-hats reconcile.
6. **04:301, :303, enforcement refuses unassigned Employees and denies missing pages.** If wrong, turning enforcement on locks out unassigned staff, or a default role is needed.
7. **04:313, "Shift schedule" credits clocked-in Employees, split evenly, and falls back to Converters while time tracking is off.** If wrong, every Employee report figure under the default rule changes.
8. **01:164, a multi-agency chatter naming no Creator gets 400.** If the owner wants a remembered current Agency, a stored preference is needed, and every Phase's chatter cases change.
9. **02:136, one `me` call spans every Agency a chatter is linked to.** If Phase 1's rule forbids the union, `me` takes a required `account_id`, and the Dashboard card changes.
10. **03:218, S4S live posting is one Deployment-wide env flag.** If per-Agency control is wanted, it becomes a setting and a migration.
11. **04:319, a never-stored translation switch counts as on.** If the owner wants translation off until enabled, every Agency that never opened Messaging settings loses translation on upgrade day.
12. **05:188, Sales records reads a view revision with `tx_id` and `rule`.** If any reader selects the view positionally, the revision breaks it. A grep at ticket time must rule this out.
13. **06:263, every routed row's Phone cell reads "intentionally improved".** If the owner wants Phone graded per row, Phase 6 has to grade 390×844 against evidence that does not exist.
14. **05:176, item 9 (the Creators tenancy check) is folded into Phase 5.** If the owner wants the Creators surface specced whole, the test moves to that plan.
15. **00:253, Landing loses the dead `REPO_URL` import.** If the owner wants the repo link back, it is a new change, not a merge resolution.

**The rest, by spec**

*Phase 0*
- **00:255:** `CONTEXT.md` is a second conflict the plan did not list, and it is resolved as the union, with `main`'s block first. *Falls if wrong:* Overturned if a term turns out to be defined differently on the two sides.
- **00:259:** The implementer stages the merge (`--no-commit`) and the coordinator commits it. *Falls if wrong:* Rung 2 (repo rule), so it has no overturn.
- **00:261:** Phase 0 creates `.scratch/infloww-parity-next-steps/suite.sh` with two steps, `matrix` (shape check) and `relay` (the five relay tests), and it never calls another suite. *Falls if wrong:* Overturned if the owner wants every Phase to append its own tests as it lands, in which case each Acceptance block of Phases 1–5 gains one `relay` line.
- **00:263:** The relay tests run here are the five the branch touched or added, not all 228. *Falls if wrong:* Overturned by any relay failure that shows up during the walk's relay-backed ui-shots stack.
- **00:265:** The matrix uses seven Matrix status values, the plan's six plus `intentionally different` for Leaderboard and Referrals, and it treats §1, §2, §3 and §6 as containers or non-surfaces without rows of their own. *Falls if wrong:* Overturned if the owner grades those surfaces `blocked`, or wants container rows.
- **00:267:** The Messages Pro row and the 11 Settings tab rows copy their grades from `docs/messages-pro-parity.md` and `docs/settings-parity.md` without a re-walk. *Falls if wrong:* Overturned by a walk cell in this Phase that fails on those routes. That cell's row then reads `unverified`, with the failure.
- **00:269:** The four-route walk uses the two existing harnesses where they reach, plus a throwaway `/tmp` Playwright pass that copies walk.py's mock routing for the cells they don't reach (`/` and `/employees` entirely, `/settings/time-tracking` in light). *Falls if wrong:* Overturned if the owner wants a committed route-walk harness, which Phase 6 would then own.

*Phase 1*
- **01:162:** The helper lives in the employees module rather than the auth module. *Falls if wrong:* Overturned if the owner prefers all tenancy helpers in the auth module, which needs only a move and a re-export.
- **01:166:** When a Creator is held by two of a chatter's linked Agencies, the alphabetically first owner id wins. *Falls if wrong:* Overturned if cross-grants are removed or the owner picks another rule.
- **01:168:** The Master's `agency_user_id` is its own id. *Falls if wrong:* Overturned if the owner wants the Master to act inside whichever Agency holds the named Creator.
- **01:170:** Mirror Employee creation on first use stays a write inside a read path, as it already is for chat-send. *Falls if wrong:* Overturned if a later Phase needs a read-only context, which would add a `create=False` flag.
- **01:172:** The Phase's tests drive `agency_context` through a probe route that the test file mounts on the Relay app, rather than through a production endpoint. *Falls if wrong:* Overturned if a later Phase's real endpoint lands first and can serve as the seam.
- **01:174:** A database failure while resolving the Mirror Employee answers 503. *Falls if wrong:* Overturned if the owner prefers a degraded context with `employee_id` null.
- **01:176:** The chatter's Agency for a named Creator is filtered by its Chatter Access allowlist before the alphabetical tie-break, while `resolve_chatter_employee_id` keeps its unfiltered tie-break. *Falls if wrong:* Overturned if the owner wants the two to agree in the cross-grant edge, which means applying the same filter inside `resolve_chatter_employee_id`.

*Phase 2*
- **02:100:** `clock_events` carries `agency_user_id`, which the plan's column list leaves out. *Falls if wrong:* Overturned if the owner wants a deleted Employee's time dropped instead, which would make it CASCADE.
- **02:102:** A Shift with E Employees and C Creators stores E×C `shift_assignments` rows, one per (Employee, Creator) pair. *Falls if wrong:* Overturned by evidence that Infloww pairs Employees and Creators selectively inside one Shift.
- **02:106:** Shifts and Clock events are kept until their Agency is deleted. *Falls if wrong:* Overturned if the owner wants the edit history kept longer than other audit rows.
- **02:138:** A Master gets no cross-agency read or write of schedules here. *Falls if wrong:* Overturned if the owner wants a Master view of every Agency's schedule.
- **02:147:** An edit or cancel always applies to the whole series. *Falls if wrong:* Overturned by evidence of a per-occurrence edit.
- **02:149:** 🗑️ cancels a Shift (soft) and never deletes the row. *Falls if wrong:* Overturned if the owner wants a hard delete for Shifts created by mistake.
- **02:159:** The 53-week cap and the write-only check are rungs 5 and 4. *Falls if wrong:* Overturned if the owner wants turning the setting off to flag existing clashes.
- **02:195:** Edit history is read through the existing audit views. *Falls if wrong:* Overturned by a request for a per-Shift history panel.
- **02:208:** The Sales note wording is new copy, rung 5. *Falls if wrong:* Overturned by Phase 4's per-field note design.
- **02:214:** Refusing an assignment the chatter cannot clock, rather than allowing it. *Falls if wrong:* Overturned by Phase 4's Data scope, if it decouples clocking from Creator access.
- **02:318:** The endpoints live under `/admin/shifts` rather than `/api/shifts`. *Falls if wrong:* Overturned by a routing convention that the Phase 0 matrix records.
- **02:320:** `zoneinfo` needs no new dependency in the Relay image. *Falls if wrong:* Overturned if a test run shows `ZoneInfoNotFoundError`. In that case adding `tzdata` to `requirements.txt` is a new dependency, which parks the ticket with the exact `pip install tzdata` command for the human.
- **02:322:** A Shift's length is capped at 24 hours, and a range read at 42 days. *Falls if wrong:* Overturned by evidence of longer Shifts.
- **02:324:** A Clock event's Shift link is recomputed from the Shift's current rule when the Timesheet and the sweep run. *Falls if wrong:* Overturned if editing a Shift after it was worked must leave past "Shifts worked" untouched, which would need an `occurrence_start_utc` column on `clock_events`.
- **02:326:** "My shifts" shows today plus the next seven days. *Falls if wrong:* Overturned by evidence of Infloww's range.

*Phase 3*
- **03:196:** The display fields are entered by the owner in the S4S Setting panel and prefilled from the Creator's nickname. *Falls if wrong:* Overturned if a cached OF identity for the Creator becomes available on the Relay.
- **03:198:** Foreign Creators are referred to by S4S profile id, never by account id, so the isolation middleware's numeric-segment 403 is never bypassed or loosened. *Falls if wrong:* Overturned by nothing in the plan. It is a way to satisfy ADR-0011 without touching the middleware.
- **03:200:** Share for Share is owner-only. *Falls if wrong:* Overturned when Phase 4's role permissions grant S4S to an Employee role.
- **03:202:** A Master session is treated like an Owner session. *Falls if wrong:* Overturned by the owner wanting S4S closed to the Master.
- **03:204:** S4S is reciprocal. *Falls if wrong:* Overturned by evidence that Infloww's S4S is one-directional.
- **03:206:** A request carries one proposed `slot_at`. *Falls if wrong:* Overturned by evidence of Infloww's request form (the inventory records only the Accept/Skip/Decline buttons).
- **03:212:** A request stores both projections at send time, and Requests and the schedule show those snapshots, never a live read of the partner's profile. *Falls if wrong:* Overturned by an ADR-0011 amendment allowing a live partner read for parties to a request.
- **03:214:** A slot whose run comes 24 hours or more after `slot_at` (executor down) is cancelled as `missed`, and a slot interrupted mid-post is marked `failed` and never re-posted. *Falls if wrong:* Overturned by an owner preference for late posting.
- **03:216:** Posting runs through a thin `s4s_post` automation that is queued at accept time and checks the flag, both opt-ins and the slot status at run time. *Falls if wrong:* Overturned if the owner wants held slots posted later once the flag is turned on.
- **03:220:** "Failed" is shown as an Inflowwww extra status beside Infloww's four. *Falls if wrong:* Overturned by evidence of how Infloww shows a failed S4S post.
- **03:222:** S4S rows are kept until their Creator is deleted, with no separate retention window. *Falls if wrong:* Overturned by an owner retention policy.
- **03:224:** The "S4S Setting" panel is a drawer opened from each S4S page header, not a fourth sidebar entry. *Falls if wrong:* Overturned by evidence of a menu entry.

*Phase 4*
- **04:291:** Unknown keys inside a blob are kept, not refused. *Falls if wrong:* Overturned if the owner wants strict blobs, which needs a one-off clean of stored blobs first.
- **04:293:** A save without `version` is stamped 1, and any other version is refused. *Falls if wrong:* Overturned if the owner wants the client to own the version.
- **04:295:** The new length and range bounds are agency_name 128, role name 64, description 256, 100 roles, prompt 2000 characters and auto clock-out 1 to 1440 minutes. *Falls if wrong:* Overturned by Infloww evidence of other limits.
- **04:297:** A stored field that fails validation is applied as its default and shown unchanged in its Panel until the next save. *Falls if wrong:* Overturned if the owner wants invalid stored blobs reported on load.
- **04:299:** The Role enforcement switch is a key (`enforce`) in the `roles` blob rather than a column or table. *Falls if wrong:* Overturned if the owner wants the switch outside the owner-editable blob.
- **04:305:** Enforcement is one middleware over a page-to-route-prefix map, and a route that serves several pages is allowed when any of them is granted. *Falls if wrong:* Overturned if per-handler checks are wanted for finer control.
- **04:307:** A chatter linked to several Agencies with no single Creator in scope is refused a page if any linked Agency with enforcement on denies it, and is offered translation only if every linked Agency allows it. *Falls if wrong:* Overturned by Phase 1 deciding a different rule for naming the Agency.
- **04:309:** Data scope narrows only employee-keyed report reads that a chatter can reach (per-employee stats; Phase 2 keeps the Timesheet and clocked-in now owner and Master only), not chats or fans, and "Self and subordinates" reads as "self" until Phase 5's groups land. *Falls if wrong:* Overturned by the owner's role matrix (inventory §6 item 6).
- **04:311:** "Converters" means the Relay's existing attribution (linked message sender, else the 7-day lookback), and "Message sender" means the linked sender only. *Falls if wrong:* Overturned by Infloww's Employee calculation rules (H262080).
- **04:315:** The revenue kinds map to the three rule groups as listed above, and the welcome kinds are `send_welcome`, `welcome` and `welcome_chatter_for_info`. *Falls if wrong:* Overturned by Infloww's calculation rules.
- **04:317:** "Exclude the 20% OnlyFans fee" uses `net_cents` where OnlyFans reported it, else 80% of gross. *Falls if wrong:* Overturned if the owner wants a flat 80% always.
- **04:323:** The week start has no consumer in the reports, so it is applied only to the Shift schedule, its "This week" filter (Inventory §3.8) and the "My shifts" week. *Falls if wrong:* Overturned by evidence of Infloww's weekly report views, which would bring the preset back as one story and one vitest case.
- **04:325:** Report day bounds use `report_tz`, and day buckets use that zone's offset at the window's end, so a daylight-saving change inside a window can move one hour of sales across a day edge. *Falls if wrong:* Overturned if exact per-day zone math is needed.
- **04:327:** The regular time zone (`preferences.tz`) changes only the top bar's (and Window header's) label. *Falls if wrong:* Overturned by evidence that Infloww converts other times.
- **04:329:** The page map's drift check reads hrefs out of `app/lib/nav.ts` from the Relay test suite. *Falls if wrong:* Overturned if a generated JSON export of the nav is preferred.

*Phase 5*
- **05:172:** Delete in the More menu is Not wired and the existing soft-disable stays the only removal. *Falls if wrong:* Overturned if the owner wants a hard delete, which needs its own retention decision.
- **05:174:** Batch actions are built even though the plan's item 1 does not list them, because the plan's Baseline row names "no … batch actions" as part of the gap and they are confirmed C[H262104]. *Falls if wrong:* Overturned if the owner cuts them.
- **05:178:** The shift history columns cover the current calendar month in the Agency's timezone (Phase 4 preferences). *Falls if wrong:* Overturned by evidence of Infloww's range.
- **05:180:** Clocked hours builds only "Total by employee" of Infloww's four views (H262078). *Falls if wrong:* Overturned when the Timesheet gains a pair or by-day grouping.
- **05:182:** The full platform notice is unknown (the Inventory quotes "Clocked hours are not differentiated by platform…"), so the shown text is that prefix ending in a full stop. *Falls if wrong:* Overturned by the full Infloww text.
- **05:184:** Reassign is owner or Master only, even under Role enforcement. *Falls if wrong:* Overturned by the owner granting it to a role.
- **05:186:** "Assigned by" is read from the latest `sales.reassign` audit row for the sale: the actor Employee's name, or "Owner" for an owner session. *Falls if wrong:* Overturned if the owner wants a dedicated column.
- **05:190:** "Self and subordinates" means the Employee plus every Employee in a strict descendant group of the Employee's own group. *Falls if wrong:* Overturned by the owner's definition.
- **05:192:** Organization Chart offers Add sub-group (confirmed) and Delete for empty groups (Rung 4: the undo of an add). *Falls if wrong:* Overturned by evidence of Infloww's other ⋮ items, which would add a move route with its cycle check.
- **05:194:** Organization Chart is a tab, not a left panel on Employees. *Falls if wrong:* Overturned by a capture of Infloww's Manage employees.
- **05:196:** `/notifications` is a page reached from a "See all" link in the top bar bell's panel. *Falls if wrong:* Overturned if the owner wants the bell to navigate straight to the page.
- **05:198:** The Notifications page reuses the bell's fetch (20 per type, 50 merged; `app/components/NotificationBell.tsx:83`, `:230`) and its error and empty states. *Falls if wrong:* Overturned if the feed ignores `offset`, in which case "Load more" is Not wired.
- **05:200:** The Notifications page's "Mark all read" and gear are Not wired, because the Relay has no mark-read endpoint (`service/server.py:5364-5430` holds only GETs). *Falls if wrong:* Overturned when a known body exists.
- **05:316:** The Relay test files are named per router (`test_employee_groups.py`, `test_sales_records.py`) rather than one Phase file. *Falls if wrong:* Overturned if the ticketing step merges them.
- **05:318:** Groups live in a new router file mounted on the existing Relay app rather than inside `service/employees.py`. *Falls if wrong:* Overturned if a reviewer prefers the employees module.
- **05:320:** The Acceptance block downgrades to the `down_revision` of item 3's view migration, read from the file `*_attr_view_sales_records.py`, instead of `downgrade -2`. *Falls if wrong:* Overturned if the ticket names the migrations differently, in which case the glob follows the ticket.

*Phase 6*
- **06:226:** The walk is a throwaway `/tmp` script that copies `scripts/settings-check/walk.py`'s mock routing, not a committed harness with a self-test. *Falls if wrong:* Overturned if the owner wants a committed route-walk harness, which this Phase would then add under `scripts/route-walk/` with the self-test back.
- **06:228:** The walk mocks the relay with Playwright routes instead of starting a temp-DB relay like ui-shots. *Falls if wrong:* Overturned if a route renders nothing gradable on empty mocks. In that case its populated state comes from the owning Phase's fixture, added to the walk's mock table.
- **06:230:** A plain page load that writes anything fails the walk. *Falls if wrong:* Overturned by a route whose load write is intended. It gets a named allowlist entry in the walk with its reason.
- **06:232:** The walk's matrix cross-check lives inside the walk, not in a vitest that parses a Markdown doc. *Falls if wrong:* Overturned if the owner wants the matrix checked without a dev server.
- **06:234:** Ownership of this plan's suite is settled once, in the same words in Phase 0 and Phase 6 (six-hats review): Phase 0 creates `.scratch/infloww-parity-next-steps/suite.sh` with two steps, `matrix` and `relay`. *Falls if wrong:* Overturned if the owner wants every Phase to append its own tests as it lands, in which case this Phase only adds typecheck, lint and vitest.
- **06:236:** The matrix grades use the glossary's seven Matrix status values ("intentionally different" kept for Leaderboard and Referrals), not only the four the plan's Phase 6 goal names. *Falls if wrong:* Overturned with the glossary's own ASSUMPTION.
- **06:238:** The sign-off is proven by `git diff --quiet <signed sha> HEAD` excluding the matrix, rather than by naming HEAD. *Falls if wrong:* Overturned if the coordinator commits the matrix in the signed commit itself.
- **06:240:** Whole-relay `scripts/run-tests.sh` stands in for the roadmap's "backend tests". *Falls if wrong:* Overturned if the owner scopes backend tests to the Effort suites only.
- **06:265:** Phase 6 keeps the `docs/routes.md` correction for rows the owning Phase left stale. *Falls if wrong:* Overturned if the owner wants every stale doc row ticketed to its owning Phase.

## Needs the human

**By spec**
- **Phase 0:** none from review. Its merge is the plan's first entry below.
- **Phase 1:** none.
- **Phase 2:** none.
- **Phase 3:** the plan's S4S policy entry (cross-agency fields, request lifecycle, disable behaviour) and S4S live posting (connectors ticket 06). The spec proceeds on ASSUMPTION until vetoed.
- **Phase 4:** the LLM spend of the translator prompt tier (codex D2, six-hats Black). It is now on the plan's list. The role enforcement default is the plan's entry.
- **Phase 5:** none from review. Its parked surfaces each carry one `Question:` line (trial link, promotion, Leaderboard, Referrals, platform selector, idle mode, help center, retention data).
- **Phase 6:** none.

**The plan's list** (`docs/plans/infloww-parity-next-steps.md` › Needs the human, as it now stands)
- Merge the branch, or keep it apart (Phase 0's first step, under ASSUMPTION).
- Messages Pro ordering if the merge is declined.
- S4S policy: cross-agency visible fields, the request/accept lifecycle, and the disable behaviour.
- S4S live posting, which stays off until the owner runs connectors ticket 06's live `POST /posts` check.
- The role enforcement rollout: per agency and off by default, or on by default?
- **New:** LLM spend for the AI Translator prompt. Approve it, or veto it so the prompt stays "Not applied yet".
- **New:** a second merge for `ff715056`, the live session's 21 files past the pinned tip. Without it, `main` stays behind the branch after Phase 0.
- Carried over from the original runs:
  - connectors 06, 12, 19, 31, 38 and 46;
  - Settings: Tab list icons, dark palette mapping, initials colours, and the public-export path scrub;
  - Messages Pro: the B11 page-bounded figures, if still open after the merge.
