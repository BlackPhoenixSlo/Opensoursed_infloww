---
title: "Vault Pro bulk actions: one import for the whole batch, at $0 per creator"
description: "A bulk workflow for Inflowwww's Vault Pro: prepare files, import a batch from disk or Google Drive, sort, label and dedupe it."
date: 2026-10-12
tags: ["product", "vault-pro", "workflow"]
parodyOf: "vault-pro-bulk"
parodyTitle: "Vault Pro: Save time with bulk actions"
parodyDate: "Dec 20, 2024"
image: "vault-pro-combo.webp"
imageAlt: "Vault Pro on desktop and phone: a grid of media thumbnails sorted into folders"
---

Putting files into an OnlyFans vault one at a time is slow, and doing it for several creators is a part-time job. Vault Pro (**Growth > Vault Pro**, the owner's screen) handles the batch work. This is a step-by-step workflow for a typical shoot of 50 to 200 files.

## Before you import: prepare the batch

Ten minutes of preparation saves an hour of fixing.

1. **One shoot, one folder** on your disk or in Google Drive. Split by theme if a shoot has several.
2. **Remove what you will not use.** Every file you import costs time, because OnlyFans throttles writes.
3. **Name files meaningfully** if you can (`june-beach-01.jpg`), so you can tell them apart in the vault.
4. **Keep the originals.** The vault is a working copy, not your archive.

For Google Drive, make each folder viewable by link. Vault Pro takes public folder links.

## Step 1: import everything at once

{% shot "vault-pro.webp", "Vault Pro with a grid of media thumbnails and a folder list", "A vault after a few bulk imports. Demo data." %}

1. Open **Growth > Vault Pro** and check the model name in the header. It is the vault you are about to fill.
2. In the import card, drop the files, or paste the Drive folder links, one per line.
3. Choose a target folder, or leave it in the vault with no folder.
4. Start the import.

Expect about three new files a minute. OnlyFans has no direct vault upload, so each new file is attached to a far-future scheduled post and the post is deleted once the vault id is known. Nothing is published. Large videos are re-encoded first, which adds time.

The import runs on the server, so you can close the tab. Files already in the vault are skipped quickly, which makes re-running a half-finished batch cheap.

## Step 2: sort into folders in bulk

When the import is done:

1. Select the media that belong together.
2. Use **Put into folder**, or make a new folder from the selection.
3. Rename folders so a chatter knows what is inside without opening them.
4. Drag folders into order, most-used first.

Work by selection, not file by file. Selecting 40 images and moving them once is the whole point.

## Step 3: label what chatters will search for

Each item has **tags**, a **description** and a **caption**. You do not need to label every photo in a set the same depth:

- **Tag every item** with the set name and two or three content tags from your agreed list.
- **Describe the hero items** in detail: the ones most likely to be sent as a preview or sold alone.
- **Caption the items you will send first**, in the creator's voice.

Write the tag list down once and share it. Consistent tags are what make search work at 2,000 items.

## Step 4: remove duplicates

Imports from several sources leave copies. Open **Duplicate media**, choose a match strictness, and review what it finds. Keep the copy that has your labels and folders. Nothing is removed until you confirm, and OnlyFans has no undo, so check each group.

Run it after every large import and once a month.

## Step 5: hand it to the team

Chatters do not open Vault Pro; they attach media from the composer in Messages Pro. Two things make that smooth:

- Use **Access limits** in **Employees > Manage employees** to set which folders each chatter may use, for example to hold back a set until launch.
- Post the week's new folder names in the team chat.

**A weekly rhythm**

| Day | Task |
|---|---|
| Shoot day | Prepare the batch |
| Next morning | Import, sort, label |
| Launch day | Open the folder to chatters |
| End of month | Duplicate cleanup, archive old folders |

> **The pitch.** Bulk import, bulk sort and duplicate cleanup for every creator, on your own server. The one thing it cannot do in bulk is invoice you. [Deploy it yourself]({{ '/#deploy' | url }}).
