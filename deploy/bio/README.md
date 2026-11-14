# Bio pages: path mode on every box (default), own host optional

Each box serves its own bio pages (`service/bio_pages`, compose service `openinflowwww-bio`, on by default).

**Path mode (default, no DNS).** The app rewrites `/p/*` to the bio service (`BIO_URL`, compose default
`http://openinflowwww-bio:8788`, baked in at app build), and the bio service (`BIO_PATH_PREFIX`, compose default `/p`)
serves `<app host>/p/<username>` with every URL on the page under `/p`. Set `BIO_PUBLIC_URL=https://<app host>/p` so
the editor links there. A plain `docker compose up -d --build` builds and starts it; AE's targeted
`up -d --no-deps <services>` starts it only when `openinflowwww-bio` (and `openinflowwww-app`, for the rewrite) is
named. The overrides must name the bio image (§3). Bot check: with `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` in
`.env`, a Link with `bot_check` (new Links' default) Reveals only after Cloudflare Turnstile passes; unset = no check.
Fleet shards (`deploy/fleet`) keep it off (their override profiles it out: it would mount the wrong data dir and
oi-epoch does not fence it).

**Host mode (optional, the rest of this file).** The same service on its own host (`new.ofl.ink`, `ofl.ink` at
cutover) through the box's Traefik; any path outside `/p` is host mode, so both work at once. TLS ends at Traefik
(resolver `letsencrypt`). Nothing on `ofl.ink` changes here: `ofl.ink` keeps going to oflinkv2 until the cutover
runbook (PR3b) swaps it. The editor (relay `/admin/bio-pages`) links to `BIO_PUBLIC_URL/<username>` and shows
"serving" once the relay reaches the bio service (`BIO_HEALTH_URL`; compose default
`http://openinflowwww-bio:8788/internal/healthz`).

Labels: [m] measured (read), [i] inferred, [g] guess. Never run any of this against your-host.example.com.

## Per box

| | public | AE |
|---|---|---|
| bio host | `new.ofl.ink` (**owner to confirm**, Q1; kept as a primary host after the flip) | `ae.ofl.ink` (**owner to confirm**, Q2) |
| `BIO_PORT` (host, loopback) | `8790` [g] | `8798` [g] |
| compose project | `opensource` | `ae` |
| Traefik route file | `/root/traefik-dynamic/bio-opensource.yml` | `/root/traefik-dynamic/bio-ae.yml` |

The compose bio block publishes no host port (8788 is the AE relay's host port): host mode adds
`127.0.0.1:${BIO_PORT}:8788` in the override (§3). The block's `image: openinflowwww-relay:latest` is not the
hosts' retagged relay image, so the override names the image [m] (path mode too).
On each box, check the chosen port is free with `ss -ltn` before deploying.

## 1. DNS (owner)

- public: `new.ofl.ink  A  <the public box IP>`
- AE: `ae.ofl.ink  A  187.126.20.230`

No AAAA (unless the box's Traefik listens on v6). Check: `dig +short new.ofl.ink` = the box IP. LE's HTTP-01
challenge needs the record live before step 5.

## 2. `.env` keys

```
BIO_PORT=8790                                   # AE: 8798
BIO_PRIMARY_HOSTS=ofl.ink,www.ofl.ink,v2.ofl.ink,new.ofl.ink   # AE: ae.ofl.ink
BIO_PUBLIC_URL=https://new.ofl.ink              # AE: https://ae.ofl.ink
BIO_ESCAPE_TAP=...                              # PR-E's default; leave as that PR says
```

`BIO_PRIMARY_HOSTS` on public already lists `ofl.ink`: harmless before the flip, Traefik still sends `ofl.ink` to
:8080. `BIO_HEALTH_URL` stays unset (the compose default reaches the bio service on the project network).
On AE, the `.env` change goes through ae-deploy's env-change path (§1 of `.claude/skills/ae-deploy/SKILL.md`).

## 3. Override (host `docker-compose.override.yml`, back it up first)

```yaml
services:
  openinflowwww-bio:
    image: opensource-relay:latest     # AE: the relay image name its override uses
    container_name: opensource-bio     # AE: ae-bio
    ports: ["127.0.0.1:${BIO_PORT}:8788"]   # host mode only
```

Check: `docker compose config openinflowwww-bio | grep -E "image|container_name|published|DATABASE_URL"` shows
the image, the name, `127.0.0.1` + `BIO_PORT`, and the same DB file as the relay.

## 4. Route file

Read the entrypoint and resolver names Traefik already uses (read only):

```bash
grep -nE "entryPoints|certResolver" -A2 /root/traefik-dynamic/oflink.yml     # AE: ae.yml
```

Set `P`, `H`, and `PORT` from the table. Set `EP` and `CR` from the box's existing route file. A duplicate
router or service name may make Traefik keep another file's definition [m reviewer, Traefik v3.3]. The check
reads every file Traefik loads (`.yml`/`.yaml`/`.toml`, subdirectories too); only the own installed file is
excluded, so a rerun (or a leftover `.bio-$P.yml.tmp`) passes and a stale copy elsewhere stops it. Names start
with `bio-`.

```bash
P=opensource H=new.ofl.ink PORT=8790 EP=websecure CR=letsencrypt  # AE: P=ae H=ae.ofl.ink PORT=8798; read EP/CR
collisions=$(grep -rl --include='*.yml' --include='*.yaml' --include='*.toml' "bio-$P" /root/traefik-dynamic |
  grep -vxF "/root/traefik-dynamic/bio-$P.yml" || true)
test -z "$collisions" || { echo "bio route name collision: $collisions" >&2; exit 1; }
cat > "/root/traefik-dynamic/.bio-$P.yml.tmp" <<YAML
http:
  routers:
    bio-$P:
      rule: "Host(\`$H\`)"
      entryPoints: [$EP]
      tls:
        certResolver: $CR
      service: bio-$P
  services:
    bio-$P:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:$PORT"
YAML
grep -q "bio-$P" "/root/traefik-dynamic/.bio-$P.yml.tmp" && \
  test -s "/root/traefik-dynamic/.bio-$P.yml.tmp" && \
  mv "/root/traefik-dynamic/.bio-$P.yml.tmp" "/root/traefik-dynamic/bio-$P.yml"
```

The file defines one TLS router and service, with no retry middleware. Traefik reloads it by itself; check
`docker logs <traefik> --since 5m | grep -iE "error|bio-"` is clean.

## 5. Deploy and verify

Back up `service/bio_files` and the DB first (public-sync §6 / ae-backup). Then the relay is recreated for the
`BIO_HEALTH_URL` default (1-3 min app downtime [i ae-deploy]) and the bio service started (public):

```bash
docker compose up -d openinflowwww-relay openinflowwww-bio
```

On AE, this recreate is ae-deploy §2's relay path (fence gate, backup, checkpoint, stop) with `<services>` = `openinflowwww-relay openinflowwww-bio`, whatever `dry-run.sh needs` printed (it lists neither bio keys nor the bio block, so it says `services: none`).

Verify:
- `docker ps --format "{{.Names}} {{.Status}}" | grep -- -bio` → `(healthy)`.
- `curl -fsS https://new.ofl.ink/internal/healthz` → 200, empty body, LE cert (`curl -v` shows the issuer).
- `curl -sI http://new.ofl.ink/` → a redirect to https. If not, file a follow-up (no web router here).
- Editor (Growth → Tracking links → Bio pages) says serving and shows `https://new.ofl.ink/<username>`; open one
  page on a phone.
- Limiter: if `.env` sets `TRUSTED_PROXIES`, it must cover the `<project>_default` network gateway
  (`docker network inspect <project>_default`), else every visitor shares one limiter key [i]. Functional check: a
  test page, exceed the ping limit from the laptop (429), then ping from the box (204); delete the test page.
- Recreate gap: a curl loop every 0.2 s on `/internal/healthz` during
  `docker compose up -d --force-recreate openinflowwww-bio`; record the longest gap (target ≤ 5 s [g]).
- After each box ships: append a `bio_counter_loss` line to that sweep's WATCH.md (CLAUDE.md "Post-deploy
  watch"). The bio container name derives from the relay name (`<relay minus -relay>-bio`).

## Short address (optional)

`BIO_SHORT_URL` (e.g. `https://ofl.ink/s`) makes the editor show `<BIO_SHORT_URL>/<username>` as "Short" next to the
long address. The short host only redirects: a Traefik file router (public: `/root/traefik-dynamic/ofl-short.yml`,
router `ofl-short`, `Host(ofl.ink|www.ofl.ink|v2.ofl.ink) && PathPrefix(/s/)`, priority 1000 over `oflink`, a
`redirectRegex` middleware `^https?://[^/]+/s/(.*)$` → `https://bio.inflowwww.com/${1}`, 302, service
`noop@internal`). Every other ofl.ink path stays on oflinkv2. Recreate the relay after setting the key. Rollback:
`rm /root/traefik-dynamic/ofl-short.yml` and unset the key.

## Custom domains (editor-driven)

A page's own domain (`links.example.com` → that one page) is set in the editor's "Use your own domain" card (relay
`PUT/DELETE /admin/bio-pages/{pid}/domain`, `POST …/domain/check`; `service/bio_pages/domains.py`), ofl.ink v2's
flow and checks. Status: `pending` (saved; serves nothing) → `pending_cert` once the check (DNS over HTTPS, Cloudflare)
sees TXT `_oflink.<domain>` = `oflink-verify=<token>` (v2's record, so a domain verified there keeps its TXT name), at
least one A and every A = `BIO_SERVER_IP`, every AAAA = `BIO_SERVER_IPV6` (none is fine), and no CAA refusing
letsencrypt.org → `live` once
`https://<domain>/internal/healthz` answers 200 with a valid certificate. The bio service serves `pending_cert` and
`live` hosts (the certificate's HTTP-01 challenge and the probe need it). Only one page may hold a domain past
`pending`; an account holds at most 10.

Install (per box, once; public box paths shown):

1. `.env`: `BIO_SERVER_IP=<the box's public IPv4>` (the address its Traefik answers on; optional
   `BIO_SERVER_IPV6` only if Traefik answers on v6 too), then recreate the relay
   (`docker compose up -d --no-deps openinflowwww-relay`). Unset = the editor shows no domain form.
2. Units (back up any old copies first):
   ```bash
   cp deploy/bio/bio-custom-domains.service deploy/bio/bio-custom-domains.timer /etc/systemd/system/
   systemctl daemon-reload && systemctl enable --now bio-custom-domains.timer
   ```
   The service runs `deploy/bio/sync-custom-domains.py` (stdlib python3) every minute: it reads
   `bio_custom_domains` read-only and writes `/root/traefik-dynamic/bio-custom-domains.yml` (one `websecure` router
   with `certResolver: letsencrypt` per `pending_cert`/`live` domain, all to `http://127.0.0.1:8791`, the bio
   service's host port; JSON, which Traefik reads as YAML). At most 5 new domains per run; no write when nothing
   changed. Another box edits the unit's flags (`--db`, `--out`, `--upstream`, `--env-file`).
3. Verify: `systemctl start bio-custom-domains.service; journalctl -u bio-custom-domains -n 5` (a `routers=` line on
   the first write), `cat /root/traefik-dynamic/bio-custom-domains.yml` (`{}` with no domains), and
   `docker logs traefik-traefik-1 --since 5m | grep -i error` clean.

DNS drift: the timer re-resolves each routed domain's A record hourly; one that has not named `BIO_SERVER_IP` for
24 h loses its router (logged `dropped_dns=`), and gets it back once it resolves here again. The row stays as it is
(the timer never writes the DB); the owner checks or removes it in the editor.

Rollback: `systemctl disable --now bio-custom-domains.timer`, `rm /root/traefik-dynamic/bio-custom-domains.yml`
(Traefik drops the routers), unset `BIO_SERVER_IP` and recreate the relay. Rows stay in the DB.

## Every deploy

- When the relay image is rebuilt or the bio block/env changes, run `docker compose up -d --no-build
  openinflowwww-bio` on bio boxes (AE: ae-deploy §2 with `openinflowwww-bio` added to `<services>`).
- On `:prev` rollback, roll the bio service back to the previous relay image too; verify its container is
  healthy and `curl -fsS https://<bio host>/internal/healthz` succeeds.

## Rollback

1. Remove `BIO_PUBLIC_URL` and the other bio keys from `.env` (on AE through ae-deploy's env-change path, §1).
   Remove the bio override block.
2. Recreate the relay to apply the removed URL (public: `docker compose up -d openinflowwww-relay`; AE: ae-deploy
   §2's relay path with `<services>` = `openinflowwww-relay` whatever `needs` printed; 1-3 min app downtime
   [i ae-deploy]); the editor then shows no public URL. Bio rows
   stay in the DB.
3. `rm /root/traefik-dynamic/bio-<project>.yml`, then `docker compose stop openinflowwww-bio`.
4. Remove this box's `bio_counter_loss` line from its sweep's WATCH.md. The DNS record can stay; without a
   route Traefik answers 404 with its default cert.
