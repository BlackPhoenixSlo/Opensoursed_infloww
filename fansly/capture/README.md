# Fansly CDP capture rig

Records what a `.har` structurally cannot: **WebSocket frames**. The HAR spec
carries the WS handshake and stops there, and DevTools' "Save all as HAR" drops
the frames silently — so `PARITY_SPEC §5` (Fansly's realtime channel) was never
capturable as a HAR no matter how carefully anyone clicked.

## Use

```bash
./start_chrome.sh                      # real Chrome, throwaway profile, CDP on :9222
                                       # log into fansly.com in THAT window (once — profile persists)
../../venv/bin/python -u record.py --name <run> --verbose &
PORT=<rig port> ../../venv/bin/python drive.py nav https://fansly.com/messages
PORT=<rig port> ../../venv/bin/python drive.py shot /tmp/p.png     # look at the page
PORT=<rig port> ../../venv/bin/python drive.py links               # every clickable + its routerLink
touch out/<run>/STOP                   # stop; prints a summary
```

`drive.py` has no default port and refuses `PORT=9222` (the unrelated Chrome), so it
drives a rig Chrome on its own port (the creator rig is :9223 in RECIPES).

`record.py` and `drive.py` run side by side — driving the page is itself
recorded.

## Mirror capture

A read-only copy of every page and State in `mirror_plan.json`, taken from the owner's
signed-in creator Chrome with the Capture gate (`gate.py`, ADR-0065) armed throughout.
The live run is the coordinator's alone, never an implementer's. Creator Chrome CDP
:9231 only — never :9222 or :9232. Every process at `nice -n 10`.

**Never (re)launch the creator Chrome with `start_chrome.sh` during a capture; it opens
Fansly ungated.** If that Chrome dies mid-capture, stop, relaunch it with no Fansly tab,
and start again from `blank`.

Every blank (`blank`, halt, watchdog trip, `stop`) stops service workers, crashes every iframe and
each web tab's renderer, then loads about:blank. A brief "Aw, Snap!" is expected. Crashing is what keeps
pagehide beacons and keepalive fetches from leaving. A crash that is still unconfirmed after one
retry, or a web tab still open after the last pass, is logged as `blank_unconfirmed`: the audit fails,
and `blank` / `stop` exit 3. On a halt, the gate waits for the blank to finish before it exits.

Live run order (`R=~/Downloads/fansly-live-capture`, outside the repo):

1. `gate.py blank --port 9231` — no Fansly page is live before the gate arms.
2. `gate.py selftest --port 9231 --root $R` — five cases on localhost; refuses while a Fansly tab is open.
3. `gate.py run --port 9231 --root $R --fan-account-id <id> &` and `gate.py watch --port 9231 --root $R &`;
   `run` refuses while any Fansly target is open (re-run step 1); wait for `ports/9231.json` `armed: true`.
4. Check the shown theme is light; if not, under the armed gate `nav /settings/display` and
   `tclick '[class*=setting] [class*=btn]'` (client-side, zero writes; `save` refuses non-light). Flip it
   back the same way before `stop`.
5. Tracer: `PORT=9231 drive.py nav /messages` (baseline unread observation), then for each `tracer` plan
   entry `nav` / `tclick` / `wait` / `save`, then `nav /messages` again → `gate.py stop --port 9231` →
   `gate.py audit --root $R --session <id>` must pass.
6. Spot-check the tracer metas (`canvases`, `shadow_roots`, `iframes`) and screenshots against the saved
   html, and the page named by any unverified-fake warning; write "Tracer facts" into RECIPES (names
   only). Phase 3 and 4 code starts only after this.
7. Later: the remaining plan entries, in as many gate sessions as needed, same pattern, each audited. A
   failed entry is re-run alone under a new session; a re-save replaces the earlier one.
8. `gate.py manifest --root $R` → `"complete": true` and `audit.passed: true` before the real generator run.
9. One CAPTURE_LOG entry per session: counts, audit verdict, new On-open writes; no identity values.

Drive verbs under the gate (`PORT=9231 drive.py <verb> --root $R`): on :9231 every verb needs a fresh armed
gate, and while any gate session is open only `nav`, `list`, `shot`, `links`, `text`, `probe` (each match: visible, tag, class, text) and the mirror verbs
run (`eval`, `click`, `focus`, `type`, `insert` are refused). The mirror verbs: `tclick <sel>`
(trusted click, opens CDK menus), `key <Escape|Tab|Arrow*>`, `wait [--gone] <sel> [--timeout s]`,
`save <id> --state <page|name> --opener <sel> --settled <sel> [--reset-key K | --reset-click <sel>] [--reset-gone <sel>]`
(a State needs one reset (Fansly dropdowns ignore Escape, so use `--reset-click` on the opener) plus `--reset-gone`; files are kept only once the State closed), `assets` (CSS, fonts, SVG
from the resource tree into `static/`, never `cdn3`/`mediav2`), `skip <id> --reason <text> --tried <sel>...`
(optional entries only). Every verb acts on the capture tab the gate recorded; `nav` goes to
`https://fansly.com` only, and any `/messages/<id>` path is refused unless the gate's latest
`/messaging/groups` observation shows that thread at zero unread.

`gate.py plan --check` validates `mirror_plan.json` (unique ids, a State's parent is a page, at most 5
tracer pages and a tracer State, every ticket 01 route and State except the deferred nested States).

Capture folder: `selftest.json`, `ports/<port>.json`, `sessions/<id>/` (gate log, heartbeats, markers,
unread, identities, audit), `pages/<id>.{html,meta.json,png}`, `static/`, `assets.json`,
`skipped.json`, `manifest.json`.

**Refresh after a Fansly release:** no automation. Re-run the capture into a fresh root, tracer first
(the bundle hash changes), then the remaining entries and `gate.py manifest`, then the generator, by hand.

## Output (`out/<run>/`, gitignored — contains a live session token)

| file | what |
|---|---|
| `ws.jsonl` | every WS frame both directions + handshake headers |
| `http.jsonl` | request/response pairs with bodies for the API hosts |
| `events.jsonl` | raw CDP target events, as a backstop |
| `summary.txt` | sockets, frame counts, endpoints touched |

## Two design choices that are load-bearing

**Browser-level `Target.setAutoAttach(flatten=True)`, not a per-page session.**
It catches pages, iframes, workers AND service workers, and re-arms on every new
target. Fansly runs `ngsw-worker.js` (Angular's service worker) — a per-page CDP
session, which is what `playwright.new_cdp_session` hands you, cannot see it.
`waitForDebuggerOnStart` is on so a worker cannot run a line before Network is
enabled; that is the difference between catching a socket's opening frames and
joining it midway.

**One reader task owns `ws.recv()`.** `await cdp.send(...)` parks on a future
that only the reader can resolve. The first version awaited its own reply with
nothing draining the socket and deadlocked on the very first command.

## Fansly realtime protocol (captured 2026-09-01)

```
wss://wsv3.fansly.com/?v=3        Origin: https://fansly.com, no auth headers
OUT  {"t":1,"d":"{\"token\":\"<session token>\",\"v\":3}"}    ← d is DOUBLE-encoded JSON
IN   {"t":1,"d":"{\"session\":{...,\"websocketSessionId\":\"...\"}}"}
OUT  p                                                        ← keepalive, a bare literal
IN   {"t":2,"d":"{\"lastPing\":<ms>}"}
```

Auth is **in-band** and uses the same `token` the login extension already writes
to `fansly_session.json` — no new credential is needed to open this socket.
`t` is the message type; 1 = auth, 2 = ping/pong. Event type codes for inbound
message / typing / notification are NOT yet captured (they need a real event to
fire while recording).
