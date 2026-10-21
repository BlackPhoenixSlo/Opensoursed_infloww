---
title: "How Inflowwww's creator reports track revenue from a database you own"
description: "How Inflowwww's Creator reports show each model's revenue by source, fans, LTV and ARPU, read from SQLite on your own server."
date: 2026-10-12
tags: ["product", "analytics", "creator-reports"]
parodyOf: "infloww-creator-reports"
parodyTitle: "How Infloww's creator reports help you track revenue performance"
parodyDate: "Feb 18, 2025"
---

If you manage more than two creators, you have probably kept a spreadsheet of who earned what. **Analytics > Creator reports** (`/analytics/creator-reports`) replaces most of it, and the numbers live in a database on your own server.

## 1. The whole roster on one screen

Creator reports shows one tile per model for the date range you pick. It defaults to the last 30 days. Each tile has:

- **Fans**: the current subscriber count as OnlyFans reports it, the same audience a mass message reaches.
- **New fans (30d)** for free pages, or **New subs** for paid pages, which counts new and renewed paid subscriptions and leaves out trials.
- **LTV**: revenue in the window divided by new fans or new subs in the window.
- **ARPU**: revenue in the window divided by current fans.
- **Messages** sent and **PPVs sold**.

A line under the title says when the data was last read. **Refresh** fetches it again. If an account's data could not be read, the page says so with a banner instead of showing a quiet zero.

## 2. Where every dollar comes from

Under each tile, revenue is split into chips: **PPV** (message unlocks), **Post** (feed post sales), **Tip**, **Sub**, **Rebill** and **Other**. Pending amounts are marked separately from cleared ones, so you do not plan around money that has not landed.

What to look for:

- A creator whose revenue is mostly **Sub** and **Rebill** depends on subscriber count. Growth there means promotion.
- A creator whose revenue is mostly **PPV** and **Tip** depends on chatting. Growth there means more and better conversations.
- **Other** catches the rest. If it is large, open the **Message dashboard** to see what it is.

## 3. Spot who needs help

Line up the tiles and sort them in your head by ARPU, not total revenue. A creator with a small audience and a high ARPU is being served well. A creator with a large audience and a low ARPU is the one to staff up or retarget.

Then cross-check with **Analytics > Employee reports** for the same range, to see which team members are selling on which accounts.

## 4. Track trends week over week

There is no trend chart on this screen, so use the date range:

1. Every Monday, set the range to the previous seven days.
2. Write each creator's total and the PPV, Tip and Sub chips into a simple sheet.
3. After four weeks you have a trend line per creator and per revenue source.

Four rows a month per creator is enough to catch a slide before it becomes a bad month.

## 5. Find the hours that sell

There is no earnings heatmap in Creator reports. You can build one from the **Message dashboard**:

1. Open **Analytics > Message dashboard**, tab **PPV**, and pick the range.
2. Export CSV.
3. In a spreadsheet, take the hour from `purchased_at_iso` and count purchases and sum `price_cents` per hour and weekday.

That table tells you when fans buy, which is when your strongest chatter should be online and when mass messages should go out.

## Where the data lives

Creator reports reads from the relay's SQLite database, `service/chatterly.db`, on your server. Back that file up like you would any business record. Sessions and the database live on your server.

**Next steps**

1. Install Inflowwww and capture each creator's session.
2. Open **Analytics > Creator reports** and set the range to last month.
3. Note each creator's ARPU and revenue mix.
4. Pick one creator and one change for this month.

> **The pitch.** One report covers every creator on the roster, and the fiftieth costs what the first did: nothing. [Deploy it yourself]({{ '/#deploy' | url }}).
