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
    searchingOf: false,
    mirrorItems: [] as Tile[],
    get: vi.fn(),
    summary: { data: { count: 0 } as { count: number; complete?: boolean }, isLoading: false },
    access: { isLoading: false, isError: false } as { isLoading: boolean; isError: boolean; data?: { restricted: boolean } },
  };
});
const AID = "1000001";
const { BEACH } = h;

vi.mock("@/components/vault/VaultAccount", () => ({
  useVaultAccountId: () => "1000001",
  useVaultAccount: () => ({ account: { id: "1000001", nickname: "Amy" } }),
}));
vi.mock("@/lib/relay", async (orig) => {
  const mod = await orig<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, patch: h.patch, post: vi.fn(), get: h.get } };
});
vi.mock("@/hooks/useVaultMedia", async (orig) => {
  const mod = await orig<typeof import("@/hooks/useVaultMedia")>();
  const lists = { data: { list: h.FOLDERS }, isLoading: false, isError: false, refetch: () => {} };
  return {
    ...mod,
    useVaultLists: () => lists,
    useChatterFolderAccess: () => h.access,
    useVaultMedia: (o: { listId: unknown; type: string }) => ({
      items: (o.listId == null ? h.ALL : h.IN_BEACH).filter((m) => o.type === "all" || m.type === o.type),
      hasMore: false, isLoading: false, isFetchingNextPage: false, error: null, loadMore: () => {},
    }),
  };
});
vi.mock("@/hooks/useVaultCache", async (orig) => {
  const mod = await orig<typeof import("@/hooks/useVaultCache")>();
  const plan = { data: undefined, refetch: () => {} };
  return {
    ...mod,
    useVaultCacheSummary: () => h.summary,
    useDescribePlan: () => plan,
    useOfFoldersMirror: () => ({ data: undefined }),
    useMirrorItems: () => ({
      items: h.mirrorItems, hasMore: false, isLoading: false, isFetchingNextPage: false, error: null, loadMore: () => {},
    }),
    describeMedia: h.describeMedia,
    addToOfFolder: h.addToOfFolder,
    useOfSearch: (_a: string, q: string, on: boolean) => on && !!q && h.searchingOf,
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
      {/* A folder the rail shows before the panel's folder list has it (the list still loading). */}
      <button type="button" onClick={() => onSelect(4242)}>rail:not loaded</button>
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

import { VaultDownloadProvider } from "./VaultDownloadPanel";
import VaultManagePanel, { FOLDER_LOADING } from "./VaultManagePanel";

/** The panel as VaultProPage mounts it: under the page's one download (`headerSlot`: its header button's place). */
const renderPanel = (headerSlot?: HTMLElement) =>
  renderWithProviders(<VaultDownloadProvider><VaultManagePanel headerSlot={headerSlot} /></VaultDownloadProvider>);

beforeAll(() => {
  globalThis.IntersectionObserver = class {
    observe() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver;
  window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as
    unknown as typeof window.matchMedia;
});
beforeEach(() => {
  h.summary.data = { count: 0 };
  h.searchingOf = false;
  h.mirrorItems = [];
  h.access = { isLoading: false, isError: false };
  h.describeMedia.mockReset();
  h.addToOfFolder.mockReset().mockResolvedValue({});
  h.patch.mockReset().mockResolvedValue({ item: {}, locked: [] });
  h.get.mockReset();
});
afterEach(cleanup);

const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const selectionBar = () => screen.queryByText("Selected");
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("selection across a change of view", () => {
  it("switching folder clears the ticks, and Add to category sends only what is ticked now", async () => {
    renderPanel();
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

  it("the Photo / Video filter keeps the ticks; Download selected takes every one (hidden too), then clears them", async () => {
    const fetched: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      fetched.push(u);
      return new Response(new Uint8Array(2), { status: 200, headers: { "content-length": "2" } });
    }));
    const root = {
      getDirectoryHandle: async () => root,
      getFileHandle: async () => ({ createWritable: async () => new WritableStream<Uint8Array>() }),
    };
    (window as unknown as { showDirectoryPicker: unknown }).showDirectoryPicker = vi.fn(async () => root);
    vi.spyOn(console, "warn").mockImplementation(() => {});   // writeLinks: jsdom's Blob has no stream()
    try {
      renderPanel();
      click("Photo");
      click("Select");
      click("tile 1");
      click("Video");
      expect(screen.queryByRole("button", { name: "tile 1" })).toBeNull();   // hidden by the filter
      click("tile 3");
      // every bar action takes both: the bar says one is off screen
      const count = () => screen.queryByTestId("selection-count");
      expect(count()).toHaveTextContent(/^2 selected · 1 hidden by filter$/);
      click("All");
      expect(count()).toHaveTextContent(/^Selected\s*2$/);
      click("Video");
      click("Download selected");
      await waitFor(() => expect(count()).toBeNull());   // cleared once the run started
      await waitFor(() => expect(fetched.length).toBe(2));
      expect(fetched.map((u) => new URL(u, "http://x").searchParams.get("media_id")).sort()).toEqual(["1", "3"]);
    } finally {
      delete (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker;
      vi.unstubAllGlobals();
      vi.restoreAllMocks();
    }
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
    click("tile 1");
    fireEvent.change(screen.getByTitle(/Your price for this media/), { target: { value: "abc" } });
    // Bug: "abc" → "" → Number("") === 0, so Save sent suggested_price_cents: 0 and locked it.
    fireEvent.click(screen.getByRole("button", { name: "Save & lock" }));
    await flush();
    expect(h.patch).not.toHaveBeenCalled();
  });
});

describe("the header download button", () => {
  // The relay soft-denies "All" to a folder-limited chatter on both sources (here a partial mirror of its folders,
  // count 12, complete:false: the live path), so a whole-vault download would read "Nothing to download".
  // The button is portalled into VaultProPage's header slot; here a bare div stands in for it.
  const button = () => screen.getByTestId("vault-header-download");
  let slot: HTMLElement;
  const render = () => renderPanel(slot);
  beforeEach(() => {
    slot = document.body.appendChild(document.createElement("div"));
    (window as { showDirectoryPicker?: unknown }).showDirectoryPicker = () => Promise.resolve(null);
  });
  afterEach(() => {
    slot.remove();
    delete (window as { showDirectoryPicker?: unknown }).showDirectoryPicker;
  });

  it.each([
    // An owner's folder-access query is disabled: not loading, no data.
    { who: "owner", access: { isLoading: false, isError: false }, off: false },
    { who: "unrestricted chatter", access: { isLoading: false, isError: false, data: { restricted: false } }, off: false },
    { who: "restricted chatter", access: { isLoading: false, isError: false, data: { restricted: true } }, off: true },
    { who: "chatter, folder access not read yet", access: { isLoading: true, isError: false }, off: true },
    { who: "chatter, folder access read failed", access: { isLoading: false, isError: true }, off: true },
  ])("$who: off=$off", ({ access, off }) => {
    h.summary.data = { count: 12, complete: false };
    h.access = access;
    render();
    expect(slot).toContainElement(button());
    expect(button()).toHaveTextContent("Download full vault");
    if (off) {
      expect(button()).toBeDisabled();
      expect(button()).toHaveAttribute("title", "Your access is by folder: download a folder");
    } else {
      expect(button()).toBeEnabled();
    }
  });

  it("follows the selected folder: a restricted chatter can download the folder it sees", () => {
    h.access = { isLoading: false, isError: false, data: { restricted: true } };
    render();
    expect(button()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "rail:Beach" }));
    expect(button()).toHaveTextContent("Download full folder");
    expect(button()).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "rail:All media" }));
    expect(button()).toHaveTextContent("Download full vault");
  });

  // #29: a selected folder the folder list does not have yet is never downloaded under a guessed name: off.
  it("a selected folder not in the loaded list: off, says why, a click starts nothing", () => {
    h.access = { isLoading: false, isError: false };
    render();
    fireEvent.click(screen.getByRole("button", { name: "rail:not loaded" }));
    expect(button()).toHaveTextContent("Download full folder");
    expect(button()).toBeDisabled();
    expect(button()).toHaveAttribute("title", FOLDER_LOADING);
    fireEvent.click(button());
    expect(screen.queryByLabelText("Vault download")).toBeNull();
  });

  // #430 + #29: a selection made in a folder saves into it; one made in a folder not resolved yet is off, not guessed.
  it.each<[string, string, string | null]>([
    ["a resolved folder: on", "rail:Beach", null],
    ["a folder not in the loaded list: off", "rail:not loaded", FOLDER_LOADING],
  ])("Download selected in %s", (_n, railClick, off) => {
    h.access = { isLoading: false, isError: false };
    render();
    fireEvent.click(screen.getByRole("button", { name: railClick }));
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "tile 10" }));
    const dlSel = screen.getByRole("button", { name: "Download selected" });
    if (off) {
      expect(dlSel).toBeDisabled();
      expect(dlSel).toHaveAttribute("title", off);
    } else {
      expect(dlSel).toBeEnabled();
    }
  });

  // #24: the header click downloads the scope it names: the listing carries the selected folder's id, or none.
  it.each<[string, string | null, string | null]>([
    ["All media: the whole vault", null, null],
    ["a selected folder: that folder", "rail:Beach", String(BEACH.id)],
  ])("%s", async (_n, railClick, listId) => {
    (window as { showDirectoryPicker?: unknown }).showDirectoryPicker = () => Promise.resolve({});
    h.summary.data = { count: 12, complete: false };   // a partial mirror: the live listing
    h.access = { isLoading: false, isError: false };
    h.get.mockResolvedValue({ list: [], hasMore: false });
    render();
    if (railClick) fireEvent.click(screen.getByRole("button", { name: railClick }));
    fireEvent.click(button());
    await waitFor(() => expect(h.get.mock.calls.some(([p]) => String(p).startsWith("/api/of/v2/vault/media?"))).toBe(true));
    const listing = h.get.mock.calls.map(([p]) => String(p)).filter((p) => p.startsWith("/api/of/v2/vault/media?"));
    expect(listing.map((p) => new URLSearchParams(p.split("?")[1]).get("list_id"))).toEqual([listId]);
  });

  it("while Chrome's picker is open, says Desktop/Documents/Downloads themselves are refused; gone once closed", async () => {
    let close!: (v: null) => void;
    (window as { showDirectoryPicker?: unknown }).showDirectoryPicker = () => new Promise((r) => { close = r; });
    h.summary.data = { count: 12, complete: false };
    h.access = { isLoading: false, isError: false };
    render();
    fireEvent.click(button());
    expect(await screen.findByTestId("dl-pick-hint")).toHaveTextContent(/New Folder/);
    expect(button()).toBeDisabled();
    close(null);
    await flush();
    expect(screen.queryByTestId("dl-pick-hint")).toBeNull();
    expect(button()).toBeEnabled();
  });
});

describe("search while OF's own search runs", () => {
  it("an empty grid spins 'Searching OnlyFans…', not 'No data', until OF answered", async () => {
    h.summary.data = { count: 12, complete: true };   // the mirror path; its search found nothing
    h.searchingOf = true;
    const { rerender } = renderPanel();
    fireEvent.change(screen.getByPlaceholderText("Search media by PPV caption"), { target: { value: "leggings" } });
    expect(await screen.findByText("Searching OnlyFans…")).toBeInTheDocument();
    expect(screen.queryByText("No data")).toBeNull();
    h.searchingOf = false;
    rerender(<VaultDownloadProvider><VaultManagePanel /></VaultDownloadProvider>);
    expect(await screen.findByText("No data")).toBeInTheDocument();
    expect(screen.queryByText("Searching OnlyFans…")).toBeNull();
  });

  it("with mirror hits already shown, a small line says more may come", async () => {
    h.summary.data = { count: 12, complete: true };
    h.mirrorItems = h.ALL;
    h.searchingOf = true;
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("Search media by PPV caption"), { target: { value: "leggings" } });
    expect(await screen.findByText("Searching OnlyFans for more…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "tile 1" })).toBeInTheDocument();
  });

  it("the live path (no mirror) never says it is searching OnlyFans: its listing is OF's search", async () => {
    h.searchingOf = true;   // what the hook would say if it were not gated
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("Search media by PPV caption"), { target: { value: "leggings" } });
    await flush();
    await new Promise((r) => setTimeout(r, 300));   // past the search box's 250 ms debounce
    await flush();
    expect(screen.queryByText(/Searching OnlyFans/)).toBeNull();
    expect(screen.getByRole("button", { name: "tile 1" })).toBeInTheDocument();
  });
});
