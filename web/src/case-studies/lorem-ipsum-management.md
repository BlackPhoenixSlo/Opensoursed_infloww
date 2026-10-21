---
title: "How Lorem Ipsum Management backs up its whole CRM every night, and checks the backup works"
description: "A fictional agency backs up its self-hosted Inflowwww every night, keeps a copy off the server and tests a restore monthly."
date: 2026-10-12
agency: "Lorem Ipsum Management"
tagline: "One SQLite file, a nightly copy, and a monthly restore test, all for the price of the disk it sits on."
stats:
  - value: "$0"
    label: "Per creator per month x 22 creators = $0"
  - value: "7 + 4"
    label: "Daily and weekly backups kept"
  - value: "1"
    label: "Restore test per month, on a scratch copy"
  - value: "1"
    label: "Command to install, after the README's other seven"
quote: "When we self-hosted, the backups became our job. So we made them a scheduled job."
quoteBy: "Tomas, technical manager, Lorem Ipsum Management"
---

Lorem Ipsum Management backs up Inflowwww every night by copying the SQLite database out of the running relay, archiving the session and config files beside it, and keeping a copy on a second machine. Once a month it restores a backup to a scratch folder to prove it works. The backup, test and restore commands are in [Help > Backups](/help/#backups).

## About

Lorem Ipsum Management is a fictional agency with 22 creators on OnlyFans. It runs Inflowwww with Docker Compose on one VPS. One technical manager looks after the server for a few hours a month.

## Challenge

Self-hosting means the data lives on your server, so nobody else is backing it up. The agency's first backup plan was "the VPS provider probably has snapshots". When they checked, snapshots were an add-on they had never turned on.

## Solution

Back up the files that the stack keeps on the host, next to the compose file. The `service/` ones are bind-mounted into the relay; `.env` is read by Compose:

- `service/chatterly.db`: the SQLite store.
- `service/sessions/`: the captured sessions.
- `service/proxies.json`: the proxy registry.
- `service/secrets/`: the server keys and the admin password.
- `.env`: the share token and the session secrets.

Back up the vault image folders too (`service/vault_thumbs/`, `vault_posters/`, `vault_images/`): once OnlyFans' signed URLs expire, those images can't be downloaded again.

## Strategy

The database, the sessions folder, `proxies.json` and `.env` are all as sensitive as passwords: `chatterly.db` and `proxies.json` hold passwords in plain text. The agency encrypts each archive before it leaves the server (with `age` or `gpg`) and keeps the key somewhere other than the backup. A backup that anyone can read is just a second copy of the risk.

They keep seven daily and four weekly copies, and they copy every night's files to a second machine. Your data stays on your server, and a copy of it stays on a second one.

## Operations

An entry in root's crontab changes into the install folder (`cd /path/to/openinflowwww`) and runs the backup commands at 04:00, then copies the results off the server and deletes local copies older than seven days. The technical manager gets an email only if the job fails.

On the first Monday of the month, they test a restore on a scratch copy.

## Results

- Every night has a backup, and every month has proof that one restores.
- The restore steps are written down, so anyone with server access can do it.
- The agency knows exactly which files its CRM is, which is useful for moving servers too.

None of this makes money. It makes sure a bad disk costs you an evening, not your history.
