# Product shots

Web-ready WebP versions of the real app screenshots in `docs/screenshots/`.
Encoded with `cwebp -q 80 -m 6 -sharp_yuv`, resized with
ImageMagick Lanczos. All shots use the dark theme and a disconnected demo
account, so revenue figures read `$0.00`.

## Files

| File | Pixels | Bytes | Shows | Source | Suggested alt |
|---|---|---|---|---|---|
| `app-dashboard.webp` | 1280x800 | 32,050 | Dashboard: 30-day revenue chart, Creator Reports earnings summary (subscriptions, posts, messages, tips, referrals, streams), Analytics menu open | `app-dashboard.png` | Inflowwww dashboard with the revenue chart and earnings summary |
| `app-dashboard-640.webp` | 640x400 | 12,182 | Same, half size | `app-dashboard.png` | (same as above) |
| `app-auto-post.webp` | 1280x800 | 23,538 | My Automations > Auto Post: saved auto posts card, "+ New auto post", empty state | `app-auto-post.png` | Auto Post screen for scheduling recurring posts |
| `app-auto-post-640.webp` | 640x400 | 9,154 | Same, half size | `app-auto-post.png` | (same as above) |
| `desktop-shell.webp` | 1280x800 | 15,648 | Desktop app shell (1440x900 @2x source) on Messages Pro, Creators and Employees in the sidebar | `desktop-shell.png` (2880x1800) | Inflowwww desktop app showing the Messages Pro inbox |
| `desktop-shell-640.webp` | 640x400 | 5,744 | Same, half size | `desktop-shell.png` | (same as above) |
| `phone-dashboard.webp` | 390x844 | 15,166 | Phone dashboard: revenue card, 7d/30d/90d toggle, Creator Reports filters, earnings summary | `phone-dashboard.png` | Inflowwww dashboard on a phone |
| `phone-dashboard-780.webp` | 780x1688 | 34,366 | Same, 2x | `phone-dashboard.png` | (same as above) |
| `phone-messages-pro-list.webp` | 390x844 | 12,814 | Phone Messages Pro chat list: 5 demo fan chats with unread badges and creator tags | `phone-messages-pro-list.png` | Messages Pro chat list on a phone |
| `phone-messages-pro-list-780.webp` | 780x1688 | 28,722 | Same, 2x | `phone-messages-pro-list.png` | (same as above) |

## Privacy check

No real usernames, emails, tokens or earnings are visible. The phone Messages
Pro shots show fan names (Jake M., Marcus, Ryan, Danny K, Tom, handle
`@jakem`) and creator "Luna": these are demo data (the desktop Messages Pro
shots from the same app build show an empty inbox, and "Luna" is the
placeholder creator used across the tests), so nothing was blurred.

Edited: `desktop-shell.webp` had the Next.js dev-mode "N" badge over the
sidebar's version label; it was painted out and "Version 0.1.0" restored from
`app-messages-pro.png`. The source PNG is unchanged.

## Usage

Desktop shot (pick `sizes` to match the layout column):

```html
<img
  src="/img/app-dashboard.webp"
  srcset="/img/app-dashboard-640.webp 640w, /img/app-dashboard.webp 1280w"
  sizes="(min-width: 1280px) 1280px, 100vw"
  width="1280" height="800"
  alt="Inflowwww dashboard with the revenue chart and earnings summary"
  loading="lazy" decoding="async">
```

Phone shot (1x / 2x):

```html
<img
  src="/img/phone-messages-pro-list.webp"
  srcset="/img/phone-messages-pro-list.webp 1x, /img/phone-messages-pro-list-780.webp 2x"
  width="390" height="844"
  alt="Messages Pro chat list on a phone"
  loading="lazy" decoding="async">
```

All files are WebP only; every current browser supports it, so no `<picture>`
fallback is needed.
