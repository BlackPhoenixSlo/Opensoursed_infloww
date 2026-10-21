---
title: "Inflowwww announces no partnership with Fanvue. Here is what we support today."
description: "Inflowwww has no Fanvue integration and no partnerships; this is the plain list of what it supports today, platform by platform."
date: 2026-10-12
tags: ["platforms", "openinflowwww", "product-news"]
parodyOf: "infloww-fanvue-partnership"
parodyTitle: "Infloww announces official partnership with Fanvue"
parodyDate: "Apr 23, 2026"
---

Does Inflowwww integrate with Fanvue? No. We have no Fanvue integration and no partnerships with any platform. This post is the plain list of what the project does support today, so you can decide in five minutes whether it fits your roster.

## What we support: one platform, and one in the repo

**OnlyFans.** This is the core of the project. A Python relay (FastAPI) holds each captured OnlyFans web session and signs and replays its API calls. You capture a session with the Chrome extension in `loginExtensionMulti/`, and the account appears in the dashboard.

**Fansly.** A Fansly client lives in the repo, in `fansly/`; the Docker image does not ship it yet. The same capture extension can grab a Fansly session. Fansly does not have every screen OnlyFans has; the status of each piece is tracked in `fansly/FANSLY_PARITY_STATUS.md`.

**Not supported:** Fanvue and mym. There is no client for either in the repository. If your agency runs creators there, you will need their own dashboards or another tool for that part of the roster.

## What works on those accounts today

These screens are real, with the route so you can check:

- **Dashboard** at `/`.
- **Messages Pro** at `/messages-pro`: chat list, thread and a fan insights rail.
- **Analytics:** Creator, Employee and Fan reports, plus the Message dashboard (paid messages, tips and a message log).
- **Growth:** Smart Messages, Smart lists, Auto-follow, Profile promotion, Free trial links, Tracking links, Vault Pro and Scripts.
- **My Automations:** Auto Post and Auto Story.
- **Creators:** Manage creators and Custom proxy. **Employees:** Manage employees.

## What is a stub, and what does not exist

Some pages exist in the sidebar but show an empty state. The 12 OF Manager sections, the 3 Share for Share sections, Shift schedule, the Settings tabs and the Help center ship in our NotBuiltYet edition: the page is real, the feature is not.

Things that do not exist at all: Fanvue support, mym support, a native phone app, an AI copilot, a support desk and any uptime figure. The phone experience is the same web app, which is responsive. There is also an Electron desktop shell that loads the web app from your server.

## How you run it

- Docker Compose starts three containers: the relay, the Next.js app and an autoheal container.
- Data lives in SQLite on your server. Sessions are files on your server.
- Optional LLM keys are billed by the provider, not by us. The dashboard works without them.
- The license is MIT.

The project reverse-engineers OnlyFans' public web API and is not affiliated with or endorsed by OnlyFans. Read [the disclaimer]({{ '/legal/terms/#disclaimer' | url }}) before you connect a live account, and make that decision with the creator, not for them.

## What would change this post

A Fanvue client would need someone to write it, test it against real accounts and keep it working. If that is you, the repository takes pull requests. Until then, the honest answer to "does it work with Fanvue" stays no.

> **The pitch.** OnlyFans today, and no partnership press release. [Deploy it yourself]({{ '/#deploy' | url }}).
