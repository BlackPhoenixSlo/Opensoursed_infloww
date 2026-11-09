#!/usr/bin/env bash
# Keep relay logs across a container recreation (the health sweep reads a whole interval
# through a redeploy). Run from the checkout before the relay's `docker compose up`; idempotent.
#   1. journald: persistent, bounded (1 GB, 8 days), rate limit raised for relay boot bursts
#      (journald restarted only when the drop-in changed).
#   2. compose .env: RELAY_LOG_DRIVER=journald (docker-compose.yml; default `local`). A tracked
#      .env (a client repo carries it) is never edited here: it prints the line to commit upstream.
# No systemd-journald: changes nothing, exit 0 (the relay keeps `local`, collect.sh reads docker logs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENVF="$ROOT/.env"

if ! command -v systemctl >/dev/null || ! command -v journalctl >/dev/null || ! systemctl is-active -q systemd-journald; then
  echo "journal: no systemd-journald here; relay keeps the local log driver"
  exit 0
fi
SUDO=(); [ "$(id -u)" -eq 0 ] || SUDO=(sudo)

conf=/etc/systemd/journald.conf.d/50-oi-relay-persistent.conf
want='[Journal]
Storage=persistent
SystemMaxUse=1G
SystemKeepFree=2G
MaxRetentionSec=8day
RuntimeMaxUse=128M
RateLimitIntervalSec=30s
RateLimitBurst=100000'
if [ -d /var/log/journal ] && [ "$(cat "$conf" 2>/dev/null)" = "$want" ]; then
  echo "journal: already persistent (1G / 8 days)"
else
  "${SUDO[@]}" install -d -m 0755 /var/log/journal /etc/systemd/journald.conf.d
  printf '%s\n' "$want" | "${SUDO[@]}" tee "$conf" >/dev/null
  "${SUDO[@]}" systemctl restart systemd-journald
  "${SUDO[@]}" journalctl --flush || true
  echo "journal: persistent enabled (1G / 8 days): $conf"
fi

if grep -q '^RELAY_LOG_DRIVER=' "$ENVF" 2>/dev/null; then
  echo "env: $(grep '^RELAY_LOG_DRIVER=' "$ENVF" | tail -1) (kept)"
elif git -C "$ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "env: .env is tracked by git: commit RELAY_LOG_DRIVER=journald to it upstream; relay stays on local until then" >&2
else
  printf '\n# deploy/enable-persistent-journal.sh: relay logs survive a recreation\nRELAY_LOG_DRIVER=journald\n' >> "$ENVF"
  echo "env: RELAY_LOG_DRIVER=journald added to $ENVF"
fi
