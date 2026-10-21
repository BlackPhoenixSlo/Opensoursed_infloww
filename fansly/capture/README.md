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
../../venv/bin/python drive.py nav https://fansly.com/messages
../../venv/bin/python drive.py shot /tmp/p.png     # look at the page
../../venv/bin/python drive.py links               # every clickable + its routerLink
touch out/<run>/STOP                   # stop; prints a summary
```

`record.py` and `drive.py` run side by side — driving the page is itself
recorded.

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
