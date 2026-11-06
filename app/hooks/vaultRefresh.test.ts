import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { QueryClient } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: { post: vi.fn(), get: vi.fn() },
}));
vi.mock("@/hooks/useVaultCache", () => ({
  invalidateVaultGrid: vi.fn(async () => {}),
  mirrorItemsKey: (accountId: string) => ["vault-mirror-items", accountId],
}));

import { invalidateVaultGrid } from "@/hooks/useVaultCache";
import { ofUnreachable, refreshVaultFromOf, reloadBrokenThumbs, type ThumbSource } from "@/hooks/vaultRefresh";
import { relay, RelayError } from "@/lib/relay";

const post = relay.post as unknown as Mock;
const reload = invalidateVaultGrid as unknown as Mock;

// R2-6: only "OnlyFans could not be reached" reads as the saved-vault note; anything else is an error.
describe("ofUnreachable", () => {
  it.each<[string, unknown, boolean]>([
    ["relay 502 (OF failed)", new RelayError(502, null), true],
    ["relay 504 (OF timed out)", new RelayError(504, null), true],
    ["no answer (network)", new TypeError("Failed to fetch"), true],
    ["401", new RelayError(401, null), false],
    ["403", new RelayError(403, null), false],
    ["422", new RelayError(422, null), false],
  ])("%s", (_n, e, want) => expect(ofUnreachable(e)).toBe(want));
});

describe("refreshVaultFromOf", () => {
  const qc = new QueryClient();
  beforeEach(() => { post.mockReset(); reload.mockClear(); });

  it("synced: true, grid reloaded", async () => {
    post.mockResolvedValue({});
    await expect(refreshVaultFromOf(qc, "1", null)).resolves.toBe(true);
    expect(post.mock.calls[0][0]).toBe("/admin/vault-ai/sync?account_id=1");
    expect(reload).toHaveBeenCalledOnce();
  });

  it("OF unreachable: false, grid still reloaded", async () => {
    post.mockRejectedValue(new RelayError(502, null));
    await expect(refreshVaultFromOf(qc, "1", 7)).resolves.toBe(false);
    expect(post.mock.calls[0][0]).toBe("/admin/vault-ai/sync?account_id=1&of_folder_id=7");
    expect(reload).toHaveBeenCalledOnce();
  });

  it("another failure: thrown, after the grid reloaded", async () => {
    const e = new RelayError(403, null);
    post.mockRejectedValue(e);
    await expect(refreshVaultFromOf(qc, "1", null)).rejects.toBe(e);
    expect(reload).toHaveBeenCalledOnce();
  });
});

// R3-6: what each source reloads for broken thumbnails, in order (the relay's cache drop first, then the refetch).
describe("reloadBrokenThumbs", () => {
  it.each<[ThumbSource, string[]]>([
    ["mirror", ['invalidate ["vault-mirror-items","1"]']],
    ["live", ["POST /admin/vault/cache/invalidate", 'invalidate ["vault-media","1"]']],
  ])("%s", async (source, want) => {
    const log: string[] = [];
    post.mockReset();
    post.mockImplementation(async (url: string) => { log.push(`POST ${url}`); });
    const qc = new QueryClient();
    vi.spyOn(qc, "invalidateQueries").mockImplementation(async (f) => { log.push(`invalidate ${JSON.stringify(f?.queryKey)}`); });
    await reloadBrokenThumbs(qc, "1", source);
    expect(log).toEqual(want);
  });
});
