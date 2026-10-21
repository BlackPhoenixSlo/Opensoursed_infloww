---
title: "OnlyFans vs Inflowwww: what the platform gives an agency, and what we add on top"
description: "What the OnlyFans web app gives an agency on its own, what Inflowwww adds on top today, and which screens we have not built yet."
date: 2026-10-12
tags: ["product", "comparison", "agency-operations"]
parodyOf: "feature-comparison-infloww-onlyfans"
parodyTitle: "OnlyFans vs Infloww: Complete feature comparison for agencies"
parodyDate: "Dec 19, 2024"
---

Inflowwww does not replace OnlyFans. It sits on top of a creator's account, using a captured web session, and gives a team a shared workspace for it. This comparison lists what we add, screen by screen, and what we have not built.

One thing first, said plainly: Inflowwww works by replaying OnlyFans' own web API calls.

## Messaging

OnlyFans gives a creator an inbox, media sending and scheduled messages. That works well for one person at one desk.

What Inflowwww adds in **Messages Pro** (`/messages-pro`):

- A chat list, thread and fan insights rail in one screen, used by several team members at once.
- Fan insights next to the thread: lifetime spend, tips, subscription status and price, renewal date, last seen, recent PPV purchases.
- Notes, tags, a custom nickname and pinned messages per fan.
- Saved replies from **Growth > Scripts**, inserted from the composer.
- Mass messages and the scheduled queue in **Growth > Smart Messages**.

What we do not have: the automated-trigger half of Smart Messages (messages that fire when a fan comes online or a subscription is about to expire). Our older trigger automations are off by default and not part of the product.

## Content

OnlyFans has a vault with lists. Getting a batch of new files into it is slow by hand.

**Growth > Vault Pro** (the owner manages it; chatters attach media from the chat composer, limited to the vault folders the owner grants them) adds bulk import from dropped files or public Google Drive links, folders you can create, rename and reorder, per-item tags, descriptions and captions, search, and a duplicate finder that asks you to review before anything is removed. It is honest about speed: OnlyFans throttles writes, so new files import at roughly three a minute.

## Audiences

OnlyFans lets a creator make lists by hand. **Growth > Smart lists** builds saved segments from rules over spend, recency, status and tags, previews the count live, and lets you include or exclude the list when you send a mass message.

## Team access

On OnlyFans alone, sharing an account usually means sharing a password. In Inflowwww the owner captures the session once, and chatters log in to Inflowwww with their own username and password from an invite link. Owner pages are hidden from chatter sessions, and the owner can limit which models and which vault folders each chatter sees.

There are no custom roles beyond owner and chatter.

## Analytics

OnlyFans has its own statistics pages per creator. Inflowwww adds:

- **Creator reports**: fans, new fans or new subs, LTV, ARPU, messages, PPVs sold, and revenue split by PPV, post, tip, subscription, rebill and other, across every model.
- **Employee reports**: messages, PPVs and revenue per employee, plus a list of sales that still need attributing.
- **Fan reports**: a per-fan table.
- **Message dashboard**: every message in a filterable log with CSV export.

The data sits in a SQLite file on your server.

## What we have not built

Some screens exist as pages and nothing more. They render a NotBuiltYet empty state: the page is real, the feature is not.

- All twelve **OF Manager** sections.
- All three **Share for Share** sections.
- **Employees > Shift schedule**.
- The **Settings** tabs and the **Help center**.

There is also no native phone app (the web app is responsive), no support desk and no uptime promise. If any of those are deal-breakers, they are fair ones.

Every Infloww cell on our [comparison page]({{ '/openinflowwww-vs-infloww/' | url }}) says where we read it and when.

**Making the switch**

1. Follow the README's Quick start on a small VPS or a spare machine.
2. Capture one creator's session with the extension in `loginExtensionMulti/`.
3. Spend a week in Messages Pro and the reports before you move the whole team.
4. Invite chatters one at a time from **Employees > Manage employees**.

> **The pitch.** The comparison above is checkable against the code, because the code is one repository you can read. $0 per creator, on your own server. [Deploy it yourself]({{ '/#deploy' | url }}).
