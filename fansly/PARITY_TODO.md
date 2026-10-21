# Fansly parity — TODO (media bridge)

Queued work, to start **after** the hook-parity workflow (`wt3njp4sb`) lands. That
workflow fills the OF *client-method* hooks (vault/notifications/chat_media/
get_pinned_messages/schedules/... → empty stubs, messaging/fan actions → real).
This file is the **media/image bridge**, which is a separate path (CDN + media
resolution), not a client method — flagged by the user: "no gifs, images don't fill."

## What's confirmed
- Fansly media CDN host: **cdn3.fansly.com** (also `assets.fansly.com`). OF's `/img`
  proxy only allowlists `.ofcdn.com` / `.mycdn.dev` and tunnels the fetch through the
  account's egress IP because OF signs CDN URLs with `AWS:SourceIp`. Fansly signs
  differently — so Fansly URLs are currently **blocked by the proxy allowlist**.
- Message attachments are references, not URLs:
  `{"messageId", "contentType": 1, "contentId": "<accountMedia id>", "pos": 0}`.
  Our `of_message` sets `media: []` and only counts them (`mediaCount`) — so the
  bubble knows media exists but has no URL to render. **This is why images don't fill.**

## Tasks

- [ ] **1. Resolve message media** (`fansly_shim.of_message`)
      Parse the `/message` response's `accountMedia` / `aggregationData` (or a
      `/account/media?ids=` batch) to map each attachment `contentId` → a media object,
      build the `cdn3.fansly.com` variant URLs, and emit OF's `media[]` shape
      (`{id, type, src/full, preview, canView}`). Fill `media`, not just `mediaCount`.

### 1a–1c — what live capture actually shows (verified 2026-08-31, read-only smoke)

Task 1 is **partially** done. `of_media` + the accountMedia lookup exist and are
correct for media **we** uploaded (own-account media carries a full Policy-signed
`locations[0].location`). They are wrong for **fan/creator-owned** media, which is
what the inbox mostly shows. Evidence from the live Bonnie Blue thread (7
accountMedia, all `access=False, purchased=False`):

- [ ] **1a. Never emit `media.location` as a URL.** `_media_full_url`
      ([fansly_shim.py:72](fansly_shim.py#L72)) falls back to `media["location"]`,
      which is a **bare storage path** (`/500365665494917120/852291699018317824.jpeg`)
      — no host, no signature. `/img` rejects it with **400 "bad scheme"**
      ([server.py:3212](../service/server.py#L3212)), so the bubble renders broken.
      6 of 7 live accountMedia hit exactly this path (`locations: []`, every
      variant location `None`). Fix: treat `media.location` as a storage key, not a
      URL — return `None` when no signed `locations[]`/variant URL exists.

- [ ] **1b. Emit `canView`.** All 7 were `access=False` (locked/unpurchased PPV),
      which is *correct* Fansly behaviour, not an error — there is legitimately no
      signed URL to fetch. OF models this with `canView`, and the frontend already
      reads it (`m.canView === false` ⇒ locked badge,
      [PostCard.tsx:62](../app/components/messages/PostCard.tsx#L62)). `of_media`
      never sets it, so locked media is indistinguishable from broken media. Map
      `accountMedia.access` → `canView`, and when a `previewId` + signed variants
      exist (1 of 7 did) use those as the preview so the locked bubble shows a
      blurred still instead of nothing.

- [ ] **1c. Resolve bundle attachments (`contentType: 2`).** The lookup only
      indexes `accountMedia[]`, so an attachment with `contentType: 2` resolves to
      **0 media** while `mediaCount` says 1 (live: contentId `900239700342448129`).
      That id is in the response's **`accountMediaBundles[]`** bucket, whose
      `accountMediaIds[]` / `bundleContent[{accountMediaId,pos}]` expand to the six
      accountMedia ids. Index bundles too and expand them in `pos` order.

> Money stays out of scope: 1b/1c are about *rendering* a locked bundle correctly,
> never about unlocking or purchasing it.

- [ ] **1d. The chat bubble can't act on `canView` (APP-side, not the shim).**
      1a–1c are done and verified — the shim now emits correct media. But the
      fan-facing render is still wrong. `MessageList.tsx:655` computes
      `locked = isPPV && !unlocked && !outgoing`, where
      `isPPV = !!msg.price && msg.price > 0` ([MessageList.tsx:647](../app/components/chat/MessageList.tsx#L647)).
      Fansly locked messages carry **`price: 0`** (live: 3/3, `isOpened: True`,
      6/7 media `url: None`, all `canView: False`), so `isPPV` is false ⇒
      `locked` is false ⇒ the tile falls through to the `if (!thumb)` branch and
      renders a **permanent grey "…" skeleton** instead of the 🔒 lock tile that
      already exists 10 lines above it. Nothing in the chat path reads `canView`
      at all — only `PostCard.tsx:62` does.

      Fix (app-side): make the per-media lock honour `canView`, matching the
      convention PostCard already uses — e.g. in the media map,
      `const mLocked = locked || m.canView === false;` and branch the 🔒
      placeholder on `mLocked` rather than the message-level `locked`. Note
      `locked` is message-level while `canView` is per-media, which is exactly
      why a bundle needs the per-item form.

      **Do not** "fix" this by faking a price on the shim side — price 0 is what
      Fansly actually reports, and inventing one would corrupt the money rail.

- [ ] **1e. `mLocked` needs an outgoing guard (OF-regression risk).**
      §1d landed as `const mLocked = locked || m.canView === false;`
      ([MessageList.tsx:1122](../app/components/chat/MessageList.tsx#L1122)), and the
      comment beside it says *"OF media has no canView, so this is a no-op there."*
      **That is factually wrong.** OF media does carry `canView`:
      [of_shapes.py:94](../service/of_shapes.py#L94) — *"`canView: true` ⇒ preview +
      thumb present; locked ones carry only the .mp4"* — and
      `service/tests/fixtures/of_media_shapes.json:55` is a real OF fixture with
      `"canView": false`.

      Why it matters: the message-level `locked` deliberately EXCLUDES outgoing
      (`locked = isPPV && !unlocked && !(isOutgoing || isOptimisticOutgoing)`,
      line 655) so a chatter can see the PPV they sent. `mLocked` has no such
      guard, so any outgoing OF media reporting `canView:false` would now paint a
      🔒 over the chatter's own sent content — exactly the case line 655 was
      written to protect.

      Not yet observed live (the OF client can't be reached from CLI — proxy 403
      on the CONNECT tunnel — so this is unverified in either direction). `isOutgoing`
      is already in scope: `MediaStrip` takes it as a prop (line 985, used line 1090).
      Cheap, behaviour-preserving fix:
      `const mLocked = locked || (m.canView === false && !isOutgoing);`
      On Fansly this costs nothing (our own media is `canView:true`), and on OF it
      restores exactly the outgoing exemption line 655 intends. Also fix the comment.

- [ ] **1f. GIF send: match the capture, then send one for real.**
      Our body adds `scheduledFor: 0`; the captured gif send omits it (Fansly's
      client sends it on TEXT sends but not the gif one — checked across all 4
      captured `POST /message` bodies). Likely benign, but the method here is
      capture-don't-guess. Either drop the field when `giphy_id` is set, or send one
      real GIF and confirm delivery — then the row can go ✅.

- [ ] **2. Avatars** (`fansly_shim.of_user` / `_avatar_url`)
      Confirm the Fansly avatar (nested media `locations`/`variants`) resolves to a real
      `cdn3.fansly.com` URL for every account object the inbox gets (some come from
      `/messaging/groups aggregationData`, which may omit the full avatar → may need a
      `/account?ids=` enrich).

- [ ] **3. `/img` proxy — Fansly path** (`service/server.py` img proxy)
      Add `cdn3.fansly.com` / `assets.fansly.com` / `*.fansly.com` to the CDN allowlist,
      and give Fansly a distinct fetch path: Fansly CDN URLs are **not** AWS-SourceIp
      signed, so they should NOT need the egress tunnel (verify: public vs. token-signed;
      may need the `authorization` header instead). Keep the OF path untouched.

- [ ] **4. Real GIFs (KLIPY)** — replace the empty `gif_trending`/`gif_search` stubs
      Fansly's composer uses **KLIPY**, not Giphy. Wire `gif_search`/`gif_trending` to
      KLIPY (find the endpoint + key from the Fansly bundle/HAR), returning OF's
      `{data: [GiphyItem], pagination}` shape. Then wire GIF **send** (Fansly sends a GIF
      as an attachment/embed, not OF's top-level `giphyId`) — currently rejected in
      `FanslyShimClient.send_message`.

- [ ] **5. Media send (images/video)** — currently rejected in `send_message`
      Upload to Fansly media → get a `contentId` → attach on `POST /message`. Mirror the
      OF `media_files` → attachment flow.

## "Full copy new bridge"
Consider a dedicated `fansly/fansly_media.py` module (parallel to `fansly_shim.py`) that
owns media resolution + CDN URL building + KLIPY, so the shim stays messaging-focused and
the `/img` proxy has one clear Fansly entry point. Mirror the OF media flow file-for-file.

## Notes
- Money-moving stays out of scope (tips/PPV/paid unlocks) unless explicitly requested.
- Everything additive — the OnlyFans path must stay untouched (platform defaults to `onlyfans`).
