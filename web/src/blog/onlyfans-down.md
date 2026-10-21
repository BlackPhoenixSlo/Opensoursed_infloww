---
title: "Is OnlyFans down? How to tell whether it is the platform or your server"
description: "How to tell whether OnlyFans is down or the fault is your connection or server, and how to keep fans informed until it is back."
date: 2026-10-12
tags: ["creator-life", "troubleshooting", "self-hosting"]
straight: true
parodyOf: "onlyfans-down"
parodyTitle: "What happens when OnlyFans is down?"
parodyDate: "Sep 20, 2024"
---
When OnlyFans goes down, nobody can post, message or buy until it's back, and there is little you can do but wait. When it's your connection or your own server, there is plenty you can do. So the first job is always the same: work out which one it is.

## Step 1: is it OnlyFans or everyone?

Symptoms of a platform problem include internal error messages, a page that keeps reloading, media that won't load, or only the chat failing while the rest works.

Check in this order:

1. **The official status sources.** Look for an OnlyFans status page or announcements on OnlyFans' official social accounts.
2. **An independent checker.** Sites that test whether a website is down for everyone, or that collect user outage reports, will usually show a spike within minutes.
3. **A second device on a different network.** Try your phone on mobile data. If it fails there too, it's almost certainly the platform.

If it's the platform, stop troubleshooting. Nothing on your side will fix it, and repeated logins won't help.

## Step 2: if it's just you

If other people can reach the site and you can't, work through the basics:

- **Restart your connection.** Router, Wi-Fi, then the device.
- **Hard refresh** the page, then try a private browser window.
- **Clear cache and cookies** for the site.
- **Disable extensions** one at a time, including ad blockers, to see if one is interfering.
- **Try another browser.** If it works there, the problem is local to the first one.
- **Check your account notifications** once you're back in, in case the issue was specific to your account rather than technical.

## Step 3: if you self-host Inflowwww

Self-hosting means one extra place where things can break, and one extra place you can fix them. If OnlyFans works in your browser but the dashboard doesn't:

1. **Check the containers.** On the server, run `docker compose ps`. You should see `openinflowwww-relay`, `openinflowwww-app` and `openinflowwww-autoheal` running. The healthchecks show whether each service is healthy.
2. **Read the logs.** `docker compose logs --tail=100 openinflowwww-relay` (or `openinflowwww-app`) usually shows the error directly.
3. **Let autoheal work, or restart.** An autoheal container restarts unhealthy services. If something is stuck anyway, `docker compose restart <service>` is the next step.
4. **Check the server itself.** Full disks and exhausted memory cause most self-hosting outages. Check free space and memory, and your hosting provider's status page.
5. **Isolate one account.** If every account fails, look at the server. If only one creator's account fails, its captured session may need capturing again with the login extension.
6. **If you use the quick tunnel**, remember its `trycloudflare.com` URL changes on every restart. An old bookmark will stop working.

If OnlyFans itself is down, the dashboard can't reach it either. Wait for the platform.

## What an outage costs, and how to limit it

An outage stops tips, pay-per-view sales, new subscriptions and messages, and any scheduled live stream. Fans may get frustrated even though it's nobody's fault on your side.

Damage control:

- **Tell fans on your other channels.** A short, calm post ("OnlyFans is having issues; I'll be back as soon as it is") prevents a pile of confused messages later.
- **Reschedule rather than cancel.** Move a live stream to a new time and announce it once the platform is stable.
- **Follow up once it's back.** A quick message to fans who were mid-conversation or mid-purchase shows you noticed.
- **Use the downtime.** Shoot, edit, plan next month's calendar or write scripts for later.

## Plan before the next one

- Keep at least one promotion channel where you can reach fans, within the platform's rules on promotion.
- Keep a short outage announcement saved as a draft.
- Hold a cash buffer, so a lost day of sales doesn't become a problem.
- If you self-host, write down your server's restart steps somewhere you can find them on a bad day.

> **The pitch.** When something breaks, Inflowwww's logs are on your own server to read; it is a free, open-source CRM. [Deploy it yourself]({{ '/#deploy' | url }}).
