/**
 * Growth > Scripts, the page component (docs/spec/infloww-parity-round-2/phase-02-growth-pages.md, Testing
 * Decisions, Seam 1; ticket 35). Rendered with `@/lib/relay` mocked and a fresh QueryClient over two placeholder
 * Creators; Creator A has two saved replies, Creator B none. What is pinned:
 *
 *  - the header, the More menu, the toolbar, the list control and a script row appear in the Layout capture's
 *    order, and every label transcribed here is read back from the capture on disk next to its Item ID;
 *  - the saved replies list as scripts, and create, edit and delete reach the same `/admin/saved-replies` routes as
 *    the Templates tab;
 *  - every Not wired control is disabled, titled "not wired" and calls nothing; a Not wired cell shows "—";
 *  - no welcome editor renders (ticket 43 moved it to Smart Messages); every extra carries `EXTRA_LABEL`;
 *  - switching the creator control makes the next saved-reply read and write carry the other Creator's id.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: {
      ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});
// The Vault picker is a portal modal with its own reads; closed it renders nothing, so it is stubbed out here.
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [
    { id: "acc-a", nickname: "Creator A", has_session: true },
    { id: "acc-b", nickname: "Creator B", has_session: true },
  ],
}));

import ScriptsPage from "@/components/growth/ScriptsPage";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;
const patch = relay.patch as unknown as Mock;
const del = relay.delete as unknown as Mock;
const uploadFile = relay.uploadFile as unknown as Mock;

/* ── the Layout capture, read from disk ─────────────────────────────────── */

const CAPTURE = readFileSync(
  resolve(__dirname, "../../../docs/infloww-layouts/growth-scripts.md"),
  "utf8",
);

/** The capture's Items row for `id`, which must exist and must hold `label`. */
function expectInCapture(id: string, label: string) {
  const row = CAPTURE.split("\n").find((l) => l.startsWith(`| ${id} |`));
  expect(row, `capture row ${id}`).toBeTruthy();
  expect(row, `capture row ${id} holds "${label}"`).toContain(label);
}

/** Each element follows the one before it in document order. */
function expectInOrder(els: Element[]) {
  for (let i = 1; i < els.length; i++) {
    expect(
      els[i - 1].compareDocumentPosition(els[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      `element ${i} follows element ${i - 1}`,
    ).toBeTruthy();
  }
}

/* ── fixtures ───────────────────────────────────────────────────────────── */

const TEMPLATES = "/api/of/v2/messages/templates";
const SETTINGS = "/api/of/v2/users/me/settings";
const LIST_A = "/admin/saved-replies?account_id=acc-a";
const LIST_B = "/admin/saved-replies?account_id=acc-b";

const REPLIES = [
  {
    id: 1, account_id: "acc-a", title: "Greeting", text: "Hey there", price: 0, locked_text: false,
    media: [{ id: 501, type: "photo", files: null }], tagged_users: [9001, 9002],
  },
  { id: 2, account_id: "acc-a", title: "Unlock", text: "Unlock this one", price: 12.5, locked_text: true, media: [] },
];

function serve() {
  get.mockImplementation((path: string, ctx?: { accountId?: string }) => {
    if (path === TEMPLATES) return Promise.resolve([]);
    if (path === SETTINGS) return Promise.resolve({ replyOnSubscribe: ctx?.accountId === "acc-a" });
    if (path === LIST_A) return Promise.resolve({ list: REPLIES });
    if (path.startsWith("/admin/saved-replies")) return Promise.resolve({ list: [] });
    return Promise.reject(new Error(`unmocked GET ${path}`));
  });
  post.mockResolvedValue({});
  put.mockResolvedValue({});
  patch.mockResolvedValue({});
  del.mockResolvedValue({});
}

beforeEach(() => {
  vi.clearAllMocks();
  serve();
  vi.stubGlobal("confirm", () => true);
  // Desktop width: the phone-only scroll-into-view of an opened editor stays off.
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function mount() {
  renderWithProviders(<ScriptsPage />);
  await screen.findByText("Hey there");
}

const rows = () => screen.getAllByRole("listitem").filter((li) => li.closest("[aria-label='Scripts list']"));
const textbox = () => screen.getByPlaceholderText("Enter your message...");
const nameBox = () => screen.getByPlaceholderText("Enter name");
const openMore = () => fireEvent.click(screen.getByRole("button", { name: "More" }));
const writes = () => post.mock.calls.length + put.mock.calls.length + patch.mock.calls.length + del.mock.calls.length;
/** Opens the select named `name` and picks `option` from its listbox. */
function pick(name: string, option: string) {
  fireEvent.click(screen.getByRole("combobox", { name }));
  fireEvent.click(within(screen.getByRole("listbox", { name })).getByRole("option", { name: new RegExp(`${option}$`) }));
}
/** The creator column left of the page (`CreatorRail`, Smart lists'), and its row for a Creator. */
const column = () => screen.getByTestId("of-creator-column");
const creatorRow = (name: string) => within(column()).getByRole("button", { name: new RegExp(name) });
const pickCreator = (name: string) => fireEvent.click(creatorRow(name));

/* ── the capture's structure, in order ──────────────────────────────────── */

describe("Scripts follows the capture's order", () => {
  it("shows the header: title, Learn, Share, More; the creator selector is the column left of the page", async () => {
    await mount();
    const header = [
      { id: "growth-scripts#3", label: "Scripts", el: screen.getByRole("heading", { level: 1, name: "Scripts" }) },
      { id: "growth-scripts#8", label: "Learn", el: screen.getByRole("button", { name: "Learn" }) },
      { id: "growth-scripts#11", label: "Share", el: screen.getByRole("button", { name: "Share" }) },
      { id: "growth-scripts#12", label: "More menu", el: screen.getByRole("button", { name: "More" }) },
    ];
    for (const h of header) expectInCapture(h.id, h.label);
    expectInOrder(header.map((h) => h.el));
    // The capture's creator selector (#6) is the creator column now: not in the header, under it, left of the
    // toolbar and list, showing the open Creator.
    expectInCapture("growth-scripts#6", "creator selector");
    const banner = screen.getByRole("banner");
    expect(within(banner).queryByRole("combobox", { name: "Creator" })).toBeNull();
    expect(within(banner).queryByTestId("of-creator-column")).toBeNull();
    expectInOrder([banner, column()]);
    expect(column().nextElementSibling!.contains(screen.getByRole("tab", { name: "Sequence" }))).toBe(true);
    expect(creatorRow("Creator A")).toHaveAttribute("aria-current", "true");
    expect(creatorRow("Creator B")).not.toHaveAttribute("aria-current");
    // Learn carries the book icon, in T1 ink.
    const learn = screen.getByRole("button", { name: "Learn" });
    expect(learn.querySelector("svg")).toHaveClass("lucide-book-open");
    expect(learn).toHaveClass("text-fg");
    expect(learn).not.toHaveClass("text-fg-dim");
  });

  it("draws the inactive tab in T1, not dimmed, and the Sequence tab with the flow icon", async () => {
    await mount();
    const seq = screen.getByRole("tab", { name: "Sequence" });
    expect(seq).toHaveAttribute("aria-selected", "false");
    expect(seq).toHaveClass("text-fg");
    expect(seq).not.toHaveClass("text-fg-dim");
    expect(seq.querySelector("svg")).toHaveClass("lucide-workflow");
  });

  it("closes the More menu on Escape, moves between items with the arrows, and puts focus back on More", async () => {
    await mount();
    const more = screen.getByRole("button", { name: "More" });
    fireEvent.click(more);
    const menu = screen.getByRole("menu", { name: "More" });
    fireEvent.keyDown(more, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Add script" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Create new" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    // Wraps to the last enabled item (Use template and Import from tag are Not wired).
    expect(within(menu).getByRole("menuitem", { name: "From other creators" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(more).toHaveFocus();
  });

  it("draws the More trigger as the bundle shot does, a filled accent circle with a plus (#12)", async () => {
    await mount();
    const more = screen.getByRole("button", { name: "More" });
    expect(more).toHaveClass("rounded-full", "bg-accent");
    expect(more.querySelector("svg")).not.toBeNull();
  });

  it("runs the tab bar and the list flush across the page, in no bordered card", async () => {
    await mount();
    expect(screen.getByRole("tablist", { name: "Scripts" }).closest(".rounded-lg")).toBeNull();
    expect(screen.getByRole("list", { name: "Scripts list" }).closest(".rounded-lg")).toBeNull();
  });

  it("opens the More menu on its items and dividers, in the capture's order", async () => {
    await mount();
    openMore();
    const menu = screen.getByRole("menu");
    const items = [
      ["growth-scripts#13", "Add script"],
      ["growth-scripts#14", "Add sequence"],
      ["growth-scripts#14", "Create new"],
      ["growth-scripts#14", "Use template"],
      ["growth-scripts#14", "Import from tag"],
      ["growth-scripts#15", "Add tag"],
      ["growth-scripts#16", "Import"],
      ["growth-scripts#16", "From Excel"],
      ["growth-scripts#16", "From other creators"],
    ];
    for (const [id, label] of items) expectInCapture(id, label);
    const els = items.map(([, label]) => within(menu).getByText(label, { exact: true }));
    expectInOrder(els);
    // #17: a divider after Add script and one before Import.
    const seps = within(menu).getAllByRole("separator");
    expect(seps).toHaveLength(2);
    expectInOrder([els[0], seps[0], els[1]]);
    expectInOrder([els[5], seps[1], els[6]]);
  });

  it("shows the toolbar: Tag, Sequence, the search icon, Manage scripts; then the list control and the rows", async () => {
    await mount();
    const toolbar = [
      { id: "growth-scripts#21", label: "Tag", el: screen.getByRole("tab", { name: "Tag" }) },
      { id: "growth-scripts#22", label: "Sequence", el: screen.getByRole("tab", { name: "Sequence" }) },
      { id: "growth-scripts#26", label: "search", el: screen.getByRole("button", { name: "Search" }) },
      { id: "growth-scripts#28", label: "Manage scripts", el: screen.getByRole("button", { name: "Manage scripts" }) },
      { id: "growth-scripts#34", label: "Expand scripts", el: screen.getByRole("switch", { name: "Expand scripts" }) },
    ];
    for (const t of toolbar) expectInCapture(t.id, t.label);
    expectInOrder([...toolbar.map((t) => t.el), rows()[0]]);
    // Opens on Tag (#23), on its "All scripts" entry.
    expectInCapture("growth-scripts#23", "ScriptType.Tags");
    expect(screen.getByRole("tab", { name: "Tag" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /All scripts/ })).toHaveAttribute("aria-current", "true");
    // Manage scripts swaps the tabs for a back arrow and its title (#31), and sorts (#33).
    fireEvent.click(screen.getByRole("button", { name: "Manage scripts" }));
    expectInCapture("growth-scripts#31", "back arrow");
    expect(screen.queryByRole("tab", { name: "Tag" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Manage scripts" })).toBeInTheDocument();
    expectInCapture("growth-scripts#33", "Recent");
    const options = (name: string) => {
      fireEvent.click(screen.getByRole("combobox", { name }));
      const shown = within(screen.getByRole("listbox", { name })).getAllByRole("option").map((o) => o.textContent);
      fireEvent.click(screen.getByRole("combobox", { name }));
      return shown;
    };
    expect(options("Sort by")).toEqual(["Recent", "Name"]);
    expect(options("Sort order")).toEqual(["Ascending", "Descending"]);
    // Starts on Recent and Descending (#33).
    expect(screen.getByRole("combobox", { name: "Sort by" })).toHaveTextContent("Recent");
    expect(screen.getByRole("combobox", { name: "Sort order" })).toHaveTextContent("Descending");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("tab", { name: "Tag" })).toHaveAttribute("aria-selected", "true");
  });

  it("lays a script row out as name, tags, text, price and stats, then edit, share, delete", async () => {
    await mount();
    const row = rows()[1];
    expectInCapture("growth-scripts#38", "name cell");
    expectInCapture("growth-scripts#41", "tags");
    expectInCapture("growth-scripts#44", "$ ");
    expectInCapture("growth-scripts#47", "edit");
    const cells = [
      within(row).getByText("Unlock"),
      within(row).getByLabelText("Tags"),
      within(row).getByText("Unlock this one"),
      within(row).getByText("$12.50"),
      within(row).getByLabelText("Stats"),
      within(row).getByRole("button", { name: "Edit" }),
      within(row).getByRole("button", { name: "Share script" }),
      within(row).getByRole("button", { name: "Delete" }),
    ];
    expectInOrder(cells);
  });

  it("shows the sequence empty panel for a Creator with no scripts on Tag, and No data under Manage scripts", async () => {
    await mount();
    expectInCapture("growth-scripts#62", "Try out our new sequence feature");
    expectInCapture("growth-scripts#50", "No data");
    pickCreator("Creator B");
    expect(await screen.findByText("Try out our new sequence feature")).toBeInTheDocument();
    expect(screen.queryByText("Hey there")).toBeNull();
    // Three borderless cards, each with its arrow under the label.
    const cards = ["Create new sequence", "Use a template", "Import from tag"]
      .map((name) => screen.getByRole("button", { name }));
    for (const card of cards) {
      expect(card.querySelector("[data-arrow]")).not.toBeNull();
      expect(card).not.toHaveClass("border");
    }
    fireEvent.click(screen.getByRole("button", { name: "Manage scripts" }));
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});

/* ── saved replies are the scripts ──────────────────────────────────────── */

describe("the saved replies are the scripts", () => {
  it("lists each saved reply with its title, text, price, media and tagged Creators", async () => {
    await mount();
    const [first, second] = rows();
    expect(within(first).getByText("Greeting")).toBeInTheDocument();
    expect(within(first).getByText("Hey there")).toBeInTheDocument();
    // Media: one tile per attached item (a placeholder with its type, since the fixture has no thumbnail).
    expect(within(first).getByText("photo")).toBeInTheDocument();
    expect(within(first).getByLabelText("Tagged Creators: 2")).toBeInTheDocument();
    expect(within(first).queryByText(/^\$\d/)).toBeNull();
    expect(within(second).getByText("Unlock this one")).toBeInTheDocument();
    expect(within(second).getByText("$12.50")).toBeInTheDocument();
    expect(get.mock.calls.map(([p]) => p)).toContain(LIST_A);
  });

  it("Add script opens the saved-reply editor, whose OK posts to the saved-replies route", async () => {
    await mount();
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Add script" }));
    expect(screen.getByRole("dialog", { name: "Add script" })).toBeInTheDocument();
    fireEvent.change(nameBox(), { target: { value: "New one" } });
    fireEvent.change(textbox(), { target: { value: "A new one" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe(LIST_A);
    expect(post.mock.calls[0][1]).toMatchObject({ title: "New one", text: "A new one", price: 0 });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a row's edit opens the editor on that reply, whose OK puts to its route", async () => {
    await mount();
    fireEvent.click(within(rows()[1]).getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("dialog", { name: "Edit script" })).toBeInTheDocument();
    expect(nameBox()).toHaveValue("Unlock");
    expect(textbox()).toHaveValue("Unlock this one");
    fireEvent.change(textbox(), { target: { value: "Unlock it now" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][0]).toBe("/admin/saved-replies/2");
    expect(put.mock.calls[0][1]).toMatchObject({ text: "Unlock it now", price: 12.5, locked_text: true });
  });

  it("a row's delete calls the saved-replies delete route", async () => {
    await mount();
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/saved-replies/1"));
  });

  it("Expand scripts lifts the two-line clamp on the script text", async () => {
    await mount();
    expectInCapture("growth-scripts#42", "ellipsis:{rows:2");
    const text = () => within(rows()[0]).getByText("Hey there");
    expect(text()).toHaveClass("line-clamp-2");
    fireEvent.click(screen.getByRole("switch", { name: "Expand scripts" }));
    expect(text()).not.toHaveClass("line-clamp-2");
  });
});

describe("each row expands on its own (#42)", () => {
  it("a row's expander lifts that row's clamp only, and the Expand scripts switch still opens every row", async () => {
    await mount();
    expectInCapture("growth-scripts#42", "expandable");
    const text = (i: number) => within(rows()[i]).getByText(i === 0 ? "Hey there" : "Unlock this one");
    const toggle = within(rows()[0]).getByRole("button", { name: "Expand script" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(text(0)).not.toHaveClass("line-clamp-2");
    expect(text(1)).toHaveClass("line-clamp-2");
    fireEvent.click(toggle);
    expect(text(0)).toHaveClass("line-clamp-2");
    fireEvent.click(screen.getByRole("switch", { name: "Expand scripts" }));
    expect(text(0)).not.toHaveClass("line-clamp-2");
    expect(text(1)).not.toHaveClass("line-clamp-2");
  });
});

/* ── the script editor modal ────────────────────────────────────────────── */

describe("the script editor is the capture's 535px modal (#72 to #79)", () => {
  async function openAdd() {
    await mount();
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Add script" }));
    return screen.getByRole("dialog", { name: "Add script" });
  }

  it("is a 535px dialog titled Add script, with Name, Tags, Text, Message price, Internal notes in the capture's order", async () => {
    const dialog = await openAdd();
    expectInCapture("growth-scripts#72", "535px");
    // IfModal's antd box (jsdom drops its `min(535px, …)` width, so the source pins the 535).
    expect(dialog).toHaveClass("rounded-[10px]");
    expect(readFileSync(resolve(__dirname, "ScriptsPage.tsx"), "utf8")).toMatch(/<IfModal title=\{title\} width=\{535\}/);
    for (const [id, label] of [
      ["growth-scripts#73", "Name"], ["growth-scripts#74", "Tags"], ["growth-scripts#75", "Text"],
      ["growth-scripts#76", "Message price"], ["growth-scripts#79", "Internal notes"],
    ]) expectInCapture(id, label);
    expectInOrder([
      within(dialog).getByLabelText(/^Name/),
      within(dialog).getByLabelText("Tags"),
      within(dialog).getByLabelText(/^Text/),
      within(dialog).getByLabelText("Message price"),
      within(dialog).getByLabelText("Internal notes"),
    ]);
  });

  it("requires Name at 64 characters and Text at 6500, and OK waits for both", async () => {
    const dialog = await openAdd();
    expectInCapture("growth-scripts#73", "maxLength:64");
    expectInCapture("growth-scripts#75", "Yn=6500");
    expect(nameBox()).toHaveAttribute("maxLength", "64");
    expect(nameBox()).toBeRequired();
    expect(textbox()).toHaveAttribute("maxLength", "6500");
    expect(textbox()).toBeRequired();
    const save = within(dialog).getByRole("button", { name: "OK" });
    fireEvent.change(textbox(), { target: { value: "Body only" } });
    expect(save).toBeDisabled();
    fireEvent.change(nameBox(), { target: { value: "Named" } });
    expect(save).toBeEnabled();
  });

  it("holds a priced script to the $3 minimum", async () => {
    const dialog = await openAdd();
    expectInCapture("growth-scripts#77", "Minimum $3 USD");
    fireEvent.change(nameBox(), { target: { value: "Named" } });
    fireEvent.change(textbox(), { target: { value: "Pay me" } });
    const price = within(dialog).getByLabelText("Message price");
    fireEvent.change(price, { target: { value: "2" } });
    expect(within(dialog).getByText("Minimum $3 USD")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "OK" })).toBeDisabled();
    fireEvent.change(price, { target: { value: "3" } });
    expect(within(dialog).queryByText("Minimum $3 USD")).toBeNull();
    expect(within(dialog).getByRole("button", { name: "OK" })).toBeEnabled();
  });

  it("saves Tags, Internal notes and the Sequence and Step with the script", async () => {
    const dialog = await openAdd();
    expectInCapture("growth-scripts#74", "Select or create a tag");
    expectInCapture("growth-scripts#79", "maxLength:256");
    fireEvent.change(nameBox(), { target: { value: "ask name" } });
    fireEvent.change(textbox(), { target: { value: "what's your name?" } });
    const tags = within(dialog).getByLabelText("Tags");
    expect(tags).toHaveAttribute("maxLength", "32");
    fireEvent.change(tags, { target: { value: "Opener" } });
    fireEvent.keyDown(tags, { key: "Enter" });
    fireEvent.change(tags, { target: { value: "VIP" } });
    fireEvent.keyDown(tags, { key: "," });
    expect(within(dialog).getByRole("button", { name: "Remove tag VIP" })).toBeInTheDocument();
    const notes = within(dialog).getByLabelText("Internal notes");
    expect(notes).toHaveAttribute("maxLength", "256");
    fireEvent.change(notes, { target: { value: "only after 9pm" } });
    // A sequence without a step cannot be saved: the chat's next-step suggestion needs both.
    fireEvent.change(within(dialog).getByLabelText("Sequence"), { target: { value: "New Sub" } });
    expect(within(dialog).getByText("Enter a step")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "OK" })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Step"), { target: { value: "2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1]).toMatchObject({
      title: "ask name", tags: ["Opener", "VIP"], notes: "only after 9pm", script_id: "New Sub", script_step: 2,
    });
  });

  it("closes on Cancel without a write", async () => {
    const dialog = await openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toBe(0);
  });

  it("closes on Escape and returns focus to More, the menu that opened Add script", async () => {
    await openAdd();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "More" })).toHaveFocus();
    expect(writes()).toBe(0);
  });
});

/* ── the saved-reply editor's own controls, inside the script modal ─────── */

describe("the saved-reply editor's own controls follow the bundle's script modal", () => {
  async function openEdit(i: number) {
    await mount();
    fireEvent.click(within(rows()[i]).getByRole("button", { name: "Edit" }));
    return screen.getByRole("dialog", { name: "Edit script" });
  }

  it("keeps the emoji row under Text, as the bundle's Text field carries one, with no label", async () => {
    const dialog = await openEdit(0);
    const picker = within(dialog).getByRole("button", { name: "Emoji picker" });
    expect(picker.closest(`[title="${EXTRA_LABEL}"]`)).toBeNull();
    expectInOrder([within(dialog).getByLabelText(/^Text/), picker, within(dialog).getByLabelText("Message price")]);
  });

  it("shows the stored Sequence and Step, labelled Inflowwww extra, and an edit keeps them", async () => {
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A
        ? Promise.resolve({ list: [{ ...REPLIES[1], script_id: "flow", script_step: 2 }] })
        : reads(path, ctx));
    renderWithProviders(<ScriptsPage />);
    await screen.findByText("Unlock this one");
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit script" });
    expect(within(dialog).getByLabelText("Sequence")).toHaveValue("flow");
    expect(within(dialog).getByLabelText("Step")).toHaveValue("2");
    expect(within(dialog).getByLabelText("Sequence").closest(`[title="${EXTRA_LABEL}"]`)).toBeTruthy();
    expect(within(dialog).queryByPlaceholderText("name (e.g. welcome-flow)")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1]).toMatchObject({ script_id: "flow", script_step: 2 });
  });

  it("titles the GIF button and Lock text behind price Inflowwww extra: the bundle's script has neither", async () => {
    const dialog = await openEdit(1);
    expect(within(dialog).getByRole("button", { name: "GIF picker" }).closest(`[title="${EXTRA_LABEL}"]`)).toBeTruthy();
    expect(within(dialog).getByText("Lock text behind price").closest(`[title="${EXTRA_LABEL}"]`)).toBeTruthy();
  });

  it("marks each tile Paid with a checkbox and counts them as the bundle does, in place of the FREE/PPV tiles", async () => {
    const dialog = await openEdit(0);
    fireEvent.change(within(dialog).getByLabelText("Message price"), { target: { value: "5" } });
    expect(within(dialog).queryByRole("button", { name: /FREE|PPV/ })).toBeNull();
    const paid = within(dialog).getByRole("checkbox", { name: "Paid" });
    expect(paid).toBeChecked();
    // The count is drawn in the accent, as the bundle's is, so the line spans two elements.
    const ppvLine = (t: string) => within(dialog).getByText((_, el) => el?.tagName === "SPAN" && el.textContent === t
      && !Array.from(el.children).some((c) => c.textContent === t));
    expect(ppvLine("1 of 1 selected as PPV")).toBeInTheDocument();
    fireEvent.click(paid);
    expect(paid).not.toBeChecked();
    expect(ppvLine("0 of 1 selected as PPV")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "All" }));
    expect(paid).toBeChecked();
    fireEvent.click(paid);
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1]).toMatchObject({ price: 5, previews: [501] });
  });

  it("puts Tag other Creators after Media, as its own field (#78), and closes on OK, not Save (Modal's onOk)", async () => {
    const dialog = await openEdit(0);
    expectInCapture("growth-scripts#78", "Tag other Creator(s)");
    expectInOrder([
      within(dialog).getByLabelText("Message price"),
      within(dialog).getByTitle("Tag other creators in this message"),
      within(dialog).getByLabelText("Internal notes"),
    ]);
    expect(within(dialog).queryByRole("button", { name: "Save" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "OK" })).toBeEnabled();
  });
});

/* ── Import and Share (#94 to #98) ─────────────────────────────────────── */

describe("Import from Excel, Import from other creators and Share copy scripts", () => {
  it("From Excel uploads the file to the import route and reports the counts and each failed row", async () => {
    uploadFile.mockResolvedValue({
      total: 3, success_count: 2, fail_count: 1,
      failed: [{ sheet: "Openers", row: 4, name: "hi", reason: "duplicate name" }],
    });
    await mount();
    openMore();
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "From Excel" }));
    expectInCapture("growth-scripts#94", "Import scripts from Excel");
    expectInCapture("growth-scripts#95", "Step1: Download the script template and fill in the data:");
    const dialog = screen.getByRole("dialog", { name: "Import scripts from Excel" });
    expect(within(dialog).getByText("Step1: Download the script template and fill in the data:")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Script templates\.xlsx/ }))
      .toHaveAttribute("href", "/admin/saved-replies/import-template");
    const importBtn = within(dialog).getByRole("button", { name: "Import" });
    expect(importBtn).toBeDisabled();
    const file = new File(["x"], "scripts.xlsx");
    fireEvent.change(within(dialog).getByLabelText("Excel file"), { target: { files: [file] } });
    fireEvent.click(importBtn);
    await screen.findByText(/You've imported a total of 3 data items/);
    expect(uploadFile).toHaveBeenCalledWith("/admin/saved-replies/import?account_id=acc-a", file);
    expect(screen.getByText(/Openers, row 4:/)).toBeInTheDocument();
    expect(screen.getByText(/duplicate name/)).toBeInTheDocument();
  });

  it("From other creators copies the picked Creators' scripts here", async () => {
    post.mockResolvedValue({ copied: 2, skipped: 1, media_dropped: 1, sequence_dropped: 0 });
    await mount();
    openMore();
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "From other creators" }));
    expectInCapture("growth-scripts#97", "Up to 5 creators can be selected");
    const dialog = screen.getByRole("dialog", { name: "Import scripts from other creators" });
    // The open Creator is not offered as its own source.
    expect(within(dialog).queryByRole("checkbox", { name: "Creator A" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Creator B" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await screen.findByText(/script(s)? copied/);
    expect(post).toHaveBeenCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["acc-b"], to_account_ids: ["acc-a"], ids: undefined,
    });
    expect(screen.getByText(/1 arrived without their media/)).toBeInTheDocument();
  });

  it("a row's Share sends that script, and the header's Share the selection, to the picked Creators", async () => {
    post.mockResolvedValue({ copied: 1, skipped: 0, media_dropped: 0, sequence_dropped: 0 });
    await mount();
    fireEvent.click(within(rows()[1]).getByRole("button", { name: "Share script" }));
    let dialog = screen.getByRole("dialog", { name: "Share script with other Creators" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Creator B" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await screen.findByText(/script copied/);
    expect(post).toHaveBeenLastCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["acc-a"], to_account_ids: ["acc-b"], ids: [2],
    });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Shared" })).getAllByRole("button", { name: "Close" })[0]);
    fireEvent.click(within(rows()[0]).getByRole("checkbox"));
    // Cancel keeps the selection; only a Share that went through clears it.
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Share script with other Creators" }))
      .getByRole("button", { name: "Cancel" }));
    expect(within(rows()[0]).getByRole("checkbox")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    dialog = screen.getByRole("dialog", { name: "Share script with other Creators" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Creator B" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(post).toHaveBeenLastCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["acc-a"], to_account_ids: ["acc-b"], ids: [1],
    }));
    await waitFor(() => expect(within(rows()[0]).getByRole("checkbox")).not.toBeChecked());
  });
});

/* ── Not wired ──────────────────────────────────────────────────────────── */

describe("controls with nothing behind them are Not wired", () => {
  it("disables and titles every Not wired control, and none of them calls the relay", async () => {
    await mount();
    openMore();
    const menu = screen.getByRole("menu");
    const controls = [
      screen.getByRole("button", { name: "Learn" }),
      ...["Use template", "Import from tag"].map((n) => within(menu).getByRole("menuitem", { name: n })),
    ];
    const reads = get.mock.calls.length;
    for (const c of controls) {
      expect(c, c.textContent ?? "").toBeDisabled();
      expect(c).toHaveAttribute("title", "not wired");
      fireEvent.click(c);
    }
    expect(get.mock.calls.length).toBe(reads);
    expect(writes()).toBe(0);
  });

  it("shows the stats cell of every row as — titled not wired, and an untagged row's tags cell as —", async () => {
    await mount();
    expectInCapture("growth-scripts#45", "--");
    for (const row of rows()) {
      expect(within(row).getByLabelText("Tags")).toHaveTextContent(/^—$/);
      const stats = within(row).getByLabelText("Stats");
      expect(stats).toHaveAttribute("title", "not wired");
      expect(stats).toHaveTextContent(/^—$/);
    }
  });
});

/* ── extras ─────────────────────────────────────────────────────────────── */

describe("Inflowwww extras", () => {
  it("renders no welcome editor: it lives on Smart Messages' Delayed welcome row (ticket 43)", async () => {
    await mount();
    expect(screen.queryByRole("heading", { name: "Welcome message" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Set welcome" })).toBeNull();
    expect(screen.queryByText(/No welcome message set/)).toBeNull();
    // Nor does the page read the welcome slot or its switch.
    expect(get.mock.calls.map(([p]) => p)).not.toContain(TEMPLATES);
    expect(get.mock.calls.map(([p]) => p)).not.toContain(SETTINGS);
    // Its source uses neither welcome write.
    const src = readFileSync(resolve(__dirname, "ScriptsPage.tsx"), "utf8");
    expect(src).not.toMatch(/useUpsertWelcome|useToggleReplyOnSubscribe|WelcomeEditor/);
  });

  it("titles every other extra EXTRA_LABEL: the tagged-Creators count", async () => {
    await mount();
    expect(within(rows()[0]).getByLabelText("Tagged Creators: 2")).toHaveAttribute("title", EXTRA_LABEL);
    // #6: the creator select is Infloww's own now, so it carries no label (its script count is left out, YAGNI).
    expectInCapture("growth-scripts#6", "showScriptCount");
    expect(screen.getByRole("combobox", { name: "Creator" }).closest(`[title="${EXTRA_LABEL}"]`)).toBeNull();
  });

  it("titles the house Loading… line EXTRA_LABEL", async () => {
    get.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<ScriptsPage />);
    expect(await screen.findByText("Loading…")).toHaveAttribute("title", EXTRA_LABEL);
  });

  it("titles the house Failed to load line EXTRA_LABEL", async () => {
    get.mockImplementation(() => Promise.reject(new Error("boom")));
    renderWithProviders(<ScriptsPage />);
    expect(await screen.findByText(/Failed to load/, undefined, { timeout: 5000 })).toHaveAttribute("title", EXTRA_LABEL);
  });

  it("drops the Templates card's heading, Refresh and local-only note", async () => {
    await mount();
    expect(screen.queryByRole("heading", { name: "Templates" })).toBeNull();
    // The creator column's own "Refresh creators" aside, nothing on the page refreshes.
    expect(screen.queryAllByRole("button", { name: /Refresh/ }).filter((b) => !column().contains(b))).toEqual([]);
    expect(screen.queryByText(/OF won.t see them/)).toBeNull();
  });
});

/* ── the creator control ────────────────────────────────────────────────── */

describe("the creator control scopes every read and write", () => {
  it("switching to Creator B reads B's saved replies and creates the next script under B", async () => {
    await mount();
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Edit" }));
    pickCreator("Creator B");
    // The open draft belongs to Creator A, so the switch closes it.
    expect(screen.queryByRole("dialog")).toBeNull();
    await screen.findByText("Try out our new sequence feature");
    expect(get.mock.calls.map(([p]) => p)).toContain(LIST_B);
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Add script" }));
    fireEvent.change(nameBox(), { target: { value: "B one" } });
    fireEvent.change(textbox(), { target: { value: "For B" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe(LIST_B);
  });
});

/* ── tags and sequences ─────────────────────────────────────────────────── */

describe("tags and sequences are stored on the scripts", () => {
  const RELABEL = "/admin/saved-replies/relabel?account_id=acc-a";
  const TAGGED = [
    { ...REPLIES[0], tags: ["Opener", "VIP"], notes: "use after 9pm", updated_at: "2026-10-01T00:00:00" },
    { ...REPLIES[1], tags: [], updated_at: "2026-10-02T00:00:00" },
    { id: 3, account_id: "acc-a", title: "ask location", text: "where are you from?", price: 0, locked_text: false,
      media: [], tags: ["Opener"], script_id: "New Sub", script_step: 1, updated_at: "2026-09-01T00:00:00" },
    { id: 4, account_id: "acc-a", title: "answer job", text: "a waitress", price: 0, locked_text: false,
      media: [], script_id: "New Sub", script_step: 2, updated_at: "2026-09-02T00:00:00" },
    { id: 5, account_id: "acc-a", title: "ask fantasy", text: "any fantasies?", price: 0, locked_text: false,
      media: [], script_id: "New Sub", script_step: 2, updated_at: "2026-09-03T00:00:00" },
  ];
  async function mountTagged() {
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A ? Promise.resolve({ list: TAGGED }) : reads(path, ctx));
    renderWithProviders(<ScriptsPage />);
    await screen.findByText("Hey there");
  }
  const sidebar = (name: string) => screen.getByRole("complementary", { name });
  const titles = () => rows().map((r) => r.querySelector(".line-clamp-3")?.textContent);

  it("lists All scripts, each tag with its count, then Uncategorized; a tag shows only its scripts", async () => {
    await mountTagged();
    const side = sidebar("Tags");
    expect([...side.querySelectorAll("li > [role='button']")].map((b) => b.textContent)).toEqual([
      "All scripts5 scripts", "Opener2 scripts", "VIP1 script", "Uncategorized3 scripts",
    ]);
    fireEvent.click(within(side).getByText("Opener"));
    expect(titles()).toEqual(["Greeting", "ask location"]);
    fireEvent.click(within(side).getByText("Uncategorized"));
    expect(titles()).toEqual(["Unlock", "answer job", "ask fantasy"]);
  });

  it("shows a row's tag and sequence chips, its notes, and a chip opens its tag or sequence", async () => {
    await mountTagged();
    const first = rows()[0];
    expect(within(first).getByLabelText("Internal notes")).toHaveTextContent("use after 9pm");
    const loc = rows()[2];
    expect(within(loc).getByTitle("Tag: Opener")).toBeInTheDocument();
    fireEvent.click(within(loc).getByTitle("Sequence: New Sub"));
    expect(screen.getByRole("tab", { name: "Sequence" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "New Sub" })).toBeInTheDocument();
  });

  it("numbers a sequence's steps, 2.1 / 2.2 when a step holds several scripts, and Add step seeds the next step", async () => {
    await mountTagged();
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    expectInCapture("growth-scripts#38", "72px in a sequence");
    expect(titles()).toEqual(["1", "2.1", "2.2"]);
    expect(within(rows()[1]).getByText("answer job")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    const dialog = screen.getByRole("dialog", { name: "Add script" });
    expect(within(dialog).getByLabelText("Sequence")).toHaveValue("New Sub");
    expect(within(dialog).getByLabelText("Step")).toHaveValue("3");
  });

  it("removes a script from the open tag or sequence instead of deleting it", async () => {
    await mountTagged();
    fireEvent.click(within(sidebar("Tags")).getByText("VIP"));
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Remove from tag" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0]).toEqual([RELABEL, { kind: "tag", from: "VIP", ids: [1] }]);
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Remove from sequence" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1]).toEqual([RELABEL, { kind: "sequence", from: "New Sub", ids: [3] }]);
    expect(del).not.toHaveBeenCalled();
  });

  it("renames and deletes a tag from its sidebar menu", async () => {
    await mountTagged();
    fireEvent.click(within(sidebar("Tags")).getByRole("button", { name: "Opener menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Modify tag name" });
    expectInCapture("growth-scripts#81", "maxLength:32");
    const input = within(dialog).getByLabelText(/Tag name/);
    expect(input).toHaveValue("Opener");
    expect(input).toHaveAttribute("maxLength", "32");
    fireEvent.change(input, { target: { value: "Openers" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0]).toEqual([RELABEL, { kind: "tag", from: "Opener", to: "Openers" }]);
    fireEvent.click(within(sidebar("Tags")).getByRole("button", { name: "VIP menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1]).toEqual([RELABEL, { kind: "tag", from: "VIP" }]);
  });

  type Relabel = { kind: "tag" | "sequence"; from?: string; to?: string; ids?: number[] };
  type Live = { id: number; tags?: string[]; script_id?: string | null; [k: string]: unknown };
  /** The list GET answers the relabels POSTed so far, as the relay applies them. */
  async function mountLive(extra: Live[] = []) {
    let data = structuredClone([...TAGGED, ...extra]) as Live[];
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A ? Promise.resolve({ list: data }) : reads(path, ctx));
    post.mockImplementation((path: string, b: Relabel) => {
      if (path !== RELABEL) return Promise.resolve({});
      data = data.map((r) => {
        if (b.ids && !b.ids.includes(r.id)) return r;
        if (b.kind === "sequence") return r.script_id === b.from ? { ...r, script_id: b.to ?? null } : r;
        const tags = r.tags ?? [];
        if (b.from) return tags.includes(b.from) ? { ...r, tags: [...tags.filter((t) => t !== b.from), ...(b.to ? [b.to] : [])] } : r;
        return tags.includes(b.to!) ? r : { ...r, tags: [...tags, b.to!] };
      });
      return Promise.resolve({ updated: 1 });
    });
    renderWithProviders(<ScriptsPage />);
    await screen.findByText("Hey there");
  }
  const openRow = (side: string) => sidebar(side).querySelector("[aria-current='true'] span")?.textContent;
  const box = (title: string) => screen.getByRole("checkbox", { name: `Select ${title}` });
  function rowMenu(side: string, name: string, item: "Rename" | "Delete") {
    fireEvent.click(within(sidebar(side)).getByRole("button", { name: `${name} menu` }));
    fireEvent.click(screen.getByRole("menuitem", { name: item }));
  }
  function rename(title: string, label: RegExp, to: string) {
    const dialog = screen.getByRole("dialog", { name: title });
    fireEvent.change(within(dialog).getByLabelText(label), { target: { value: to } });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
  }

  it("keeps the open tag and checks through other tags' renames and deletes; deleting the open one opens the next", async () => {
    await mountLive();
    fireEvent.click(within(sidebar("Tags")).getByText("VIP"));
    fireEvent.click(box("Greeting"));
    rowMenu("Tags", "Opener", "Rename");
    rename("Modify tag name", /Tag name/, "Openers");
    await within(sidebar("Tags")).findByText("Openers");
    expect(openRow("Tags")).toBe("VIP");
    expect(box("Greeting")).toBeChecked();
    rowMenu("Tags", "VIP", "Rename");
    rename("Modify tag name", /Tag name/, "VIPs");
    await waitFor(() => expect(openRow("Tags")).toBe("VIPs"));
    expect(box("Greeting")).toBeChecked();
    rowMenu("Tags", "Openers", "Delete");
    await waitFor(() => expect(within(sidebar("Tags")).queryByText("Openers")).toBeNull());
    expect(openRow("Tags")).toBe("VIPs");
    expect(box("Greeting")).toBeChecked();
    // The open tag, last of the tags: the next row drawn is Uncategorized, where Greeting now is, unchecked.
    rowMenu("Tags", "VIPs", "Delete");
    await waitFor(() => expect(openRow("Tags")).toBe("Uncategorized"));
    expect(box("Greeting")).not.toBeChecked();
  });

  it("deleting the open sequence opens the next once the server agrees; a failed delete keeps it and its checks", async () => {
    await mountLive([{ ...TAGGED[3], id: 6, title: "alpha one", script_id: "Alpha", script_step: 1 }]);
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    expect(openRow("Sequences")).toBe("Alpha");
    fireEvent.click(box("alpha one"));
    post.mockRejectedValueOnce(new Error("relay down"));
    rowMenu("Sequences", "Alpha", "Delete");
    expect(await screen.findByText("relay down")).toBeInTheDocument();
    expect(openRow("Sequences")).toBe("Alpha");
    expect(box("alpha one")).toBeChecked();
    rowMenu("Sequences", "Alpha", "Delete");
    await waitFor(() => expect(openRow("Sequences")).toBe("New Sub"));
    expect(screen.getByRole("heading", { name: "New Sub" })).toBeInTheDocument();
  });

  it("renames a new tag on the server once a script has taken it", async () => {
    await mountLive();
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Add tag" }));
    rename("Add tag name", /Tag name/, "Night");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(openRow("Tags")).toBe("Night");
    fireEvent.click(within(sidebar("Tags")).getByText("All scripts"));
    fireEvent.click(box("Greeting"));
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Selection" })).getByRole("button", { name: /Add to tag/ }));
    rename("Add tag name", /Tag name/, "Night");
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(sidebar("Tags")).getByText("Night").closest("[role='button']")).toHaveTextContent("1 script"));
    rowMenu("Tags", "Night", "Rename");
    rename("Modify tag name", /Tag name/, "Late");
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1]).toEqual([RELABEL, { kind: "tag", from: "Night", to: "Late" }]);
    await waitFor(() => expect(openRow("Tags")).toBe("Late"));
  });

  it("closes a sidebar row's menu on Escape and puts focus back on its trigger", async () => {
    await mountTagged();
    const trigger = within(sidebar("Tags")).getByRole("button", { name: "Opener menu" });
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("shows a sequence rename clash under the name field and keeps the modal open", async () => {
    await mountTagged();
    post.mockRejectedValueOnce(new Error("Sequence name already exists. Please rename sequence."));
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    fireEvent.click(within(sidebar("Sequences")).getByRole("button", { name: "New Sub menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Modify sequence name" });
    fireEvent.change(within(dialog).getByLabelText(/Sequence name/), { target: { value: "Other" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    expect(await within(dialog).findByText(/already exists/)).toBeInTheDocument();
  });

  it("selects scripts and adds them to a tag, or deletes them, from the selection bar", async () => {
    await mountTagged();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Greeting" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Unlock" }));
    const bar = screen.getByRole("toolbar", { name: "Selection" });
    expectInCapture("growth-scripts#51", "Selected");
    expect(bar).toHaveTextContent("Selected2");
    fireEvent.click(within(bar).getByRole("button", { name: /Add to tag/ }));
    const dialog = screen.getByRole("dialog", { name: "Add tag name" });
    fireEvent.change(within(dialog).getByLabelText(/Tag name/), { target: { value: "Night" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0]).toEqual([RELABEL, { kind: "tag", to: "Night", ids: [1, 2] }]);
    // Select all, then Delete removes each.
    fireEvent.click(screen.getByRole("button", { name: /All scripts/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Selection" })).getByRole("button", { name: /Delete/ }));
    await waitFor(() => expect(del).toHaveBeenCalledTimes(5));
  });

  it("Create new sequence asks for a name, then opens the editor on its step 1", async () => {
    await mount();
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Create new" }));
    const dialog = screen.getByRole("dialog", { name: "Add sequence" });
    fireEvent.change(within(dialog).getByLabelText(/Sequence name/), { target: { value: "Welcome" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    const editor = await screen.findByRole("dialog", { name: "Add script" });
    expect(within(editor).getByLabelText("Sequence")).toHaveValue("Welcome");
    expect(within(editor).getByLabelText("Step")).toHaveValue("1");
  });

  it("searches name, text, notes and tags, and Manage scripts sorts by Name", async () => {
    await mountTagged();
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search scripts" }), { target: { value: "9pm" } });
    expect(titles()).toEqual(["Greeting"]);
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "Manage scripts" }));
    // Recent, descending: the newest edit first.
    expect(titles()[0]).toBe("Unlock");
    pick("Sort by", "Name");
    pick("Sort order", "Ascending");
    expect(titles()).toEqual(["answer job", "ask fantasy", "ask location", "Greeting", "Unlock"]);
  });
});
