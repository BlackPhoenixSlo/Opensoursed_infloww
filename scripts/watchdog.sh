#!/usr/bin/env bash
# watchdog.sh — install the server watchdog on a box and point it at a phone.
#
# Usage (from your laptop; the box needs root ssh, curl and python3):
#   scripts/watchdog.sh root@1.2.3.4                    # read-only status
#   scripts/watchdog.sh root@1.2.3.4 install [--url https://site/ ...] [--containers "a b"]
#   scripts/watchdog.sh root@1.2.3.4 telegram           # paste the BotFather token, then send the bot "hi"
#   scripts/watchdog.sh root@1.2.3.4 whatsapp           # CallMeBot phone + apikey
#   scripts/watchdog.sh root@1.2.3.4 webhook            # JSON webhook URL (n8n etc.)
#   scripts/watchdog.sh root@1.2.3.4 status | test | clear <telegram|whatsapp|webhook>
#
# Secrets are read from stdin, never argv: argv lands in shell history and `ps`
# on both machines. They reach the box on ssh's stdin, into a 0600 file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_DIR="/root/fastt/scripts"
CFG="/root/fastt/watchdog.env"
LOG="/var/log/fastt-watchdog.log"
STATE="/var/lib/fastt-watchdog"
TG_TRIES="${TG_TRIES:-20}"
TG_SLEEP="${TG_SLEEP:-3}"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

read_secret() {
  local prompt="$1" __var="$2" val=""
  if [ -t 0 ]; then printf '%s: ' "$prompt" >&2; fi
  IFS= read -r val || true
  val="${val%$'\r'}"
  printf -v "$__var" '%s' "$val"
}

remote() {
  local command
  printf -v command '%q ' "$@"
  ssh "$HOST" "$command"
}

write_config() {
  local prog
  prog="$(cat <<'PY'
import os, pathlib, re, shlex, sys, tempfile

p = pathlib.Path(sys.argv[1])
fields = sys.stdin.buffer.read().split(b"\0")
if fields.pop() or len(fields) % 2:
    sys.exit("invalid config input")
pairs = dict(zip(map(os.fsdecode, fields[::2]), map(os.fsdecode, fields[1::2])))
if any(not re.fullmatch(r"[A-Z_]+", key) for key in pairs):
    sys.exit("invalid config key")

lines = p.read_text().split("\n") if p.exists() else []
entries = re.compile(r"^\s*#?\s*(" + "|".join(pairs) + r")=")
lines = [line for line in lines if not entries.match(line)]
text = "\n".join(lines).rstrip("\n")
fd, temp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".")
try:
    with os.fdopen(fd, "w") as out:
        if text:
            out.write(text + "\n")
        for key, value in pairs.items():
            quoted = "$'\\n'".join(map(shlex.quote, value.split("\n")))
            out.write(f"{key}={quoted}\n")
    os.replace(temp, p)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
print("set " + ", ".join(pairs) + " in " + str(p))
PY
)" && [ -n "$prog" ] || { echo "❌ could not prepare config writer" >&2; return 1; }
  printf '%s\0' "$@" | remote python3 -c "$prog" "$CFG" ||
    { echo "❌ could not write $CFG on $HOST" >&2; return 1; }
}

tg_updates() {
  local token="$1" offset="$2" body
  body="$(printf 'url = "https://api.telegram.org/bot%s/getUpdates?offset=%s"\n' "$token" "$offset" \
          | curl -q -sS --max-time 15 -K - 2>/dev/null)" || return 1
  printf '%s' "$body" | python3 -c '
import json, sys
response = json.load(sys.stdin)
if response.get("ok") is False:
    sys.exit(2)
if response.get("ok") is not True:
    sys.exit(1)
offset = int(sys.argv[1])
updates = sorted(
    (u for u in response.get("result", []) if u["update_id"] >= offset),
    key=lambda u: u["update_id"], reverse=True,
)
print(updates[0]["update_id"] + 1 if updates else offset)
for update in updates:
    message = update.get("message", {})
    chat = message.get("chat", {})
    if message.get("text", "").strip().casefold() == "hi" and "id" in chat:
        print(chat["id"])
        print(chat.get("title") or chat.get("username") or "")
        break' "$offset" 2>/dev/null
}

tg_chat_id() {
  local token="$1" i page offset=0 next
  for ((i = 1; i <= TG_TRIES; i++)); do
    if page="$(tg_updates "$token" "$offset")"; then
      next="${page%%$'\n'*}"
      [ "$next" != "$offset" ] || break
      offset="$next"
    else
      [ "$?" -ne 2 ] || return 2
      return 3
    fi
  done
  [ "$i" -le "$TG_TRIES" ] || return 3
  echo "Now open your bot in Telegram and send it: hi" >&2
  if [ -t 0 ]; then read -r -p "Press Enter once sent… " _ || true; fi

  for ((i = 1; i <= TG_TRIES; i++)); do
    if page="$(tg_updates "$token" "$offset")"; then
      offset="${page%%$'\n'*}"
      if [[ "$page" = *$'\n'* ]]; then
        printf '%s\n' "${page#*$'\n'}"
        return 0
      fi
    else
      [ "$?" -ne 2 ] || return 2
    fi
    [ "$i" -lt "$TG_TRIES" ] && sleep "$TG_SLEEP"
  done
  return 1
}

fire_test() {
  local rc
  if remote "$REMOTE_DIR/notify.sh" ok "$1" "$2" "${3:-}" "${4:-}" </dev/null; then
    echo "✅ delivered — check your phone"
  else
    rc=$?
    if [ "${4:-}" = --allow-unconfigured ] && [ "$rc" -eq 4 ]; then
      echo "    no channel yet: run  scripts/watchdog.sh $HOST telegram"
      return 0
    fi
    echo "❌ not delivered (notify.sh found no working channel)"
    return 3
  fi
}

status() {
  local nm wm
  nm="$(md5 -q "$HERE/notify.sh" 2>/dev/null || md5sum "$HERE/notify.sh" | cut -d' ' -f1)"
  wm="$(md5 -q "$HERE/vps-watchdog.sh" 2>/dev/null || md5sum "$HERE/vps-watchdog.sh" | cut -d' ' -f1)"
  remote bash -s -- "$nm" "$wm" "$REMOTE_DIR" "$CFG" "$STATE" "$LOG" <<'REMOTE'
set -uo pipefail
WANT_NOTIFY=$1 WANT_WD=$2 DIR=$3 CFG=$4 STATE=$5 LOG=$6
say() { printf '  %-18s %s\n' "$1" "$2"; }
echo "state on $(hostname -s):"
for f in notify.sh vps-watchdog.sh; do
  case "$f" in notify.sh) want="$WANT_NOTIFY" ;; *) want="$WANT_WD" ;; esac
  if [ -f "$DIR/$f" ]; then
    [ "$(md5sum "$DIR/$f" | cut -d' ' -f1)" = "$want" ] && say "$f" "present, matches laptop" \
                                                     || say "$f" "present but STALE vs laptop"
  else say "$f" "MISSING"; fi
done
if [ -f "$CFG" ]; then
  python3 - "$CFG" <<'PY'
import re, sys

channels = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "WHATSAPP_PHONE", "WHATSAPP_APIKEY", "ALERT_WEBHOOK_URL")
probes = ("PUBLIC_URLS", "PUBLIC_URL", "WATCH_CONTAINERS")
values = {}
with open(sys.argv[1]) as config:
    for line in config:
        entry = re.match(r"^\s*([A-Z_]+)=(.*)$", line)
        if entry:
            key, value = entry.groups()
            values[key] = value.strip()
for key in channels + probes:
    value = values.get(key, "").strip("'\"")
    if key in channels:
        print(f"  {key:<18} " + ("(set)" if value else "(not set)"))
    elif value:
        print(f"  {key:<18} {value}")
PY
else say "watchdog.env" "MISSING"; fi
cron="$(crontab -l 2>/dev/null | grep 'vps-watchdog.sh' || true)"
say "cron" "${cron:-NOT INSTALLED}"
command -v curl >/dev/null 2>&1 && say "curl" "present" || say "curl" "MISSING — no channel can send"
[ -f "$STATE/cpustat" ] && say "last run" "$(date -r "$STATE/cpustat" '+%Y-%m-%d %H:%M:%S %Z')" \
                        || say "last run" "never"
echo "last alerts:"
if [ -f "$LOG" ]; then tail -n 5 "$LOG" | sed 's/^/  /'; fi
REMOTE
}

copy_scripts() {
  local f stage
  for f in notify.sh vps-watchdog.sh; do
    bash -n "$HERE/$f" || { echo "❌ $HERE/$f does not parse" >&2; return 1; }
  done

  echo "==> copying the watchdog to $HOST"
  if remote mkdir -p "$REMOTE_DIR" </dev/null &&
     stage="$(remote mktemp "$REMOTE_DIR/.watchdog.XXXXXXXX" </dev/null)"; then
    if scp -q "$HERE/notify.sh" "$HOST:$stage.notify.sh.new" </dev/null &&
       scp -q "$HERE/vps-watchdog.sh" "$HOST:$stage.vps-watchdog.sh.new" </dev/null &&
       remote bash -s -- "$REMOTE_DIR" "$stage" <<'REMOTE'
set -euo pipefail
dir=$1 stage=$2
bash -n "$stage.notify.sh.new"
bash -n "$stage.vps-watchdog.sh.new"
chmod 0755 "$stage.notify.sh.new" "$stage.vps-watchdog.sh.new"
mv -f "$stage.notify.sh.new" "$dir/notify.sh"
mv -f "$stage.vps-watchdog.sh.new" "$dir/vps-watchdog.sh"
REMOTE
    then
      remote rm -f "$stage" </dev/null || return 1
      return 0
    fi
    remote rm -f "$stage" "$stage.notify.sh.new" "$stage.vps-watchdog.sh.new" </dev/null || true
  fi
  echo "❌ could not install watchdog scripts on $HOST" >&2
  return 1
}

install() {
  local urls="" containers="" set_c=0 rc
  while [ $# -gt 0 ]; do
    case "$1" in
      --url) urls="${urls:+$urls }${2:?--url needs a value}"; shift 2 ;;
      --containers) containers="${2-}"; set_c=1; shift 2 ;;
      *) echo "unknown install flag: $1" >&2; exit 1 ;;
    esac
  done
  urls="${urls:-${PUBLIC_URLS:-}}"
  if [ "$set_c" -eq 0 ] && [ -n "${WATCH_CONTAINERS+x}" ]; then containers="$WATCH_CONTAINERS"; set_c=1; fi

  copy_scripts || return 1
  remote bash -s -- "$REMOTE_DIR" "$CFG" "$LOG" <<'REMOTE' || return 1
set -euo pipefail
DIR=$1 CFG=$2 LOG=$3
# holds the secrets: created once, never overwritten
if [ ! -f "$CFG" ]; then
  (umask 077; cat > "$CFG") <<'ENVEOF'
# watchdog.env — alert channels + what to watch. Set with scripts/watchdog.sh.
#TELEGRAM_TOKEN=
#TELEGRAM_CHAT_ID=
#WHATSAPP_PHONE=
#WHATSAPP_APIKEY=
#ALERT_WEBHOOK_URL=
#PUBLIC_URLS="https://your-site.example.com/"
#WATCH_CONTAINERS="app relay"
#STEAL_WARN=25
#LOAD_MULT=4
#DISK_WARN=85
ENVEOF
  chmod 0600 "$CFG"
  echo "created $CFG"
fi
LINE="*/3 * * * * $DIR/vps-watchdog.sh >> $LOG 2>&1"
cron_err="$(mktemp)"
trap 'rm -f "$cron_err"' EXIT
if ! cron="$(LC_ALL=C crontab -l 2>"$cron_err")"; then
  err="$(cat "$cron_err")"
  if [[ "$err" != 'no crontab for '* || "$err" == *$'\n'* ]]; then
    echo "❌ could not read crontab: $err" >&2
    exit 1
  fi
  cron=""
fi
if ! { printf '%s' "${cron:+$cron$'\n'}" | grep -Fv -- "$DIR/vps-watchdog.sh" || true; echo "$LINE"; } | crontab - ||
   ! cron="$(crontab -l 2>/dev/null)" || ! grep -Fxq "$LINE" <<< "$cron"; then
  echo "❌ could not install watchdog cron" >&2
  exit 1
fi
echo "cron: every 3 min"
cat > /etc/logrotate.d/fastt-watchdog <<LREOF
$LOG {
    weekly
    rotate 4
    size 1M
    missingok
    notifempty
    compress
    copytruncate
}
LREOF
REMOTE

  if [ "$set_c" -eq 0 ]; then
    rc=0
    remote grep -qE '^[[:space:]]*WATCH_CONTAINERS=' "$CFG" </dev/null || rc=$?
    if [ "$rc" -eq 1 ] && containers="$(remote docker ps --format '{{.Names}}' </dev/null | xargs)"; then
      echo "watching running containers: ${containers:-none}"
      set_c=1
    elif [ "$rc" -ne 0 ]; then
      echo "⚠ could not list containers; re-run with --containers" >&2
    fi
  fi
  set --
  [ -n "$urls" ] && set -- "$@" PUBLIC_URLS "$urls"
  [ "$set_c" -eq 1 ] && set -- "$@" WATCH_CONTAINERS "$containers"
  if [ "$#" -gt 0 ]; then write_config "$@" || return 1; fi
  remote grep -qE '^[[:space:]]*PUBLIC_URLS?=' "$CFG" </dev/null ||
    echo 'no site to probe: re-run install with --url https://your-site/'
  remote "$REMOTE_DIR/vps-watchdog.sh" </dev/null >/dev/null ||
    { echo "❌ watchdog smoke run failed on $HOST" >&2; return 1; }

  echo "==> test alert"
  fire_test "watchdog installed" "The alert path works. Checks run every 3 minutes and speak only when something changes." "" --allow-unconfigured
}

channel() {
  local mode="$1"
  shift
  case "$mode" in
    telegram)
      read_secret "Bot token from @BotFather" TOKEN
      [[ "${TOKEN:-}" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "REFUSING: that does not look like a bot token (123456:ABC…)"; exit 1; }
      local chat_info chat_id chat_name answer rc
      if chat_info="$(tg_chat_id "$TOKEN")"; then
        chat_id="${chat_info%%$'\n'*}"
        chat_name="${chat_info#"$chat_id"}"
        chat_name="${chat_name#$'\n'}"
      else
        rc=$?
        case "$rc" in
          2) echo "❌ Telegram token rejected" ;;
          3) echo "❌ could not finish reading Telegram backlog; re-run setup" ;;
          *) echo "❌ no message reached the bot. Send it \"hi\" (press Start first) and re-run." ;;
        esac
        return 1
      fi
      printf 'found chat id %s%s\n' "$chat_id" "${chat_name:+ ($chat_name)}"
      if [ -t 0 ]; then
        read -r -p "Use this chat? [y/N] " answer || return 1
        [[ "$answer" = [yY] ]] || return 1
      fi
      set -- TELEGRAM_TOKEN "$TOKEN" TELEGRAM_CHAT_ID "$chat_id"
      ;;
    whatsapp)
      read_secret "WhatsApp number, international, digits only (e.g. 38641234567)" PHONE
      read_secret "CallMeBot apikey" APIKEY
      [[ "${PHONE:-}" =~ ^[0-9]{8,}$ ]] && [ -n "${APIKEY:-}" ] || { echo "REFUSING: need a digits-only phone and an apikey"; exit 1; }
      set -- WHATSAPP_PHONE "$PHONE" WHATSAPP_APIKEY "$APIKEY"
      ;;
    webhook)
      read_secret "Webhook URL" URL
      [[ "${URL:-}" =~ ^https?:// ]] || { echo "REFUSING: must be an http(s) URL"; exit 1; }
      remote command -v jq </dev/null >/dev/null 2>&1 ||
        { echo "❌ webhook requires jq on $HOST" >&2; return 1; }
      set -- ALERT_WEBHOOK_URL "$URL"
      ;;
  esac
  copy_scripts || return 1
  write_config "$@" || return 1
  fire_test "watchdog channel live" "Alerts now reach you. Checks run every 3 minutes and speak only when something changes." "$mode"
}

clear_channel() {
  local pat
  case "${1:-}" in
    whatsapp) pat='WHATSAPP_PHONE|WHATSAPP_APIKEY' ;;
    webhook)  pat='ALERT_WEBHOOK_URL' ;;
    telegram) pat='TELEGRAM_TOKEN|TELEGRAM_CHAT_ID' ;;
    *) echo "clear which: telegram | whatsapp | webhook"; exit 1 ;;
  esac
  remote sed -i -E "s/^[[:space:]]*(($pat)=)/#\\1/" "$CFG" </dev/null &&
    echo "commented out: $1"
}

dispatch() {
  local run="$1" mode="$2"
  shift 2
  case "$mode" in
    status|show) set -- status ;;
    install) set -- install "$@" ;;
    telegram|whatsapp|webhook) set -- channel "$mode" ;;
    test) set -- fire_test "channel test" "Manual test. If this reached you, an outage will too." ;;
    clear) set -- clear_channel "${1:-}" ;;
    *) if [ "$run" = run ]; then usage; fi; return 1 ;;
  esac
  if [ "$run" = run ]; then "$@"; fi
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0

HOST="${1:-}"
case "$HOST" in ''|-*) usage ;; esac
if dispatch check "$HOST"; then usage; fi
shift
MODE="${1:-status}"; [ $# -gt 0 ] && shift
dispatch run "$MODE" "$@"
