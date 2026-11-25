#!/usr/bin/env bash
#
#
#
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 <repo-path> <blob-file>" >&2; exit 2; }
path="$1"; blob="$2"
[ -f "$blob" ] || { echo "no such blob file: $blob" >&2; exit 2; }
sha="$(git hash-object -w "$blob")"
[ -n "$sha" ] || { echo "hash-object produced nothing for $blob" >&2; exit 1; }
mode="$(git ls-files --stage -- "$path" 2>/dev/null | awk 'NR==1{print $1}')"
[ -n "$mode" ] || mode="$(git ls-tree HEAD -- "$path" 2>/dev/null | awk 'NR==1{print $1}')"
if [ -z "$mode" ]; then
  if [ -x "$blob" ]; then mode=100755; else mode=100644; fi
fi
git update-index --add --cacheinfo "$mode,$sha,$path"
echo "staged $path from $blob as $mode (working tree untouched)"
