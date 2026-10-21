# Parody voice guide

Every parody page of infloww.com follows this guide.

## 1. Premise

We are Infloww's straight-faced corporate twin that charges $0: one self-hosted app that serves many agencies, each with its own logins. The comedy comes from playing their genre perfectly and flipping every claim into something the reader can check.

## 2. Voice rules

- Write short sentences in a confident SaaS register. Never wink at the reader.
- Use one joke per section at most. A section that is only useful is fine.
- Every joke lands on the business model (per-creator fees, earnings tiers, demo calls) or the SaaS genre (™, "#1", vanity stats).
- Jokes never target creators, sex workers, chatters, fans or Infloww's staff. Don't punch down.
- No sexual jokes, no innuendo, no puns on the content.
- No jokes about bans, account safety, ToS or legal trouble. When those topics come up, write them straight.
- Blog post bodies never repeat the OnlyFans Terms of Service sentence, because the deploy band at the foot of every post carries it; a post that needs to point at the risk links the disclaimer at `/legal/terms/#disclaimer`, never the README.
- The page has to work as a real page, even for a reader who misses every joke.

## 3. Recurring bits

Reuse these; don't invent new ones. Each bit at most once per page.

| Bit | Approved phrasings | Avoid |
|---|---|---|
| **The ™ habit**: they write Smart Messages™, Messages Pro™ and Vault Pro™. | "A Folder™"; "The .env File™ (not actually trademarked)"; "Your Own Disk™" | ™ on anyone else's product names (Docker, SQLite and Next.js are real marks) or on our screens that use Infloww's labels |
| **The earnings ladder**: their price goes up with what the creator earns. | "$0 at every bracket."; "Under $500: $0. Over $75,000: still $0."; "Our slider has one position." | "they tax your creators" (state the ladder and let the reader judge) |
| **No demo call** | "No demo call. The demo is `docker compose up`."; "Book a demo: open the README." | "nobody wants your call" |
| **No card form** | "No credit card required, because there is no card form."; "The checkout page is a git clone." | "free forever!!" |
| **One app, many agencies** | "Each agency account sees only its own creators."; "Every owner and every chatter has their own login." | "your own server" or any line that treats the reader as the only user; "100% secure", or any security promise |
| **Trusted by** | "Trusted by the people who read the code."; "Join everyone who ran `docker compose up`. We don't count." | install numbers |
| **Voted #1 by nobody** | "Voted #1 by nobody. We weren't in the poll." | mocking their polls or voters |
| **Uptime** | "Uptime is whatever your VPS does."; "An autoheal container restarts unhealthy services. The rest is your hosting." | "better uptime than them" |
| **Top talent** | "Our team: whoever reads the code and sends a fix."; "Hiring: open a pull request." | anything about their staff |
| **24/7 support** | "The README is open 24/7."; "No SLA, no hold music, no desk." | "support is overrated" |
| **NotBuiltYet** | "Shift schedule ships in our NotBuiltYet edition: the page is real, the feature is not."; "Coming when someone builds it. That could be you." | "coming soon" (it promises a date), "in beta" for a stub, or a ™ on NotBuiltYet |
| **About the author** | "The maintainers. Based wherever the app is installed." | parodies of their named authors or bios |

`web/src/index.njk` no longer says "No ™ on any of it"; keep it that way and use the ™ bit instead.

## 4. Truth rules

**Claims about Inflowwww.** We may claim only what README.md and docs/routes.md support.

- **Real:** Dashboard; Messages Pro (chat list, thread, fan insights); Analytics (Creator, Employee and Fan reports, Message dashboard); Growth (Smart Messages, Smart lists, Auto-follow, Profile promotion, Free trial links, Tracking links, Vault Pro, Scripts); My Automations (Auto Post, Auto Story); Creators (Manage creators, Custom proxy); Manage employees; Fansly accounts; a responsive web app for phones; an Electron desktop shell; optional LLM keys billed by the provider; MIT license; Docker Compose; SQLite.
- **NotBuiltYet stubs:** all 12 OF Manager sections, all 3 Share for Share sections, Shift schedule, the Settings tabs and Help center.
- **Does not exist:** a native phone app, mym, Fanvue, any uptime figure, any support desk, any AI Copilot. The legacy AI automations are off by default, so don't market them.

**Claims about Infloww.** Facts about Infloww come only from docs/infloww-landing-snapshot.md and docs/infloww-site-inventory.md.

- Every fact carries "(infloww.com, captured 2026-10-11)" or the inventory's date. Quote verbatim or not at all.
- Never invent their quotes or numbers, or go beyond their own words on security, bans or customers.
- No Infloww logo or screenshots.
- No claims about third parties (CreatorHero, OnlyMonster).

## 5. Blog rules

**Length and structure.**

- Posts are 500-900 words.
- Hook mirrors their genre: SEO-question H1, one-line subtitle, answer-first summary paragraph.
- 3-6 H2s, each with concrete, usable advice.
- End with one "The pitch" box whose "Deploy it yourself" links the install band on / (`/#deploy`), not the repo.

**Title flips** (their slug, then our title):

1. `average-taxes-to-pay`: "Do you have to pay taxes as an OnlyFans creator? Yes. Do you have to pay us? No."
2. `onlyfans-welcome-messages`: "How to change your OnlyFans welcome message. No CRM subscription required."
3. `infloww-creator-reports`: "How Inflowwww's creator reports track revenue from a database you own"
4. `5-reasons-to-use-infloww-when-chatting`: "5 reasons to use Inflowwww when chatting with fans. Reason 5 is the price."
5. `customers-hate-ppv`: "Why do customers hate PPV? Notes from a product that charges per nothing."
6. `how-vault-pro-makes-content-management-easy`: "How Vault Pro makes content management easy, with no meter per creator"
7. `infloww-messaging-benchmarks`: "Inflowwww messaging benchmarks: exactly as fast as your box"
8. `onlyfans-down`: "Is OnlyFans down? How to check before you blame your VPS"
9. `scale-onlyfans-agency`: "How to scale an agency without your software bill scaling with it"
10. `getting-started-with-infloww`: "Getting started with Inflowwww: one command, after the README"

**Feature posts.** Write about our equivalent, honestly, and name the route.

- If the screen is a stub, say so in the first paragraph with the NotBuiltYet note.
- No equivalent: write the general how-to and leave the product out.

**Sensitive topics.**

- **Taxes, payouts and legal** (`average-taxes-to-pay`, `declare-onlyfans-income-uk`, `claims-onlyfans-taxes-canada`, `onlyfans-1099`): keep the advice generic and add "Not tax advice."
  - Link IRS.gov, gov.uk (HMRC) or canada.ca. No rates or thresholds without the official page and year.
- **Safety, stigma, boundaries and wellbeing** (`onlyfans-creators-safety`, `onlyfans-creators-stigma`, `handle-boundaries`): write them sincerely.
  - No jokes in the advice. The parody lives only in the frame and the pitch box.
- **Do not write these as how-tos:** `onlyfans-bypass-verification`, `onlyfans-ban` and `onlyfans-banned-words`. Rewrite them as "follow the platform's rules; here is where to get support", or skip them.

**Front matter.** The file is `web/src/blog/<their-slug>.md`. `web/src/blog/blog.json` sets the layout and the permalink (`/blog/<file-slug>/`), so leave both out. The byline, reading time and author box come from the layout.

```yaml
---
title: "Our title, from the title flips above or in the same register"
description: "One sentence for the card, the meta description and the feed."
date: 2026-10-12
tags: ["money", "taxes", "self-employment"]  # first tag is the bucket, the rest are free topics
parodyOf: "average-taxes-to-pay"             # their slug; the post links to infloww.com/blog/<slug>
parodyTitle: "Do you have to pay taxes as an OnlyFans Creator?"  # their title, verbatim
parodyDate: "Jul 19, 2024"                   # their visible date, verbatim, or "" if none
---
```

- **Bucket** (first tag): one of `product`, `getting-started`, `money`, `chatting`, `content-ideas`, `promotion`, `platforms`, `agency`, `creator-life`. The list, labels and blurbs live in `web/src/_data/buckets.json`. Only buckets get a `/blog/tag/<bucket>/` page.
- **Free tags:** lowercase and hyphenated. They show as plain text on the post and get no page.
- Quote every string. `date` stays unquoted and is our publish date (`2026-10-12`); their date goes in `parodyDate`. With `parodyDate: ""` the byline says "their page stamped Oct 10, 2026". Add `straight: true` when the post is sincere advice; it swaps the Parody badge for a "Straight advice" label.

## 6. Case studies

- Agencies are fictional, with generic names ("Example Talent Co.") that you have searched to confirm no real agency uses.
- The frame says, near the top: "Fictional, and labelled so. Real users have not written in yet."
- Mirror their structure: four stat tiles, a summary, then About, Challenge, Solution, Strategy, Operations, Results.
- Stat tiles are obviously jokes and still true:
  - "$0 per creator per month x 40 creators = $0"
  - "0% increase in software fees"
  - "1 command to install, after the README"
  - "0 demo calls attended"
- Never claim the software raises revenue. Quotes come from personas labelled "(fictional)".

## 7. Comparison pages

- Every row of "Inflowwww vs. Infloww" is checkable: their own words with the capture date, against our file, route or README line.
- Where we lose, say so plainly: no 24/7 support, no uptime SLA, no mym or Fanvue, no native phone app, some screens NotBuiltYet. Losing honestly is part of the bit.
- No rows about bans or security outcomes.

**Other pages:**

- **Download:** the Electron shell and the responsive web app.
- **Affiliate:** "We pay 0% commission on $0."
- **Roadmap:** VISION.md plus the list of stubs.
- **Legal:** a light frame; the MIT license and disclaimer stay unchanged.

## 8. Pre-finish checklist

1. Every Inflowwww claim traces to README.md or docs/routes.md.
2. Every Infloww fact is verbatim from the snapshot or inventory, with its capture date.
3. No invented Infloww quotes, numbers or customers.
4. Every stub mentioned is marked NotBuiltYet.
5. At most one joke per section, and each joke hits the model or the genre.
6. Nothing makes fun of creators, sex workers, chatters, fans or staff.
7. No sexual jokes, and no jokes about bans or the law.
8. The page is useful with the jokes deleted.
9. Recurring bits use the approved phrasings, each once at most.
10. Posts: 500-900 words, 3-6 H2s, front matter, one pitch box.
11. At most one exclamation mark. No emoji.
12. Sensitive pages: "Not tax advice" or official links, and no jokes in the advice.

## 9. Banned

- **Words:** "scam", "rip-off", "greedy", "lol", "game-changer", "unlike our competitors" (without a checkable fact), "we're not like them", "ban-proof", "undetectable".
- **Formatting:** emoji, more than one exclamation mark per page, all-caps shouting.
- **Moves:**
  - Calling Infloww dishonest.
  - Guessing their margins, revenue or customer counts.
  - Fake testimonials that are not labelled.
  - "Coming soon" with no date.
  - Writing the same "No X. No Y. No Z." triplet more than once per page.
