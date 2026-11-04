# slop/: OS notification push (Web Push) at volume

The relay's Web Push path (`service/push_send.py` with its pure halves `push_decide.py`, `push_scope.py`,
`push_notice.py`, routes in `push_api.py`; the app's bell OS checkbox + Test, `app/lib/webPush.ts`,
`app/public/sw-push.js`). The harness, its knobs and its rules are in `README.md`; this file is only what this
flow adds. The scenario's docstring is its spec (phases, load, KNOWN_RED, bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/push_wire.py` | `PushWire`: the push service (FCM / Mozilla / Apple stand-in) at its wire, a stdlib threaded HTTP server on loopback in the harness process (not a `/__slop` route: a relay posting to its own loop would hide loop stalls). `POST /push/<device>`: verifies VAPID (ES256 under k, k = the relay's `/push/key`, aud, mailto: sub, exp <= 24 h), decrypts the aes128gcm body with the device's real keys, records it, answers 201 / 403 (bad VAPID) / 404 (unknown) / what the device is armed with (`arm(dev, status=410)`, `status=429, once=True` with Retry-After 1, `latency_s=`). |
| `lib/push_relay.py` | Relay plugin, no route: `VAPID_KEY_FILE=$DEMO_SHOTS_TMP/vapid_private.pem` unless set, so the relay never writes its key into the repo's `service/secrets/`, and a restart keeps it. |
| `lib/push_faults.py` | The check names and four faults, each patching a `push_decide` / `push_scope` attribute `push_send` looks up at call time. |
| `actors/push_device.py` | `PushDevice`: a real sign-in (owner `POST /auth/login`, Employee `POST /chatter/login`, its own cookie), its own P-256 keys + auth secret, `PUT /push/subscription` with the bell's types / platforms; `wants(account_id, type_key)` is the oracle (scope from the seed). |
| `scenarios/2026-11-03-os-ping-push.py` | The scenario. Shared: `fan_dm.serial(make=)` (any SSE frame through the pump's shape), `manager.SseListener(last_id=)` (resume a dropped stream). |

## Scenarios

- `2026-11-03-os-ping-push`: `multi_agency_big_models` (5 Agencies, SCALES `os_ping_creators`); `max(--users, 15)`
  push devices: 2 owner sessions per Agency, the rest Employees with Creator subsets, type mixes from the bell.
  Phases: 1 steady (`os_ping_frames` per Creator, open loop `--rate=` frames/s per Creator: DMs, tips, purchases,
  likes, subs, an unnamed OF type), 2 re-offer (a purchase 3x, an old one again; 429-once devices), 3 SSE replay
  (Last-Event-ID), 4 relay restart (SIGTERM + start, old purchases re-offered), 5 prune (410 devices; `POST
  /auth/logout`; Log out other sessions), 6 UI (prod build, full headless Chromium: bell OS checkbox + Test, shot
  `push-test-trigger`; the relay's pushed plaintext into the real service worker by CDP `deliverPushMessage`,
  `getNotifications()` holds its tag, shot `push-settled`; side effect SQL row + `sse.push.sent`). Checks:
  `PUSH_ALL_ONCE`, `PUSH_SCOPE`, `PUSH_TYPES`, `PUSH_ORDER`, `PUSH_NO_REPUSH`, `PUSH_PRUNED_GONE`,
  `PUSH_PRUNED_DEAD`, `PUSH_DECRYPT`, `PUSH_VAPID`, `UI_TEST_BUTTON`, `UI_SW_SHOW`; budgets frame -> push p95 and
  `PUT /push/subscription` p95, both also vs the last green run. Faults: `push-leaks-scope` (default; targets
  `PUSH_SCOPE`), `push-forgets-sent` (`PUSH_NO_REPUSH`), `push-keeps-gone` (`PUSH_PRUNED_GONE`),
  `push-ignores-types` (`PUSH_TYPES`). Knobs: `--creators=`, `--frames=`, `--rate=`. `push-records.jsonl` in the
  run folder: every request push_wire got (status, VAPID verdict, plaintext).
