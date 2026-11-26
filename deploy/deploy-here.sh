#!/usr/bin/env bash
#
#
#
#
#
#

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/BlackPhoenixSlo/Opensoursed_infloww.git}"
BRANCH="${BRANCH:-main}"
DIR="${DIR:-$HOME/openinflowwww}"

say() { printf '\n\033[36m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# Files only: with no marker and no Cell this must print and call nothing (unset = byte-identical to before).
cell_mode_gate() {
  local root=/opt/oi mark cells="" d
  mark="$root/CELL-MODE"
  for d in "$root" "$root/shards"; do
    if [ -e "$d" ] || [ -L "$d" ]; then
      [ -d "$d" ] && [ -r "$d" ] && [ -x "$d" ] || die "refused: cannot inspect $d"
    fi
  done
  for d in "$root"/shards/*/; do
    [ -d "$d" ] || continue
    [ -r "$d" ] && [ -x "$d" ] || die "refused: cannot inspect ${d%/}"
    if [ -f "$d"override.yml ]; then
      cells="$cells $(basename "$d")"
    fi
  done
  if [ -e "$mark" ] && [ -n "$cells" ]; then
    die "refused: cell-mode marker $mark ($(head -c 200 "$mark" | tr '\n' ' ')); deploy Cells with: deploy/fleet/fleet.py deploy <box>"
  elif [ -e "$mark" ]; then
    die "refused (mixed): cell-mode marker $mark but no Cell under $root/shards; a human checks the box, then fleet.py deploy or removes the marker"
  elif [ -n "$cells" ]; then
    die "refused (mixed): Cells$cells under $root/shards but no marker $mark; deploy with: deploy/fleet/fleet.py deploy <box>"
  fi
}
cell_mode_gate
[ "${1:-}" = "--cell-mode-check" ] && { echo "cell-mode check: clear"; exit 0; }

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
gen_secret() { openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

if ! command -v docker >/dev/null; then
  say "installing Docker"
  curl -fsSL https://get.docker.com | $SUDO sh
fi
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing — install Docker Engine 20+ with the compose plugin"

command -v git >/dev/null || { say "installing git"; ($SUDO apt-get update -y && $SUDO apt-get install -y git) 2>/dev/null || $SUDO yum install -y git; }
if [ -d "$DIR/.git" ]; then
  say "updating $DIR"
  git -C "$DIR" fetch origin; git -C "$DIR" checkout "$BRANCH"; git -C "$DIR" pull --ff-only
else
  say "cloning $REPO_URL into $DIR (branch: $BRANCH)"
  git clone --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
cd "$DIR"

[ -f service/proxies.json ] || echo '{"proxies":[]}' > service/proxies.json
mkdir -p service/data service/sessions service/storyboard_cache
if [ -s service/chatterly.db ] && [ -e service/data/chatterly.db ]; then
  die "both service/chatterly.db and service/data/chatterly.db exist: keep the right one, move the other out of the way, re-run"
fi
if [ -s service/chatterly.db ]; then
  say "moving service/chatterly.db to service/data/ (one time)"
  cid=$(docker compose ps -aq openinflowwww-relay)
  if [ -n "$cid" ]; then
    docker exec "$cid" python3 -c 'import sqlite3; print("  checkpoint", sqlite3.connect("/app/service/chatterly.db", timeout=30).execute("pragma wal_checkpoint(TRUNCATE)").fetchone())' \
      || echo "  relay not running: no checkpoint"
    docker compose stop openinflowwww-relay
  fi
  # carry any WAL the old container still holds (relay replays it on start)
  rm -f service/data/chatterly.db-wal service/data/chatterly.db-shm
  mv service/chatterly.db service/data/chatterly.db && rm -f service/chatterly.db-shm service/chatterly.db-wal
  if [ -n "$cid" ] && docker cp "$cid:/app/service/chatterly.db-wal" service/data/chatterly.db-wal 2>/dev/null; then
    echo "  carried the old container's WAL"
  fi
fi

say "writing .env (secrets stay on this box, chmod 600)"
touch .env; chmod 600 .env
upsert() { local k="$1" v="$2"; [ -z "$v" ] && return 0
  if grep -q "^$k=" .env; then sed -i "s|^$k=.*|$k=$v|" .env; else printf '%s=%s\n' "$k" "$v" >> .env; fi; }
grep -q '^SESSION_SECRET=.\+'         .env || upsert SESSION_SECRET "$(gen_secret)"
grep -q '^CHATTER_SESSION_SECRET=.\+' .env || upsert CHATTER_SESSION_SECRET "$(gen_secret)"
# empty SHARE_TOKEN = friend-auth only
grep -q '^SHARE_TOKEN='               .env || echo 'SHARE_TOKEN=' >> .env
# VAPID key is minted by the relay on first use (service/secrets); never rotate it. Subject needs a real host (Apple refuses localhost)
if [ -n "${DOMAIN:-}" ] && ! grep -q '^VAPID_SUBJECT=.\+' .env; then upsert VAPID_SUBJECT "mailto:admin@$DOMAIN"; fi
[ -n "${DEEPSEEK_API_KEY:-}" ] && upsert DEEPSEEK_API_KEY "$DEEPSEEK_API_KEY"
grep -q '^DEEPSEEK_API_KEY=' .env || echo 'DEEPSEEK_API_KEY=' >> .env
echo "  .env keys: $(grep -oE '^[A-Z_]+' .env | tr '\n' ' ')"
grep -q '^DEEPSEEK_API_KEY=.\+' .env || echo "  note: no DeepSeek key yet — the dashboard works without one. Switch AI on at Setup → Your AI keys once your account is captured (this .env key covers only accounts with no owner)."

DOMAIN="${DOMAIN:-}"

# base compose attaches the app to external n8n_default; absent on a bare box, so create a stand-in or compose refuses to start
docker network inspect n8n_default >/dev/null 2>&1 || docker network create n8n_default >/dev/null 2>&1 || true

if [ -n "$DOMAIN" ]; then
  TNAME=$(docker ps --format '{{.Names}} {{.Image}}' | awk 'tolower($2) ~ /traefik/ {print $1; exit}')
  [ -z "$TNAME" ] && die "DOMAIN set but no Traefik container is running on this box. Omit DOMAIN to use the Cloudflare tunnel, or start Traefik first."
  TNET=$(docker inspect "$TNAME" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' 2>/dev/null | grep -vE '^bridge$|^$' | head -1)
  TNET="${TNET:-n8n_default}"
  CR=$(docker inspect "$TNAME" --format '{{json .Args}}' 2>/dev/null | grep -oE 'certificatesresolvers\.[A-Za-z0-9_-]+' | head -1 | cut -d. -f2)
  CR="${CR:-mytlschallenge}"
  say "routing the dashboard through Traefik '$TNAME' on https://$DOMAIN (network=$TNET, certresolver=$CR)"
  cat > docker-compose.override.yml <<YAML
services:
  openinflowwww-app:
    networks:
      - default
      - $TNET
    labels:
      traefik.enable: "true"
      traefik.docker.network: "$TNET"
      traefik.http.routers.openinflowwww.rule: "Host(\`$DOMAIN\`)"
      traefik.http.routers.openinflowwww.entrypoints: "websecure"
      traefik.http.routers.openinflowwww.tls.certresolver: "$CR"
      traefik.http.services.openinflowwww.loadbalancer.server.port: "3001"
  # The relay's own paths (same list as docker-compose.yml) go straight to it;
  # without this its router keeps the base file's placeholder host.
  openinflowwww-relay:
    networks:
      - default
      - $TNET
    labels:
      traefik.enable: "true"
      traefik.docker.network: "$TNET"
      traefik.http.routers.openinflowwww-relay.rule: "Host(\`$DOMAIN\`) && (PathPrefix(\`/api/of/\`) || (PathPrefix(\`/admin/\`) && !Path(\`/admin/manage\`)) || Path(\`/img\`) || PathPrefix(\`/img/\`) || Path(\`/events\`) || PathPrefix(\`/auth/\`) || PathPrefix(\`/chatter/\`))"
      traefik.http.routers.openinflowwww-relay.entrypoints: "websecure"
      traefik.http.routers.openinflowwww-relay.tls.certresolver: "$CR"
networks:
  $TNET:
    external: true
YAML
  say "docker compose up -d --build (first build takes a few minutes)"
  docker compose up -d --build --remove-orphans
  docker compose ps
  cat <<DONE

────────────────────────────────────────────────────────────
✓ OpenInfloww is live behind Traefik with a real TLS certificate.

  URL:  https://${DOMAIN}
  dir:  ${DIR}   branch: ${BRANCH}

If the page doesn't load yet:
  • confirm ${DOMAIN} has a DNS A-record → this server's public IP
  • give Traefik ~30s to fetch the Let's Encrypt cert on first hit
  • check:  docker logs ${TNAME} 2>&1 | grep -iE "${DOMAIN}|certificate|error"

Connect an OnlyFans account: open the URL, then capture your session with the
Chrome extension in loginExtensionMulti/ (see its README).

Re-run to update:   DOMAIN=${DOMAIN} bash $DIR/deploy/deploy-here.sh
────────────────────────────────────────────────────────────
DONE
  exit 0
fi

if [ "${TUNNEL:-}" = "1" ]; then
  say "TUNNEL=1 → Cloudflare quick tunnel (random https url, changes on every restart)"
  cat > docker-compose.override.yml <<'YAML'
services:
  openinflowwww-app:
    labels:
      traefik.enable: "false"
  openinflowwww-relay:
    labels:
      traefik.enable: "false"
YAML
  say "docker compose --profile tunnel up -d --build (first build takes a few minutes)"
  docker compose --profile tunnel up -d --build --remove-orphans
  docker compose ps
  say "waiting for the Cloudflare tunnel URL"
  URL=""
  for _ in $(seq 1 30); do
    URL=$(docker logs openinflowwww-tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)
    [ -n "$URL" ] && break; printf '.'; sleep 4
  done; echo
  [ -z "$URL" ] && { echo "⚠ tunnel URL not seen yet. Check: docker logs -f openinflowwww-tunnel | grep trycloudflare"; exit 0; }
  cat <<DONE

────────────────────────────────────────────────────────────
✓ OpenInfloww is live (Cloudflare tunnel).

  URL:  ${URL}   ← random, changes every restart
  dir:  ${DIR}   branch: ${BRANCH}

Current URL anytime: docker logs openinflowwww-tunnel | grep trycloudflare | tail -1
Want a STABLE url?    DOMAIN=you.duckdns.org bash $DIR/deploy/deploy-here.sh
────────────────────────────────────────────────────────────
DONE
  exit 0
fi

PORT="${PORT:-3000}"
IP=$(curl -fsS https://api.ipify.org 2>/dev/null || curl -fsS https://ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
IP="${IP:-<this-server-ip>}"
say "exposing the dashboard on http://$IP:$PORT (plain http — see footer to add https)"
cat > docker-compose.override.yml <<YAML
services:
  openinflowwww-app:
    ports:
      - "0.0.0.0:$PORT:3001"
    labels:
      traefik.enable: "false"
  openinflowwww-relay:
    labels:
      traefik.enable: "false"
YAML
say "docker compose up -d --build (first build takes a few minutes)"
docker compose up -d --build --remove-orphans
docker compose ps
cat <<DONE

────────────────────────────────────────────────────────────
✓ OpenInfloww is live on this server.

  URL:  http://$IP:$PORT
  dir:  $DIR   branch: $BRANCH

  ⚠ plain http (no encryption). If the page won't open, allow the port in your
    firewall:   ufw allow $PORT/tcp    (or your VPS provider's firewall panel)

Connect an OnlyFans account: open the URL, then capture your session with the
Chrome extension in loginExtensionMulti/ (see its README).

── upgrade to a secure, permanent https url (free or cheap) ─────────────────
  1) Free DuckDNS subdomain (recommended): create one at https://www.duckdns.org,
     point it at $IP, then re-run:
        DOMAIN=yourname.duckdns.org bash $DIR/deploy/deploy-here.sh
  2) Your own domain: add a DNS A-record → $IP, then re-run:
        DOMAIN=app.yourdomain.com bash $DIR/deploy/deploy-here.sh
  (both route through the box's Traefik — every Hostinger n8n template has it.)
────────────────────────────────────────────────────────────
DONE
