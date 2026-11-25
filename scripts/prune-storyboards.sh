#!/usr/bin/env bash
#
#

set -euo pipefail

DIR="${STORYBOARD_DIR:-/tmp/of-relay-storyboard}"
TTL_DAYS="${TTL_DAYS:-7}"

[[ -d "$DIR" ]] || exit 0

# mtime, not atime: macOS APFS does not update atime.
removed=$(find "$DIR" -mindepth 1 -maxdepth 1 -type d -mtime +"$TTL_DAYS" -print -exec rm -rf {} + 2>/dev/null | wc -l | tr -d ' ')

if [[ "$removed" -gt 0 ]]; then
  echo "[storyboard-prune] removed $removed dirs older than ${TTL_DAYS}d from $DIR"
fi
