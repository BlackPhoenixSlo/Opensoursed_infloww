import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { invalidateVaultGrid, vaultGridKeys } from "@/hooks/useVaultCache";
import type { FanId } from "@/lib/fanId";

const AID = "700237824869654528";
const FANSLY_ALBUM: FanId = "900805470987055104"; // the real "asdf" album
const OF_LIST: FanId = 29271410;

const refreshAll = invalidateVaultGrid;

function seedGrid(qc: QueryClient, listId: FanId | null) {
  qc.setQueryData(["vault-media", AID, "all", listId, "newest", ""], { list: [] });
}

const isInvalidated = (qc: QueryClient, key: unknown[]) =>
  qc.getQueryCache().find({ queryKey: key })?.state.isInvalidated ?? false;

describe("vault refreshAll", () => {
  it("invalidates the grid for a Fansly album snowflake", () => {
    const qc = new QueryClient();
    seedGrid(qc, FANSLY_ALBUM);
    refreshAll(qc, AID);
    expect(isInvalidated(qc, ["vault-media", AID, "all", FANSLY_ALBUM, "newest", ""])).toBe(true);
  });

  it("invalidates the grid for a numeric OnlyFans list id", () => {
    const qc = new QueryClient();
    seedGrid(qc, OF_LIST);
    refreshAll(qc, AID);
    expect(isInvalidated(qc, ["vault-media", AID, "all", OF_LIST, "newest", ""])).toBe(true);
  });

  it("also refreshes an album that is NOT the one on screen", () => {
    const qc = new QueryClient();
    seedGrid(qc, null);
    seedGrid(qc, FANSLY_ALBUM);
    refreshAll(qc, AID);
    expect(isInvalidated(qc, ["vault-media", AID, "all", null, "newest", ""])).toBe(true);
    expect(isInvalidated(qc, ["vault-media", AID, "all", FANSLY_ALBUM, "newest", ""])).toBe(true);
  });

  it("covers the folder counts and the mirror flag too, not just the grid", () => {
    const qc = new QueryClient();
    qc.setQueryData(["vault-of-folders-mirror", AID], { list: [] });
    qc.setQueryData(["vault-cache-summary", AID], { count: 0 });
    refreshAll(qc, AID);
    expect(isInvalidated(qc, ["vault-of-folders-mirror", AID])).toBe(true);
    expect(isInvalidated(qc, ["vault-cache-summary", AID])).toBe(true);
  });

  it("names every root the vault surface reads, and each is account-scoped", () => {
    const keys = vaultGridKeys(AID);
    expect(keys.map((k) => k[0])).toEqual([
      "vault-media",
      "vault-lists",
      "vault-mirror-items",
      "vault-cache-summary",
      "vault-of-folders-mirror",
    ]);
    for (const k of keys) expect(k[1]).toBe(AID);
  });

  it("proves the OLD refreshAll left the grid stale", () => {
    const qc = new QueryClient();
    seedGrid(qc, FANSLY_ALBUM);
    qc.invalidateQueries({ queryKey: ["vault-mirror-items", AID] });
    qc.invalidateQueries({ queryKey: ["vault-lists", AID] });
    qc.invalidateQueries({ queryKey: ["vault-cache-summary", AID] });
    expect(isInvalidated(qc, ["vault-media", AID, "all", FANSLY_ALBUM, "newest", ""])).toBe(false);
  });
});
