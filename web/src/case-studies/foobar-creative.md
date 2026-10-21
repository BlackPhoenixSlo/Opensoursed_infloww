---
title: "How Foobar Creative reviews chat quality with a five-point rubric instead of a gut feeling"
description: "A fictional agency scores ten threads per chatter per week on five criteria, then coaches on the lowest one. The rubric and the routine are below."
date: 2026-10-12
agency: "Foobar Creative"
tagline: "Eighteen chatters, a five-criterion rubric, and one coaching conversation a week. The software bill was not invited."
stats:
  - value: "$0"
    label: "Per creator per month x 30 creators = $0"
  - value: "10"
    label: "Threads reviewed per chatter per week"
  - value: "5"
    label: "Criteria, scored 0 to 2, for a total out of 10"
  - value: "0%"
    label: "Increase in software fees when creator number 30 signed"
quote: "Before the rubric, feedback was 'be better'. Now it is 'criterion 3, here is the thread, here is what to try'."
quoteBy: "Ade, head of chat, Foobar Creative"
---

Foobar Creative reviews chat quality by reading ten threads per chatter every week and scoring each on a five-criterion rubric, then coaching each chatter on their single lowest criterion. It is fair because everyone is scored the same way, and useful because the feedback is specific. The rubric is below.

## About

Foobar Creative is a fictional agency with 30 creators and 18 chatters. It runs Inflowwww on a VPS. Chatters sign in at `/chatter-login` and work in Messages Pro (`/messages-pro`). Owner pages such as Creators and Vault Pro are hidden from chatter-only sessions.

## Challenge

Quality reviews used to depend on who did them. One manager cared about speed, another about tone, a third about sales. Chatters got contradictory feedback and could not tell what "good" meant. The best chatters had no way to show it, and the struggling ones had no way to improve.

## Solution

A written rubric with five criteria. Each is scored 0 (missed), 1 (partly) or 2 (fully). A thread scores out of 10.

1. **Voice.** Does the reply sound like the creator, per their voice notes? Greetings, phrasing and words they never use.
2. **Accuracy.** Nothing promised that the creator has not approved. Nothing described that is not in the vault. No made-up availability.
3. **Boundaries.** The creator's written limits are respected every time, with no exceptions for a big spender.
4. **Fan care.** No pressure. A "no" or a "not now" from the fan is accepted the first time. Fans who asked for space get it.
5. **Continuity.** The chatter picked up context from earlier in the thread and from the shift handover, and left the thread in a state the next shift can follow.

Criteria 2, 3 and 4 are floors. A 0 on any of them goes to the manager the same day, whatever the total.

## Strategy

The rubric scores conversations, not people. Revenue is deliberately not a criterion. Per-employee numbers already live in Analytics > Employee reports (`/analytics/employee-reports`), and mixing sales into a quality score teaches chatters that pushing harder is how you pass review.

Each chatter gets one coaching point per week: their lowest-scoring criterion, with one real thread as the example and one thing to try. One point is enough to act on. Five points is a list nobody reads.

## Operations

Every Monday, each manager picks ten threads per chatter from the past week in Messages Pro. Half are random. Half are the longest threads, because that is where context slips. Scoring takes about two minutes per thread. Results go in a spreadsheet with one row per thread.

The coaching conversation happens on Wednesday and takes ten minutes. If an approved reply would have helped, it goes into Growth > Scripts (`/growth/scripts`) so the whole team has it.

Managers score a shared set of five threads once a month and compare. If they disagree by more than two points, they rewrite the criterion until they don't. A rubric only works if two people reading the same thread give it the same score.

## Results

- Every chatter knows exactly what is reviewed and how.
- Feedback points to a thread, not a mood.
- Boundary and accuracy issues surface within a day instead of when a creator complains.

We don't claim the rubric raised sales, and we chose not to measure it that way. It made the conversations consistent, and it made "good" something the team can point to.
