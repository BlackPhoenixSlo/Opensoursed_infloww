---
title: "How Placeholder Partners stopped losing context between chat shifts"
description: "A fictional agency with three shifts a day adopts a five-line handover note. The template is below, and it costs nothing in any CRM."
date: 2026-10-12
agency: "Placeholder Partners"
tagline: "Three shifts a day, one five-line note per shift, and a software bill that never clocks in."
stats:
  - value: "$0"
    label: "Per creator per month x 8 creators = $0"
  - value: "5"
    label: "Lines in the handover note template"
  - value: "10 min"
    label: "Overlap between outgoing and incoming chatter"
  - value: "0"
    label: "Demo calls attended. The demo is docker compose up."
quote: "The note takes five minutes to write. Explaining to a fan why we forgot what they said took longer."
quoteBy: "Marco, shift manager, Placeholder Partners"
---

Placeholder Partners keeps conversations consistent across three daily chat shifts with one habit: every outgoing chatter writes a five-line handover note, and the incoming chatter reads it before sending anything. The template is below and works in any tool.

## About

Placeholder Partners is a fictional agency with 8 creators and 12 chatters working in three eight-hour shifts. It runs OnlyFans accounts from an Inflowwww install on a small VPS. Managers use Messages Pro (`/messages-pro`) for the inbox and Analytics for the numbers.

## Challenge

A fan would mention something on the morning shift, a birthday or a custom request, and the evening chatter would not know. Promises were made and not kept. Fans noticed, and they were right to. The chat history was there, but nobody has time to read 200 messages back at the start of a shift.

## Solution

A short note, written by the person who knows, read by the person who needs it. The note lives in a shared document with one section per creator, newest shift on top. It has exactly five lines:

1. **Open promises.** Anything a chatter said would happen: "said we'd reply about the custom by tonight."
2. **Pending customs.** Requests in progress, with where they stand. Analytics > Message dashboard (`/analytics/message-dashboard`) has a customs tab to check against.
3. **Fans to leave alone.** Anyone who asked for a break, or who should not get a mass message today.
4. **Context worth knowing.** One line per fan, at most three fans. Example: "back from travel, mentioned it twice."
5. **Anything odd.** A session that needed recapturing, a page that would not load, a question for the manager.

If a line has nothing in it, the chatter writes "none". An empty note and a forgotten note look the same, and "none" tells them apart.

## Strategy

The note is for continuity, not for monitoring. Managers read the notes once a day to spot patterns: the same promise carried for three shifts means a process is stuck somewhere. Nobody is graded on their notes. The only rule is that they exist.

## Operations

Shifts overlap by ten minutes. The outgoing chatter writes the note in the first five; the incoming chatter reads it and asks questions in the last five. Then the incoming chatter opens Messages Pro and starts with the fans named in lines 1 to 3. The fan insights rail beside each thread covers the rest.

The rota itself lives in a spreadsheet. Inflowwww has an Employees > Shift schedule page (`/employees/shifts`), and it is a NotBuiltYet stub: the page is real, the feature is not. The handover note never depended on it.

## Results

- Open promises are now visible to every shift, so they get kept or closed.
- New chatters ramp up faster, because the notes show what good context looks like.
- Managers spend their daily review on stuck items, not on reconstructing what happened.

We do not claim the note made anyone more money. It made the conversations make sense from one shift to the next, which is what fans notice first.

## Copy the template

```
Creator: ______    Shift: ______    Chatter: ______
1. Open promises:
2. Pending customs:
3. Fans to leave alone:
4. Context worth knowing (max 3 fans):
5. Anything odd:
```
