---
title: "Nudges: the online-fan messages we switched off by default, and what to do instead"
description: "How to reach fans who are online today by hand and with care, and why Inflowwww keeps its older nudge automations switched off."
date: 2026-10-12
tags: ["product", "smart-messages", "fan-engagement"]
parodyOf: "infloww-nudge"
parodyTitle: "Infloww’s Nudge: automated messages when fans come online"
parodyDate: "Dec 20, 2024"
image: "messages-pro-combo.webp"
imageAlt: "Messages Pro on desktop and phone: a fan chat list and an open thread with an image and a PPV"
---

An automatic message the moment a fan comes online sounds like free conversations. Inflowwww does not ship that feature. This post says where the old code is, why it is off, and how to catch online fans well without it.

## Where nudges stand in Inflowwww

The codebase has older automation screens, nudges among them, from the project it grew out of. They are hidden, and their routes return 404, unless the app container runs with `OPENINFLOWW_LEGACY_AUTOMATIONS=1`. That line is commented out in `docker-compose.yml`, and the README documents it as legacy.

The product's scope is the dashboard screens plus two automations, Auto Post and Auto Story. The automated-trigger half of **Growth > Smart Messages** (messages that fire on fan actions) is not built. So we do not recommend the flag, we do not document the old screens, and this post will not tell you how to tune them.

## Catch fans while they are online, by hand

{% shot "messages-pro.webp", "Messages Pro with a fan chat list and an open conversation", "Messages Pro, where a chatter answers online fans by hand. Demo data." %}

You can do most of what a nudge does with a person and two screens.

1. In **Messages Pro**, use **Sort by** and the fan insights rail. **Last seen** tells you who was just on.
2. Keep a short list of openers in **Growth > Scripts**: a question about something the fan mentioned before, a note about a new post, a simple hello at their usual time.
3. Use the fan's **Notes** to make the opener specific. "How did the interview go?" beats "hey, you there?"

A chatter who works the most recently seen fans for the first 15 minutes of a shift starts more real conversations than any timer.

## Reach recently active fans in one go

When you want to reach many fans who have been around lately:

1. In **Growth > Smart lists**, make a list with a rule for fans active within the last few days.
2. In **Growth > Smart Messages**, send that list a mass message at the hour your fans are usually online. The Message dashboard export tells you when that is.
3. Exclude a Smart list of your top spenders. They should hear from a person, not a broadcast.

Write mass messages as an announcement: say what is new and why this fan might care. Leave out questions that pretend to be personal, because fans can tell a broadcast from a chat.

## A softer signal: likes, not messages

**Growth > Auto-follow** has a **Like latest message** action. It likes a fan's most recent message, which shows up for them as a notification, not a DM. Set a small daily cap and a cooldown of several days per fan, and start in dry run. It is a light way to say "still here" without asking for anything.

## If you message on a schedule, keep it human

Whatever you send, by hand or in bulk:

- **Vary the words.** Keep several versions of each opener and rotate them.
- **Stop when they reply.** A real reply deserves a real person.
- **Limit frequency.** Once a week is plenty for anything automated-feeling.
- **Respect silence.** A fan who never answers broadcasts is telling you something.
- **Never pretend.** Do not dress up a broadcast as a one-to-one message.

## Next steps

1. Add three openers to **Growth > Scripts**.
2. Start the next shift with 15 minutes on the most recently seen fans.
3. Build an "active in the last 3 days" Smart list and send one mass message at your peak hour.
4. Compare replies in the **Message dashboard** a week later.

> **The pitch.** Every message in this post is written by a person and sent from Messages Pro or Smart Messages, at $0 per creator. [Deploy it yourself]({{ '/#deploy' | url }}).
