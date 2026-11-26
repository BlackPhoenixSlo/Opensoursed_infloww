#!/usr/bin/env bash
# BASE (default origin/main) = the script the no-marker run must match byte-for-byte.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BASE="${BASE:-origin/main}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
ok() { echo "PASS $1"; }
bad() { echo "FAIL $1"; fail=1; }

mkdir -p "$T/bin"
for c in docker git curl sudo; do
  cat > "$T/bin/$c" <<EOF
#!/usr/bin/env bash
echo "$c \$*" >> "\$CALLS"
[ "$c" = curl ] && echo 203.0.113.7
[ "$c" = git ] && [ "\$1" = clone ] && mkdir -p "\${@: -1}/service"
exit 0
EOF
  chmod +x "$T/bin/$c"
done

run() {
  local script="$1" oi="$2"; shift 2
  rm -rf "$T/dir"; : > "$T/calls"; sed "s|local root=/opt/oi |local root=\"$oi\" |" "$script" > "$T/run.sh"
  ( cd "$T" && PATH="$T/bin:$PATH" CALLS="$T/calls" HOME="$T" DIR="$T/dir" OI_FLEET_ROOT="$T/empty" \
      bash "$T/run.sh" "$@" > "$T/out" 2>&1 ); echo $? > "$T/rc"
}

git -C "$ROOT" show "$BASE:deploy/deploy-here.sh" > "$T/base.sh" || { echo "cannot read $BASE"; exit 2; }
mkdir -p "$T/empty"

run "$T/base.sh" "$T/empty"; cp "$T/out" "$T/base.out"; cp "$T/calls" "$T/base.calls"; cp "$T/rc" "$T/base.rc"
run "$ROOT/deploy/deploy-here.sh" "$T/empty"
if cmp -s "$T/out" "$T/base.out" && cmp -s "$T/calls" "$T/base.calls" && cmp -s "$T/rc" "$T/base.rc" \
   && grep -q '^docker compose up -d --build' "$T/calls"; then ok "no marker: output, calls, exit identical to $BASE"
else bad "no marker differs from $BASE"; diff "$T/base.out" "$T/out"; diff "$T/base.calls" "$T/calls"; fi

refused() {
  local name="$1" oi="$2" re="$3"; shift 3
  run "$ROOT/deploy/deploy-here.sh" "$oi" "$@"
  if [ "$(cat "$T/rc")" != 0 ] && [ ! -s "$T/calls" ] && [ "$(wc -l < "$T/out")" -eq 1 ] && grep -Eq "$re" "$T/out"
  then ok "$name"; else bad "$name: rc=$(cat "$T/rc") calls=$(cat "$T/calls") out=$(cat "$T/out")"; fi
}

M="$T/mark"; mkdir -p "$M/shards/cell-1"; echo x > "$M/shards/cell-1/override.yml"; echo "2026-11-26T00:00:00Z fleet.py shadow" > "$M/CELL-MODE"
refused "marker + Cell: refused before any call" "$M" "refused: cell-mode marker $M/CELL-MODE .*fleet.py deploy"
refused "marker + Cell: ignores OI_FLEET_ROOT with --cell-mode-check" "$M" "refused: cell-mode marker" --cell-mode-check

N="$T/nocell"; mkdir -p "$N"; echo "x" > "$N/CELL-MODE"
refused "mixed: marker, no Cell" "$N" "refused \(mixed\): cell-mode marker .* but no Cell"

C="$T/nomark"; mkdir -p "$C/shards/cell-2"; echo x > "$C/shards/cell-2/override.yml"
refused "mixed: Cell, no marker" "$C" "refused \(mixed\): Cells cell-2 .* no marker .*fleet.py deploy"

U="$T/unreadable"; mkdir -p "$U/shards"
if [ "$(id -u)" -ne 0 ]; then
  chmod 000 "$U/shards"
  refused "unreadable shards: refused before any call" "$U" "refused: cannot inspect .*shards" --cell-mode-check
  chmod 700 "$U/shards"
fi

run "$ROOT/deploy/deploy-here.sh" "$T/empty" --cell-mode-check
if [ "$(cat "$T/rc")" = 0 ] && [ ! -s "$T/calls" ] && grep -qx "cell-mode check: clear" "$T/out"; then ok "--cell-mode-check clear: exit 0, no calls"
else bad "--cell-mode-check clear: $(cat "$T/out")"; fi

AE="$ROOT/.claude/skills/ae-deploy/SKILL.md"; DA="$ROOT/.claude/skills/deploy-all/SKILL.md"
gate_line=$(grep -n -- "--cell-mode-check' < deploy/deploy-here.sh" "$AE" | head -1 | cut -d: -f1)
build_line=$(grep -n "nice -n 10 docker compose build" "$AE" | head -1 | cut -d: -f1)
if [ -n "$gate_line" ] && [ -n "$build_line" ] && [ "$gate_line" -lt "$build_line" ]; then ok "ae-deploy: gate before build"
else bad "ae-deploy: gate step missing or after build"; fi
if grep -q -- "--cell-mode-check' < deploy/deploy-here.sh" "$DA" && grep -q "cell-mode refusal stops only AE" "$DA"; then ok "deploy-all: gate step, AE only"
else bad "deploy-all: gate step missing"; fi

[ "$fail" = 0 ] && echo "deploy-here.test.sh: all passed"
exit "$fail"
