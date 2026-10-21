# Product shots

Web-ready WebP screenshots of the real app, captured 2026-10-21 with headless
Chromium (Playwright, device scale 2) from a production build (`next build` +
`next start`) of the deployed public repo, against a fresh relay with an empty
database and one newly registered owner ("studio"), no creator connected. So
every figure reads `$0.00`, the free-trial banner shows, and Messages Pro has
no chats (its list shows the loading rows). Encoded with
`cwebp -q 80 -m 6 -sharp_yuv`, resized with ImageMagick Lanczos. The PNGs in
`docs/screenshots/` are the older captures and are not the source of these.

## Files

| File | Pixels | Bytes | Shows | Capture | Suggested alt |
|---|---|---|---|---|---|
| `app-dashboard.webp` | 1280x800 | 36,190 | Dashboard: period tabs, Creator earnings overview (subscriptions, posts, messages, tips, referrals, streams), My shifts, clocked-in employees | 1280x800 viewport @2x | Inflowwww dashboard with the creator earnings overview |
| `app-dashboard-640.webp` | 640x400 | 14,380 | Same, half size | same | (same as above) |
| `app-auto-post.webp` | 1280x800 | 21,820 | My Automations > Auto Post: "No creators" picker, "+ New auto post", "No creator with a live session" | 1280x800 viewport @2x | Auto Post screen with a New auto post button |
| `app-auto-post-640.webp` | 640x400 | 8,452 | Same, half size | same | (same as above) |
| `desktop-shell.webp` | 1280x800 | 13,476 | Messages Pro window: All Models, Add a Creator, Online Fans / Notifications, empty conversation pane | 1440x900 viewport @2x | Inflowwww desktop app showing the Messages Pro inbox |
| `desktop-shell-640.webp` | 640x400 | 5,420 | Same, half size | same | (same as above) |
| `phone-dashboard.webp` | 390x844 | 15,074 | Phone dashboard: free-trial banner, period tabs, Creator earnings overview | 390x844 viewport @2x | Inflowwww dashboard on a phone |
| `phone-dashboard-780.webp` | 780x1688 | 34,642 | Same, 2x | same | (same as above) |
| `phone-messages-pro-list.webp` | 390x844 | 7,784 | Phone Messages Pro chat list, no chats yet | 390x844 viewport @2x | Messages Pro chat list on a phone |
| `phone-messages-pro-list-780.webp` | 780x1688 | 16,372 | Same, 2x | same | (same as above) |

## Privacy check

A fresh install: no creator, fan, email, token or earnings data exists to show.

## Usage

Desktop shot (pick `sizes` to match the layout column):

```html
<img
  src="/img/app-dashboard.webp"
  srcset="/img/app-dashboard-640.webp 640w, /img/app-dashboard.webp 1280w"
  sizes="(min-width: 1280px) 1280px, 100vw"
  width="1280" height="800"
  alt="Inflowwww dashboard with the creator earnings overview"
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
