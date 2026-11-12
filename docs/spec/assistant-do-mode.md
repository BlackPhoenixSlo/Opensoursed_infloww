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
- Turns any rule on — not a new one, not an existing one (`mass_edit` can only switch rules off).
- Deletes a rule, presses Run-now, or edits an existing rule's captions, folder or audience.
- Edits an existing rule outside `mass_edit` (D11): only Auto mass rules, only unsend, how often, online only,
  skip-recent-chats, price, photo count and switch-off; only after the user presses Do it on a plan card that
  lists every rule and its before → after (rules that would send more marked LIVE); each rule re-checked
  server-side (version, owner, opt-in) and skipped if it changed since the card.
- Touches another account than the focused one, except `mass_edit` with scope "all" ("every model"): the
  session's own accounts, each through the same Auto Mass opt-in gate; price / photo count stay one model only.
- Loosens a default silently: `onlineOnly`, `excludeLastChatHours`, excludes change only when the request says so,
  and the card lists every change.
- Runs paid vision flagging; claims a folder is "safe" (wording is "likely SFW").
- Acts beyond the asker's permissions (same session, same endpoints). Do-mode hidden where the asker can't save.

## Decision log

| # | Decision | Why (ladder rung) | Invalidated if |
|---|---|---|---|
| D1 | Approach C (recipes over existing reducers), not vision (A) / generic DOM loop (B) / silent API create (D) | reducer action unions already exist + repo rule mandates them (3); A/B costly, brittle, can hit live switches (4) | owner wants any-page autonomy now |
| D2 | Agent saves the rule, Enabled **off**, Dry run off | owner: "gets set up just off, user clicks turn on" (2). Fable wanted no save + dry-run on; overruled by owner text — disabled rule sends nothing | owner wants review before save |
| D3 | No Opus/Sonnet at runtime; one DeepSeek JSON call; delivery is deterministic code | slot-fill has nothing to plan (5); per-purpose pin can still pick Opus; confirmed by eval (D9) | draft accuracy <90% on eval set |
| D4 | Jev not used in pilot; swap offer from answerLinks routes | zero-call signal exists (5) | chip misfires often / no link in answers |
| D5 | Folder by tier counts, warn on drift; keep `folderId` (not pinned media ids) | owner said "folder" (2); pinning = later option (4) | owner wants frozen media |
| D6 | Pilot = `mass_premade` only, create-only | smallest thing (5) | — |

Fable (2026-11-11, first consult): C yes; A/B no; D as skip-animation path; DeepSeek draft, Jev as gate/veto,
plan card is the real review surface, cap cursor effort; risks: hourly mass-to-all spam/churn, folder drift,
redundant exclude, phone sheet, audit, duplicates, chatters, eval set. Opus response: adopted all except D2
(owner text) and D4 (answerLinks gate is free).

| D7 | "Saved OFF" is structural: the agent's save forces `is_enabled:false` in the body, whatever steps ran; no server token | reviewer P1 (1 s timer → stale enabled:true) + Fable round 2; server token only guards our own client (5) | — |
| D8 | ~~Agency key only, no platform fallback~~ — REVERSED by owner 2026-11-11: agency's own key, else the company DeepSeek key (`HELP_ASSISTANT_DEEPSEEK_KEY`, Q&A's fallback row), sharing Q&A's per-account daily cost cap; a Claude (Sonnet/Opus) pin bills the agency's own Anthropic key; `do-caps` reports `no_key` only when neither resolves | owner: do-mode is cheap (2) | owner wants a separate do-mode budget |

| D9 | Runtime = DeepSeek v4-flash only; one same-model retry on `bad_draft`; no Opus/Sonnet escalation on `flow:null`; deterministic `Check:` cross-checks (request says "online" but audience isn't online-only / adds Following; a request number used nowhere) added to assumptions | eval 2026-11-11 (below): flash 98.2% exact, 0 safety; Opus on its misses fixes them, but no runtime "failed" signal except null, and null is right for most null traffic + both v1 safety slips were false creates (Fable round 3); Sonnet ≈ flash at ~9× cost | real traffic exact <95%, or a false-create safety slip |

Fable round 3 (eval data): (a)+(d)-lite; retry only bad_draft; no Sonnet. Adopted.

| D10 | "Set up a mass …" with no timing = Auto mass (every null → 1 h, said in assumptions); flow null only when the request says one-time / now / a set time. Deterministic veto turns a mass draft back to null when another feature is named with no mass word, or an existing rule is edited (`vetoed()`, never on refine). A null on a mass request answers with what would work; Q&A turns sent from do-mode never offer "Do it for me" back | owner phone test 2026-11-12: "Settuo a mass post with nice captions and sfw photos" → refused, then Q&A ↔ do-mode ping-pong (1). Broad prompt rule (v4) cost 7 false creates + 97.3%; narrow rule + 1 few-shot (v5) 98.2% / 7 false creates; veto replay → ~98.8%, 1 false create, 0 correct drafts vetoed in 4 stored runs (5) | veto blocks a real Auto mass request |

| D11 | `mass_edit`: bulk edits of EXISTING Auto mass rules, on this model or every model (scope this \| all). Changes unsend, every, online_only, exclude_last_chat_hours, price + media_count (scope this only) and can switch rules off; never switches one on. Plan card (rules per model, before → after, LIVE marks) → Do it → `POST /admin/assistant/edit/apply {account_id, rules:[{id, version}], changes}`: per rule the server reloads it, checks owner + opt-in + version (sha1 of steps\|trigger\|enabled, "changed since you saw it" when stale), re-applies the clamped change to the fresh row and answers per rule (partial success OK; old steps hash logged). Overrides the old "never edits an existing rule / never touches another account" safety rules | owner 2026-11-12: "please turn off auto mass unsend for every model" (2) | owner wants edits reviewed in the form, or a bulk edit hits a rule the card didn't show |

| D12 | Siri-style broad box, in the normal Q&A (not do-mode). (a) **Data markers**: the Q&A prompt may emit at most 2 closed-enum markers `[[data:<metric>\|<window>\|<scope>]]` (metric revenue → `/admin/stats/revenue?group_by=kind` · per_model → `/admin/stats/per-model` · top_spenders → `/admin/stats/fan-report?sort=total` · top_tippers → `/admin/top-tippers` · unread → OF `/users/me` `chatMessagesCount`, window `now` only; online_fans dropped: no endpoint; window today · yesterday · 7d · 30d · this_month · last_month · now; scope this \| all) and `[[chat:@handle]]`; the client renders each as a live card fetching the existing endpoint with the asker's own session (role gates kept; 403 → "not available for your role", never $0); the model never writes figures, the client drops digits/currency in the marker's sentence; invalid marker → dropped silently; card values never enter history (a follow-up re-emits a marker). (b) **Deterministic pre-pass** before any LLM call, both modes: imperative verb + nav label → navigate (only `visibleLinks` for this role), theme light/dark/toggle, "open/chat with @handle" → chat; no verb = falls through to Q&A. (c) Honest refusals for send-now / delete / switch-on → name the page. Never switches an automation on. Do-mode prompt untouched | owner 2026-11-12: "generate all possible stuff users can ask … think of what iPhone Siri can do" (2); Fable: marker-in-Q&A beats lookup-in-do-mode (no extra call, lands where people type, tuned do prompt untouched) (5) | model writes numbers anyway (eval "no digits" > 1%), false markers on how-to questions > 2%, or pre-pass hijacks a question |
| D13 | `auto_story`: from one sentence, a NEW Auto Story rule. Same one JSON call (flow `auto_story`, keys `folder` · `every` · `times` "HH:MM" · `per_run` · `hours_to_live` · `max_runs`); `resolve_story` clamps (every whole hours 1–168, per run 1–10, delete after 0–168 h, default 6 h, runs 1–1000 or forever), folder only with photos (none said / none found / no photos → unresolved, the form's own "Pick a vault folder" gap blocks Save), no time and no interval → daily 09:00 (said). Veto: needs a story word, no mass word, never an edit of "my story", never a refine. Gate: the `auto_stories` opt-in (else "Your role can't…"), and one rule per account — a rule there → flow null "Auto Story is already set up for <model> — open it to edit: My Automations → Auto Story." Client: AutoStoriesTab's form is a reducer (`autoStoriesForm.ts`); the page registers on the same agent bridge as editor kind `auto_stories` (ready only after the rules read, `isNew` = no rule, dirty = form ≠ loaded), the runner opens `/growth/auto-story?creator=`, refuses when not new, plays steps in form order (a slot at the blank form's value makes no step), then Enabled OFF and Save; the page's agent save creates with `is_enabled:false` (D7) and refuses when a rule exists | owner 2026-11-12 task (2) | a story request lands on a mass draft, or the agent saves over an existing story rule |

Fable round 4 (D12): biggest risk = figures in text / contradicting the card → client strip + hard eval metric; follow-up
cases; small Opus sample; 403 ≠ $0; ≤2% false markers on how-to. PR 2 (later): `rule_off` for every automation kind in
do-mode via each kind's own disable path (config PUT for autoreply/nudge, `/automation-rules/switch` singletons, PATCH else).

Fable round 2 (after build): continue; gates = slop green + CAUGHT, structural OFF guard, live eval ≥90% exact-slot
(online_only, include resolution, keep_skip_recent hardest). Opus response: D7 adopted; eval is owner-run (paid).

## Acceptance

- vitest: slots→actions table, plan-card text, runner abort; pytest: draft validation, folder ranking, list
  resolution, flow:null, 200-always on LLM failure.
- slop scenario `assistant-do-auto-mass` (fake DeepSeek at its wire): seeded lists + vault items with tiers,
  drive the bot in the browser, Do it → DB row `automation_rules` kind mass_premade, `is_enabled=0`,
  interval 3600, `online_only=false`, folder = the seeded SFW folder, 10 texts; screenshots of trigger, cursor
  mid-run, settled end; FAULT: runner skips the Enabled-off step → `rule_saved_disabled` red.
- Live eval (2026-11-11, real APIs, 1000 cases from `scripts/assistant_draft_eval/`, measured):
  deepseek-v4-flash v1 prompt 84.3% exact → v3 prompt 98.2%, 0 safety violations, routing 996/1000,
  $0.38 per 1000 drafts, p50 1.6 s / p95 3.0 s. Prompt fixes: recurring-only flow rule (one-off/post/story/
  bulk → null), days/weeks → hours, fractional unsend, any language, >20 captions → 20, refine keeps
  captions (PREVIOUS DRAFT trimmed to few-shot keys + caption_count). Opus 5.5 on flash's 18 misses: 15/18,
  the other 3 were label bugs (fixed in gen_cases).

  | model (same final prompt) | exact | false create | false null | $ / 1000 drafts | p50 / p95 |
  |---|---:|---:|---:|---:|---:|
  | deepseek-v4-flash | 98.2% | 0 | 4 | $0.38 | 1.6 / 3.0 s |
  | claude-sonnet-5-5 | 98.6% (4 misses = the fixed label bug) | 5 | 0 | $4.23 | 2.5 / 6.6 s |
  | claude-opus-5-5, on the misses only | flash 15/18 · Sonnet 13/14 | — | — | ~$14 | — |

  `Check:` cross-checks, replayed over the stored raw replies (no extra spend): current prompt 0 caught /
  0 false on 646 good drafts; v1 prompt 9 of 132 errors caught, 1 false flag. A regression guard, not a fixer.
  Spend: DeepSeek $1.65 of $3, Anthropic $4.62 of $29 (ledger `results/ledger.json`).
  2026-11-12 (D10): +8 no-timing / one-off hand cases (h29–h36), flash v5 prompt 982/1000 exact, 0 safety, 4 false
  null, 7 false create (6 removed by the veto on replay); all 6 no-timing cases pass. Spend now DeepSeek $2.45 of $3.
  2026-11-12 (D11): +60 edit (e01–e60) + 15 create-knob (x01–x15) hand cases, 1075 total. Flash on 411 (all 111
  hand + 300 random generated): v6 prompt 96.1%; fixes: scope "all" only when the request names models
  (`_ALL_MODELS`, else "this" + said), "fans" as recipients = include fans, `parse_json_object` closes a dropped
  outer "}" (4 of 193 long DeepSeek replies parsed a nested object → silent flow null). Replay of the stored replies
  through the final code: 405/411 = 98.5%, 0 safety, edit routing 50/51, owner's phrase (e06) passes. Spend DeepSeek
  $2.75 of $3.
  2026-11-12 (D13): the 15 `oth-auto_story-*` rows (were flow null) now expect `auto_story` (ids kept) + 16 hand rows
  (s01–s10 positives incl. es/sl, s11–s16 story-vs-mass / can't-do confusers), 1091 total. Live eval not run yet
  (owner-run).

## Later (not pilot)

More flows (welcome, auto-follow, autopost…) = one registry entry each; "dry-run preview now"; duplicate-rule
detection → offer edit; audit column for assistant-made rules; frozen-media option; Jev "draft matches request" veto.
