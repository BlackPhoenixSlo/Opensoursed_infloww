# Full AI Chat's Shadow mode sends nothing by construction and writes only the Decision ledger

**Status: proposed** (2026-11-13, `plans/full-ai-chat.md` constraint and Phase 01; nothing built yet).

Phase 01 runs the Router on real AE traffic before any Fan may see Full AI Chat. We decided that Shadow mode is inert by construction rather than by a mode check before a send. The shadow runner has no send path: it imports no `of_client`, `_outbound` or `ax._make_client`, takes no fan lease, sets no cooldown, skip_list entry, stamp or ownership, makes no OF call, and writes only `ai_decisions` (Shadow enrols no one, R8). From Phase 04, `sender_for(mode)` has no shadow sender, so a shadow Turn ends at its Decision row. Tests pin it: an AST import scan, a run with the client and send patched to raise that still yields a row, and a mutation that injects a `_make_client` call and must fail them. The WATCH check `full_ai_shadow` (any `messages.automation_kind = 'full_ai_chat'`, any `fan_lease` row of the kind, or an OF call counted under `auto:full_ai_chat`; Phase 01's rows have no send or offer column to read) is only the second line. We chose this because a mode flag read before a send is one inverted condition away from a real PPV to a real Fan on AE, and a lease or cooldown would change how the old Lanes treat the same Fan, so the shadow reading would no longer describe today's traffic. The cost: the shadow runner and the live sender are separate paths, and Shadow mode cannot observe outcomes (a shadow tease never converts), so outcome checks wait for the live Rollout stages.

## Considered Options

- **One runner with `if mode == "shadow": return` before the send.** Rejected: the guarantee would rest on one condition, and no test can show the runner is unable to send.
- **Proving shadow from sent-message attribution alone.** Rejected as the main proof: `service/attribution.py` writes the `automation_kind` row best-effort, so a real send can leave none.
