#!/usr/bin/env bash
# Build — or VERIFY — the shipped login-capture extension zip from source.
#
# WHY THIS EXISTS
#
# `infloww-rea-login-capture-<version>.zip` is a tracked binary. Four of them sit at
# the repo root and there are 25 zip blobs across history: every rebuild adds an
# incompressible object no diff can review, and whether the zip matches the
# source it claims to be built from is a question nobody can answer by reading a
# pull request. Today it does match (12/12 entries, verified) — but by
# DISCIPLINE, not by construction, and discipline is exactly what is missing on
# the day the shipped extension quietly stops being the reviewed one.
#
#   ./scripts/build-login-extension.sh --check   # does the tracked zip match source?
#   ./scripts/build-login-extension.sh           # rebuild it from source
#
# `--check` is the one to wire into CI (and it is what a pre-commit hook should
# run). It compares the CONTENT of every entry, not the archive bytes: zip
# embeds mtimes, so two archives of identical files differ byte-for-byte and a
# checksum comparison would be permanently red.
#
# THE REAL FIX, which this script only makes possible: stop tracking the zips,
# and publish one built by CI from a tagged commit. That is a `git rm --cached`
# plus a `.gitignore` line plus a release job, and it is a human's call because
# it changes what a `git clone` hands you.

set -euo pipefail
cd "$(dirname "$0")/.."

SRC=loginExtensionMulti
# The manifest is the single source of truth for the version, so the zip cannot
# be named after a version the extension does not report.
VERSION=$(python3 -c 'import json,sys; print(json.load(open("'"$SRC"'/manifest.json"))["version"])')
ZIP="infloww-rea-login-capture-${VERSION}.zip"

# Exactly what ships. Named explicitly rather than globbed: a stray file in the
# source folder (a scratch note, an editor backup) must not silently become part
# of a published extension.
FILES=(
  popup.js popup.html background.js bridge.js interceptor.js
  fansly_bridge.js fansly_interceptor.js manifest.json
  icons/icon16.png icons/icon32.png icons/icon48.png icons/icon128.png
)

for f in "${FILES[@]}"; do
  [[ -f "$SRC/$f" ]] || { echo "missing source file: $SRC/$f" >&2; exit 2; }
done

# …and every path the MANIFEST names is in FILES. `FILES` hand-restates the
# manifest's own file list, so the two can drift in the one direction that is
# silent: a content script added to `manifest.json` and not to `FILES` is left
# out of the zip, the shipped extension is broken on that site, and `--check`
# calls the zip a clean match because it only ever compares the list to itself.
# This asks the manifest instead.
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

# Arg handling BEFORE anything destructive. `--check` is read-only; the no-arg
# path deletes and rebuilds the tracked zip. An unknown flag used to fall
# through to that rebuild — so a typo'd `--dry-run` or `--verify` REBUILT the
# artifact it was asked to inspect.
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
  # …and nothing the source does not have. An extra file in a published zip is
  # the half nobody thinks to look for.
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
