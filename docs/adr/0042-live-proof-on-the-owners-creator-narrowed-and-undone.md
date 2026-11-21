# Live proof runs on the owner's own Creator, every write Narrowed and undone

**Status: proposed** (2026-11-20, `docs/plans/ofm-not-yet.md` Phase 0; nothing built yet).

A Not-yet control is wired to OnlyFans's undocumented API, and a mocked Mirror check proves only that the binder sends something, not that OnlyFans accepts the body or does what the control says: connector tickets 06 and 19 sat parked for want of a live check (`docs/infloww-parity-matrix.md` §3.2). There is no throwaway Creator; the owner named his own, the Proof Creator (80000112), which has 59 real subscribing Fans. We decided every Not-yet control and every Unproven control except the Critical controls (ADR-0043) gets a Live proof on the Proof Creator, under fixed limits that Phase 0's harness enforces for every later Phase: each write is a Narrowed write (an OF list, the Proof fan, or a Scheduled post deleted before it fires; a post to all Fans only if deleted at once; never a mass message); a real stream starts only after the owner's go, since it notifies subscribers, and "Available to" is narrowed to a list where OnlyFans allows; Lockout controls run last or with a harmless value, then are reverted; an OAuth hand-off makes no live link; and every live write is undone and recorded with its reversal in the PR's Undo log, so the account ends each run as it began. We chose this because the owner's goal is that each control is proven live on that account, and only OnlyFans's own answer shows a captured body works. The cost: a post, list change or notification can reach a Fan in the moments before its undo, which no undo takes back, and an undo that fails leaves a change on a real account that the Undo log names for the owner.
ASSUMPTION: Unproven controls fall under the same limits as Not-yet controls (rung 4); overturned if the owner exempts Phase 6's re-checks from the Undo log.

## Considered Options

- **Mocked proof for every control.** Rejected: the owner asked for each control proven live, and a mock cannot show that OnlyFans accepts a body.
- **A separate throwaway Creator.** Not taken: none exists, opening an account is out of bounds for a run, and the plan names 91610731.
