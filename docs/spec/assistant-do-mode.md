# Help bot "Do it for me" mode (pilot: Auto mass)

Owner ask 2026-11-11: the help bot opens the right page/window and fills the form for you, with a visible
mouse clicking and typing. Q&A bot stays read-only and offers the swap. Pilot goal phrase:
"auto mass to fans every hour, delete after, everyone except mass-exclude, SFW folder, 10 captions, leave it off".

## Shape (approach C — per-flow recipes over the form's own reducer)

1. **Draft** `POST /admin/assistant/draft {request, account_id, thread_id?}` → 200-always
   `{id, flow, summary, slots, assumptions[], unresolved[], answer, error}`. One JSON-mode LLM call
   (purpose `help_assistant_do`, DeepSeek default, small byte-stable system prefix = flow schema + examples,
   NOT the 28k manual). The LLM fills intents only; the SERVER resolves ids:
   - folder: `{want:"sfw"|"named", name?}` → server ranks the account's vault folders from existing
     `_ai.explicitness_tier` rows (photos>0, explicit+hardcore=0, highest flagged share; unflagged = unknown).
     Never triggers paid flagging.
   - lists: names → ids from the account's lists; unknown names → `unresolved`.
   - captions: user-given verbatim, AI fills to `count` (≤20), SFW teaser tone, `captions_ai` count reported.
   - unknown flow → `flow:null` + a sentence pointing to Q&A.
2. **Plan card** in the bot: plain-words slots, folder tier counts ("41/60 flagged · 0 explicit · 19 unknown —
   likely SFW"), assumptions, unresolved, and the fixed facts (MASSdmEXCLUDE is always excluded; folder photos
   join at send time, so later uploads ride along). Buttons: Do it · Skip animation · Cancel. A chat reply
   re-drafts with the previous draft as context.
3. **Runner** (in AssistantProvider, survives route changes): flow registry `flowId → {route, open, toActions,
   targets}`. Navigates (`?creator=`), opens the editor through an **agent bridge** (the editor registers its
   `dispatch`/`save`; the panel registers `openNew`), then dispatches the editor's existing
   `RuleEditorAction`s one at a time while a cosmetic cursor glides to each field's element id. Saves through the
   editor's own Save handler (same `canSave`/`sendGap`, same request). Stop button, Esc, or any user pointer
   input on the page aborts. Phone: sheet collapses to a pill ("Doing it… Stop").
4. **Swap offer**: a Q&A answer whose links (answerLinks.ts) hit a registered flow route shows a
   "Do it for me" chip that starts do-mode with the original question. Home screen gets a second card
   "Do it for me — Opens the page and fills it in". Zero extra LLM calls.

## Safety rules (agent never, on its own)

- Leaves a rule live: it always saves with **Enabled off**; the user's toggle is the go-live.
- Edits/deletes an existing rule, presses Run-now, or touches another account than the focused one.
- Loosens a default silently: `onlineOnly`, `excludeLastChatHours`, excludes change only when the request says so,
  and the card lists every change.
- Runs paid vision flagging; claims a folder is "safe" (wording is "likely SFW").
- Acts beyond the asker's permissions (same session, same endpoints). Do-mode hidden where the asker can't save.

## Decision log

| # | Decision | Why (ladder rung) | Invalidated if |
|---|---|---|---|
| D1 | Approach C (recipes over existing reducers), not vision (A) / generic DOM loop (B) / silent API create (D) | reducer action unions already exist + repo rule mandates them (3); A/B costly, brittle, can hit live switches (4) | owner wants any-page autonomy now |
| D2 | Agent saves the rule, Enabled **off**, Dry run off | owner: "gets set up just off, user clicks turn on" (2). Fable wanted no save + dry-run on; overruled by owner text — disabled rule sends nothing | owner wants review before save |
| D3 | No Opus/Sonnet at runtime; one DeepSeek JSON call; delivery is deterministic code | slot-fill has nothing to plan (5); per-purpose pin can still pick Opus | draft accuracy <90% on eval set |
| D4 | Jev not used in pilot; swap offer from answerLinks routes | zero-call signal exists (5) | chip misfires often / no link in answers |
| D5 | Folder by tier counts, warn on drift; keep `folderId` (not pinned media ids) | owner said "folder" (2); pinning = later option (4) | owner wants frozen media |
| D6 | Pilot = `mass_premade` only, create-only | smallest thing (5) | — |

Fable (2026-11-11, first consult): C yes; A/B no; D as skip-animation path; DeepSeek draft, Jev as gate/veto,
plan card is the real review surface, cap cursor effort; risks: hourly mass-to-all spam/churn, folder drift,
redundant exclude, phone sheet, audit, duplicates, chatters, eval set. Opus response: adopted all except D2
(owner text) and D4 (answerLinks gate is free).

| D7 | "Saved OFF" is structural: the agent's save forces `is_enabled:false` in the body, whatever steps ran; no server token | reviewer P1 (1 s timer → stale enabled:true) + Fable round 2; server token only guards our own client (5) | — |
| D8 | Do-mode bills the agency's own DeepSeek key, no platform fallback; `do-caps` reports `no_key` up front | money decision left to owner (4) | owner wants platform-paid drafts |

Fable round 2 (after build): continue; gates = slop green + CAUGHT, structural OFF guard, live eval ≥90% exact-slot
(online_only, include resolution, keep_skip_recent hardest). Opus response: D7 adopted; eval is owner-run (paid).

## Acceptance

- vitest: slots→actions table, plan-card text, runner abort; pytest: draft validation, folder ranking, list
  resolution, flow:null, 200-always on LLM failure.
- slop scenario `assistant-do-auto-mass` (fake DeepSeek at its wire): seeded lists + vault items with tiers,
  drive the bot in the browser, Do it → DB row `automation_rules` kind mass_premade, `is_enabled=0`,
  interval 3600, `online_only=false`, folder = the seeded SFW folder, 10 texts; screenshots of trigger, cursor
  mid-run, settled end; FAULT: runner skips the Enabled-off step → `rule_saved_disabled` red.
- Not measured: live DeepSeek draft accuracy (paid; owner-run eval script `scripts/assistant_draft_eval.py`).

## Later (not pilot)

More flows (welcome, auto-follow, autopost…) = one registry entry each; "dry-run preview now"; duplicate-rule
detection → offer edit; audit column for assistant-made rules; frozen-media option; Jev "draft matches request" veto.
