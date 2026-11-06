#!/bin/bash
# slop-netloss: packet loss, delay and bandwidth on loopback TCP ports, via macOS dummynet (dnctl + pfctl).
# Runs as root through sudo (slop/install-netloss copies it to /usr/local/libexec/slop-netloss, root:wheel 755, and
# grants this one path NOPASSWD). Never edit the installed copy; the harness refuses a copy that differs from this.
#
#   slop-netloss [--dry-run] on <port[,port...]> <rtt_ms> <plr> <down_kbit> <up_kbit>
#   slop-netloss [--dry-run] off
#   slop-netloss status
#
# on: lo0 only, IPv4 127.0.0.1 <-> 127.0.0.1, only TCP to / from the given ports (1024-65535, at most 4). Two fixed
#     dummynet pipes: UP (to the port: the browser's upload) and DOWN (from the port: the download), each with
#     rtt_ms / 2 delay, its own bandwidth (0 = no cap) and plr (per packet, each direction). Rules match `out` only:
#     a loopback packet passes pf out and in, so matching both would shape it twice. MSS clamped to 1460 on those
#     ports (lo0's MTU is 16 KB: loss and queueing per 16 KB packet would not be a phone's). Rules live in the
#     sub-anchor com.apple/slop-netloss, which /etc/pf.conf's `dummynet-anchor "com.apple/*"` / `scrub-anchor
#     "com.apple/*"` already evaluate: the main ruleset is never loaded or flushed. pf enabled with -E (a reference;
#     its token kept in the state file) so `off` releases only ours: pf stays on only if something else holds it.
# off: idempotent. Loads an empty ruleset into the sub-anchor (never -F: that reaches global states / counters), deletes the two pipes, releases the token. Safe with nothing on.
# status: pf's enable state and references, the sub-anchor's rules, the pipes. Read-only.
# --dry-run: validate and print the commands and rules `on` / `off` would run; touches nothing (no root needed).
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
IFS=$' \t\n'
umask 022

ANCHOR="com.apple/slop-netloss"
PIPE_UP=7401
PIPE_DOWN=7402
MSS=1460
STATE=/var/run/slop-netloss.state   # root 644: "token=<n>" while on; its existence = shaping may be on
PFCTL=/sbin/pfctl
DNCTL=/usr/sbin/dnctl

die() { echo "slop-netloss: $*" >&2; exit 2; }
usage() { die "usage: slop-netloss [--dry-run] on <port[,port...]> <rtt_ms> <plr> <down_kbit> <up_kbit> | [--dry-run] off | status"; }

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
[ $# -ge 1 ] || usage
CMD=$1; shift

int_in() {  # int_in <name> <value> <min> <max>: a plain decimal integer in range
  case "$2" in ''|*[!0-9]*) die "$1 must be a decimal integer, got '$2'";; esac
  [ ${#2} -le 6 ] || die "$1 out of range: $2"
  [ "$2" = 0 ] || [ "${2#0}" = "$2" ] || die "$1 must not have leading zeros: $2"
  [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] || die "$1 must be $3..$4, got $2"
}

PORTS=() RTT=0 PLR=0 DOWN=0 UP=0
parse_on() {
  [ $# -eq 5 ] || usage
  case "$1" in ''|*[!0-9,]*|,*|*,|*,,*) die "ports must be a comma list of integers, got '$1'";; esac
  local IFS=,
  # shellcheck disable=SC2206  # split on commas, charset checked above
  PORTS=($1)
  IFS=$' \t\n'
  [ ${#PORTS[@]} -ge 1 ] && [ ${#PORTS[@]} -le 4 ] || die "1..4 ports, got ${#PORTS[@]}"
  local p; for p in "${PORTS[@]}"; do int_in port "$p" 1024 65535; done
  int_in rtt_ms "$2" 0 2000; RTT=$2
  # plr: 0, or 0.<1-4 digits>, at most 0.2
  case "$3" in 0|0.[0-9]|0.[0-9][0-9]|0.[0-9][0-9][0-9]|0.[0-9][0-9][0-9][0-9]) ;; *) die "plr must be 0..0.2 (at most 4 decimals), got '$3'";; esac
  local frac="${3#0}"; frac="${frac#.}"; frac="${frac}0000"; frac="${frac:0:4}"
  [ $((10#$frac)) -le 2000 ] || die "plr must be <= 0.2, got $3"
  PLR=$3
  int_in down_kbit "$4" 0 100000; DOWN=$4
  int_in up_kbit "$5" 0 100000; UP=$5
  { [ "$DOWN" = 0 ] || [ "$DOWN" -ge 64 ]; } || die "down_kbit: 0 (no cap) or >= 64, got $DOWN"
  { [ "$UP" = 0 ] || [ "$UP" -ge 64 ]; } || die "up_kbit: 0 (no cap) or >= 64, got $UP"
}

rules() {  # the sub-anchor's ruleset: normalization first, then dummynet (pf.conf's order)
  local p
  for p in "${PORTS[@]}"; do
    echo "scrub on lo0 inet proto tcp from 127.0.0.1 to 127.0.0.1 port $p max-mss $MSS"
    echo "scrub on lo0 inet proto tcp from 127.0.0.1 port $p to 127.0.0.1 max-mss $MSS"
  done
  for p in "${PORTS[@]}"; do
    echo "dummynet out quick on lo0 inet proto tcp from 127.0.0.1 to 127.0.0.1 port $p pipe $PIPE_UP"
    echo "dummynet out quick on lo0 inet proto tcp from 127.0.0.1 port $p to 127.0.0.1 pipe $PIPE_DOWN"
  done
}

pipe_args() {  # pipe_args <kbit>: dnctl config for one direction
  local a="delay $((RTT / 2))"
  [ "$1" = 0 ] || a="$a bw ${1}Kbit/s"
  [ "$PLR" = 0 ] || a="$a plr $PLR"
  echo "$a"
}

run() {  # run <cmd...>: print in dry-run, else execute
  if [ $DRY = 1 ]; then echo "+ $*"; else "$@"; fi
}

need_root() { [ "$(id -u)" = 0 ] || die "$CMD needs root (sudo -n /usr/local/libexec/slop-netloss $CMD ...); --dry-run does not"; }

do_off() {
  run "$PFCTL" -q -a "$ANCHOR" -f /dev/null 2>/dev/null || true   # an empty ruleset: every rule type in it gone
  run "$DNCTL" -q pipe delete "$PIPE_UP" 2>/dev/null || true
  run "$DNCTL" -q pipe delete "$PIPE_DOWN" 2>/dev/null || true
  if [ $DRY = 1 ]; then echo "+ $PFCTL -X <token from $STATE>"; echo "+ rm -f $STATE"; return 0; fi
  if [ -f "$STATE" ]; then
    local tok; tok=$(sed -n 's/^token=\([0-9][0-9]*\)$/\1/p' "$STATE" | head -1)
    [ -z "$tok" ] || "$PFCTL" -X "$tok" >/dev/null 2>&1 || true
    rm -f "$STATE"
  fi
}

do_on() {
  if [ $DRY = 1 ]; then
    echo "# anchor $ANCHOR rules:"; rules
    echo "# pfctl syntax check (unprivileged, pfctl -nf):"
    if err=$(rules | "$PFCTL" -nf - 2>&1); then echo "syntax ok"
    else echo "$err" | grep -v -e 'could result in flushing' -e 'present in the main ruleset' \
      -e '/etc/pf.conf for further' -e '^$' >&2; die "pfctl rejected the rules"; fi
    echo "+ $DNCTL pipe $PIPE_UP config $(pipe_args "$UP")"
    echo "+ $DNCTL pipe $PIPE_DOWN config $(pipe_args "$DOWN")"
    echo "+ printf 'rules...' | $PFCTL -a $ANCHOR -f -"
    echo "+ $PFCTL -E   (token -> $STATE)"
    return 0
  fi
  "$PFCTL" -s dummynet 2>/dev/null | grep -qF 'dummynet-anchor "com.apple/*"' \
    || die "the main ruleset has no dummynet-anchor \"com.apple/*\" (/etc/pf.conf's, loaded at boot); refusing to load a main ruleset"
  local tok=""
  [ -f "$STATE" ] && tok=$(sed -n 's/^token=\([0-9][0-9]*\)$/\1/p' "$STATE" | head -1)
  echo "on" > "$STATE"   # before any change: a crash from here on leaves the marker the harness's stale-off reads
  [ -z "$tok" ] || echo "token=$tok" > "$STATE"
  # shellcheck disable=SC2046  # pipe_args is a word list on purpose
  "$DNCTL" -q pipe "$PIPE_UP" config $(pipe_args "$UP")
  # shellcheck disable=SC2046
  "$DNCTL" -q pipe "$PIPE_DOWN" config $(pipe_args "$DOWN")
  rules | "$PFCTL" -q -a "$ANCHOR" -f -
  if [ -z "$tok" ]; then
    tok=$("$PFCTL" -E 2>&1 | sed -n 's/.*Token : \([0-9][0-9]*\).*/\1/p' | head -1)
    [ -n "$tok" ] || { do_off; die "pfctl -E gave no token; shaping rolled back"; }
    echo "token=$tok" > "$STATE"
  fi
  do_status
}

do_status() {
  echo "state: $( [ -f "$STATE" ] && cat "$STATE" || echo off)"
  if [ "$(id -u)" != 0 ]; then echo "(not root: pf / dnctl details need sudo)"; return 0; fi
  "$PFCTL" -s info 2>/dev/null | head -1 || true
  echo "anchor $ANCHOR:"
  "$PFCTL" -a "$ANCHOR" -s dummynet 2>/dev/null | sed 's/^/  /' || true
  "$PFCTL" -a "$ANCHOR" -s rules 2>/dev/null | sed 's/^/  /' || true
  echo "pipes:"
  "$DNCTL" pipe show "$PIPE_UP" "$PIPE_DOWN" 2>/dev/null | sed 's/^/  /' || true
}

case "$CMD" in
  on) parse_on "$@"; [ $DRY = 1 ] || need_root; do_on ;;
  off) [ $# -eq 0 ] || usage; [ $DRY = 1 ] || need_root; do_off; [ $DRY = 1 ] || echo "slop-netloss: off" ;;
  status) [ $# -eq 0 ] && [ $DRY = 0 ] || usage; do_status ;;
  *) usage ;;
esac
