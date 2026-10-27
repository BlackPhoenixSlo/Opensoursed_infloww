# Run it on two boxes: primary + backup/standby

One VPS runs the stack. A second VPS receives an hourly backup and can take
over as a cold standby. A daily copy also goes to Google Drive. This guide
covers the setup, a failover, a failback, and an incident playbook. It is
written so an AI agent with shell access and only this file (plus the repo)
can operate it.

Placeholders:

| Placeholder | Meaning |
|---|---|
| `<PRIMARY_IP>` | the box that normally runs the stack |
| `<STANDBY_IP>` | the backup target and cold standby |
| `<DOMAIN>` | the public hostname (DNS A record → `<PRIMARY_IP>`) |
| `<APP_DIR>` | the checkout on each box, e.g. `/root/inflowwww` |

The primary and the standby can be different sizes. Set `RELAY_CPUS` /
`APP_CPUS` (in `.env`) to fit the smaller one: on 4 vCPU, `RELAY_CPUS=3.0
APP_CPUS=0.4`. Docker refuses a `cpus` above the core count.

## 1. You are the on-call agent

**The system.**
- **Relay** (`openinflowwww-relay`, Python): holds the OnlyFans sessions,
  ingests messages, runs automations and scheduled sends, and owns the SQLite DB
  `service/chatterly.db`.
- **App** (`openinflowwww-app`, Next.js): the UI. It proxies the relay's paths.
- Both run under Docker Compose behind Traefik (or any TLS proxy) on `<PRIMARY_IP>`.

**Safety rules:**
1. **Never run two relays on the same OnlyFans sessions.** Both would pump and
   both would send. The stack runs on the primary or the standby, never on both.
   The boot fence (section 5) enforces this when a box powers on. Before a
   failover, a human stops the primary in the provider's panel.
2. **Back up the DB in-container before any change** (section 2). Only the DB
   file is bind-mounted; its WAL lives in the container, so the host file misses
   recent writes.
3. **Never `docker compose down` / `up --force-recreate` without a WAL
   checkpoint and a clean stop first** (section 2.3). `docker compose restart`
   keeps the container, so it is safe.
4. **A Creator with 401 / expired session is a normal OnlyFans state.** A human
   logs that Creator in again. Never patch sessions or the DB for it.
5. **Query the DB in-container, read-only:** `docker exec -i openinflowwww-relay python3`
   with `sqlite3.connect("file:/app/service/chatterly.db?mode=ro", uri=True)`.
6. **Leave everything else on the box alone:** other stacks, the proxy's own config.

## 2. Hourly backup to the standby

### 2.1 What a bundle is

`bundle-<UTC stamp>.tar.zst` holds:
- the DB, copied **in-container** with SQLite's backup API, then
  `pragma integrity_check` = ok
- `service/sessions/`, `service/secrets/`, `service/proxies.json`
- `.env` and `docker-compose.override.yml`
- the proxy route for `<DOMAIN>`, and the live TLS cert, so the standby serves
  `<DOMAIN>` from its first request
- `manifest.json`: a sha256 per file, the git sha, and row counts

The core of the backup:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd <APP_DIR>
S=$(date -u +%Y%m%dT%H%M%SZ); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
docker exec -i openinflowwww-relay python3 - <<'EOF'
import sqlite3
s = sqlite3.connect("file:/app/service/chatterly.db?mode=ro", uri=True, timeout=60)
d = sqlite3.connect("/tmp/bk.db"); s.backup(d); d.close()
EOF
docker cp openinflowwww-relay:/tmp/bk.db "$T/chatterly.db" && docker exec openinflowwww-relay rm /tmp/bk.db
[ "$(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0])" "$T/chatterly.db")" = ok ]
tar -cf - -C "$T" chatterly.db -C <APP_DIR> service/sessions service/secrets service/proxies.json .env docker-compose.override.yml \
  | zstd -q -T2 -3 > /root/backups/hourly/bundle-$S.tar.zst
# --timeout: without it, a slow link hangs the run and blocks the next hourly one.
rsync -t --timeout=300 -e "ssh -i /root/.ssh/backup_standby -o BatchMode=yes -o ConnectTimeout=15" \
  /root/backups/hourly/bundle-$S.tar.zst root@<STANDBY_IP>:
date -u +%FT%TZ > /root/backups/last-ok
ls -1t /root/backups/hourly/bundle-*.tar.zst | tail -n +7 | xargs -r rm -f    # keep 6 locally
```

Run it from a systemd timer: `OnCalendar=hourly`, `RandomizedDelaySec=5m`,
`Persistent=true`. Give the service `Type=oneshot`, `Nice=10`,
`IOSchedulingClass=idle` and `TimeoutStartSec=45min`.

Measured on 1.5 GB of DB:
- the bundle is ~205 MB
- the DB copy takes ~11 s and one core
- the whole run takes ~60 s

### 2.2 The standby side: a write-only key

The standby's `/root/.ssh/authorized_keys` gets the primary's backup key. The
key can only write into the backup dir and has no shell:

```
restrict,command="/usr/bin/rrsync -wo -no-del /root/backups/hourly" ssh-ed25519 AAAA... backup@primary
```

To answer the fence's question as well (section 5), point `command=` at a
small wrapper instead. The wrapper:
- runs `rrsync` for `rsync --server ...`
- prints `active=yes` / `active=no` for `owner`
- refuses anything else

On the standby, rotate from cron: keep 48 hourly bundles, and hardlink the
first bundle of each UTC day into `daily/` (keep 30).

### 2.3 Checkpointed stop (before anything that recreates the relay)

```bash
cd <APP_DIR>
docker exec openinflowwww-relay python3 -c "import sqlite3; print(sqlite3.connect('/app/service/chatterly.db', timeout=30).execute('pragma wal_checkpoint(TRUNCATE)').fetchone())"   # (0, 0, 0)
docker compose stop openinflowwww-relay
docker cp openinflowwww-relay:/app/service/chatterly.db-wal service/chatterly.db-wal 2>/dev/null && echo "WAL left: fold it in"
```

A small WAL is often left (measured: 41 KB, written between the checkpoint and
the stop). Fold it in on the host, then recreate:

```bash
rm -f service/chatterly.db-shm
python3 -c "import sqlite3; print(sqlite3.connect('service/chatterly.db').execute('pragma wal_checkpoint(TRUNCATE)').fetchone())"
```

### 2.4 Staleness check

A second timer at :15 and :45 fails when `/root/backups/last-ok`, or the
standby's newest bundle, is older than 2 h. It then shows in
`systemctl --failed`. Add an outside HTTP monitor on `https://<DOMAIN>/login`
too: without one, the people using the site are the only alert.

## 3. Daily copy to Google Drive (rclone)

On the primary:
- rclone remote `gdrive`, scope `drive.file` (rclone sees only the files it
  created, not the whole Drive)
- a daily timer (e.g. 03:30 UTC) that copies today's first bundle and prunes
  copies older than 30 days:

```bash
rclone copy /root/backups/hourly/<today's first bundle> gdrive:backups/
rclone delete --min-age 30d gdrive:backups/
```

**Linking the Drive (one command, run on your laptop).** The primary has no
browser, so the Google login runs on the laptop. The second argument is
rclone's base64 config blob for `{"scope":"drive.file"}`:

```bash
rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlLmZpbGUifQ" | sed -n '/^{/p' \
  | ssh root@<PRIMARY_IP> 'read -r T; rclone config create gdrive drive scope=drive.file token="$T" >/dev/null && rclone lsd gdrive: && echo LINKED'
```

- The token travels over ssh's stdin. It never lands on a command line or on screen.
- Newer rclone versions may print the token as base64 between `--->` and
  `<---End paste` rather than as a JSON line. Decode it to the JSON first.
- If the browser does not open, rclone prints the link to click.
- Run it again whenever the daily log says `invalid_grant` / token expired.

## 4. Standby images

A failover should not wait on a build: a full build on a 4-core standby takes
10+ min (guess). After every deploy, copy the primary's images to the standby
and tag them with the git sha:

```bash
ssh root@<PRIMARY_IP> 'docker save openinflowwww-relay:latest openinflowwww-app:latest | zstd -q -T2' \
  | ssh root@<STANDBY_IP> 'zstd -q -d | docker load'
```

Measured: 106 s, with every other site on the standby still answering.

Then tag them `:<sha12>` on the standby. Pin them against `docker image prune`
by creating (never starting) a container from each:
`docker create --name standby-relay openinflowwww-relay:<sha12>`.

## 5. The boot fence (the double-relay guard)

A oneshot unit on the **primary** runs `Before=docker.service`
(`WantedBy=docker.service`, `TimeoutStartSec=300`). On every power-on it
decides:

1. If `/root/FENCED` exists, it stays fenced. The marker is sticky until a
   human clears it.
2. Otherwise it asks the standby `owner` over the backup key:
   - `active=yes` means the stack runs there: fence.
   - `active=no` means start as usual.
   - No answer for 240 s: fence (it fails closed).
3. **Fenced:** write `"RestartPolicy": {"Name": "no"}` into the relay's and the
   app's `/var/lib/docker/containers/<id>/hostconfig.json` while dockerd is still
   down, and write the marker. dockerd then leaves both stopped. Other containers
   start normally.

A second unit runs `After=docker.service`. If the box is fenced and either
container runs anyway, it stops them and logs a warning.

`clear` (failback):
- refuses while the standby says `active=yes`
- removes the marker
- puts `restart=unless-stopped` back on the containers that exist (after a
  `compose down` there are none, and that is fine)

What it does **not** cover:
- **A primary that never went down** (network split, hung box): it never boots,
  so the fence never runs. A human must stop it in the provider's panel before
  the standby starts the stack.
- **Anyone running `docker compose up` on a fenced primary.**

## 6. Failover (the primary is gone)

1. **Human:** stop the primary in the provider's panel, even if it looks dead.
2. On the standby, claim the stack:
   `echo "$(date -u +%FT%TZ) failover" > /root/active-here`. That file makes
   `owner` answer `active=yes`.
3. Extract the newest bundle into a scratch dir.
   - Check every sha256 against `manifest.json`, `integrity_check` = ok, and the
     row counts against the manifest.
   - If the standby is lost too, `rclone copy gdrive:backups/<bundle> .`
4. In `<APP_DIR>` on the standby:
   1. `git checkout --detach <bundle's git sha>`.
   2. Move the standby's own `.env` / override / DB aside.
   3. Copy in the DB (drop any `-wal`/`-shm`), sessions, secrets, proxies,
      `.env`, and an override sized for this box.
5. **Hold the sends that came due since the bundle.** The old primary may
   already have made them. Dry-run the query first, then run the update:
   ```sql
   update scheduled_jobs set status='error', last_error='failover-hold <STAMP>'
    where status='pending' and kind != 'scrape_chats' and run_at > '<STAMP_ISO>' and run_at <= '<NOW_ISO>';
   pragma wal_checkpoint(TRUNCATE);
   ```
6. Start from the standby images:
   `docker tag openinflowwww-relay:<sha12> openinflowwww-relay:latest` (same for the app),
   then `docker compose up -d --no-build --force-recreate`, then wait for `(healthy)`.
7. Put the bundle's cert and route into the proxy. Check:
   `curl --resolve <DOMAIN>:443:127.0.0.1 https://<DOMAIN>/login` → 200, verify 0.
8. **Human:** point `<DOMAIN>`'s A record(s) at `<STANDBY_IP>` (TTL 300).
   - If nobody can change DNS, keep a second hostname whose DNS already points
     at the standby (normally a redirect to `<DOMAIN>`) and switch its route to
     the stack. That is the emergency door.

Data loss: writes after the bundle's stamp, at most ~65 min (hourly + jitter +
run). Messages that fans sent in the gap are still on OnlyFans.

## 7. Failback

1. **Human:** start the primary. The fence keeps the stack down: the log says
   `boot: FENCED ...`, and both containers are `running=false`.
2. On the standby, do a checkpointed stop (2.3) and fold in any WAL left behind.
   Then `docker update --restart=no` on both containers.
3. Copy the standby's DB, sessions, secrets and proxies to a staging dir on the
   primary through a compressed pipe:
   `tar -cf - ... | zstd -T3 -3 | ssh <PRIMARY_IP> 'zstd -d | tar -xf - -C /root/failback'`.
   Uncompressed it took ~10 min for 1.56 GB. Compare the sha256 on both ends and
   run `integrity_check`.
4. `rm /root/active-here` on the standby.
5. On the primary:
   1. `docker compose down`. This drops the stale containers and any WAL left in them.
   2. Keep the current files aside.
   3. Copy the staging files in.
   4. Clear the fence, then `docker compose up -d --no-build`.
6. While DNS moves back, the standby's proxy forwards `<DOMAIN>` to
   `https://<PRIMARY_IP>` (a bridge route). **Human:** point DNS back.
   Remove the bridge ~30 min later.

## 8. Example timings (one measured drill)

These come from one run, so read them as examples: 5 Creators, ~250k
messages, a 1.5 GB DB.

| Step | Measured |
|---|---|
| Hourly bundle | 205 MB in 59 s (DB copy 11 s) |
| Restore + verification (30 files, integrity, counts) | 38 s |
| Crash → healthy on the standby (fresh bundle, standby images) | 1 min 43 s |
| Inbound messages ingested on the standby, first 6 min | 351 |
| Standby image copy | 106 s |
| Standby load during the rehearsal | load1 peak 1.87; neighbour sites p50 33-64 ms, all 200 |
| Public downtime when nobody could change DNS | 31 min (served on the emergency door meanwhile) |
| Failback copy uncompressed (use zstd) | ~10 min for 1.56 GB |

The lesson: the restore takes minutes, while DNS access decides the downtime.
Make sure whoever is on call can change the A record, or keep the emergency door.

## 9. Incident playbook

For each incident: symptom → diagnose → fix → verify. Commands run on the
primary unless marked.

| Symptom | Diagnose | Fix | Verify |
|---|---|---|---|
| Site 502 / timeout | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/login` (app); `curl -s http://127.0.0.1:8787/livez` (relay); `docker ps -a`; the proxy's logs; `openssl s_client -connect 127.0.0.1:443 -servername <DOMAIN> \| openssl x509 -noout -enddate` | App down: `docker compose restart openinflowwww-app`. Proxy down: start it. Cert expired: check port 80 reaches the box for ACME. ssh fails too: row "Primary unreachable" | `https://<DOMAIN>/login` → 200 |
| Relay unhealthy / restart loop | `docker inspect -f '{{.State.Health.Status}} {{.RestartCount}} oom={{.State.OOMKilled}}' openinflowwww-relay`; `docker logs --tail 200 openinflowwww-relay \| grep -iE 'error\|traceback'` | Booting < 3 min: wait. OOM: restart and raise the limit only with the owner. After a deploy: roll back (last row). Else `docker compose restart openinflowwww-relay` once | `(healthy)`, `/livez` 200, ingest lines in the log |
| High CPU / slow | `docker stats --no-stream`; `ps -eo pcpu,args --sort=-pcpu \| head` | The backup's DB copy (~1 core, ~11 s): wait. Relay pinned > 15 min: restart once | `/login` < 1 s |
| Disk full | `df -h /; docker system df; du -sh /root/backups/*` | `docker image prune -f`, `docker builder prune -f`, `journalctl --vacuum-size=500M`. Never delete `service/`, the bundles, or volumes | `df` < 80 % |
| DB locked / corrupt | `pragma quick_check` in-container (read-only) | Locked now and then: normal. Corrupt: **ask first** (a restore loses writes since the bundle). Then restore the newest bundle's DB after `compose down`, keeping the bad file | `quick_check` ok; counts ≈ manifest |
| Backups stale | the staleness check; `systemctl status <backup unit>`; its log | Unit stuck in `activating` with an `rsync` child: `systemctl kill` it and run it once more. Standby unreachable: tell the owner | check ok, newest < 2 h |
| Drive copy failing | `rclone lsd gdrive:` | `invalid_grant` / expired: rerun the one-command link (section 3) from a laptop with a browser | a new file in the Drive folder |
| Primary unreachable | `curl` + `ssh -o ConnectTimeout=10` from outside, again after 5 min | Back up but the stack is down: `fence status`. Marker or `active=yes`: ask. Standby unreachable at boot: clear only after confirming the standby runs nothing. Still down: failover (section 6) | probe 200 from the expected IP |
| A Creator disconnected | `docker logs --since 30m openinflowwww-relay \| grep -iE '401\|expired'` | A human logs the Creator in again in the app (normal OnlyFans state) | that Creator's ingest lines resume |
| Bad deploy | `git reflog -5` | Back up; `git reset --hard <PREV>`; `docker compose build`; checkpointed stop (2.3); `docker compose up -d --no-build`. The DB stays (boot migrations only add) | health checks above |

## 10. When to stop and ask the human

- **Anything that can lose data:** a DB restore, deleting under `service/` or the
  bundles, or recreating the relay with a WAL left.
- **Anything that could start a second relay:** a fence marker, `active=yes`, or
  not knowing where the stack is live.
- **Anything that needs a human login:** the provider's panel, DNS, an OnlyFans
  re-login, or the Google token.
- **Payments**, billing and API keys.
- **The same fix failing twice**, or a fix that needs a code change.
