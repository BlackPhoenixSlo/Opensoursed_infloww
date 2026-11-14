/**
 * VaultInternalFoldersModal: the list (sections, counts, the OF mark, the price), an open folder's rule note and
 * controls per kind, and each write's request (remove, move, reorder, create, delete). The data hooks, the tile and
 * the viewer are faked at the module; every name is fake.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

const api = vi.hoisted(() => ({
  list: [] as unknown[],
  items: [] as { id: number; type: string }[],
  hasMore: false,
  mirrorOpts: [] as { internalFolderId?: number | null; enabled?: boolean }[],
  confirm: true,
}));

vi.mock("@/hooks/useInternalFolders", () => ({
  useInternalFolders: () => ({ data: { list: api.list }, isPending: false, isError: false, isSuccess: true, isFetching: false }),
  invalidateInternalFolders: vi.fn(async () => {}),
  internalFolders: {
    create: vi.fn(async (_a: string, name: string) => ({ folder_id: 9, name })),
    rename: vi.fn(async (_a: string, _id: number, name: string) => ({ name })),
    remove: vi.fn(async () => {}),
    add: vi.fn(async () => ({ added: 1, already: 0, moved: 1 })),
    take: vi.fn(async () => ({ removed: 2 })),
    reorder: vi.fn(async () => ({ items: 3 })),
  },
}));
vi.mock("@/hooks/useVaultCache", () => ({
  mirrorItemsKey: (a: string) => ["vault-mirror-items", a],
  useMirrorItems: (opts: { internalFolderId?: number | null; enabled?: boolean }) => {
    api.mirrorOpts.push(opts);
    return { items: opts.enabled ? api.items : [], hasMore: api.hasMore, isLoading: false, isFetching: false,
      isFetchingNextPage: false, error: null, loadMore: () => {}, refetch: () => {} };
  },
}));
vi.mock("@/hooks/useFolderPrices", () => ({
  useFolderPrices: () => ({ data: { "vf:2": 2500 } }),
  setFolderPrice: vi.fn(async () => {}),
}));
vi.mock("@/hooks/useThumbAutoRefresh", () => ({ useThumbAutoRefresh: () => ({}) }));
vi.mock("@/components/chat/VaultPicker", () => ({ VaultVideoPreview: () => null }));
vi.mock("@/components/vault/VaultItemModal", () => ({ default: () => <div data-testid="viewer" /> }));
vi.mock("@/components/vault/VaultFolderRail", () => ({ FolderPriceModal: ({ priceRef }: { priceRef: string }) => <div data-testid="price">{priceRef}</div> }));
vi.mock("@/components/ui/ifConfirm", () => ({ ifConfirm: vi.fn(async () => api.confirm) }));
vi.mock("@/components/vault/VaultTile", () => ({
  default: ({ media, selectMode, checked, onCheck, onClick }: {
    media: { id: number }; selectMode?: boolean; checked?: boolean;
    onCheck?: (m: unknown) => void; onClick?: (m: unknown) => void;
  }) => (
    <button type="button" aria-pressed={!!checked} onClick={() => (selectMode ? onCheck?.(media) : onClick?.(media))}>
      tile {media.id}
    </button>
  ),
}));

import { ifConfirm } from "@/components/ui/ifConfirm";
import VaultInternalFoldersModal from "@/components/vault/VaultInternalFoldersModal";
import { internalFolders } from "@/hooks/useInternalFolders";
import { renderWithProviders } from "@/test-utils";

const LIST = [
  { id: 1, name: "feet-nude", kind: "pack", items: 3, photos: 3, videos: 0, of_list_id: null },
  { id: 2, name: "AI-mass", kind: "ai", items: 9, photos: 6, videos: 3, of_list_id: "88" },
  { id: 3, name: "beach", kind: "own", items: 0, photos: 0, videos: 0, of_list_id: null },
];
const calls = vi.mocked(internalFolders);

function open(folderId: number | "all") {
  api.list = LIST;
  api.items = [{ id: 11, type: "photo" }, { id: 12, type: "photo" }, { id: 13, type: "video" }];
  const onClose = vi.fn();
  renderWithProviders(<VaultInternalFoldersModal accountId="acc-1" onClose={onClose} />);
  fireEvent.click(screen.getByTestId(`if-folder-${folderId}`));
  return onClose;
}
const tick = (...ids: number[]) => {
  fireEvent.click(screen.getByRole("button", { name: "Select" }));
  for (const id of ids) fireEvent.click(screen.getByRole("button", { name: `tile ${id}` }));
};
const bar = () => within(screen.getByTestId("if-selection-bar"));

afterEach(() => { cleanup(); vi.clearAllMocks(); api.list = []; api.items = []; api.hasMore = false; api.mirrorOpts = []; api.confirm = true; });

describe("VaultInternalFoldersModal", () => {
  it("lists the folders in sections with counts, price and the OF mark; no grid is read until one opens", () => {
    api.list = LIST;
    renderWithProviders(<VaultInternalFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(
      ["Yours · 1", "AI folders · 1", "Feet pack · 1"]);
    const ai = within(screen.getByTestId("if-folder-2"));
    expect(ai.getByText("6 photos · 3 videos")).toBeInTheDocument();
    expect(ai.getByText("$25")).toBeInTheDocument();
    expect(ai.getByText("on OF")).toBeInTheDocument();
    expect(within(screen.getByTestId("if-folder-3")).getByText("not on OF")).toBeInTheDocument();
    expect(api.mirrorOpts.every((o) => o.enabled === false)).toBe(true);
  });

  it("a generated folder says the edit rule and reads its own items; a pack rung keeps its name and stays", () => {
    open(2);
    expect(screen.getByTestId("if-kind-note").textContent).toMatch(/becomes yours/);
    expect(api.mirrorOpts.at(-1)).toMatchObject({ internalFolderId: 2, enabled: true });
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("if-folder-1"));
    expect(screen.getByTestId("if-kind-note").textContent).toMatch(/photos only/);
    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.getByRole("button", { name: "Set price" })).toBeInTheDocument();
  });

  it("Remove takes the ticks out of the open folder and says so", async () => {
    open(2);
    tick(11, 13);
    fireEvent.click(bar().getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.take).toHaveBeenCalledWith(2, { account_id: "acc-1", media_ids: [11, 13] }));
    expect(await screen.findByText("Removed 2 from AI-mass")).toBeInTheDocument();
    expect(screen.queryByTestId("if-selection-bar")).toBeNull();
  });

  it("Move to… names the open folder as the source; Copy to… does not", async () => {
    open(2);
    tick(12);
    fireEvent.click(bar().getByRole("button", { name: "Move to…" }));
    const dlg = within(screen.getByRole("dialog", { name: "Move to folder" }));
    expect(dlg.queryByText("AI-mass")).toBeNull();
    fireEvent.click(dlg.getByText("beach"));
    await waitFor(() => expect(calls.add).toHaveBeenCalledWith(3, { account_id: "acc-1", media_ids: [12], move_from: 2 }));
    expect(await screen.findByText("Moved 1 to beach")).toBeInTheDocument();

    // Select mode stays on after a write.
    fireEvent.click(screen.getByRole("button", { name: "tile 11" }));
    fireEvent.click(bar().getByRole("button", { name: "Copy to…" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Copy to folder" })).getByText("feet-nude"));
    await waitFor(() => expect(calls.add).toHaveBeenLastCalledWith(1, { account_id: "acc-1", media_ids: [11] }));
  });

  it("All media only adds", async () => {
    open("all");
    expect(api.mirrorOpts.at(-1)).toMatchObject({ internalFolderId: null, enabled: true });
    tick(13);
    expect(bar().queryByRole("button", { name: "Remove" })).toBeNull();
    expect(bar().queryByRole("group", { name: "Reorder" })).toBeNull();
    fireEvent.click(bar().getByRole("button", { name: "Add to folder…" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Add to folder" })).getByText("beach"));
    await waitFor(() => expect(calls.add).toHaveBeenCalledWith(3, { account_id: "acc-1", media_ids: [13] }));
  });

  it("reorder: the press that would change nothing is off; Later sends the item it lands in front of and keeps the ticks", async () => {
    open(2);
    tick(11);
    expect(bar().getByRole("button", { name: "First" })).toBeDisabled();
    expect(bar().getByRole("button", { name: "← Earlier" })).toBeDisabled();
    fireEvent.click(bar().getByRole("button", { name: "Later →" }));
    await waitFor(() => expect(calls.reorder).toHaveBeenCalledWith(2, { account_id: "acc-1", media_ids: [11], before: 13 }));
    expect(await screen.findByText("Order saved")).toBeInTheDocument();
    expect(screen.getByTestId("if-selected-count").textContent).toBe("Selected 1");
    fireEvent.click(bar().getByRole("button", { name: "Last" }));
    await waitFor(() => expect(calls.reorder).toHaveBeenLastCalledWith(2, { account_id: "acc-1", media_ids: [11], before: null }));
  });

  it("a filter turns reorder off", () => {
    open(2);
    fireEvent.click(screen.getByRole("button", { name: "Videos" }));
    tick(13);
    expect(bar().queryByRole("group", { name: "Reorder" })).toBeNull();
    expect(bar().getByText("Clear the filter to reorder")).toBeInTheDocument();
  });

  it("New folder: a taken name is refused in the dialog; a free one is created and opened", async () => {
    open(2);
    fireEvent.click(screen.getByRole("button", { name: "New folder" }));
    const dlg = within(screen.getByRole("dialog", { name: "New folder" }));
    const save = dlg.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(dlg.getByRole("textbox"), { target: { value: "beach" } });
    expect(dlg.getByText("A folder with this name already exists.")).toBeInTheDocument();
    expect(save).toBeDisabled();
    calls.create.mockImplementationOnce(async (_a: string, name: string) => {
      api.list = [...LIST, { id: 9, name, kind: "own", items: 0, photos: 0, videos: 0, of_list_id: null }];
      return { folder_id: 9, name };
    });
    fireEvent.change(dlg.getByRole("textbox"), { target: { value: " pool " } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.create).toHaveBeenCalledWith("acc-1", "pool"));
    expect(await screen.findByText("Created pool")).toBeInTheDocument();
    expect(screen.getByTestId("if-folder-9")).toHaveAttribute("aria-current", "true");
  });

  it("a refused write shows the relay's sentence and keeps the ticks", async () => {
    calls.add.mockRejectedValueOnce(new Error("A feet pack is photos only: 1 of these are not photos."));
    open(2);
    tick(13);
    fireEvent.click(bar().getByRole("button", { name: "Copy to…" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Copy to folder" })).getByText("feet-nude"));
    // Said in the dialog (which stays for another pick) and on the editor's notice line under it.
    expect(await within(screen.getByRole("dialog", { name: "Copy to folder" })).findByRole("alert")).toHaveTextContent(
      "A feet pack is photos only: 1 of these are not photos.");
    expect(screen.getByTestId("if-notice")).toHaveClass("text-err");
    expect(screen.getByTestId("if-selected-count").textContent).toBe("Selected 1");
  });

  it("Delete asks first (naming the OF list it leaves), then goes back to the list; a No deletes nothing", async () => {
    api.confirm = false;
    open(2);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(ifConfirm).toHaveBeenCalledTimes(1));
    expect(vi.mocked(ifConfirm).mock.calls[0][0]).toMatch(/9 items stay in the vault\. The OnlyFans list .* left as it is/);
    expect(calls.remove).not.toHaveBeenCalled();

    api.confirm = true;
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.remove).toHaveBeenCalledWith(expect.anything(), "acc-1", 2));
    expect(await screen.findByText("Deleted AI-mass")).toBeInTheDocument();
    expect(screen.queryByTestId("if-kind-note")).toBeNull();
  });

  it("a tile opens the vault's viewer; Set price uses the folder's vf ref", () => {
    open(2);
    fireEvent.click(screen.getByRole("button", { name: "tile 12" }));
    expect(screen.getByTestId("viewer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change price" }));
    expect(screen.getByTestId("price").textContent).toBe("vf:2");
  });
});
