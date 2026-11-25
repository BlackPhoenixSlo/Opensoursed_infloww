import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
vi.mock("@/contexts/UserContext", async (orig) => ({
  ...(await orig<typeof import("@/contexts/UserContext")>()),
  useOptionalUser: () => ({ user: { user_id: "owner-A" }, loading: false }),
}));

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: {
      ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});
const access = vi.hoisted(() => ({ q: { isLoading: false, isError: false, data: undefined as { restricted?: boolean } | undefined } }));
vi.mock("@/hooks/useVaultMedia", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useVaultMedia")>()),
  useChatterFolderAccess: () => access.q,
}));
const renderCap = vi.hoisted(() => ({ step: undefined as number | undefined }));
vi.mock("@/hooks/useRenderCap", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useRenderCap")>();
  return { useRenderCap: (total: number, key: string, step?: number) => mod.useRenderCap(total, key, renderCap.step ?? step) };
});
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [
    { id: "acc-a", nickname: "Creator A", has_session: true },
    { id: "acc-b", nickname: "Creator B", has_session: true },
  ],
  ownerAccountsQuery: (u?: string) => ({ queryKey: ["accounts", u ?? "anon"], queryFn: async () => ({ accounts: [] }) }),
}));

import ScriptsPage from "@/components/growth/ScriptsPage";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay, RelayError } from "@/lib/relay";
import { QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "@/test-utils";

const ownerCache = () => {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  c.setQueryData(["accounts", "owner-A"], {
    accounts: [{ id: "acc-a", platform: "onlyfans" }, { id: "acc-b", platform: "onlyfans" }], active_account_id: null,
  });
  return c;
};

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;
const patch = relay.patch as unknown as Mock;
const del = relay.delete as unknown as Mock;
const uploadFile = relay.uploadFile as unknown as Mock;


const CAPTURE = readFileSync(
  resolve(__dirname, "../../../docs/infloww-layouts/growth-scripts.md"),
  "utf8",
);

function expectInCapture(id: string, label: string) {
  const row = CAPTURE.split("\n").find((l) => l.startsWith(`| ${id} |`));
  expect(row, `capture row ${id}`).toBeTruthy();
  expect(row, `capture row ${id} holds "${label}"`).toContain(label);
}

function expectInOrder(els: Element[]) {
  for (let i = 1; i < els.length; i++) {
    expect(
      els[i - 1].compareDocumentPosition(els[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      `element ${i} follows element ${i - 1}`,
    ).toBeTruthy();
  }
}


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
  access.q = { isLoading: false, isError: false, data: undefined };
  serve();
  vi.stubGlobal("confirm", () => true);
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function mount() {
  renderWithProviders(<ScriptsPage />, ownerCache());
  await screen.findByText("Hey there");
}

const rows = () => screen.getAllByRole("listitem").filter((li) => li.closest("[aria-label='Scripts list']"));
const textbox = () => screen.getByPlaceholderText("Enter your message...");
const typeBody = (v: string) => {
  const el = textbox();
  el.innerHTML = v.split("\n").map((l) => `<p>${l}</p>`).join("");
  fireEvent.input(el);
};
const nameBox = () => screen.getByPlaceholderText("Enter name");
const openMore = () => fireEvent.click(screen.getByRole("button", { name: "More" }));
const writes = () => post.mock.calls.length + put.mock.calls.length + patch.mock.calls.length + del.mock.calls.length;
function pick(name: string, option: string) {
  fireEvent.click(screen.getByRole("combobox", { name }));
  fireEvent.click(within(screen.getByRole("listbox", { name })).getByRole("option", { name: new RegExp(`${option}$`) }));
}
const column = () => screen.getByTestId("of-creator-column");
const creatorRow = (name: string) => within(column()).getByRole("button", { name: new RegExp(name) });
const pickCreator = (name: string) => fireEvent.click(creatorRow(name));


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
    expectInCapture("growth-scripts#6", "creator selector");
    const banner = screen.getByRole("banner");
    expect(within(banner).queryByRole("combobox", { name: "Creator" })).toBeNull();
    expect(within(banner).queryByTestId("of-creator-column")).toBeNull();
    expectInOrder([banner, column()]);
    expect(column().nextElementSibling!.contains(screen.getByRole("tab", { name: "Sequence" }))).toBe(true);
    expect(creatorRow("Creator A")).toHaveAttribute("aria-current", "true");
    expect(creatorRow("Creator B")).not.toHaveAttribute("aria-current");
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
    expect(within(menu).getByRole("menuitem", { name: "From other creators" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(more).toHaveFocus();
  });

  it("draws the More trigger as a labelled \"+ Add\" accent button (#12; the bundle's bare circle read as nothing)", async () => {
    await mount();
    const more = screen.getByRole("button", { name: "More" });
    expect(more).toHaveClass("bg-accent");
    expect(more).toHaveTextContent(/^Add$/);
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
    expectInCapture("growth-scripts#23", "ScriptType.Tags");
    expect(screen.getByRole("tab", { name: "Tag" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /All scripts/ })).toHaveAttribute("aria-current", "true");
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


describe("the saved replies are the scripts", () => {
  it("lists each saved reply with its title, text, price, media and tagged Creators", async () => {
    await mount();
    const [first, second] = rows();
    expect(within(first).getByText("Greeting")).toBeInTheDocument();
    expect(within(first).getByText("Hey there")).toBeInTheDocument();
    expect(within(first).getByText("photo")).toBeInTheDocument();
    expect(within(first).getByLabelText("Tagged Creators: 2")).toBeInTheDocument();
    expect(within(first).queryByText(/^\$\d/)).toBeNull();
    expect(within(second).getByText("Unlock this one")).toBeInTheDocument();
    expect(within(second).getByText("$12.50")).toBeInTheDocument();
    expect(within(second).getByLabelText("Price")).toHaveTextContent("$12.50");
    expect(within(first).queryByLabelText("Price")).toBeNull();
    expect(first.querySelectorAll("[data-media-id]").length).toBeGreaterThan(0);
    expect(get.mock.calls.map(([p]) => p)).toContain(LIST_A);
  });

  it("Add script opens the saved-reply editor, whose OK posts to the saved-replies route", async () => {
    await mount();
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Add script" }));
    expect(screen.getByRole("dialog", { name: "Add script" })).toBeInTheDocument();
    fireEvent.change(nameBox(), { target: { value: "New one" } });
    typeBody("A new one");
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
    expect(textbox()).toHaveTextContent("Unlock this one");
    typeBody("Unlock it now");
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
  beforeEach(() => {
    const cs = window.getComputedStyle;
    vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) => {
      const st = cs(el, pseudo);
      Object.defineProperty(st, "lineHeight", { value: "20px" });
      return st;
    });
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) {
      return this.textContent === "Hey there" ? 60 : 20;
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("only a row whose text runs past two lines gets the arrow", async () => {
    await mount();
    expectInCapture("growth-scripts#42", "expandable");
    expect(within(rows()[0]).getByRole("button", { name: "Expand script" })).toBeInTheDocument();
    expect(within(rows()[1]).queryByRole("button", { name: /(Expand|Collapse) script/ })).toBeNull();
  });

  it("a row's expander lifts that row's clamp only, and the Expand scripts switch still opens every row", async () => {
    await mount();
    const text = (i: number) => within(rows()[i]).getByText(i === 0 ? "Hey there" : "Unlock this one");
    const toggle = within(rows()[0]).getByRole("button", { name: "Expand script" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName("Collapse script");
    expect(text(0)).not.toHaveClass("line-clamp-2");
    expect(text(1)).toHaveClass("line-clamp-2");
    fireEvent.click(toggle);
    expect(text(0)).toHaveClass("line-clamp-2");
    fireEvent.click(screen.getByRole("switch", { name: "Expand scripts" }));
    expect(text(0)).not.toHaveClass("line-clamp-2");
    expect(text(1)).not.toHaveClass("line-clamp-2");
  });
});


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
    expect(dialog).toHaveClass("rounded-[10px]");
    expect(readFileSync(resolve(__dirname, "ScriptModals.tsx"), "utf8")).toMatch(/<IfModal title=\{title\} width=\{535\}/);
    for (const [id, label] of [
      ["growth-scripts#73", "Name"], ["growth-scripts#74", "Tags"], ["growth-scripts#75", "Text"],
      ["growth-scripts#76", "Message price"], ["growth-scripts#79", "Internal notes"],
    ]) expectInCapture(id, label);
    expectInOrder([
      within(dialog).getByLabelText(/^Name/),
      within(dialog).getByLabelText("Tags"),
      within(dialog).getByRole("textbox", { name: /^Text/ }),
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
    expect(textbox()).toHaveAttribute("data-maxlength", "6500");
    expect(textbox()).toBeRequired();
    const save = within(dialog).getByRole("button", { name: "OK" });
    typeBody("Body only");
    expect(save).toBeDisabled();
    fireEvent.change(nameBox(), { target: { value: "Named" } });
    expect(save).toBeEnabled();
  });

  it("holds a priced script to the $3 minimum", async () => {
    const dialog = await openAdd();
    expectInCapture("growth-scripts#77", "Minimum $3 USD");
    fireEvent.change(nameBox(), { target: { value: "Named" } });
    typeBody("Pay me");
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
    typeBody("what's your name?");
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
    expectInOrder([within(dialog).getByRole("textbox", { name: /^Text/ }), picker, within(dialog).getByLabelText("Message price")]);
  });

  it("shows the stored Sequence and Step, labelled Inflowwww extra, and an edit keeps them", async () => {
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A
        ? Promise.resolve({ list: [{ ...REPLIES[1], script_id: "flow", script_step: 2 }] })
        : reads(path, ctx));
    renderWithProviders(<ScriptsPage />, ownerCache());
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

  it("All creators hides the header's write actions (they would act on the hidden Creator) until a Creator's pick", async () => {
    await mount();
    expect(screen.getByRole("button", { name: "Share" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /All creators/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /All creators/ }).at(-1)!);
    await waitFor(() => expect(screen.queryByRole("button", { name: "More" })).toBeNull());
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Creator A/ }));
    await screen.findByRole("button", { name: "More" });
  });

  it("From other creators copies the picked Creators' scripts here", async () => {
    post.mockResolvedValue({ copied: 2, skipped: 1, media_dropped: 1 });
    await mount();
    openMore();
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "From other creators" }));
    expectInCapture("growth-scripts#97", "Up to 5 creators can be selected");
    const dialog = screen.getByRole("dialog", { name: "Import scripts from other creators" });
    expect(within(dialog).queryByRole("checkbox", { name: "Creator A" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Creator B" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await screen.findByText(/script(s)? copied/);
    expect(post).toHaveBeenCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["acc-b"], to_account_ids: ["acc-a"], all_creators: false, ids: undefined,
    });
    expect(screen.getByText(/1 arrived without their media/)).toBeInTheDocument();
  });

  it("a row's Share sends that script, and the header's Share the selection, to the picked Creators", async () => {
    post.mockResolvedValue({ copied: 1, skipped: 0, media_dropped: 0 });
    await mount();
    fireEvent.click(within(rows()[1]).getByRole("button", { name: "Share script" }));
    let dialog = screen.getByRole("dialog", { name: "Share script with other Creators" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Creator B" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await screen.findByText(/script copied/);
    expect(post).toHaveBeenLastCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["acc-a"], to_account_ids: ["acc-b"], all_creators: false, ids: [2],
    });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Shared" })).getAllByRole("button", { name: "Close" })[0]);
    fireEvent.click(within(rows()[0]).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Share script with other Creators" }))
      .getByRole("button", { name: "Cancel" }));
    expect(within(rows()[0]).getByRole("checkbox")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    dialog = screen.getByRole("dialog", { name: "Share script with other Creators" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Creator B" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(post).toHaveBeenLastCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["acc-a"], to_account_ids: ["acc-b"], all_creators: false, ids: [1],
    }));
    await waitFor(() => expect(within(rows()[0]).getByRole("checkbox")).not.toBeChecked());
  });
});


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


describe("Inflowwww extras", () => {
  it("renders no welcome editor: it lives on Smart Messages' Delayed welcome row (ticket 43)", async () => {
    await mount();
    expect(screen.queryByRole("heading", { name: "Welcome message" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Set welcome" })).toBeNull();
    expect(screen.queryByText(/No welcome message set/)).toBeNull();
    expect(get.mock.calls.map(([p]) => p)).not.toContain(TEMPLATES);
    expect(get.mock.calls.map(([p]) => p)).not.toContain(SETTINGS);
    const src = readFileSync(resolve(__dirname, "ScriptsPage.tsx"), "utf8");
    expect(src).not.toMatch(/useUpsertWelcome|useToggleReplyOnSubscribe|WelcomeEditor/);
  });

  it("titles every other extra EXTRA_LABEL: the tagged-Creators count", async () => {
    await mount();
    expect(within(rows()[0]).getByLabelText("Tagged Creators: 2")).toHaveAttribute("title", EXTRA_LABEL);
    expectInCapture("growth-scripts#6", "showScriptCount");
    expect(screen.getByRole("combobox", { name: "Creator" }).closest(`[title="${EXTRA_LABEL}"]`)).toBeNull();
  });

  it("titles the house Loading… line EXTRA_LABEL", async () => {
    get.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<ScriptsPage />, ownerCache());
    expect(await screen.findByText("Loading…")).toHaveAttribute("title", EXTRA_LABEL);
  });

  it("titles the house Failed to load line EXTRA_LABEL", async () => {
    get.mockImplementation(() => Promise.reject(new Error("boom")));
    renderWithProviders(<ScriptsPage />, ownerCache());
    expect(await screen.findByText(/Failed to load/, undefined, { timeout: 5000 })).toHaveAttribute("title", EXTRA_LABEL);
  });

  it("drops the Templates card's heading, Refresh and local-only note", async () => {
    await mount();
    expect(screen.queryByRole("heading", { name: "Templates" })).toBeNull();
    expect(screen.queryAllByRole("button", { name: /Refresh/ }).filter((b) => !column().contains(b))).toEqual([]);
    expect(screen.queryByText(/OF won.t see them/)).toBeNull();
  });
});


describe("the creator control scopes every read and write", () => {
  it("switching to Creator B reads B's saved replies and creates the next script under B", async () => {
    await mount();
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Edit" }));
    pickCreator("Creator B");
    expect(screen.queryByRole("dialog")).toBeNull();
    await screen.findByText("Try out our new sequence feature");
    expect(get.mock.calls.map(([p]) => p)).toContain(LIST_B);
    openMore();
    fireEvent.click(screen.getByRole("menuitem", { name: "Add script" }));
    fireEvent.change(nameBox(), { target: { value: "B one" } });
    typeBody("For B");
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe(LIST_B);
  });
});


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
    renderWithProviders(<ScriptsPage />, ownerCache());
    await screen.findByText("Hey there");
  }
  const sidebar = (name: string) => screen.getByRole("complementary", { name });
  const titles = () => rows().map((r) => r.querySelector(".line-clamp-3, [aria-label^='Step ']")?.textContent);

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

  it("on a phone the tags are one select (each with its count) and the picked tag's own menu", async () => {
    await mountTagged();
    const side = sidebar("Tags");
    const pick = within(side).getByRole("combobox", { name: "Pick tag" }) as HTMLSelectElement;
    expect([...pick.options].map((o) => o.textContent)).toEqual([
      "All scripts · 5", "Opener · 2", "VIP · 1", "Uncategorized · 3",
    ]);
    expect(within(side).queryByRole("button", { name: "All scripts actions" })).toBeNull();
    fireEvent.change(pick, { target: { value: "Opener" } });
    expect(titles()).toEqual(["Greeting", "ask location"]);
    fireEvent.click(within(side).getByRole("button", { name: "Opener actions" }));
    expect(screen.getByRole("menu", { name: "Opener actions" })).toBeInTheDocument();
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
    renderWithProviders(<ScriptsPage />, ownerCache());
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

  async function mountTwoCreators() {
    const B_ROW = { id: 9, account_id: "acc-b", title: "B script", text: "for B", price: 0, locked_text: false, media: [] };
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A ? Promise.resolve({ list: TAGGED })
        : path === LIST_B ? Promise.resolve({ list: [B_ROW] }) : reads(path, ctx));
    renderWithProviders(<ScriptsPage />, ownerCache());
    await screen.findByText("Hey there");
    fireEvent.click(within(sidebar("Tags")).getByText("VIP"));
  }

  it("another Creator drops a failed remove's error, the open name modal and the search", async () => {
    await mountTwoCreators();
    post.mockRejectedValueOnce(new Error("relay down"));
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Remove from tag" }));
    expect(await screen.findByText("relay down")).toBeInTheDocument();
    pickCreator("Creator B");
    await screen.findByText("for B");
    expect(screen.queryByText("relay down")).toBeNull();
    pickCreator("Creator A");
    await screen.findByText("Hey there");
    expect(screen.queryByText("relay down")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search scripts" }), { target: { value: "9pm" } });
    rowMenu("Tags", "Opener", "Rename");
    expect(screen.getByRole("dialog", { name: "Modify tag name" })).toBeInTheDocument();
    pickCreator("Creator B");
    await screen.findByText("for B");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("searchbox", { name: "Search scripts" })).toBeNull();
  });

  it("a remove in flight at a Creator switch: its failure stays off the next Creator; back, its row waits for it", async () => {
    await mountTwoCreators();
    let fail!: (e: Error) => void;
    post.mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Remove from tag" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    pickCreator("Creator B");
    await screen.findByText("for B");
    pickCreator("Creator A");
    await screen.findByText("Hey there");
    const greetingDelete = () => within(rows().find((r) => r.textContent!.includes("Hey there"))!)
      .getByRole("button", { name: "Delete" });
    expect(greetingDelete()).toBeDisabled();
    pickCreator("Creator B");
    await screen.findByText("for B");
    fail(new Error("relay down"));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("relay down")).toBeNull();
    pickCreator("Creator A");
    await screen.findByText("Hey there");
    await waitFor(() => expect(greetingDelete()).toBeEnabled());
    expect(screen.queryByText("relay down")).toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
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
    expect(screen.getByRole("menuitem", { name: "Share" })).toHaveFocus();
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
    fireEvent.click(screen.getByRole("button", { name: /All scripts/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Selection" })).getByRole("button", { name: /Delete/ }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1][0]).toBe("/admin/saved-replies/delete?account_id=acc-a");
    expect([...post.mock.calls[1][1].ids].sort()).toHaveLength(5);
    expect(del).not.toHaveBeenCalled();
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
    expect(titles()[0]).toBe("Unlock");
    pick("Sort by", "Name");
    pick("Sort order", "Ascending");
    expect(titles()).toEqual(["answer job", "ask fantasy", "ask location", "Greeting", "Unlock"]);
  });
});


describe("an imported library", () => {
  const META = "/admin/saved-replies/sequences?account_id=acc-a";
  const step = (id: number, seq: string, n: number, over: object = {}) => ({
    id, account_id: "acc-a", title: `${seq} s${n}`, text: `${seq} text ${n}`, price: 0, locked_text: false, media: [],
    script_id: seq, script_step: n, updated_at: "2026-09-01T00:00:00", created_at: "2026-09-01T00:00:00", ...over,
  });
  function mountLib(list: object[], metas: object[]) {
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A ? Promise.resolve({ list }) : path === META ? Promise.resolve({ list: metas }) : reads(path, ctx));
    renderWithProviders(<ScriptsPage />, ownerCache());
  }
  const seqOrder = () =>
    [...screen.getByRole("complementary", { name: "Sequences" }).querySelectorAll("li > [role='button'] span.truncate")]
      .map((s) => s.textContent);

  it("orders the Sequence sidebar Custom by default, then Name and Recent; the header shows Created by", async () => {
    mountLib(
      [step(1, "Seq 10", 1, { updated_at: "2026-10-05T00:00:00" }), step(2, "Seq 2", 1), step(3, "Seq 1", 1)],
      [
        { name: "Seq 10", position: 0, created_by: "Ana", description: null, created_at: "2025-01-02T00:00:00", updated_at: null },
        { name: "Seq 2", position: 1, created_by: null, description: null, created_at: null, updated_at: null },
      ],
    );
    await screen.findByText("Seq 10 text 1");
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    await waitFor(() => expect(seqOrder()).toEqual(["Seq 10", "Seq 2", "Seq 1"]));
    expect(screen.getByText(/Created by：Ana/)).toBeInTheDocument();
    expect(screen.getByText("Created on：Jan 2, 2025")).toBeInTheDocument();
    const sorts = screen.getByRole("group", { name: "Sort sequences" });
    fireEvent.click(within(sorts).getByRole("button", { name: /Name/ }));
    expect(seqOrder()).toEqual(["Seq 1", "Seq 2", "Seq 10"]);
    fireEvent.click(within(sorts).getByRole("button", { name: /Recent/ }));
    expect(seqOrder()[0]).toBe("Seq 10");
  });

  it("draws steps as numbered cards with a line to the next, and shows the send count in the stats", async () => {
    mountLib([step(1, "S", 1, { sent_count: 3 }), step(2, "S", 2, { sent_count: 0, conditional: "if she asks" })], []);
    await screen.findByText("S text 1");
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    const [a, b] = rows();
    expect(within(a).getByLabelText("Step 1")).toBeInTheDocument();
    expect(a.querySelector("[data-connector]")).not.toBeNull();
    expect(b.querySelector("[data-connector]")).toBeNull();
    expect(within(a).getByLabelText("Sent")).toHaveTextContent("Sent 3");
    expect(within(b).getByLabelText("Condition")).toHaveTextContent("If: if she asks");
    expect(within(a).getByLabelText("Stats")).toHaveAttribute("title", "not wired");
  });

  it("renders 10k scripts 200 at a time; Show more adds the next 200; search reaches the last one", async () => {
    const list = Array.from({ length: 10_000 }, (_, i) => ({
      id: i + 1, account_id: "acc-a", title: `t${i + 1}`, text: `body ${i + 1}`, price: 0, locked_text: false,
      media: [], updated_at: "2026-09-01T00:00:00",
    }));
    mountLib(list, []);
    await screen.findByText("body 1");
    expect(rows()).toHaveLength(201);
    fireEvent.click(screen.getByRole("button", { name: "Show more (9800)" }));
    expect(rows()).toHaveLength(401);
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search scripts" }), { target: { value: "body 10000" } });
    expect(rows()).toHaveLength(1);
    expect(screen.getByText("body 10000")).toBeInTheDocument();
  });
});


describe("Fill with content", () => {
  const APPLY_A = "/admin/saved-replies/fill/apply?account_id=acc-a";
  const PLAN_A = "/admin/saved-replies/fill/plan?account_id=acc-a";
  const UNDO_A = "/admin/saved-replies/fill/undo?account_id=acc-a";
  const DESCRIBE = "/admin/vault-ai/describe-all";
  const SWEEP_A = "/admin/vault-ai/describe-all/status?account_id=acc-a";
  const row = (id: number, account: string, seq: string, step: number, title: string, price = 0) => ({
    id, account_id: account, title, text: `${title} text`, price, locked_text: false, media: [], script_id: seq,
    script_step: step, updated_at: "2026-11-01T00:00:00",
  });
  const A_ROWS = [row(21, "acc-a", "New Sub", 1, "say hi"), row(22, "acc-a", "New Sub", 3, "sell set", 0),
    row(23, "acc-a", "New Sub", 3, "sell set alt", 0), row(24, "acc-a", "Old Sub", 1, "old one")];
  const B_ROWS = [row(31, "acc-b", "New Sub", 1, "b hi")];
  const opt = (id: number, step: number, media: number[], previews: number[] = []) => ({
    id, step, option: 1, role: "paid_media", wants: "photo", keep: false, media, previews, price_cents: 1500,
    price_fixed: false, flags: [],
  });
  const plan = (status: string, describe = { described: 120, target: 1000, remaining: 880, can_describe: true, blocked_reason: null as string | null }) => ({
    status, options: [], flags: ["gap"], conflict: null, describe, fingerprint: "fp",
  });
  const UNDO = [
    { id: 22, media_ids: [701, 702], previews: [701], price_cents: 1500, price_set: true },
    { id: 23, media_ids: [701, 702], previews: [701], price_cents: 900, price_set: false },
    { id: 21, media_ids: [703], previews: [], price_cents: 0, price_set: false },
  ];
  const OK = { status: "ok", plan: plan("ok"), undo: UNDO,
    applied: [opt(22, 3, [701, 702], [701]), opt(23, 3, [701, 702], [701]), opt(21, 1, [703])] };

  function deferred<T>() {
    let resolve!: (v: T) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
  }

  let sweepStatus: { running: boolean; progress: unknown };
  function mountFill(routes: Record<string, (body: unknown) => Promise<unknown>>, client?: QueryClient) {
    sweepStatus = { running: false, progress: null };
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A ? Promise.resolve({ list: A_ROWS })
        : path === LIST_B ? Promise.resolve({ list: B_ROWS })
          : path === SWEEP_A ? Promise.resolve(sweepStatus) : reads(path, ctx));
    post.mockImplementation((path: string, body: unknown) =>
      routes[path] ? routes[path](body) : Promise.reject(new Error(`unmocked POST ${path}`)));
    return renderWithProviders(<ScriptsPage />, client);
  }
  async function openSequence(name = "New Sub") {
    await screen.findByText("say hi text");
    fireEvent.click(screen.getByRole("tab", { name: "Sequence" }));
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText(name));
    await screen.findByRole("heading", { name });
  }
  const fillButton = () => screen.getByRole("button", { name: "Fill with content" });
  const applyCalls = () => post.mock.calls.filter(([p]) => p === APPLY_A);
  const listReads = () => get.mock.calls.filter(([p]) => p === LIST_A).length;

  it("sits before Add step, titled EXTRA_LABEL; a double press while apply is pending sends one POST", async () => {
    const answer = deferred<unknown>();
    mountFill({ [APPLY_A]: () => answer.promise });
    await openSequence();
    const btn = fillButton();
    expectInOrder([btn, screen.getByRole("button", { name: "Add step" })]);
    expect(btn.closest(`[title="${EXTRA_LABEL}"]`)).toBeTruthy();
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(fillButton()).toBeDisabled());
    fireEvent.click(fillButton());
    expect(applyCalls()).toEqual([[APPLY_A, { sequence: "New Sub" }]]);
    const reads = listReads();
    answer.resolve(OK);
    const notice = await screen.findByRole("status", { name: "Fill notice" });
    expect(notice).toHaveTextContent("Added 3 items to 2 steps");
    expect(within(notice).getByRole("button", { name: "Undo" })).toBeEnabled();
    expect(notice).toHaveTextContent("No script at step 2");
    expect(notice).toHaveAttribute("title", EXTRA_LABEL);
    await waitFor(() => expect(listReads()).toBeGreaterThan(reads));
    expect(fillButton()).toBeEnabled();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("Old Sub"));
    await screen.findByRole("heading", { name: "Old Sub" });
    expect(screen.queryByRole("status", { name: "Fill notice" })).toBeNull();
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("New Sub"));
    expect(await screen.findByRole("status", { name: "Fill notice" })).toHaveTextContent("Added 3 items to 2 steps");
  });

  it("two presses in one render (before React re-renders) send exactly one apply", async () => {
    const answer = deferred<unknown>();
    mountFill({ [APPLY_A]: () => answer.promise });
    await openSequence();
    const btn = fillButton();
    act(() => {
      btn.click();
      btn.click();
    });
    await waitFor(() => expect(applyCalls()).not.toHaveLength(0));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(applyCalls()).toEqual([[APPLY_A, { sequence: "New Sub" }]]);
    answer.resolve(OK);
    await screen.findByRole("status", { name: "Fill notice" });
    expect(applyCalls()).toHaveLength(1);
  });

  it("a second ok on the Sequence adds its write to the notice: one Undo posts both lists", async () => {
    const SECOND = { status: "ok", plan: plan("ok"), applied: [opt(24, 4, [704])],
      undo: [{ id: 24, media_ids: [704], previews: [], price_cents: 1500, price_set: true }] };
    let answer: unknown = OK;
    mountFill({ [APPLY_A]: async () => answer, [UNDO_A]: async () => ({ undone: [], kept: [] }) });
    await openSequence();
    fireEvent.click(fillButton());
    expect(await screen.findByRole("status", { name: "Fill notice" })).toHaveTextContent("Added 3 items to 2 steps");
    answer = SECOND;
    fireEvent.click(fillButton());
    await waitFor(() => expect(screen.getByRole("status", { name: "Fill notice" })).toHaveTextContent("Added 4 items to 3 steps"));
    answer = { status: "ok", plan: plan("ok"), applied: [], undo: [] };
    fireEvent.click(fillButton());
    await waitFor(() => expect(applyCalls()).toHaveLength(3));
    await waitFor(() => expect(fillButton()).toBeEnabled());
    expect(screen.getByRole("status", { name: "Fill notice" })).toHaveTextContent("Added 4 items to 3 steps");
    fireEvent.click(within(screen.getByRole("status", { name: "Fill notice" })).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(post.mock.calls.some(([p]) => p === UNDO_A)).toBe(true));
    expect(post.mock.calls.find(([p]) => p === UNDO_A)).toEqual([UNDO_A, { sequence: "New Sub", undo: [...UNDO, ...SECOND.undo] }]);
  });

  it("an ok answered after switching Creator waits on that Creator's Sequence, and its Undo goes to that Creator", async () => {
    const ok = deferred<unknown>();
    mountFill({ [APPLY_A]: () => ok.promise, [UNDO_A]: async () => ({ undone: [21, 22, 23], kept: [] }) });
    await openSequence();
    fireEvent.click(fillButton());
    pickCreator("Creator B");
    await screen.findByText("b hi text");
    ok.resolve(OK);
    await screen.findByRole("heading", { name: "New Sub" });
    await waitFor(() => expect(fillButton()).toBeEnabled());
    expect(screen.queryByRole("status", { name: "Fill notice" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    pickCreator("Creator A");
    await openSequence();
    const notice = await screen.findByRole("status", { name: "Fill notice" });
    expect(notice).toHaveTextContent("Added 3 items to 2 steps");
    fireEvent.click(within(notice).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(post.mock.calls.some(([p]) => p === UNDO_A)).toBe(true));
    expect(post.mock.calls.find(([p]) => p === UNDO_A)).toEqual([UNDO_A, { sequence: "New Sub", undo: UNDO }]);
    await waitFor(() => expect(screen.queryByRole("status", { name: "Fill notice" })).toBeNull());
  });

  it("an ok answered after switching Sequence opens no dialog, refetches the list, and its notice waits on that Sequence", async () => {
    const ok = deferred<unknown>();
    mountFill({ [APPLY_A]: () => ok.promise });
    await openSequence();
    fireEvent.click(fillButton());
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("Old Sub"));
    await screen.findByRole("heading", { name: "Old Sub" });
    const reads = listReads();
    ok.resolve(OK);
    await waitFor(() => expect(listReads()).toBeGreaterThan(reads));
    expect(screen.queryByRole("status", { name: "Fill notice" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("New Sub"));
    await screen.findByRole("heading", { name: "New Sub" });
    const notice = await screen.findByRole("status", { name: "Fill notice" });
    expect(notice).toHaveTextContent("Added 3 items to 2 steps");
    expect(within(notice).getByRole("button", { name: "Undo" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Fill notice" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    const late = deferred<unknown>();
    post.mockImplementation((path: string) => (path === APPLY_A ? late.promise : Promise.reject(new Error(path))));
    fireEvent.click(fillButton());
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("Old Sub"));
    await screen.findByRole("heading", { name: "Old Sub" });
    late.resolve({ status: "no_fit", plan: plan("no_fit"), applied: [], undo: [] });
    await waitFor(() => expect(screen.getByRole("button", { name: "Fill with content" })).toBeEnabled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Undo posts apply's list verbatim and shows what it left, by reason", async () => {
    mountFill({
      [APPLY_A]: async () => OK,
      [UNDO_A]: async () => ({ undone: [21], kept: [{ id: 22, reason: "edited" }, { id: 23, reason: "missing" }] }),
    });
    await openSequence();
    fireEvent.click(fillButton());
    const notice = await screen.findByRole("status", { name: "Fill notice" });
    fireEvent.click(within(notice).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(post.mock.calls.some(([p]) => p === UNDO_A)).toBe(true));
    expect(post.mock.calls.find(([p]) => p === UNDO_A)).toEqual([UNDO_A, { sequence: "New Sub", undo: UNDO }]);
    expect(await screen.findByText("Undo left 2 steps: 1 changed since the Fill, 1 moved or deleted.")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Fill notice" })).toBeNull();
  });

  it("Undo on a reserved Sequence says so for every entry it kept", async () => {
    mountFill({
      [APPLY_A]: async () => OK,
      [UNDO_A]: async () => ({ undone: [], kept: UNDO.map((u) => ({ id: u.id, reason: "reserved" })) }),
    });
    await openSequence();
    fireEvent.click(fillButton());
    fireEvent.click(within(await screen.findByRole("status", { name: "Fill notice" })).getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Undo left 3 steps: 3 in a sequence generated by a script source.")).toBeInTheDocument();
  });

  it.each<[string, () => Error, string]>([
    ["404 sequence_not_found", () => new RelayError(404, { detail: { error: "sequence_not_found" } }, '{"error":"sequence_not_found"}'),
      "This sequence has no steps any more. It was renamed or deleted: reload the page."],
    ["503 inventory_unknown", () => new RelayError(503, { detail: { error: "inventory_unknown" } }, '{"error":"inventory_unknown"}'),
      "The vault list could not be read just now. Try again in a minute."],
    ["a bare HTTP 500", () => new RelayError(500, "", "HTTP 500"), "The relay could not do that. Try again in a minute."],
  ])("a refused apply (%s) shows its sentence, never JSON or HTTP n", async (_n, refusal, sentence) => {
    mountFill({ [APPLY_A]: async () => { throw refusal(); } });
    await openSequence();
    fireEvent.click(fillButton());
    const shown = await screen.findByRole("dialog", { name: "Fill with content" });
    expect(shown).toHaveTextContent(sentence);
    expect(shown).not.toHaveTextContent(/[{}]|HTTP \d/);
  });

  it("Ready to fill.'s press fills: the dialog closes and the notice shows; Close and a new press reopen it", async () => {
    let answer: unknown = { status: "no_fit", plan: plan("no_fit"), applied: [], undo: [] };
    let fresh = plan("no_fit");
    mountFill({ [APPLY_A]: async () => answer, [PLAN_A]: async () => fresh });
    await openSequence();
    fireEvent.click(fillButton());
    const first = await screen.findByRole("dialog", { name: "Fill with content" });
    fireEvent.click(within(first).getAllByRole("button", { name: "Close" }).at(-1)!);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    answer = { status: "not_enough_content", plan: plan("not_enough_content"), applied: [], undo: [] };
    fresh = plan("ok");
    fireEvent.click(fillButton());
    const ready = await screen.findByRole("dialog", { name: "Fill with content" });
    await within(ready).findByText("Ready to fill.");
    expect(applyCalls()).toHaveLength(2);
    answer = OK;
    fireEvent.click(within(ready).getByRole("button", { name: "Fill with content" }));
    expect(await screen.findByRole("status", { name: "Fill notice" })).toHaveTextContent("Added 3 items to 2 steps");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(applyCalls()).toEqual([[APPLY_A, { sequence: "New Sub" }], [APPLY_A, { sequence: "New Sub" }], [APPLY_A, { sequence: "New Sub" }]]);
  });

  it("not_enough_content offers to describe; Describe content starts describe-all with target 1000", async () => {
    const short = plan("not_enough_content");
    mountFill({
      [APPLY_A]: async () => ({ status: "not_enough_content", plan: short, applied: [], undo: [] }),
      [PLAN_A]: async () => short,
      [DESCRIBE]: async () => { sweepStatus = { running: true, progress: { total: 880, done: 12 } }; return { status: "running" }; },
    });
    await openSequence();
    fireEvent.click(fillButton());
    const dialog = await screen.findByRole("dialog", { name: "Describe content first?" });
    expect(dialog).toHaveTextContent(
      "This sequence needs more described vault content. Describe up to 1,000 items for this Creator? 120 of 1000 done.");
    expect(dialog).not.toHaveTextContent("$");
    fireEvent.click(within(dialog).getByRole("button", { name: "Describe content" }));
    await waitFor(() => expect(post.mock.calls.some(([p]) => p === DESCRIBE)).toBe(true));
    expect(post.mock.calls.find(([p]) => p === DESCRIBE)).toEqual([DESCRIBE, { account_id: "acc-a", target: 1000 }, { accountId: "acc-a" }]);
    expect(await screen.findByText("Checked 12 of 880. Keeps going if you close this.")).toBeInTheDocument();
    expect(applyCalls()).toHaveLength(1);
  });

  it.each<[string, () => Error, string]>([
    ["429 with blocked_reason shows that sentence, not JSON", () => new RelayError(429,
      { detail: { error: "daily_cap_reached", capped: true, blocked_reason: "Today's AI budget for this account is spent." } },
      '{"error":"daily_cap_reached","capped":true}'), "Today's AI budget for this account is spent."],
    ["403 role string shows that sentence", () => new RelayError(403, { detail: "Your role does not allow Vault Pro" },
      "Your role does not allow Vault Pro"), "Your role does not allow Vault Pro"],
  ])("a refused describe start: %s", async (_n, refusal, sentence) => {
    const short = plan("not_enough_content");
    mountFill({
      [APPLY_A]: async () => ({ status: "not_enough_content", plan: short, applied: [], undo: [] }),
      [PLAN_A]: async () => short,
      [DESCRIBE]: async () => { throw refusal(); },
    });
    await openSequence();
    fireEvent.click(fillButton());
    const dialog = await screen.findByRole("dialog", { name: "Describe content first?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Describe content" }));
    const shown = await screen.findByRole("dialog", { name: "Fill with content" });
    expect(shown).toHaveTextContent(sentence);
    expect(shown).not.toHaveTextContent(/[{}]|HTTP \d/);
    expect(within(shown).queryByRole("button", { name: "Describe content" })).toBeNull();
  });

  it("a reserved answer gets its own line", async () => {
    mountFill({
      [APPLY_A]: async () => ({ status: "reserved", plan: plan("reserved"), applied: [], undo: [] }),
      [PLAN_A]: async () => plan("reserved"),
    });
    await openSequence();
    fireEvent.click(fillButton());
    expect(await screen.findByRole("dialog", { name: "Fill with content" }))
      .toHaveTextContent("This sequence is generated by a script source and is not filled.");
  });

  const editOf = (i: number) => within(rows()[i]).getByRole("button", { name: "Edit" });
  it.each<[string, () => Promise<unknown>]>([
    ["a refused apply (404 sequence_not_found)",
      async () => { throw new RelayError(404, { detail: { error: "sequence_not_found" } }, "sequence_not_found"); }],
    ["a 409 stale", async () => { throw new RelayError(409, { detail: { error: "stale", plan: plan("no_fit") } }, "stale"); }],
    ["a bare HTTP 500", async () => { throw new RelayError(500, "", "HTTP 500"); }],
    ["a dropped connection", async () => { throw new TypeError("Failed to fetch"); }],
    ["a no_fit answer", async () => ({ status: "no_fit", plan: plan("no_fit"), applied: [], undo: [] })],
    ["an ok", async () => OK],
  ])("a Fill in flight locks every step's Edit until its answer: %s", async (_n, answer) => {
    const out = deferred<void>();
    mountFill({ [APPLY_A]: async () => { await out.promise; return answer(); } });
    await openSequence();
    fireEvent.click(fillButton());
    await waitFor(() => expect(applyCalls()).toHaveLength(1));
    [0, 1, 2].forEach((i) => expect(editOf(i)).toBeDisabled());
    fireEvent.click(editOf(0));
    expect(screen.queryByRole("dialog", { name: "Edit script" })).toBeNull();
    out.resolve();
    await waitFor(() => expect(editOf(0)).toBeEnabled());
    [1, 2].forEach((i) => expect(editOf(i)).toBeEnabled());
  });

  it.each<[string, () => Promise<unknown>]>([
    ["an answer", async () => ({ undone: [22, 23], kept: [] })],
    ["a bare HTTP 500", async () => { throw new RelayError(500, "", "HTTP 500"); }],
    ["a dropped connection", async () => { throw new TypeError("Failed to fetch"); }],
  ])("an Undo in flight locks every step's Edit until its answer: %s", async (_n, answer) => {
    const out = deferred<void>();
    mountFill({
      [APPLY_A]: async () => ({ ...OK, applied: OK.applied.slice(0, 2), undo: UNDO.slice(0, 2) }),
      [UNDO_A]: async () => { await out.promise; return answer(); },
    });
    await openSequence();
    fireEvent.click(fillButton());
    fireEvent.click(within(await screen.findByRole("status", { name: "Fill notice" })).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(post.mock.calls.some(([p]) => p === UNDO_A)).toBe(true));
    [0, 1, 2].forEach((i) => expect(editOf(i)).toBeDisabled());
    out.resolve();
    await waitFor(() => expect(editOf(0)).toBeEnabled());
    [1, 2].forEach((i) => expect(editOf(i)).toBeEnabled());
  });

  it.each<[string, boolean]>([["Fill", false], ["Undo", true]])(
    "a %s whose list reload fails keeps the steps locked until Reload succeeds", async (_n, undo) => {
      let listDown = false;
      mountFill({ [APPLY_A]: async () => { listDown = !undo; return OK; },
        [UNDO_A]: async () => { listDown = true; return { undone: [22, 23, 21], kept: [] }; } });
      const reads = get.getMockImplementation()!;
      get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
        path === LIST_A && listDown ? Promise.reject(new TypeError("Failed to fetch")) : reads(path, ctx));
      await openSequence();
      fireEvent.click(fillButton());
      const notice = await screen.findByRole("status", { name: "Fill notice" });
      if (undo) fireEvent.click(within(notice).getByRole("button", { name: "Undo" }));
      const reload = await screen.findByRole("button", { name: "Reload" });
      [0, 1, 2].forEach((i) => expect(editOf(i)).toBeDisabled());
      fireEvent.click(reload);
      await waitFor(() => expect(reload).toBeEnabled());
      [0, 1, 2].forEach((i) => expect(editOf(i)).toBeDisabled());
      listDown = false;
      fireEvent.click(screen.getByRole("button", { name: "Reload" }));
      await waitFor(() => expect(editOf(0)).toBeEnabled());
      expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
    });

  it("a failed list reload after a Fill keeps the steps locked across a remount", async () => {
    let listDown = false;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } });
    const page = mountFill({ [APPLY_A]: async () => { listDown = true; return OK; } }, client);
    const reads = get.getMockImplementation()!;
    get.mockImplementation((path: string, ctx?: { accountId?: string }) =>
      path === LIST_A && listDown ? Promise.reject(new TypeError("Failed to fetch")) : reads(path, ctx));
    await openSequence();
    fireEvent.click(fillButton());
    await screen.findByRole("button", { name: "Reload" });
    page.unmount();
    renderWithProviders(<ScriptsPage />, client);
    await openSequence();
    await waitFor(() => expect(listReads()).toBeGreaterThan(2));
    await screen.findByRole("button", { name: "Reload" });
    [0, 1, 2].forEach((i) => expect(editOf(i)).toBeDisabled());
    listDown = false;
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(editOf(0)).toBeEnabled());
  });

  it("a step that Show more renders after the press is locked too", async () => {
    const extra = [row(1000, "acc-a", "New Sub", 4, "extra 0")];
    A_ROWS.push(...extra);
    renderCap.step = 2;
    try {
      const out = deferred<unknown>();
      mountFill({ [APPLY_A]: () => out.promise });
      await openSequence();
      fireEvent.click(fillButton());
      await waitFor(() => expect(applyCalls()).toHaveLength(1));
      expect(rows()).toHaveLength(3);
      fireEvent.click(screen.getByRole("button", { name: /^Show more/ }));
      expect(rows()).toHaveLength(4);
      expect(editOf(3)).toBeDisabled();
      out.resolve(OK);
      await waitFor(() => expect(editOf(3)).toBeEnabled());
    } finally {
      renderCap.step = undefined;
      A_ROWS.splice(A_ROWS.length - extra.length, extra.length);
    }
  });

  it("Undo is disabled while a draft is open on a row of its list that left the Sequence", async () => {
    const MOVED = { id: 24, media_ids: [704], previews: [], price_cents: 0, price_set: false };
    mountFill({ [APPLY_A]: async () => ({ ...OK, undo: [...UNDO, MOVED] }) });
    await openSequence();
    fireEvent.click(fillButton());
    const notice = await screen.findByRole("status", { name: "Fill notice" });
    expect(within(notice).getByRole("button", { name: "Undo" })).toBeEnabled();
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("Old Sub"));
    await screen.findByRole("heading", { name: "Old Sub" });
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Edit" }));
    await screen.findByRole("dialog", { name: "Edit script" });
    fireEvent.click(within(screen.getByRole("complementary", { name: "Sequences" })).getByText("New Sub"));
    await screen.findByRole("heading", { name: "New Sub" });
    const undo = within(screen.getByRole("status", { name: "Fill notice" })).getByRole("button", { name: "Undo" });
    expect(undo).toBeDisabled();
    expect(undo).toHaveAttribute("title", "Save or close the open step first");
    expect(fillButton()).toBeEnabled();
  });

  it("an open edit of one of the Sequence's steps disables Fill with \"Save or close the open step first\"", async () => {
    mountFill({});
    await openSequence();
    expect(fillButton()).toBeEnabled();
    fireEvent.click(within(rows()[0]).getByRole("button", { name: "Edit" }));
    await screen.findByRole("dialog", { name: "Edit script" });
    expect(fillButton()).toBeDisabled();
    expect(fillButton()).toHaveAttribute("title", "Save or close the open step first");
    expect(applyCalls()).toHaveLength(0);
  });

  it.each<[string, { isLoading: boolean; isError: boolean; data?: { restricted?: boolean } }]>([
    ["folder-limited", { isLoading: false, isError: false, data: { restricted: true } }],
    ["access unknown", { isLoading: true, isError: false }],
  ])("a %s chatter sees Fill disabled with the Ask the owner title", async (_n, q) => {
    access.q = { data: undefined, ...q };
    mountFill({});
    await openSequence();
    expect(fillButton()).toBeDisabled();
    expect(fillButton()).toHaveAttribute("title", "Ask the owner: filling uses the whole vault");
  });

  it("All creators shows no Fill button", async () => {
    mountFill({});
    await openSequence();
    fireEvent.click(screen.getByRole("button", { name: /All creators/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /All creators/ }).at(-1)!);
    await waitFor(() => expect(screen.queryByRole("button", { name: "More" })).toBeNull());
    expect(screen.queryByRole("button", { name: "Fill with content" })).toBeNull();
  });

  it("another Creator's same-named Sequence shows no notice of the first's Fill", async () => {
    mountFill({ [APPLY_A]: async () => OK });
    await openSequence();
    fireEvent.click(fillButton());
    await screen.findByRole("status", { name: "Fill notice" });
    pickCreator("Creator B");
    await screen.findByText("b hi text");
    await screen.findByRole("heading", { name: "New Sub" });
    expect(screen.queryByRole("status", { name: "Fill notice" })).toBeNull();
  });
});
