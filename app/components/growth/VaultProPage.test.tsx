/**
 * Growth > Vault Pro, the page component (docs/spec/infloww-parity-round-2/phase-02-growth-pages.md, Testing
 * Decisions, Seam 1; ticket 36). Rendered with `@/lib/relay` mocked and a fresh QueryClient over two placeholder
 * Creators. What is pinned:
 *
 *  - the header ("Vault Pro", the creator chip, "Learn", "Add media") and the folder rail's labels appear in the
 *    Layout capture's order, and every label transcribed here is read back from the capture on disk next to its
 *    Item ID, so a label the capture does not have fails here rather than in review;
 *  - "Add media" reveals the existing import card (its contents are Phase 5's and are not looked at here);
 *  - every Inflowwww extra the ticket names sits inside the one Extras drawer, which the header's overflow button
 *    (`EXTRAS_OVERFLOW_LABEL`, left of Add media) opens (page-parity ticket 10);
 *  - (ticket 10) with no Creator, the page is the clone's empty frame: the rail's sort row, the toolbar disabled and
 *    an empty state, with the Creator select off and reading "No creators";
 *  - (ticket 57) the header is a bar with a bottom rule over the flush rail and grid; the Creator selector is a
 *    select; the row menu's trigger is the 20px icon; the move opens the "Add to category" modal; per-folder
 *    statistics and the vault-wide totals show as Not wired; the loading spinner, our no-Creator line and Back;
 *  - switching the Creator selector remounts the grid and the import card, and the next Vault read
 *    carries the new Creator's `account_id`; a dropped session is said and nothing is written;
 *  - folder create, rename, delete and reorder reach the same Vault routes as before;
 *  - (ticket 37) the toolbar's search, sort box and popover, media tabs and tools appear in the capture's order with
 *    its labels; each type chip, the search, the sort directions, Refresh and Select all reach the read or write the
 *    grid used before; every Not wired control is disabled, titled "not wired" and calls nothing; the toolbar's and
 *    the selection bar's own extras carry `EXTRA_LABEL`;
 *  - (the owner's 2026-10-18 ruling on #12) the Add media tour and the upload guide (#118, #119) show once, from
 *    the bundle's `localStorage["vaultProOnboarding"]`, with its text and its Got it / Next / Start upload.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  // Unstubbed verbs stay the REAL ones, so a new call fails loudly instead of reaching a live relay.
  return {
    ...mod,
    relay: {
      ...mod.relay,
      get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(),
      delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});
// An owner session, so `useAccounts` reads `/admin/accounts` through the mocked relay.
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/UserContext")>()),
  useUser: () => ({ user: { user_id: "owner-1" } }),
}));
vi.mock("@/contexts/ChatterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => ({ chatter: null }),
}));

import VaultProPage from "@/components/growth/VaultProPage";
import { relay } from "@/lib/relay";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPatch = relay.patch as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

/* ── the Layout capture, read from disk ─────────────────────────────────── */

const CAPTURE = readFileSync(
  resolve(__dirname, "../../../docs/infloww-layouts/growth-vault-pro.md"),
  "utf8",
);

/** The capture's Items row for `id`, which must exist and must hold `label`. */
function expectInCapture(id: string, label: string) {
  const row = CAPTURE.split("\n").find((l) => l.startsWith(`| ${id} |`));
  expect(row, `capture row ${id}`).toBeTruthy();
  expect(row, `capture row ${id} holds "${label}"`).toContain(label);
}

/** a precedes b in document order. */
function expectBefore(a: Element, b: Element) {
  expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

/* ── fixtures: two placeholder Creators, two folders ────────────────────── */

const A = { id: "1000001", nickname: "Creator A", has_session: true };
const B = { id: "1000002", nickname: "Creator B", has_session: true };
const FOLDERS = [
  { id: 11, name: "Folder one", type: "custom", hasMedia: true, photosCount: 3, videosCount: 1, gifsCount: 0, audiosCount: 0 },
  { id: 12, name: "Folder two", type: "custom", hasMedia: false, photosCount: 0, videosCount: 0, gifsCount: 0, audiosCount: 0 },
];

let roster: Array<typeof A> = [A, B];

beforeEach(() => {
  roster = [A, B];
  window.localStorage.clear();
  // The guided tours show once per browser (the bundle's "vaultProOnboarding" store); every test but the tours'
  // own starts with both seen, so no tour overlays the page under test.
  window.localStorage.setItem("vaultProOnboarding", JSON.stringify({ batchUploadEntry: "1", uploadPageStep: "1" }));
  for (const m of [relayGet, relayPost, relayPut, relayPatch, relayDelete]) m.mockReset();
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p === "/admin/accounts") return Promise.resolve({ accounts: roster, active_account_id: null });
    if (p.startsWith("/api/of/v2/vault/lists")) return Promise.resolve({ list: FOLDERS, hasMore: false });
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
});

/** Mount the page and wait for the rail's folders, which only render once a Creator is adopted. */
async function mount() {
  renderWithProviders(<VaultProPage />);
  await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());
}

/** The header's one Extras overflow button. */
function extrasButton(): HTMLElement {
  return screen.getByRole("button", { name: EXTRAS_OVERFLOW_LABEL });
}

/** The Extras drawer, opened from the header's overflow button if it is not open yet. */
function overflow(): HTMLElement {
  const open = screen.queryByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL });
  if (open) return open;
  fireEvent.click(extrasButton());
  return screen.getByRole("dialog", { name: EXTRAS_OVERFLOW_LABEL });
}

/** Open a listbox select (`IfSelect`, `IfCreatorSelect`) and return its options. */
function openOptions(combobox: HTMLElement): HTMLElement[] {
  if (combobox.getAttribute("aria-expanded") !== "true") fireEvent.click(combobox);
  const list = document.getElementById(combobox.getAttribute("aria-controls") ?? "") as HTMLElement;
  return within(list).getAllByRole("option");
}

/** The rail: the element holding the sort label and the "All media" row. */
function rail(): HTMLElement {
  return screen.getAllByText("All media").map((el) => el.closest("aside")).find(Boolean) as HTMLElement;
}

describe("Vault Pro header and rail, in the capture's order", () => {
  it("shows the header items in the capture's order, each label in the capture next to its ID", async () => {
    await mount();
    const header = [
      { id: "growth-vault-pro#3", label: "Vault Pro", el: screen.getByRole("heading", { level: 1, name: "Vault Pro" }) },
      { id: "growth-vault-pro#6", label: "creator selector", el: screen.getByRole("combobox", { name: "Creator" }) },
      { id: "growth-vault-pro#7", label: "Learn", el: screen.getByRole("link", { name: "Learn" }) },
      { id: "growth-vault-pro#10", label: "Add media", el: screen.getByRole("button", { name: "Add media" }) },
    ];
    for (const h of header) expectInCapture(h.id, h.label);
    for (let i = 1; i < header.length; i++) expectBefore(header[i - 1].el, header[i].el);
  });

  it("lays the header out as a bar with a bottom rule, with the rail and grid flush beneath it (#15, #16)", async () => {
    await mount();
    const header = screen.getByRole("heading", { level: 1, name: "Vault Pro" }).closest("header") as HTMLElement;
    expect(header.className).toContain("border-b");
    // The two-pane row is the rail's parent: no box of its own around the rail and the grid.
    const pane = rail().parentElement as HTMLElement;
    expect(pane.className).not.toMatch(/\brounded|\bborder\b/);
    expectBefore(header, pane);
    // No Extras strip between them any more: the rail starts under the header rule, and the one overflow is a
    // header button, left of Add media.
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
    // "Default" at first, as the capture has it; reading back OF's stored sort is Not wired, and the title says so.
    expect(sort.getAttribute("title")).toMatch(/not wired$/);
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
    // The grid's toolbar sits after the rail.
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

  it("shows per-folder statistics (#33) and the vault-wide totals (#58) as Not wired", async () => {
    await mount();
    expectInCapture("growth-vault-pro#33", "send count");
    for (const name of ["Folder one", "Folder two"]) {
      const row = within(rail()).getByText(name).closest("[role=button]") as HTMLElement;
      const stats = within(row).getByLabelText("Statistics");
      expect(stats).toHaveAttribute("title", "not wired");
      expect(stats.textContent).not.toMatch(/\d/);
    }
    const all = within(rail()).getByText("All media").closest("button") as HTMLElement;
    expect(within(all).getByTitle("not wired").textContent).not.toMatch(/\d/);
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
    // The trigger is the bundle's 20px icon (`STpMessageMore,{size:20`, index.9f50f370.js @6802706), not a glyph.
    expect(more.textContent).toBe("");
    expect(more.querySelector("svg")).toHaveAttribute("width", "20");
    fireEvent.click(more);
    const items =within(screen.getByRole("menu")).getAllByRole("menuitem").map((el) => el.textContent);
    expectInCapture("growth-vault-pro#34", "Rename / Delete");
    expect(items).toEqual(["Rename", "Delete"]);
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

describe("Add media", () => {
  it("reveals the import card over the page, and the back arrow hides it again", async () => {
    await mount();
    const card = await screen.findByText(/Import to/);
    expect(card).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Add media" }));
    expect(card).toBeVisible();
    // Back keeps the picked files (the card stays mounted), so it never asks: ours, labelled.
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
    // The bundle marks a tour seen the moment it shows (`setVaultProOnboardingItemShow`), so a reload never repeats it.
    expect(seen()).toEqual({ batchUploadEntry: "1" });
    // One step: no Next and no Skip, only the bundle's "Got it".
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
    renderWithProviders(<VaultProPage />);
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
    // Titles from the capture (#118), step 2's text from the capture (#119), steps 1 and 3's text from the bundle.
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
    // Shown once: closing and reopening the card does not bring it back.
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
    // Closed by default: one click away, never in the page's way.
    expect(screen.queryByRole("button", { name: "Collect all" })).toBeNull();
    expect(extrasButton()).toHaveAttribute("title", EXTRAS_OVERFLOW_LABEL);
    const box = overflow();
    expect(within(box).getByRole("heading", { name: EXTRAS_OVERFLOW_LABEL })).toHaveAttribute("title", EXTRA_LABEL);
    // Collect, AI describe and its prompt picker, harvest, duplicates, the pack picker, AI folders and disputes.
    const tools = [
      screen.getByRole("button", { name: "Collect all" }),
      screen.getByRole("button", { name: /^Describe all/ }),
      screen.getByTitle("Describe prompt variant"),
      screen.getByRole("button", { name: /^Harvest OF/ }),
      screen.getByRole("button", { name: "Duplicates" }),
      screen.getByRole("button", { name: "Feet pack" }),
      screen.getByRole("button", { name: "Build AI folders" }),
      screen.getByRole("button", { name: "Fix disagreements" }),
    ];
    for (const t of tools) expect(box.contains(t)).toBe(true);
    // The drawer's × closes it; so does Escape, and the button again.
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
  it("is a select showing the picked Creator, with the house chips gone (#6)", async () => {
    await mount();
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
    // State in each of the two, so a re-render that kept it would show.
    fireEvent.click(within(rail()).getByRole("button", { name: "Search" }));
    expect(within(rail()).getByPlaceholderText("Search")).toBeTruthy();
    const gridBefore = rail();
    const cardBefore = screen.getByText(/Import to/).closest("section");
    relayGet.mockClear();

    fireEvent.click(openOptions(screen.getByRole("combobox", { name: "Creator" }))[1]);
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());

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

  it("says a dropped session and writes nothing", async () => {
    // A is selected and live; then its session drops and the account list is read again.
    const { queryClient } = renderWithProviders(<VaultProPage />);
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());
    roster = [{ ...A, has_session: false }, B];
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ["accounts"] }); });
    expect(await screen.findByText(/session has dropped/)).toBeTruthy();
    // Said, not acted on: the page stays on A, and the select still shows A.
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent(/Creator A$/);
    expect(within(rail()).getByText("Folder one")).toBeTruthy();
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    for (const m of [relayPost, relayPut, relayPatch, relayDelete]) expect(m).not.toHaveBeenCalled();
  });

  it("with no session at all draws the empty frame, offers no Add media and writes nothing", async () => {
    roster = [];
    renderWithProviders(<VaultProPage />);
    const line = await screen.findByText("No model accounts with a live session.");
    // Ours, in place of the capture's not-a-creator text (#13), in the grid's empty state.
    expect(line).toHaveAttribute("title", EXTRA_LABEL);
    expect(line.closest("div")?.querySelector("[data-empty-art='creator']")).toBeTruthy();
    // The frame: the rail's sort row and an empty All media row, then the toolbar, every control off.
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
    // The Creator select is always shown: off, reading "No creators".
    const creator = screen.getByRole("combobox", { name: "Creator" });
    expect(creator).toBeDisabled();
    expect(creator).toHaveTextContent("No creators");
    expect(extrasButton()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add media" })).toBeDisabled();
    for (const m of [relayPost, relayPut, relayPatch, relayDelete]) expect(m).not.toHaveBeenCalled();
  });
});

describe("the page's loading state", () => {
  it("is the capture's spinner (#13), not a line of text", async () => {
    relayGet.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<VaultProPage />);
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
    // The bundle's media wipe is shown, Not wired (house marker).
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
    // As the bundle: the drop moves the row, and nothing is written until the check.
    expectBefore(within(rail()).getByText("Folder two"), within(rail()).getByText("Folder one"));
    expect(relayPost).not.toHaveBeenCalled();
    fireEvent.click(within(rail()).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/of-folders/sort",
      { account_id: A.id, sort: undefined, order: undefined, custom_order: [12, 11] },
      { accountId: A.id },
    ));
    // A saved custom order is OF's "Custom" sort, so the label says so.
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
    const { queryClient } = renderWithProviders(<VaultProPage />);
    await waitFor(() => expect(within(rail()).getByText("Folder one")).toBeTruthy());

    const describe = await within(overflow()).findByRole("button", { name: /^Describe all/ });
    await waitFor(() => expect(describe).toBeEnabled());
    fireEvent.click(describe);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/describe-all", expect.objectContaining({ account_id: A.id }), { accountId: A.id },
    ));
    await within(overflow()).findByRole("button", { name: /^Describing/ });

    // The sweep ends with two items flagged for a human.
    sweep = { running: false, progress: { done: 5, total: 5, needs_review: 2 } };
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["vault-sweep", "describe-all", A.id] });
    });
    const check = await screen.findByRole("button", { name: "Check them" });
    expect(overflow()).toContainElement(check);
  });
});

/* ── ticket 37: the toolbar (#38 to #77) ────────────────────────────────── */

/** The grid's section: the element holding the toolbar's search. */
function grid(): HTMLElement {
  return screen.getByPlaceholderText(/^Search media by/).closest("section") as HTMLElement;
}

/** The `/api/of/v2/vault/media` reads made so far, their query strings parsed. */
function mediaReads(): URLSearchParams[] {
  return relayGet.mock.calls
    .map(([p]) => String(p))
    .filter((p) => p.startsWith("/api/of/v2/vault/media?"))
    .map((p) => new URLSearchParams(p.split("?")[1]));
}

/** Two audio files (no still, so no image request), for the tools that need something loaded. */
const MEDIA = [
  { id: 501, type: "audio", files: {} },
  { id: 502, type: "audio", files: {} },
];
function withMedia() {
  // jsdom has no IntersectionObserver; the grid's infinite-load sentinel needs one once files render.
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  const base = relayGet.getMockImplementation()!;
  relayGet.mockImplementation((path: string, ctx?: unknown) =>
    String(path).startsWith("/api/of/v2/vault/media")
      ? Promise.resolve({ list: MEDIA, hasMore: false })
      : base(path, ctx));
}
/** Mount with MEDIA loaded in the grid. */
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
    // What the page opens on: all time, Recent, Descending.
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
    // Recent, Descending: newest first, the read's default.
    expect(mediaReads()[0].get("sort")).toBe("desc");
    fireEvent.click(within(grid()).getByRole("button", { name: "Recent" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Ascending" }));
    await waitFor(() => expect(mediaReads().at(-1)?.get("sort")).toBe("asc"));
    // The box keeps the field's name; the direction is in its title.
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
    await mount();
    expectInCapture("growth-vault-pro#58", "a type with no files is disabled");
    // All media: no per-type count, so every chip is on.
    for (const l of ["Photo", "Video", "GIF", "Audio"]) expect(within(grid()).getByRole("button", { name: l })).toBeEnabled();
    // Folder one: 3 photos, 1 video, no GIF, no audio.
    fireEvent.click(within(rail()).getByText("Folder one"));
    await waitFor(() => expect(within(grid()).getByRole("button", { name: "GIF" })).toBeDisabled());
    expect(within(grid()).getByRole("button", { name: "Audio" })).toBeDisabled();
    expect(within(grid()).getByRole("button", { name: "Photo" })).toBeEnabled();
    expect(within(grid()).getByRole("button", { name: "Video" })).toBeEnabled();
  });

  it("Select all selects every loaded file and opens the capture's selection bar, whose move adds them to a folder", async () => {
    await mountWithMedia();
    fireEvent.click(within(grid()).getByRole("button", { name: "Select all" }));
    expectInCapture("growth-vault-pro#74", "\"Selected\" and the count");
    expectInCapture("growth-vault-pro#77", "Add to category");
    const move = within(grid()).getByRole("button", { name: "Add to category" });
    const bar = move.parentElement as HTMLElement;
    // "Selected", the count, then move and delete.
    const selected = within(bar).getByText("Selected");
    expect(selected.nextElementSibling?.textContent).toBe("2");
    expectBefore(selected, move);
    expectBefore(move, within(bar).getByRole("button", { name: "Delete" }));
    // The move icon opens the capture's "Add to category" modal, 480px, one row per folder.
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
    // Listbox options with no read: the search type's Note and Hashtag, then (below) the video lengths.
    const offOptions: HTMLElement[] = [];
    const searchType = within(g).getByRole("combobox", { name: "Search type" });
    offOptions.push(...openOptions(searchType).slice(1));
    // The sort popover's unread options and the hide switch.
    fireEvent.click(within(g).getByRole("button", { name: "Recent" }));
    for (const l of ["Go to date", "Most liked", "Highest tips", "Send count", "Unlock count", "Revenue"]) {
      notWired.push(within(g).getByRole("menuitemradio", { name: l }));
    }
    notWired.push(within(g).getByRole("menuitemcheckbox", { name: SWITCH }));
    // The table view; the video length picker on the Video tab.
    notWired.push(within(g).getByRole("button", { name: "Table view" }));
    fireEvent.click(within(g).getByRole("button", { name: "Video" }));
    expectInCapture("growth-vault-pro#62", "\"Video length:\"");
    expect(within(g).getByText("Video length:")).toBeTruthy();
    offOptions.push(...openOptions(within(g).getByRole("combobox", { name: "Video length" })).slice(1));
    // The selection bar's delete.
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
    // In a folder, each tile's "#" order box (ours: the folder's manual order).
    fireEvent.click(within(rail()).getByText("Folder one"));
    const boxes = await within(grid()).findAllByPlaceholderText("#");
    expect(boxes).toHaveLength(2);
    for (const b of boxes) expect(b.getAttribute("title")).toMatch(new RegExp(`^${EXTRA_LABEL}\\n`));
  });
});
