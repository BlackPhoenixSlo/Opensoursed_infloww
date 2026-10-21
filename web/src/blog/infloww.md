---
title: "What is Inflowwww? Product updates and feature guides, NotBuiltYet included"
description: "Inflowwww is a free, open-source, self-hosted tool for OnlyFans agencies. What it is, how it works, what is built, what is not, and how to try it in an hour."
date: 2026-10-12
tags: ["product", "openinflowwww", "overview"]
parodyOf: "infloww"
parodyTitle: "Product Updates & Feature Guides | Infloww Blog"
parodyDate: ""
---

Inflowwww is a free, open-source, self-hosted alternative to Infloww for OnlyFans agencies. You run it on your own server, your team uses it in a browser, and it costs $0 per creator. This page explains what that means in practice.

## What it does

Inflowwww gives an agency one workspace for many creator accounts. Today that covers:

- **Messages Pro**: a shared inbox with a chat list, thread and fan insights.
- **Analytics**: Creator reports, Employee reports, Fan reports and a Message dashboard with CSV export.
- **Growth**: Smart Messages (mass and scheduled messages), Smart lists, Auto-follow, Profile promotion, Free trial links, Tracking links, Vault Pro and Scripts.
- **My Automations**: Auto Post and Auto Story.
- **Creators**: Manage creators and Custom proxy.
- **Employees**: Manage employees, with chatter invites and access limits.

Fansly: a Fansly client lives in the repo; the Docker image does not ship it yet.

## How it works

Two parts, both started by Docker Compose:

1. **The relay**, a Python (FastAPI) service. It holds each creator's captured web session, signs and replays OnlyFans API calls, and keeps its data in a SQLite file.
2. **The app**, a Next.js dashboard that your team opens in a browser.

A third container, autoheal, restarts services that fail their healthcheck. Sessions are captured with a Chrome extension included in the repository, so nobody types a creator's password into Inflowwww.

Said plainly: Inflowwww is an independent reverse-engineering of OnlyFans' public web API, and the project is not affiliated with or endorsed by OnlyFans.

## Where it runs

- **Web**: the main app.
- **Phone**: the same web app, which is responsive. There is no native phone app.
- **Desktop**: an Electron shell that asks for your server URL on first launch.

## What is not built yet

Inflowwww covers the same screens an agency expects, and some of them are placeholders. They render a NotBuiltYet empty state: the page is real, the feature is not.

- All twelve **OF Manager** sections.
- All three **Share for Share** sections.
- **Employees > Shift schedule**.
- The **Settings** tabs and the **Help center**.

There is also no support desk, no uptime promise and no AI copilot. The older AI automations in the code are off by default and are not part of the product.

## Who it is for

- Agencies that want to stop paying per creator and are comfortable running a server.
- Solo creators who want a better inbox and reports for their own page.
- Developers who want to read, change or extend the code. It is MIT-licensed.

It is not for anyone who wants someone else to run the servers, answer the phone, or carry the risk. That is a real service, and it is not what this is.

## How to try it

1. Read the README's Quick start.
2. Run it on a spare machine or a small VPS.
3. Capture one creator's session.
4. Use Messages Pro and the reports for a week before moving anyone else over.

Each post on this blog takes the topic of a post on Infloww's blog (their page, stamped Oct 10, 2026) and answers it in our own words. Feature posts describe what each Inflowwww screen does, including the ones that are not built. The rest are practical guides for creators and agencies.

> **The pitch.** One workspace for your agency, minus the invoice. [Deploy it yourself]({{ '/#deploy' | url }}).
