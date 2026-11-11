# Videos — what to record once the UI settles

All videos are recorded on the live demo: **https://demo.inflowwww.com**, login `demodemo` / `demodemo`.
The demo has 20 creators, about $400k over 30 days, a sale about every minute, fans writing in, and the AI chatter and automations running.
Seed facts: `docs/spec/demo-stack.md`, `demo/README.md`.

Each card below says which screen to start on, what has to be on screen, and what to say. Exact clicks are left as *fill in at freeze*, because the UI is still changing and click paths would go stale.

---

## 1. Before you press record

- [ ] **UI freeze:** UI changes are done, `deploy-all` has run, and the demo matches `main`.
- [ ] **Stop the nightly reset:** run `systemctl stop demo-reset.timer` on the demo box, and start it again afterwards. The reset runs at 04:00 UTC and would wipe the data mid-take.
- [ ] **AI replies:** the daily AI cap is fresh. Record videos 2 and 4 first. Once the cap is spent, replies switch to canned text.
- [ ] **Videos that move:** demo vault videos must show visible motion before video 3 is recorded. See §5, item 1.
- [ ] **Clear the tips:** dismiss every first-visit tip once (Vault Pro shows a "Click + Add media…" tip with a "Got it" button).
- [ ] **Browser:** clean profile, 1440×900 at 100% zoom, no bookmarks bar, no notifications. Phone takes use 390×844.
- [ ] **Dry run:** walk every card once on the demo and save a screenshot per card in `slop/evidence/<date>-video-dryrun/`.
- [ ] **Prices:** re-check Infloww's pricing page the same day (video 9) and show the date on screen.
- [ ] **Screen content:** only demo creators (Ava, Luna, Mia…) are on screen. No real fans, real tabs or real email.

## 2. The series

| # | Video | Length | Who it's for |
|---|---|---|---|
| 0 | **A day in an agency**: the hero cut, made from the best takes of videos 1–9 | 60–90 s | landing page, socials |
| 1 | Tour of the app | 3 min | first-time visitor |
| 2 | Messages Pro: replying and selling | 5 min | chatters |
| 3 | Vault Pro and hover previews | 2 min | chatters, managers |
| 4 | Smart Messages and the AI chatter | 4 min | owners |
| 5 | Scripts, tracking links, auto-follow | 3 min | managers |
| 6 | Analytics and CSV export | 4 min | owners |
| 7 | Employees, shifts, clock-in, roles, audit | 4 min | owners, managers |
| 8 | Notifications and quick reply | 2 min | chatters |
| 9 | Free vs $40–$500 per creator | 2 min | owners comparing tools |
| later | Install it on your own server | 5 min | technical owners. The demo locks sign-up and add-creator, so record this on a fresh install. |

Record 1–9 first, then cut 0 from them.

## 3. Cards

Every card uses the same fields:
- **Start:** the URL to open.
- **Show:** what must appear on screen, in order.
- **Say:** the line to say.
- **Don't show:** screens to stay away from.
- **Proof shot:** the one frame that backs the claim.
- **Done when:** the end state on screen.

### 0 · A day in an agency (hero, 60–90 s)
- **Show:**
  1. The Dashboard total ticks up as a sale lands.
  2. A fan DM arrives in Messages Pro.
  3. Hover a vault video, see inside it, and send it as a paid message.
  4. A Smart Message fires in its run history.
  5. Who is clocked in right now.
  6. The same inbox on a phone.
  7. End card: "Free. Your server. Your data."
- **Say:** "Everything an agency runs on, open source, on your own server."
- **Done when:** the end card is up with demo.inflowwww.com and the login.

### 1 · Tour (3 min)
- **Start:** `/login`, which is already filled in.
- **Show:** the Dashboard (earnings, My shifts, who is clocked in), then the sidebar: Messages Pro, Vault Pro, Growth, Analytics, Creators, Employees, Settings. End with the bell and a live toast.
- **Say:** "Twenty creators, sales coming in live. Here's where everything lives."
- **Don't show:** Fansly Manager, Help center, OF Manager Queue/Collections.
- **Proof shot:** the Dashboard total moving between two frames.

### 2 · Messages Pro (5 min)
- **Start:** `/messages-pro`.
- **Show:**
  1. Fan List with filters and the **Owe reply** chip.
  2. Open a thread while a live DM arrives.
  3. Copilot gives 3 suggested replies; pick one.
  4. In the composer: emoji/GIF, the PPV price row, **+5/+15/+60 min send-at**.
  5. The vault picker: hover a video, add it, set a price, send.
  6. The fan drawer and insights (spend, sales).
  7. **Alt+T** translation.
  8. Group chat (up to 8 threads).
  9. Pop-out window.
- **Say:** "One inbox for every creator. AI drafts, you decide."
- **Don't show:** controls marked *not wired* in `docs/messages-pro-parity.md`.
- **Proof shot:** the paid message sent and showing as locked in the thread.

### 3 · Vault Pro and hover previews (2 min)
- **Start:** `/growth/vault-pro`.
- **Show:**
  1. Folders (Beach day, Gym & fitness…) with photo and video counts.
  2. Rest the pointer on a video tile for half a second: it plays a preview strip.
  3. Brush quickly across 20 tiles: nothing loads.
  4. Click a tile to play and seek.
  5. The same hover inside the chat vault picker and in fan insights → Sales.
- **Say:** "See what's in a video before you send it, without opening it."
- **Proof shot:** before and after the dwell on one tile (see §4).
- **Needs:** §5, item 1.

### 4 · Smart Messages and AI chatter (4 min)
- **Start:** `/growth/smart-messages`.
- **Show:**
  1. The five rules that are on (welcome, purchase follow-up, expiry, expired, resubscribe).
  2. 12 h of run history.
  3. Open one rule.
  4. My AI Chatter: it answers a fan nobody had replied to. Show it in the thread.
- **Say:** "Set it once; it works every fan, every creator, all night."
- **Don't show:** Auto Story / Auto Mass / Auto Funnel. They have no seeded rules, so they'd be empty.
- **Proof shot:** a run-history row next to the message it sent.

### 5 · Scripts, tracking links, auto-follow (3 min)
- **Start:** `/growth/scripts`, then `/growth/tracking-links`, then `/growth/auto-follow`.
- **Show:** the script library with prices; tracking links with their numbers; auto-follow switched on.
- **Don't show:** Profile promotion, Free trial links, Share for Share. They're unverified or not wired.

### 6 · Analytics (4 min)
- **Start:** `/analytics/creator-reports`.
- **Show:**
  1. Creator reports, Overview and Performance.
  2. Employee reports and the chatter leaderboard.
  3. Sales records with filters, then CSV export.
  4. Fan reports.
  5. Message dashboard.
- **Say:** "Who earned what, which chatter sold it, exported in one click."
- **Don't show:** the Creator-tag filter in Sales records (disabled).
- **Proof shot:** the opened CSV matches the on-screen total.

### 7 · Team (4 min)
- **Start:** `/employees`.
- **Show:**
  1. 12 employees and the org chart.
  2. `/employees/shifts`: the week calendar; create a repeating shift.
  3. Clock in from the top bar.
  4. The hours show up in Employee reports.
  5. `/settings/roles`: per-page permissions.
  6. `/settings/audit`: the audit log.
- **Don't show:** employee Delete (disabled); Settings → Billing, Upload picture, Change password (not wired or locked).

### 8 · Notifications (2 min)
- **Start:** any page, with the bell visible.
- **Show:**
  1. A live toast.
  2. The bell badge.
  3. `/notifications` tabs (Purchases, Tips…).
  4. Reply to a fan straight from a notification.
  5. Notification settings: OS ping and the money rail.

### 9 · Free vs paid (2 min)
- **Start:** `inflowwww.com/openinflowwww-vs-infloww/` (comparison page).
- **Show:** Infloww's pricing page with today's date, then our MIT licence and the `docker compose up` quick start.
- **Say:** "Forty creators: $1,600 to $20,000 a month there. Free here. You pay for your server and your AI key."
- **Must include:** the comparison page's own "we lose" rows (uptime, support). Honesty sells.

## 4. Where we beat Infloww (what to show on camera)

| What | How to show it | Proof we have | Line to say |
|---|---|---|---|
| **Free, open source, your own server** | Video 9: their pricing page next to our licence and quick start | `LICENSE` (MIT), `README.md`; their prices captured in `web/src/openinflowwww-vs-infloww.njk` | "Free. Your server, your data." |
| **Hover a video to see inside it** | Video 3: rest on a tile, then brush across many tiles | **Measured** on the live demo 2026-11-11: one hover made 12 preview-frame requests; brushing across 11 video tiles made **0** (`slop/evidence/20261111T-video-plan/hover.json`). The vault, chat picker and fan sales share the same hover code (`app/hooks/useHoverPreview.ts`). | "See what's in a video before you send it." |
| **Fast, even on a slow connection** | A stopwatch overlay: reload the Dashboard; open a fan chat | **Measured** on our test rig with a 250 ms delay added: the Dashboard reload painted in 1.2 s with 0 calls to OnlyFans; opening a fan chat painted in 0.9 s (`slop/evidence/20261105T161842Z-2026-11-05-clicks-first-3324/metrics.json`). Live demo from a Mac, one run, 2026-11-11: every page frame was up in under 0.4 s, and pages finished loading in 0.8–3.2 s (`slop/evidence/20261111T-video-plan/probe.json`). | "About a second, even on a slow connection." Don't say "faster than Infloww" without §5, item 2. |
| **One slow creator doesn't freeze the rest** | The Dashboard with many creators: the others fill in while one is slow | **Measured** on the test rig (`slop/evidence/20261105T155311Z-2026-11-05-screen-bundles-7b4a/summary.txt`) | "One stuck account never blocks the others." |
| **Works on your phone** | The 390 px phone layout of the inbox: one pane at a time | Comparison page: Infloww's phone dashboard is still on their roadmap (`web/src/openinflowwww-vs-infloww.njk`) | "Works in your phone's browser." Not "phone app". |
| **Messages Pro extras** | Video 2: Owe-reply chip, send-at presets, group chat of 8, Alt+T translation | `docs/messages-pro-parity.md` (Ours section), `app/lib/openinflowwwwExtras.ts` | "Small things chatters use all day." |
| **AI on your own key** | Video 4: the AI chatter replies, and the cost goes to your own LLM key | `docs/routes.md`, `VISION.md` | "Your AI, your key, cost price." Not "only we have AI": Infloww sells an AI Copilot. |

**Never claim:**
- Faster than Infloww, or any percent speed-up, without a side-by-side recording.
- Uptime, support or security. The comparison page says we lose on uptime and support.
- Fansly or other platforms. Fansly is 4 of 16 pages.
- A native phone app.
- A full OF Manager.
- Auto-renew campaigns.
- Big-vault speed. The `/duplicates` read is known slow.
- A hover-preview on/off setting. None exists yet; see §5, item 3.

## 5. To do before recording

1. **Demo videos need real motion.** Today each demo video is a slow zoom on a single photo (`demo/media.py`, `-loop 1`). The hover preview fires (measured), but its frames barely change on camera. Render each mp4 as a 3–4 photo slideshow so the preview visibly changes.
2. **Side-by-side speed (optional).** To say "faster than Infloww", record both apps on the same machine and network, opening the same kind of screen. Without that recording, use only the line in §4.
3. **Owner question: a hover-preview setting?** "Option on video hover to show" was read as *show the hover preview in the videos*. No setting exists, and the timings are fixed in `app/hooks/useHoverPreview.ts`. Fable advised not to build one unless you want it (yes/no).

Answer: *(owner fills in)*
