---
title: "How Sample Size Studio reviews PPV prices once a month instead of every time someone has a feeling"
description: "A fictional nine-creator agency moves PPV pricing to a fixed monthly review with one change at a time and a written log. The method is below."
date: 2026-10-12
agency: "Sample Size Studio"
tagline: "Nine creators, one review meeting a month, and a price log that is longer than its software invoice."
stats:
  - value: "$0"
    label: "Per creator per month x 9 creators = $0"
  - value: "1st Monday"
    label: "Of each month: the only day PPV prices change"
  - value: "1"
    label: "Price change per creator per review, at most"
  - value: "0%"
    label: "Increase in software fees when a creator has a record month"
quote: "We stopped arguing about prices on Tuesdays. Now we argue about them on the first Monday, with data."
quoteBy: "Lena, owner, Sample Size Studio"
---

Sample Size Studio sets PPV prices in one monthly review, changes at most one thing per creator per month, and writes every change in a log. That cadence is what makes the numbers readable. The method below needs a report screen and a spreadsheet, and nothing else.

## About

Sample Size Studio is a fictional agency with nine creators on OnlyFans. It runs Inflowwww on a VPS. Its managers use Analytics > Creator reports (`/analytics/creator-reports`) and Analytics > Message dashboard (`/analytics/message-dashboard`), which logs PPVs, tips and messages.

## Challenge

Prices moved whenever someone had a hunch. A chatter would drop a price after a slow evening, a manager would raise it after a good weekend, and a month later nobody could say which change did what. Two changes in the same week cancel each other out in the data. Ten changes in a month are noise.

## Solution

One fixed review per month, on the first Monday. Between reviews, prices do not change. Chatters can flag an idea in the log at any time; it waits for the review.

For each creator, the manager reads the last full month in the Message dashboard's PPV log and in Creator reports, then fills in one row of the log:

| Field | Example |
|---|---|
| Creator | Creator C |
| PPVs sent / unlocked | 410 / 52 |
| Median unlocked price | $18 |
| What changed last month | Bundle price $25 to $22 |
| Result, in one line | Unlocks up, revenue per unlock down, total flat |
| Decision this month | Keep $22, test a new opener script instead |

## Strategy

Three rules keep the review honest:

1. **One change per creator per month.** A price, a bundle, an opener or a schedule. Not two. If you change two things, you learn nothing about either.
2. **Write the decision before the month starts.** Then compare against what you wrote, not against what you remember.
3. **"No change" is a valid decision.** Most months, for most creators, it is the right one.

The creator is in the loop on every change to their pricing. It is their page and their work, and the review exists to give them a clear answer to "why did my prices change?"

## Operations

The review takes about ten minutes per creator, so 90 minutes for the roster. The owner and one manager run it together. Chatters see the decisions the same day, and any new opener goes into Growth > Scripts (`/growth/scripts`) so everyone uses the same text.

One line in the log never changes. When a creator moves up an earnings bracket, the software bill stays put: under $500: $0, over $75,000: still $0.

## Results

- Every price on the roster has a reason and a date in the log.
- The team can answer "what happened in March?" in one scroll.
- Arguments about pricing moved from the chat channel to a meeting with a table on the screen.

We are not telling you the review raised revenue. We are telling you it made the effect of each change visible, which is the only way to know whether a change helped at all.
