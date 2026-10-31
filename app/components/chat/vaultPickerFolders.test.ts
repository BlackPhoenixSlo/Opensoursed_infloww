import { describe, expect, it } from "vitest";

import type { ChatterFolderGrant } from "@/hooks/useVaultMedia";
import type { VaultList } from "@/lib/relay";
import { firstUsableFolderId, folderChips, folderSelectItems } from "./vaultPickerFolders";

const list = (id: number, name: string, c: Partial<VaultList> = {}): VaultList =>
  ({ id, type: "custom", name, hasMedia: true, ...c }) as VaultList;

const grant = (folder_id: number): ChatterFolderGrant => ({ folder_id, folder_name: null });

const LISTS = [
  list(1, "Pics", { photosCount: 3, gifsCount: 1 }),
  list(2, "Clips", { videosCount: 17 }),
  list(3, "Mixed", { photosCount: 2, videosCount: 5, audiosCount: 1 }),
  list(4, "Empty"),
];

describe("folderSelectItems", () => {
  it.each<[string, boolean, ChatterFolderGrant[], VaultList[], Array<[unknown, string, string]>]>([
    ["owner: every OF folder, counts label formats", false, [], LISTS, [
      [1, "Pics", "Pics — 🖼 4"],
      [2, "Clips", "Clips — 🎬 17"],
      [3, "Mixed", "Mixed — 🖼 2 · 🎬 5 · 🎵 1"],
      [4, "Empty", "Empty"],
    ]],
    ["owner ignores the allowlist", false, [{ folder_id: 2, folder_name: "X" }], LISTS.slice(0, 1), [
      [1, "Pics", "Pics — 🖼 4"],
    ]],
    ["restricted, 0 allowed: empty menu", true, [], LISTS, []],
    ["restricted, 1 allowed: access name wins over OF name", true, [{ folder_id: 2, folder_name: "Granted" }], LISTS, [
      [2, "Granted", "Granted — 🎬 17"],
    ]],
    ["restricted, many: allowlist order, OF name fallback", true,
      [{ folder_id: 3, folder_name: null }, { folder_id: 1, folder_name: "" }], LISTS, [
        [3, "Mixed", "Mixed — 🖼 2 · 🎬 5 · 🎵 1"],
        [1, "Pics", "Pics — 🖼 4"],
      ]],
    ["restricted, allowed folder not live on OF: placeholder name, no counts", true,
      [{ folder_id: 99, folder_name: null }, { folder_id: 98, folder_name: "Kept" }], LISTS, [
        [99, "Folder 99", "Folder 99"],
        [98, "Kept", "Kept"],
      ]],
  ])("%s", (_n, restricted, allowed, lists, want) => {
    expect(folderSelectItems(restricted, allowed, lists).map((f) => [f.id, f.name, f.label])).toEqual(want);
  });
});

describe("firstUsableFolderId", () => {
  it.each<[string, ChatterFolderGrant[], VaultList[], unknown]>([
    ["0 allowed → null", [], LISTS, null],
    ["1 allowed, live", [grant(2)], LISTS, 2],
    ["many: first one still live on OF", [grant(99), grant(3), grant(1)], LISTS, 3],
    ["none live: first allowed, never All", [grant(99), grant(98)], LISTS, 99],
    ["lists not loaded yet: first allowed", [grant(7)], [], 7],
  ])("%s", (_n, allowed, lists, want) => {
    expect(firstUsableFolderId(allowed, lists)).toBe(want);
  });
});

describe("folderChips", () => {
  it.each<[string, unknown[], Record<string, number>, Array<[unknown, string]>]>([
    // TODO known bug, pinned not spec: count keys are strings, so on numeric (OF)
    // folder ids the global tier never matches and OF's order fills in; the
    // "most used" chips never show for OF. String (Fansly) ids work, below.
    ["known bug: numeric ids skip the global tier (MRU, then OF order); capped, deduped", [2], { "3": 5, "2": 9, "1": 1 },
      [[2, "mru"], [1, "default"], [3, "default"]]],
    ["no history: OF's first folders", [], {}, [[1, "default"], [2, "default"], [3, "default"]]],
    ["deleted folders + zero counts skipped", [99], { "4": 0, "98": 3 }, [[1, "default"], [2, "default"], [3, "default"]]],
  ])("%s", (_n, mru, counts, want) => {
    expect(folderChips(LISTS, mru as never, counts, 3).map((c) => [c.id, c.source])).toEqual(want);
  });
  it("string ids: MRU, then account-wide most used, then OF order", () => {
    const fansly = [list(0, "a"), list(0, "b"), list(0, "c"), list(0, "d")].map((l, i) => ({ ...l, id: `s${i}` }));
    expect(folderChips(fansly, ["s3"], { s1: 2, s2: 5, s3: 9 }, 3).map((c) => [c.id, c.source]))
      .toEqual([["s3", "mru"], ["s2", "global"], ["s1", "global"]]);
    expect(folderChips(fansly, [], { s2: 1 }, 2).map((c) => [c.id, c.source]))
      .toEqual([["s2", "global"], ["s0", "default"]]);
  });
  it("no folders → no chips", () => expect(folderChips([], [1], { "1": 1 }, 3)).toEqual([]));
});
