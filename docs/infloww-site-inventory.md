# infloww.com site inventory (English pages)

**Source:** notes taken from a local, gitignored copy of infloww.com pages (`infloww.com/` in the repo root, never committed). The pages are Framer static HTML.
**Capture date:** every saved page carries the same Framer publish stamp, "Published Oct 10, 2026, 4:07 PM UTC" (verbatim, from an HTML comment). The `index.html` in the mirror shows "Published Oct 10, 2026". The mirror files were written to disk on 2026-10-12. The live homepage and /pricing were re-fetched on 2026-10-12 and carry the same publish stamp. Their visible text is identical to the mirror (see `infloww-landing-snapshot.md`).
**Machine-readable companion:** `docs/infloww-site-inventory.json` has one record per page. Each record has the title, meta description, date, author, h2s, word count, a topic bucket and a written gist. Feature posts also have `feature` and `feature_summary`. Parody writers should read the gists there.
**Quoting rule used here:** verbatim phrases are marked "(verbatim)" and kept under 15 words. Everything else is paraphrase.

## (a) Site map

| Area | Files | Notes |
|---|---|---|
| Top-level pages | 18 | index, pricing, download, contact, blog (index), case-studies (index), smart-messages, onlyfans-crm-enterprise, customer-success-at-infloww, infloww-affiliate, product-roadmap, infloww-vs-creatorhero, infloww-vs-onlymonster, switch-crm, tos, privacy-policy, cookie-policy, complaints-policy |
| Case studies | 5 | Modelify, Prime Pro Agency, Grey Matter Digital, FansHub, Coco Collaborative |
| Blog | 196 | 191 articles, plus 5 category index pages that sit in `blog/`: `fansly`, `fanvue`, `infloww`, `mym`, `onlyfans` |
| **English total in the inventory** | **219** | |
| Ignored | | The `de/`, `es/` and `fr/` translations. Two download-tool artifacts: `_downloads.html` (the crawler's index) and `﹟/index.html` (a duplicate of the homepage, saved from an in-page anchor link). |

**Blog metadata:**
- **Dates.** 167 of the 191 articles are dated 2024, 14 are dated 2025 and 10 are dated 2026. The newest is 2026-09-30 (Creator Reports). Nearly all of the generic OnlyFans content was published June to December 2024. Since then the blog has turned into product, Fansly, mym and Fanvue posts.
- **Category tags.** Each article shows exactly one tag: OnlyFans (158), Infloww (25), Fansly (4) or mym (4).
- **Authors (first name plus an initial).** Ambra A. and Savannah wrote 44 each, Robbie 28, Brunni C. 22, Grace 21, Nikki C. 14, Maddie 6, Christian 4 and Ebony 4. Two posts are by "Dorian - Growth & CRM Lead at mym" (verbatim), who is a guest author from mym. Fruzsina and "B.C." wrote one each. Grace writes almost all of the product posts.
- **Category page bug.** The Fanvue category page's `<title>` says "Fansly Growth & Management Tips | Infloww Blog" (verbatim). It is a copy-paste error.

## (b) Blog taxonomy (191 articles, 10 buckets)

Each article is assigned to exactly one bucket. The bucket is the `topic` field in the JSON.

1. **Money, taxes and payouts** (28)
   `average-income-for-onlyfans-creators`, `average-male-onlyfans-income`, `average-taxes-to-pay`, `claims-onlyfans-taxes-canada`, `creative-ideas-onlyfans`, `declare-onlyfans-income`, `declare-onlyfans-income-uk`, `how-much-do-onlyfans-creators-make`, `increase-onlyfans-earnings`, `onlyfans-1099`, `onlyfans-amazon-wishlist`, `onlyfans-bank-usa`, `onlyfans-creators-fees`, `onlyfans-earnings-potential`, `onlyfans-explicit-content-cost`, `onlyfans-free`, `onlyfans-free-subscriptions`, `onlyfans-guys-earnings`, `onlyfans-lucrative-woman`, `onlyfans-male-creators`, `onlyfans-money-deposit`, `onlyfans-payout-method`, `onlyfans-payout-not-in-bank`, `onlyfans-pricing-strategy`, `onlyfans-profit`, `onlyfans-tipping`, `onlyfans-w-9`, `tax-onlyfans-creators`
2. **Content ideas and niches** (25)
   `10-onlyfans-content-ideas`, `august-content-ideas`, `easy-things-to-sell-onlyfans`, `halloween-content`, `halloween-costumes`, `november-onlyfans-content`, `october-onlyfans-content-ideas`, `onlyfans-birthday-content`, `onlyfans-content-september`, `onlyfans-couples`, `onlyfans-creators-niche`, `onlyfans-feet`, `onlyfans-fitness-content-ideas`, `onlyfans-for-gaming`, `onlyfans-for-podcasters`, `onlyfans-goals`, `onlyfans-live-benefits`, `onlyfans-livestreams-tips`, `onlyfans-non-adult`, `onlyfans-partnership`, `onlyfans-without-showing-your-face`, `onlyfans-without-video-content`, `sell-hand-pics`, `summer-content-ideas`, `thanksgiving-content`
3. **Promotion channels (X, Reddit, Instagram, TikTok, YouTube, Discord)** (23)
   `apps-to-post-onlyfans-content`, `becoming-youtuber-onlyfans`, `instagram-onlyfans-promotions`, `link-twitter-onlyfans`, `onlyfans-10-new-subs`, `onlyfans-followers`, `onlyfans-instagram-issue`, `onlyfans-model-instagram`, `onlyfans-page-on-instagram`, `onlyfans-reddit-promotions`, `onlyfans-reel`, `onlyfans-tiktok-promotion`, `onlyfans-tiktok-promotion-permission`, `onlyfans-top-subreddit`, `onlyfans-x-growth`, `onlyfans-x-posting-schedule`, `onlyfans-x-proven-tips`, `onlyfans-youtube`, `promote-onlyfans-discord`, `reddit-3-things-to-know`, `reddit-worth-it`, `setup-discord-onlyfans`, `top-1-earners-marketing`
4. **Infloww feature and product posts** (22)
   `5-reasons-to-use-infloww-when-chatting`, `feature-comparison-infloww-onlyfans`, `getting-started-with-infloww`, `how-to-use-creator-reports`, `how-vault-pro-makes-content-management-easy`, `infloww-auto-follow`, `infloww-creator-reports`, `infloww-employee-reports`, `infloww-fanvue-partnership`, `infloww-messaging-benchmarks`, `infloww-nudge`, `infloww-passwordless-account-sharing`, `infloww-role-permissions`, `infloww-scripts`, `infloww-smart-automation`, `introducing-infloww-for-fansly`, `make-more-money-infloww`, `news-message-dashboard`, `news-vault-pro`, `scale-onlyfans-agency`, `start-more-conversations-with-fans`, `vault-pro-bulk`
5. **Platform guides and rules (OnlyFans rules, Fansly, mym, Fanvue, alternatives)** (21)
   `4-things-about-fanvue`, `delete-onlyfans-account`, `fansly-analytics-101`, `fansly-analytics-growth`, `fansly-growth-playbook-agencies`, `how-to-scale-on-mym`, `mym-growth-playbook`, `mym-traffic-playbook`, `onlyfans-account-rejected`, `onlyfans-alternatives`, `onlyfans-app`, `onlyfans-ban`, `onlyfans-banned-words`, `onlyfans-bypass-verification`, `onlyfans-checkmark`, `onlyfans-collaborations`, `onlyfans-down`, `onlyfans-fansly`, `onlyfans-verification-not-working`, `onlyfans-vs-facebook`, `why-agencies-are-sleeping-on-mym`
6. **Creator life, safety, stigma and legal** (19)
   `bulletproof-mindset-onlyfans`, `copyright-music-onlyfans`, `handle-boundaries`, `onlyfans-a-job`, `onlyfans-bad-influence`, `onlyfans-creator-origin`, `onlyfans-creators-safety`, `onlyfans-creators-stigma`, `onlyfans-empowering-creators`, `onlyfans-life-impact`, `onlyfans-mom-success`, `onlyfans-project-2025`, `onlyfans-ruining-porn`, `onlyfans-selling-other-photos`, `onlyfans-vs-porn`, `onlyfans-watermark-importance`, `protect-onlyfans-content`, `someone-who-start-onlyfans`, `support-onlyfans-creator-network`
7. **Getting started and profile setup** (18)
   `beginners-successful-onlyfans`, `boost-onlyfans-profile`, `mistakes-to-avoid-onlyfans`, `onlyfans-attractiveness`, `onlyfans-banner`, `onlyfans-best-time-to-post`, `onlyfans-bio-examples`, `onlyfans-checklist`, `onlyfans-creator-signup`, `onlyfans-demographic`, `onlyfans-for-beginners`, `onlyfans-must-knows`, `onlyfans-profile-picture`, `onlyfans-usernames`, `onlyfans-viewers`, `onlyfans-without-followers`, `onlyfans-work`, `why-your-onlyfans-bio-matters`
8. **Chatting, PPV and fan sales** (15)
   `content-teasing-onlyfans`, `conversational-chatting-onlyfans`, `customers-hate-ppv`, `exclusive-content-onlyfans`, `girlfriend-experience`, `onlyfans-chatter`, `onlyfans-messages`, `onlyfans-non-ppv-creators`, `onlyfans-personalized-chatting`, `onlyfans-welcome-messages`, `ppv-definition`, `ppv-frequency`, `sell-onlyfans-messages`, `sexting-101`, `thanksgiving-gratitude`
9. **Agency operations** (14)
   `diversification-growth-strategy`, `multi-platform-strategy`, `navigating-the-ai-transition`, `onboarding-creators`, `onlyfans-agency`, `onlyfans-agency-niche`, `onlyfans-business`, `onlyfans-call-models-tips`, `onlyfans-chatters-interview`, `onlyfans-legal-consideration`, `onlyfans-manager-roles`, `onlyfans-managers`, `social-media-onlyfans-agency`, `what-a-successful-creator-portfolio-looks-like`
10. **Photo, video and tools** (6)
   `better-onlyfans-pictures`, `cameras-onlyfans`, `onlyfans-must-haves-app`, `onlyfans-pictures-ideas`, `onlyfans-video-thumbnail`, `use-ai-on-onlyfans`

The 5 category index pages (`fansly`, `fanvue`, `infloww`, `mym`, `onlyfans`) have `topic: "hub"` and `category_index: true` in the JSON.

## (c) Blog house style

- **Length.**
  - The median article is about 1,200 words (mean 1,183).
  - Generic OnlyFans guides run 1,000 to 2,500 words. The longest is `increase-onlyfans-earnings` at 2,566 words.
  - Infloww feature posts are short: median 385 words, range 225 to 940.
- **Page anatomy, top to bottom:**
  1. Breadcrumb ("Blog > title").
  2. A category pill.
  3. H1 (the title).
  4. A one-line subtitle, styled as an H2.
  5. The author's first name and the date.
  6. A **direct-answer lead paragraph** that answers the title's question in 2 to 4 sentences. Examples: copyrighted music, "No, ... without a licence"; payouts, "seven days pending, then 1 to 5 business days". These leads read like a later rewrite for search and AI answer engines. They sit right on top of the original chatty 2024 intro ("Luckily, we've got you covered" and "Let's dive in", both verbatim).
  7. 4 to 12 H2 sections. The median is 5. About 15% of H2s are phrased as questions.
  8. A closing H2 that restates the title, for example "Getting paid on OnlyFans" or "Succeeding on OnlyFans as a beginner".
  9. Sometimes a "Common FAQs" table (11 posts) or a glossary ("Words you should know", 1 post).
  10. An "About the author" box with a one-line bio.
  11. The site-wide CTA band (see the next bullet).
- **Listicles.**
  - Numbered H2s are common: "1.", "#1:", "Step 1:", "Mistake #1:" and "Milestone 1:".
  - Each month gets a 30 or 31 H2 calendar ("August 1: Summer splash" and so on), for August, September, October and November.
  - Reddit roundups are a recurring format, with titles ending "according to Reddit" (verbatim). They quote Redditors by username.
- **CTA.**
  - Generic posts have no CTA in the body.
  - Every page ends with the same band: "Get started with Infloww today" / "Join over 5000+ agencies growing with Infloww." / "Start free trial" / "No credit card required" (all verbatim).
  - The template renders this band twice, once per breakpoint. On every blog page (191 files) the second copy is stale: it says "Join over 4000+ agencies growing with Infloww." (verbatim). So one page claims two different agency counts.
- **Feature-post closing.** Feature posts end with "Next steps", a 3 to 5 item imperative checklist. A typical item is "Send a mass message to fans' priority inbox" (verbatim, repeated across at least 4 posts). The list sometimes ends with "Start your free trial today." The Fansly launch post says "Sign up for a 7-day free trial" (verbatim). This is the only trial length stated anywhere on the site.
- **How often Infloww is plugged.**
  - In generic posts the plug is a single sentence: 129 of the 191 articles mention Infloww exactly once.
  - That one mention is almost always a bolted-on boilerplate clause. 172 articles contain "Infloww, a CRM for/built for OnlyFans agency owners…". 154 add "that also supports solo creators" (verbatim). 39 end a sentence with the formula "…also supports solo creators, reports on that" (verbatim fragment).
  - The clause gets grafted into places where it doesn't fit, for example the FAQ answer to "What content do OnlyFans Creators make?". It is the main parody target for the blog: an SEO/LLM-bait sentence stapled into every article.
- **Vocabulary quirks.**
  - "Creator" is capitalised, and adult creators are "Spicy Creators".
  - Two posts say outright that agencies call the role "chatters" but Infloww calls them "chatting assistant" or "engagement assistant" (verbatim).
  - "OFM" (OnlyFans management) appears on the comparison pages.
  - Product names carry ™: Smart Messages™, Messages Pro™, Vault Pro™ and Smart Lists™.

## (d) Case studies

All five follow the same template. A headline claim comes first, then 3 or 4 stat tiles (each rendered twice), then a direct-answer lead paragraph. After that come About, Challenge, Solution, Strategy, Operations and Results sections, and the page ends with "Next steps", which plugs Infloww as "a CRM built for OnlyFans agency owners" (verbatim). The two newest are videos with a written summary.

| Agency | Date | Headline claim and numbers | Notable details |
|---|---|---|---|
| **Modelify** (Paris, founder Tristan Vandevenne) | 2025-04-29 | 3x revenue in 18 months, to over $1M a month. Clients grew from 4 to 120, which they call "2900%". Employee onboarding is 6x faster, and Vault Pro saves 50 hours a week on uploads. | 300+ employees and 12 managers with about 30 staff each. Access is granted and revoked at every shift change. Employees share their screens over Discord so managers can watch them. Fan Notes record where each fan is from and what he does. They rejected Dolphin and GoLogin anti-detect browsers because those need the creator's password. |
| **Prime Pro Agency** (Italy, founder Luigi) | 2025-06-03 | +2,000% revenue in 10 months, to over $800K a month. Creators grew from 10 to 43 ("330%"). Onboarding is 3.5x faster. | Seven departments per creator: Marketing, Publishing, Creative, Leak Removal, Sales, Closers and Personal. Closers must close at least one $300+ package a day. Founder quote: "if you're not selling, you're not needed" (verbatim). |
| **Grey Matter Digital** (COO Elizabeth) | 2025-10-08 | Before/after monthly Fansly revenue per creator, with names changed: $3,000 to $11,259; $0 to $3,000; $0 to $990; $350 to $716; $200 to $1,637. | Same chatters work both platforms. Their For You Page tactics: 6 to 8 second clips and switching from scenery hashtags to identity hashtags. Quote: "you don't need this enormous vault" (verbatim). Their creators already make $10K to $120K on OnlyFans. |
| **FansHub** (UK/US, Finn) | 2026-06-05 (video) | No numbers. The rule is to move a creator to Fansly once they earn 40k a month. | Reasons given: protection against bans, a new audience, and the For You Page. |
| **Coco Collaborative** (Olivia, ex-creator and ex-engineer) | 2026-05-19 (video, filmed at AVN Las Vegas) | No revenue numbers. The headline anecdote is spending 48 hours deleting 8,000 promotional photos to restore one creator's brand. | Calls itself a "girls and gays-run" agency (verbatim) and rejects cookie-cutter management. Messages Pro is their favourite feature. |

**Testimonial quirk.** The Modelify founder's quote is credited to "Tristan, The Sweet Agency" on the enterprise page, but to "Tristan, Modelify" on the homepage and the comparison pages.

## (e) Comparison and switch pages

**`infloww-vs-creatorhero` and `infloww-vs-onlymonster`** use one template with the competitor name swapped.
- **Hero.** The kicker is "The stable CreatorHero alternative" (verbatim). The pitch is "Stop putting up with downtime" (verbatim), backed by **99.96% uptime**. The homepage says 99.99% "in the last 90 days", so the two pages disagree.
- **Proof stats.**
  - "over 465 million messages every month" (verbatim) for 5000+ agencies.
  - Support available 24/7/365 in English, Spanish and French.
  - An average resolution time of 8.42 minutes.
  - The OnlyMonster page adds a 1.03-minute average response time and an **86.9%** customer satisfaction score. Both are oddly precise.
  - "During emergencies" a developer team responds "in under five minutes" (both verbatim).
- **"The true cost of platform instability."** The page admits "Infloww is a premium investment" (verbatim). It then shows a downtime calculator: at $550,000 monthly portfolio revenue, a 3-hour outage costs $2,291.67. The arithmetic is monthly revenue / 720 hours x outage hours.
- **Feature lists.**
  - Messages Pro: AI Translator, Fan Insights, multi-window tabs, split inbox, and script sequences with auto-suggest.
  - Data: creator, employee and fan reports, plus an API in beta.
  - Security: encryption, 2FA and custom roles.
- **Comparison tables, "Accurate as of May 2026" (verbatim).** Cells use ✅, ☑️ (partial), ❌ and 🚧.
  - **OnlyFans table rows:** custom chat interface; fan insights "including spending power and chargeback risk" (verbatim); AI fan summary (Infloww 🚧, rivals ✅); AI translator; API; automated messages; advanced lists (Infloww 🚧 "New version coming soon"); Messages QA; creator, employee and fan reports; social media statistics (CreatorHero ✅, Infloww ❌); 2FA; Share for Share.
  - **Multi-platform table rows:** exclusive partnerships; Fansly, Fanvue and MYM integrations; chat interface, scripts and fan insights (each "Available on Fansly. MYM & Fanvue coming soon", verbatim); analytics (Infloww 🚧); roles and permissions.
  - Infloww's own tables show it losing or still building on some rows.
- **"Infloww is more than a software"** (verbatim).
  - Infloww Connect: private events with leadership.
  - **IF100**: "Exclusively available to the top 100 agencies on Infloww" (verbatim).
  - **MAKE**: a banking partner offering early access and reduced fees.
- **Closing offer.** "We'll take on the financial risk of your move" (verbatim): 60 days of migration coverage and a 6-week transition framework, if you qualify. The CreatorHero page also says Infloww will "cover your overlapping costs" (verbatim) while you move your roster.
- **FAQ.** The questions are only stubs, for example "Is Infloww a cheaper alternative to CreatorHero?" (verbatim). The answers aren't in the static HTML.

**`switch-crm`** has no competitor named.
- **Message.** The H1 is "Upgrade to the most stable CRM on the market" (verbatim). The argument is that "Smaller CRMs are struggling to keep up" and "When your CRM goes down, you stop earning" (both verbatim).
- **Content.** It repeats the same downtime calculator and feature blocks. The official MYM and Fanvue partnerships "guarantee stability" (verbatim). Fan Insights is described as "spending power and chargeback risk" (verbatim).
- **"Backed by the largest team in the industry"** (verbatim). Claims: 100+ developers, and private Telegram support with "Real human support, no AI" (verbatim). That sits oddly next to the AI Copilot, AI Chatbot and AI Autochat they sell.
- **Calls to action.** Every CTA is "Book a demo".

## (f) Other pages

- **Download.**
  - The desktop app downloads as Mac `.dmg` files for Apple Silicon and Intel, from `download.infloww.com/latest/`.
  - Requirements: macOS 12 Monterey or later, an Intel Core i5 or equivalent, 8GB RAM and 10GB of free storage.
  - A "Looking for the Windows download?" (verbatim) toggle exists, but the Windows link isn't in the static HTML.
  - There is no Linux build, no web app and no mobile app. The roadmap lists a "Mobile accessible Dashboard" as in progress.
  - The getting-started blog post says Infloww is desktop-only "for better performance, stability, and greater development potential" (verbatim).
- **Affiliate.**
  - The page offers "earn 10% of their first year's subscription" (verbatim) and says "There's no limit to how much you can earn" (verbatim).
  - Sign-up has "no screening needed" (verbatim). The affiliate link is under Referrals in the app.
  - Eligible affiliates include bloggers, educators, newsletters, influencers and "OFM community leaders and ambassadors" (verbatim).
  - The calculator example shows a 40-creator agency at 40 x $60 = $2,400, paying you $240. That is 10% of one month, not of a first year [inferred: the widget's arithmetic doesn't match its own promise].
  - The ToS (section 18) adds that referring a **Creator** pays **20%** of their first-year fees. Infloww can change referral amounts by notice and calculates earnings "at the sole discretion of Infloww" (verbatim).
- **Product roadmap ("We develop in the open", verbatim, on the comparison pages).**
  - The board has columns Planned (5), In discovery (0), In progress (7), In beta (4) and Done (24), plus a "Submit new feature" button.
  - **Planned:** Messages Pro 2.0, Fansly employee reports (overview and sales records), active device management and a device login list.
  - **In progress:** tracking-link overview updates, a mobile dashboard, Nudge timeliness, Messages Pro and Vault Pro for Fanvue, a Home Dashboard and multi-platform APIs.
  - **In beta:** Smart Lists enhancements, the Infloww API, shift scheduling, and **AI Autochat**: "A high-performing AI chatbot that drives fan monetization" (verbatim).
  - **Done:** includes AI Translator (30+ languages), Fan Insights ("Quickly identify whales" and flag chargeback risk, both verbatim), multi-window, a Country Leaderboard (rank your agency against local peers), 2FA, chat links, and sales records "built for fast, accurate payroll" (verbatim).
  - **Typo.** One card says "Insights into your team's performane" (verbatim).
- **Enterprise (`onlyfans-crm-enterprise`).**
  - The H1 is "The multi-platform CRM that scales with you" (verbatim). A second H1 variant says "The OnlyFans CRM that scales with you".
  - It is a sales-call page. Its claims are "5000+ agencies", "#1 OnlyFans Management Tool" (Community Choice), and **"$2.61 billion USD in revenue generated in 2024 by Infloww users"** (verbatim).
  - "Premium agency" perks: 24/7 support, dedicated account managers, priority access to features, and "Industry-leading data & creator protection" (verbatim).
  - It has the same 6 FAQs as the homepage. The JSON-LD again includes "No OnlyFans account managed through Infloww has been banned" (verbatim).
- **Customer Success.**
  - Perks: a dedicated CSM, strategy calls, an "Exclusive Telegram with our product team and C-level leadership" (verbatim), a newsletter, priority access to MAKE, MYM and Fanvue, invite-only catered "Infloww Connect" events, and early access to betas.
  - It ends with "Do I have a Customer Success Manager?" (verbatim). The answer is that if you're a customer you "may already" have one (verbatim).
- **Smart Messages.**
  - A Nudge claims block says "up to 50%" more fan engagement, "up to 89%" average increase in tips, and "up to 72.6%" average PPV revenue growth. An "up to … average" is a contradiction.
  - Priority messages land in the fan's Priority tab "while messages from other creators are hidden in the All tab" (verbatim).
  - Sequences come "with natural pauses and PPV" (verbatim).
  - Feature headline: "Never send the same media twice" (verbatim).
- **Contact.** A four-field form under "Talk to our team" (verbatim). Elsewhere: support@infloww.com, a HubSpot booking link, and a Telegram invite in the footer.
- **Blog index and case-study index.** Card listings with category tabs. See (a) and (d).
- **Legal pages.**
  - **Operator.** Infinni Innovations S.A., Spanish registration A55470629, Calle Maria Zambrano 42, Club de Campo Abama, Guia de Isora, Santa Cruz de Tenerife. The footer says postcode 38687, the ToS says 38630.
  - **Terms of Service (last updated June 22, 2025).**
    - Much of it is a fan-platform ToS: Content, "Co-Authored Content", Creator Earnings, release-form rules and an 18+ requirement. It reads as if adapted from a creator platform's terms rather than written for a CRM.
    - Fees and billing:
      - Subscriptions auto-renew.
      - Fees are invoiced at month end and due within 5 days. Creators pay by VISA or Mastercard; agencies by wire or card.
      - The agency fee is "based on the number of Creators" and "those Creator's monthly earnings" (verbatim). This is the earnings ladder, in contract form.
      - Infloww charges "including inactive, no revenue earned, or not-disconnected Creator accounts" (verbatim).
      - Billing is pro-rata for partial months.
      - Trial deposits are non-refundable. They can be used as credit for 6 months.
    - Termination is possible "for any reason" (verbatim).
    - Liability is capped at the lesser of fees paid or **USD 2,000**.
    - Spanish law governs. Disputes go to binding arbitration at the Santa Cruz de Tenerife Chamber of Commerce, with a class-action waiver.
    - Users may not scrape, mirror or frame the service.
    - Changes take effect 10 days after posting.
  - **Privacy Policy (last updated Aug 17, 2026).**
    - INFINNI is a controller for account and site data, and a processor for "Customer Data" (verbatim) put into the product.
    - It collects form, account, event and payment data. It also collects usage data (which features you use and how often) and IP and device data "for security and debugging purposes" (verbatim).
    - Payment banking credentials are sent to NetSuite.
    - Marketing may come via "WhatsApp or Telegram" (verbatim).
    - Retention is open-ended ("ongoing legitimate business need", verbatim).
    - The homepage FAQ's narrower promise ("only collect what's essential, like Creator rank and earnings", verbatim) isn't repeated here.
  - **Cookie Policy.** The body is **empty**. The page shows only the heading.
  - **Complaints Policy.** Investigation "within seven (7) business days" (verbatim). Unlawful or non-consensual content is removed, and copyright goes through a DMCA policy. It is written for a content host, not a CRM.

## (g) Things the parody can use

1. The boilerplate plug sentence in 172 of 191 blog posts, sometimes stapled into unrelated FAQ answers.
2. Two agency counts on one page: 5000+ and a stale 4000+.
3. Two uptime figures: 99.99% on the homepage and 99.96% on the comparison and switch pages.
4. Precise-sounding support stats: 8.42 minutes, 1.03 minutes, 86.9% CSAT.
5. The "$2.61 billion" users' revenue claim, and the same quote credited to two different agencies.
6. "Real human support, no AI" from a company whose roadmap is shipping an AI chatbot for fan monetization.
7. Employee Reports track "keystrokes per message". The Golden Ratio KPI (PPVs / messages, with an "8.79% sweet spot") comes from the benchmarks post.
8. Nudge's randomised delay, sold so the message doesn't seem "too eager or spammy" (verbatim).
9. Case-study ops: screen-sharing chatters over Discord, a quota of one $300+ package per day per closer, "if you're not selling, you're not needed".
10. Billing: inactive, zero-revenue creators are still billed; the price rises with creator earnings; trial deposits are non-refundable; liability is capped at USD 2,000.
11. The affiliate calculator that pays 10% of one month while promising 10% of a year.
12. The empty Cookie Policy page, and the Fanvue category page titled "Fansly".
