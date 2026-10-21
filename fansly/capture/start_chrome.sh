#!/usr/bin/env bash
# Launch the REAL Google Chrome with CDP open, on a throwaway profile.
#
# Why the real Chrome and not Playwright's bundled Chromium: Fansly fingerprints
# the client (Cloudflare + its own client-check header). The stock Chrome build
# is the one the captured session was minted under, so it is the one least
# likely to get challenged mid-capture and poison a recording.
#
# Why a separate --user-data-dir: since Chrome 136, --remote-debugging-port is
# REFUSED on the default profile dir (a deliberate anti-token-theft change). It
# also means this never touches your everyday browsing profile. You log into
# fansly.com once here; the profile persists, so later runs are already signed in.
set -euo pipefail

PORT="${PORT:-9222}"
PROFILE="${PROFILE:-/tmp/fansly-chrome-profile}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Chrome already listening on :$PORT — reusing it."
  curl -s "http://127.0.0.1:$PORT/json/version" | sed -n 's/.*"Browser": *"\([^"]*\)".*/  \1/p'
  exit 0
fi

mkdir -p "$PROFILE"
echo "profile : $PROFILE"
echo "cdp     : http://127.0.0.1:$PORT"

"$CHROME" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=Translate,MediaRouter \
  --restore-last-session=false \
  "https://fansly.com/" \
  >/dev/null 2>&1 &

for _ in $(seq 1 40); do
  if curl -s "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
    echo "ready. Log into fansly.com in THIS window, then start the recorder."
    exit 0
  fi
  sleep 0.25
done
echo "Chrome did not open the CDP port in 10s" >&2
exit 1
