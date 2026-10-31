/**
 * VaultManagePanel, driven as the operator drives it: the real panel, toolbar
 * and item editor; the data hooks and the heavy children (folder rail, tile,
 * preview player) are stubs. Each case here failed on the pre-reducer panel —
 * see `vaultBrowseReducer` and `vaultItemEditorReducer` for the bugs.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import type { VaultList, VaultMedia } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

type Tile = VaultMedia & { _ai?: Record<string, unknown> };
const h = vi.hoisted(() => {
  const BEACH = { id: 29271410, name: "Beach", type: "custom", hasMedia: true };
  return {
    BEACH,
    FOLDERS: [BEACH],
    ALL: [
      {
        id: 1, type: "photo",
        _ai: { description: "old desc", tags: ["a", "b"], describe_status: "described", suggested_price_cents: 1250 },
      },
      { id: 2, type: "photo" },
      { id: 3, type: "video" },
    ] as Tile[],
    IN_BEACH: [{ id: 10, type: "photo" }] as Tile[],
    describeMedia: vi.fn(),
    addToOfFolder: vi.fn(),
    patch: vi.fn(),
  };
});
const AID = "1000001";
const { BEACH } = h;

vi.mock("@/components/vault/VaultAccount", () => ({ useVaultAccountId: () => "1000001" }));
vi.mock("@/lib/relay", async (orig) => {
  const mod = await orig<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, patch: h.patch, post: vi.fn(), get: vi.fn() } };
});
vi.mock("@/hooks/useVaultMedia", async (orig) => {
  const mod = await orig<typeof import("@/hooks/useVaultMedia")>();
  const lists = { data: { list: h.FOLDERS }, isLoading: false, isError: false, refetch: () => {} };
  return {
    ...mod,
    useVaultLists: () => lists,
    useVaultMedia: (o: { listId: unknown }) => ({
      items: o.listId == null ? h.ALL : h.IN_BEACH,
      hasMore: false, isLoading: false, isFetchingNextPage: false, error: null, loadMore: () => {},
    }),
  };
});
vi.mock("@/hooks/useVaultCache", async (orig) => {
  const mod = await orig<typeof import("@/hooks/useVaultCache")>();
  const summary = { data: { count: 0 }, isLoading: false };
  const plan = { data: undefined, refetch: () => {} };
  return {
    ...mod,
    useVaultCacheSummary: () => summary,
    useDescribePlan: () => plan,
    useOfFoldersMirror: () => ({ data: undefined }),
    useMirrorItems: () => ({
      items: [], hasMore: false, isLoading: false, isFetchingNextPage: false, error: null, loadMore: () => {},
    }),
    describeMedia: h.describeMedia,
    addToOfFolder: h.addToOfFolder,
    searchOf: () => Promise.resolve(),
  };
});
vi.mock("@/hooks/useVaultSweep", async (orig) => {
  const mod = await orig<typeof import("@/hooks/useVaultSweep")>();
  return { ...mod, useVaultSweep: () => ({ busy: false, progress: null, start: () => {} }) };
});
vi.mock("@/components/vault/VaultFolderRail", () => ({
  default: ({ folders, onSelect }: { folders: VaultList[]; onSelect: (id: unknown) => void }) => (
    <nav>
      <button type="button" onClick={() => onSelect(null)}>rail:All media</button>
      {folders.map((f) => (
        <button key={String(f.id)} type="button" onClick={() => onSelect(f.id)}>rail:{f.name}</button>
      ))}
    </nav>
  ),
  FolderCounts: () => null,
}));
vi.mock("@/components/vault/VaultTile", () => ({
  default: ({ media, selectMode, checked, onClick, onCheck }: {
    media: VaultMedia; selectMode: boolean; checked: boolean;
    onClick: (m: VaultMedia) => void; onCheck: (m: VaultMedia) => void;
  }) => (
    <button type="button" aria-pressed={checked} onClick={() => (selectMode ? onCheck(media) : onClick(media))}>
      tile {media.id}
    </button>
  ),
}));
vi.mock("@/components/vault/VaultPreviewMedia", () => ({ default: () => null }));
vi.mock("@/components/chat/VaultPicker", () => ({ VaultVideoPreview: () => null }));

import VaultManagePanel from "./VaultManagePanel";

beforeAll(() => {
  globalThis.IntersectionObserver = class {
    observe() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver;
  window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as
    unknown as typeof window.matchMedia;
});
beforeEach(() => {
  h.describeMedia.mockReset();
  h.addToOfFolder.mockReset().mockResolvedValue({});
  h.patch.mockReset().mockResolvedValue({ item: {}, locked: [] });
});
afterEach(cleanup);

const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const selectionBar = () => screen.queryByText("Selected");
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("selection across a change of view", () => {
  it("switching folder clears the ticks, and Add to category sends only what is ticked now", async () => {
    renderWithProviders(<VaultManagePanel />);
    click("Select");
    click("tile 1");
    click("tile 2");
    expect(selectionBar()).toBeInTheDocument();

    click("rail:Beach");
    // Bug: the bar stayed up with "Selected 2" over a grid showing none of them.
    expect(selectionBar()).toBeNull();

    click("tile 10");
    click("Add to category");
    click("Beach");
    await flush();
    expect(h.addToOfFolder).toHaveBeenCalledTimes(1);
    expect(h.addToOfFolder).toHaveBeenCalledWith(AID, BEACH.id, [10]);
  });

  it("switching media type clears the ticks", () => {
    renderWithProviders(<VaultManagePanel />);
    click("Select");
    click("tile 1");
    expect(selectionBar()).toBeInTheDocument();
    click("Photo");
    expect(selectionBar()).toBeNull();
  });
});

describe("the item editor under a Re-describe", () => {
  const redescribe = () => h.describeMedia.mockResolvedValue({
    media_id: 1, ok: true, status: "described", description: "new desc", tags: ["x", "y"],
  });
  const descBox = () => screen.getByPlaceholderText("Full description…") as HTMLTextAreaElement;
  const tagsBox = () => screen.getByPlaceholderText("comma, separated, tags") as HTMLInputElement;
  const saveBtn = () => screen.getByRole("button", { name: "Save & lock" });

  it("shows the new description, and nothing reads as edited", async () => {
    redescribe();
    renderWithProviders(<VaultManagePanel />);
    click("tile 1");
    expect(descBox().value).toBe("old desc");
    click("Re-describe");
    await flush();
    // Bug: the inputs kept "old desc" / "a, b" and Save turned on, armed with them.
    expect(descBox().value).toBe("new desc");
    expect(tagsBox().value).toBe("x, y");
    expect(saveBtn()).toBeDisabled();
  });

  it("keeps the operator's edit, and Save & lock sends only that field", async () => {
    redescribe();
    renderWithProviders(<VaultManagePanel />);
    click("tile 1");
    fireEvent.change(descBox(), { target: { value: "mine" } });
    click("Re-describe");
    await flush();
    expect(descBox().value).toBe("mine");
    click("Save & lock");
    await flush();
    // Bug: the body also carried tags: "a, b" — the stale tags, locked over the fresh describe.
    expect(h.patch).toHaveBeenCalledWith(
      "/admin/vault-ai/items/1", { account_id: AID, fields: { description: "mine" } }, { accountId: AID },
    );
    await waitFor(() => expect(screen.getByText("Saved — locked 1 field")).toBeInTheDocument());
  });
});

describe("the item editor's price", () => {
  it("letters in the price box are not a $0 price", async () => {
    renderWithProviders(<VaultManagePanel />);
    click("tile 1");
    fireEvent.change(screen.getByTitle(/Your price for this media/), { target: { value: "abc" } });
    // Bug: "abc" → "" → Number("") === 0, so Save sent suggested_price_cents: 0 and locked it.
    fireEvent.click(screen.getByRole("button", { name: "Save & lock" }));
    await flush();
    expect(h.patch).not.toHaveBeenCalled();
  });
});
