---
title: "How agencies use Creator reports to measure profitability, creator by creator"
description: "How to read Inflowwww's Creator reports for profit per creator: LTV, ARPU, revenue by source and messages against earnings."
date: 2026-10-12
tags: ["product", "analytics", "creator-reports"]
parodyOf: "how-to-use-creator-reports"
parodyTitle: "How agencies use Infloww Creator Reports to measure profitability"
parodyDate: "Sep 30, 2026"
image: "creator-reports-combo.webp"
imageAlt: "Creator reports on desktop and phone: revenue and KPIs per creator for a demo agency"
---

Total revenue tells you what a creator earned. It does not tell you whether the team's hours paid for themselves. **Analytics > Creator reports** (`/analytics/creator-reports`) gives you the inputs; this post shows how to turn them into profitability numbers.

## What the report shows

{% shot "creator-reports-table.webp", "Creator reports with fans, new subs, LTV, ARPU, messages, PPVs sold and revenue for each of 20 creators", "Creator reports for the last 30 days, one entry per creator. Demo data." %}

Pick a date range (it defaults to the last 30 days). Each model gets a tile with:

- **Fans**: the current subscriber count, as OnlyFans reports it.
- **New fans (30d)** on free pages, or **New subs** on paid pages (new and renewed paid subscriptions, trials excluded).
- **LTV**: revenue in the window divided by the new fans or new subs in that window.
- **ARPU**: revenue in the window divided by current fans.
- **Messages** and **PPVs sold** in the window.
- Revenue chips by source: **PPV**, **Post**, **Tip**, **Sub**, **Rebill** and **Other**, with pending amounts marked.

The header shows when the data was last read, and **Refresh** re-fetches it. Note that our LTV is a window ratio, not a lifetime figure. Compare it only against itself, period to period.

## Monetization beyond the subscription

Take the chips and compute one ratio per creator:

**Engagement ratio = (PPV + Tip + Post) / (Sub + Rebill)**

A creator at 3.0 earns three dollars from conversations and posts for every dollar of subscriptions. A creator at 0.5 is mostly a subscription business. Neither is wrong, but a low ratio on an account with a full chatting team is the first place to look.

When the ratio is low, open **Analytics > Employee reports** for the same window and see who is selling on that account. The best performer's threads, read in Messages Pro, are your training material.

## Return on the team's hours

There is no hourly earnings view, and **Employees > Shift schedule** is NotBuiltYet: the page is real, the feature is not. You can still do this in a spreadsheet:

1. Take the window's total revenue for the creator.
2. Divide by the hours your team covered that account. Your own rota is the source.
3. Divide that by the hourly cost of the people on it.

If a creator earns $200 an hour of coverage and the team costs $40 an hour, the return is 5x. Close to 1x means the hours need a look before the headcount does. The software line in this calculation is $0, which keeps the arithmetic short.

## Messages against earnings

{% shot "sales-records.webp", "Sales records listing each sale with amount, fan, creator, chatter and type", "Sales records: the sales behind the report, one row each. Demo data." %}

Compare the **Messages** tile with revenue for each creator:

| Messages | Revenue | Likely meaning | Try |
|---|---|---|---|
| High | Low | Lots of talk, few sales | Shorter threads, clearer offers |
| High | High | Working, but heavy | Save the best openers as Scripts |
| Low | Low | Fans are not being reached | More outreach, a mass message to a Smart list |
| Low | High | Efficient | Keep it, and do not over-message |

"High" and "low" mean relative to your own other creators, not to an industry number.

## Traffic and retention

Creator reports does not split visitors by type. What you can track today:

- **New fans or new subs per window**, compared month to month, to see whether promotion is working.
- **Rebill** revenue against **Sub** revenue. Rebill growing faster than new subs means retention is carrying the account.
- **Growth > Tracking links** and **Free trial links** to see which links bring people in.

For fans who rarely hear from you, build a Smart list of active subscribers who have spent nothing and look at how many there are. A large number is a reach problem, not a content problem.

## A monthly routine

1. On the first of the month, set the range to the previous month.
2. Write down each creator's revenue chips, LTV, ARPU and messages.
3. Compute the engagement ratio and the return on hours.
4. Pick one creator to improve and one change to try.
5. Check the same numbers a month later.

> **The pitch.** Creator reports reads from a SQLite file on your own server, and the report is the same price for every creator: $0. [Deploy it yourself]({{ '/#deploy' | url }}).
