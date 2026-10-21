---
title: "Passwordless account sharing: your chatters never see the creator's password"
description: "How Inflowwww lets a team work an OnlyFans account through a captured session, so chatters never see the creator's password."
date: 2026-10-12
tags: ["product", "team-access", "account-sharing"]
parodyOf: "infloww-passwordless-account-sharing"
parodyTitle: "Passwordless account sharing: secure team access in Infloww"
parodyDate: "Feb 20, 2025"
---

Sending a creator's password to every new chatter is the habit most agencies want to break. In Inflowwww the password is entered once, by whoever captures the session, and the team works through the app instead.

## How it works

Inflowwww does not store an OnlyFans password. It holds a captured web session:

1. Someone logs in to OnlyFans through the capture extension in `loginExtensionMulti/`.
2. They open a chat, click **Copy cURL**, and paste it into **Creators > Manage creators**.
3. The relay keeps that session on your server and signs each OnlyFans request with it.

Chatters then log in to Inflowwww, not to OnlyFans. Login is a share token for the dashboard plus per-user logins for the owner and each chatter (`/chatter-login`). They see Messages Pro, Scripts and the other screens they are allowed, and never the login that produced the session.

Ideally the creator does the capture on their own device, so the password never leaves their hands at all.

## Invite a chatter

1. Open **Employees > Manage employees** (owner only).
2. Add the person to the roster with a display name.
3. In the Chatters tab, under **Invite a new chatter**, click **Mint invite URL** to create a one-time invite link, valid for 24 hours, and send it to them.
4. They open it and choose their own username and password.

Each person gets their own login, so every message in the reports has a name on it. Never share one chatter login between two people; you lose the attribution and the ability to remove one of them.

## Limit what each chatter sees

Two controls under **Access limits**:

- **Limit which models this chatter sees.** Turn it on and tick only the creators they work on. Off means they see all of your models.
- **Folder limits (per model).** Restrict which vault folders they can use, for example to keep unreleased sets out of reach until launch day.

Owner screens (Creators, Employees, Vault Pro, Smart lists, Auto-follow, the link tools and My Automations) are hidden from chatter sessions, though chatters attach media from the chat composer, limited to the vault folders the owner grants them. On the relay, a fixed list of owner-only admin endpoints, such as proxies, sessions and chatter management, is blocked for chatter sessions; other endpoints are limited to the accounts the chatter is assigned. Hidden is not the same as locked, so check what a chatter login can reach before you rely on it.

## When someone leaves

1. **Unlink** the chatter in **Manage employees** the same day. That unlinks their chatter login from you, so it no longer reaches your creators. While sign-up is open (see [Known gaps]({{ '/roadmap/#known-gaps' | url }}) on the roadmap) anyone who reaches the server can register again, so keep the server on a VPN.
2. If you think the session itself may have been copied, have the creator sign out of other sessions in their OnlyFans settings, change the password, and capture a fresh session.
3. Review the **Message dashboard** for the person's last week, filtered by their name.

Write this down as a checklist before you need it. Offboarding goes wrong when it is improvised.

## Treat the session like a key

A captured session can act as the account, so handle it that way:

- Run Inflowwww on a server only you control, on a private network or a VPN, and keep the `.env` secrets private. The [security notes]({{ '/help/#security' | url }}) explain why.
- Set your own `SHARE_TOKEN`; without one, the share-link gate is off and sign-in is the only gate.
- Give owner access to as few people as possible.
- Recapture sessions when they expire rather than passing cURL strings around in chat.

Sessions and the database live on your server. That makes you responsible for the server, which is the point.

## Next steps

1. Capture one creator's session, ideally on the creator's device.
2. Invite one chatter and set a model limit.
3. Log in as that chatter in a private window and check what they can see.
4. Write your offboarding checklist.

> **The pitch.** Manage employees lives at `/employees` on your own server, for every chatter you add, and none of them ever needs the creator's password. [Deploy it yourself]({{ '/#deploy' | url }}).
