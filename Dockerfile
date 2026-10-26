# syntax=docker/dockerfile:1.6
#
# OF Relay — runtime image (Python).
#
# Mirrors what `./scripts/start.sh` boots natively as `venv/bin/uvicorn
# service.server:app`, but inside a container so the same artefact runs on
# your laptop, on a $5/mo VPS (Hetzner / DO / Vultr), or on Railway/Fly.
#
# Companion image: app/Dockerfile builds the Next.js /inbox UI.
# Wired together in docker-compose.yml at the repo root.
#
# What is NOT included: a browser (no Chromium), capture scripts, the dev
# `--reload` watcher. Auth state arrives via the loginExtensionMulti
# paste-curl flow, or the served Browserbase login (service/remote_login.py),
# which drives a REMOTE browser over CDP with the playwright client only.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl_cffi ships pre-built libcurl-impersonate wheels for linux/amd64 +
# linux/arm64, so no compiler toolchain is needed. ca-certificates is for
# OF + proxy TLS verification. curl backs the HEALTHCHECK below. ffmpeg
# (+ ffprobe) is used by the vault-thumbnail extractor in server.py to
# pull 12 frames out of source mp4s when the UI's VaultPicker hovers a
# video tile.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so the layer caches across code edits.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the whole service package in one shot. The synced tree is already
# curated: dev/live-test drivers (_drive_*/_test_*/_send_*), capture scripts,
# the test suite, secrets (.session_secret/.chatter_secret) and *.db files are
# all excluded by the deploy filter and .dockerignore.
#
# ⚠️ DO NOT go back to a per-file allowlist. One lived here and crashed boot
# every time a new module landed; the deploy repo replaced it with this single
# COPY, that fix was never back-ported, and on 2026-08-21 the first commit to
# touch this file synced the allowlist back over it — server.py imports 32
# modules it did not list, so the relay died on `ModuleNotFoundError:
# account_health` and took the app container down with it. The whole automations engine
# (automation_executor, webhook_dispatch, funnels_api, the automations/ package)
# has to be in the image, and an allowlist cannot keep up with that by hand.
COPY service/ service/
# The Fansly runtime. service/fansly_backend.py puts HERE.parent/"fansly" (i.e.
# /app/fansly) on sys.path and imports fansly_client / fansly_shim from there;
# without it the Fansly backend can't load. Five explicit files, NEVER the
# whole folder: fansly/ also holds capture tooling, .har captures and
# sessions/session.json (a live auth token) — see .dockerignore.
COPY fansly/fansly_client.py fansly/fansly_shim.py fansly/fansly_signer.py \
     fansly/fansly_vault.py fansly/fansly_ws.py fansly/

# Persistent state lives outside the image so a rebuild never wipes your
# auth or your event history. Volume targets:
#   /app/service/sessions   — captured OF sessions (loginExtensionMulti output)
#   /app/service/proxies.json — proxy registry
#   /app/service/chatterly.db — SQLite event store (WAL + SHM created beside it)
RUN mkdir -p /app/service/sessions
# The login extension's interceptor, injected by the Browserbase login
# (remote_login.INTERCEPTOR_PATH) so its capture matches the extension's.
COPY loginExtensionMulti/interceptor.js loginExtensionMulti/

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8787/livez > /dev/null || exit 1

# On SIGTERM uvicorn waits for open connections before the app's shutdown hook
# runs, and a browser tab's /events stream never closes by itself: without a
# bound the hook never ran and `docker stop` ended in SIGKILL. 5 s, then the
# streams are cut and the hook drains the automation runs that claimed a send
# (automation_executor.drain, RELAY_DRAIN_S); the compose stop_grace_period
# covers both. An env var, so every `uvicorn` command in this image
# gets it.
ENV UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=5

# Single worker on purpose — SQLite write lock + the WebSocket pump is a
# module-level singleton. Production mode, no --reload.
CMD ["uvicorn", "service.server:app", "--host", "0.0.0.0", "--port", "8787"]
