# Platforms

One product UI, the Next app in `app/`, talking to one backend, the FastAPI
relay in `service/`. Every surface below loads that same Next app.

## Web

- `docker compose up -d` (`docker-compose.yml`) runs:
  - `openinflowwww-relay` on `127.0.0.1:8787` (FastAPI, SQLite event store)
  - `openinflowwww-app` on `127.0.0.1:3001` (Next, `RELAY_URL=http://openinflowwww-relay:8787`)
  - `openinflowwww-autoheal`, plus `openinflowwww-tunnel` (cloudflared) under the
    `tunnel` profile.
- Both ports bind to localhost only. Expose the app (3001), not the relay, through
  a reverse proxy or the tunnel. The Next app proxies `/api/of/*`, `/admin/*`,
  `/events`, `/ws/*`, `/img` and `/health` to the relay (`app/next.config.ts`).
- Without Docker, use `scripts/start.sh`: it starts uvicorn on 8787 and `next dev` on 3001.
- Auth entry: `/login` (Sign in / Register). After login the app asks
  "Who's chatting?" to pick an employee, then opens the shell. Routes are listed
  in `docs/routes.md`.
- The relay root `/` returns `{"service": "openinflowwww-relay", "ok": true}`.
  The old static mockup at `/infloww/` is gone; the app redirects `/infloww/*` to `/`.

## Phone

- Same Next app, same URL. The layout is responsive (`app/app/layout.tsx` sets a
  device-width viewport with `viewportFit: cover` and tracks the visual viewport
  for the chat composer).
- No PWA manifest exists in `app/public` or `app/app`, so the app cannot be
  installed to the home screen as an app. The only service worker is
  `app/public/sw-images.js`, which caches images.
- There is no native app. This matches Infloww, which has none either
  (`docs/infloww-screens.md` §5: "Infloww is currently unavailable for mobile
  devices").

## Desktop

- Electron shell in `desktop/` (Mac + Windows). It remote-loads the Next app and
  bundles no product code. Multi-window: same-origin pop-outs (for example
  `/messages-pro/...`) open as in-app windows.
- Server URL precedence:
  1. env `OPENINFLOWW_URL` (used for that run only, never saved; an invalid URL
     is ignored with a warning; when it is set, first launch skips Settings)
  2. the URL saved in the Settings screen
  3. `http://localhost:3001`
- Run: `cd desktop && npm install && npm start` (`npm run dev` adds DevTools).
  Example: `OPENINFLOWW_URL=https://your-host.example.com npm start`.
- Build: `npm run dist:mac` (arm64 + x64 `.dmg`), `npm run dist:win` (NSIS
  `.exe`, builds on macOS too), `npm run pack` (unpacked). Output goes to
  `desktop/dist/`. Builds are unsigned (see `desktop/README.md`).
- CI: `.github/workflows/desktop-build.yml` builds the Mac and Windows installers
  on `workflow_dispatch` or a `desktop-v*` tag push and uploads them as run
  artifacts.
- Config: `fastt-desktop-config.json` (mode 600) in Electron's userData dir:
  `~/Library/Application Support/OpenInfloww/` on macOS,
  `%APPDATA%\OpenInfloww\` on Windows (pinned in `main.js`). The session lives in the
  `persist:fastt` partition. These old names are kept on purpose so existing
  users stay logged in.
- Dev-only `--screenshot-to <path>` writes a PNG of the main window about 3s
  after load, then quits (used for `docs/screenshots/desktop-shell.png`). If
  the launching shell exports `ELECTRON_RUN_AS_NODE=1`, unset it first;
  otherwise Electron starts as plain Node.
