# Inflowwww Desktop

A thin, secure Electron shell that ships the Inflowwww Next app (`../app`) as a
downloadable **Mac + Windows** app. It **remote-loads** the running app
(see "Server URL" below) — it imports nothing from `../app` or
`../service` and ships no product code. Delete this folder and the web app is
untouched.

Implements the old `plan/DESKTOP_APP_PLAN.md` (git tag `legacy-ui-final`), Phase 1
(the shell) **and** Phase 2 (native OnlyFans login capture — the extension
replacement). See "Add an OnlyFans account" below.

## What you get

- A real dock/taskbar app window onto the live UI — no browser tab to lose.
- **No tab-suspension**: the realtime SSE stream and roster badges stay live in
  the background (browsers throttle/suspend hidden tabs; a window doesn't).
- **Native OS notifications** for DM/buy events and timed reminders — the UI
  calls `window.fasttShell.notify()` and the main process shows an Electron
  `Notification` (click → the app window, on that chat). On **macOS** they show
  in the shell's own toast window instead (`lib/toast-window.js`: top right,
  always on top, never takes focus), because Electron 42+ there delivers OS
  notifications only for a signed app. ⚠️ **Unverified in a packaged build —
  see "Notifications" below.**
- **Notifications and badge survive a page crash** — a main-process stream of
  the relay's `/events` (`lib/sse.js`, `lib/relay-notices.js`) pings DMs, buys
  and OF toasts, per the page's own notification settings, while the page is
  crashed, reloading or not loaded.
- **Sleep / lock pauses the clock** (`lib/clock-pause.js`): sleeping or locking
  the screen clocks the chatter out; waking or unlocking within the Agency's
  auto clock-out minutes clocks them back in on the same Creator. While clocked
  in, the app keeps the machine from idle-sleeping.
- **Tray / menu-bar icon** with Open, Clear Cache and Relaunch, and Quit.
- **Alert sounds** (12 synthesised presets) for new messages and timed
  reminders, played by the page; pick them in the bell's settings.
- **macOS: closing the window hides it**, so the page keeps running and
  notifying; click the Dock icon to bring it back, Cmd+Q to quit.
- **Unread dock badge** — a numeric dock badge on macOS, and a matching numbered
  taskbar overlay on Windows (`assets/overlay/`, counts 1–9 then `9+`).
- **External links** open in the OS browser; same-origin popouts (group view)
  open as in-app child windows.

## Run it (dev)

```bash
cd desktop
npm install
npm start          # opens the app; every launch shows the Settings screen first
npm run dev        # same, but enables the DevTools menu item
```

### Server URL

Precedence: env `OPENINFLOWW_URL` > the URL saved in the Settings screen.
Every launch opens the Settings screen first, pre-filled with the saved URL (or
`https://app.inflowwww.com` when none is saved); only the origin is saved, so a
pasted `#hash`, path or query is dropped. `inflowwww.com` (and `www.`) is the
marketing site, never a server: entered, saved or set in the env, it means
`https://app.inflowwww.com`, which also repairs installs that kept the old
`http://inflowwww.com` default. Tick **Don't show this again** to go
straight to the app on later launches; reopen Settings from the app menu
(**Inflowwww → Settings…**, ⌘,). When `OPENINFLOWW_URL` is set to a valid http(s)
URL the Settings screen is skipped; the env value is used for that run only and
never saved. An invalid value is ignored with a warning.

If loading the app fails (a network error, an HTTP 4xx/5xx such as a wrong
server's 404 or the share gate's 401, a page that stays blank for ~10s, or a
renderer crash) the Settings screen pops up with what failed, even if
**Don't show this again** is ticked; **Save & Open** retries.

```bash
OPENINFLOWW_URL=https://your-inflowwww-server npm start
```

Without the env var, Settings asks for your **Server URL** and your
**share token** (the `t=` value from your Inflowwww link). These are stored
in `fastt-desktop-config.json` under Electron's per-user data dir (mode `600`).
The token is encrypted with the OS keychain (`safeStorage`, field `shareTokenEnc`);
without real OS encryption (e.g. Linux `basic_text`) it stays plaintext. If it
can't be decrypted, the Settings screen opens again.

Settings → Advanced has hardware acceleration and secure DNS (DoH) switches; both
apply after **Restart**. Help → **Show Logs Folder** opens `logs/` (`main.log`,
2 × 1 MB, tokens redacted; crash dumps stay local in `Crashpad/`). Help → **Clear
Cache and Relaunch** clears the HTTP cache only, not the login.
The file name, the `OpenInfloww` userData folder, the `persist:fastt` session partition and the `window.fasttShell`
/ `fasttNative` / `fasttCapture` bridges keep their old names on purpose:
renaming them would log existing users out.

Dev-only: `npx electron . --screenshot-to /abs/path.png` captures the first
window (Settings, or the main window when Settings is skipped) about 3s after it
loads, writes the PNG and quits.
The token is seeded into the app's cookie + `localStorage` once, via the
frontend's own `?t=` mechanism — it is **not** re-appended to the URL on every
launch. Use **Re-seed Login / Fix Access** in the menu if the token rotates or
access expires.

## Add an OnlyFans account (native capture — replaces the extension)

Menu → **Add OnlyFans Account…**. A real OnlyFans login window opens; sign in
with **email + password**, then open your **Messages** so OnlyFans signs a
request. A small status panel walks through four steps (signed in to Inflowwww
in the main window, signed in to OnlyFans, Messages opened, saved) and saves on
its own once the first three are done (**Save now** / **Retry save** otherwise).
It POSTs the session, with the main window's sign-in cookie, to the relay's
`/admin/session/bootstrap`
(the same endpoint the extension fed), so it's a drop-in front end for a proven
path.

How it works: the shell injects a MAIN-world interceptor at document-start via
Chrome DevTools Protocol (`Page.addScriptToEvaluateOnNewDocument`) — a faithful
port of `loginExtensionMulti/interceptor.js` (`capture/of-interceptor-preload.js`), capturing the signed headers and the
webpack sign-rules (`static_param` from module 89668, `start`/`end` from 802313).
The OF login runs in a **non-persistent** partition that is wiped on teardown, so
OF cookies never linger on disk.

**Detection mitigation.** Electron's default UA + broken client-hints are a
fingerprint tell vs real Chrome (the fusion review's main objection to Phase 2).
The capture window uses CDP `Network.setUserAgentOverride` to present a real
Chrome UA **and** a consistent client-hints block (the documented fix for
electron#34762), and that same UA is what the relay replays. This makes Electron
login materially closer to real Chrome — but it is **not a guarantee** OnlyFans
won't flag it. **If an account matters, capturing it in the real Chrome extension
is still the lowest-risk path.** Prefer email/password login: social-login
pop-ups (Google/X) open in the OS browser and won't complete the in-app session.

## ⚠️ Notifications: changed, not yet verified in a packaged build

**What changed (W3 row 3.3).** The page no longer depends on the web
`Notification` permission inside the app. It calls `fasttShell.notify({id,
title, body, href})` (`preload.js`); the main process checks the sender origin,
treats title/body as plain text, dedupes by id (popouts run their own toaster)
and rate-limits, then shows a silent Electron `Notification` (`lib/notify.js`);
on macOS a card in the shell's toast window (`lib/toast-window.js`) instead.
A click shows the main window and opens `href` only when it is a same-origin
path. Also: the permission check handler now compares parsed origins (the
trailing-slash / empty-origin suspect below), Windows gets
`setAppUserModelId(appId)`, and on macOS closing the window hides it.

**Still to verify by the owner, in a packaged build** (`npm run pack`): a test
notification from bell → ⚙ → Test, a real DM while the window is unfocused or
hidden, a click on it opening the chat, the macOS toast window over a
full-screen app, and Windows toasts. If the packaged
macOS build still shows nothing, the remaining hypothesis is the Electron 42+
signing requirement below; the boot log line from `lib/signing.js` says how
the bundle is signed.

### Background (2026-08-21)

Tested on macOS 15.6.1 against packaged builds on **both** Electron 41 and 43:
the in-app test (bell → settings → Test) reports `Permission denied`, meaning
`Notification.permission` is already `"denied"` and `requestPermission()` is
never reached. Two supporting facts:

- **No `org.openinflowwww.*` bundle appears in `~/Library/Preferences/com.apple.ncprefs.plist`**,
  which lists the 128 apps macOS knows about — including `com.github.Electron`
  and other Electron apps. A build that had ever delivered a notification would
  be listed.
- Both Electron versions fail *identically*, which points at something common to
  all builds rather than the Electron 42 `UNNotification` signing change.

Leading suspect is this shell's own `setPermissionCheckHandler` (`main.js`),
which answers `Notification.permission` and returns false unless
`requestingOrigin === appOrigin`; if Chromium passes an empty origin for
notification checks, that denies on every version. **Not yet confirmed** — an
instrumented build was prepared but the trace was not captured before this was
parked.

Why it went unnoticed: `npm start` runs inside Electron's own signed, already
registered `Electron.app`, where notifications DO work. The feature can only
fail in the packaged bundle, so testing the obvious way gives a false pass.

It was parked on 2026-08-21 as not blocking, and picked up again by row 3.3
(above).

## Build installers

```bash
npm run dist:mac   # → dist/Inflowwww-0.2.0-arm64.dmg  and  -x64.dmg
npm run dist:win   # → dist/Inflowwww-Setup-0.2.0.exe   (builds fine ON macOS)
npm run pack       # unpacked build for quick local testing (no installer)
```

**The Windows installer now cross-builds on macOS.** electron-builder 26 ships
its own NSIS toolchain, so the old advice — "the installer must be built on a
Windows machine, it crashes under emulation on Apple Silicon" — is obsolete as of
the 0.2.0 upgrade. `npm run dist:win` produced a valid NSIS installer straight
from an M-series Mac, no Wine and no Windows VM. The GitHub Actions workflow is
still useful for a clean-room build, but is no longer required.

Builds are **unsigned** by default (`mac.identity: null`). See Signing below.

## Security posture (enforced in `main.js`)

- `nodeIntegration: false`, `contextIsolation: true`, `sandbox: true`.
- The remote page gets **no** privileged bridge — only a read-only
  `window.fasttShell` object (`preload.js`): version info plus `notify()`, which
  passes four strings to an origin-checked IPC. All capability (badge,
  external-link routing, permissions, notifications) lives in the main process.
- **Deny-by-default navigation**: foreign-origin top-level navigations and
  `window.open` targets go to the OS browser; only same-origin popouts become
  in-app windows.
- **Permissions**: only `notifications` are granted; camera/mic/geolocation/USB
  are denied.
- IPC handlers (settings) accept **only `file://` local senders** — the
  remote app page can never reach them.

## Signing (deferred — see the fusion review)

**Electron 42+ raises the stakes on macOS.** Electron 42 moved macOS
notifications to Apple's `UNNotification` API, which per Electron's breaking
changes "requires that an application be code-signed in order for notifications
to be displayed" — an unsigned app gets a `failed` event on the `Notification`
object and shows nothing. Whether this is why our packaged builds showed no
notifications is a hypothesis, not established (Electron 41 builds failed the
same way). Native notifications are a headline feature of this shell, so on
Electron 42+ signing may stop being cosmetic. Verify with
`scratchpad/probe-mac-notifications.sh` before assuming an unsigned build still
notifies.

Shipping unsigned is otherwise fine while your users are you + technical early
adopters (macOS: right-click → Open the first time). **Before a non-technical chatter-team
rollout, sign + notarize the mac build** — an unsigned `.dmg` shows *"app is
damaged and can't be opened"* to a normal user, and **macOS auto-update requires
a signed app** (so deferring signing also defers auto-update). Windows can stay
unsigned longer (SmartScreen "More info → Run anyway").

To sign later: get an Apple Developer ID cert ($99/yr), then set
`CSC_LINK`/`CSC_KEY_PASSWORD` + a notarize config in `package.json`'s `build.mac`
and drop `identity: null`.

## ⚠️ Pre-ship revocation probe (REQUIRED before a team rollout)

The fusion review's wrong-layer finding: a persistent Electron partition turns
the share token + session cookie into **durable on-disk credentials**, and
closing the window is **not** logout. Before handing this to a team, verify a
revoked user actually loses access. Run this matrix against the **real**
production edge:

1. Configure + authenticate the app with a `?t=` token.
2. Close and reopen the app; reboot the machine. → still logged in (expected).
3. Copy the Electron profile dir to a **second** machine, launch there.
4. On the server: revoke the employee, rotate the share token, invalidate the
   session.
5. **Verify**: every already-open window AND every subsequent API/navigation
   request fails **immediately** — not after cookie expiry. Confirm the token is
   not recoverable from disk, URL, or history to restore access.

If any case survives revocation, that's a **relay/edge/session change** that
becomes a Phase-1 requirement (not frontend-only).

## Still deliberately deferred

- **Sign + notarize the mac build** before a non-technical rollout (unsigned
  shows "app is damaged"); mac auto-update needs it too.
- **Run the revocation probe** below before a team rollout.
- **Verify a captured session end-to-end on a test account** (e.g. Ava) — that a
  captured login actually sends an OF message via the relay — before trusting the
  native capture for a real account. The capture path is faithful to the
  extension by construction + review, but has not been exercised against live OF
  in this environment.

## Limitations (v0.2)

- **No auto-update** yet — it requires signing on mac (see above). Ship it when
  you sign.
- The unread badge parses the page **title** (best-effort); if the title format
  changes the badge goes quiet, it never misfires.
