---
title: "Vault Pro: the key to saving hours on content management, released under MIT"
description: "Release notes for Inflowwww's Vault Pro: what it does, how imports reach the OnlyFans vault, its speed limits and a good setup."
date: 2026-10-12
tags: ["product", "vault-pro", "release-notes"]
parodyOf: "news-vault-pro"
parodyTitle: "Vault Pro: The key to saving hours on content management"
parodyDate: "Jun 17, 2024"
image: "vault-pro-combo.webp"
imageAlt: "Vault Pro on desktop and phone: a grid of media thumbnails sorted into folders"
---

Vault Pro is Inflowwww's content manager, at **Growth > Vault Pro** (`/growth/vault-pro`). It replaces the old `/vault` page, which now redirects there. The owner manages it; chatters attach its media from the chat composer. These are the notes on what it does and how to get the most from it.

## What's in it

{% shot "vault-pro.webp", "Vault Pro with a grid of media thumbnails and a folder list", "Vault Pro with folders and media. Demo data." %}

- **Browse** a model's whole vault, filtered by folder or media type, sorted newest or oldest.
- **Search** across the vault.
- **Import** new media by dropping files or pasting public Google Drive folder links, one per line, straight into the OnlyFans vault and, if you choose, into a folder.
- **Label** each item with tags, a full description and a one-line caption.
- **Organize** folders: create one from a selection, rename, delete, put media into a folder, and drag folders into a custom order.
- **Clean up** re-uploaded copies with **Duplicate media**, at a match strictness you choose, with a review step before anything is removed.

The header always names the model whose vault you are working in. With several creators, check it before every import.

## How importing works

OnlyFans has no direct "save to vault" call, so Vault Pro works around it. For each new file, the relay:

1. Re-encodes large videos first, since OnlyFans rejects very large objects.
2. Attaches the file to a scheduled post set far in the future.
3. Reads the vault id from that post.
4. Deletes the post.

Nothing is published and no fan sees anything, but real objects are created and deleted, and the import screen says so.

## Known limits

- **Speed.** OnlyFans throttles writes, and each new file costs two of them. Expect about three new files a minute, however small the files are.
- **Re-runs are quick.** Files already in the vault skip the post step, so re-importing a folder finishes in seconds.
- **No undo.** OnlyFans offers no undo for removals. The duplicate cleaner makes you review and confirm first; take that step seriously.
- **Owner manages, chatters attach.** Chatters do not see the Vault Pro page. They attach media from the composer, and you can limit which folders each chatter may use.

The import runs on the server and is tracked there. A page reload, a second tab or a closed laptop does not lose it.

## How to save the hours

The time saving comes from the labels, not the upload. A setup that works:

1. **One folder per purpose.** "New this week", "Teasers", one per paid set, "Customs delivered", "Archive".
2. **A fixed tag list.** Twenty tags, written down, used by everyone. Free-form tags drift.
3. **Descriptions for chatters.** What is in it, how long it is, anything the creator wants said or avoided.
4. **Captions you would send.** One line, in the creator's voice.
5. **A weekly tidy.** Move last week's items down, run **Duplicate media** after big imports.

A chatter who can find the right file by searching a tag stays in the conversation instead of scrolling.

## Upgrading

If you used the old `/vault` page, nothing moves: Vault Pro reads the same vault. Pull the latest code and rebuild:

```bash
git pull
docker compose up -d --build
```

Bookmarks to `/vault` redirect automatically.

## Next steps

1. Open **Growth > Vault Pro** and check the model in the header.
2. Import one shoot into a new folder.
3. Tag, describe and caption it.
4. Ask a chatter to find it from Messages Pro.

> **The pitch.** Vault Pro ships to every creator on your roster, on your own server, at $0 per creator. [Deploy it yourself]({{ '/#deploy' | url }}).
