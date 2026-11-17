/**
 * useStandardFolders — opening the vault only reads the categories. The sort (POST sync: O(vault) write batches)
 * runs when "Standard folders" is turned on, when the switch is on but no category exists yet, and on Retry.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));

import { useStandardFolders } from "@/hooks/useStandardFolders";
import { setVaultSetting, useVaultSettings } from "@/hooks/useVaultSettings";
import { relay } from "@/lib/relay";
const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;

const AID = "1000001";
const SYNC = "/admin/vault-ai/standard-folders/sync";
const FOLDER = { id: 1, kind: "photo", slug: "beach", name: "Beach", items: 2, priceable: true };
const syncCalls = () => post.mock.calls.filter(([url]) => url === SYNC).length;

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  get.mockReset();
  post.mockReset().mockResolvedValue({ list: [FOLDER], pending: 0 });
  put.mockReset();
});
afterEach(cleanup);

describe("useStandardFolders", () => {
  it("mount with categories: one GET, no sync", async () => {
    get.mockResolvedValue({ list: [FOLDER], pending: 0 });
    const { result } = renderHook(() => useStandardFolders(AID, true), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(get).toHaveBeenCalledTimes(1);
    expect(syncCalls()).toBe(0);
  });

  it("switch off: no GET, no sync", async () => {
    renderHook(() => useStandardFolders(AID, false), { wrapper });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(get).not.toHaveBeenCalled();
    expect(syncCalls()).toBe(0);
  });

  it("on with no category yet: one sync, and its list replaces the empty one", async () => {
    get.mockResolvedValue({ list: [], pending: 0 });
    const { result } = renderHook(() => useStandardFolders(AID, true), { wrapper });
    await waitFor(() => expect(result.current.data?.list).toEqual([FOLDER]));
    expect(syncCalls()).toBe(1);
  });

  it("Retry syncs", async () => {
    get.mockResolvedValue({ list: [FOLDER], pending: 0 });
    const { result } = renderHook(() => useStandardFolders(AID, true), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => result.current.refresh());
    await waitFor(() => expect(syncCalls()).toBe(1));
  });
});

describe("turn-on with the rail mounted (rwl3 N2)", () => {
  // The rail reads the switch, as VaultManagePanel does; its categories GET answers [] until the sort lands.
  const useRail = () => {
    const settings = useVaultSettings(AID);
    return useStandardFolders(AID, !!settings.data?.standard_folders);
  };
  const mount = async () => {
    get.mockImplementation(async (url: string) =>
      url.startsWith("/admin/vault-ai/settings") ? { folder_price_final: false, standard_folders: false }
        : { list: [], pending: 0 });
    put.mockResolvedValue({ folder_price_final: false, standard_folders: true });
    const hook = renderHook(useRail, { wrapper });
    await waitFor(() => expect(client.getQueryData(["vault-settings", AID])).toBeTruthy());
    return hook;
  };

  it("one sort, not one from the switch and one from the empty rail", async () => {
    let land!: (v: unknown) => void;
    post.mockReset().mockReturnValue(new Promise((r) => { land = r; }));
    const { result } = await mount();
    await act(async () => { await setVaultSetting(client, AID, { standard_folders: true }); });
    await waitFor(() => expect(result.current.syncing).toBe(true));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(syncCalls()).toBe(1);
    await act(async () => { land({ list: [FOLDER], pending: 0 }); });
    await waitFor(() => expect(result.current.data?.list).toEqual([FOLDER]));
    expect(syncCalls()).toBe(1);
  });

  it("a failed turn-on sort shows on the rail (not swallowed)", async () => {
    let fail!: (e: Error) => void;
    post.mockReset().mockReturnValue(new Promise((_r, j) => { fail = j; }));
    const { result } = await mount();
    await act(async () => { await setVaultSetting(client, AID, { standard_folders: true }); });
    await waitFor(() => expect(result.current.syncing).toBe(true));
    await act(async () => { fail(new Error("boom")); });
    await waitFor(() => expect(result.current.syncError).toBe(true));
    expect(syncCalls()).toBe(1);
  });
});

describe("setVaultSetting", () => {
  it.each([
    ["turning Standard folders on sorts once", { standard_folders: true }, true, 1],
    ["turning it off does not", { standard_folders: false }, false, 0],
    ["the other switch does not", { folder_price_final: true }, true, 0],
  ])("%s", async (_name, patch, savedStandard, want) => {
    put.mockResolvedValue({ folder_price_final: false, standard_folders: savedStandard });
    await setVaultSetting(client, AID, patch);
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(syncCalls()).toBe(want);
  });
});
