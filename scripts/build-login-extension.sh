#!/usr/bin/env bash
#
#
#
#
#

set -euo pipefail
cd "$(dirname "$0")/.."

SRC=loginExtensionMulti
VERSION=$(python3 -c 'import json,sys; print(json.load(open("'"$SRC"'/manifest.json"))["version"])')
ZIP="infloww-rea-login-capture-${VERSION}.zip"

FILES=(
  popup.js popup.html background.js bridge.js interceptor.js
  fansly_bridge.js fansly_interceptor.js manifest.json
  icons/icon16.png icons/icon32.png icons/icon48.png icons/icon128.png
)

for f in "${FILES[@]}"; do
  [[ -f "$SRC/$f" ]] || { echo "missing source file: $SRC/$f" >&2; exit 2; }
done

missing_from_files=$(SRC="$SRC" python3 - "${FILES[@]}" <<'PY'
import json, os, sys
m = json.load(open(os.path.join(os.environ["SRC"], "manifest.json")))
want = {"manifest.json"}
want.update(m.get("icons", {}).values())
act = m.get("action", {})
if act.get("default_popup"):
    want.add(act["default_popup"])
want.update(act.get("default_icon", {}).values())
sw = m.get("background", {}).get("service_worker")
if sw:
    want.add(sw)
for cs in m.get("content_scripts", []):
    want.update(cs.get("js", []))
    want.update(cs.get("css", []))
for war in m.get("web_accessible_resources", []):
    want.update(war.get("resources", []))
# A `*` glob in web_accessible_resources cannot be resolved to a file list here;
# it is not used today, and a build that starts using one must teach this check.
missing = sorted(p for p in want if "*" not in p and p not in set(sys.argv[1:]))
print("\n".join(missing))
PY
)
if [[ -n "$missing_from_files" ]]; then
  echo "manifest.json references files that FILES does not list:" >&2
  printf '  %s\n' $missing_from_files >&2
  echo "add them to FILES in $0 (or they ship missing and --check stays green)" >&2
  exit 2
fi

# Validate args before anything destructive: an unknown flag used to fall through to the rebuild.
MODE=build
case "$#" in
  0) ;;
  1) case "$1" in
       --check) MODE=check ;;
       *) echo "unknown arg: $1 (expected --check, or no argument to build)" >&2; exit 2 ;;
     esac ;;
  *) echo "too many args: expected --check, or no argument to build" >&2; exit 2 ;;
esac

if [[ "$MODE" == "check" ]]; then
  [[ -f "$ZIP" ]] || { echo "no $ZIP to check — run without --check to build it" >&2; exit 2; }
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  unzip -q "$ZIP" -d "$tmp"
  rc=0
  for f in "${FILES[@]}"; do
    if [[ ! -f "$tmp/$f" ]]; then
      echo "MISSING in $ZIP: $f"; rc=1; continue
    fi
    if ! cmp -s "$SRC/$f" "$tmp/$f"; then
      echo "DIFFERS from source: $f"; rc=1
    fi
  done
  while IFS= read -r got; do
    printf '%s\n' "${FILES[@]}" | grep -qxF "$got" || { echo "EXTRA in $ZIP: $got"; rc=1; }
  done < <(cd "$tmp" && find . -type f | sed 's|^\./||')
  if [[ $rc -eq 0 ]]; then
    echo "$ZIP matches $SRC/ — ${#FILES[@]}/${#FILES[@]} entries, manifest $VERSION"
  fi
  exit $rc
fi

rm -f "$ZIP"
(cd "$SRC" && zip -q -X "../$ZIP" "${FILES[@]}")
echo "built $ZIP from $SRC/ (manifest $VERSION)"
"$0" --check
