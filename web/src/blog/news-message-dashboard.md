---
title: "Message dashboard: quality control for every team message, in a log you host"
description: "Inflowwww's Message dashboard puts every message, PPV, tip and custom in one filterable log with CSV export. How to use it for a weekly quality review."
date: 2026-10-12
tags: ["product", "message-dashboard", "quality-control"]
parodyOf: "news-message-dashboard"
parodyTitle: "Infloww’s Message Dashboard: quality control for every team message"
parodyDate: "Jun 20, 2024"
---

Reviewing a team's messages used to mean opening inbox after inbox. **Analytics > Message dashboard** (`/analytics/message-dashboard`) puts them in one log, so a manager can review a week of chatting in half an hour.

## What is on the dashboard

The dashboard has seven tabs:

- **PPV**: paid messages and whether they were unlocked.
- **Tips**: tips received.
- **All**: every message, inbound and outbound.
- **Customs**: custom requests.
- **Posts**, **My Feed** and **Top Posts**: feed activity and the posts that earned most.

Every tab follows the date range you pick. The old `/messages` and `/customs` addresses redirect here, so existing bookmarks keep working.

## Filter to what you need

On the **All** tab you can narrow the log by:

- **Fan**: search by username or display name.
- **Direction**: inbound or outbound.
- **Type**: free or paid.
- **Status**: paid or unpaid, for priced messages.
- **Employee**: who sent it.

Reviewing one chatter's week is two clicks: pick their name and set **Direction** to outbound. Reviewing one fan's experience is the opposite: search the fan and leave direction on all.

## Export for deeper checks

**Export CSV** downloads the filtered log, up to 50,000 rows. Each row includes the account, the fan, the direction, the time, the message body, media count, price, paid and tip flags, purchase time, the employee and, for automated sends, the automation kind. If the export hits the cap, the last line says `# TRUNCATED` and you should narrow the range.

Uses for the export:

- Response times per chatter (see the post on messaging benchmarks).
- Sales by hour of day, to plan coverage.
- An archive of the month for your own records.

## A weekly quality review

Set aside 30 minutes each week per team lead.

1. **Sample.** For each chatter, filter by their name, outbound only, last seven days. Read 20 messages spread across the week, not the 20 most recent.
2. **Score.** Use a short rubric: does it sound like the creator, is it specific to the fan, is any offer clear and fairly priced, does it respect what the fan said before.
3. **Check the follow-through.** Open the PPV tab filtered by the same person. Unlocked versus not tells you whether offers are landing.
4. **Look for patterns.** The same opener pasted 40 times is a Scripts problem, not a chatter problem. Fix the library.
5. **Give one note.** One thing to keep, one thing to try. Use real messages as the examples.

## Rules worth writing down

A dashboard only helps if the team knows what you are checking for. Write a one-page guide and share it:

- Topics the creator does not discuss.
- How to say no to a request politely.
- How often a fan can be offered paid content in one conversation.
- What to do if a fan seems upset or at risk: stop selling, be kind, and escalate to a manager.
- Never promise anything the creator has not agreed to.

Review against that page, not against your mood that day.

## What it does not do

The dashboard is a log and a filter. It does not flag sensitive words or score messages for you, and it does not unsend messages. Review decisions, and any follow-up, stay with a person. The data sits in a SQLite file on your own server.

**Next steps**

1. Invite every chatter with their own login, so each message has a name.
2. Run one week.
3. Do the 30-minute review above for one chatter.
4. Turn what you found into one new script or one line in the team guide.

> **The pitch.** The Message dashboard lives at `/analytics/message-dashboard` on your own server, for every creator you add. [Deploy it yourself]({{ '/#deploy' | url }}).
