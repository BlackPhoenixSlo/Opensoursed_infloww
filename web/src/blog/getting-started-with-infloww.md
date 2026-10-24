---
title: "Getting started with Inflowwww: a few commands from the README, then a browser"
description: "How to set up Inflowwww in five steps: the Quick start, the dashboard, the owner account, a creator's session, then chatters."
date: 2026-10-12
tags: ["product", "setup", "self-hosting"]
parodyOf: "getting-started-with-infloww"
parodyTitle: "How to set up Infloww in 5 steps"
parodyDate: "Feb 20, 2025"
image: "dashboard-combo.webp"
imageAlt: "Inflowwww dashboard on desktop and phone, with a demo agency's earnings for the month"
---

Inflowwww is set up in five steps, in this order: run the eight Quick start commands on the server, open the dashboard from your laptop, register the owner, capture a creator's session, invite the chatters. This is the README's Quick start and the [Help center's]({{ '/help/' | url }}) first login, with notes on what each step is for.

## 1. Run the Quick start on the server

You need Docker Engine 25 or newer with Compose 2.20 or newer; the healthchecks use `start_interval`, which older versions reject. A small VPS works, and so does a spare computer that stays on. On the server, run:

```bash
git clone {{ site.repo }}.git openinflowwww
cd openinflowwww

# openinflowwww-app joins the external network n8n_default; it must exist.
docker network create n8n_default

# Bind-mounted state files. They must exist as files, not directories.
echo '{"proxies": []}' > service/proxies.json
touch service/chatterly.db
mkdir -p service/sessions

# Without SHARE_TOKEN the share-link gate is off (sign-in is the only gate);
# without the session secrets every rebuild signs all users out.
cat > .env <<ENV
SHARE_TOKEN=$(openssl rand -hex 24)
SESSION_SECRET=$(openssl rand -hex 32)
CHATTER_SESSION_SECRET=$(openssl rand -hex 32)
ENV

docker compose up -d --build
```

The app container joins an external network called `n8n_default`, so it has to exist first (the network name comes from the maintainer's own Traefik setup; you don't need n8n). The proxies file and the database are bind-mounted, so they must exist as files, not directories. If Docker creates them for you, it creates folders and the relay will not start.

Optional extras for `.env`: `ADMIN_PASSWORD` (without it, founder-only actions return 503) and the LLM keys `DEEPSEEK_API_KEY`, `DEEPINFRA_API_KEY` and `ZAI_API_KEY`. The dashboard works without them. Keep this file out of chat logs and screenshots. The .env File™ (not actually trademarked) is the closest thing we have to an account page.

The last command starts three containers: `openinflowwww-relay` on 127.0.0.1:8787, `openinflowwww-app` on 127.0.0.1:3001, and `openinflowwww-autoheal`, which restarts services that fail their healthcheck.

## 2. Open the dashboard from your laptop

{% shot "dashboard.webp", "Inflowwww dashboard with the month's earnings by source, shifts and clocked-in employees", "The dashboard once creators are connected and selling. Demo data." %}

A server usually has no browser, and the app listens on 127.0.0.1 only. From your own computer, forward the port with `ssh -L 3001:127.0.0.1:3001 user@server`, then open `http://127.0.0.1:3001/?t=<SHARE_TOKEN>` in your browser. `grep SHARE_TOKEN .env` on the server prints the token; it is remembered after the first visit.

To give your chatters a normal web address later, someone technical sets up a domain behind a reverse proxy, or runs `docker compose --profile tunnel up -d` for a Cloudflare quick tunnel whose address changes on every restart; the tunnel is for trying it only. Both make the dashboard public, so read the [security notes]({{ '/help/#security' | url }}) first. If a page will not load after setup, [check OnlyFans and your stack in this order]({{ '/blog/onlyfans-down/' | url }}).

## 3. Register the owner

The first screen is Sign in / Register at `/login`. Register the owner account there first, before anyone else reaches the server. Ignore the installer link on the login screen; it points at an older setup.

## 4. Add your first creator

{% shot "creators.webp", "Creator roster with avatars, status and earnings for each creator", "The creator roster after a few months of adding creators. Demo data." %}

Inflowwww works from a captured OnlyFans web session, not a stored password. The creator needs Chrome on a computer, not a phone. They install the extension from the repository's `loginExtensionMulti/` folder (open `chrome://extensions`, turn on Developer mode, click Load unpacked and pick the folder you send them), log in on onlyfans.com, open Messages, click Copy curl, and send you the copied text over a channel they would trust with their password. No password is shared. The copied text is a live login to their account, so treat it like one.

You paste it under **Creators > Manage creators** (`/creators`), in the Paste cURL card, and click Bootstrap from cURL. The [Help center]({{ '/help/#capture' | url }}) has the full capture steps. If the creator should appear from a fixed location, add a proxy in **Creators > Custom proxy** (`/creators/proxy`) before pasting. The extension can capture a Fansly session too, but a Fansly client lives in the repo and the Docker image does not ship it yet. Plan a first install around OnlyFans accounts.

## 5. Invite your chatters

Invite each chatter from **Employees > Manage employees > Chatters** (`/employees`): under Invite a new chatter, **Mint invite URL** makes a one-time `/chatter-login?token=...` link, valid for 24 hours, and they pick a username and password there. Login is a share token for the dashboard plus per-user logins for the owner and each chatter (`/chatter-login`); [Running a team]({{ '/help/#team' | url }}) in the Help center covers the rest. Chatters never see the creator's OnlyFans password, because the relay holds a captured session, not the password.

Owner screens such as Vault Pro, Smart lists and Manage creators are hidden from chatter sessions; chatters attach media from the chat composer, limited to the vault folders the owner grants them. Shift schedule (`/employees/shifts`) is NotBuiltYet: the page is real, the feature is not.

## What's next

- Chat in **Messages Pro**.
- Sort content in **Growth > Vault Pro**.
- Write five replies in **Growth > Scripts**.
- After the first shift, read **Analytics > Employee reports** and the **Message dashboard**.
- For phones, open the server's URL; the web app is responsive. For a desktop window, the Electron shell in `desktop/` asks for your server URL on first launch.

> **The pitch.** That was the whole onboarding. One owner account to create, on your own server, and no plan to pick. [Deploy it yourself]({{ '/#deploy' | url }}).
