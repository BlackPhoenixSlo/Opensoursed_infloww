---
title: "How to monitor employee performance fairly, with reports on your own server"
description: "How to use Inflowwww's Employee reports to review a chat team fairly: messages, PPVs, revenue per person and unclaimed sales."
date: 2026-10-12
tags: ["product", "analytics", "employee-reports"]
parodyOf: "infloww-employee-reports"
parodyTitle: "How to easily monitor employee performance with Infloww"
parodyDate: "Feb 20, 2025"
image: "employee-reports-combo.webp"
imageAlt: "Employee reports on desktop and phone: sales, messages sent and hours per chatter"
---

A chat team is easy to judge badly: by gut feel, by who is loudest, or by one good night. **Analytics > Employee reports** (`/analytics/employee-reports`) gives you numbers per person, and this post covers how to use them fairly.

## 1. Sales per person

{% shot "employee-reports.webp", "Employee reports with sales, messages sent and hours for each chatter", "Sales, messages and hours per chatter. Demo data." %}

Pick a date range (default: last 30 days). The table lists each employee with:

- **Messages** sent.
- **PPVs** sold (unlocks attributed to them).
- **PPV Rev** and **Tip Rev**.
- **Total** revenue.

Click a column header to sort. Sort by **Total** to see who sells most, then by **Messages** to see who works most. The interesting people are the ones whose position changes between the two.

Their Employee Reports post (their page, stamped Oct 10, 2026) lists "keystrokes per message". Ours count messages sent, not keystrokes.

On a phone, the PPV and tip revenue columns are hidden to keep the table readable; rotate or use a wider screen for the full view.

## 2. Measure the balance, not just the volume

Two ratios you can compute from the table:

- **PPVs per message** = PPVs / Messages. Low means lots of conversation and few sales; very high can mean the person is pushing offers too hard.
- **Revenue per message** = Total / Messages. It shows how much each message is worth, whatever the style.

We do not publish a target for either. Set yours from your own team: take the median of your three most consistent people over the last two months, and use that as the bar for coaching conversations. A benchmark from your own accounts is one your team will believe.

## 3. Attribute sales that nobody claimed

Messages sent from a chatter login already carry that chatter's name. Not every sale arrives with a name on it, though. The **Sales needing attribution** card lists sales the system could not tie to an employee, with the chatters who were recently in that conversation as suggestions. Assign each one, or leave it. You can clear a manual attribution later if you got it wrong.

Do this weekly, before you look at rankings. Unattributed sales are the most common reason a good chatter looks average.

## 4. Check coverage

The coverage table shows, per account, how outbound messages split into **Human**, **Automation** and **Unattributed**, and a **Coverage** figure for how much is accounted for. If coverage is low on an account, the per-employee numbers for it are incomplete. Fix that before you draw conclusions.

## 5. Response times and shifts

{% shot "shifts.webp", "Shift schedule for the week with every chatter's shifts filled in", "A full week of shifts. Demo data." %}

Response time is not a column in Employee reports. You can measure it from the **Message dashboard** export; the [post on messaging benchmarks]({{ '/blog/infloww-messaging-benchmarks/' | url }}) walks through it.

Shift scheduling lives in **Employees > Shift schedule**, which is a NotBuiltYet page: the screen is real, the feature is not. Until then, keep your rota where it is today and line it up with the report's date range by hand.

## A fair review routine

1. Monday: attribute last week's unclaimed sales.
2. Set the range to last week and sort by **Total**.
3. Compute PPVs per message and revenue per message for each person.
4. Pick one thing each person does well and one thing to try. Use their real threads in Messages Pro as examples.
5. Compare against their own previous weeks first, and against the team second.

People improve faster against their own history than against a leaderboard. Keep rankings for the manager, not the group chat.

**Next steps**

1. Invite your team from **Employees > Manage employees** so every sent message has a name.
2. Run one full week.
3. Attribute the leftovers and read the table.
4. Hold the first review using your own medians as the bar.

> **The pitch.** Employee reports covers every employee and every creator, on your own server, at $0 per creator. [Deploy it yourself]({{ '/#deploy' | url }}).
