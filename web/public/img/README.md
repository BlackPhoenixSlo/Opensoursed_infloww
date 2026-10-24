# Product shots

## 2026-10-23: demo-agency shots

138 files (5,145,866 bytes): 23 screens x 6 sizes, named `<screen>.webp`
(1280x800), `-640` (640x400), `-phone` (390x844), `-phone-780` (780x1688),
`-combo` (1440x900, the phone shot at ~24% width over the desktop shot's
bottom-right, 5px dark ring, rounded corners, soft shadow, solid page
background) and `-combo-720` (720x450).

**Method.** `scripts/demo-shots/run.sh` (see its README) starts a throwaway
localhost stack: the relay on a temp SQLite database seeded with a synthetic
agency, `next dev`, and headless Chromium (Playwright, device scale 2,
1280x800 desktop and 390x844 phone viewports, light mode, the owner signed in;
the dashboard shot signs in as manager Jordan Lee so My shifts is filled,
and the Messages Pro desktop shots use a 1600x1000 viewport so the thread
fits 9 or more bubbles). Each combo keeps the phone clear of the shot's key figure
(dashboard total, creator-reports total, the thread's last bubble).
Every shot also checks that the app font, Instrument Sans (next/font/local),
loaded and painted the text. OnlyFans reads are answered from the same dataset by request fixtures; the
browser and server cannot reach the internet. The page clock is pinned to
2026-10-22 22:40 UTC. Each shot waits for its data and fails on loading rows,
`$0.00` or "No creators". Encoded with `cwebp -q 80 -m 6 -sharp_yuv`, resized
with ImageMagick Lanczos.

**Dataset.** Agency "Northstar Studio": 20 creators earning $1,000,420 net
this month (top $180,000, bottom $8,000), 12 employees (owner, 2 managers,
9 chatters) with shifts and 435 clock events, 2,600 fans on 18,703
subscriptions, 62,494 sales over the 35 days to the anchor, 150,437
messages, 14 scripts, 8 vault folders, auto posts, 47 tracking links, smart
messages, 12 S4S partners and roles. Seeded from a fixed seed, so a
re-run on the same anchor gives the same figures.

**Privacy.** All data is synthetic: names, handles, ids, amounts and messages
are generated. Portraits come from pravatar.cc (CC0); photo media from
picsum.photos (Unsplash License). No real account, fan or session was used.

| File | Pixels | Bytes | Shows | Suggested alt |
|---|---|---|---|---|
| `dashboard.webp` | 1280x800 | 43,084 | Dashboard signed in as manager Jordan Lee, This month, gross: $1,005,875 total earnings (whole dollars), the six earning kinds, My shifts filled (this week and next), Employee sales ranking | Inflowwww dashboard showing $1,005,875 in creator earnings this month |
| `dashboard-640.webp` | 640x400 | 16,544 | Same, half size | (same as above) |
| `dashboard-phone.webp` | 390x844 | 16,240 | Phone (390x844 viewport @2x, downsized) | Inflowwww dashboard showing $1,005,875 in creator earnings this month |
| `dashboard-phone-780.webp` | 780x1688 | 35,890 | Phone, 2x | (same as above) |
| `dashboard-combo.webp` | 1440x900 | 56,444 | Desktop with the phone shot over its bottom-right | Inflowwww dashboard showing $1,005,875 in creator earnings this month |
| `dashboard-combo-720.webp` | 720x450 | 22,776 | Combo, half size | (same as above) |
| `dashboard-kpis.webp` | 1280x800 | 78,218 | Dashboard scrolled to Per-model KPIs: 20 model cards, each with total revenue incl. pending, PPV/post/tip/sub/rebill/other chips, fans, new subs, LTV, ARPU, messages, PPVs sold (top: Ava Monroe $180,009) | Per-model KPI cards for 20 creators, led by $180,009 in revenue |
| `dashboard-kpis-640.webp` | 640x400 | 26,914 | Same, half size | (same as above) |
| `dashboard-kpis-phone.webp` | 390x844 | 24,532 | Phone (390x844 viewport @2x, downsized) | Per-model KPI cards for 20 creators, led by $180,009 in revenue |
| `dashboard-kpis-phone-780.webp` | 780x1688 | 58,538 | Phone, 2x | (same as above) |
| `dashboard-kpis-combo.webp` | 1440x900 | 88,958 | Desktop with the phone shot over its bottom-right | Per-model KPI cards for 20 creators, led by $180,009 in revenue |
| `dashboard-kpis-combo-720.webp` | 720x450 | 31,624 | Combo, half size | (same as above) |
| `messages-pro.webp` | 1280x800 | 44,988 | Messages Pro (1600x1000 viewport, downsized): Ava's chats with spend chips and an open thread scrolled to the latest with 9 bubbles: short fan and creator lines, a photo, a paid $45 PPV, a $50 tip and the composer's script hint; phone: the All Models chat list | Messages Pro inbox with a fan thread showing a paid PPV and a $50 tip |
| `messages-pro-640.webp` | 640x400 | 15,694 | Same, half size | (same as above) |
| `messages-pro-phone.webp` | 390x844 | 24,190 | Phone (390x844 viewport @2x, downsized) | Messages Pro inbox with a fan thread showing a paid PPV and a $50 tip |
| `messages-pro-phone-780.webp` | 780x1688 | 54,474 | Phone, 2x | (same as above) |
| `messages-pro-combo.webp` | 1440x900 | 64,162 | Desktop with the phone shot over its bottom-right | Messages Pro inbox with a fan thread showing a paid PPV and a $50 tip |
| `messages-pro-combo-720.webp` | 720x450 | 23,844 | Combo, half size | (same as above) |
| `messages-pro-thread.webp` | 1280x800 | 55,366 | Messages Pro thread (1600x1000 viewport, downsized), 10 bubbles to the latest, with the Fan insights column: $11,135 total spend, PPV and tip totals, purchases over time | A fan chat in Messages Pro with Fan insights showing $11,135 total spend |
| `messages-pro-thread-640.webp` | 640x400 | 19,170 | Same, half size | (same as above) |
| `messages-pro-thread-phone.webp` | 390x844 | 24,116 | Phone (390x844 viewport @2x, downsized) | A fan chat in Messages Pro with Fan insights showing $11,135 total spend |
| `messages-pro-thread-phone-780.webp` | 780x1688 | 55,892 | Phone, 2x | (same as above) |
| `messages-pro-thread-combo.webp` | 1440x900 | 73,308 | Desktop with the phone shot over its bottom-right | A fan chat in Messages Pro with Fan insights showing $11,135 total spend |
| `messages-pro-thread-combo-720.webp` | 720x450 | 26,936 | Combo, half size | (same as above) |
| `creators.webp` | 1280x800 | 56,282 | Manage creators: 20 connected OnlyFans creators with nicknames, accounts and assigned chatters | Manage creators list with 20 connected OnlyFans creators |
| `creators-640.webp` | 640x400 | 21,750 | Same, half size | (same as above) |
| `creators-phone.webp` | 390x844 | 16,588 | Phone (390x844 viewport @2x, downsized) | Manage creators list with 20 connected OnlyFans creators |
| `creators-phone-780.webp` | 780x1688 | 37,384 | Phone, 2x | (same as above) |
| `creators-combo.webp` | 1440x900 | 65,462 | Desktop with the phone shot over its bottom-right | Manage creators list with 20 connected OnlyFans creators |
| `creators-combo-720.webp` | 720x450 | 25,292 | Combo, half size | (same as above) |
| `creator-reports.webp` | 1280x800 | 45,322 | Creator reports: earnings summary (subscriptions, posts, messages, tips, referrals, streams) with change badges and the earnings trend | Creator reports with an earnings summary and a daily earnings chart |
| `creator-reports-640.webp` | 640x400 | 18,676 | Same, half size | (same as above) |
| `creator-reports-phone.webp` | 390x844 | 27,046 | Phone (390x844 viewport @2x, downsized) | Creator reports with an earnings summary and a daily earnings chart |
| `creator-reports-phone-780.webp` | 780x1688 | 58,092 | Phone, 2x | (same as above) |
| `creator-reports-combo.webp` | 1440x900 | 69,906 | Desktop with the phone shot over its bottom-right | Creator reports with an earnings summary and a daily earnings chart |
| `creator-reports-combo-720.webp` | 720x450 | 28,480 | Combo, half size | (same as above) |
| `creator-reports-table.webp` | 1280x800 | 40,958 | Creator reports scrolled to the Creator statistics table, gross: header row and 15 of the 20 creators with subscription, post, message and tip earnings (whole dollars: Ava $7,213 subs, $14,220 tips, $32,125 messages) | Creator statistics table with per-creator earnings for 20 creators |
| `creator-reports-table-640.webp` | 640x400 | 14,438 | Same, half size | (same as above) |
| `creator-reports-table-phone.webp` | 390x844 | 10,830 | Phone (390x844 viewport @2x, downsized) | Creator statistics table with per-creator earnings for 20 creators |
| `creator-reports-table-phone-780.webp` | 780x1688 | 23,864 | Phone, 2x | (same as above) |
| `creator-reports-table-combo.webp` | 1440x900 | 51,588 | Desktop with the phone shot over its bottom-right | Creator statistics table with per-creator earnings for 20 creators |
| `creator-reports-table-combo-720.webp` | 720x450 | 19,244 | Combo, half size | (same as above) |
| `employee-reports.webp` | 1280x800 | 46,806 | Employee reports: employee sales over 30 days and the sales ranking | Employee reports chart of chatter sales over the last 30 days |
| `employee-reports-640.webp` | 640x400 | 17,172 | Same, half size | (same as above) |
| `employee-reports-phone.webp` | 390x844 | 18,254 | Phone (390x844 viewport @2x, downsized) | Employee reports chart of chatter sales over the last 30 days |
| `employee-reports-phone-780.webp` | 780x1688 | 41,300 | Phone, 2x | (same as above) |
| `employee-reports-combo.webp` | 1440x900 | 58,366 | Desktop with the phone shot over its bottom-right | Employee reports chart of chatter sales over the last 30 days |
| `employee-reports-combo-720.webp` | 720x450 | 22,226 | Combo, half size | (same as above) |
| `sales-records.webp` | 1280x800 | 57,978 | Sales records: the latest sales with employee, creator, fan, earnings and Reassign | Sales records table listing each sale with its chatter and creator |
| `sales-records-640.webp` | 640x400 | 21,238 | Same, half size | (same as above) |
| `sales-records-phone.webp` | 390x844 | 23,352 | Phone (390x844 viewport @2x, downsized) | Sales records table listing each sale with its chatter and creator |
| `sales-records-phone-780.webp` | 780x1688 | 53,474 | Phone, 2x | (same as above) |
| `sales-records-combo.webp` | 1440x900 | 79,208 | Desktop with the phone shot over its bottom-right | Sales records table listing each sale with its chatter and creator |
| `sales-records-combo-720.webp` | 720x450 | 29,706 | Combo, half size | (same as above) |
| `message-dashboard.webp` | 1280x800 | 45,114 | Message dashboard: direct messages sent by chatters with creator, message and Unsend | Message dashboard listing chatters' sent messages |
| `message-dashboard-640.webp` | 640x400 | 16,548 | Same, half size | (same as above) |
| `message-dashboard-phone.webp` | 390x844 | 17,010 | Phone (390x844 viewport @2x, downsized) | Message dashboard listing chatters' sent messages |
| `message-dashboard-phone-780.webp` | 780x1688 | 38,612 | Phone, 2x | (same as above) |
| `message-dashboard-combo.webp` | 1440x900 | 56,910 | Desktop with the phone shot over its bottom-right | Message dashboard listing chatters' sent messages |
| `message-dashboard-combo-720.webp` | 720x450 | 21,650 | Combo, half size | (same as above) |
| `fan-reports.webp` | 1280x800 | 44,674 | Fan reports: new fans and renewals over 30 days per creator | Fan reports chart of new fans and renewals |
| `fan-reports-640.webp` | 640x400 | 17,828 | Same, half size | (same as above) |
| `fan-reports-phone.webp` | 390x844 | 17,180 | Phone (390x844 viewport @2x, downsized) | Fan reports chart of new fans and renewals |
| `fan-reports-phone-780.webp` | 780x1688 | 38,008 | Phone, 2x | (same as above) |
| `fan-reports-combo.webp` | 1440x900 | 62,690 | Desktop with the phone shot over its bottom-right | Fan reports chart of new fans and renewals |
| `fan-reports-combo-720.webp` | 720x450 | 24,704 | Combo, half size | (same as above) |
| `vault-pro.webp` | 1280x800 | 86,046 | Vault Pro: folders with counts (Beach day, Gym & fitness, Travel ...) and the media grid | Vault Pro media library with folders and photo thumbnails |
| `vault-pro-640.webp` | 640x400 | 31,928 | Same, half size | (same as above) |
| `vault-pro-phone.webp` | 390x844 | 20,706 | Phone (390x844 viewport @2x, downsized) | Vault Pro media library with folders and photo thumbnails |
| `vault-pro-phone-780.webp` | 780x1688 | 48,910 | Phone, 2x | (same as above) |
| `vault-pro-combo.webp` | 1440x900 | 92,582 | Desktop with the phone shot over its bottom-right | Vault Pro media library with folders and photo thumbnails |
| `vault-pro-combo-720.webp` | 720x450 | 36,474 | Combo, half size | (same as above) |
| `scripts.webp` | 1280x800 | 44,472 | Scripts: script tags and sequences (Holiday special, Gym selfie lead-in, Bundle offer ...) with prices | Scripts library with message sequences and PPV prices |
| `scripts-640.webp` | 640x400 | 17,114 | Same, half size | (same as above) |
| `scripts-phone.webp` | 390x844 | 16,586 | Phone (390x844 viewport @2x, downsized) | Scripts library with message sequences and PPV prices |
| `scripts-phone-780.webp` | 780x1688 | 37,952 | Phone, 2x | (same as above) |
| `scripts-combo.webp` | 1440x900 | 59,110 | Desktop with the phone shot over its bottom-right | Scripts library with message sequences and PPV prices |
| `scripts-combo-720.webp` | 720x450 | 22,936 | Combo, half size | (same as above) |
| `smart-messages.webp` | 1280x800 | 42,762 | Smart Messages: active automated messages (nudge, welcome, purchase follow-up, expiry, birthday) | Smart Messages list of active automated messages |
| `smart-messages-640.webp` | 640x400 | 15,374 | Same, half size | (same as above) |
| `smart-messages-phone.webp` | 390x844 | 17,428 | Phone (390x844 viewport @2x, downsized) | Smart Messages list of active automated messages |
| `smart-messages-phone-780.webp` | 780x1688 | 40,090 | Phone, 2x | (same as above) |
| `smart-messages-combo.webp` | 1440x900 | 58,520 | Desktop with the phone shot over its bottom-right | Smart Messages list of active automated messages |
| `smart-messages-combo-720.webp` | 720x450 | 21,936 | Combo, half size | (same as above) |
| `auto-post.webp` | 1280x800 | 35,650 | Auto Post: five scheduled posts with schedules, next runs and one paused | Auto Post list of scheduled posts with their next run |
| `auto-post-640.webp` | 640x400 | 13,764 | Same, half size | (same as above) |
| `auto-post-phone.webp` | 390x844 | 11,932 | Phone (390x844 viewport @2x, downsized) | Auto Post list of scheduled posts with their next run |
| `auto-post-phone-780.webp` | 780x1688 | 27,032 | Phone, 2x | (same as above) |
| `auto-post-combo.webp` | 1440x900 | 44,800 | Desktop with the phone shot over its bottom-right | Auto Post list of scheduled posts with their next run |
| `auto-post-combo-720.webp` | 720x450 | 17,768 | Combo, half size | (same as above) |
| `auto-follow.webp` | 1280x800 | 48,872 | Auto-follow: total follows per creator, today, yesterday, 7 and 30 days | Auto-follow stats per creator |
| `auto-follow-640.webp` | 640x400 | 18,466 | Same, half size | (same as above) |
| `auto-follow-phone.webp` | 390x844 | 21,202 | Phone (390x844 viewport @2x, downsized) | Auto-follow stats per creator |
| `auto-follow-phone-780.webp` | 780x1688 | 50,252 | Phone, 2x | (same as above) |
| `auto-follow-combo.webp` | 1440x900 | 61,116 | Desktop with the phone shot over its bottom-right | Auto-follow stats per creator |
| `auto-follow-combo-720.webp` | 720x450 | 23,556 | Combo, half size | (same as above) |
| `tracking-links.webp` | 1280x800 | 60,580 | Tracking links: links with clicks, subscribers, conversion and earnings | Tracking links table with clicks, subscribers and earnings |
| `tracking-links-640.webp` | 640x400 | 23,070 | Same, half size | (same as above) |
| `tracking-links-phone.webp` | 390x844 | 23,566 | Phone (390x844 viewport @2x, downsized) | Tracking links table with clicks, subscribers and earnings |
| `tracking-links-phone-780.webp` | 780x1688 | 51,994 | Phone, 2x | (same as above) |
| `tracking-links-combo.webp` | 1440x900 | 82,144 | Desktop with the phone shot over its bottom-right | Tracking links table with clicks, subscribers and earnings |
| `tracking-links-combo-720.webp` | 720x450 | 31,444 | Combo, half size | (same as above) |
| `employees.webp` | 1280x800 | 48,190 | Manage employees for Northstar Studio: 12 people with roles and assigned creators | Manage employees list with roles and assigned creators |
| `employees-640.webp` | 640x400 | 18,082 | Same, half size | (same as above) |
| `employees-phone.webp` | 390x844 | 19,014 | Phone (390x844 viewport @2x, downsized) | Manage employees list with roles and assigned creators |
| `employees-phone-780.webp` | 780x1688 | 42,774 | Phone, 2x | (same as above) |
| `employees-combo.webp` | 1440x900 | 62,836 | Desktop with the phone shot over its bottom-right | Manage employees list with roles and assigned creators |
| `employees-combo-720.webp` | 720x450 | 24,370 | Combo, half size | (same as above) |
| `shifts.webp` | 1280x800 | 74,862 | Shift schedule: a week of chatter shifts per creator | Weekly shift schedule of chatters per creator |
| `shifts-640.webp` | 640x400 | 27,684 | Same, half size | (same as above) |
| `shifts-phone.webp` | 390x844 | 25,596 | Phone (390x844 viewport @2x, downsized) | Weekly shift schedule of chatters per creator |
| `shifts-phone-780.webp` | 780x1688 | 58,430 | Phone, 2x | (same as above) |
| `shifts-combo.webp` | 1440x900 | 92,190 | Desktop with the phone shot over its bottom-right | Weekly shift schedule of chatters per creator |
| `shifts-combo-720.webp` | 720x450 | 34,494 | Combo, half size | (same as above) |
| `roles.webp` | 1280x800 | 39,854 | Role Settings: Owner, Admin, Team Leader, Chatter, Creator, Manager, VA | Role settings listing the team roles |
| `roles-640.webp` | 640x400 | 14,826 | Same, half size | (same as above) |
| `roles-phone.webp` | 390x844 | 14,988 | Phone (390x844 viewport @2x, downsized) | Role settings listing the team roles |
| `roles-phone-780.webp` | 780x1688 | 33,336 | Phone, 2x | (same as above) |
| `roles-combo.webp` | 1440x900 | 45,882 | Desktop with the phone shot over its bottom-right | Role settings listing the team roles |
| `roles-combo-720.webp` | 720x450 | 18,116 | Combo, half size | (same as above) |
| `share-for-share.webp` | 1280x800 | 45,158 | Share for Share, Discover creators: partner creators with daily limits and pitches | Share for Share partner discovery list |
| `share-for-share-640.webp` | 640x400 | 16,930 | Same, half size | (same as above) |
| `share-for-share-phone.webp` | 390x844 | 15,960 | Phone (390x844 viewport @2x, downsized) | Share for Share partner discovery list |
| `share-for-share-phone-780.webp` | 780x1688 | 37,130 | Phone, 2x | (same as above) |
| `share-for-share-combo.webp` | 1440x900 | 56,184 | Desktop with the phone shot over its bottom-right | Share for Share partner discovery list |
| `share-for-share-combo-720.webp` | 720x450 | 21,274 | Combo, half size | (same as above) |
| `of-manager.webp` | 1280x800 | 39,274 | OF Manager home for Ava: compose box, story, and a feed post | OF Manager showing a creator's OnlyFans home feed |
| `of-manager-640.webp` | 640x400 | 15,766 | Same, half size | (same as above) |
| `of-manager-phone.webp` | 390x844 | 16,044 | Phone (390x844 viewport @2x, downsized) | OF Manager showing a creator's OnlyFans home feed |
| `of-manager-phone-780.webp` | 780x1688 | 36,158 | Phone, 2x | (same as above) |
| `of-manager-combo.webp` | 1440x900 | 52,458 | Desktop with the phone shot over its bottom-right | OF Manager showing a creator's OnlyFans home feed |
| `of-manager-combo-720.webp` | 720x450 | 21,528 | Combo, half size | (same as above) |
| `login.webp` | 1280x800 | 28,622 | Sign-in page (dark by design) | Inflowwww sign-in page |
| `login-640.webp` | 640x400 | 10,432 | Same, half size | (same as above) |
| `login-phone.webp` | 390x844 | 25,030 | Phone (390x844 viewport @2x, downsized) | Inflowwww sign-in page |
| `login-phone-780.webp` | 780x1688 | 54,216 | Phone, 2x | (same as above) |
| `login-combo.webp` | 1440x900 | 52,196 | Desktop with the phone shot over its bottom-right | Inflowwww sign-in page |
| `login-combo-720.webp` | 720x450 | 18,684 | Combo, half size | (same as above) |

Use the combo for a hero or feature card, the desktop pair (`srcset` 640w /
1280w) for wide columns, and the phone pair (1x / 2x) for narrow ones.

## Usage

Desktop shot (pick `sizes` to match the layout column):

```html
<img
  src="/img/dashboard.webp"
  srcset="/img/dashboard-640.webp 640w, /img/dashboard.webp 1280w"
  sizes="(min-width: 1280px) 1280px, 100vw"
  width="1280" height="800"
  alt="Inflowwww dashboard with the creator earnings overview"
  loading="lazy" decoding="async">
```

Phone shot (1x / 2x):

```html
<img
  src="/img/messages-pro-thread-phone.webp"
  srcset="/img/messages-pro-thread-phone.webp 1x, /img/messages-pro-thread-phone-780.webp 2x"
  width="390" height="844"
  alt="Messages Pro chat list on a phone"
  loading="lazy" decoding="async">
```

All files are WebP only; every current browser supports it, so no `<picture>`
fallback is needed.
