---
title: "What permissions should you set for chatters? Two roles, no role editor"
description: "Inflowwww has two kinds of session, owner and chatter. What each one sees, how to limit models and vault folders, and how to check a chatter's view yourself."
date: 2026-10-12
tags: ["product", "team-access", "permissions"]
parodyOf: "infloww-role-permissions"
parodyTitle: "What permissions should you set for Infloww assistants?"
parodyDate: "Jul 20, 2024"
image: "roles-combo.webp"
imageAlt: "Roles and permissions on desktop and phone: a matrix of roles and what each can open"
---

Chatters need the inbox and the tools that help them reply. They rarely need to manage creators or rebuild the vault. Inflowwww keeps this simple: there are two kinds of session, owner and chatter, plus per-chatter limits.

## The two sessions

{% shot "roles.webp", "Roles and permissions matrix", "The roles and permissions screen. Demo data." %}

Login is a share token for the dashboard plus per-user logins for the owner and each chatter (`/chatter-login`). The [Help center]({{ '/help/#first-login' | url }}) walks through the first login.

**Owner.** The agency owner signs in with the owner login and sees every screen.

**Chatter.** A chatter logs in at `/chatter-login` with the username and password they chose from an invite link. Their sidebar leaves out every item marked owner-only, Vault Pro included; in a chat they still attach media from the composer, limited to the vault folders the owner grants them. On the relay, a fixed list of owner-only admin endpoints (proxies, sessions, chatter management and a few more) is blocked for chatter sessions; other endpoints are limited to the accounts the chatter is assigned. That is narrower than "everything owner-only is locked", which is why step 3 below matters.

There are no custom roles, no role editor and no data permission levels in between. If you need a team lead who sees more than a chatter but less than the owner, we do not have that today.

## What a chatter does not see

These sidebar items are hidden from chatter sessions:

- **Growth**: Smart lists, Auto-follow, Vault Pro, Profile promotion, Free trial links, Tracking links.
- **My Automations**: Auto Post and Auto Story.
- **Creators**: Manage creators and Custom proxy.
- **Employees**: Manage employees and Shift schedule (NotBuiltYet).

What remains is the working set: the Dashboard, Messages Pro, Smart Messages, Scripts, the Analytics section and Settings. Several of these, like the Settings tabs, are NotBuiltYet pages: the page is real, the feature is not.

Hiding a menu item is not the same as hiding data. Before you invite the team, check what the remaining screens show to a chatter (step 3 below) and decide whether that is acceptable for your agency.

## Limit models and folders per chatter

In **Employees > Manage employees**, each linked chatter has **Access limits**:

- **Limit which models this chatter sees.** On: they only see the creators you tick. Off: they see all of your models. To remove someone completely, **Unlink** them instead of ticking nothing.
- **Folder limits (per model).** Pick which vault folders they may use for each creator. Useful for keeping a launch set out of circulation until its date.

Set limits the day you invite someone, not after the first mistake.

## Recommended setup

| Person | Session | Limits |
|---|---|---|
| Agency owner | Owner | None |
| Full-time chatter | Chatter | Only their creators |
| Trial or part-time chatter | Chatter | One creator, a few vault folders |
| Contractor for one launch | Chatter | One creator, launch folder only; unlink after |

Keep owner access to one or two people. Anyone with it can manage creators, sessions and the team, and while sign-up is open (see [Known gaps]({{ '/roadmap/#known-gaps' | url }}) on the roadmap) anyone who reaches the server can register an account too. Before you give the team the server's address, read the [security notes]({{ '/help/#security' | url }}).

## Check a chatter's view yourself

1. Invite a test chatter from **Manage employees**.
2. Set the same limits you plan to give a real chatter.
3. Open the invite in a private browser window and log in as that test chatter.
4. Walk the sidebar: open Messages Pro, Scripts, Smart Messages and each Analytics page.
5. Note anything you would rather they did not see, and adjust limits or who you invite.
6. Unlink the test chatter.

Ten minutes of this beats a policy document nobody reads.

## Review regularly

Once a month, open **Manage employees** and read the list. Unlink anyone who no longer works with you, and narrow model limits for anyone who moved accounts. Access that outlives the job is the most common gap in any team setup.

> **The pitch.** Two roles, every creator, one price: $0. [Deploy it yourself]({{ '/#deploy' | url }}).
