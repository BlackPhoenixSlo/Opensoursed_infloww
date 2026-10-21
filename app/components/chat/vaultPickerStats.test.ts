import { describe, expect, it } from "vitest";

import type { VaultMediaStat } from "@/hooks/useVaultMediaStats";

import { isStatsSort, seenByFan, sortByStats, statsLabel } from "./vaultPickerStats";

const st = (sent: number, unlocks: number, rate: number | null, last: string | null): VaultMediaStat =>
  ({ sent, priced: sent, unlocks, unlock_rate: rate, last_sent_at: last });

const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }];
const ids = (xs: Array<{ id: number }>) => xs.map((x) => x.id);
const byMedia = {
  "2": st(10, 1, 0.1, "2026-10-01T00:00:00"),
  "3": st(4, 3, 0.75, "2026-10-05T00:00:00"),
  "4": st(10, 2, 0.2, null),
};

describe("sortByStats", () => {
  it("ranks by the chosen stat, best first, never-sent media last in served order", () => {
    expect(ids(sortByStats(items, byMedia, "sent"))).toEqual([4, 2, 3, 1]);
    expect(ids(sortByStats(items, byMedia, "unlocks"))).toEqual([3, 4, 2, 1]);
    expect(ids(sortByStats(items, byMedia, "unlock_rate"))).toEqual([3, 4, 2, 1]);
    expect(ids(sortByStats(items, byMedia, "recent"))).toEqual([3, 2, 4, 1]);
  });

  it("keeps the served order when nothing has stats", () => {
    expect(ids(sortByStats(items, {}, "sent"))).toEqual([1, 2, 3, 4]);
  });
});

describe("statsLabel", () => {
  it("shows the rate only when the media was ever sent priced", () => {
    expect(statsLabel(st(12, 3, 0.25, null))).toBe("Sent 12 · Unlock 3 · 25%");
    expect(statsLabel(st(2, 0, null, null))).toBe("Sent 2 · Unlock 0");
  });
});

describe("seenByFan / isStatsSort", () => {
  it("hides unlocked, free and on-wall media; a locked PPV stays", () => {
    expect(["unlocked", "free", "on-wall"].every(seenByFan)).toBe(true);
    expect(seenByFan("locked")).toBe(false);
    expect(seenByFan(null)).toBe(false);
  });

  it("knows its own sorts, not OF's", () => {
    expect(isStatsSort("recent")).toBe(true);
    expect(isStatsSort("newest")).toBe(false);
  });
});
