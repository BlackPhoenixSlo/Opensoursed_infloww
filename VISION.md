# Vision

This repository is an open-source reimplementation of Infloww, the OnlyFans
creator-agency tool.

## Scope

Fully re-implement the Infloww UI as it exists today, on all three surfaces:

- Web app
- Phone app
- Desktop app

## Out of scope

The "My Automations" section is skipped, except for three small automations
that are in scope:

- Auto-post
- Auto-story
- Auto-reply (our addition: Infloww has no counterpart). It sends one AI reply
  to a fan nobody answered within the set delay. It only replies to the fans
  in the picked folders and/or new fans. It never sells; it replaces the
  legacy AI Chatter selling engine, which was removed.

## Next step

1. Inventory every Infloww screen (web, phone, desktop).
2. Build the UI phase by phase from that inventory, on top of the existing
   relay and app.
