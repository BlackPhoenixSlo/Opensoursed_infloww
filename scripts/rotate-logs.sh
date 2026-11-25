#!/usr/bin/env bash
#

set -u
MAX_BYTES="${MAX_BYTES:-52428800}"
LOGS=(
  "/tmp/of-relay.log"
  "/tmp/of-inbox.log"
  "/tmp/of-api.log"
)

for f in "${LOGS[@]}"; do
  [[ -f "$f" ]] || continue
  if size=$(stat -f%z "$f" 2>/dev/null); then :; else size=$(stat -c%s "$f" 2>/dev/null || echo 0); fi
  if [[ "$size" -gt "$MAX_BYTES" ]]; then
    echo "[rotate] $f $size bytes > $MAX_BYTES — rotating"
    cp "$f" "${f}.1" 2>/dev/null || true
    : > "$f"
  fi
done

exit 0
