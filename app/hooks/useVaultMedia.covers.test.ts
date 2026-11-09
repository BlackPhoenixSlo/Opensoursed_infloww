/** ["vault-lists"] is persisted to the browser: its folder covers must never be OF-signed urls. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/relay", () => ({ relay: { get } }));

import { fetchAllVaultLists } from "./useVaultMedia";

const SIGNED = "https://cdn2.onlyfans.com/files/a/ab/abc/300x300_1.jpg?Policy=eyJ&Signature=xyz&Key-Pair-Id=K1";

beforeEach(() => {
  get.mockReset();
  get.mockResolvedValue({
    hasMore: false,
    all: { photosCount: 9, videosCount: 4, gifsCount: 1, audiosCount: 3, medias: [{ id: 501, type: "photo", url: SIGNED }] },
    list: [
      { id: 1, type: "custom", name: "With ids", hasMedia: true, medias: [{ id: 501, type: "photo", url: SIGNED }, { type: "video", url: SIGNED }] },
      { id: 2, type: "custom", name: "No ids", hasMedia: true, medias: [{ type: "photo", url: SIGNED }] },
      { id: 3, type: "custom", name: "Empty", hasMedia: false, medias: [] },
    ],
  });
});

describe("fetchAllVaultLists covers", () => {
  it("rewrites an id'd cover to the stable thumb, drops the rest, and leaves no signature", async () => {
    const r = await fetchAllVaultLists({ accountId: "acct 1" });
    expect(r.list.map((l) => l.medias)).toEqual([
      [{ id: 501, type: "photo", url: "/admin/vault-ai/thumb?account_id=acct%201&media_id=501" }],
      [],
      [],
    ]);
    expect(JSON.stringify(r)).not.toMatch(/Policy=|Signature=|Key-Pair-Id/);
  });

  it("keeps OF's whole-vault counts (`all`, the All media row's), counts only", async () => {
    const r = await fetchAllVaultLists({ accountId: "acct 1" });
    expect(r.all).toEqual({ photosCount: 9, videosCount: 4, gifsCount: 1, audiosCount: 3 });
  });

  it("drops every cover when no account is known (no thumb url can be built)", async () => {
    const r = await fetchAllVaultLists({});
    expect(r.list.every((l) => l.medias?.length === 0)).toBe(true);
    expect(JSON.stringify(r)).not.toMatch(/Policy=|Signature=|Key-Pair-Id/);
  });
});
