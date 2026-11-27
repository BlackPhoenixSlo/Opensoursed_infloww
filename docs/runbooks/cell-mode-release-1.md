# Cell mode Release 1: AE moves from one relay to Cells on box A

Spec: `docs/spec/agency-scale-out/phase-04-release-1-live.md`. Tickets: 75 (this file), 119 shadow, 120 canary, 77 full cut, 78 relocation, 72/79 the 7-day proof.

AE stays on one Box, **box A** (today's KVM 8). Nothing here buys or touches another VM.

- **OWNER** = you. On the phone: decisions, the app, clicking through, saying "go". On the laptop: the steps marked OWNER RUNS.
- **AGENT** = a laptop session. It prepares files and reads output you paste back. It never reaches box A on its own.

Labels: **measured** = seen on a real run; **inferred** = follows from code or a measurement; **guess** = not measured.

## The plan on one screen

1. **Shadow (119).** Control and Cells start on box A from `.backup` copies, beside the live relay. Egress is closed, every write is refused, a banner says "shadow, read-only". You click through. No OnlyFans contact.
2. **Canary, wave 1 (120).** The 6 lowest-revenue models (ticket 120, list B, confirmed 2026-11-26) move out of the old relay into a small **Cell 2**. The old relay keeps everyone else.
3. **Full cut, wave 2 (77).** All other models move into **Cell 1**. The old relay container is removed and its data dir is renamed aside.
4. **Later (78).** Cell 2 relocates whole to a new slot on box A.
5. **After the demo (72, 79).** Days 1–7: one `cell-report` a day. Day 7: `cell-report --done`.

Demo done = both waves + post-cut green + the real-path check + the relocation. "2 Cells on one Box" proves the design, not 1,000 models (`phase-07-hold-1000.md`).

## Rules for every step

- **The laptop never holds the live DB.** It gets only a `sqlite3 .backup` copy, `proxies.json` (deleted after the plan) and the session-folder names.
- **The laptop never talks to OnlyFans and never sends.** Test sends happen in the app, by you, to the sandbox Fan you confirm that day. No Fan id is written in this file.
- **Every block that reaches box A starts with `need_owner go`.** It stops unless the owner's "go" is typed at the prompt.
- **No AE deploys from D-3 on.** The `CELL-MODE` marker makes `deploy-here.sh`, ae-deploy and deploy-all refuse box A (118). New code goes through `fleet.py deploy` once Cells run.
- **Never re-login a canary model on the old relay after wave 1.** It would give that model a second owner (`docs/cell-mode/p3-entry-cut-drill.md`). Wave 2 refuses it (`relogged:`), but only at wave 2.
- **The KVM4 standby is retired for AE from wave 1 on.** A restored standby would be a second owner of the moved models. Recovery is `fleet.py failover` / `fleet.py restore` from the bucket. Do not run `docs/runbooks/ae-failover-drill.md` after C-2.
- **One quiet hour per wave:** Tue 09:00–10:00 UTC (measured on the 2026-11-26 copy, ticket 66). W-3 re-checks it.

## How to run a block

Each step is one `sh` block. Copy it, save it under the step id, run that file:

```
pbpaste > /tmp/r1-step.sh && bash -euo pipefail /tmp/r1-step.sh
```

Never pipe a block into bash (`pbpaste | bash`): an inner `ssh` swallows the rest (measured 2026-10-28, `ae-kvm8-shadow-campaign.md`). Every block after S-1 starts by loading the helpers S-1 writes. Save each block's output; most blocks do it for you into `~/.config/openinfloww/release1/evidence/`.

`deploy/fleet/tests/release1-rehearsal.sh --lint-only` checks this file: every block passes `bash -n`, step ids in order, every step says what it leaves, no box address, no Fan id, owner go before box A, abort rule both ways, stages in order.

---

## Stage 0: T-7 d, a week before

**S-1. Laptop helpers.** (AGENT, 1 min, changes nothing)

```sh
REPO="$(git rev-parse --show-toplevel)"
R1="$HOME/.config/openinfloww/release1"
mkdir -p "$R1/evidence" "$R1/plan"
chmod 700 "$R1" "$R1/plan"
printf 'REPO="%s"\n' "$REPO" > "$R1/lib.sh"
cat >> "$R1/lib.sh" <<'EOF'
R1="$HOME/.config/openinfloww/release1"
EV="$R1/evidence"
PLAN="$R1/plan"
MAP="${OI_R1_MAP:-$REPO/deploy/fleet/fleet.toml}"
PY="$REPO/venv/bin/python"
FLEET() { nice -n 10 "$PY" "$REPO/deploy/fleet/fleet.py" --map "$MAP" "$@"; }
FLEETS() { nice -n 10 "$PY" "$REPO/deploy/fleet/fleet.py" --map "$PLAN/fleet-shadow.toml" "$@"; }
K="${OI_FLEET_KEY:-$HOME/.ssh/oi_fleet}"
if [ -f "$K" ]; then
  ssh() { command ssh -i "$K" "$@"; }
  scp() { command scp -i "$K" "$@"; }
fi
mapq() {
  [ -f "$MAP" ] || { echo ""; return 0; }
  "$PY" - "$MAP" "$1" <<'PY'
import sys, tomllib
m = tomllib.load(open(sys.argv[1], "rb"))
ec = m.get("entry_cut", {})
box = {b.get("name"): b for b in m.get("box", [])}.get(ec.get("box"), {})
print({"box": ec.get("box", ""), "checkout": ec.get("checkout", ""), "ip": box.get("ip", ""),
       "container": ec.get("container", "openinflowwww-relay"), "front": m.get("front", "")}[sys.argv[2]])
PY
}
SRC_BOX="$(mapq box)"; CK="$(mapq checkout)"; RELAY_C="$(mapq container)"; CONTROL="$(mapq front)"
BOX="root@$(mapq ip)"
need_owner() {
  printf '\nOWNER word for this step: "%s". Type it only once the owner said it: ' "$*" >/dev/tty
  read -r said </dev/tty
  [ "$said" = "$*" ] || { echo "no '$*' from the owner: stopped, nothing ran" >&2; exit 1; }
}
ask() {
  printf '%s: ' "$2" >/dev/tty
  read -r "$1" </dev/tty
  [ -n "${!1}" ] || { echo "empty answer: stopped" >&2; exit 1; }
  export "${1?}"
}
confirm_fan() {
  printf 'Sandbox Fan id, as the owner confirmed it in the app today: ' >/dev/tty
  read -r FAN_ID </dev/tty
  printf 'OWNER: is %s the sandbox Fan, not a real fan? type yes: ' "$FAN_ID" >/dev/tty
  read -r ok </dev/tty
  [ -n "$FAN_ID" ] && [ "$ok" = yes ] || { echo "Fan not confirmed: no send" >&2; exit 1; }
  export FAN_ID
}
keep() { tee "$EV/$1-$(date -u +%Y%m%dT%H%M%SZ).txt"; }
EOF
. "$R1/lib.sh"
echo "lib ok: map=$MAP source=${SRC_BOX:-unset} checkout=${CK:-unset} control=${CONTROL:-unset}"
```

Expect: `lib ok: map=...`. Run it from inside the repo checkout. Before W-1 the box values print `unset`; that is fine. `ssh`/`scp` use fleet's key (`~/.ssh/oi_fleet`, or `OI_FLEET_KEY`) when it exists.
Leaves: `~/.config/openinfloww/release1/lib.sh` (every later block loads it).

**W-1. Owner decisions and the fleet.toml frame.** (OWNER decides, AGENT writes, 20 min, changes nothing on box A)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
ask GRANT_AGE "OWNER: max Grant age (how long a sign-in grant may live, e.g. 12h)"
ask UPTIME "OWNER: Front-door uptime target (e.g. 99.5% a month)"
printf 'decided %s by owner: max_grant_age=%s front_door_uptime=%s\n' "$(date -u +%FT%TZ)" "$GRANT_AGE" "$UPTIME" | keep W-1-decisions
grep -nE '^(agency|sha|front|min_cell_proto) *=|^\[(entry_cut|preflight|bucket)\]|^\[\[box\]\]' "$MAP" || echo "fleet.toml frame missing: AGENT drafts it (keys below)"
```

Expect: your two answers saved, then the frame lines of `fleet.toml`.
The AGENT drafts the frame from `deploy/fleet/fleet.toml.example` and the code's real keys: top-level `agency`, `sha` (the release commit), `front` (Control's id), `generation` and `written_at` (W-3's `--toml` prints both); one `[[box]]` for box A with `ip`, `vm_id`, `provider_account` (OWNER copies them from hPanel); `[bucket]`; `[entry_cut]` with `box`, `checkout` (AE's checkout), `container`, `project`, `compose_file`, `relay_port`; `[preflight] proofs = ["docs/cell-mode/p3-entry-cut-drill.md"]`. No `[[shard]]` yet (W-5).
Leaves: `evidence/W-1-decisions-*.txt`; `fleet.toml` frame (the map every later step reads).

**W-2. DB copy on box A, then to the laptop.** (OWNER RUNS, 10 min. Reads the live DB only through `.backup`; never copies the live file)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
TS="$(date -u +%Y%m%dT%H%M%SZ)"
ssh -n "$BOX" "set -e; umask 077; mkdir -p /root/r1-copy
  nice -n 19 ionice -c3 sqlite3 '$CK/service/data/chatterly.db' \".backup /root/r1-copy/ae-copy-$TS.db\"
  sqlite3 -readonly /root/r1-copy/ae-copy-$TS.db 'pragma integrity_check'"
scp -q "$BOX:/root/r1-copy/ae-copy-$TS.db" "$PLAN/ae-copy-$TS.db"
scp -q "$BOX:$CK/service/proxies.json" "$PLAN/proxies.json"
ssh "$BOX" python3 - "$CK" > "$PLAN/sessions.txt" <<'PY'
import json, os, sys
root = os.path.join(sys.argv[1], "service", "sessions", "accounts")
for d in sorted(os.listdir(root)):
    try:
        p = json.load(open(os.path.join(root, d, "meta.json"))).get("platform") or "onlyfans"
    except (OSError, ValueError):
        p = ""
    print(f"{p}:{d}" if p else d)
PY
chmod 600 "$PLAN"/*
ssh -n "$BOX" "rm -f /root/r1-copy/ae-copy-$TS.db"
ls -l "$PLAN" | keep W-2-copy
```

Expect: `ok` (integrity), then three files in the plan folder. Budget: the 11-26 copy took about 11 s for the DB inside `ae-backup` (measured on the KVM 8, 2026-10-27); the scp depends on the line.
Leaves: `plan/ae-copy-<stamp>.db`, `plan/proxies.json`, `plan/sessions.txt` (W-3 reads all three).

**W-3. Grouping plan.** (AGENT, 2 min, laptop only, read-only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
DB="$(ls -1 "$PLAN"/ae-copy-*.db | tail -n1)"
ask CANARY_TOML "path of a fleet.toml whose canary Cell lists ticket 120's list B (66c used canary-b-current.toml)"
nice -n 10 "$PY" "$REPO/deploy/fleet/cell_plan.py" --db "$DB" --proxies "$PLAN/proxies.json" \
  --sessions "$PLAN/sessions.txt" --current "$CANARY_TOML" --toml > "$PLAN/plan.toml" 2> "$PLAN/plan.txt"
rm -f "$PLAN/proxies.json"
keep W-3-plan < "$PLAN/plan.txt"
```

Expect: the plan prints the quiet hour, one admission line per Creator, any cross-Cell S4S pair, 2 data Cells, and `restricted chatters on <=2 Cells` ok (66c: 21/21 admitted, quiet hour Tue 09:00–10:00 UTC, measured on the 11-26 copy).
Fix before going on: a Creator "not admitted" needs a proxy bound (or leaves the Agency); a cross-Cell S4S pair moves together; a Creator with no session folder (66b found 5) needs a login or removal, because wave 2 refuses an unplaced source Creator.
Leaves: `plan/plan.txt` (for you), `plan/plan.toml` (W-5 pastes it).

**W-4. Owner reads the Feature table and signs it.** (OWNER, 20 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
"$PY" -c 'import json, sys; t = json.load(open(sys.argv[1])); print("signed:", t.get("signed")); [print(k, v.get("state")) for k, v in sorted(t["features"].items()) if v.get("state") in ("off", "partial")]' "$REPO/service/cell_features.json"
```

Expect: the `off` and `partial` rows. You read them (`docs/cell-mode/release-1-features.md` explains each) and say yes in writing; the AGENT then writes the `signed {by, at, sha256}` block in a PR (ticket 21). `signed: None` blocks every pre-cut (69).
Leaves: `service/cell_features.json` with `signed` on main (pre-cut `features-signed` reads it).

**W-5. Owner applies the plan to fleet.toml.** (OWNER, 15 min, laptop only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
cp "$MAP" "$MAP.before-W5"
echo "1) paste into $MAP for wave 1: Control (no accounts) + the canary Cell (list B only), from $PLAN/plan.toml"
echo "2) save a copy of $MAP with ALL planned Cells as $PLAN/fleet-shadow.toml (the shadow runs every Cell)"
echo "press enter when both are saved"; read -r _ </dev/tty
FLEET render
FLEETS render --out "$PLAN/shadow-render"
```

Expect: both renders exit 0. For wave 1 the map holds only Control and the canary Cell (Cell 2); wave 1 refuses any other new Cell's accounts (`placed: new Cells list ..., not in this wave`). Cell 1's block waits for F-1.
Leaves: `fleet.toml` with Control + Cell 2 (`fleet.toml.before-W5` is the undo); `plan/fleet-shadow.toml` with every Cell (H-1, H-3, H-5 use it).

## Stage 0b: T-1 d, the day before

**D-1. Witness on the laptop.** (OWNER RUNS, 5 min. The Witness polls box A every minute and pages)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
line="* * * * * cd $REPO && nice -n 10 venv/bin/python deploy/fleet/fleet.py --map $MAP witness >> $EV/witness.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'fleet.py --map .* witness' || true; echo "$line" ) | crontab -
sleep 70
tail -n 3 "$EV/witness.log"
ssh -n "$BOX" 'stat -c "%y heartbeat" /var/lib/oi/witness-heartbeat'
```

Expect: a heartbeat time from the last 2 minutes (pre-cut prints `AMBER witness`: checked by hand, R8).
Leaves: the laptop crontab line, `evidence/witness.log`, `/var/lib/oi/witness-heartbeat` on box A.

**D-2. Standby bundle off.** (OWNER RUNS, 1 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ssh -n "$BOX" 'systemctl disable --now ae-backup.timer; systemctl is-enabled ae-backup.timer || true' | keep D-2-standby
```

Expect: `disabled`. From now on no hourly bundle runs, so the source backup ages; C-1 and F-1 take one by hand (ticket 70 finding).
Leaves: `ae-backup.timer` off (pre-cut `standby` reads it).

**D-3. Deploy refuse marker.** (OWNER RUNS, 1 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ssh -n "$BOX" 'mkdir -p /opt/oi; [ -e /opt/oi/CELL-MODE ] || printf "%s release-1 runbook D-3\n" "$(date -u +%FT%TZ)" > /opt/oi/CELL-MODE; cat /opt/oi/CELL-MODE'
ssh -n "$BOX" "cd '$CK' && bash deploy/deploy-here.sh --cell-mode-check; echo rc=\$?" | keep D-3-marker
```

Expect: the marker line, then a refusal naming the marker and `rc=` not 0.
`fleet.py` has the marker writer (`fleet.mark_cell_mode`) but no command calls it yet, so this step writes it by hand. Only a human removes it, and only if Release 1 is called off before C-2.
Leaves: `/opt/oi/CELL-MODE` on box A (pre-cut `marker` reads it).

## Stage 1: Shadow (119)

**H-1. Shadow up.** (OWNER RUNS, 10 min. Builds the release images on the laptop and loads them onto box A: this is the "image staged" step)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask SHADOW_HOST "shadow hostname (its own name and cookie scope, not AE's site)"
FLEETS shadow up --box "$SRC_BOX" --host "$SHADOW_HOST" --live-db "$CK/service/data/chatterly.db" --every 30 | keep H-1-shadow
```

Expect: one JSON line `{"shadow": ..., "cells": [...]}` listing every planned Cell (from `plan/fleet-shadow.toml`), so H-3 reads the full load. The live relay keeps its container id and keeps answering (measured in the 119 drill).
Leaves: shadow containers and `/opt/oi/shadow` on box A; the release images loaded (pre-cut `image` reads them).

**H-2. Owner clicks through.** (OWNER, phone, 15 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
ask SAW_BANNER "OWNER: banner 'shadow, read-only' with the copy age on every page? yes/no"
ask SEND_REFUSED "OWNER: a send or edit in the shadow was refused? yes/no"
ask INBOX_NOTE "OWNER: what the inbox/roster showed (119: empty by design, no session folders)"
printf 'banner=%s send_refused=%s inbox="%s"\n' "$SAW_BANNER" "$SEND_REFUSED" "$INBOX_NOTE" | keep H-2-clickthrough
```

Expect: `banner=yes send_refused=yes`. The inbox and roster list no Creators (measured in the 119 drill); that is the open owner call in ticket 119, not a failure.
Leaves: `evidence/H-2-clickthrough-*.txt`.

**H-3. RAM and disk on box A with the shadow running.** (OWNER RUNS, 2 min, read-only. Soft AMBER, not a blocker)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ssh -n "$BOX" "free -m | sed -n 2p
  df -m / /opt/oi '$CK' | tail -n +2
  du -sm '$CK/service'
  docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E '^($RELAY_C|shadow-)' || true
  cat /sys/fs/cgroup/system.slice/docker-\$(docker inspect -f '{{.Id}}' '$RELAY_C').scope/memory.peak 2>/dev/null || echo 'memory.peak unreadable: read the old relay peak by hand'" | keep H-3-ram-disk
```

Expect: write the numbers against 70's bars: free disk ≥ 3× `service/` (what pre-cut `disk` measures), MemAvailable ≥ 2× the old relay's peak (both guesses). Below a bar = **AMBER**: write it down and tell the owner; the pre-cut lines `disk` and `ram` decide at T-0.
Leaves: `evidence/H-3-ram-disk-*.txt` (C-1 compares).

**H-4. Pre-cut preflight, first run.** (OWNER RUNS, 3 min, read-only, sends one test page)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ssh -n "$BOX" 'systemctl start ae-backup; tail -n 1 /var/log/ae-backup.log'
FLEET preflight --stage pre-cut | keep H-4-precut || rc=$?; echo "exit=${rc:-0}"
ask PAGE_OK "OWNER: did the page 'OpenInfloww preflight test page ...' arrive on the phone? yes/no"
echo "test_page_arrived=$PAGE_OK" | keep H-4-page
```

Expect: `ok ae-<stamp>.tar.zst` (the timer is off since D-2, and pre-cut wants a bundle under 1 h old), then `exit=0`, no `RED` line; `AMBER spare`, `AMBER witness` and maybe `AMBER proxy-creds` are accepted for the demo (R8, R9). `test_page_arrived=yes`.
Leaves: `evidence/H-4-precut-*.txt`, `evidence/H-4-page-*.txt`.

**Go / no-go for Stage 1 → Stage 2 (OWNER):** go only if H-2 says `banner=yes send_refused=yes`, H-4 exited 0 with your test page arrived, and the live AE site worked all day.

**H-5. Shadow down.** (OWNER RUNS, 2 min. Frees RAM; the refresh timer must not race the cut)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
FLEETS shadow down --box "$SRC_BOX" | keep H-5-shadow-down
```

Expect: `shadow down on ...`. The release images stay loaded.
Leaves: box A without shadow containers; images still there for C-2.

## Stage 2: Canary, wave 1 (120)

Inside the quiet hour. Grey for wave 1 was 66 s in the drill, an upper bound (measured, `p3-entry-cut-drill.md`).

**C-1. Pre-cut again and a fresh source backup.** (OWNER RUNS, 5 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ssh -n "$BOX" 'systemctl start ae-backup; tail -n 1 /var/log/ae-backup.log'
FLEET preflight --stage pre-cut | keep C-1-precut || rc=$?; echo "exit=${rc:-0}"
ask PAGE_OK "OWNER: did today's test page arrive? yes/no"
echo "test_page_arrived=$PAGE_OK" | keep C-1-page
```

Expect: `ok ae-<stamp>.tar.zst`, then `exit=0` and `OK backup ... min old`. The bundle still goes to the KVM4 with sessions; that is why the KVM4 standby is retired from here on (Rules).
Leaves: `evidence/C-1-precut-*.txt`, `evidence/C-1-page-*.txt` (120's "pre-cut output saved").

**Go / no-go for Stage 2 (OWNER):** go only if C-1 exited 0, the page arrived, it is the quiet hour, and you have 60 min free.

**C-2. Wave 1: the canaries into Cell 2.** (OWNER RUNS, ~5 min plus grey)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask CANARIES "the 6 canaries from ticket 120 list B, as onlyfans:id,onlyfans:id,..."
FLEET entry-cut --accounts "$CANARIES" 2>&1 | keep C-2-cut
ls -1t "$HOME/.config/openinfloww/witness"/*/ops/entry-cut-*.jsonl | head -n1 | keep C-2-op
```

Expect: `entry cut wave 1: ...`, you type `entry-cut wave 1` at its prompt, then `entry cut entry-cut-<ts>-<pid>: done; wave 1: ... live`. Write down the op id. If it refuses (`entry-cut refused (nothing written)`), nothing changed: fix the named line and run C-1 again. If it stops part way, read Abort below before anything else.
`remote-login: ... pass --logins-checked`: check by hand that no remote-login job runs on the old relay, then re-run with `--logins-checked` added.
Leaves: the op journal `witness/<agency>/ops/entry-cut-*.jsonl` (post-cut and Abort read it); `evidence/C-2-op-*.txt`.

**C-3. Post-cut preflight.** (OWNER RUNS, 2 min, read-only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
FLEET preflight --stage post-cut | keep C-3-postcut || rc=$?; echo "exit=${rc:-0}"
```

Expect: `exit=0`: `PLACEMENT-OK` per Cell, release SHA, manifest v2 < 1 h, `fence-order` OK, the old relay's account list (read twice) without the canaries.
Leaves: `evidence/C-3-postcut-*.txt` (120's "post-cut output saved").

**C-4. No canary folder left in the old relay.** (OWNER RUNS, 1 min, read-only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask CANARIES "the same 6 canaries, onlyfans:id,..."
for a in $(echo "$CANARIES" | tr ',' ' '); do
  ssh -n "$BOX" "test -e '$CK/service/sessions/accounts/${a#*:}' && echo 'LEFT ${a#*:}' || echo 'gone ${a#*:}'"
done | keep C-4-folders
```

Expect: six `gone` lines, no `LEFT`.
Leaves: `evidence/C-4-folders-*.txt`.

**Real path for Cell 2.** Run R-1 to R-4 below with Cell 2 as the owning Cell. Then check that a grant edit is refused with a clear message (grants are frozen until wave 2, ticket 120).

**Go / no-go for Stage 2 → Stage 3 (OWNER):** go only if C-3 exited 0, C-4 shows six `gone`, R-1 to R-4 passed for Cell 2, and the canary models ran clean for the days you chose (watch first the canary ticket 120 names as peaking at 3 chatters).

## Stage 3: Full cut, wave 2 (77)

Inside the quiet hour. Grey for wave 2 was 16 s in the drill, an upper bound (measured).

**F-1. Cell 1 into fleet.toml, pre-cut again, fresh backup.** (OWNER RUNS, 10 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
cp "$MAP" "$MAP.before-F1"
echo "paste Cell 1's [[shard]] block from $PLAN/plan.toml (every Creator left) into $MAP, then press enter"; read -r _ </dev/tty
FLEET render
ssh -n "$BOX" 'systemctl start ae-backup; tail -n 1 /var/log/ae-backup.log'
FLEET preflight --stage pre-cut | keep F-1-precut || rc=$?; echo "exit=${rc:-0}"
ask PAGE_OK "OWNER: did today's test page arrive? yes/no"
echo "test_page_arrived=$PAGE_OK" | keep F-1-page
```

Expect: `render` 0, a fresh bundle, `exit=0`, page arrived. Before this step an outside check must watch the front-door hostname (site down = page, ticket 77); if none does yet, write it down as AMBER.
Leaves: `fleet.toml` with Cell 1 (`fleet.toml.before-F1` is the undo), `evidence/F-1-precut-*.txt`, `evidence/F-1-page-*.txt`.

**Go / no-go for Stage 3 (OWNER):** go only if F-1 exited 0, the page arrived, it is the quiet hour, no AE deploy is planned, and you have 60 min free.

**F-2. Wave 2: everyone else into Cell 1.** (OWNER RUNS, ~5 min plus grey)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
FLEET entry-cut 2>&1 | keep F-2-cut
ls -1t "$HOME/.config/openinfloww/witness"/*/ops/entry-cut-*.jsonl | head -n1 | keep F-2-op
```

Expect: `entry cut wave 2: ...`, you type `entry-cut wave 2`, then `... done; wave 2: ... live`. The old relay container is stopped and removed (two `docker inspect` reads), its data dir renamed to `data.entry-cut-aside/<op>`. Grey sits in the journal (`stop` to `live`).
Leaves: the wave-2 op journal; the aside data dir on box A (stays frozen until G-2 passes for every Cell).

**F-3. Post-cut preflight.** (OWNER RUNS, 2 min, read-only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
FLEET preflight --stage post-cut | keep F-3-postcut || rc=$?; echo "exit=${rc:-0}"
```

Expect: `exit=0`, including `fence-order` and the old relay container gone + data aside.
Leaves: `evidence/F-3-postcut-*.txt` (77's "post-cut output saved").

**F-4. Journal copy off the laptop.** (OWNER RUNS, 2 min. A lost laptop must not lose the fence proof, ticket 77)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
W="$HOME/.config/openinfloww/witness"
tar -C "$W" -czf "$EV/witness-journal-$(date -u +%Y%m%dT%H%M%SZ).tgz" .
ssh -n "$BOX" 'mkdir -p /root/r1-journal && chmod 700 /root/r1-journal'
scp -q "$(ls -1t "$EV"/witness-journal-*.tgz | head -n1)" "$BOX:/root/r1-journal/"
ls -l "$EV"/witness-journal-*.tgz | tail -n1 | keep F-4-journal
```

Expect: one archive, copied. Box A is not the bucket; ticket 77 wants the bucket too: the AGENT names the bucket upload in 77's PR if it is not built.
Leaves: `evidence/witness-journal-*.tgz` and its copy on box A.

## Real path (after C-2 for Cell 2, after F-2 for both Cells)

**R-1. Owner login and the All inbox.** (OWNER, phone and laptop, 5 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
ask LOGIN_OK "OWNER: logged in on AE's normal site with your usual login? yes/no"
ask ALL_INBOX "OWNER: the All inbox shows models from every Cell (canaries and the rest)? yes/no"
printf 'login=%s all_inbox=%s\n' "$LOGIN_OK" "$ALL_INBOX" | keep R-1-inbox
```

Expect: `login=yes all_inbox=yes`. Take a settled screenshot of the All inbox (desktop and phone).
Leaves: `evidence/R-1-inbox-*.txt` + the two screenshots in `evidence/`.

**R-2. Restricted test chatter.** (OWNER, 5 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
ask SEES_OWN "OWNER: the restricted test chatter sees exactly their Creators? yes/no"
ask SEES_OTHER "OWNER: does that chatter see any Creator from another Cell? yes/no"
printf 'sees_own=%s sees_other=%s\n' "$SEES_OWN" "$SEES_OTHER" | keep R-2-chatter
```

Expect: `sees_own=yes sees_other=no`, with a settled screenshot.
Leaves: `evidence/R-2-chatter-*.txt` + screenshot.

**R-3. One send per Cell to the sandbox Fan.** (OWNER sends in the app, 5 min per Cell)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
confirm_fan
ask CELL "Cell id that owns the model you send from"
ask SENT_AT "OWNER: sent one short message from that model to Fan $FAN_ID in the app; UTC time of the send"
printf 'cell=%s fan=%s sent_at=%s\n' "$CELL" "$FAN_ID" "$SENT_AT" | keep "R-3-send-$CELL"
```

Expect: you send by hand in the app, nothing is sent by this block. Settled screenshot of the chat after the send.
Leaves: `evidence/R-3-send-<cell>-*.txt` (R-4 reads the Fan id and Cell from you again).

**R-4. The `sent` row in the owning Cell.** (OWNER RUNS, 1 min per Cell, read-only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
confirm_fan
ask CELL "the same Cell id as R-3"
ssh -n "$BOX" "sqlite3 -readonly /opt/oi/shards/$CELL/data/chatterly.db \"SELECT account, kind, state, attempts, created_at FROM send_ops WHERE target LIKE '%$FAN_ID%' ORDER BY created_at DESC LIMIT 3\"" | keep "R-4-row-$CELL"
```

Expect: the newest row has `state` = `sent` and `attempts` = 1, in this Cell's DB only (`/opt/oi/shards/<cell dir>`; use the Cell's `dir` if it differs from its id).
Leaves: `evidence/R-4-row-<cell>-*.txt`.

## Go-live bookkeeping (after F-3)

**G-1. WATCH.md line (AE only).** (AGENT, 2 min, laptop only)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
grep -q '"cell_release_proof"' "$REPO/scripts/proxy-health/watch.py" || { echo "cell_release_proof not in WATCH_CHECKS yet: ticket 77 adds it first; stop"; exit 1; }
ask PR_URL "url of the go-live PR (ticket 77)"
printf -- '- r1-ae-cell-mode | added %s | expires +3d | cell_release_proof | AE Release 1 Cell mode live | %s\n' "$(date -u +%F)" "$PR_URL" >> "$HOME/oi-proxy-health/docs/proxy-health/WATCH.md"
tail -n 1 "$HOME/oi-proxy-health/docs/proxy-health/WATCH.md" | keep G-1-watch
```

Expect: the new line. The check needs `cell-report` (72); until both exist the block stops on purpose, because the 4 h sweep drops a line whose check is missing.
Leaves: one line in `WATCH.md` (the 4 h sweep runs it).

**G-2. Restore test per Cell, inside the cut hour.** (OWNER RUNS, ~10 min, guess)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask CELLS "every Cell's folder under /opt/oi/shards (its dir, else its id), space separated, Control first"
for c in $CELLS; do
  s=$(date +%s)
  ssh -n "$BOX" "/opt/oi/bin/oi-backup $c --drill" && r=ok || r=FAILED
  echo "$c drill=$r took=$(( $(date +%s) - s ))s"
done | keep G-2-restore
```

Expect: `drill=ok` for every Cell, and the total inside the quiet hour (no spare Box, so this is the only proof a Cell comes back). A `FAILED` Cell: keep the aside data dir frozen and tell the AGENT; do not relocate (M-1).
Leaves: `evidence/G-2-restore-*.txt`; `/var/lib/oi/<cell>.drill-ok` on box A. Only after every Cell is `ok` may the aside data dir be archived (not before).

## Later: relocate Cell 2 (78)

**M-1. Cell 2 moves whole to a new slot on box A.** (OWNER RUNS at a quiet hour, ~5 min. Steps and pre-move checks are ticket 78's; not built yet)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask CANARY_CELL "Cell 2's id"
ask SLOT "the new slot number on box A"
FLEET move "$CANARY_CELL" --to "$SRC_BOX/$SLOT" 2>&1 | keep M-1-move
```

Expect: the `cell` fence stops only the old Cell 2 instance; Control and Cell 1 keep sending (D3 = B). The journal gets one `move` op with `status: done`, equal per-account hashes and the grey. Then R-3/R-4 once more for Cell 2.
Leaves: the move op journal (`cell-report --done` reads it).

## After the demo: days 1–7 (72, 79; not built yet)

**Y-1. Daily report.** (OWNER RUNS, once a UTC day, 2 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask PAGE_OK "OWNER: did today's test page arrive? yes/no"
FLEET cell-report --page-received "$PAGE_OK" | keep Y-1-report || rc=$?; echo "exit=${rc:-0}"
```

Expect: one line per Cell plus a total, `exit=0`. A red day restarts the 7-day count. Path per the spec; until ticket 72 lands, `fleet.py` answers `invalid choice: 'cell-report'`.
Leaves: `/var/lib/oi-witness/<agency>/proof/<YYYY-MM-DD>.json` (Y-2 reads seven of them).

**Y-2. Day 7: Release 1 done?** (OWNER RUNS, 1 min)

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
FLEET cell-report --done | keep Y-2-done || rc=$?; echo "exit=${rc:-0}"
```

Expect: `exit=0` only for 7 green contiguous days, every Cell, every page confirmed, the M-1 move in the window. Then Fansly, then Fanvue, each by its own gate (80, 81).
Leaves: `evidence/Y-2-done-*.txt` (the Release 1 record).

---

## Abort

The **rollback boundary** of a wave is the moment `fleet.py` writes the new Cells' Owner epochs to the bucket (step `epoch` in the op journal).

**Before the rollback boundary: put the old relay back and start it.**

```sh
. "$HOME/.config/openinfloww/release1/lib.sh"
need_owner go
ask OP "the op id (entry-cut-...)"
FLEET abort "$OP" 2>&1 | keep abort
```

- Wave 1: the canary session folders go back into the old relay and it starts again. Anything written in Cell 2 is lost (accepted, ticket 120).
- Wave 2: the data dir is renamed back from `data.entry-cut-aside/<op>` and the old relay container starts again.
- Expect `entry cut ...: aborted (abort); the source is back up, hold cleared, Placement unchanged`. Then put back `fleet.toml.before-W5` (wave 1) or `fleet.toml.before-F1` (wave 2).

**After the rollback boundary: forward only, never merge.** `fleet.py abort` refuses (`abort refused: ... forward only`). Finish the cut with `fleet.py resume <op>`, then fix a bad Cell forward: `fleet.py failover <box>` or `fleet.py move <cell> --to <box>/<slot>`. Never copy Cells back into one relay, and never start the old relay over a Cell (ADR-0062; the marker blocks routine deploys).

If you are unsure which side you are on: run the abort block above. Before the boundary it undoes the cut (the safe way); after it, it refuses and names `resume`. Never run `fleet.py resume` to find out: it carries on straight away, past the boundary.

## Box A fault (AMBER, accepted for the demo)

There is no spare Box (pre-cut prints `AMBER spare`). A kernel or disk fault on box A takes **all of AE** down: old relay, Control and every Cell.

What you do then, by hand:

1. OWNER buys or picks a new box in hPanel and stops box A there, so it cannot come back as a second owner.
2. AGENT adds the new `[[box]]` to `fleet.toml` and bootstraps it (`deploy/fleet/bootstrap-box.sh`).
3. For every Cell, Control first: `fleet.py restore <cell> --to-box <new box> --typed-stop "stopped <box A vm_id>"`. It restores from the bucket, raises the epoch and deploys.
4. OWNER points AE's DNS at the new box; then the real path (R-1 to R-4).

Recovery time = bootstrap + one restore per Cell (G-2 measures a restore). A second Box would turn this into a normal failover (ticket 56, scale path).
