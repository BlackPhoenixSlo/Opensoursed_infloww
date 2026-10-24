---
title: "Inflowwww messaging benchmarks: exactly as fast as your server"
description: "How to measure your chatters' response times and PPV ratios from the Message dashboard export, and set targets your team trusts."
date: 2026-10-12
tags: ["product", "message-dashboard", "benchmarks"]
parodyOf: "infloww-messaging-benchmarks"
parodyTitle: "“Is this good?”: messaging benchmarks"
parodyDate: "Jul 18, 2025"
image: "messages-pro-combo.webp"
imageAlt: "Messages Pro on desktop and phone: a fan chat list and an open thread with an image and a PPV"
---

"Are these numbers any good?" is the question every agency asks. Infloww answers it from its own platform: its post (infloww.com, stamped Jul 18, 2025) says "We analyzed the top 20 chatting teams on Infloww", 48,442 messages in all. We do not publish an answer, because we have nothing to pool: we host no one's install, and each copy of Inflowwww keeps its data on its owner's server. What we can give you is a method to build your own benchmark in an afternoon.

## Why your own benchmark beats a published one

Any benchmark built from other teams, ours included if we had one, can mix free and paid pages, time zones and very different creators. Your own history doesn't. A target taken from your best weeks is one your team has already hit, so nobody can argue it is unrealistic.

Pick three numbers and stick to them:

1. **Median response time**: how long a fan waits for a reply.
2. **PPVs per message**: sales against volume.
3. **Revenue per message**: what a message is worth.

## Step 1: export the messages

{% shot "message-dashboard.webp", "Message dashboard with message volume and response-time cards and a chart", "The Message dashboard, where the export starts. Demo data." %}

1. Open **Analytics > Message dashboard** (`/analytics/message-dashboard`) and choose the **All** tab.
2. Set the date range to the last four weeks and pick one model.
3. Leave **Direction** on **All**, so inbound and outbound messages are both included.
4. Click **Export CSV**.

The file has one row per message, with columns including `fan_id`, `direction`, `sent_at_iso`, `employee_name` and `automation_kind`. Exports stop at 50,000 rows and add a `# TRUNCATED` line at the end when they do; if you see it, narrow the range or export one model at a time.

## Step 2: compute response times

In any spreadsheet:

1. Sort by `fan_id`, then by `sent_at_iso`.
2. For each inbound message, find the next outbound message to the same fan.
3. Response time is the difference between the two timestamps, in minutes.
4. Skip pairs where the outbound row has an `automation_kind`, so you measure people, not scheduled sends.
5. Skip inbound messages that arrive while a reply is already pending, so one wait is not counted three times.
6. Group by the outbound row's `employee_name`.

Report the **median** and the **90th percentile** per person. The median says what a normal wait looks like. The 90th percentile shows the long waits fans remember.

Then group the same pairs by hour of day. Long waits clustered in a few hours usually point to a coverage gap, not to a slow chatter.

## Step 3: the sales ratios

These need no spreadsheet. Open **Analytics > Employee reports** for the same four weeks and, for each person, divide **PPVs** by **Messages** and **Total** by **Messages**. A chatter login puts the chatter's name on every message they send, and sales that cannot be tied to anyone wait in a **Sales needing attribution** card for the owner to assign. Clear that card first, or someone's ratio is wrong.

PPVs per message tells you balance: very low means lots of talk with few offers, very high can mean too many offers. Revenue per message tells you value, whatever the style.

## Step 4: set the targets

1. Take your three most consistent people.
2. Use their median values from the four weeks as the team target.
3. Repeat the exercise every quarter; targets should move as the team improves.

Share the method with the team, not only the result. A chatter who knows how response time is measured knows how to improve it.

## About speed

The app's speed depends on your server and your connection to OnlyFans. Uptime is whatever your VPS does. If replies feel slow, check the server's load before you check the team.

> **The pitch.** Your benchmark, computed from your data, on your own server, for $0 per creator. Book a demo: open the README. [Deploy it yourself]({{ '/#deploy' | url }}).
