# Combined Messages Pro lists every Platform's Creators, reads Platform per Creator, and never mixes Platforms in a send

**Status: proposed** (2026-11-24, `.scratch/multi-platform-p1/plan.md` Phase 1d; ticket 05; nothing built yet).

Every app surface follows the sidebar's Platform switch, so a chatter working OnlyFans and Fansly Creators must flip it to reach the other inbox, and `/inbox` already redirects to `/messages-pro`, so there is no second inbox to put them in. We decided Messages Pro (Pop-out window, phone, Deep link) lists every Platform's Creators together, through `AllPlatformsContext` provided in AppShell's window branch, while every other surface keeps following the Platform switch. Inside it a Creator's Platform comes from the Creator (`useAccountPlatform`, and the chatter roster gains `platform`), never from the switch; `<PlatformSync/>` leaves the window branch and never writes the shared `chatterly:scope` key on a mismatch; Fan ids stay exact strings end to end, a precondition since a mixed list makes the `Number` rounding reachable from OnlyFans mode; the mass composer's All-models pick and multi-Creator chips keep to the picked Creator's Platform, and switching Platform clears rich text to plain. A Platform badge marks non-OnlyFans Creators on Creator tabs, pickers and the composer. We chose this because the owner wants one working window, and reading Platform per Creator is the only rule that is right when the switch and the open Thread disagree. The cost: two Platform answers coexist in the app (switch and Creator), every per-Platform read inside Messages Pro must use the Creator's, and a Fansly broadcast stays hidden until its Capability works.

ASSUMPTION: the Platform badge stays off Fan rows and the Thread header (rung 5); overturned if the owner wants them badged.
ASSUMPTION: Fansly rows keep waiting on the OnlyFans inbox bundle on cold load (`screenBundle.ts:124-129`, rung 5); changed only if measured slow.

## Considered Options

- **Messages Pro follows the Platform switch like every other surface.** Rejected: the owner wants every Creator in the window.
- **`<PlatformSync/>` sets scope to all on load.** Rejected: `ScopeContext.tsx:99-105` persists it and would wipe the window's saved Creator.
- **Mixed-Platform mass sends.** Rejected: Fansly's broadcast is skipped by the Shim and reported as sent.
