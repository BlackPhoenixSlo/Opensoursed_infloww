---
title: "How smart automation levels up your page without alienating fans: we ship exactly two"
description: "Inflowwww's only in-scope automations are Auto Post and Auto Story. How each works, how to set them up safely with a dry run, and a posting rhythm fans like."
date: 2026-10-12
tags: ["product", "automation", "auto-post"]
parodyOf: "infloww-smart-automation"
parodyTitle: "How Infloww’s smart automation levels up your OF (without alienating fans)"
parodyDate: "Dec 20, 2024"
---

Automation is best at the jobs that are the same every time and never need a reply: posting to the feed and keeping stories fresh. Those are the two automations Inflowwww ships, under **My Automations**, and the project's scope stops there on purpose.

## What is in scope, and what is not

The project's scope lists **Auto Post** and **Auto Story** as the only automations. Both are owner-only.

Everything that messages fans on a trigger (when they come online, when a subscription is expiring, after a purchase) is not part of the product. Older versions of those screens exist in the code from an earlier project, but they are off by default and we do not support them. Messages to fans are written, or at least sent, by people.

**Growth > Auto-follow** sits outside My Automations. It only follows and likes, never messages.

## Auto Post: a feed that fills itself

**My Automations > Auto Post** (`/growth/auto-post`) takes a list of ready posts and publishes them one at a time:

1. You prepare the list. Each post has its text and vault media, and an optional price. A price above zero makes it a paid post, which OnlyFans only allows with media attached.
2. It publishes the first post, waits the delay you set, then publishes the next.
3. If a post has a time to live in hours, it is deleted when that time is up. Posts without one stay up.

Setup that avoids surprises:

- Turn on **Dry run** for the first run. It plans the posts without calling OnlyFans, so you can check the order and the text.
- Set **Run every** to match your rhythm. One to three posts a day suits most pages; a burst of ten in an hour does not.
- Use time to live for time-limited promotions, so last week's offer does not sit on the feed.

Posting is public and immediate. Read each caption once more before you switch off the dry run.

## Auto Story: stories from a vault folder

**My Automations > Auto Story** (`/growth/auto-story`) posts stories from your vault on a schedule:

- Pick the **Account** and a **Vault folder**, or pick specific images instead.
- Set **Stories per run**. Each run picks that many random photos from the folder.
- Choose the schedule: **At set times each day** or **Every few hours**.
- Set **Delete after (hours, 0 = keep)** and **Total runs** (blank means forever).
- Use **Post one batch now** to test it outside the schedule.

Because stories need a fresh upload, OnlyFans files a duplicate of each photo in the vault. Auto Story removes that duplicate afterwards by default, so the vault does not slowly double.

Give Auto Story its own folder, such as "story pool", with 30 or more photos. A small pool means fans see the same image every other day.

## A rhythm fans like

- **Predictable beats frequent.** Fans like knowing there will be something new each morning.
- **Mix free and paid.** A feed that is all offers trains people to scroll past.
- **Keep stories light.** Behind-the-scenes and everyday photos work better than sales.
- **Refresh the pool monthly.** Swap a third of the story folder for new photos.
- **Stay in the conversation.** Automation keeps the page alive; people keep fans.

## Next steps

1. Create a "story pool" folder in **Growth > Vault Pro** and fill it.
2. Set up Auto Story with two stories per run, every few hours, deleted after 24 hours.
3. Write five posts for Auto Post and run them once in dry run.
4. Check **Analytics > Creator reports** after two weeks.

> **The pitch.** Two automations, both on your own server, both $0 per creator. An autoheal container restarts unhealthy services; the rest is your hosting. [Deploy it yourself]({{ '/#deploy' | url }}).
