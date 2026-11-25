import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
const platform = vi.hoisted(() => ({ current: "onlyfans" as "onlyfans" | "fansly" }));
vi.mock("@/hooks/useCan", async () => {
  const { can } = await import("@/lib/platform");
  return { useCan: (_: unknown, cap: Parameters<typeof can>[1]) => can(platform.current, cap) };
});
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: {
      ...mod.relay,
      get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(),
      delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/UserContext")>()),
  useUser: () => ({ user: { user_id: "owner-1" } }),
}));
const dlRun = vi.hoisted(() => ({
  sink: undefined as "folder" | undefined,
  calls: [] as Array<{ a: { accountId: string; creator: string; label: string }; signal: AbortSignal }>,
}));
vi.mock("@/components/vault/vaultDownload", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/components/vault/vaultDownload")>();
  return {
    ...mod,
    downloadSink: () => dlRun.sink ?? mod.downloadSink(),
    startDownload: (a: { accountId: string; creator: string; label: string; mode: "vault" },
      d: { send: (x: unknown) => void; signal: AbortSignal }, kind: "folder",
      started: (s: unknown, attempt: number, root: unknown) => void) => {
      dlRun.calls.push({ a, signal: d.signal });
      d.send({ type: "start", mode: a.mode, label: a.label, accountId: a.accountId, creator: a.creator, sink: kind });
      started(async () => null, 1, {});
      return new Promise(() => {});
    },
  };
});
vi.mock("@/contexts/ChatterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => ({ chatter: null }),
}));

import VaultProPage from "@/components/growth/VaultProPage";
import { VaultDownloadProvider } from "@/components/vault/VaultDownloadPanel";
import { relay } from "@/lib/relay";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { renderWithProviders } from "@/test-utils";
import { DOWNLOAD_OFF, SHARE_MODE_OFF } from "@/components/vault/vaultDownloadReducer";

const Page = () => <VaultDownloadProvider><VaultProPage /></VaultDownloadProvider>;

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPatch = relay.patch as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;


const CAPTURE = readFileSync(
  resolve(__dirname, "../../../docs/infloww-layouts/growth-vault-pro.md"),
  "utf8",
);

function expectInCapture(id: string, label: string) {
  const row = CAPTURE.split("\n").find((l) => l.startsWith(`| ${id} |`));
  expect(row, `capture row ${id}`).toBeTruthy();
  expect(row, `capture row ${id} holds "${label}"`).toContain(label);
}

function expectBefore(a: Element, b: Element) {
  expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}


const A = { id: "1000001", nickname: "Creator A", has_session: true };
const B = { id: "1000002", nickname: "Creator B", has_session: true };
const FOLDERS = [
  { id: 11, name: "Folder one", type: "custom", hasMedia: true, photosCount: 3, videosCount: 1, gifsCount: 0, audiosCount: 0 },
  { id: 12, name: "Folder two", type: "custom", hasMedia: false, photosCount: 0, videosCount: 0, gifsCount: 0, audiosCount: 0 },
];
const ALL = { photosCount: 7, videosCount: 5, gifsCount: 2, audiosCount: 1, medias: [{ id: 1, type: "photo", url: "https://cdn/signed" }] };
const ALL_NO_VIDEO = { ...ALL, videosCount: 0, audiosCount: 0 };
let listsAll: typeof ALL | undefined = ALL;

let roster: Array<typeof A> = [A, B];

beforeEach(() => {
  dlRun.sink = undefined;
  roster = [A, B];
  listsAll = ALL;
  window.localStorage.clear();
  window.localStorage.setItem("vaultProOnboarding", JSON.stringify({ batchUploadEntry: "1", uploadPageStep: "1" }));
  for (const m of [relayGet, relayPost, relayPut, relayPatch, relayDelete]) m.mockReset();
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p === "/admin/accounts") return Promise.resolve({ accounts: roster, active_account_id: null });
    if (p.startsWith("/api/of/v2/vault/lists")) return Promise.resolve({ list: FOLDERS, hasMore: false, all: listsAll });
    if (p.startsWith("/api/of/v2/vault/media")) return Promise.resolve({ list: [], hasMore: false });
    if (p.startsWith("/api/of/v2/vault/upload/status")) return Promise.resolve({ running: false });
    if (p.startsWith("/admin/vault-ai/cache/summary")) return Promise.resolve({ count: 0, running: false, last_run: null });
    return Promise.resolve({});
  });
  relayPost.mockResolvedValue({});
  relayDelete.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  platform.current = "onlyfans";
});

/** Mount the page and wait for the rail's folders, which only render once a Creator is adopted. */
async function mount() {
  renderWithProviders(<Page />);
  await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());
}

function extrasButton(): HTMLElement {
  return screen.getByRole("button", { name: EXTRAS_OVERFLOW_LABEL });
}

function overflow(): HTMLElement {
  const open = screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL });
  if (open) return open;
  fireEvent.click(extrasButton());
  return screen.getByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL });
}

function openOptions(combobox: HTMLElement): HTMLElement[] {
  if (combobox.getAttribute("aria-expanded") !== "true") fireEvent.click(combobox);
  const list = document.getElementById(combobox.getAttribute("aria-controls") ?? "") as HTMLElement;
  return within(list).getAllByRole("option");
}

const column = () => screen.getByTestId("of-creator-column");
const creatorRow = (name: string) => within(column()).getByRole("button", { name: new RegExp(name) });

function rail(): HTMLElement {
  const els = screen.getAllByText("All media");
  return (els.map((el) => el.closest("[data-rail-desk]")).find(Boolean)
    ?? els.map((el) => el.closest("aside")).find(Boolean)) as HTMLElement;
}

describe("Vault Pro header and rail, in the capture's order", () => {
  it("shows the header items in the capture's order, each label in the capture next to its ID", async () => {
    await mount();
    const header = [
      { id: "growth-vault-pro#3", label: "Vault Pro", el: screen.getByRole("heading", { level: 1, name: "Vault Pro" }) },
      { id: "growth-vault-pro#7", label: "Learn", el: screen.getByRole("link", { name: "Learn" }) },
      { id: "growth-vault-pro#10", label: "Add media", el: screen.getByRole("button", { name: "Add media" }) },
    ];
    for (const h of header) expectInCapture(h.id, h.label);
    for (let i = 1; i < header.length; i++) expectBefore(header[i - 1].el, header[i].el);
    expectInCapture("growth-vault-pro#6", "creator selector");
    const bar = screen.getByRole("heading", { level: 1, name: "Vault Pro" }).closest("header") as HTMLElement;
    expect(within(bar).queryByRole("combobox", { name: "Creator" })).toBeNull();
    expect(within(bar).queryByTestId("of-creator-column")).toBeNull();
    expectBefore(bar, column());
    expect(column().nextElementSibling!.contains(rail())).toBe(true);
  });

  it("lays the header out as a bar with a bottom rule, with the rail and grid flush beneath it (#15, #16)", async () => {
    await mount();
    const header = screen.getByRole("heading", { level: 1, name: "Vault Pro" }).closest("header") as HTMLElement;
    expect(header.className).toContain("border-b");
    const pane = rail().closest("aside")!.parentElement as HTMLElement;
    expect(pane.className).not.toMatch(/\brounded|\bborder\b/);
    expectBefore(header, pane);
    expect(document.querySelector("details")).toBeNull();
    expect(header.contains(extrasButton())).toBe(true);
    expectBefore(extrasButton(), screen.getByRole("button", { name: "Add media" }));
  });

  it("drops the long description paragraph, which the capture does not have", async () => {
    await mount();
    expect(screen.queryByText(/Browse and organize/)).toBeNull();
  });

  it("links Learn to the bundle's help article, in a new tab", async () => {
    await mount();
    const learn = screen.getByRole("link", { name: "Learn" });
    expect(learn).toHaveAttribute("href", "https://help.infloww.com/en/articles/9346888-vault-pro");
    expect(learn).toHaveAttribute("target", "_blank");
  });

  it("puts the rail before the grid, opening on the sort label, then All media, then the folders", async () => {
    await mount();
    const r = rail();
    const sort = within(r).getByRole("button", { name: "Default" });
    expect(sort.getAttribute("title")).toMatch(/not read back\)$/);
    const all = within(r).getByText("All media");
    const one = within(r).getByText("Folder one");
    const two = within(r).getByText("Folder two");
    expectInCapture("growth-vault-pro#20", "Default");
    expectInCapture("growth-vault-pro#26", "All media");
    expectBefore(sort, all);
    expectBefore(all, one);
    expectBefore(one, two);
    expectBefore(within(r).getByRole("button", { name: "Search" }), all);
    expectBefore(within(r).getByRole("button", { name: "New category" }), all);
    expectInCapture("growth-vault-pro#23", "Search");
    expectInCapture("growth-vault-pro#36", "New category");
    expectBefore(r, document.querySelector("section input[placeholder^='Search']") as HTMLElement);
  });

  it("shows each folder's counts, or the capture's \"empty\" when it has none", async () => {
    await mount();
    expectInCapture("growth-vault-pro#30", "\"empty\" when all are 0");
    const two = within(rail()).getByText("Folder two").closest("[role=button]") as HTMLElement;
    expect(within(two).getByText("empty")).toBeTruthy();
    const one = within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement;
    expect(within(one).queryByText("empty")).toBeNull();
    expect(within(one).getByText("3")).toBeTruthy();
    expect(within(one).getByText("1")).toBeTruthy();
  });

  it("draws no per-folder statistics line (#33): no read reports them, so no dash placeholders", async () => {
    await mount();
    expectInCapture("growth-vault-pro#33", "send count");
    for (const name of ["Folder one", "Folder two"]) {
      const row = within(rail()).getByText(name).closest("[role=button]") as HTMLElement;
      expect(within(row).queryByLabelText("Statistics")).toBeNull();
      expect(row.textContent).not.toContain("—");
    }
  });

  it("shows the whole vault's per-type counts (OF's `all`) on the All media row, no line when the read has none", async () => {
    listsAll = ALL_NO_VIDEO;
    await mount();
    const all = () => within(rail()).getByText("All media").closest("button") as HTMLElement;
    await waitFor(() => expect(within(all()).getByTitle("photo").textContent).toBe("7"));
    expect(within(all()).getByTitle("gif").textContent).toBe("2");
    expect(within(all()).queryByTitle("video")).toBeNull();
    cleanup();
    listsAll = undefined;
    await mount();
    expect(all().textContent).toBe("All media");
  });

  it("opens the sort popover with the capture's options, in its order", async () => {
    await mount();
    fireEvent.click(within(rail()).getByRole("button", { name: "Default" }));
    const menu = screen.getByRole("menu");
    const labels = ["Default", "Name", "Recent", "Media", "Custom", "Ascending", "Descending", "Customize order"];
    for (const l of labels) expectInCapture("growth-vault-pro#22", `"${l}"`);
    const items = Array.from(menu.querySelectorAll("[role^=menuitem]")).map((el) => el.textContent);
    expect(items).toEqual(labels);
  });

  it("names the row menu's items as the capture does", async () => {
    await mount();
    const one = within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement;
    const more = within(one).getByRole("button", { name: "More" });
    expect(more.textContent).toBe("");
    expect(more.querySelector("svg")).toHaveAttribute("width", "20");
    fireEvent.click(more);
    const items =within(screen.getByRole("menu")).getAllByRole("menuitem").map((el) => el.textContent);
    expectInCapture("growth-vault-pro#34", "Rename / Delete");
    expect(items).toEqual(["Rename", "Set price", "Delete", "Download folder"]);
    const dl = within(screen.getByRole("menu")).getByRole("menuitem", { name: "Download folder" });
    expect(dl).toBeDisabled();
    expect(dl).toHaveAttribute("title", DOWNLOAD_OFF);
  });

  it("filters the rail by folder name from its search, with no relay call", async () => {
    await mount();
    const calls = relayGet.mock.calls.length;
    fireEvent.click(within(rail()).getByRole("button", { name: "Search" }));
    const input = within(rail()).getByPlaceholderText("Search");
    expectInCapture("growth-vault-pro#23", "`maxLength:100`");
    expect(input).toHaveAttribute("maxLength", "100");
    fireEvent.change(input, { target: { value: "two" } });
    expect(within(rail()).queryByText("Folder one")).toBeNull();
    expect(within(rail()).getByText("Folder two")).toBeTruthy();
    expect(relayGet.mock.calls.length).toBe(calls);
  });
});

describe("the Extras drawer's full download", () => {
  const dl = () => within(overflow()).getByTestId("vault-extras-download");
  afterEach(() => {
    delete (window as { showDirectoryPicker?: unknown }).showDirectoryPicker;
    delete (navigator as { canShare?: unknown }).canShare;
  });

  it("is not in the header; first in the drawer, and names the vault or the selected folder", async () => {
    (window as { showDirectoryPicker?: unknown }).showDirectoryPicker = () => Promise.resolve(null);
    await mount();
    expect(screen.queryByTestId("vault-extras-download")).toBeNull();
    expect(screen.queryByText("Download full vault")).toBeNull();
    expectBefore(dl(), within(overflow()).getByRole("button", { name: "Collect all" }));
    expect(dl()).toHaveTextContent("Download full vault");
    expect(dl()).toBeEnabled();
    fireEvent.click(within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement);
    await waitFor(() => expect(dl()).toHaveTextContent("Download full folder"));
    expect(dl()).toBeEnabled();
    fireEvent.click(within(rail()).getByText("All media"));
    await waitFor(() => expect(dl()).toHaveTextContent("Download full vault"));
  });

  it("is on a phone too, off with the desktop-only reason (share sheet only)", async () => {
    (navigator as { canShare?: unknown }).canShare = () => true;
    await mount();
    expect(dl()).toBeDisabled();
    expect(dl()).toHaveAttribute("title", SHARE_MODE_OFF);
    expect(dl().closest(".hidden")).toBeNull();
  });

  it("is off with the browser reason where nothing can save", async () => {
    await mount();
    expect(dl()).toBeDisabled();
    expect(dl()).toHaveAttribute("title", DOWNLOAD_OFF);
  });

  it("while the model accounts are still read, there is no drawer to open (#25)", async () => {
    relayGet.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<Page />);
    await waitFor(() => expect(extrasButton()).toBeDisabled());
    expect(screen.queryByTestId("vault-extras-download")).toBeNull();
  });

  it("with no Creator, there is no drawer to open", async () => {
    roster = [];
    renderWithProviders(<Page />);
    await screen.findAllByText("No model accounts with a live session.");
    expect(extrasButton()).toBeDisabled();
    expect(screen.queryByTestId("vault-extras-download")).toBeNull();
  });
});

describe("Add media", () => {
  it("reveals the import card over the page, and the back arrow hides it again", async () => {
    await mount();
    const card = await screen.findByText(/Import to/);
    expect(card).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Add media" }));
    expect(card).toBeVisible();
    expect(screen.getByRole("button", { name: "Back" }).getAttribute("title")).toMatch(new RegExp(`^${EXTRA_LABEL}\\n`));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(card).not.toBeVisible();
  });
});

describe("the guided tours (#12, #118, #119)", () => {
  const seen = () => JSON.parse(window.localStorage.getItem("vaultProOnboarding") || "{}");
  const tour = () => screen.queryByRole("dialog", { name: "Guided tour" });

  it("shows the Add media tour once on a first visit with a Creator, and Got it closes it", async () => {
    window.localStorage.clear();
    await mount();
    const t = await screen.findByRole("dialog", { name: "Guided tour" });
    expectInCapture("growth-vault-pro#12", "Click “+ Add media” to upload one or more media files to the vault");
    expect(within(t).getByText("Click “+ Add media” to upload one or more media files to the vault")).toBeTruthy();
    expect(seen()).toEqual({ batchUploadEntry: "1" });
    expect(within(t).queryByRole("button", { name: "Next" })).toBeNull();
    expect(within(t).queryByRole("button", { name: "Skip" })).toBeNull();
    fireEvent.click(within(t).getByRole("button", { name: "Got it" }));
    expect(tour()).toBeNull();
    cleanup();
    await mount();
    expect(tour()).toBeNull();
  });

  it("shows no tour and marks nothing seen while there is no Creator, as Add media is then off", async () => {
    window.localStorage.clear();
    roster = [];
    renderWithProviders(<Page />);
    await screen.findByText("No model accounts with a live session.");
    expect(tour()).toBeNull();
    expect(seen()).toEqual({});
  });

  it("closes the Add media tour on Add media, then walks the upload guide's three steps to Start upload", async () => {
    window.localStorage.clear();
    await mount();
    await screen.findByRole("dialog", { name: "Guided tour" });
    fireEvent.click(screen.getByRole("button", { name: "Add media" }));
    const t = await screen.findByRole("dialog", { name: "Guided tour" });
    expect(seen()).toEqual({ batchUploadEntry: "1", uploadPageStep: "1" });
    expectInCapture("growth-vault-pro#118", "First, you’ll need to link a fan account");
    expect(within(t).getByText("First, you’ll need to link a fan account")).toBeTruthy();
    expect(within(t).getByText(/^Easily start uploading content by linking your fan account\./)).toBeTruthy();
    fireEvent.click(within(t).getByRole("button", { name: "Next" }));
    expectInCapture("growth-vault-pro#118", "Next, choose the media you want to upload");
    expect(within(t).getByText("Next, choose the media you want to upload")).toBeTruthy();
    expectInCapture("growth-vault-pro#119", "You can drag and drop media file(s) here or select them from your computer");
    expect(within(t).getByText("You can drag and drop media file(s) here or select them from your computer")).toBeTruthy();
    fireEvent.click(within(t).getByRole("button", { name: "Next" }));
    expectInCapture("growth-vault-pro#118", "Then, add your media details");
    expect(within(t).getByText("Then, add your media details")).toBeTruthy();
    expect(within(t).getByText(/^Add all necessary information to your media files/)).toBeTruthy();
    expect(within(t).queryByRole("button", { name: "Next" })).toBeNull();
    fireEvent.click(within(t).getByRole("button", { name: "Start upload" }));
    expect(tour()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Add media" }));
    expect(tour()).toBeNull();
  });

  it("lets the upload guide's step markers jump, and Skip, ours and labelled, closes it", async () => {
    window.localStorage.setItem("vaultProOnboarding", JSON.stringify({ batchUploadEntry: "1" }));
    await mount();
    expect(tour()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add media" }));
    const t = await screen.findByRole("dialog", { name: "Guided tour" });
    fireEvent.click(within(t).getByRole("button", { name: "3" }));
    expect(within(t).getByText("Then, add your media details")).toBeTruthy();
    fireEvent.click(within(t).getByRole("button", { name: "1" }));
    expect(within(t).getByText("First, you’ll need to link a fan account")).toBeTruthy();
    const skip = within(t).getByRole("button", { name: "Skip" });
    expect(skip.getAttribute("title")).toMatch(new RegExp(`^${EXTRA_LABEL}`));
    fireEvent.click(skip);
    expect(tour()).toBeNull();
    for (const m of [relayPost, relayPut, relayPatch, relayDelete]) expect(m).not.toHaveBeenCalled();
  });
});

describe("the Extras overflow", () => {
  it("is a header button that opens a drawer holding every named extra, none of which renders outside it", async () => {
    await mount();
    expect(screen.queryByRole("button", { name: "Collect all" })).toBeNull();
    expect(extrasButton()).toHaveAttribute("title", EXTRAS_OVERFLOW_LABEL);
    const box = overflow();
    expect(within(box).getByRole("heading", { name: EXTRAS_OVERFLOW_LABEL })).toHaveAttribute("title", EXTRA_LABEL);
    const tools = [
      screen.getByRole("button", { name: "Collect all" }),
      screen.getByRole("button", { name: /^Describe all/ }),
      screen.getByRole("button", { name: /^Harvest OF/ }),
      screen.getByRole("button", { name: "Duplicates" }),
      screen.getByRole("button", { name: "Feet pack" }),
      screen.getByRole("button", { name: "Build AI folders" }),
    ];
    for (const t of tools) expect(box.contains(t)).toBe(true);
    for (const t of tools) expect(t.closest(".hidden")).toBeNull();
    fireEvent.click(within(box).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL })).toBeNull();
    overflow();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL })).toBeNull();
    fireEvent.click(extrasButton());
    fireEvent.click(extrasButton());
    expect(screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL })).toBeNull();
  });
});

describe("the Creator selector", () => {
  it("is the creator column showing the picked Creator, with the house chips gone (#6)", async () => {
    await mount();
    const rows = within(column()).getAllByTestId("of-creator-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toBe(creatorRow("Creator A"));
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).toBe(creatorRow("Creator B"));
    expect(rows[1]).not.toHaveAttribute("aria-current");
    const select = screen.getByRole("combobox", { name: "Creator" });
    expect(select).toHaveTextContent(/Creator A$/);
    const options = openOptions(select);
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent(/Creator A$/);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveTextContent(/Creator B$/);
    expect(screen.queryByText("Account")).toBeNull();
    expect(screen.queryByRole("button", { name: "Creator A" })).toBeNull();
  });

  it("remounts the grid and the import card, and the next read carries the new account_id", async () => {
    await mount();
    fireEvent.click(within(rail()).getByRole("button", { name: "Search" }));
    expect(within(rail()).getByPlaceholderText("Search")).toBeTruthy();
    const gridBefore = rail();
    const cardBefore = screen.getByText(/Import to/).closest("section");
    relayGet.mockClear();

    fireEvent.click(creatorRow("Creator B"));
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());
    expect(creatorRow("Creator B")).toHaveAttribute("aria-current", "true");

    expect(rail()).not.toBe(gridBefore);
    expect(within(rail()).queryByPlaceholderText("Search")).toBeNull();
    expect(screen.getByText(/Import to/).closest("section")).not.toBe(cardBefore);

    await waitFor(() => {
      const calls = relayGet.mock.calls.map(([p, ctx]) => ({ p: String(p), acc: ctx?.accountId }));
      expect(calls.find((c) => c.p.startsWith("/api/of/v2/vault/lists"))?.acc).toBe(B.id);
      expect(calls.find((c) => c.p.startsWith("/api/of/v2/vault/media"))?.acc).toBe(B.id);
      expect(calls.find((c) => c.p.startsWith("/api/of/v2/vault/upload/status"))?.acc).toBe(B.id);
      expect(calls.some((c) => c.acc === A.id || c.p.includes(`account_id=${A.id}`))).toBe(false);
    });
  });

  it("keeps a running download going, and its card up, when another Creator is picked", async () => {
    dlRun.calls.length = 0;
    dlRun.sink = "folder";
    await mount();
    fireEvent.click(within(overflow()).getByTestId("vault-extras-download"));
    expect(screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL })).toBeNull();
    await waitFor(() => expect(dlRun.calls).toHaveLength(1));
    expect(dlRun.calls[0].a.accountId).toBe(A.id);
    expect(screen.getByRole("region", { name: "Vault download" })).toHaveTextContent("Creator A: whole vault");

    fireEvent.click(creatorRow("Creator B"));
    await waitFor(() => expect(creatorRow("Creator B")).toHaveAttribute("aria-current", "true"));
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());

    expect(dlRun.calls[0].signal.aborted).toBe(false);
    expect(screen.getByRole("region", { name: "Vault download" })).toHaveTextContent("Creator A: whole vault");
    const add = within(overflow()).getByTestId("vault-extras-download");
    expect(add).toHaveTextContent("Add full vault to queue");
    expect(add).toBeEnabled();
    fireEvent.click(add);
    expect(screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL })).toBeNull();
    const card = screen.getByRole("region", { name: "Vault download" });
    await waitFor(() => expect(card).toHaveAttribute("data-queued", "1"));
    expect(card).toHaveTextContent("Creator B: whole vault");
    expect(dlRun.calls).toHaveLength(1);
    fireEvent.click(within(overflow()).getByTestId("vault-extras-download"));
    expect(card).toHaveAttribute("data-queued", "1");
  });

  it("says a dropped session and writes nothing", async () => {
    const { queryClient } = renderWithProviders(<Page />);
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());
    roster = [{ ...A, has_session: false }, B];
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ["accounts"] }); });
    expect(await screen.findByText(/session has dropped/)).toBeTruthy();
    expect(creatorRow("Creator A")).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent(/Creator A$/);
    expect(within(rail()).getByText("Folder one")).toBeTruthy();
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    for (const m of [relayPost, relayPut, relayPatch, relayDelete]) expect(m).not.toHaveBeenCalled();
  });

  it("with no session at all draws the empty frame, offers no Add media and writes nothing", async () => {
    roster = [];
    renderWithProviders(<Page />);
    const line = await screen.findByText("No model accounts with a live session.");
    expect(line).toHaveAttribute("title", EXTRA_LABEL);
    expect(line.closest("div")?.querySelector("[data-empty-art='creator']")).toBeTruthy();
    const r = rail();
    expect(within(r).getByText("Default")).toBeTruthy();
    expect(within(r).getByText("empty")).toBeTruthy();
    expect(within(r).getByRole("button", { name: "Search" })).toBeDisabled();
    const search = screen.getByPlaceholderText("Search media by PPV caption");
    expect(search).toBeDisabled();
    expectBefore(r, search);
    expectBefore(search, line);
    expect(screen.getByRole("combobox", { name: "Search type" })).toBeDisabled();
    for (const l of ["Recent", "All", "Photo", "Refresh", "Grid view", "Select"]) {
      expect(screen.getByRole("button", { name: l })).toBeDisabled();
    }
    expect(within(column()).queryAllByTestId("of-creator-row")).toEqual([]);
    expect(screen.queryByRole("combobox", { name: "Creator" })).toBeNull();
    expect(extrasButton()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add media" })).toBeDisabled();
    for (const m of [relayPost, relayPut, relayPatch, relayDelete]) expect(m).not.toHaveBeenCalled();
  });
});

describe("the page's loading state", () => {
  it("is the capture's spinner (#13), not a line of text", async () => {
    relayGet.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<Page />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeTruthy();
    expect(screen.queryByText("Loading models…")).toBeNull();
  });
});

describe("folder writes reach the same Vault routes as before", () => {
  it("creates a folder from the rail's add icon, through the capture's New category modal", async () => {
    await mount();
    fireEvent.click(within(rail()).getByRole("button", { name: "New category" }));
    const dlg = screen.getByRole("dialog", { name: "New category" });
    expectInCapture("growth-vault-pro#36", "\"Enter category name\"");
    expectInCapture("growth-vault-pro#36", "`maxLength:64`");
    const input = within(dlg).getByLabelText("Category");
    expect(input).toHaveAttribute("placeholder", "Enter category name");
    expect(input).toHaveAttribute("maxLength", "64");
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/of-folders",
      { account_id: A.id, name: "Fresh", media_ids: [] },
      { accountId: A.id },
    ));
  });

  it("on a phone the folders are one select with their counts; the picked folder gets its menu", async () => {
    await mount();
    const pick = screen.getByRole("combobox", { name: "Folder" }) as HTMLSelectElement;
    await waitFor(() => expect([...pick.options].map((o) => o.textContent)).toEqual([
      "All media · 7 photos · 5 videos · 1 audio · 2 GIFs", "Folder one · 3 photos · 1 video", "Folder two · empty",
    ]));
    // All media is no folder: nothing to rename.
    expect(screen.queryByRole("button", { name: "Folder actions" })).toBeNull();
    fireEvent.change(pick, { target: { value: "11" } });
    // The rail's selected row follows the select: one selection, two views of it.
    await waitFor(() => expect(pick.value).toBe("11"));
    fireEvent.click(screen.getByRole("button", { name: "Folder actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    expect(within(screen.getByRole("dialog", { name: "Rename category" })).getByLabelText("Category")).toHaveValue("Folder one");
  });

  it("renames a folder from its row menu, through the Rename category modal", async () => {
    await mount();
    const one = within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement;
    fireEvent.click(within(one).getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const dlg = screen.getByRole("dialog", { name: "Rename category" });
    expectInCapture("growth-vault-pro#36", "\"Rename category\"");
    const input = within(dlg).getByLabelText("Category");
    expect(input).toHaveValue("Folder one");
    expect(within(dlg).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "Folder uno" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/of-folders/11/rename",
      { account_id: A.id, name: "Folder uno" },
      { accountId: A.id },
    ));
  });

  it("deletes a folder from its row menu, through the Delete category modal, and never removes its media", async () => {
    await mount();
    const one = within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement;
    fireEvent.click(within(one).getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dlg = screen.getByRole("dialog", { name: "Delete category" });
    expectInCapture("growth-vault-pro#37", "This will permanently remove the category from the vault.");
    expect(within(dlg).getByText(/This will permanently remove the category from the vault/)).toBeTruthy();
    expectInCapture("growth-vault-pro#37", "Permanently remove all media from the vault");
    const purge = within(dlg).getByRole("checkbox", { name: "Permanently remove all media from the vault" });
    expect(purge).toBeDisabled();
    expect(purge).toHaveAttribute("title", "not wired");
    fireEvent.click(within(dlg).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(
      `/admin/vault-ai/of-folders/11?account_id=${A.id}`,
      { accountId: A.id },
    ));
    for (const [url] of relayDelete.mock.calls) expect(String(url)).not.toContain("clear_media");
  });

  it("offers no media box for an empty folder", async () => {
    await mount();
    const two = within(rail()).getByText("Folder two").closest("[role=button]") as HTMLElement;
    fireEvent.click(within(two).getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dlg = screen.getByRole("dialog", { name: "Delete category" });
    expect(within(dlg).queryByRole("checkbox")).toBeNull();
  });

  it("reorders folders by drag after Customize order, writing the custom order on the check", async () => {
    await mount();
    fireEvent.click(within(rail()).getByRole("button", { name: "Default" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Customize order" }));
    expect(within(rail()).getByText("Customize order")).toBeTruthy();
    const one = within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement;
    const two = within(rail()).getByText("Folder two").closest("[role=button]") as HTMLElement;
    fireEvent.dragStart(two);
    fireEvent.dragOver(one);
    fireEvent.drop(one);
    expectBefore(within(rail()).getByText("Folder two"), within(rail()).getByText("Folder one"));
    expect(relayPost).not.toHaveBeenCalled();
    fireEvent.click(within(rail()).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/of-folders/sort",
      { account_id: A.id, sort: undefined, order: undefined, custom_order: [12, 11] },
      { accountId: A.id },
    ));
    expect(await within(rail()).findByRole("button", { name: "Custom" })).toBeTruthy();
  });

  it("drops a dragged order on the Customize order close, writing nothing", async () => {
    await mount();
    fireEvent.click(within(rail()).getByRole("button", { name: "Default" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Customize order" }));
    const one = within(rail()).getByText("Folder one").closest("[role=button]") as HTMLElement;
    const two = within(rail()).getByText("Folder two").closest("[role=button]") as HTMLElement;
    fireEvent.dragStart(two);
    fireEvent.dragOver(one);
    fireEvent.drop(one);
    fireEvent.click(within(rail()).getByRole("button", { name: "Cancel" }));
    expect(within(rail()).getByRole("button", { name: "Default" })).toBeTruthy();
    expectBefore(within(rail()).getByText("Folder one"), within(rail()).getByText("Folder two"));
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("sorts folders from the popover through the folder sort route", async () => {
    await mount();
    fireEvent.click(within(rail()).getByRole("button", { name: "Default" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Name" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/of-folders/sort",
      { account_id: A.id, sort: "name", order: "asc", custom_order: undefined },
      { accountId: A.id },
    ));
    expect(within(rail()).getByRole("button", { name: "Name" })).toBeTruthy();
  });
});

describe("the flags review banner", () => {
  it("appears inside the Extras overflow when a describe sweep ends with items worth a look", async () => {
    let sweep: Record<string, unknown> = { running: false };
    const base = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string, ctx?: unknown) => {
      const p = String(path);
      if (p.startsWith("/admin/vault-ai/cache/summary")) return Promise.resolve({ count: 5, running: false, last_run: null });
      if (p.startsWith("/admin/vault-ai/describe-all/plan")) return Promise.resolve({ total: 5, undescribed: 5, restage: 0 });
      if (p.startsWith("/admin/vault-ai/describe-all/status")) return Promise.resolve(sweep);
      return base(path, ctx);
    });
    relayPost.mockImplementation((path: string) => {
      if (String(path) === "/admin/vault-ai/describe-all") sweep = { running: true, progress: { done: 0, total: 5 } };
      return Promise.resolve({});
    });
    const { queryClient } = renderWithProviders(<Page />);
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());

    const describe = await within(overflow()).findByRole("button", { name: /^Describe all/ });
    await waitFor(() => expect(describe).toBeEnabled());
    fireEvent.click(describe);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/describe-all", expect.objectContaining({ account_id: A.id }), { accountId: A.id },
    ));
    await within(overflow()).findByRole("button", { name: /^Describing/ });

    sweep = { running: false, progress: { done: 5, total: 5, needs_review: 2 } };
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["vault-sweep", "describe-all", A.id] });
    });
    const check = await screen.findByRole("button", { name: "Check them" });
    expect(overflow()).toContainElement(check);
  });
});


function grid(): HTMLElement {
  return screen.getByPlaceholderText(/^Search media by/).closest("section") as HTMLElement;
}

function mediaReads(): URLSearchParams[] {
  return relayGet.mock.calls
    .map(([p]) => String(p))
    .filter((p) => p.startsWith("/api/of/v2/vault/media?"))
    .map((p) => new URLSearchParams(p.split("?")[1]));
}

const MEDIA = [
  { id: 501, type: "audio", files: {} },
  { id: 502, type: "audio", files: {} },
];
function withMedia() {
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  const base = relayGet.getMockImplementation()!;
  relayGet.mockImplementation((path: string, ctx?: unknown) =>
    String(path).startsWith("/api/of/v2/vault/media")
      ? Promise.resolve({ list: MEDIA, hasMore: false })
      : base(path, ctx));
}
async function mountWithMedia() {
  withMedia();
  await mount();
  await waitFor(() => expect(within(grid()).getAllByTitle(/^#50[12] /)).toHaveLength(2));
}

const SWITCH = "Hide content viewed or unlocked by fan, or posted on Creator's feed";

describe("the toolbar, in the capture's order", () => {
  it("shows the search, the sort box, the media tabs and the tools in order, each label in the capture next to its ID", async () => {
    await mount();
    const g = grid();
    const searchType = within(g).getByRole("combobox", { name: "Search type" });
    expect(searchType).toHaveTextContent("Caption");
    const options = openOptions(searchType).map((o) => o.textContent);
    expect(options).toEqual(["Caption", "Note", "Hashtag"]);
    for (const o of options) expectInCapture("growth-vault-pro#41", `"${o}"`);
    fireEvent.click(searchType);

    const input = within(g).getByPlaceholderText("Search media by PPV caption");
    expectInCapture("growth-vault-pro#43", "\"Search media by \"");
    expectInCapture("growth-vault-pro#43", "\"PPV caption\"");
    expectInCapture("growth-vault-pro#43", "`maxLength:100`");
    expect(input).toHaveAttribute("maxLength", "100");

    const sortBox = within(g).getByRole("button", { name: "Recent" });
    expectInCapture("growth-vault-pro#48", "\"Recent\" at first");

    const mediaLabel = within(g).getByText("Media:");
    expectInCapture("growth-vault-pro#55", "Media:");
    const chips = ["All", "Photo", "Video", "GIF", "Audio"].map((l) => {
      expectInCapture("growth-vault-pro#57", `"${l}"`);
      return within(g).getByRole("button", { name: l });
    });

    const tools = [
      { id: "growth-vault-pro#64", label: "Refresh" },
      { id: "growth-vault-pro#65", label: "Select all" },
      { id: "growth-vault-pro#67", label: "Grid view" },
      { id: "growth-vault-pro#67", label: "Table view" },
    ].map((t) => {
      expectInCapture(t.id, t.label);
      return within(g).getByRole("button", { name: t.label });
    });

    const order = [searchType, input, sortBox, mediaLabel, ...chips, ...tools];
    for (let i = 1; i < order.length; i++) expectBefore(order[i - 1], order[i]);
    expectBefore(rail(), searchType);
  });

  it("opens the sort popover with the capture's dates, fields, directions and switch, in its order", async () => {
    await mount();
    fireEvent.click(within(grid()).getByRole("button", { name: "Recent" }));
    const menu = within(grid()).getByRole("menu");
    const labels = [
      ["growth-vault-pro#50", "All time"], ["growth-vault-pro#50", "Go to date"],
      ["growth-vault-pro#51", "Recent"], ["growth-vault-pro#51", "Most liked"], ["growth-vault-pro#51", "Highest tips"],
      ["growth-vault-pro#51", "Send count"], ["growth-vault-pro#51", "Unlock count"], ["growth-vault-pro#51", "Revenue"],
      ["growth-vault-pro#52", "Ascending"], ["growth-vault-pro#52", "Descending"],
      ["growth-vault-pro#53", SWITCH],
    ];
    for (const [id, l] of labels) expectInCapture(id, l);
    const items = Array.from(menu.querySelectorAll("[role^=menuitem]")).map((el) => el.textContent);
    expect(items).toEqual(labels.map(([, l]) => l));
    for (const l of ["All time", "Recent", "Descending"]) {
      expect(within(menu).getByRole("menuitemradio", { name: l })).toHaveAttribute("aria-checked", "true");
    }
  });

  it("shows \"No data\" for an empty grid, as the capture does", async () => {
    await mount();
    expectInCapture("growth-vault-pro#71", "No data");
    expect(await within(grid()).findByText("No data")).toBeTruthy();
  });
});

describe("the wired toolbar controls call the reads they used before", () => {
  it("each type chip calls the media read with the matching type", async () => {
    await mount();
    await waitFor(() => expect(mediaReads().length).toBeGreaterThan(0));
    expect(mediaReads()[0].get("type")).toBe("all");
    for (const [label, type] of [["Photo", "photo"], ["Video", "video"], ["GIF", "gif"], ["Audio", "audio"]]) {
      fireEvent.click(within(grid()).getByRole("button", { name: label }));
      await waitFor(() => expect(mediaReads().at(-1)?.get("type")).toBe(type));
      expect(within(grid()).getByRole("button", { name: label })).toHaveAttribute("aria-pressed", "true");
    }
  });

  it("search calls the media read with its query, at 3 characters or more", async () => {
    await mount();
    const input = within(grid()).getByPlaceholderText("Search media by PPV caption");
    expectInCapture("growth-vault-pro#44", "`>=3`");
    fireEvent.change(input, { target: { value: "ab" } });
    await act(async () => { await new Promise((r) => setTimeout(r, 400)); });
    expect(mediaReads().some((q) => q.has("query"))).toBe(false);
    fireEvent.change(input, { target: { value: "abc" } });
    await waitFor(() => expect(mediaReads().at(-1)?.get("query")).toBe("abc"));
  });

  it("Ascending and Descending call the media read with the direction; Recent is the read's own order", async () => {
    await mount();
    await waitFor(() => expect(mediaReads().length).toBeGreaterThan(0));
    expect(mediaReads()[0].get("sort")).toBe("desc");
    fireEvent.click(within(grid()).getByRole("button", { name: "Recent" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Ascending" }));
    await waitFor(() => expect(mediaReads().at(-1)?.get("sort")).toBe("asc"));
    const box = within(grid()).getByRole("button", { name: "Recent" });
    expect(box).toHaveAttribute("title", "Ascending");
    fireEvent.click(within(grid()).getByRole("button", { name: "Photo" }));
    await waitFor(() => expect(mediaReads().at(-1)?.toString()).toContain("type=photo&sort=asc"));
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Descending" }));
    await waitFor(() => expect(mediaReads().at(-1)?.toString()).toContain("type=photo&sort=desc"));
  });

  it("Refresh reads the grid again through the same read", async () => {
    await mount();
    await waitFor(() => expect(mediaReads().length).toBeGreaterThan(0));
    const n = mediaReads().length;
    fireEvent.click(within(grid()).getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mediaReads().length).toBeGreaterThan(n));
  });

  it("disables a type chip whose count in the chosen folder is 0", async () => {
    listsAll = ALL_NO_VIDEO;
    await mount();
    expectInCapture("growth-vault-pro#58", "a type with no files is disabled");
    await waitFor(() => expect(within(grid()).getByRole("button", { name: "Video" })).toBeDisabled());
    expect(within(grid()).getByRole("button", { name: "Audio" })).toBeDisabled();
    expect(within(grid()).getByRole("button", { name: "Photo" })).toBeEnabled();
    expect(within(grid()).getByRole("button", { name: "GIF" })).toBeEnabled();
    fireEvent.click(within(rail()).getByText("Folder one"));
    await waitFor(() => expect(within(grid()).getByRole("button", { name: "GIF" })).toBeDisabled());
    expect(within(grid()).getByRole("button", { name: "Audio" })).toBeDisabled();
    expect(within(grid()).getByRole("button", { name: "Photo" })).toBeEnabled();
    expect(within(grid()).getByRole("button", { name: "Video" })).toBeEnabled();
    fireEvent.click(within(rail()).getByText("All media"));
    await waitFor(() => expect(within(grid()).getByRole("button", { name: "Video" })).toBeDisabled());
    expect(within(grid()).getByRole("button", { name: "GIF" })).toBeEnabled();
  });

  it("Select all selects every loaded file and opens the capture's selection bar, whose move adds them to a folder", async () => {
    await mountWithMedia();
    fireEvent.click(within(grid()).getByRole("button", { name: "Select all" }));
    expectInCapture("growth-vault-pro#74", "\"Selected\" and the count");
    expectInCapture("growth-vault-pro#77", "Add to category");
    const move = within(grid()).getByRole("button", { name: "Add to category" });
    const bar = move.parentElement as HTMLElement;
    const selected = within(bar).getByText("Selected");
    expect(selected.nextElementSibling?.textContent).toBe("2");
    expectBefore(selected, move);
    expectBefore(move, within(bar).getByRole("button", { name: "Delete" }));
    fireEvent.click(move);
    const modal = screen.getByRole("dialog", { name: "Add to category" });
    const rows = within(modal).getAllByRole("button", { name: /^Folder/ }).map((b) => b.textContent);
    expect(rows).toEqual([expect.stringContaining("Folder one"), expect.stringContaining("Folder two")]);
    fireEvent.click(within(modal).getByRole("button", { name: /^Folder one/ }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/of-folders/11/add",
      { account_id: A.id, media_ids: [501, 502] },
      { accountId: A.id },
    ));
  });
});

describe("Not wired toolbar controls", () => {
  it("are disabled, titled not wired, and call nothing", async () => {
    await mountWithMedia();
    const g = grid();
    const notWired: HTMLElement[] = [];
    const offOptions: HTMLElement[] = [];
    const searchType = within(g).getByRole("combobox", { name: "Search type" });
    offOptions.push(...openOptions(searchType).slice(1));
    fireEvent.click(within(g).getByRole("button", { name: "Recent" }));
    for (const l of ["Go to date", "Most liked", "Highest tips", "Send count", "Unlock count", "Revenue"]) {
      notWired.push(within(g).getByRole("menuitemradio", { name: l }));
    }
    notWired.push(within(g).getByRole("menuitemcheckbox", { name: SWITCH }));
    notWired.push(within(g).getByRole("button", { name: "Table view" }));
    fireEvent.click(within(g).getByRole("button", { name: "Video" }));
    expectInCapture("growth-vault-pro#62", "\"Video length:\"");
    expect(within(g).getByText("Video length:")).toBeTruthy();
    offOptions.push(...openOptions(within(g).getByRole("combobox", { name: "Video length" })).slice(1));
    fireEvent.click(within(g).getByRole("button", { name: "All" }));
    await waitFor(() => expect(within(grid()).getAllByTitle(/^#50[12] /)).toHaveLength(2));
    fireEvent.click(within(g).getByRole("button", { name: "Select all" }));
    notWired.push(within(g).getByRole("button", { name: "Delete" }));

    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    const gets = relayGet.mock.calls.length;
    for (const el of notWired) {
      expect(el, el.textContent ?? "").toBeDisabled();
      expect(el).toHaveAttribute("title", "not wired");
      fireEvent.click(el);
    }
    expect(offOptions).toHaveLength(6);
    for (const el of offOptions) {
      expect(el, el.textContent ?? "").toHaveAttribute("aria-disabled", "true");
      expect(el.querySelector("[title='not wired']"), el.textContent ?? "").toBeTruthy();
      fireEvent.click(el);
    }
    expect(searchType).toHaveTextContent("Caption");
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(relayGet.mock.calls.length).toBe(gets);
    for (const m of [relayPost, relayPut, relayPatch, relayDelete]) expect(m).not.toHaveBeenCalled();
  });

  it("shows the video length picker on the Video tab only", async () => {
    await mount();
    expect(within(grid()).queryByText("Video length:")).toBeNull();
    fireEvent.click(within(grid()).getByRole("button", { name: "Video" }));
    const picker = within(grid()).getByRole("combobox", { name: "Video length" });
    expect(picker).toHaveTextContent("All");
    const options = openOptions(picker).map((o) => o.textContent);

    expect(options).toEqual(["All", "< 1 min", "1 - 5 mins", "5 - 10 mins", "> 10 mins"]);
    for (const o of options) expectInCapture("growth-vault-pro#62", `"${o}"`);
    fireEvent.click(within(grid()).getByRole("button", { name: "Photo" }));
    expect(within(grid()).queryByText("Video length:")).toBeNull();
  });
});

describe("the toolbar's Inflowwww extras", () => {
  it("carry EXTRA_LABEL: the Select toggle, the search's tag match, the shown count and the selection bar's own tools", async () => {
    await mountWithMedia();
    const g = grid();
    expect(within(g).getByRole("button", { name: "Select" })).toHaveAttribute("title", EXTRA_LABEL);
    expect(within(g).getByPlaceholderText("Search media by PPV caption").getAttribute("title")).toMatch(new RegExp(`^${EXTRA_LABEL}\\n`));
    expect(within(g).getByText("2 shown")).toHaveAttribute("title", EXTRA_LABEL);
    fireEvent.click(within(g).getByRole("button", { name: "Select all" }));
    for (const name of ["New OF folder with these", "Describe selected", "Clear"]) {
      expect(within(g).getByRole("button", { name }).getAttribute("title")).toMatch(new RegExp(`^${EXTRA_LABEL}`));
    }
    fireEvent.click(within(rail()).getByText("Folder one"));
    const boxes = await within(grid()).findAllByPlaceholderText("#");
    expect(boxes).toHaveLength(2);
    for (const b of boxes) expect(b.getAttribute("title")).toMatch(new RegExp(`^${EXTRA_LABEL}\\n`));
  });
});

describe("Vault pro on a Fansly Creator", () => {
  it.each([["onlyfans", true], ["fansly", false]] as const)(
    "%s: Delete in the selection bar, Duplicates in Extras and Remove from vault in the viewer shown: %s",
    async (p, shown) => {
      platform.current = p;
      await mountWithMedia();
      const tile = within(grid()).getAllByTitle(/^#501 /)[0];
      fireEvent.click(tile);
      const viewer = await screen.findByRole("dialog", { name: /#501|Media/ });
      expect(!!within(viewer).queryByRole("button", { name: "Remove from vault" })).toBe(shown);
      fireEvent.keyDown(document, { key: "Escape" });

      fireEvent.click(within(grid()).getByRole("button", { name: "Select all" }));
      const bar = within(grid()).getByRole("button", { name: "Add to category" }).parentElement as HTMLElement;
      expect(!!within(bar).queryByRole("button", { name: "Delete" })).toBe(shown);
      expect(!!within(overflow()).queryByRole("button", { name: "Duplicates" })).toBe(shown);
    },
  );
});
