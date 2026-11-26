# The Front door is Caddy routing by explicit account; the app merges Cells itself over HTTP/2

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Phases 0–1, Fable round-2 amendment 3; tickets 06, 08; nothing built yet).

Chatters must log in once and see one All inbox with live updates across Cells. We decided there is no gateway service: Caddy, already on every Box (`deploy/fleet/fleet.py:273-303`), renders a block per Cell from local Placement and routes the Control cell's allowlist to it, every other request by the account in `X-Account-Id`, `?account_id=`, `?account=` or the path, and anything else to 400 `account_required`. Ids stay bare on the wire (a namespaced id is the implicit tuple platform, account, local id; ids above 2^53 stay strings), and `X-Cell-Gen` on writes catches a stale tab after a lossy restore. The app, which already fans the All inbox out per account (`useChatList.ts:325-354`, m), fans out per Cell, merges with a fixed order, and opens one EventSource per Cell it touches plus the Control cell, each with its own cursor; a dead Cell greys only its Creators. Live updates need HTTP/2: 19 streams over HTTP/1.1 hit the ~6-connections-per-host browser limit (i), so HTTP/1.1 shows a clear "unsupported" banner. We chose this because it adds no service and reuses what Caddy and the app already do. The cost: Caddy cannot read a JSON body, so ~75 app calls must gain an account header (`relay.ts` refuses an unclassified call without one), merge and cursor logic lives in the browser, and Phase 0's 19-stream spike is a veto: if it fails, this is re-planned before Phase 1.

Amended 2026-11-26: the veto is now ticket 22 resized to 125 stub streams + 125 fetches in one real browser through local Caddy (re-plan R5; ~125 Cells at 1,000 models, i). Pass keeps no-gateway; fail brings in gateway fan-in (the rejected option below becomes the fallback, Phase 7).

ASSUMPTION: chatters' browsers get HTTP/2 through Caddy; overturned by a browser or proxy forcing HTTP/1.1 (then a SharedWorker or gateway fan-in).
ASSUMPTION: `X-Cell-Gen` is enough, with no per-row generation columns; overturned by a write path that skips the Front door.

## Considered Options

- **A gateway service that merges Cells.** Rejected unless the stream spike fails: a new service to run and keep up.
- **Prefixed, namespaced id strings.** Rejected: a wire change everywhere for routing the account already gives.
- **One shared stream through a SharedWorker.** Kept as the fallback if HTTP/2 fails.
