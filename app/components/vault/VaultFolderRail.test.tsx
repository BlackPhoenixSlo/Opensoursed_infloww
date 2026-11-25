import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";

import { vaultListsKey } from "@/hooks/useVaultMedia";
import type { VaultList, VaultListsResp } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const h = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/components/vault/VaultAccount", () => ({ useVaultAccountId: () => "1000001" }));
vi.mock("@/lib/relay", async (orig) => {
  const mod = await orig<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: h.post } };
});

import VaultFolderRail from "@/components/vault/VaultFolderRail";
import { loadFolderSort } from "@/components/vault/vaultFolderSort";

const AID = "1000001";
const folder = (id: number, name: string): VaultList => ({ id, name, type: "custom", hasMedia: false });
const FOLDERS = [folder(1, "Alpha"), folder(2, "Beta"), folder(3, "Gamma")];
const sortButton = () => screen.getByTitle(/^Sort — the name shown is saved in this browser/);

const newClient = () => new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });

function deferred() {
  let resolve!: (v: unknown) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise((res, rej) => ((resolve = res), (reject = rej)));
  return { promise, resolve, reject };
}

function setup(qc?: QueryClient) {
  const onChanged = vi.fn();
  const utils = renderWithProviders(
    <VaultFolderRail folders={FOLDERS} loading={false} error={false} onRetry={() => {}} selectedId={null}
      onSelect={() => {}} onChanged={onChanged} onDownloadFolder={() => {}}
      downloadFolderGate={{ reason: "", desktopOnly: false, queues: false }} />,
    qc ?? newClient(),
  );
  if (!qc) utils.queryClient.setQueryData<VaultListsResp>(vaultListsKey(AID), { list: FOLDERS });
  const cached = () => utils.queryClient.getQueryData<VaultListsResp>(vaultListsKey(AID))?.list.map((f) => f.name);
  const label = () => sortButton().textContent;
  return { onChanged, cached, label };
}

async function customizeGammaFirst() {
  fireEvent.click(sortButton());
  fireEvent.click(screen.getByRole("menuitem", { name: "Customize order" }));
  const row = (name: string) => screen.getByText(name).closest("[role=button]")!;
  fireEvent.dragStart(row("Gamma"));
  fireEvent.dragOver(row("Alpha"));
  fireEvent.drop(row("Alpha"));
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
}

beforeEach(() => {
  h.post.mockReset();
  window.localStorage.clear();
});
afterEach(cleanup);

describe("VaultFolderRail Customize order → Done", () => {
  it("the cache takes the dragged order once OF took it, not before, with no refetch", async () => {
    const sort = deferred();
    h.post.mockReturnValue(sort.promise);
    const { onChanged, cached, label } = setup();
    await customizeGammaFirst();

    expect(h.post).toHaveBeenCalledWith("/admin/vault-ai/of-folders/sort", expect.objectContaining({ custom_order: [3, 1, 2] }), { accountId: AID });
    expect(cached()).toEqual(["Alpha", "Beta", "Gamma"]);
    expect(onChanged).not.toHaveBeenCalled();
    expect(label()).toBe("Default");

    await act(async () => sort.resolve({}));
    expect(cached()).toEqual(["Gamma", "Alpha", "Beta"]);
    expect(label()).toBe("Custom");
    expect(loadFolderSort(AID).sort).toBe("custom");
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("OF refusing keeps OF's order in the cache and the label, and still asks the parent to refetch", async () => {
    const sort = deferred();
    h.post.mockReturnValue(sort.promise);
    const { onChanged, cached, label } = setup();
    await customizeGammaFirst();

    await act(async () => sort.reject(new Error("502")));
    expect(cached()).toEqual(["Alpha", "Beta", "Gamma"]);
    expect(label()).toBe("Default");
    expect(onChanged).toHaveBeenCalledTimes(1);
  });
});

describe("VaultFolderRail sort", () => {
  it("a picked sort OF took is the label, the same one stored", async () => {
    h.post.mockResolvedValue({});
    const { label } = setup();
    fireEvent.click(sortButton());
    await act(async () => fireEvent.click(screen.getByRole("menuitemradio", { name: "Name" })));
    expect(label()).toBe("Name");
    expect(loadFolderSort(AID).sort).toBe("name");
  });

  it("the rail has its cached folder list read again at mount", () => {
    const qc = newClient();
    qc.setQueryData<VaultListsResp>(vaultListsKey(AID), { list: FOLDERS });
    setup(qc);
    expect(qc.getQueryState(vaultListsKey(AID))?.isInvalidated).toBe(true);
  });
});
