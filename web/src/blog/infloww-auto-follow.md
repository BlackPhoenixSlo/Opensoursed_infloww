---
title: "Boost subscriber retention with Auto-follow: targets, limits and a dry run"
description: "How Inflowwww's Auto-follow re-engages expired and quiet fans with follow-backs and likes, never DMs, and how to set its limits."
date: 2026-10-12
tags: ["product", "auto-follow", "retention"]
straight: true
parodyOf: "infloww-auto-follow"
parodyTitle: "Boost subscriber retention with Infloww's Auto-Follow feature"
parodyDate: "Feb 20, 2025"
image: "auto-follow-combo.webp"
imageAlt: "Auto-follow on desktop and phone: follow campaigns with their counts"
---

Winning back a fan who let their subscription lapse is cheaper than finding a new one, but nobody has time to follow back expired fans by hand. **Growth > Auto-follow** (`/growth/auto-follow`) does the repetitive part.

## What it does

{% shot "auto-follow.webp", "Auto-follow campaigns with how many fans each one followed", "Auto-follow campaigns and their counts. Demo data." %}

Auto-follow sends OnlyFans notifications, not messages. Every action it takes shows up for the fan as a follow or a like, never as a DM. That makes it a gentle nudge rather than an ask.

It has four actions:

- **Follow fans**: follow fans back, picked by the target you choose below.
- **Like latest message**: like a fan's most recent message, to bring the thread back to the top of their attention.
- **Like posts**: like specific posts, by post id.
- **Re-follow ping**: re-follow fans who have been quiet for a number of days you set.

Following targets free fan profiles by default. The engine checks each fan's page price and skips paid pages, so the account does not subscribe to anyone by accident.

## Pick who it targets

The **Target** setting decides who gets the action:

- **Recently expired** fans (follow only): the classic win-back.
- **Recently active** fans, within a number of days you set.
- A **Smart list**, so you can aim at, say, past buyers whose subscription ended.
- Every fan on file (follow only), as a one-time backfill.

For most accounts, start with recently expired fans and a Smart list of expired fans who spent something. Those are the people most likely to come back.

## Set limits before you switch it on

Three settings keep it sensible:

1. **Max actions / run**: a daily ceiling. Start low, such as 25, and raise it once you have watched a week of runs.
2. **Min days between actions (per fan)**: one cooldown shared by follow and re-follow ping. Seven days is a reasonable floor. No fan should feel watched.
3. **Run every (minutes)**: how often the rule wakes up. Every few hours is plenty for a retention job.

New rules default to a dry run, so nothing happens on OnlyFans until you confirm and enable it. Read the dry-run output first: who would be followed, and how many. Run it again whenever you change a rule.

## Follow up with a message, by hand

Auto-follow never messages anyone, and nothing else in Inflowwww messages fans on a trigger either: the automated-trigger half of Smart Messages is not built, and our older trigger automations are off by default.

What works today:

1. In **Growth > Smart lists**, build a list of expired fans, with a spend rule if you want only past buyers.
2. In **Growth > Smart Messages**, send that list a mass message once a week with a reason to come back: a new set, a returning-fan discount, a short personal note.
3. Exclude a Smart list of fans active in the last day or two, so nobody you are mid-conversation with gets a broadcast.

Keep the message short and specific. "New set this Friday, 30% off for returning fans until Sunday" beats a paragraph.

## Watch the results

After two weeks, check:

- **Analytics > Creator reports**: are **New subs** or **Rebill** revenue moving for this creator?
- **Analytics > Fan reports**: did the fans you followed back resubscribe?
- The rule's last-run line on the Auto-follow page, which says what each run did.

If nothing moved, change one thing (the target, the cap or the message) and give it another two weeks.

## Next steps

1. Open **Growth > Auto-follow**, choose **Follow fans** and **Recently expired**.
2. Set a cap of 25 and a seven-day cooldown.
3. Read the dry run, then enable it.
4. Build the expired-fans Smart list and send your first win-back message.

> **The pitch.** Auto-follow runs on your own server, with the caps and the dry run you set before it touches a fan. [Deploy it yourself]({{ '/#deploy' | url }}).
