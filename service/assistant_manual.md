---
kinds: [apply_profiles, auto_follow, auto_posts, auto_stories, autoreply, birthday_message, customs_watch, expired_message, expiry_message, gen_info, mass_premade, nudge_online, nudge_online_fire, priority_mass, process_old_fans, promo_reactivate, purchase_followup, reply_mass_funnel, resubscribe_message, s4s_check, s4s_post, scheduled_send, scrape_chats, send_followup, send_mass_message, send_welcome, smart_list_sync, unsend_messages, welcome_chatter_for_info]
verified: 2026-10-21
---

# Inflowwww — how the product works

This is the reference for agency staff. Everything below was checked against the
running product on 2026-10-21. If something is not described here, it is not a
feature — say so instead of guessing.

Inflowwww works **only with OnlyFans**. It does not post to, read from, or connect to
any other platform.

---

## The navigation

The sidebar, top to bottom:

- **Dashboard** — the home page.
- **OF Manager** — the creator's own OnlyFans pages inside the app: Home, Go
  live, New post, Notifications, Messages Basic, Vault, Queue, Collections,
  Bookmarks, Statements, Statistics, Bank, My profile, Release forms and OF
  settings.
- **Analytics** — Creator reports, Employee reports (with Sales records), Fan
  reports and **Message dashboard**, the money-and-posts page. The Message
  dashboard's tabs are Direct messages, OnlyFans mass messages, PPV, Tips, All,
  Customs, Posts, My Feed and Top Posts. The customs queue is **Analytics →
  Message dashboard → Customs**.
- **Messages Pro** — the chat workspace. It opens in a window of its own.
  **Focus** works the owe-reply queue one fan at a time.
- **Growth** — Smart Messages, Smart lists, Auto-follow, Vault Pro, Scripts,
  Profile promotion, Free trial links, Tracking links and Sensitive words.
- **Share for Share** — Discover creators, Requests, S4S schedule and S4S
  settings.
- **My Automations** — Auto Post, Auto Story, Auto Mass, Auto-reply, Auto
  Funnel, Get to know fans and Gen-Info.
- **Creators** — Manage creators (connecting and watching OnlyFans accounts)
  and Custom proxy.
- **Employees** — Manage employees (logins, roles, access) and Shift schedule.
- Pinned at the bottom: **Settings** and **Help center**.

The top bar holds the sidebar toggle, the Inflowwww wordmark, the status pill,
the error badge, your time zone, the SFW switch, the notification bell, the
Clock button and the avatar menu (theme, Log out). There is no model picker: a
page that shows one creator has its own creator select.

**Old names people still use.** "Stuff" is now Analytics → Message dashboard,
"Inbox" is Messages Pro, "Stats" is Analytics, "Setup" is Creators → Manage
creators (accounts) plus Creators → Custom proxy and Settings → AI keys. The
old `/messages`, `/inbox`, `/stats`, `/customs` and `/setup` addresses redirect
to the new pages. The old **+ New ▾** menu is gone: Messages Pro's **+** button
holds **Mass message**, **Message online fans** and **Post** (which opens OF
Manager → New post).

## Roles — who can see what

There are two kinds of login: the **owner** (the agency's own account) and an
**employee** (a login the owner made, with a role — a chatter, for example).

An employee sees what their role grants. Out of the box an employee does
**not** see Growth's owner pages (Smart lists, Auto-follow, Vault Pro, Profile
promotion, Free trial links, Tracking links, Sensitive words), Share for Share,
Creators or Employees. On Growth they keep **Smart Messages** and **Scripts**.
In My Automations they see **Get to know fans**; every other My Automations page
is off for an employee until the owner turns it on for their role in **Settings
→ Role Settings**. In Settings an employee sees only **Security (personal)**,
**Billing**, **Your Balance** and **About Inflowwww**; Your Account, Your
Preferences, Security (organization), Role Settings, Sales Settings, Time
tracking, Messaging settings, AI keys and Audit log are the owner's.

The Message dashboard, Customs tab included, is visible to employees by default, because
a chatter needs to know when a fan is owed a custom.

**Rule for answering a chatter:** if the thing they are asking about is
configured on a page their role does not open — out of the box, a My
Automations page other than Get to know fans, one of Growth's owner pages, Share
for Share, Creators, Employees or an owner-only Settings page — tell them the feature
exists, say what it does, and tell them to **ask an owner or admin to set it
up** — do not hand them a click path they cannot follow.

## Where the automations actually live

**There is no Automations page any more.** The old one — the Brain card, the
Automation rules list with **+ New rule**, the 12 "Ready-made posts &
broadcasts" tabs and the Automation runs log — is gone, and an old
`/automations` link lands on My Automations → Auto Post. Automations are set up
in these places now:

- **My Automations** — one page per automation: **Auto Post**, **Auto Story**,
  **Auto Mass** (ready-made broadcasts on timers), **Auto-reply** (it was
  once called Auto Convo), **Auto Funnel**, **Get to know fans** and
  **Gen-Info**. Each page has its own creator select and its own switch.
- **Growth → Smart Messages → Automated Messages** — the per-fan triggers:
  **Nudge**, **Delayed welcome**, **Purchased**, **Nearing expiry**,
  **Expired**, **Resubscribe** and **Birthday**. A trigger that is not set up
  yet is added from **New Message** (its card there).
- **Growth → Smart Messages → Mass Messages** — the mass sends: **Priority mass
  messages**, **OF mass messages** (with the Auto-unsend card) and the list of
  every scheduled send.
- **Growth → Auto-follow** and **Growth → Profile promotion** (Keep promos
  running).
- **Share for Share** — the S4S posts a creator swaps with a partner.

**Everything else has no page any more:** the Brain (persona, clock, daily cap,
models), Follow-ups, the Audience fence, ⚡ Reply Instant, the rules list and
the run log. A rule that already exists keeps running as it was set, but nobody
can create, edit or switch it from the app. When someone asks how to set one of
these up, say there is no screen for it now and that the deployment operator has
to change it — do not send them looking for a tab.

**There is no AI Chatter, AI Upseller or Tip Reward any more.** The AI seller,
the upseller, tip rewards, tip requests and Make It Right were removed from the
product. The AI that writes to fans today is **Auto-reply** (My Automations →
**Auto-reply**, `/growth/auto-reply`, the `autoreply` engine) plus the warm-up
**Get to know fans** rule, and every AI call runs on the keys in **Settings → AI
keys**. If someone asks for one of the removed features, say plainly that it no
longer exists — do not send them looking for it. (**Growth → Scripts** is the
saved script library chatters paste from, not an automation.)

**The 💸 PPV Library and 🧠 Vault AI automations are gone too.** The PPV Library
rotator, the Vault AI arc teases, the daily vault reminder, applying approved
Vault AI items and the background describe sweep were removed; their old rules
no longer run. What is left is describing media **on demand**: on **Growth →
Vault Pro**, **Describe all** (or describing one item) has an image-reading AI
write down what is in each photo or video. It sends nothing to fans, needs a
DeepInfra key, and refuses to start once the account's daily AI cap is used up.

## "Enabled" means two different things

This is the single most common cause of "I turned it on and nothing happened."
An automation only runs when there is an **enabled rule** for it.

**1. Rule-backed — the switch IS the automation.** Switching on creates or
wakes the rule: every My Automations page (Auto Post, Auto Story, Auto Mass,
Auto-reply, Get to know fans, Gen-Info), the Auto Funnel **Reply walking**
switch, the Smart Messages triggers (Nudge, Delayed welcome, Purchased and the
lifecycle ones), Growth → Auto-follow, the **Auto-activate campaign** switch on
Growth → Profile promotion and the **Auto-unsend (automation)** card on Smart
Messages → Mass Messages.

**2. No switch in the app at all:** Follow-ups, the Audience fence,
⚡ Reply Instant, and the rule-only kinds (Apply profiles, Backfill chat
history, Customs owed). Their pages are gone; a rule that already exists keeps
running, and only the deployment operator can add, change or stop one. There is
no **+ New rule** button anywhere any more, and no run log an owner can open.

## The AI key — nothing writes without it

Every AI-written message resolves the agency's own API key. **Settings → AI
keys** (`/settings/ai-keys`, owners only — an employee does not see it), one
password field per provider in this order: **DeepInfra · DeepSeek ·
Z.ai (GLM)**, each with a set / not set badge. Leave a field blank
to keep the stored key.

- DeepSeek powers chat replies and most automations — this is the one that
  matters. The system default model is `deepseek-v4-flash`.
- DeepInfra powers vision: vault image descriptions, and Auto-reply's opt-in
  "describe photos fans send".
- Z.ai is an optional second provider.

**It fails closed.** With no key for the provider a model belongs to, the call is
refused with "add it in Settings → AI keys" — there is no fallback house key.
An agency holding only a DeepInfra key still has every chat reply fail. If two
owners are linked to one model, the one holding a key for a provider pays for
it; only when BOTH hold a key for the same provider does AI stop on that
provider, and the card shows a red "AI is stopped … — two owners, two keys"
panel naming the model and the provider.


## Which autochat is which

There are two, and **neither one pitches**. There is no AI seller any more —
selling is done by people and the mass sends.

**Get to know fans (`welcome_chatter_for_info`)** is the warm-up (info-gather).
It talks to fans who have not bought anything, asking one gentle question at a
time to build a profile. It never pitches. The one exception is optional and set
by you: when the chat ends it can send **one closing PPV** — a fixed caption,
your vault media, a fixed price, sent word-for-word — and then your team takes
over. Leave its media empty and it just stops when the chat ends.

A fan leaves the warm-up lane for good once he buys content (a tip or a PPV
unlock; a subscription does not count), or once the lane is finished with him —
every topic filled or asked to its cap, and the follow-up questions it mined all
used up. The message cutoff (10 by default) only bites while he is still being interviewed; a
fan who has finished answering keeps getting replies past it. A complete profile
on its own is not a hand-off. **Nothing AI picks him up after that** except
Auto-reply, if it is on and he is in its audience.

**Auto-reply (`autoreply`)** is a keep-warm safety net: when nobody answered a
fan in time it sends one casual line matched to the tone of the chat. Never a
PPV, never a tip ask, never a profile question. Older text and the evidence
lines still call it **Auto Convo** — same engine.

Older message rows can still carry the label **"AI Chatter"** — those were
written by the removed seller before it was deleted.

## Messaging fans who come online

**👋 Nudge Online (`nudge_online`)** is the real "message someone when they come
online". Every ~60 seconds it checks who just appeared, then sends that fan a
**personalised** DM after a short delay. This is the answer to "can I message
people when they log in". A one-off broadcast to everyone online right now is
**Message online fans** — Messages Pro → **+** → Message online fans, or Growth
→ Smart Messages → **New Message** → Message online fans.

It is not a true login event. Detection is polling, roughly once a minute.

---

# Setting up

## Connecting an OnlyFans account

**Where:** **Creators → Manage creators → Add creator.** Owners only, and the
session capture is **desktop only** — on a phone the page says "Session capture,
proxies and keys are desktop-only."

**How to do it:**
1. In the Add creator window, fill the creator details, pick the platform and
   the proxy (the Inflowwww proxy, **No proxy (server IP)**, or one of yours),
   then choose **Connect OnlyFans**.
2. Install the **Chatterly Login Capture** Chrome extension. The step shows an
   **Install Chrome Extension** button, and once it is there the button is
   replaced by a green line: "Extension installed — click the puzzle icon in
   your Chrome toolbar to open it."
3. Sign in to OnlyFans as that creator **in Chrome**, open the extension from
   the puzzle icon, and press **Copy cURL**.
4. Paste it into the big box. It must start with `curl` — anything else is
   refused with "Must start with `curl ...`".
5. Optional, before you submit:
   - **Nickname** — the name shown in the creators table and the creator
     selects.
   - **Attach proxy** — one of your registered proxies (Creators → Custom
     proxy).
   - **Flip this account to the relay's default after bootstrap** — **ticked by
     default**. Untick it if you do not want this new model to become the
     relay's default account.
6. Press **Bootstrap from cURL**. Success shows the account as linked, and the
   model appears in the creators table and every creator select.

**Re-capturing.** The session is a copy of that browser login, so it goes stale.
When OnlyFans ships a new front-end, Manage creators shows an amber **"Session
stale — re-capture required"** banner naming the models affected and the new
rev. (Its **Dismiss** button only hides it for that one rev; a new rev brings it
back.) Fix is the same steps: sign in again, Copy cURL, paste, Bootstrap. That
also immediately clears a paused account (see below).

**Caveats:**
- Picking a proxy shows an amber teleport warning, and pressing Bootstrap asks
  you to confirm it: the cookies were minted on your own IP while every call
  afterwards leaves from the proxy's. Only do it when the proxy sits close to
  where you signed in. If the session captures but the proxy attach fails, the
  result says so; attach it afterwards under Creators → Custom proxy.
- Nothing else connects an account. Custom proxy, AI keys and the creators
  table are all after-the-fact management.

## The Brain (persona, clock, daily cap, models)

**There is no Brain page any more.** Each account still has a brain — persona,
location, creator (female/male), language, creator clock, a **daily AI cap**
(a fresh account starts at 100¢ = $1.00, and at the cap the runs report ok but
do less), the nine creator facts, the model and its per-purpose model choices, and
the time-of-day lines and images the welcome uses — and every AI lane reads it,
but nothing in the app edits it. The one part an operator can still change is
**Model info**, the short note every chat prompt pins: it is on **My Automations
→ Get to know fans**. For anything else in the brain (raising the daily cap
included), say the deployment operator has to change it.

## Adding an employee (a chatter's login)

**Where:** **Employees → Manage employees → + Add employee.** Owners only.

Fill **Name**, **Role**, **Group** and **Creators** (every creator, or the ones
you tick), then pick how they sign in:
- **Create login** — you type their username and a password (at least 6
  characters) and hand it to them.
- **Invite link** — the window makes a link and you **Copy** it to them. On
  that page they pick their own username and password, which creates their login
  with the setup you chose. The link is **single use** and **expires 24 hours**
  after it is made. A pending invite shows in the list with **Resend** (a fresh
  link; the old one stops working) and **Delete**.
- **Existing login** — someone who already chats for another owner: type their
  username and they are linked to you.

**Each row** has **Edit** and **More**. More holds **Reset password** (you set
the new one), **Access limits** and **Deactivate** / **Activate**.
- **Access limits** — **Limit which models this employee sees**: off (the
  default) means all of your models; tick it and pick the accounts. Under each
  model you can also limit folders; only **custom** vault folders are listable.
  Press **Save access**. A limit switched on with nothing picked will not save
  — to take someone off completely, **Deactivate** them instead.
- **Deactivate** removes their link to you and keeps their history; an employee
  is never deleted, so the audit history stays joined up.

**Roles.** "Manage roles & permissions →" opens **Settings → Role Settings**,
where the Admin / Manager / Chatter / VA presets and the pages each role may
open are edited, and where **Enforce role permissions** is switched on.

**Caveat:** don't open an invite link in the browser you are signed in as owner
on — registering there logs the owner out of that browser.

## Stopping the bot on one fan

There is no "stop automations for this one fan" switch any more: the old
**Restrict from automations** row and the Restrictions list in Settings are
gone. A fan restricted that way earlier stays skipped. What exists, on that
fan's chat:

- **Add to MASSdmEXCLUDE** — in the chat header's Extras overflow, and as the
  Mass exclude block of Fan insights. Keeps him out of every mass send, priced
  or not: mass DMs, mass PPVs, Priority mass messages and Auto Funnel starts.
  It leaves welcomes, AI replies, nudges and 1:1 chat alone. This is the one
  opt-out list the mass sends subtract, and it is mirrored to a pinned OnlyFans
  list of the same name. The line flips to **Remove from MASSdmEXCLUDE** once
  he is on it. (There used to be a second, PPV-only list, MASSppvEXCLUDE; it was
  merged into MASSdmEXCLUDE on 2026-10-21. A MASSppvEXCLUDE list may still sit
  on OnlyFans; nothing reads it any more.)
- **Restrict** — the ⋯ menu ("More actions") in the chat header, after a
  confirm. It restricts him on OnlyFans (he is sent nothing) and hides the chat
  so the dead thread leaves the inbox. From then on he is out of every unread
  and owe-reply count and every automation hard-skips him. The hide is not
  permanent — the thread comes back if he messages again. **Lift restrict** in
  the same menu un-restricts him and un-hides the chat.

**Caveat:** a peer creator whose chat you **muted** on OnlyFans is skipped by
every automation automatically; **Unmute notifications** in the same menu frees
him.

## Building and sending a funnel

**Where:** My Automations → **Auto Funnel** (`/growth/auto-funnel`). Pick the
model in the creator select in the page header first — Start, Media and
reply walking all act on the selected model.

**Funnels are global.** One funnel is shared across every model you own. What is
*not* shared is its media — vault ids do not carry between models, so each model
maps its own.

**Build it:** press **New funnel**. A funnel is a **Name**, an optional
**Description**, an **Opening message**, and an ordered list of steps added with
**+ Reply step** and **+ PPV step**. Save with **Create funnel** (**Save
changes** when editing).
- A **reply step** polls for the fan's answer on the minutes you list ("Check for
  a reply every …", comma-separated; blank = 2, 4, 10), then sends what you typed
  in its variant boxes — **only the first two boxes are used**. Or tick
  **Generate the reply with AI** and it writes the message, steered by the
  optional prompt box.
- A **PPV step** is sales copy at a **Price (USD, whole)**, with an optional
  **Lock the text too (fan must pay to read the copy)**. Same AI tick if you want
  the sales copy generated.

**Map its media, per model:** press **Media** on the funnel's row, with the
model you want selected. You attach vault media to the **Opening message media**
(optional) and to each PPV step, then press **Save media**. Per PPV step,
"Free preview — first N of M" sets how many of the picked items go out unlocked
as the teaser; the strip is in send order and the free ones are always the first
N, so reorder with ◀ ▶ to choose them. A PPV step only shows up here once it is
saved in the editor. Do this once for every model that will run the funnel — a
funnel that works on one model and sends nothing on another is almost always
this.

**Send it:** press **Start** on the funnel's row, then set the audience:
- **Send to (include)** — **All fans** (ticked by default), **Following**, and
  the account's own OnlyFans lists.
- **Exclude** — the same chips. If that account has a list named
  **MASSDMEXCLUDE**, it is ticked into the exclude set for you; untick it for a
  one-off.
- **Online only**.
- **Skip fans I messaged in the last … hours**.
- **Auto-unsend opener after … hours** — pre-filled with 4; blank means no
  auto-unsend. Once the opener is unsent, new repliers stop enrolling, but anyone
  already being walked keeps going.

Then press **▶ Start funnel**. There is a confirm box because it is a real blast.
The opener goes out free — the priced step comes later in the funnel — and fans
who already answered this funnel are skipped automatically.

**Turn on reply walking, or nothing advances.** The **Reply walking** switch at
the top of the page reads "On · every 2 min…" or "Off. Funnels send the opener
but won't advance past it until this is on". Off means every funnel sends its
opener and stops there. It is **per model**, so switch the creator and turn it
on for every model that runs funnels. The Start panel warns you too — "Reply
walking is off — this funnel will send the opener but won't advance through its
reply / PPV steps" — with an **Enable reply walking** button right there. See
`reply_mass_funnel` below for the rest. Sending a mass with a **Funnel
follow-up** picked turns reply walking on for that model by itself.

## Growth — Smart lists, Free trial links, Tracking links, Profile promotion

Each of these pages has a creator rail on the left; pick the creator first.

**Smart lists** — a saved fan segment you build once and reuse. **Create list**
(or **Presets** — spend segments, sub length, new / expiring / recently expired
/ resubscribed, and the $ / $$ / $$$ Smart Tags tiers pre-fill the builder)
opens **Create smart list**: name it, then **Add condition** for each rule. A
list matches fans who meet **all** conditions; tick **Match any condition** to
match fans who meet any one. Conditions: **Spend** — Total spend, Messages / PPV
spend, Tips spend, Subscription spend, Highest single purchase, Last purchase
amount (from recorded transactions, each with a timeframe: all time / today /
yesterday / this week / last 7, 30, 90 days, UTC, and a scope: **this creator**
or **whole agency** = the same fan's spend summed across the agency's creators),
plus **Lifetime spend (OnlyFans total)** and **Spend in the last N days**;
**Activity** — Last purchase, Last message sent, Days since active, Last
purchase, message or subscribe; **Subscription** — Subscription status (active
/ expired), Auto-renew (on / off), Subscribed, Subscription expires (also "in
the next N days"), Resubscribed; and **Tags**. Press **Preview count** to see
how many of the account's fans match and a sample of the names, then **Create
smart list**. A saved list is then pickable as an audience — include or exclude
— in the mass composer (**Smart Lists — include / exclude**). The composer only
offers them when you have a single model selected. **Sync** on a list row keeps
a real OnlyFans list of the same name in step with it (see `smart_list_sync`;
at most 10 lists per model by default, shown as "N / 10 lists syncing to
OnlyFans"). Deleting a synced list asks whether to **Also delete the OnlyFans
list**; otherwise it is left on OnlyFans. On a send they are resolved to fan ids
against live spend at that moment — and for an *exclude*, those ids are written
into a hidden per-account OnlyFans list called `Auto_Exclude`, because OnlyFans
has no per-fan exclusion on a broadcast.

**Free trial links** — mint OnlyFans free-trial links. **Create free trial
link**, then set the **Link name**, **Offer limit**, **Offer expiration** and
**Free trial duration** (plus optional Source, Promo cost, Tag and List — List
adds every fan who claims the link to one of the account's OnlyFans lists), and
Save. The table shows each link with its claims ("3 / ∞") and what its fans
spent. OnlyFans owns these — when it is unreachable the page says so and shows
the saved links only.

**Tracking links** — two different kinds on one page, and the difference
matters:
- **Tracking links** (the Links list tab, **Create tracking link**; the OnlyFans
  kind) point at the creator's profile. OnlyFans reports real clicks **and how
  many of those clicks subscribed** — true attribution — and the Dashboard tab
  sums them. Share links makes a public read-only report on picked links.
- **Custom redirect links** (the collapsed section below — click the heading to
  open it) are for a target that is not the profile: a Linktree, a landing page,
  an X profile. Give a **Name** and a **Target URL**. These are Inflowwww's own short
  links and they count **clicks only** — the visitor never lands on OnlyFans, so
  subscribers cannot be attributed, and the per-link **Analytics** panel says so.

Use the OnlyFans kind whenever you are sending people to the profile.

**Profile promotion** — subscription campaigns on the creator's profile.
**Create promotion**, then set a **Name**, the **User type** (who may claim it),
the **Promotion type** — **Free trial** (with a **Free trial duration**) or
**First-month discount** (with a **Discount percent**) — the **Offer limit**,
the **Offer expiration** and an optional **Message**, then Create. It is a real
campaign on OnlyFans. Campaigns are listed under **Campaign insights** with
their claims and revenue.

To keep an offer alive, tick **Keep running** on the campaign's row in Campaign
insights — that is the opt-in. The **Auto-activate campaign** switch higher up
is the engine behind it, and the **Keep promos running** card under that switch
holds the engine's settings (how often it checks, a max number of re-arms, and
a **Dry run** box that is **on by default** — untick it or it will only report).
See `promo_reactivate` below.

---

# Recipes — wiring several automations together

Each of these is per model. Work down the steps in order.

## "Welcome them, chat, then sell — but leave my big spenders out of the mass sends"

The full shape: welcome every new fan → warm-up chatter for fans who have not
bought → Auto-reply keeps quiet chats warm → selling through the mass sends,
which skip anyone over your spend line. (There is no AI seller: the bot chats,
people and the mass sends sell.)

**First, build the segment.** Growth → Smart lists → **Create list**. Name it
"Over $400". Leave **Match any condition** unticked. One condition: field
**Lifetime spend (OnlyFans total)** · operator **>** · value **400** (the box
is dollars). Press **Preview count** and read the sample before saving —
**lifetime spend counts subscriptions and tips, not just content**, so a fan on
$10/month for 40 months crosses $400 without ever buying a PPV. Then **Create
smart list**.

**The three lanes.**
1. Growth → Smart Messages → **New Message** → **Subscriber welcome** (the
   **Delayed welcome** row once it exists): switch it on, write the message,
   Save.
2. My Automations → **Get to know fans** → switch it on, Save. This is the lane
   for fans who have not bought.
3. My Automations → **Auto-reply** → switch on, pick who it answers (folders
   and/or new fans), Save. That one switch also creates its rule.

**The spend line, surface by surface — they do not behave the same.**
- **Mass message** (Messages Pro → **+** → Mass message, or Smart Messages →
  New Message → OF mass message) — the mass surface that reads a Smart List.
  Select **one** model (the Smart List chips vanish in all-models mode and the
  pick is silently dropped), then under **Smart Lists — exclude** click the
  "Over $400" chip. Works the same for **Message online fans**.
- **👋 Nudge Online** — **Max lifetime spend ($)** in the Nudge editor. This one
  cuts **strictly above**, so type **400**. Yes, that is a different boundary
  from the Smart List's.

**THE OTHER DIRECTION — "only fans UNDER $400" — is not this recipe backwards.**
Asked for the mirror image, it is tempting to build an "Under $400" segment and
exclude it. That messages exactly the wrong half: exclude removes what the
segment matches, so excluding "Under $400" leaves you sending to the big
spenders. **Build the segment for the people you do NOT want and exclude that,
always.** So for "only fans under $400" you still build **"Over $400"**
(operator **>**, value **400**) and exclude it — the same chip as above.

And Nudge Online's box flips: it cuts **strictly above**, so "under $400" is
**399** (400 would keep the fan on exactly $400, who is not under it).

- **Auto Mass — cannot do it at all.**
  It has no spend control and cannot read a Smart List. If the carve-out
  matters, switch it off. The only workaround is adding each fan to
  **MASSdmEXCLUDE** by hand from the chat header's Extras, one at a time,
  re-checked as people cross the line.
- Anything a **human chatter** sends is never gated by any of this.

**Then stop the non-spenders being chatted.**
- **Auto-reply** — switch it off (My Automations → Auto-reply), or narrow WHO
  to a folder of buyers. Its spend controls are ceilings, it has no minimum, and
  a fan who never paid passes it. Leaving it on is the most common reason
  "spenders only" does not hold.
- Decide about the warm-up lane. If "spenders only" means *the AI should only
  ever reply to people who bought*, switch My Automations → Get to know fans off
  too.

**Three things to remember**
1. **"Has he bought?" is a yes/no test, not a dollar bar** — a tip or a PPV
   unlock counts, a subscription does not. There is no minimum-spend control on
   the chat engines at all.
2. **An empty or 0 spend box on the Nudge editor means off.** Its dollar boxes
   save 0 as "no limit", so clearing the box and typing 0 do the same thing.
3. **Some lanes can never be spend-gated.** The welcome (a new subscriber has
   bought nothing by definition) and **Follow-ups**, which has a hard-coded $1
   lifetime floor with no operator control — and subscription money clears $1.

## "Brand new model — what do I turn on first?"

1. **Settings → AI keys** — paste the **DeepSeek** key. Nothing AI-written
   works without it, and there is no fallback.
2. **Creators → Manage creators → Add creator** — connect the account (see
   Setting up).
3. **My Automations → Get to know fans** — fill **Model info** (the short note
   every chat prompt pins), switch it on, Save. The rest of the brain has no
   page (see "The Brain").
4. **Growth → Smart Messages → New Message → Subscriber welcome** — switch it
   on, Save.
5. **My Automations → Auto-reply** — switch on, pick who it answers, Save.
6. Only then add selling: the mass sends and **My Automations → Auto Mass /
   Auto Funnel**.

There is no one-click onboarding wizard — every step is its own Save button.

## "Make money from the vault without chatting"

The 💸 PPV Library rotator that did this was removed. Nearest real
things: **My Automations → Auto Post** (paid feed posts on a timer) and
**My Automations → Auto Mass** (ready-made broadcasts on timers). To silence
the chat lanes as well, switch off My Automations → Auto-reply and
My Automations → Get to know fans.

OnlyFans rejects any priced message under $3.00.

## "Message everyone who comes online, but not twice a day"

Growth → Smart Messages → Automated Messages → the **Nudge** row → tick
**Enabled** → **Min hours between** **24** → Save. The first pass after
switching on sends nothing on purpose — it records who is already online so you
do not stampede everyone.

It shares **one** recently-contacted ledger with the other senders, so a fan
caught by one is skipped by the next, and it is not a real login event —
detection is polling, about once a minute. For one broadcast to whoever is
online right now, use **Message online fans** instead.

## "Win back fans who expired"

1. **Growth → Auto-follow** → turn the creator's switch on. It follows fans
   whose subscription expired, so OnlyFans sends each a "started following you"
   notification (free pages only; see `auto_follow`).
2. **Growth → Profile promotion** → **Create promotion** with **User type** =
   **Expired subscribers** and a Free trial or First-month discount, then tick
   **Keep running** on it in Campaign insights and set up **Auto-activate
   campaign** with the **Keep promos running** card's **Dry run unticked**.
3. **A message to expired fans:** Messages Pro → **+** → **Message online
   fans**, untick **Only fans online right now**, and set **Expired over** to N
   days. That reaches fans whose subscription ended at least N days ago, sent as
   at most 1,000 fan ids. Inflowwww has to have read the account's whole
   subscriber list for it to work.

---

# Editing the raw JSON

Some settings have no checkbox. They are reached by opening a JSON editor and
typing the key yourself. There are **two different kinds** of JSON in this app
and they behave in opposite ways, so read this before pasting anything.

**All raw-JSON editors are desktop-only.** The buttons are hidden on a
phone-width screen — on a phone there is no raw-JSON path at all.

## The two kinds of JSON

**1. A rule payload** — the per-run settings of one automation. Three pages can
open it: My Automations → **Auto Story** (**Edit raw JSON** in the page header),
and the **Auto Post** and **Auto Mass** editors (**Edit raw JSON →**, which
swaps the form for the JSON). No other rule's payload can be opened from the app
(the rules list and its editor are gone). The Auto Funnel editor's **Edit raw
JSON →** edits the funnel itself, not a rule.

It takes one JSON object — the whole payload, e.g.

    { "limit": 200, "max_replies": 25, "dry_run": true }

**Unknown keys are kept.** The server stores whatever you type. That is
deliberate, but it means **a typo is a silent no-op**: `"limt": 40` saves fine,
reports success, and does nothing forever. Check your spelling against the
field names shown in the typed view.

**2. A config blob** — the settings behind a whole editor. One surface has one:
the 👋 Nudge Online editor, **{ } Edit raw JSON** → **Edit raw JSON — Nudge
online config**.

**Unknown keys are thrown away.** It runs the JSON through a list of keys it
recognises and **silently drops anything else**, then replaces the whole stored
blob. You get a success message either way, and
re-opening the editor shows the default — so a dropped key looks exactly like a
key that saved. If a setting does not stick, it is almost always this.

The Brain, Auto-reply and ⚡ Reply Instant have no raw-JSON editor at all.

## Setting a time of day instead of an interval

Clock times exist but have no control — they live on the rule's `trigger`:

    { "daily_at": ["09:00", "20:30"], "tz_offset_minutes": 120 }

`daily_at` is a list of "HH:MM" in the creator's local time;
`tz_offset_minutes` is minutes to add to UTC. You can add `"max_runs": 5` to
either form to switch the rule off automatically after N runs.

**Auto Story is the exception** — its page has an "At set times each day" mode
that writes this for you. For every other automation there is no way to set it
from the app.

Unlike a payload, an unrecognised key inside `trigger` is **dropped**.

## Nudge Online's day buckets

The Nudge editor's line editor writes the `default` bucket. The `weekend`,
`weekday` and per-day buckets (`friday`, …) are set in its **Advanced — edit
pools as JSON (copy in / out)** section, then **Apply JSON** and Save.

## Backing it up before you edit

There is no Export / Import settings button any more. Before hand-editing a
raw-JSON box, copy what it shows somewhere safe, so a dropped key can be pasted
back.

---

# The automations

## kind: welcome_chatter_for_info — Get to know fans (AI info-gather)

**What it does:** Opens and continues conversations with fans who have not
bought anything, asking one gentle question at a time to learn about them. It
feeds Generate fan profiles. It never pitches. Optionally, when the chat ends,
it sends **one closing PPV** set on the rule — then your team takes over. Leave
its media empty and it just stops when the chat ends.

**Where:** My Automations → **Get to know fans** (`/growth/get-to-know-fans`):
the switch, the message cutoff, the closing PPV, the Human style boxes and the
account's **Model info**, saved together by one **Save**.

**How to enable:** switch it on in the page header. The first switch-on creates
its rule from the defaults; switching off parks it.

**The closing PPV (off until you pick media):** on the same page, pick
`closing_ppv_media_ids` from the vault — that is all it needs. The caption
(`closing_ppv_text`) and price (`closing_ppv_price_cents`, $3–$200 in cents,
default 1000 = $10) come prefilled with a default; change them if you like. The
caption is sent word-for-word — the AI never writes or changes it. It goes out
once per fan, as his last message from this lane, when the lane is finished with
him — his info is gathered, or he hits the message cutoff (`max_fan_messages`,
default 10), whichever comes first. Never to a fan who already bought content,
and never to a fan who already owns any of the picked media. If the send fails
he still leaves the lane. Leave the media empty to just stop when the chat ends.

**Key knobs (rule payload):** run every 60s · `limit` 200 chats scanned per run ·
`max_replies` 25 per run · `history_tail` how many recent messages the AI reads
(engine default 20) · `dry_run` · `only_fan_ids` scope with gates on ·
`force_ids` target fans ignoring gates · `max_fan_messages` the message cutoff
(default 10, 3–100) · `closing_ppv_text` / `closing_ppv_media_ids` /
`closing_ppv_price_cents` the closing PPV.

**Prerequisites:** an agency AI key; chat history already in the system; an
enabled rule of this kind.

**Caveats:**
- Graduation is permanent, but a finished profile is not graduation. He leaves
  for good when he buys content, or when the interview is over **and** the
  follow-up questions it mined have all been used. The message cutoff (10 by default) applies
  only while he is still being interviewed. Once he does leave, this lane never
  talks to him again — only Auto-reply can, if he is in its audience.
- Dry run still calls the AI and still costs money; only the send is skipped. A
  dry run counts the closing PPV it would send but sends nothing and leaves the
  fan in the lane, so the real run still sends it.

## kind: autoreply — Auto-reply (reply when the team is slow)

**What it does:** When a fan messages and nobody answers in time, it sends one
casual line matched to the tone of the recent messages, to keep the conversation
alive. It never pitches: no PPV, no tip ask, no content offer.

**Where:** My Automations → **Auto-reply** (`/growth/auto-reply`) — the switch,
the delay, WHO it answers and the reply-style boxes. (It used to be the 💬 Auto
Convo tab; this page is the only one now.)

**How to enable:** switch it on and Save. That one switch writes the settings
**and** creates or wakes the `autoreply` rule; switching it off parks the rule.

**WHO it answers — two sources, a fan qualifies on either:**
- **Folders:** fans in the OF lists you pick (none picked = every fan), with an
  optional lifetime-spend cap. On by default.
- **New fans:** first seen in the last 72 hours and under $10 lifetime spend.
  Off by default.
Turning both off with the switch on answers nobody; the page warns about it.

**Key knobs:** wait 24 minutes of silence before stepping in (optionally a
random delay up to double that) · give up after ~18.5 hours · one reply per
waiting message · 5 minutes minimum between its replies to a fan · reads the
last 16 messages · quiet hours · 200 candidates and 25 replies per run.

**Photos he sends — two opt-ins, both off by default:**
- **Describe photos fans send** — the photo in the message being answered is
  described once by the vision model and the reply reacts to it. Needs a
  **DeepInfra** key in Settings → AI keys; without one it simply stays off.
- **Skip photo-only messages** — a message that is only a photo gets no reply.
Off, keyless or failed: the reply never claims to know what is in the photo.

**Prerequisites:** a **DeepSeek** key in Settings → AI keys (the page shows an
"add a key" notice when the account cannot pay for its model).

**Caveats:**
- Enable it only on accounts with real fans, never on promo-spam accounts.

## kind: send_welcome — Welcome new subscribers

**What it does:** Watches OnlyFans' new-subscriber feed and sends each new
subscriber a welcome: a greeting with a time-of-day photo, then a line saying the
day/time and where the creator is, then optionally a question you wrote
word-for-word, then optionally a GIF. Once per fan, ever.

**Where:** Growth → Smart Messages → Automated Messages → the **Delayed
welcome** row; before it exists, **New Message** → **Subscriber welcome**.

**How to enable:** switch it on, write the message, **Save**. That save creates
or wakes the rule.

**Key knobs:** `time_only` short 2nd bubble (on) · `question` 3rd bubble, sent
exactly as typed, default "what's yours?" (blank = off) · `gif_id` 4th bubble
(blank = off) · `with_image` · `max_welcomes` 25 per run · `guard_hours` 12.
Every bubble is sent exactly as written; no AI rewrites any of it.

**Prerequisites:** a working OnlyFans session; the account's brain (location and
creator clock drive the time line; it has no page, see "The Brain"); for a photo,
a per-slot image in the brain's time-of-day slots or a vault folder named "bot",
"welcome script" or "welcome".
The whole welcome is written by the app, so it goes out with no AI key.

**Caveats:**
- It will **not** back-fill your existing roster. Anyone with a real conversation
  already (more than 2 messages sent to him, or more than 8 from him) is treated
  as established and skipped — the OF feed also carries renewals.
- One welcome per fan for life; a fan who resubscribes months later gets nothing.

## kind: send_followup — Follow up quiet fans

**What it does:** A slow drip that re-opens chats with paying fans who went
quiet: up to three AI-written nudges as the silence grows, each optionally with a
time-of-day photo.

**Where:** It has no page any more — the Brain's Follow-ups section and the rules list
were its only screens. A rule that already exists keeps running.

**How to enable:** Not from the app; the deployment operator has to add the
rule.

**Key knobs:** the three silence thresholds in hours (real defaults **26 / 64 /
120**) · `with_image` · `limit` 200 fans per run, highest lifetime spend first ·
`exclude_replied_hours` 12.

**Prerequisites:** an agency AI key (every nudge is AI-written); fans with at
least $1 lifetime spend; the Brain filled in.

**Caveats:**
- **A third delay of 256 hours is thrown away.** Anything at or over 168 hours
  (a week) is ignored and that step falls back to its default, so the third
  nudge really fires at 120 hours.
- Free and never-spent fans are never followed up — this cannot wake a cold free
  list.

## kind: purchase_followup — Message on purchase

**What it does:** After a fan buys a PPV, sends him a message you wrote, after a
delay you choose.

**Where:** Growth → Smart Messages → Automated Messages → the **Purchased** row;
before it exists, **New Message** → **Purchases**. The editor is titled
**Message on purchase**.

**How to enable:** tick **On**, write the **Message**, **Save**. Off by default,
and only an owner can switch it on.

**Key knobs:** the delay — immediately, or a random wait between two numbers of
minutes (1 to 60) · **Frequency** — once per fan, or on every purchase but at
most once in 2 hours · media and price · **Effective** / **Expiry** dates ·
**Auto-unsend** (free messages only).

**Prerequisites:** a working OnlyFans session.

**Caveats:**
- Only purchases made after it was switched on are chased; it does not reach
  back.
- A purchase still unanswered a day after its delay ran out is dropped.
- Skip-listed, paused and blacklisted fans are left out. A fan who already owns
  the attached media gets the text alone, free.
- At most 25 fans per sweep, one sweep a minute.

## kind: expiry_message, expired_message, resubscribe_message, birthday_message — Nearing expiry, Expired, Resubscribe, Birthday

**What it does:** Each sends a message you wrote when a moment in a fan's
subscription comes round: **Nearing expiry** (`expiry_message`), **Expired**
(`expired_message`), **Resubscribe** (`resubscribe_message`) and **Birthday**
(`birthday_message`).

**Where:** Growth → Smart Messages → Automated Messages → the **Nearing
expiry**, **Expired**, **Resubscribe** and **Birthday** rows; before one exists,
**New Message** → **Expiring soon**, **Expired**, **Resubscribe** or **Birthday
greetings**.

**How to enable:** tick **On**, write at least one message, **Save**. Off by
default, and only an owner can switch one on.

**Key knobs (all four):** up to 10 messages, each with variants (**Add
variant**; each fan gets one at random) · up to 5 follow-ups per message, each 1
minute to 1 week later, which stop when the fan replies · **Frequency** — once
(once per fan, ever) or every (once per event: each subscription that nears its
end or lapses, each return, each birthday) · media and price · **Effective** /
**Expiry** dates · **Auto-unsend** (free messages only). The editor's **Buyers**
table lists the fans it reached who then bought.

**Per trigger:**
- **Nearing expiry** — "Fan’s subscription near expiry within N hour(s)" (1 to
  120, default 24): his subscription ends within N hours and will not renew. It
  can also "Give a renewal discount of X% for N month(s)" (5 to 60%, 1 to 12
  months), set on OnlyFans just before the message goes out.
- **Expired** — "Fan’s subscription expired N hour(s) ago" (12 to 120, default
  24). The creator follows him first so the message can reach him; OnlyFans may
  still refuse it.
- **Resubscribe** — a fan who had lapsed subscribes again.
- **Birthday** — the Birthday on his Fan insights (month and day), checked in
  UTC. A fan with no birthday set gets nothing.

**Prerequisites:** a working OnlyFans session.

**Caveats:**
- On a free page, Nearing expiry, Expired and Resubscribe cannot be switched on
  ("… is a free subscription profile and is unable to create this message").
- Fans whose moment came before the trigger was switched on are not chased.
- At most 25 sends per sweep, with a 45-second rest after each.
- Fans outside an include-only audience, the hard skip list, the blacklist, a
  muted creator and paused fans are left out. A fan who already owns the attached media gets
  the text alone, free.

## kind: nudge_online — Nudge Online (message a fan when they come online)

**What it does:** Every ~60 seconds it spots fans who just came online and
schedules a short-delayed personal DM — one time-of-day greeting, with or without
an image. It queues a separate job that re-checks he is still around before
sending.

**Where:** Growth → Smart Messages → Automated Messages → the **Nudge** row,
which opens the nudge editor; before it exists, **New Message** → **Nudge**.

**How to enable:** Tick Enabled and Save. That creates the rule and pins the 60s
detector cadence. "Roll out to models" applies one shared config across many
accounts at once.

**Key knobs:** delay 4 min + up to 3 min random jitter · a fan counts as newly
online after 5 min away · never nudge the same fan twice inside 12 hours · 25
fans per tick, scanning up to 200 online · quiet hours 00:00–07:00 · only fans
already welcomed (on) · skip anyone with a message in either direction in the
last 6 hours · stop after 3 unanswered nudges · optional lifetime and recent
spend floors and ceilings · six time-of-day text and image pools.

**Prerequisites:** a working OnlyFans session; fans who have already been
welcomed; vault images if you want pictures. **No AI key needed** — every line
comes from your pools.

**Caveats:**
- The very first pass on an account sends nothing; it records who is already
  online so switching on does not stampede everyone. Real nudges start on the
  second pass.
- On an account your team chats all day, most nudges never fire: any message in
  either direction inside 6 hours disqualifies the fan. Nudges land on quiet
  fans by design.
- Pressing Save rewrites the rule payload and forces the cadence back to 60s, so
  anything set on the rule by other means is wiped.
- "Roll out to models" force-disables images on every target account and
  overwrites each one's whole nudge config.

## kind: nudge_online_fire — Nudge Online, fire (internal)

**What it does:** The delayed half of Nudge Online. Nobody schedules it; the
detector creates one per fan, timed a few minutes out. It re-checks the fan is
still online and still eligible, then sends.

**Where:** No screen of its own. It appears in run logs under this name.

**How to enable:** Nothing to enable — it exists only because Nudge Online
created it.

**Caveats:** a `nudge_online_fire` run showing nothing sent is **normal**, not an
error — the fan went offline, a real conversation started during the delay, or
another automation held him. If the picture fails to attach, the text still goes.

## kind: send_mass_message — Mass message

**What it does:** Sends one message to a whole audience through OnlyFans'
broadcast endpoint, and writes a copy into each known fan's chat so the blast
shows up in your chat view. It is also the engine every other broadcast feature
calls underneath.

**Where:** For a one-off blast use **Messages Pro → + → Mass message** (or
Growth → Smart Messages → **New Message** → **OF mass message**; **Message
online fans** is the same composer in its online mode). That composer sends
straight away, or at the time you schedule, and creates no rule. A saved,
repeating blast of this kind cannot be created from the app. In practice you
also reach this engine through the features that call it (Auto Mass, funnel
openers).

**Key knobs:** text · **price in DOLLARS** · media and free previews · audience
(fan ids, saved lists, OnlyFans audiences like "fans"/"following", online only) ·
exclusions · skip fans messaged in the last 6 hours (on by default) · skip fans
who messaged us in the last 2 hours (on by default) · optional funnel to attach.

**Prerequisites:** a working OnlyFans session; text (or an attached funnel with an
opener); at least one audience source.

**Caveats:**
- **The price is in dollars.** In a raw payload, 500 meaning $5 sends a $500
  PPV.
- Two audience guards are on even if you never touch them (6 hours outbound, 2
  hours inbound), so a blast can reach far fewer people than the list size
  suggests. Only an explicit 0 turns each off.
- Free and priced blasts both subtract the one opt-out list, MASSdmEXCLUDE.
- One word from Growth → Sensitive words can end the whole broadcast with
  nothing sent.

## kind: mass_premade — Premade mass (send / resend / unsend)

**What it does:** Fires ready-made broadcasts on timers. You give it a list of
messages; it sends the first, optionally schedules it to auto-unsend, optionally
re-sends it a set number of times, and drips the rest forward.

**Where:** My Automations → **Auto Mass** (`/growth/auto-mass`) → **New auto
mass**, then **Create** (**Save changes** when editing).

**How to enable:** The saved definitions **are** the rules — the per-row
**Enabled** switch in the list is the switch.

**Key knobs, per message:** one text or a pool of texts · media ids or a vault
folder · how many images per fire · price in dollars · online only · audience and
exclusions · auto-unsend after N hours · resend after N hours · how many extra
resends · delay before the next item in the list.

**Caveats:**
- Text and images are **re-randomised on every fire** — a resend is a different
  message with different pictures, not a repeat.
- A vault-folder image pool only ever sees the folder's **48 most recent non-DRM
  photos**. Videos are never picked.
- The rule's own cadence fires **on top of** the payload's resend timers, which
  multiplies the sends.

## kind: priority_mass — Priority mass message (one DM per fan)

**What it does:** Sends one message to an audience as separate direct messages,
one per fan, so it lands in each fan's priority inbox instead of OnlyFans' mass
message folder. Each launch is a one-off run; nothing repeats.

**Where:** Growth → Smart Messages → **New Message** → **Priority mass message**
("Sent to priority inbox") → **Next**. Its runs are listed on Growth → Smart
Messages → Mass Messages → **Priority mass messages**, with their progress and
**Cancel** / **Resume**.

**How to enable:** There is no switch: fill in the composer and launch it. The
audience is frozen when the run starts processing, read from OnlyFans then; if
OnlyFans cannot return all of it, the run ends in an error with nothing sent.

**Key knobs:** Creator · the text (`{name}` is the fan's name) · vault media ·
**Price (USD)** (0 = free) · Audience: the system lists plus your own lists to
include or exclude.

**Prerequisites:** a working OnlyFans session.

**Caveats:**
- Slow by design: one send every 11 seconds per creator, about 300 fans an
  hour, and at most 5,000 fans per run.
- Left out on the way: fans outside an include-only audience, the hard skip
  list, the blacklist, fans we messaged or nudged in the last 6 hours or who
  messaged us in the last 2, MASSdmEXCLUDE, fans a queued send is about to
  reach, fans who already own the priced media, a muted creator and paused
  fans.
- A word from Growth → Sensitive words stops the run. A vault item OnlyFans
  refuses stops the run with an error.
- A send whose outcome is uncertain is marked unknown and never sent again, so
  no fan gets it twice.

## kind: reply_mass_funnel — Walk mass-funnel replies

**What it does:** Watches fans who replied to a funnel broadcast and walks each
through the funnel's follow-up and PPV steps.

**Where:** My Automations → **Auto Funnel** → the **Reply walking** switch at
the top of the page.

**How to enable:** Turn the **Reply walking** switch on (it runs every 2
minutes), per model. The Start panel's **Enable reply walking** button does the
same. Sending a mass with a **Funnel follow-up** picked turns it on for that
model too.

**Key knobs:** leave `mass_run_id` blank so one rule walks every active funnel on
the account — that is the normal setting · 40 fans advanced per tick · run every
2 minutes · dry run · `test_fan` to try a funnel on yourself.

**Prerequisites:** a funnel with steps saved and an opener actually sent; for any
paid PPV step, vault media mapped for **that funnel on that model** — vault ids
do not carry between models. Only steps that generate their text need an AI key.

**Caveats:**
- **Without an enabled rule of this kind, every funnel sends its opener and then
  nothing.** Fans reply and the funnel looks broken. This is the single most
  common funnel complaint.
- Fans who never reply are never walked — a reply is what enrols someone.
- New fans stop being enrolled 14 days after the broadcast went out.
- A paid step whose vault media was never mapped for that model is skipped, so a
  funnel that works on one model can stall on another.

## kind: auto_posts — Auto posts (self-cleaning feed)

**What it does:** Publishes a saved list of ready-made feed posts one at a time,
waiting the gap you set. Each post can delete itself after N hours, so the feed
cleans itself up.

**Where:** My Automations → **Auto Post** (`/growth/auto-post`) → **New auto
post**.

**How to enable:** Build it, switch Enabled on, **Create** (**Save changes**
when editing). The saved definitions are the rules; the per-row **Enabled**
switch is the switch.

**Key knobs, per post:** one caption or a pool · media ids and/or a vault folder ·
how many images per fire · **price in dollars** for a paid post · free teaser
images · `hours_to_live` auto-delete · `delay_minutes` before the next post ·
whole-list `resend_after_hours` + `resend_count` · dry run.

**Prerequisites:** a working OnlyFans session; vault media for images. For a
**paid** post the account must be a free page — a paid-subscription page has no
paid-post lane on OnlyFans.

**Caveats:**
- Price is in **dollars**. Typing 1000 meaning $10 posts a $1,000 post.
- On a paid-subscription page a priced item is silently **dropped**, not posted
  free — you get a partial drop with no error.
- The saved rule's timer and the payload's resend cycle both run, so a list can
  repost on two clocks at once. The editor defaults the timer to every 24 hours.
- The resend cycle needs **both** `resend_after_hours` and `resend_count` above
  zero; setting only one does nothing.

## kind: auto_stories — Auto stories (from a vault folder)

**What it does:** On a schedule, posts random photos from a vault folder as
OnlyFans stories, each optionally deleting itself after a set number of hours. It
also hides the duplicate copy OnlyFans files in the vault when it re-uploads the
photo.

**Where:** My Automations → **Auto Story** (`/growth/auto-story`).

**How to enable:** Pick a folder, choose a schedule, switch Enabled on, press
**Create automation** / **Save**.

**Key knobs:** vault folder (and/or hand-picked images — they combine into one
pool) · stories per fire (1) · `hours_to_live` (the page offers 6; 0 = keep) ·
remove the re-uploaded vault duplicate (on) · optional watermark · schedule
either **"At set times each day"** (clock times, default 09:00) or **"Every few
hours"** (default 6) · optional total run limit.

**Prerequisites:** a working OnlyFans session and a vault folder containing
photos.

**Caveats:**
- **Only photos are ever posted.** Videos in the folder are invisible, and only
  the folder's 48 most recent non-DRM photos are ever in the pool.
- **"Total runs" counts every auto-stories run this account has ever had** — from
  any rule and every "Run now" — not this rule's runs. A number below the
  account's history disables the rule on the very next tick.
- Clock times are frozen with the time-zone offset of the browser you saved from.
  Save from another zone, or ride through a daylight-saving change, and the
  stories move by an hour until you re-save.
- "Every few hours" posts its first story right away — within about 30 seconds
  of saving — and then every N hours after that. Do not also press Run now
  straight after saving, or you post two stories back to back. (The page's own
  helper text says otherwise; the page is wrong.)

## kind: unsend_messages — Unsend messages

**What it does:** Deletes messages already sent — a whole broadcast pulled back
from every recipient, individual chat bubbles, a feed post or a story, or a sweep
that cleans up anything older than the hours you set.

**Where:** **Growth → Smart Messages → Mass Messages → OF mass messages → the
"Auto-unsend (automation)" card.** Tick the model, set the hours per class,
Save. To pull back one broadcast by hand, use the unsend button in the sent list
on the same tab.

**How to enable:** Saving that card creates or updates one hourly rule per
account named "Auto-unsend mass". Ticking alone does nothing until you Save.

**Key knobs:** auto-unsend free text-only broadcasts after N hours (the card
offers 4, on by default) · broadcasts with image/video after N hours (the card
offers 24) · **priced PPV broadcasts after N hours (the card offers 48)** · a
class left unticked is kept forever.

**Caveats:**
- **A priced broadcast is never auto-unsent before 24 hours**, whatever you type
  — your number is silently raised. About half of PPV revenue lands more than 4
  hours after the send.
- An unsend job with a blank policy does **not** do nothing: it falls through to
  the per-chat sweep and deletes your own text-only bubbles older than 9 hours
  across every chat.
- Each sweep removes at most 200 items per run **in total** — the ticked classes
  share that one allowance, oldest first — so a big backlog clears gradually over
  many hourly runs, and one large class can use up the whole run's budget before
  the others are reached.
- Unsending a funnel's opening broadcast permanently stops new fans enrolling
  into that funnel.
- Every removal is irreversible and is recorded against "Automation", not a named
  chatter.

## kind: scheduled_send — Scheduled 1:1 send

**What it does:** Delivers a direct message a chatter wrote earlier, at the exact
minute they picked. Because it lives on the server it survives closing the tab,
every chatter on the model sees it queued, any of them can cancel it, and the
delivered message is credited to the chatter who scheduled it.

**Where:** The **schedule picker in the chat composer**. It then shows as a
pending bubble in that fan's chat thread — every chatter on the model sees it
there, and any of them can cancel it from that bubble before it fires.
(Growth → Smart Messages → Mass Messages → "Every scheduled send, direct and
mass" is a *different* list: it shows OnlyFans' own queue, i.e. the sends
further than 15 minutes out.)

**How to enable:** Nothing to enable — it is created automatically whenever a
chatter schedules a message.

**Caveats:**
- Only sends **15 minutes or less** in the future use this. Anything further out
  is handed to OnlyFans' own queue — that is what the "Every scheduled send"
  list on Smart Messages → Mass Messages shows and cancels. The near-term ones
  are cancelled from the pending bubble in the chat thread instead, not from
  that list.
- Cancelling only works while it is still waiting; once the worker picks it up it
  is already on its way.

## kind: customs_watch — Customs owed (tip → voice note)

**What it does:** Tags fans who tipped for a custom and have not received it, and
**stops the AI selling to them** until it ships. It sends the fan nothing.

**Where:** The rule has no page any more (it was added from the rules list); a
rule that already exists keeps running. The work queue is **Analytics → Message
dashboard → Customs** — visible to chatters. A debt clears two ways: someone clears it there, or the watch's next
sweep sees the voice note actually go out to that fan and clears it itself.

**Clearing a debt:** open **Analytics → Message dashboard → Customs**. It is one cross-account queue,
split into two lists: **Owed** (he paid, the voice note has not gone out) and
**Worth a look** (a tip big enough to be an order that nothing tagged — it may
just have been generosity). Each row shows how long he has been
waiting — red past two days — the fan, the model, what he paid and his lifetime
spend. **Read** opens the messages around that tip without leaving the page: the
tip says he paid, the conversation says what he paid *for*. Once the voice note
has actually gone out, press **Sent**. That settles the row in Inflowwww and lifts
the "he already paid, stop selling" brake so the AI can sell to him again;
nothing is pushed to OnlyFans. On a *Worth a look* row the same button reads
**Dismiss** and just settles it so it stops coming back.

`customs_watch` also clears a row by itself if it sees a voice note go out in
that thread after he paid. If an account has been taking custom-sized tips with
no `customs_watch` enabled, an amber banner at the top of the tab names it.

**Key knobs:** `min_cents` how big a tip burst counts as an order (default
**$50**) · look back 72 hours · 200 tips per run · dry run.

**Caveats:**
- **Set `min_cents` above $100 and the trap is silent:** a chatter can quote a
  price this watch refuses to book, so a fan pays and is never marked as owed.
- Stacked tips inside one burst are **one** order, not several — the amount
  encodes how *long* the voice note is, not how many.
- It marks a fan owed with **no timeout** — nothing expires on its own. The bot
  will not sell to him until the debt clears, either by someone clearing him on
  the Customs tab or by the watch seeing the voice note go out. If the custom is
  never delivered and nobody clears it, he stays blocked forever. That is
  deliberate.
- An account that takes custom-sized tips with no enabled rule looks exactly like
  a healthy empty queue — the Customs tab prints an amber warning listing those
  accounts.

## kind: auto_follow — Auto-follow

**What it does:** Follows fans whose subscriptions have expired, so OnlyFans sends
them a "started following you" **notification**. It never sends a message and
costs no AI credits. Following is the only thing it does.

**Where:** **Growth → Auto-follow.** One row per creator with an on/off switch and
follow counts (Today, Yesterday, 7 days, 30 days, Total, Last followed); a row's
details list the fans it followed. Owner/admin only. There are no other settings.

**How to enable:** Turn the creator's switch on. That creates the creator's rule:
it follows OnlyFans' recently-expired subscribers, live (not a dry run), with the
money gate on. A creator that already had a rule keeps its own settings.

**"Can I follow fans back after they expire?"** Yes, that is exactly what the
switch does. A fan with a lapsed relationship is re-armed and counted as
"refollowed". To also follow fans who just subscribed, turn on "Auto follow back
my fans" in OnlyFans' own Fans and following settings.

**Caveats:**
- It only ever follows **free** profiles. A page with a subscription price, or
  one whose price cannot be read, is skipped, because following a paid page would
  spend money. A run that follows nobody is normal on a roster of paid pages.
- Fans you already follow are left alone, and a fan notified in the last 14 days
  (by Auto-follow or by a welcome / lifecycle follow) is not followed again.
- The counts are only the fans Auto-follow followed, not every follow on the
  account.
- It has no like or "ping" (unfollow + re-follow) mode any more. A rule saved
  with one of those, or with no action, is skipped and does nothing.

## kind: promo_reactivate — Keep promos running

**What it does:** OnlyFans ends a profile promotion when its clock runs out or its
claim cap fills. This checks the campaigns you marked "Keep running" and, if
nothing is on offer any more, re-creates the same campaign with the same terms.

**Where:** **Growth → Profile promotion** → the **Auto-activate campaign**
switch and the **Keep promos running** card under it. None of its knobs are
anywhere else.

**How to enable — three things, all required:** tick **"Keep running"** on the
individual campaign in Campaign insights; turn **Auto-activate campaign** on
(it saves when you flip it); and in the Keep promos running card **untick Dry
run** and press **Save changes** (**Create automation** the first time).

**Key knobs:** check every 60 minutes · dry run (**on** by default) · max re-arms
per campaign (0 = unlimited).

**Caveats:**
- Dry run is on by default, so an operator who switches it on and saves gets
  an automation that reports forever and re-creates nothing.
- **Only one campaign per account can be set to "Keep running."** Arming a second
  is refused.
- If any promo is live on the profile — including one made by hand — it stands
  down and re-creates nothing.
- "Check now" runs the last saved config; with dry run off it can create a real
  public promo immediately.

## kind: gen_info — Generate fan profiles

**What it does:** Reads each fan's stored chat history and has the AI write him a
profile — a nickname tag, a one-line bio and a fact sheet — plus the facts it
found (age, city, job, hobbies, language). It writes **no questions or teases**
any more; lines a fan already had stay, nothing new is added. After each profile
it fills the fan drawer's tabs on OnlyFans: the **Nickname** (Name/City,Country/
Age/Job, e.g. Garrett/Delta,Canada/30/Paramedic) and the **Fan notes** (a
200-character fact sheet: Recent, Intr, Job, Rel, Kinks, then the bio). The
drawer's Location and Language read the facts it saved.

**Where:** My Automations → **Gen-Info** (`/growth/gen-info`): one switch, which
creates the daily rule the first time.

**Key knobs:** `limit` 200 fans per run, highest spend first · `model` ·
`force_ids` profile these now ignoring every gate · `refill_ids` narrow the pass
with gates on.

**Prerequisites:** an AI key; chat history already in the system (it reads that
from our own database, never from OnlyFans); daily AI cap headroom. Note: after
it writes a profile it re-pushes the structured nickname onto OnlyFans, so an
OnlyFans nickname a human typed can be overwritten even with Apply profiles'
"push to OF" left off. Fan notes are only written when the fan has none yet or
still has the one it wrote last, so a note typed in the drawer is kept.

**Caveats:**
- A fan is never profiled until he has sent **8 new messages** since his last
  profile. Raising the limit or the cadence will not profile a quiet fan — only
  `force_ids` will.
- OnlyFans keeps notes for subscribers only, so a fan who is not subscribed
  gets the nickname but no Fan notes.
- Refresh frequency is set by his spending, not your cadence: every 2 days for
  anyone who spent in the last 7 days, is a $500+ lifetime whale, subscribed in
  the last 7 days, or has ever spent anything at all; every 7 days only for fans
  with $0 lifetime who are not new subscribers. Your cadence only controls how
  often it looks.

## kind: apply_profiles — Apply profiles (nick + notes)

**What it does:** Stamps the generated profiles onto the fan — the cleaned
nickname and a 200-character fact-sheet note. By default into Inflowwww only; tick
"push to OF" and it also writes them onto OnlyFans where the whole team sees them.

**Where:** It has no page any more as a rule (it was added from the rules list); a rule that
already exists keeps running. It also runs automatically as the second half of
Onboard pre-AI fans.

**Key knobs:** `limit` 500 per run · `force_ids` bypass the 24-hour cooldown ·
`push_to_of` (off).

**Caveats:**
- The sweep is ordered by fan id, lowest first, and cut at the limit — on a big
  account the same low ids are re-checked every run and higher ids are never
  reached. Raise the limit, not the cadence.
- The note only lands on OnlyFans for **current subscribers**; an expired fan gets
  the nickname and no note, and the run still says success.
- `push_to_of` **overwrites** whatever a human typed in those OnlyFans fields.

## kind: process_old_fans — Onboard pre-AI fans

**What it does:** A one-time catch-up over fans who subscribed before the AI was
running. It flags them so the warm-up chatter never opens a conversation with
them cold, then builds their profile and applies the nickname and note. **It
sends no messages.**

**Where:** My Automations → **Gen-Info**, the card under the switch.

**How to enable:** It is a button, not a switch. Set **How many** and **Most
recent by**, press **Also run on old fans**, confirm.

**Key knobs:** **How many** recent fans (the card pre-fills 100) · **Most recent
by** subscribed or messaged. From this card the nicknames and notes are also
pushed to OnlyFans.

**Caveats:**
- **It cannot be undone from this screen** — every fan in the batch gets a
  permanent pre-AI flag.
- It is an action, not a loop. Built as a recurring rule it re-flags your newest
  subscribers as pre-AI fans on every tick, which is the opposite of onboarding.

## kind: scrape_chats — Backfill chat history

**What it does:** Pulls conversation history down from OnlyFans to fill gaps the
live message feed missed.

**Where:** It has no page any more as a rule (it was added from the rules list); a rule that
already exists keeps running.

**Key knobs:** `limit` chats per sweep (the editor suggests 50; a blank value
actually covers 100) · `max_pages` 40 · `fan_ids` to backfill specific chats.

**Caveats:**
- It does **not** fetch a whole conversation: per chat it keeps roughly the newest
  100 messages plus, once only, about 100 from the very beginning. The middle of a
  long history is skipped on purpose.
- The sweep walks the inbox most-recently-active first, so quiet old chats sit
  past whatever limit you set — name the fan in `fan_ids` to reach him.
- Every connected account gets one automatic sweep when the relay restarts, so
  you will see backfill runs nobody scheduled.

## kind: smart_list_sync — Smart List → OnlyFans list sync

**What it does:** For every Smart List switched to **Sync**, keeps an
OnlyFans list of the same name holding exactly the fans who match. Runs every 30
minutes, and right after you activate or edit a list. It only changes list
membership — it never messages anyone.

**Where:** Growth → Smart lists → **Sync** / **Stop sync** on a list row; the
row shows synced / catching up / sync error, "Last updated" and how many fans
are on the OnlyFans list.

**How to enable:** Press **Sync** on a list. The rule is created for you the
first time.

**Caveats:**
- At most 10 lists per model sync at once (the relay's `SMART_LIST_MAX_ACTIVE`).
- It reads the whole OnlyFans list before removing anyone; if that read is
  incomplete, or a subscription rule's roster is unavailable, it changes nothing
  and shows a sync error.
- Writes are paced and capped per run (about 40 per run across all lists), so a
  big list fills over several runs — "catching up" until it is done.
- Lists above 19,000 matching fans are not synced.
- While a list shows "syncing…", Edit, Delete and Stop sync are refused — try
  again in a moment.
- **Stop sync** leaves the OnlyFans list as it is. If you delete the list on
  OnlyFans, the next sync creates a fresh one.

## kind: s4s_post, s4s_check — Share for Share posts

**What it does:** Two creators promote each other: at an agreed time each one's
feed carries a post about the other. `s4s_post` publishes a slot's post on the
poster's feed; `s4s_check` checks, shortly before it comes down, that the post
stayed up untouched. Owner-only.

**Where:** the **Share for Share** pages:
- **Discover creators** — send a request with a proposed time (UTC; it offers
  06:00 on the first day with room under both creators' daily limits), and
  **Block** a creator (**Blocked creators** lists them).
- **Requests** — **Received** and **Sent**: **Accept**, **Decline**, **Skip**,
  **View Schedule**, **Review**, **Cancel**.
- **S4S schedule** — every agreed slot, in UTC, with its status: "Will be
  posted shortly", "In progress", "Complete", "Cancelled" or "Failed" (with the
  reason), the partner's post, and **Cancel** on a slot.
- **S4S settings** — the **Primary post** your partners publish (**Create
  post** / **Manage posts**, up to 20, each with up to 5 items via **Add from
  Vault**), **Limit daily S4S** (1, 2 or 3), the discoverability settings ("Take
  part in Share for Share", "Profile shown to partners").

**How to enable:** turn on "Take part in Share for Share" and agree a slot.
Accepted slots post on their own.

**Caveats:**
- At the slot time the partner's caption goes up with an @mention of the
  partner and "#advertisement", with the partner's media copied to your
  account, through Auto Post. It stays live 24 hours and is then removed.
- A slot is cancelled when live S4S posting is off on this deployment, when
  either side has stopped taking part, or when it is more than 24 hours late.
  A failed post names why: the media was missing or could not be fetched, the
  upload failed, or the post was interrupted.
- `s4s_check` runs 30 minutes before the removal and only reads: the slot is
  marked failed if the post was deleted, archived or edited on the poster's
  account. It removes nothing; the post still comes down on time.

---

# NOT SUPPORTED

These come up often and genuinely do not exist. Say so plainly, then point at the
nearest real thing.

**Posting to Instagram, X/Twitter, TikTok, Reddit or any other platform.**
OnlyFans only. The bot is in fact actively *blocked* from mentioning off-platform
contact, because that is flaggable on OnlyFans. Nearest real thing: Growth →
Tracking links builds an OnlyFans link you paste on the other platform
yourself, and OnlyFans counts the clicks and the subscribers it produced.

**Unsending a 1:1 chat message older than about 24 hours.** That is OnlyFans'
own edit window; past it OnlyFans refuses. Important near-miss: a **mass
broadcast has no window at all** — it can be pulled back from every recipient
basically forever, via the chat prompt "also unsend from everyone who received
it?" or the Auto-unsend sweep.

**Editing a message you already sent.** There is no edit anywhere, in Inflowwww or
via OnlyFans' API. Unsend and resend instead. (Feed *posts* can be edited.)

**A true "the moment he logs in" trigger.** Login detection is polling, about
once a minute — that is Nudge Online, and it is the closest thing that exists.
Real-time dispatch for an inbound **message** (⚡ Reply Instant) has no page any
more.

**Automatic delivery of a custom.** Deliberate product ruling, not a gap. The
product is a **voice note**, a person records and sends it, and the amount tipped
encodes how *long* it is, not how many. What Inflowwww does: notice a $50+ tip burst,
mark the fan owed, **stop the bot selling to him**, and put the debt on
Analytics → Message dashboard → Customs for a human to clear.

**Sending a story to specific fans.** A story has no audience — OnlyFans' story
endpoint takes no recipient list, and Auto Story has no targeting knob. If the
point is reaching specific people, send a message instead.

**Permanently deleting media from the OnlyFans vault.** OnlyFans has no
hard-delete for vault media. What "remove" does — in Inflowwww and in OnlyFans' own
web app — is **hide** it: anything already attached to a sent PPV or a live post
keeps working, and there is no unhide, so treat it as one-way. Folders *can* be
deleted for real.

**AI-generated voice notes or audio of any kind.** There is no text-to-speech in
the product. (Careful: the "voice" settings mean the *writing* voice — whether
the account writes as a woman or a man.)

**Replying to comments on posts.** No screen for it — nothing in Inflowwww opens a
comment thread or answers one, and comments are not part of any automation lane.
Comment *counts* do show on post cards, and Analytics → Message dashboard → Top
Posts can sort by comments, but that is the whole of it. Reply in OnlyFans.

**Running or scheduling OnlyFans live streams.** Streams are read-only in the
API and are not surfaced anywhere in the app. Run them in OnlyFans.

**Requesting a payout or withdrawing earnings.** Money is read-only here —
balances and payout eligibility are shown, but nothing moves money. Withdraw in
OnlyFans.

**Scheduling the *Auto posts automation* to a specific clock time.** Auto posts
runs on an interval with per-post delays, not at a wall-clock time. Everything
else timed *is* supported: a **one-off feed post** (OF Manager → New post, set
its Schedule), a **1:1 DM** (the schedule picker in the chat composer), a **mass
message** (from the Mass message composer), and **Auto Story** at set times each
day.

---

# When someone says "I turned it on and nothing happened"

Work down this list:

1. **Is the account's OnlyFans session still alive?** Check **Creators → Manage
   creators**. A model showing a red **"automations paused"** badge with
   **"unlinked N ago"** next to it has lost its OnlyFans login — either OnlyFans
   rejected the login (the creator logged in elsewhere or unlinked it) or there
   is no captured session for that account on this host. Hover the badge and it
   tells you which. While that badge is up **every** automation on that account
   is skipped: nothing sends, queued jobs are left parked, and — this is the
   part that misleads people — **no run rows are written at all**. The rules
   all still read "enabled."
   **Fix:** re-capture the session (Creators → Manage creators, the Paste cURL
   step). That clears the pause immediately and the parked jobs resume on the
   next tick. The relay also re-tests a paused account on its own and un-pauses
   it the first time the session works — every 10 min for the first hour, every
   30 min for the first day, hourly for the first week, then every 6 hours.
2. **Is there an enabled rule?** Check that the automation's own page shows it
   switched on (My Automations, or the trigger's row on Growth → Smart
   Messages). An automation with no page any more cannot be checked from the
   app.
3. **Is dry run still on?** The **Keep promos running** card on Growth →
   Profile promotion defaults to dry run.
4. **Is the agency AI key set?** Settings → AI keys. Without it every
   AI-written message fails closed — Auto-reply, follow-ups, profiles. The
   welcome and the nudges still send, because their text is not AI-written.
5. **Is the daily AI cap used up?** The cap has no page any more (see "The
   Brain"). Runs at the cap still report "ok" and just do less.
6. **Is a cooldown eating it?** Most senders skip a fan any automation or chatter
   touched recently — commonly 6 or 12 hours. An empty cooldown box means the
   default, not off. A guard with no box on its page can only be changed
   through that page's raw JSON, where it has one (see "Editing the raw JSON").
7. **Is the fan restricted?** The chat header's ⋯ menu reads **Lift restrict**
   for a fan restricted on OnlyFans — a hard skip.
8. **Is he owed a custom?** A fan on the Analytics → Message dashboard → Customs
   queue is deliberately withheld from selling until the debt is cleared.
9. **Is the Audience fence on and Enforce halted?** It has no page any more,
   and its folder sync was removed, so an account left in Enforce halts the
   gated automations once its last snapshot is a day old. The deployment
   operator has to check it.
10. **Did a page's Save wipe the setting?** Several pages rebuild their whole
    payload on Save and drop anything set through raw JSON. Re-check after
    saving.
11. **There is no run log an owner can open** any more. Ask the deployment
    operator to read it — and check a paused account's badge on Creators →
    Manage creators first, since a paused account writes no runs at all.
