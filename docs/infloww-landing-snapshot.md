# Infloww marketing site: structural snapshot

**Capture date:** 2026-10-11
Re-checked 2026-10-12: no changes.
The saved copy of `infloww.com/pricing.html` has the same publish stamp and the same visible text as live /pricing, so it matches this snapshot. The JS chunk still has the same 12-step price ladder.
**Purpose:** a reference for the Inflowwww parody landing page, so it can copy Infloww's section order and tone. No images, logos, or other assets were downloaded.

## 1. Sources

| URL | How it was fetched | Result |
|---|---|---|
| https://infloww.com/ | WebFetch and raw HTML via curl | Clean. The page is server-rendered by Framer (`<meta name="generator" content="Framer 0da2bc6">`). The page shows "Published Oct 10, 2026". |
| https://infloww.com/pricing | WebFetch and raw HTML via curl | Clean. The tier text and the earnings-bracket labels are in the HTML. The price for each bracket is filled in by JavaScript (see the next row). |
| https://framerusercontent.com/sites/XyQqLr09jape7hoNdkRhh/1oeyqSIkRJOJydKITaZtrZvRRXkHPnaA9g_2Aolt6oY.B9GW4jxH.mjs | curl. This is the pricing page's own Framer JS chunk, from Infloww's own CDN. | Clean. It contains the mapping from earnings bracket to price, verbatim. |
| FAQ answers | The JSON-LD `FAQPage` block in the raw HTML of /pricing | 4 of the 6 answers are present. The answers to "What metrics can I track?" and "How do I get started?" are in neither page's HTML or JSON-LD. They are probably loaded on click. |
| WebSearch (trial length, third-party pricing) | 2 queries | Nothing usable. No third-party source gave a trial length. |

- No archive.org or r.jina.ai fallback was needed, because both pages came back fully rendered.
- The top nav has no separate "Features" page or "FAQ" page. "Features" is an in-page anchor in the mobile menu, and the FAQ is a section on both pages.
- Download, Help, Resources sub-pages, and the comparison pages were **not** fetched.

## 2. Landing page (https://infloww.com/) sections, top to bottom

- **Page `<title>`:** "Infloww | The #1 CRM for OnlyFans and beyond"
- **Meta description:** "The operating system powering the world's top creator agencies. Manage creators across OnlyFans, Fansly, Fanvue and MYM."

1. **Top nav bar.** See section 3.

2. **Hero.** Centered hero with a pill badge above the heading, a primary and a secondary CTA, and a small note under the primary CTA.
   - Badge: "Trusted by 5,000+ agencies". It links to the case studies.
   - H1: "The #1 CRM for OnlyFans and beyond"
   - Subtext: "Grow your agency revenue across OnlyFans, Fansly, MYM, and Fanvue with the operating system top agencies already run on."
   - CTAs: "Start free trial" (primary) and "Watch demo" (secondary).
   - Note under the primary CTA: "No credit card required"

3. **"Why choose Infloww?"** A 6-card grid with an icon, a title, and one line per card.
   - **Data security:** "Unlike other platforms, we don't run an OnlyFans agency—your data is safe with us."
   - **Better performance:** "Messages Pro is the fastest chatting solution on the market, up to 40% faster than other tools in the market."
   - **Your safety comes first:** "Each creator is assigned a unique IP to ensure your accounts stay secure."
   - **Uptime guarantee:** "With 99.99% uptime in the last 90 days, our investment in infrastructure ensures uninterrupted service you can rely on."
   - **Top talent:** "Our team includes experts from top tech companies like Microsoft, TikTok, and Facebook…"
   - **24/7 support:** "Our dedicated team ensures you always have the help you need, when you need it."

4. **"Grow your revenue faster."** A feature block: a heading and an intro, then 4 feature items beside a product visual, then a CTA.
   - Intro: "Use powerful messaging features to personalize communication, re-engage fans, and drive faster revenue growth."
   - Items: "Message online fans", "Smart Messages™", "Priority mass messages", "Smart lists"
   - CTA: "Try for free"

5. **"Make more by knowing what drives your growth."** Same layout as the previous block, with 4 items.
   - Intro: "From quality assurance to scheduling and analytics, you'll have the insights and tools to maximize your earnings."
   - Items: "Message dashboard", "Fan reports", "Employee reports", "Employee shifts"
   - CTA: "Try for free"

6. **"Increase efficiency with our AI Copilot".** Same layout, with an "In Beta" tag and 4 items.
   - Intro: "Our AI tool learns from every interaction and adapts to your creator's style, ensuring each message feels authentic."
   - Items: "Context-awareness", "Your digital clone", "Real-time auto-suggestions", "Messages Pro™"
   - CTA: "Try for free"

7. **"We've helped thousands grow".** 3 testimonial quote cards, each showing a first name and an agency.
   - **Tristan (Modelify):** "Fast client support, actually listening and implementing feedback, the stability of the software, constantly implementing new capabilities…"
   - **Luigi (Prime Pro Agency):** "The Infloww team is lovely and always available."
   - **Jonathan (Ascending Lights Agency):** "Been using Infloww since May 2023 and I'm really satisfied." His quote also mentions "over 20 employees".
   - [uncertain] Whether this is a carousel or a static row. Static HTML can't tell the two apart.

8. **"Your all-in-one multi-platform management solution".** A 12-card feature grid.
   - Intro: "Powerful growth and analytics tools made to help boost your fanbase and earnings."
   - Cards: Vault Pro™, Smart Messages™ ("in beta"), AI Copilot, Messages Pro™, Split Inbox ("up to 9 groups"), Analytics, Scripts, Auto-renew campaigns, Free trial & tracking links, Insights panel, Unique proxies, Block sensitive words.

9. **"Voted the #1 creator CRM by the community".** Social proof built from 2 embedded community poll screenshots, plus a "Start free trial" CTA.
   - **Poll 1** ("Chatters Venture OF", 155 votes): Infloww 59%, Supercreator 18%, CreatorHero 13%, BuddyX 8%, OnlyMonster 3%.
   - **Poll 2** ("OF Empire", 670 votes): Infloww 50%, Supercreator 15%, Other 7%, OnlyMonster 5%, plus one option whose label is unclear [uncertain].

10. **"Frequently asked questions".** An accordion with 6 questions. See section 7.

11. **"Get started with Infloww today".** A closing CTA band.
    - Text: "Join over 5000+ agencies growing with Infloww."
    - Button: "Start free trial"
    - Note: "No credit card required"

12. **Footer.** A tagline, then link columns, then legal and company info. See section 3.

## 3. Navigation

**Top nav, desktop (verbatim):**
- Left: logo, then **Pricing · Download · Resources · Help**. Resources and Help appear to be dropdowns [inferred].
- Right: language selector ("English"; the site also has es, fr, and de), **Book a demo** (secondary button), **Start free trial** (primary button).

**Mobile / secondary menu (verbatim):** About · Integration · Features · Blogs · Get Started [inferred: these are in-page anchors].

**Footer.** Tagline: "The #1 management tool for creator agencies". The link groups, verbatim (the typo "Customer Succes" is in the original):

| Product | Company | Resources | Legal | Comparison |
|---|---|---|---|---|
| Pricing | Careers | Blog | Terms | Infloww vs. CreatorHero |
| Releases | News | Affiliate | Privacy | Infloww vs. OnlyMonster |
| Changelog | Media Kit | Help Center | Cookies | Switch to Infloww |
| | Customer Succes | Tutorials | Complaints | |
| | Contact | Support | Status | |

**Legal line:** "©2026 Infloww. All rights reserved. Infloww is a registered trademark. Infinni Innovations S.A. Maria Zambrano 42, Club de Campo Abama Parcela 4-B1 Santa Cruz de Tenerife 38687 Spain"

## 4. Pricing (https://infloww.com/pricing)

- **Page `<title>`:** "Infloww Price Breakdown: Plans & Features for your Growth"
- **Meta description:** "Explore Infloww's transparent pricing plans. Find the right subscription to fit your budget and scale your business with our flexible options. No hidden fees."
- **H1 / intro:** "Manage all your creators with one CRM". "Every Infloww plan includes all our unique features, full-platform security with encryption and two-factor authentication, and 24/7 technical support."

**Billing basis.** Every tier is priced **per creator profile, per month**. The page says "Monthly pricing per creator profile" and "Billed monthly".
- There is no per-seat or per-chatter pricing.
- There is no annual toggle.
- There is no Enterprise or "Contact sales" tier. The only sales touchpoint is a "Questions? We're here to help." block with a **Book a demo** button.

**One plan card per platform:**

| Tier (verbatim) | Headline price | Basis | Features listed as included (verbatim) |
|---|---|---|---|
| Infloww for OnlyFans | "Starting at just $40" | Per creator profile, monthly, **scales with the creator's monthly earnings** (see the slider below) | Messages Pro ™, Smart Lists ™, Smart Messages™, Vault Pro ™, Infloww AI Copilot (in beta), Message dashboard, Auto-messages, Priority Mass Messages, Built-in proxies, Sensitive word blocker |
| Infloww for Fansly | "Starting at just $40" | Per creator profile, monthly, with the same earnings slider | Roles and permissions, Centralized chat inbox, Fan insights, PPV history and timeline, Scripts. One variant also lists Built-in proxies. |
| Infloww for mym | "Starting at just $50" | Per creator profile, monthly, flat (no slider) | Centralized chat inbox, Roles and permissions, Shift scheduling, MYM Cloud, Notifications |
| Infloww for Fanvue | "Starting at just $50" | "Monthly pricing per creator profile until 30 June 2026", flat (no slider) | Centralized chat inbox, Roles and permissions, Shift scheduling, Notifications |

**Fanvue caveat.** The qualifier "until 30 June 2026" is already in the past on the capture date. The page does not say what Fanvue pricing is now [uncertain].

**Earnings slider ("Creator's monthly earnings").** These are the prices per creator profile per month. They come verbatim from the pricing page's own JS chunk (`{label, price}` array):

| Creator's monthly earnings | Price / creator / month |
|---|---|
| Under $500 | $40 |
| $500.01 – $1,000 | $50 |
| $1,000.01 – $2,000 | $65 |
| $2,000.01 – $5,000 | $70 |
| $5,000.01 – $7,500 | $90 |
| $7,500.01 – $10,000 | $125 |
| $10,000.01 – $15,000 | $175 |
| $15,000.01 – $30,000 | $225 |
| $30,000.01 – $45,000 | $275 |
| $45,000.01 – $60,000 | $300 |
| $60,000.01 – $75,000 | $400 |
| Over $75,000 | $500 |

- Only one such array exists in the bundle, so OnlyFans and Fansly appear to share the same ladder [inferred].
- **In short:** the price is a tax on how much the creator earns. The more the model makes, the more Infloww charges per model. This is the obvious target for the parody ($0, self-hosted, no earnings ladder).

**Free trial.**
- Every card has a "Start free trial" button that leads to signup.infloww.com.
- The site says "No credit card required" (homepage hero and closing band).
- The trial length is **not stated** on any fetched page, and WebSearch found no reliable figure [unknown].

**FAQ answer on cost (verbatim):** "Starting at as little as $40 a month you'll have access to all our features. See our pricing page for more information."

## 5. Tone: verbatim phrases to flip

1. "The #1 CRM for OnlyFans and beyond"
2. "The operating system powering the world's top creator agencies."
3. "Trusted by 5,000+ agencies" / "Join over 5000+ agencies growing with Infloww."
4. "Your all-in-one multi-platform management solution"
5. "Messages Pro is the fastest chatting solution on the market, up to 40% faster than other tools in the market."
6. "With 99.99% uptime in the last 90 days…"
7. "Unlike other platforms, we don't run an OnlyFans agency—your data is safe with us."
8. "Your digital clone" / "Our AI tool learns from every interaction and adapts to your creator's style, ensuring each message feels authentic."
9. "Voted the #1 creator CRM by the community"
10. "Every Infloww plan includes all our unique features" (which sits right above per-platform feature lists that differ)
11. "Explore Infloww's transparent pricing plans… No hidden fees." (the per-bracket prices only appear when you move the slider)
12. "No OnlyFans account managed through Infloww has been banned." (from the FAQ)

**Trademark habit.** They put ™ on everything: Smart Messages™, Messages Pro™, Vault Pro™, Smart Lists™.

## 6. Visual notes

- **Theme: light.**
  - The body background is forced to `rgb(255, 255, 255)`.
  - Text is mostly black (`#000`, `rgba(0,0,0,0.62–0.64)` for body copy, `#292929`).
  - Many blocks have `background-color: rgb(0,0,0)`. These are the black primary buttons and dark cards.
- **Accent: there is no strong brand color in the CSS.** The look is monochrome black and white, plus a few soft accents:
  - warm off-white / cream `#f1ede5` (with alpha variants)
  - neutral greys `#f4f4f5`, `#fafafa`, `#71717a`
  - near-black `#0d0d0d`, `#090909`, `#020015`
  - pale green `#b9e1b4`, dark green `#00805e`
  - yellow `#fcd879`, peach `#f0c992`
  - lavender `rgb(142,140,242)` (appears once)
  - Framer default link blue `#09f`
  - Which of these colors goes on which element is [inferred] from frequency only.
- **Fonts:**
  - **Suisse Int'l** (Regular / Medium / Semi Bold): the headings and the pricing widget, which uses `fontFamily: "Suisse Int'l", sans-serif`.
  - **Inter**: body and UI text.
  - **Satoshi** and **Roboto** also appear. Roboto is probably from embedded widgets [inferred].
- **Built with:** Framer.

## 7. FAQ (identical on the homepage and /pricing)

The questions are verbatim. Four answers come from the page's JSON-LD.

1. **Why do I need Infloww?**
   "Infloww is designed to help agencies take their OnlyFans to the next level. With our powerful suite of features and AI automations, our platform helps you make more money, increase speed & streamline your workflows. All while keeping your creator's accounts safe."
2. **What makes Infloww different from other platforms?**
   "Infloww is trusted by thousands of OnlyFans agencies worldwide for our powerful features, stability & 24/7 support. Infloww is a tech company (not an agency). Our team includes experts from other top tech companies like Microsoft, TikTok & Facebook. We're proud to have this exceptional talent constantly bringing you new updates that help you succeed."
3. **Is Infloww safe?**
   "We use the latest encryption to protect your data and only collect what's essential, like Creator rank and earnings. Unlike our competitors, we don't run an agency, and we never sell or share your information—your content remains completely yours. Our platform simulates normal user behavior, while enhancing your OnlyFans experience with powerful messaging features, in-depth analytics and team management tools. No OnlyFans account managed through Infloww has been banned."
4. **How much does Infloww cost?**
   "Starting at as little as $40 a month you'll have access to all our features. See our pricing page for more information."
5. **What metrics can I track?** The answer was not in the static HTML or the JSON-LD [not captured].
6. **How do I get started?** The answer was not captured [not captured].

## 8. Sign-in and sign-up pages, captured 2026-10-12

**How fetched:** curl for the redirects and raw HTML, then headless Chromium (Playwright) for the rendered
text, links and inputs, because both pages are client-rendered. Plus the saved screenshot
`docs/infloww-signup-snapshot-2026-10-12.png`. No assets were downloaded.

### Sign-up: https://signup.infloww.com/ (every "Start free trial" and "Try for free" on infloww.com links to `signup.infloww.com/en`)

- **`<title>`:** "Infloww | Signup"
- **Theme:** the saved screenshot is dark; the headless capture rendered the same page light (white page, black
  text, pale grey inputs, a peach-tinted disabled button). It appears to follow the browser's colour scheme
  [inferred].
- **Chrome:** no site nav. Logo and "INFLOWW" wordmark top left (links to infloww.com), a language picker
  top right ("English", globe icon, chevron), "© 2026 Infloww" bottom left. A cookie consent banner
  (Cookiebot: Necessary / Preferences / Statistics / Marketing, "Allow all", "Reject all") covers the page on
  first load.
- **Layout:** two columns. Form on the left, pitch on the right.
- **Left column, top to bottom (verbatim):**
  1. H1 "Sign up"
  2. "Email address", text input, placeholder "name@agency.com"
  3. "Password", password input, placeholder "Create a password", with a show/hide eye button
  4. Hint: "Must be at least 8 characters"
  5. Checkbox: "I agree to the Privacy Policy and Terms of Condition". "Privacy Policy" links to
     `infloww.com/privacy-policy`, "Terms of Condition" to `infloww.com/tos`.
  6. "Let us know you're human", above a Cloudflare Turnstile box ("Verify you are human"; "Success!" once
     passed)
  7. Button: "Sign up with email" (orange; disabled until the form is complete)
- **Right column (verbatim):**
  - Headline: "Accelerate your agency's success."
  - Text: "Sign up and access all features for 7 days—no credit card needed. Get started in just two minutes."
  - Two badges: a laurel wreath with five stars, "Community Choice (Since 2022)", "#1 OnlyFans Management
    Tool"; and a shield with a tick, "Trusted by", "4,000+ agencies", four avatar circles and an arrow.
- **Not on the page:** no "Already have an account? Sign in" link, and no sign-in link of any kind.
- The trial length ("7 days") appears here and nowhere on the pages captured on 2026-10-11 (section 4).

### Sign-in: no web sign-in page found

- `infloww.com/signin` and `infloww.com/sign-in`: 404.
- `infloww.com/login`: 308 redirect to `https://login.infloww.com/`, titled "Login | Infloww" (`noindex`). It is
  not an agency sign-in form. It reads "Infloww Login+", "The login assistance to access your Creator account
  on Infloww", with "iOS Download" (a TestFlight link) and "Android Download" (an APK link), and the legal line.
  No fields.
- `app.infloww.com` and `app.infloww.com/login`: title "Infloww Share for Share", text "Infloww's Share for
  Share service operates within the Infloww CRM. To learn more, check out our website." No fields.
- `signup.infloww.com/login` and `/signin`: 404.
- infloww.com's own nav has no "Log in" link (section 3).
- **So the sign-in layout is assumed, not captured:** the parody `/login/` page uses the sign-up page's layout
  with Email address + Password + "Forgot password?" + "Sign in" + "Don't have an account? Sign up". Do not
  quote any of it as theirs.
