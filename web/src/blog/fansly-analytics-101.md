---
title: "Fansly analytics 101: five numbers to read every week. Our price is not one of them."
description: "The five Fansly numbers worth reading every week, what each one tells you, and what to change when one of them moves."
date: 2026-10-12
tags: ["platforms", "fansly", "analytics"]
parodyOf: "fansly-analytics-101"
parodyTitle: "Fansly analytics 101"
parodyDate: "Jul 14, 2025"
---

What should you track on Fansly? Five things: follower growth, subscriber retention, paid message sales, message performance, and free-to-paid conversion. Read them once a week, change one thing at a time, and write down what you changed. That is the whole method.

## Set up a weekly review before you look at anything

Numbers only help if you compare them on a fixed rhythm. Pick one day and one time, and keep it.

- Use the same date range every week (Monday to Sunday works).
- Keep a simple sheet with one row per week and one column per metric below.
- Add a "what we changed" column. Without it you will not know why a number moved.
- Change one variable per week per creator: price, posting time, or message style. Not all three.

Fansly's own Statistics pages are the source for most of this. Export or copy the figures into your sheet. A plain spreadsheet is enough to start.

## The five metrics, one at a time

Read them in this order. Each one answers a different question: who finds you, who stays, and who pays.

### 1. Follower count and growth rate

Followers can see free posts and previews, and they are warmer than cold traffic. Growth rate matters more than the total.

- Note the weekly change, not just the count.
- When a week spikes, tie it to a cause: a specific post, a tag, a shoutout, or an outside link.
- When it drops, check whether posting slowed before you blame the algorithm.

### 2. Subscription length and renewal rate

New subscribers feel good. Renewals pay the bills.

- Track the share of subscribers with renewal switched on.
- Watch average subscription length over months, not days.
- If renewals fall after a price change or a quiet week, that is your signal. Churn usually follows a mismatch between what the page promises and what arrives.

### 3. Paid message sales

Check which offers sell, at what price, and how often you send them.

- Record unlock rate per offer: unlocks divided by recipients.
- Compare single items with bundles at the same total price.
- If unlock rates fall for three weeks in a row, you are probably sending too many paid offers. Space them out and add free value between them.

### 4. Message performance

Mass messages are often the biggest lever, so measure them like campaigns.

- For each send, log time of day, audience, price and result (opens, unlocks, tips).
- Test two send times for the same offer across two weeks before you decide.
- Keep a short list of your three best messages and reuse their structure, not their exact text.

### 5. Conversion from free to paid

Not every follower will subscribe. The useful question is which content moves them.

- Tag each free post by type (clip, photo set, text update) and note which ones precede new subscriptions.
- Try subscriber-only teasers on your free feed and compare the following week.
- Keep a note on fans who showed interest but have not converted, and follow up with a relevant offer later rather than repeating the same pitch.

## Where Inflowwww fits

A Fansly client lives in the repo; the Docker image does not ship it yet. Once it is wired in, a Fansly creator's chats come into the same app as your OnlyFans accounts. It does not replace Fansly's Statistics pages for the numbers above; the item-by-item Fansly status is written down in `fansly/FANSLY_PARITY_STATUS.md` in the repo. Fan notes and lists are the parts most useful for step 5.

> **The pitch.** Fansly's five numbers live in Fansly's own dashboard; for OnlyFans creators, Inflowwww's Creator reports give the same kind of weekly view. Book a demo: open the README. [Deploy it yourself]({{ '/#deploy' | url }}).
