---
title: "Inflowwww goes multi-platform with Fansly. The platform count is one and a half."
description: "Where Inflowwww's Fansly support stands: the client is in the repo, the Docker image does not ship it, and what is verified."
date: 2026-10-12
tags: ["platforms", "fansly", "product-news"]
parodyOf: "introducing-infloww-for-fansly"
parodyTitle: "Infloww goes multi-platform with Fansly"
parodyDate: "Jun 16, 2025"
---

Does Inflowwww work with Fansly? Partly, and the part matters. A Fansly client lives in the repo, in `fansly/`; the Docker image does not ship it yet. So a standard `docker compose up` install runs OnlyFans accounts, and Fansly is code you can read, test and help wire in. Some features are verified, some are still open, and the list of which is which is written down in the repository.

## How it works

Inflowwww's relay is a Python (FastAPI) service that holds each creator's captured web session on your server. For OnlyFans it signs and replays the web API calls. The relay code imports the Fansly client from `fansly/` for Fansly accounts.

What the Fansly path looks like for someone working from the repository:

1. The capture extension in `loginExtensionMulti/` captures OnlyFans and Fansly sessions.
2. Sign in to Fansly in that browser and capture the session.
3. Add it under **Creators > Manage creators** on a relay that has the Fansly client available.

The session file stays on your server. It never goes to us, because there is no us to send it to.

## What is verified, and what is still open

We keep a single status file, `fansly/FANSLY_PARITY_STATUS.md`, that marks each item as tested, stubbed, needing a live test, or not started. Read it before you move a creator. At the time of writing it lists as working and tested, among others:

- Session capture and account setup.
- The chat list, reading threads, and sending text messages.
- Scheduled sends, marking chats read, and the unread badge.
- Fan notes and custom names, and Fansly lists.

It also lists items still open, such as blocking or restricting a fan and searching users, plus some media cases that are only partly verified. If a feature matters to your team, check its row first. That file is more current than any blog post, this one included.

## Running Fansly and OnlyFans side by side

A few habits help once both platforms share one app:

- **Brief chatters on platform.** Make sure every chatter checks which platform a thread belongs to before sending an offer, so a Fansly fan never gets an OnlyFans price.
- **Keep separate fan notes.** The same person can be a fan on both platforms with different purchase histories. Note what they bought on each.
- **Price per platform.** Decide whether the pages offer the same things or different things, and keep scripts consistent with that.
- **Plan the feed separately.** Fansly's For You feed rewards free, follower-visible posts more than OnlyFans does. Our [Fansly growth playbook]({{ '/blog/fansly-growth-playbook-agencies/' | url }}) covers that.

## What it costs

Infloww's pricing page lists Infloww for Fansly as "Starting at just $40", per creator profile, per month (infloww.com, captured 2026-10-11). Inflowwww is MIT-licensed and self-hosted, so the software is free; your costs are the server you run it on and any optional LLM keys, billed by the provider.

## What it would take

Two things: the Fansly client in the Docker image, and the open rows in the status file closed one by one. Neither has a date. Coming when someone builds it. That could be you.

> **The pitch.** OnlyFans in one self-hosted app today, and a Fansly client in the repo for whoever wants to finish the job. [Deploy it yourself]({{ '/#deploy' | url }}).
