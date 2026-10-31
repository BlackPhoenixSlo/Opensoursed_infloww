import { describe, expect, it } from "vitest";

import type { FanVaultEntry } from "@/hooks/useFanVaultHistory";
import type { VaultMedia } from "@/lib/relay";
import {
  describeTile, pillText, resolveStatus, type TileStatus,
} from "./vaultTileStatus";

const entry = (p: Partial<FanVaultEntry> = {}): FanVaultEntry => ({
  send_count: 1, last_sent_at: null, last_price_cents: 0, was_purchased: false,
  last_purchase_at: null, total_paid_cents: 0, ...p,
});
const m = { id: 42, type: "video" } as VaultMedia;

const UNLOCKED = entry({ was_purchased: true, last_price_cents: 699, total_paid_cents: 1500 });
const LOCKED = entry({ last_price_cents: 1250, send_count: 2 });
const FREE = entry({ send_count: 3 });

describe("resolveStatus", () => {
  it.each<[string, FanVaultEntry | undefined, boolean, string | null]>([
    ["unlocked beats everything", UNLOCKED, true, "unlocked"],
    ["sent paid, not bought → locked", LOCKED, true, "locked"],
    ["sent free", FREE, false, "free"],
    ["wall only", undefined, true, "on-wall"],
    ["nothing", undefined, false, null],
  ])("%s", (_n, e, onWall, want) => expect(resolveStatus(e, onWall)).toBe(want));
});

describe("describeTile", () => {
  it.each<[string, FanVaultEntry, boolean, string]>([
    ["unlocked with total paid", UNLOCKED, false, "video · 42 · UNLOCKED (fan paid) ($15)"],
    ["unlocked, nothing paid recorded, on wall", entry({ was_purchased: true }), true, "video · 42 · UNLOCKED (fan paid) · also on wall"],
    ["locked", LOCKED, false, "video · 42 · locked · sent at $12.50 (2×)"],
    ["free on wall", FREE, true, "video · 42 · sent free (3×) · also on wall"],
  ])("%s", (_n, e, onWall, want) => expect(describeTile(m, e, onWall)).toBe(want));
});

describe("pillText", () => {
  it.each<[string, TileStatus, FanVaultEntry | undefined, number, string]>([
    ["locked cents", "locked", LOCKED, 0, "$12.50"],
    ["locked whole dollars", "locked", entry({ last_price_cents: 500 }), 0, "$5"],
    ["locked, no price recorded", "locked", entry(), 0, "PPV"],
    ["unlocked: last send price, not total", "unlocked", UNLOCKED, 0, "$6.99"],
    ["unlocked, no price recorded", "unlocked", entry({ was_purchased: true }), 0, "PAID"],
    ["free (wall price ignored)", "free", FREE, 699, "FREE"],
    ["paid wall post", "on-wall", undefined, 699, "WALL $6.99"],
    ["free wall post", "on-wall", undefined, 0, "WALL"],
  ])("%s", (_n, status, e, wallCents, want) => expect(pillText(status, e, wallCents)).toBe(want));
});
