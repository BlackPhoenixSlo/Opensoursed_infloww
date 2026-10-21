/**
 * Growth > Tracking links, the page component (docs/spec/infloww-parity-round-2/phase-02-growth-pages.md, Testing
 * Decisions, Seam 1; ticket 38). Rendered as the route renders it (`GrowthTabPage tab="tracking"`), with
 * `@/lib/relay` mocked and a fresh QueryClient over two placeholder Creators. What is pinned:
 *
 *  - the tabs, the attribution tip, the filter bar and the Links list column headers appear in the Layout capture's
 *    order, and every label transcribed here is read back from the capture on disk next to its Item ID;
 *  - name, date created, clicks and subs (thousands commas) come from the OnlyFans tracking-link read, and
 *    Subscription CVR is subs divided by clicks ("—" with no clicks); only the columns with data draw, so the table
 *    has no Promo cost / earnings heads (the cut-off "Promo co") until their data exists;
 *  - the filters: Date created (a client-side range on the day created, with the bundle's six presets) and "Show
 *    deactivated links" (deleted links hidden until it is on, then shown with the "Deactivated" chip); "Show net
 *    earnings" is not drawn while no earnings column has data; Export downloads a CSV of the filtered rows;
 *  - the earnings read (claimers x the ledger) fills Earnings, Fans who spent, Spending CVR, EPC, AEPS and the
 *    Dashboard's Total earnings; "Show net earnings" (on by default) switches them, one state across both tabs; a link
 *    with no figure shows "—"; Details opens the link's fans with the bundle's columns, a "Total:" row and a search;
 *  - the custom redirect links sit in one section carrying `EXTRA_LABEL`, after the capture's elements; the
 *    "OnlyFans not reachable" note shows under its condition, and the old "Confirm the link once" note is gone;
 *  - "Create tracking link" opens the capture's editor pop-up (ticket 39): its labels in the capture's order, the name
 *    creating the link through the existing write for the picked Creator, and Source / Promo cost / Tag / List (the
 *    Edit dialog's fields) sent in the same request; a reply without an id says the fields were not saved;
 *  - each row's Actions are the capture's Details, Edit and the dots menu with Deactivate, which is the OnlyFans
 *    delete behind the bundle's confirm, disabled on a deactivated link; Edit saves Source, Promo cost, Tag and List
 *    to the relay (never OnlyFans), which fill Promo cost, Profit, CPC, CPS, ROI, Source, Tag and List ("—" with no
 *    cost) and the Source and Tag filters on both tabs; List offers the account's custom OnlyFans lists;
 *  - the Dashboard tab holds the capture's filters and seven KPI cards in its order (ticket 40): Total clicks, Total
 *    subs, the overall Subscription CVR and Total earnings are sums over the reads for the picked Creator ("—" with no
 *    data); Avg CPC, Avg CPS and Avg ROI are pooled over the links with a Promo cost ("—" without one); "Last
 *    updated: " says when the read landed;
 *  - switching the creator filter makes the next tracking-link read carry the second Creator's `account_id`;
 *  - the regrade's follow-up (ticket 59): the title carries the report time zone from the Applied settings, the tabs
 *    are the bundle's filled pill, the filters lead with their icons, the bundle's tooltips sit on the metric heads
 *    and four Dashboard cards, the update row and the house lines are labelled as ours, "Link copied" holds 5 s, and
 *    the table pages by 10 / 20 / 50.
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
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
// An owner session, so `useAccounts` reads `/admin/accounts` through the mocked relay.
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/UserContext")>()),
  useUser: () => ({ user: { user_id: "owner-1" } }),
}));
// The Applied settings read rides the Creator in scope; none here.
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/ChatterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => ({ chatter: null }),
}));

import GrowthTabPage from "@/components/growth/GrowthTabPage";
import { relay } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

/* ── the Layout capture, read from disk ─────────────────────────────────── */

const CAPTURE = readFileSync(
  resolve(__dirname, "../../../docs/infloww-layouts/growth-tracking-links.md"),
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

/* ── fixtures: two placeholder Creators, two OnlyFans links, one redirect ─ */

const A = { id: "1000001", nickname: "Creator A", has_session: true };
const B = { id: "1000002", nickname: "Creator B", has_session: true };

const LINK = (over: Record<string, unknown>) => ({
  id: 1, code: 11, name: "Link one", url: "https://example.test/c11", url_verified: false,
  clicks: 0, subscribers: 0, created_at: null, end_date: null, is_deleted: false, source: "onlyfans", ...over,
});
// Worked example: 25 subs over 200 clicks is a 12.50% Subscription CVR.
const LINKS = [
  LINK({ id: 1, code: 11, name: "Link one", clicks: 200, subscribers: 25, created_at: "2026-03-14T12:00:00Z" }),
  LINK({ id: 2, code: 12, name: "Link two", clicks: 0, subscribers: 0, created_at: null }),
];

let ofResult: { links: unknown[]; username: string | null; url_verified: boolean; of_available: boolean };
/** The earnings read (claimers x ledger); unavailable by default, so the earnings columns stay hidden. */
let earnings: { available: boolean; links: unknown[] };
/** The Details read for any link. */
let fansResult: unknown;
/** The Agency's report time zone in the Applied settings read. Asia/Kolkata has no daylight saving: UTC+05:30. */
let reportTz: string | null;
/** OnlyFans' lists read (the Edit dialog's List): two custom lists and a built-in, which is not offered. */
let fanLists: unknown[];
/** The Function permissions the Applied settings read says the role denies. */
let deniedActions: string[];

beforeEach(() => {
  deniedActions = [];
  ofResult = { links: LINKS, username: "creator_a", url_verified: false, of_available: true };
  earnings = { available: false, links: [] };
  fansResult = { fans: [] };
  reportTz = "Asia/Kolkata";
  fanLists = [
    { id: 900002, name: "Whales", type: "custom" },
    { id: "fans", name: "Fans", type: "build-in" },
    { id: 900001, name: "VIP", type: "custom" },
  ];
  for (const m of [relayGet, relayPost, relayPut, relayDelete]) m.mockReset();
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p === "/admin/accounts") return Promise.resolve({ accounts: [A, B], active_account_id: null });
    if (p === "/admin/settings/applied") {
      return Promise.resolve({
        preferences: { tz: null, report_tz: reportTz, week_start: "monday" },
        messaging: { ai_translation: true },
        permissions: { enforced: false, pages: null, scope: "all", denied_actions: deniedActions },
      });
    }
    if (p.startsWith("/api/of/v2/lists")) return Promise.resolve({ list: fanLists });
    if (p.startsWith("/admin/of-tracking-links/earnings")) return Promise.resolve(earnings);
    if (/^\/admin\/of-tracking-links\/\d+\/fans/.test(p)) return Promise.resolve(fansResult);
    if (p.startsWith("/admin/of-tracking-links")) return Promise.resolve(ofResult);
    if (p.startsWith("/admin/tracking-links")) {
      return Promise.resolve({
        links: [{ id: 7, name: "Redirect one", slug: "r1", path: "/t/r1", target_url: "https://example.test/", click_count: 3 }],
      });
    }
    return Promise.resolve({});
  });
  relayPost.mockResolvedValue({});
  relayPut.mockResolvedValue({});
  relayDelete.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Mount the route's page and wait for the first link row. */
async function mount() {
  renderWithProviders(<GrowthTabPage tab="tracking" />);
  await waitFor(() => expect(screen.getByText("Link one")).toBeTruthy());
}

/** The Links list table. */
function table(): HTMLTableElement {
  return screen.getByRole("table", { name: "Links list" }) as HTMLTableElement;
}

/** The header cells' text, in order. */
function headers(): string[] {
  return within(table()).getAllByRole("columnheader").map((th) => th.textContent?.trim() ?? "");
}

/** The body cell under header `title` in the row whose name is `name`. */
function cell(name: string, title: string): HTMLElement {
  const i = headers().indexOf(title);
  expect(i, `column ${title}`).toBeGreaterThanOrEqual(0);
  const row = within(table()).getByText(name).closest("tr") as HTMLElement;
  return within(row).getAllByRole("cell")[i];
}

/** Pick `option` in the listbox behind `combobox`: the HB selects are a button + listbox, not a native select. */
function choose(combobox: HTMLElement, option: string | RegExp) {
  fireEvent.click(combobox);
  fireEvent.click(screen.getByRole("option", { name: option }));
}

/** The options' text behind `combobox` (opens and closes it). */
function optionsOf(combobox: HTMLElement): string[] {
  fireEvent.click(combobox);
  const out = within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent ?? "");
  fireEvent.click(combobox);
  return out;
}

/** The capture's Links list columns after the selection column that the OnlyFans read fills (#37 to #41, #56, in
 *  #57's order). */
const COLUMNS: Array<{ id: string; title: string }> = [
  { id: "growth-tracking-links#37", title: "Tracking link" },
  { id: "growth-tracking-links#38", title: "Date created" },
  { id: "growth-tracking-links#39", title: "Clicks" },
  { id: "growth-tracking-links#40", title: "Subs" },
  { id: "growth-tracking-links#41", title: "Subscription CVR" },
  { id: "growth-tracking-links#56", title: "Actions" },
];

/** The capture's columns with no data behind them yet (#42 to #55): none of them draws. */
const NO_DATA_COLUMNS: Array<{ id: string; title: string }> = [
  { id: "growth-tracking-links#42", title: "Promo cost" },
  { id: "growth-tracking-links#43", title: "Earnings" },
  { id: "growth-tracking-links#44", title: "Fans who spent" },
  { id: "growth-tracking-links#45", title: "Spending CVR" },
  { id: "growth-tracking-links#46", title: "Profit" },
  { id: "growth-tracking-links#47", title: "CPC" },
  { id: "growth-tracking-links#48", title: "EPC" },
  { id: "growth-tracking-links#49", title: "CPS" },
  { id: "growth-tracking-links#50", title: "AEPS" },
  { id: "growth-tracking-links#51", title: "ROI" },
  { id: "growth-tracking-links#52", title: "Source" },
  { id: "growth-tracking-links#53", title: "Tag" },
  { id: "growth-tracking-links#54", title: "List" },
  { id: "growth-tracking-links#55", title: "Last updated" },
];

describe("Tracking links, in the capture's order", () => {
  it("shows the tabs, the tip, the filter bar and the create button in order, each label in the capture", async () => {
    await mount();
    const items = [
      { id: "growth-tracking-links#10", label: "Links list", el: screen.getByRole("tab", { name: "Links list" }) },
      { id: "growth-tracking-links#10", label: "Dashboard", el: screen.getByRole("tab", { name: "Dashboard" }) },
      {
        id: "growth-tracking-links#14",
        label: "Each fan's spending is always attributed to the last free trial link, tracking link or promotion campaign that has been clicked by the fan.",
        el: screen.getByText(/^Each fan's spending is always attributed/),
      },
      { id: "growth-tracking-links#15", label: "Learn more", el: screen.getByRole("button", { name: "Learn more" }) },
      { id: "growth-tracking-links#17", label: "Creator", el: screen.getByRole("combobox", { name: "Creator" }) },
      { id: "growth-tracking-links#18", label: "link name", el: screen.getByPlaceholderText("Search tracking link name") },
      { id: "growth-tracking-links#19", label: "Source", el: screen.getByRole("combobox", { name: "Source" }) },
      { id: "growth-tracking-links#20", label: "Tag", el: screen.getByRole("combobox", { name: "Tag" }) },
      { id: "growth-tracking-links#21", label: "Date created", el: screen.getByRole("group", { name: "Date created" }) },
      { id: "growth-tracking-links#24", label: "Show deactivated links", el: screen.getByRole("switch", { name: "Show deactivated links" }) },
      { id: "growth-tracking-links#27", label: "Create tracking link", el: screen.getByRole("button", { name: "Create tracking link" }) },
      { id: "growth-tracking-links#28", label: "Export", el: screen.getByRole("button", { name: "Export" }) },
      { id: "growth-tracking-links#34", label: "Table", el: table() },
    ];
    for (const it of items) expectInCapture(it.id, it.label);
    for (let i = 1; i < items.length; i++) expectBefore(items[i - 1].el, items[i].el);
  });

  it("opens on Links list, with Share links (#11) third for the owner", async () => {
    await mount();
    expect(screen.getByRole("tab", { name: "Links list" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Dashboard" }).getAttribute("aria-selected")).toBe("false");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Links list", "Dashboard", "Share links"]);
  });

  it("shows a selection column, then only the capture's columns that have data, in its order", async () => {
    await mount();
    const got = headers();
    // The selection column (#36) leads and has no title.
    expect(got[0]).toBe("");
    expect(got.slice(1)).toEqual(COLUMNS.map((c) => c.title));
    for (const c of COLUMNS) expectInCapture(c.id, `"${c.title}"`);
  });

  it("draws none of the columns with no data behind them, so the table does not run past Promo cost", async () => {
    await mount();
    for (const c of NO_DATA_COLUMNS) {
      expectInCapture(c.id, `"${c.title}"`);
      expect(headers(), c.title).not.toContain(c.title);
    }
    // Nothing on the page is a not-wired metric cell any more.
    for (const td of within(table()).getAllByRole("cell")) expect(td.getAttribute("title")).not.toBe("not wired");
  });

  it("does not draw \"Show net earnings\" while no earnings column has data", async () => {
    await mount();
    expectInCapture("growth-tracking-links#25", "Show net earnings");
    expect(screen.queryByRole("switch", { name: "Show net earnings" })).toBeNull();
  });

  it("disables every filter the read cannot drive, titled not wired", async () => {
    await mount();
    const notWired = [screen.getByRole("button", { name: "Learn more" })];
    for (const el of notWired) {
      expect((el as HTMLButtonElement).disabled, el.outerHTML).toBe(true);
      expect(el.getAttribute("title")).toBe("not wired");
    }
  });
});

describe("Links list rows from the OnlyFans read", () => {
  it("fills name, date created, clicks, subs and Subscription CVR from the read", async () => {
    await mount();
    expect(cell("Link one", "Clicks").textContent).toBe("200");
    expect(cell("Link one", "Subs").textContent).toBe("25");
    expect(cell("Link one", "Subscription CVR").textContent).toBe("12.50%");
    // Date only (#38): the year, and no time of day.
    expect(cell("Link one", "Date created").textContent).toMatch(/2026/);
    expect(cell("Link one", "Date created").textContent).not.toMatch(/:/);
    expect(within(cell("Link one", "Tracking link")).getByRole("button", { name: "Copy link" })).toBeTruthy();
  });

  it("shows — for CVR when a link has no clicks, and for a missing date", async () => {
    await mount();
    expect(cell("Link two", "Subscription CVR").textContent).toBe("—");
    expect(cell("Link two", "Date created").textContent).toBe("—");
  });

  it("prints Clicks and Subs with the bundle's thousands commas", async () => {
    ofResult.links = [LINK({ id: 1, name: "Link one", clicks: 1234567, subscribers: 4321 })];
    await mount();
    expect(cell("Link one", "Clicks").textContent).toBe("1,234,567");
    expect(cell("Link one", "Subs").textContent).toBe("4,321");
  });

  it("filters the rows by the search on the link name", async () => {
    await mount();
    fireEvent.change(screen.getByPlaceholderText("Search tracking link name"), { target: { value: "two" } });
    expect(within(table()).queryByText("Link one")).toBeNull();
    expect(within(table()).getByText("Link two")).toBeTruthy();
  });

  it("shows the capture's \"No data\" when there are no links", async () => {
    ofResult = { ...ofResult, links: [] };
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    expectInCapture("growth-tracking-links#65", "No data");
    await waitFor(() => expect(within(table()).getByText("No data")).toBeTruthy());
  });
});

/** Open the pop-up from the filter bar's create button. */
function openEditor(): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: "Create tracking link" }));
  return screen.getByRole("dialog", { name: "Create tracking link" });
}

describe("the Create tracking link pop-up", () => {
  it("is not inline: the filter bar has no name field until the button opens the pop-up", async () => {
    await mount();
    expect(screen.queryByRole("textbox", { name: "Tracking link name" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    openEditor();
    expect(screen.getByRole("textbox", { name: "Tracking link name" })).toBeTruthy();
  });

  it("shows the capture's title, fields and button in its order, each label in the capture", async () => {
    await mount();
    const dlg = openEditor();
    const items = [
      { id: "growth-tracking-links#69", label: "tracking link", el: within(dlg).getByRole("heading", { name: "Create tracking link" }) },
      { id: "growth-tracking-links#70", label: "Tracking link name", el: within(dlg).getByText("Tracking link name") },
      { id: "growth-tracking-links#71", label: "Source", el: within(dlg).getByText("Source") },
      { id: "growth-tracking-links#72", label: "Promo cost", el: within(dlg).getByText(/^Promo cost/) },
      { id: "growth-tracking-links#73", label: "Tag ", el: within(dlg).getByText(/^Tag/) },
      { id: "growth-tracking-links#73", label: "List ", el: within(dlg).getByText(/^List/) },
      { id: "growth-tracking-links#75", label: "Save", el: within(dlg).getByRole("button", { name: "Save" }) },
    ];
    for (const it of items) expectInCapture(it.id, it.label);
    expectInCapture("growth-tracking-links#69", "Create");
    // #74: name, Source, Promo cost, Tag, List.
    for (let i = 1; i < items.length; i++) expectBefore(items[i - 1].el, items[i].el);
    // #72, #73: "Optional" after Promo cost, Tag and List, and after Source, which Infloww requires and we do not
    // (the Edit dialog's fields, one definition); #70, #72: the length limits.
    expectInCapture("growth-tracking-links#72", "Optional");
    expect(within(dlg).getAllByText("Optional")).toHaveLength(4);
    expectInCapture("growth-tracking-links#70", "`maxLength:100`");
    expect(within(dlg).getByRole("textbox", { name: "Tracking link name" }).getAttribute("maxlength")).toBe("100");
    expectInCapture("growth-tracking-links#72", "maxLength:11");
    expect(within(dlg).getByRole("textbox", { name: "Promo cost Optional" }).getAttribute("maxlength")).toBe("11");
  });

  it("creates the link through the existing write, for the Creator the filter picked, and closes", async () => {
    await mount();
    choose(screen.getByRole("combobox", { name: "Creator" }), /Creator B$/);
    const dlg = openEditor();
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Tracking link name" }), { target: { value: "New link" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(relayPost).toHaveBeenCalledWith("/admin/of-tracking-links", { account_id: B.id, name: "New link" }),
    );
    expect(relayPost).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("says the capture's required-field words for an empty name and calls nothing", async () => {
    await mount();
    const dlg = openEditor();
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expectInCapture("growth-tracking-links#70", "This is a required field");
    expect(within(dlg).getByText("This is a required field")).toBeTruthy();
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("refuses a name a live link already has, in the bundle's words, and calls nothing", async () => {
    await mount();
    const dlg = openEditor();
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Tracking link name" }), { target: { value: "Link one" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect(within(dlg).getByText("This link name already exists. Enter a different one")).toBeTruthy();
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("sends Source, Promo cost, Tag and List with the name, in one request, and closes", async () => {
    await mount();
    const dlg = openEditor();
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Tracking link name" }), { target: { value: "Reddit May" } });
    const fields = [
      within(dlg).getByRole("combobox", { name: "Source Optional" }),
      within(dlg).getByRole("textbox", { name: "Promo cost Optional" }),
      within(dlg).getByRole("combobox", { name: "Tag Optional" }),
      within(dlg).getByRole("combobox", { name: "List Optional" }),
    ];
    for (const el of fields) {
      expect((el as HTMLInputElement).disabled, el.outerHTML).toBe(false);
      expect(el.getAttribute("title")).toBeNull();
    }
    fireEvent.change(fields[0], { target: { value: " Reddit " } });
    fireEvent.change(fields[1], { target: { value: "40" } });
    fireEvent.change(fields[2], { target: { value: "may" } });
    fireEvent.keyDown(fields[2], { key: "Enter" });
    const list = fields[3] as HTMLSelectElement;
    await waitFor(() => expect([...list.options].map((o) => o.textContent)).toEqual(["None", "VIP", "Whales"]));
    fireEvent.change(list, { target: { value: "900002" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/of-tracking-links", {
      account_id: A.id, name: "Reddit May", promo_cost: 40, source: "Reddit", tags: ["may"], list_id: "900002",
      list_name: "Whales",
    }));
    expect(relayPost).toHaveBeenCalledTimes(1);
    expect(relayPut).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("refuses a promo cost that is not an amount, and calls nothing", async () => {
    await mount();
    const dlg = openEditor();
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Tracking link name" }), { target: { value: "New link" } });
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Promo cost Optional" }), { target: { value: "12.345" } });
    expect(within(dlg).getByText(/Enter an amount/)).toBeTruthy();
    expect((within(dlg).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("says the fields were not saved when OnlyFans' reply carries no id, and keeps the pop-up open", async () => {
    relayPost.mockResolvedValue({ id: null, name: "Lost", meta_saved: false });
    await mount();
    const dlg = openEditor();
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Tracking link name" }), { target: { value: "Lost" } });
    fireEvent.change(within(dlg).getByRole("combobox", { name: "Source Optional" }), { target: { value: "X" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect((await within(dlg).findByRole("alert")).textContent)
      .toBe("Link created; Source, Promo cost, Tag and List weren't saved. Use Edit.");
    expect(relayPost).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("closes on Cancel and calls nothing", async () => {
    await mount();
    const dlg = openEditor();
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Tracking link name" }), { target: { value: "New link" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // The title row's close does the same.
    fireEvent.click(within(openEditor()).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(relayPost).not.toHaveBeenCalled();
  });
});

/** The Actions cell of the row named `name`. */
function actions(name: string): HTMLElement {
  return cell(name, "Actions");
}

describe("the row Actions", () => {
  it("are the capture's Details, Edit and dots menu, in its order", async () => {
    await mount();
    for (const label of ["\"Details\"", "\"Edit\"", "`DotsVerticalLine` menu"]) expectInCapture("growth-tracking-links#62", label);
    const btns = within(actions("Link one")).getAllByRole("button");
    expect(btns.map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([
      "Details", "Edit Link one", "More actions for Link one",
    ]);
    expect((btns[0] as HTMLButtonElement).disabled).toBe(false);
    expect((btns[1] as HTMLButtonElement).disabled).toBe(false);
    expect((btns[2] as HTMLButtonElement).disabled).toBe(false);
  });

  /** Open the dots menu of the row named `name` and return its Deactivate item. */
  function deactivateItem(name: string): HTMLButtonElement {
    fireEvent.click(within(actions(name)).getByRole("button", { name: `More actions for ${name}` }));
    const items = within(screen.getByRole("menu")).getAllByRole("menuitem");
    // Infloww's menu holds Deactivate alone: no second "Delete on OnlyFans" entry.
    expect(items.map((i) => i.textContent)).toEqual(["Deactivate"]);
    return items[0] as HTMLButtonElement;
  }

  it("asks the bundle's confirm on Deactivate, then deletes the link on OnlyFans", async () => {
    await mount();
    expectInCapture("growth-tracking-links#62", "\"Deactivate\"");
    const confirmSpy = vi.spyOn(window, "confirm");
    const item = deactivateItem("Link one");
    expect(item.disabled).toBe(false);
    fireEvent.click(item);
    expect(screen.queryByRole("menu")).toBeNull();
    expectInCapture("growth-tracking-links#64", "`Deactivate link, ${Mt}?`");
    expectInCapture("growth-tracking-links#64", "This action is permanent");
    const dlg = screen.getByRole("dialog", { name: "Deactivate link, Link one?" });
    expect(dlg.textContent).toContain(
      "Data from the tracking link is no longer tracked when the link is deactivated. This action is permanent and cannot be undone.",
    );
    expect(relayDelete).not.toHaveBeenCalled();
    fireEvent.click(within(dlg).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(`/admin/of-tracking-links/1?account_id=${A.id}`));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("deactivates nothing when the confirm is cancelled", async () => {
    await mount();
    fireEvent.click(deactivateItem("Link one"));
    fireEvent.click(within(screen.getByRole("dialog", { name: /^Deactivate link/ })).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(relayDelete).not.toHaveBeenCalled();
  });

  it("keeps the confirm open with the bundle's words when the delete fails", async () => {
    relayDelete.mockRejectedValue(new Error("502"));
    await mount();
    fireEvent.click(deactivateItem("Link one"));
    const dlg = screen.getByRole("dialog", { name: /^Deactivate link/ });
    fireEvent.click(within(dlg).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(within(dlg).getByText("Unable to deactivate tracking link. Try again later")).toBeTruthy());
  });
});

describe("deactivated links", () => {
  beforeEach(() => {
    ofResult.links = [
      ...LINKS,
      LINK({ id: 3, code: 13, name: "Old link", clicks: 9, subscribers: 2, is_deleted: true, end_date: "2026-09-21 03:01:31" }),
    ];
  });

  it("hides them until \"Show deactivated links\" is on, then shows them with the bundle's chip and no copy", async () => {
    await mount();
    const sw = screen.getByRole("switch", { name: "Show deactivated links" }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false);
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(within(table()).queryByText("Old link")).toBeNull();
    fireEvent.click(sw);
    expect(sw.getAttribute("aria-checked")).toBe("true");
    const name = cell("Old link", "Tracking link");
    expectInCapture("growth-tracking-links#58", "the \"Deactivated\" chip");
    expect(within(name).getByText("Deactivated")).toBeTruthy();
    expect(within(name).queryByRole("button", { name: "Copy link" })).toBeNull();
    // Its counts survive the delete.
    expect(cell("Old link", "Clicks").textContent).toBe("9");
    // A live row keeps its copy and has no chip.
    expect(within(cell("Link one", "Tracking link")).queryByText("Deactivated")).toBeNull();
    fireEvent.click(sw);
    expect(within(table()).queryByText("Old link")).toBeNull();
  });

  it("disables Deactivate on a deactivated link", async () => {
    await mount();
    fireEvent.click(screen.getByRole("switch", { name: "Show deactivated links" }));
    expect(deactivateItemOf("Old link").disabled).toBe(true);
  });

  it("leaves them out of the Dashboard totals", async () => {
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const card = within(panel).getByText("Total clicks").closest("[data-kpi]") as HTMLElement;
    await waitFor(() => expect(card.lastElementChild?.textContent).toBe("200"));
  });
});

/** The dots menu's Deactivate item of the row named `name`. */
function deactivateItemOf(name: string): HTMLButtonElement {
  fireEvent.click(within(actions(name)).getByRole("button", { name: `More actions for ${name}` }));
  return within(screen.getByRole("menu")).getByRole("menuitem", { name: "Deactivate" }) as HTMLButtonElement;
}

describe("the Date created filter", () => {
  const DAY = 86_400_000;
  /** An ISO time `days` days ago. */
  const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

  it("filters the rows by a typed range on the day created, and leaves out links with no date", async () => {
    await mount();
    const group = screen.getByRole("group", { name: "Date created" });
    fireEvent.change(within(group).getByLabelText("Start date"), { target: { value: "2026-03-01" } });
    fireEvent.change(within(group).getByLabelText("End date"), { target: { value: "2026-03-31" } });
    expect(within(table()).getByText("Link one")).toBeTruthy();
    expect(within(table()).queryByText("Link two")).toBeNull();
    fireEvent.change(within(group).getByLabelText("End date"), { target: { value: "2026-03-13" } });
    expect(within(table()).getByText("No data")).toBeTruthy();
    fireEvent.click(within(group).getByRole("button", { name: "Clear date created" }));
    expect(within(table()).getByText("Link one")).toBeTruthy();
    expect(within(table()).getByText("Link two")).toBeTruthy();
  });

  it("offers the bundle's six presets, and Last 7 days runs from 7 days ago to yesterday", async () => {
    ofResult.links = [
      LINK({ id: 1, name: "Three days old", created_at: ago(3) }),
      LINK({ id: 2, name: "Twenty days old", created_at: ago(20) }),
      LINK({ id: 3, name: "Made today", created_at: new Date().toISOString() }),
    ];
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(screen.getByText("Made today")).toBeTruthy());
    const presets = screen.getByRole("combobox", { name: "Date created presets" }) as HTMLSelectElement;
    const labels = Array.from(presets.options).filter((o) => o.value).map((o) => o.textContent);
    expect(labels).toEqual(["Today", "Yesterday", "Last 7 days", "Last 30 days", "Last 6 months", "Last 12 months"]);
    for (const l of labels) expectInCapture("growth-tracking-links#23", `"${l}"`);
    fireEvent.change(presets, { target: { value: "Last 7 days" } });
    expect(presets.value).toBe("Last 7 days");
    expect(within(table()).getByText("Three days old")).toBeTruthy();
    expect(within(table()).queryByText("Twenty days old")).toBeNull();
    expect(within(table()).queryByText("Made today")).toBeNull();
    fireEvent.change(presets, { target: { value: "Last 30 days" } });
    expect(within(table()).getByText("Twenty days old")).toBeTruthy();
    fireEvent.change(presets, { target: { value: "Today" } });
    expect(within(table()).getByText("Made today")).toBeTruthy();
    expect(within(table()).queryByText("Three days old")).toBeNull();
  });
});

describe("Export", () => {
  it("downloads a CSV of the filtered rows, every page, with the columns shown", async () => {
    let blob: Blob | null = null;
    // jsdom has no object URLs: lend them for this test and put the originals back after.
    const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn((b: Blob) => { blob = b; return "blob:tracking-links"; });
    URL.revokeObjectURL = vi.fn();
    try {
      const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
      ofResult.links = [
        LINK({ id: 1, name: "Big, link", url: "https://example.test/c1", clicks: 1200, subscribers: 30, created_at: "2026-03-14T12:00:00Z" }),
        LINK({ id: 2, name: "Other", url: "https://example.test/c2", clicks: 0, subscribers: 0 }),
      ];
      renderWithProviders(<GrowthTabPage tab="tracking" />);
      await waitFor(() => expect(screen.getByText("Big, link")).toBeTruthy());
      fireEvent.change(screen.getByPlaceholderText("Search tracking link name"), { target: { value: "big" } });
      const btn = screen.getByRole("button", { name: "Export" });
      expect(btn.getAttribute("title")?.startsWith(EXTRA_LABEL)).toBe(true);
      fireEvent.click(btn);
      expect(click).toHaveBeenCalledTimes(1);
      expect(blob!.type).toBe("text/csv;charset=utf-8");
      expect(await blob!.text()).toBe(
        "Tracking link,Link,Date created,Clicks,Subs,Subscription CVR\n" +
        "\"Big, link\",https://example.test/c1,2026-03-14,1200,30,2.50%",
      );
    } finally {
      URL.createObjectURL = saved.create;
      URL.revokeObjectURL = saved.revoke;
    }
  });

  it("is disabled with no rows to export", async () => {
    ofResult = { ...ofResult, links: [] };
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(within(table()).getByText("No data")).toBeTruthy());
    expect((screen.getByRole("button", { name: "Export" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("is not offered to a role denied Export CSV", async () => {
    deniedActions = ["/growth/tracking-links#export"];
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(screen.getByText("Link one")).toBeTruthy());
    await waitFor(() => expect(screen.queryByRole("button", { name: "Export" })).toBeNull());
  });
});

describe("our notes and extras", () => {
  it("puts the redirect links in one section carrying EXTRA_LABEL, after the table", async () => {
    await mount();
    const section = screen.getByRole("region", { name: /Custom redirect links/ });
    expect(within(section).getByTitle(EXTRA_LABEL)).toBeTruthy();
    expectBefore(table(), section);
    expectBefore(screen.getByRole("button", { name: "Create tracking link" }), section);
    // Its existing body: open it, and the redirect read's link is listed.
    fireEvent.click(within(section).getByRole("button", { name: /Custom redirect links/ }));
    await waitFor(() => expect(within(section).getByText("Redirect one")).toBeTruthy());
  });

  it("draws no \"Confirm the link once\" note: the URL is built as OnlyFans' own Copy-link builds it", async () => {
    await mount();
    expect(screen.queryByText(/Confirm the link once\./)).toBeNull();
  });

  it("says OnlyFans is not reachable when the read says so", async () => {
    ofResult = { links: [], username: null, url_verified: false, of_available: false };
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(screen.getByText(/OnlyFans not reachable/)).toBeTruthy());
  });
});

describe("the Dashboard tab", () => {
  const KPIS = ["Total clicks", "Avg CPC", "Total subs", "Avg CPS", "Subscription CVR", "Total earnings", "Avg ROI"];
  const AVG_KPIS = ["Avg CPC", "Avg CPS", "Avg ROI"];

  /** Mount the route's page, open the Dashboard tab and return its panel. */
  async function dashboard(): Promise<HTMLElement> {
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dashboard" }));
    return screen.getByRole("tabpanel", { name: "Dashboard" });
  }

  /** The KPI card titled `title`. */
  function card(panel: HTMLElement, title: string): HTMLElement {
    return within(panel).getByText(title).closest("[data-kpi]") as HTMLElement;
  }

  /** The value a KPI card shows, under its title. */
  function value(panel: HTMLElement, title: string): string {
    return card(panel, title).lastElementChild?.textContent ?? "";
  }

  it("shows the capture's filters, its seven KPI cards in order, then \"Last updated: \", each label in the capture", async () => {
    const panel = await dashboard();
    // The bundle's `LinkDashboard` renders the filters, the cards, then the update line under them.
    const items = [
      { id: "growth-tracking-links#80", label: '"Creator"', el: within(panel).getByRole("combobox", { name: "Creator" }) },
      { id: "growth-tracking-links#80", label: '"Source"', el: within(panel).getByRole("combobox", { name: "Source" }) },
      { id: "growth-tracking-links#80", label: '"Tag"', el: within(panel).getByRole("combobox", { name: "Tag" }) },
      ...KPIS.map((t) => ({ id: "growth-tracking-links#77", label: `"${t}"`, el: card(panel, t) })),
      { id: "growth-tracking-links#80", label: '"Last updated: "', el: within(panel).getByText(/^Last updated: /) },
    ];
    for (const it of items) expectInCapture(it.id, it.label);
    for (let i = 1; i < items.length; i++) expectBefore(items[i - 1].el, items[i].el);
    expect(screen.queryByRole("table", { name: "Links list" })).toBeNull();
  });

  it("computes Total clicks, Total subs and the overall Subscription CVR from the read, for the picked Creator", async () => {
    // Worked example: 1200 + 800 + 0 clicks is 2,000 (the bundle's thousands commas), 300 + 100 + 0 subs is 400, and
    // 400 over 2,000 is a 20.00% CVR over the whole read, not the mean of the links' own CVRs.
    ofResult.links = [
      LINK({ id: 1, name: "Link one", clicks: 1200, subscribers: 300 }),
      LINK({ id: 2, name: "Link two", clicks: 800, subscribers: 100 }),
      LINK({ id: 3, name: "Link three", clicks: 0, subscribers: 0 }),
    ];
    const panel = await dashboard();
    await waitFor(() => expect(value(panel, "Total clicks")).toBe("2,000"));
    expect(value(panel, "Total subs")).toBe("400");
    expect(value(panel, "Subscription CVR")).toBe("20.00%");
    for (const t of ["Total clicks", "Total subs", "Subscription CVR"]) {
      expect(card(panel, t).getAttribute("title"), t).toBeNull();
    }
    expect(relayGet).toHaveBeenCalledWith(`/admin/of-tracking-links?account_id=${A.id}`);
  });

  it("shows — for Subscription CVR when there are no clicks", async () => {
    ofResult.links = [LINK({ id: 1, name: "Link one", clicks: 0, subscribers: 0 })];
    const panel = await dashboard();
    await waitFor(() => expect(value(panel, "Total clicks")).toBe("0"));
    expect(value(panel, "Total subs")).toBe("0");
    expect(value(panel, "Subscription CVR")).toBe("—");
  });

  it("shows — for every total when OnlyFans is not reachable, never a zero", async () => {
    ofResult = { links: [], username: null, url_verified: false, of_available: false };
    const panel = await dashboard();
    await waitFor(() => expect(within(panel).getByText(/OnlyFans not reachable/)).toBeTruthy());
    for (const t of ["Total clicks", "Total subs", "Subscription CVR"]) expect(value(panel, t), t).toBe("—");
  });

  it("shows — on Avg CPC, Avg CPS and Avg ROI while no link has a Promo cost, and titles no tile not wired", async () => {
    const panel = await dashboard();
    // The fixture's Link one (200 clicks) and Link two (0 clicks), neither with a cost.
    await waitFor(() => expect(value(panel, "Total clicks")).toBe("200"));
    for (const t of AVG_KPIS) {
      expect(card(panel, t).getAttribute("title"), t).toBeNull();
      expect(value(panel, t), t).toBe("—");
    }
    // The earnings read is unavailable here: "—", never $0.00.
    expect(card(panel, "Total earnings").getAttribute("title")).toBeNull();
    expect(value(panel, "Total earnings")).toBe("—");
    // No earnings data, so no net switch to flip.
    expect(within(panel).queryByRole("switch", { name: "Show net earnings" })).toBeNull();
  });

  it("says when the read landed after \"Last updated: \"", async () => {
    const panel = await dashboard();
    await waitFor(() => expect(value(panel, "Total clicks")).toBe("200"));
    const updated = within(panel).getByText(/^Last updated: /);
    expect(updated.textContent).not.toBe("Last updated: —");
    expect(updated.textContent).toMatch(/\d{4}/);
    expect(updated.getAttribute("title")).toBeNull();
  });

  it("switches the Creator from its own filter, and the totals follow the second Creator's read", async () => {
    const panel = await dashboard();
    await waitFor(() => expect(value(panel, "Total clicks")).toBe("200"));
    relayGet.mockClear();
    // Worked example for Creator B: 5 subs over 50 clicks is a 10.00% CVR.
    ofResult = {
      links: [LINK({ id: 9, name: "Link nine", clicks: 50, subscribers: 5 })],
      username: "creator_b", url_verified: false, of_available: true,
    };
    choose(within(panel).getByRole("combobox", { name: "Creator" }), /Creator B$/);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith(`/admin/of-tracking-links?account_id=${B.id}`));
    const after = screen.getByRole("tabpanel", { name: "Dashboard" });
    await waitFor(() => expect(value(after, "Total clicks")).toBe("50"));
    expect(value(after, "Total subs")).toBe("5");
    expect(value(after, "Subscription CVR")).toBe("10.00%");
  });
});

describe("the creator filter", () => {
  it("moves out of the page header into the filter bar", async () => {
    await mount();
    expect(screen.queryByText("Account")).toBeNull();
    expect(screen.getAllByRole("combobox", { name: "Creator" })).toHaveLength(1);
  });

  it("makes the next tracking-link read carry the second Creator's account_id", async () => {
    await mount();
    expect(relayGet).toHaveBeenCalledWith(`/admin/of-tracking-links?account_id=${A.id}`);
    relayGet.mockClear();
    choose(screen.getByRole("combobox", { name: "Creator" }), /Creator B$/);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith(`/admin/of-tracking-links?account_id=${B.id}`));
    expect(relayGet).not.toHaveBeenCalledWith(`/admin/of-tracking-links?account_id=${A.id}`);
  });
});

/* ── ticket 59: the regrade's follow-up ─────────────────────────────────── */

describe("the page header (ticket 59)", () => {
  it("carries the report time zone after the title, with its info icon and \"Set by your organization\"", async () => {
    await mount();
    const zone = await screen.findByText("UTC+05:30");
    const title = screen.getByRole("heading", { level: 1, name: "Tracking links" });
    expectBefore(title, zone);
    const tip = screen.getByTitle("Set by your organization");
    expectBefore(zone, tip);
    expect(tip.querySelector("svg")).toBeTruthy();
    expectInCapture("growth-tracking-links#9", "Set by your organization");
    expectInCapture("growth-tracking-links#8", "InfoCircleLine,{size:16}");
  });

  it("prints Date created in the report time zone the header names", async () => {
    // 20:00 UTC on 14 March is 01:30 on 15 March in Asia/Kolkata.
    ofResult.links = [LINK({ id: 1, name: "Late link", created_at: "2026-03-14T20:00:00Z" })];
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await screen.findByText("UTC+05:30");
    await waitFor(() => expect(cell("Late link", "Date created").textContent).toBe("3/15/2026"));
  });

  it("sets the title 24px weight 500 in a 16px-padded header, on this page only (#4, #5)", async () => {
    await mount();
    const title = screen.getByRole("heading", { level: 1, name: "Tracking links" });
    expect(title.classList.contains("font-medium")).toBe(true);
    expect(title.classList.contains("font-semibold")).toBe(false);
    expect(title.closest("header")?.classList.contains("p-4")).toBe(true);
    cleanup();
    renderWithProviders(<GrowthTabPage tab="smart" />);
    expect(screen.getByRole("heading", { level: 1, name: "Smart lists" }).classList.contains("font-semibold")).toBe(true);
  });
});

describe("the tabs, filters and tooltips (ticket 59)", () => {
  it("draws the tabs as the bundle's toggle buttons: the selected one filled, none underlined", async () => {
    await mount();
    const on = screen.getByRole("tab", { name: "Links list" });
    const off = screen.getByRole("tab", { name: "Dashboard" });
    // HB's toggle-active fill, #2c2c2c in dark.
    expect(on.classList.contains("bg-[#2c2c2c]")).toBe(true);
    expect(off.classList.contains("bg-[#2c2c2c]")).toBe(false);
    for (const t of [on, off]) {
      expect(t.classList.contains("h-9")).toBe(true);
      expect(t.classList.contains("border-b-2")).toBe(false);
    }
    expect(screen.getByRole("tablist").classList.contains("border-b")).toBe(false);
  });

  it("leads the search, Source, Tag and Date created controls with their icons", async () => {
    await mount();
    const controls = [
      screen.getByPlaceholderText("Search tracking link name"),
      within(screen.getByRole("group", { name: "Date created" })).getByText("Date created"),
    ];
    // Source and Tag are HB selects: the lead icon sits inside the button, before the label and the chevron.
    for (const name of ["Source", "Tag"]) {
      const cb = screen.getByRole("combobox", { name });
      const svgs = cb.querySelectorAll("svg");
      expect(svgs.length, name).toBe(2);
      expect(svgs[0].getAttribute("aria-hidden")).toBe("true");
      expectBefore(svgs[0], within(cb).getByText(name));
    }
    for (const c of controls) {
      const icon = c.parentElement?.querySelector("svg");
      expect(icon, c.outerHTML).toBeTruthy();
      expect(icon?.getAttribute("aria-hidden")).toBe("true");
      expectBefore(icon!, c);
    }
  });

  it("puts the bundle's tooltip on the Subscription CVR head, and on no count", async () => {
    await mount();
    const ths = within(table()).getAllByRole("columnheader");
    const th = (t: string) => ths[headers().indexOf(t)];
    expect(within(th("Subscription CVR")).getByTitle(
      "Subscription conversion rate: Percentage of clicks that become subscribers. Includes those who signed up for free trial subscription through the tracking link",
    ).querySelector("svg")).toBeTruthy();
    for (const t of ["Tracking link", "Date created", "Clicks", "Subs"]) expect(th(t).querySelector("svg"), t).toBeNull();
  });

  it("puts the bundle's tooltip on the Avg CPC, Avg CPS, Subscription CVR and Avg ROI cards only", async () => {
    await mount();
    fireEvent.click(screen.getByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const card = (t: string) => within(panel).getByText(t).closest("[data-kpi]") as HTMLElement;
    const tips: Record<string, string> = {
      "Avg CPC": "Cost per click: Promo cost divided by number of clicks",
      "Avg CPS": "Cost per subscriber: Promo cost divided by number of subscribers, including those on free trial; average acquisition cost of a subscriber",
      "Subscription CVR": "Subscription conversion rate: Percentage of clicks that become subscribers. Includes those who signed up for free trial subscription through the tracking link",
      "Avg ROI": "Return of investment: Profit divided by Promo cost, multiplied by 100.",
    };
    for (const [t, tip] of Object.entries(tips)) expect(within(card(t)).getByTitle(tip), t).toBeTruthy();
    for (const t of ["Total clicks", "Total subs", "Total earnings"]) expect(card(t).querySelector("svg"), t).toBeNull();
  });
});

describe("the update row, copy feedback, pager and house lines (ticket 59)", () => {
  it("says when the links were last read from OnlyFans, labelled as ours, above the table, never the bundle's 2 hours", async () => {
    await mount();
    const row = screen.getByText(/^Last read from OnlyFans at /);
    expect(within(row.parentElement as HTMLElement).getByTitle(EXTRA_LABEL)).toBeTruthy();
    expectBefore(row, table());
    expect(screen.queryByText(/once every 2 hours/)).toBeNull();
  });

  it("says \"Link copied\" for 5 s after a copy, then \"Copy link\" again (#61)", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await mount();
    expectInCapture("growth-tracking-links#61", "Link copied");
    vi.useFakeTimers();
    try {
      const btn = within(cell("Link one", "Tracking link")).getByRole("button", { name: "Copy link" });
      await act(async () => { fireEvent.click(btn); });
      expect(writeText).toHaveBeenCalledWith("https://example.test/c11");
      expect(btn.textContent).toBe("Link copied");
      act(() => { vi.advanceTimersByTime(4999); });
      expect(btn.textContent).toBe("Link copied");
      act(() => { vi.advanceTimersByTime(1); });
      expect(btn.textContent).toBe("Copy link");
    } finally {
      vi.useRealTimers();
    }
  });

  it("pages the rows 50 at a time by default, by 10 / 20 / 50 (#66)", async () => {
    ofResult.links = Array.from({ length: 12 }, (_, i) => LINK({ id: i + 1, code: 100 + i, name: `Row ${i + 1}` }));
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(screen.getByText("Row 12")).toBeTruthy());
    expectInCapture("growth-tracking-links#66", 'PAGE_SIZE_OPTIONS=["10","20","50"];const DEFAULT_PAGE_SIZE=50');
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    const size = screen.getByRole("combobox", { name: "Per page" });
    expect(size.textContent).toBe("50");
    expect(optionsOf(size)).toEqual(["10", "20", "50"]);
    choose(size, "10");
    expect(within(table()).getByText("Row 10")).toBeTruthy();
    expect(within(table()).queryByText("Row 11")).toBeNull();
    fireEvent.click(within(pager).getByRole("button", { name: "Page 2" }));
    expect(within(table()).queryByText("Row 1")).toBeNull();
    expect(within(table()).getByText("Row 11")).toBeTruthy();
    expect(within(table()).getByText("Row 12")).toBeTruthy();
    expect((within(pager).getByRole("button", { name: "Next page" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(pager).getByRole("button", { name: "Previous page" }));
    expect(within(table()).getByText("Row 1")).toBeTruthy();
  });

  it("shows no pager when there are no rows, as the bundle's", async () => {
    ofResult = { ...ofResult, links: [] };
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(within(table()).getByText("No data")).toBeTruthy());
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
  });

  it("labels the house lines that stand in for the bundle's reconnect state as ours (#68)", async () => {
    ofResult = { links: [], username: null, url_verified: false, of_available: false };
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    const line = await screen.findByText(/OnlyFans not reachable/);
    expect(within(line).getByTitle(EXTRA_LABEL)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Dashboard" }));
    const dash = await within(screen.getByRole("tabpanel", { name: "Dashboard" })).findByText(/OnlyFans not reachable/);
    expect(within(dash).getByTitle(EXTRA_LABEL)).toBeTruthy();
  });

  it("labels the house loading row as ours", async () => {
    relayGet.mockImplementation((path: string) =>
      String(path) === "/admin/accounts"
        ? Promise.resolve({ accounts: [A, B], active_account_id: null })
        : new Promise(() => {}),
    );
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    const row = await screen.findByText(/^Loading/);
    expect(within(row.closest("td") as HTMLElement).getByTitle(EXTRA_LABEL)).toBeTruthy();
  });
});

describe("earnings: claimers x the ledger", () => {
  // Worked example: Link one (200 clicks, 25 subs) earned $1,234.50 gross / $987.60 net from 5 fans who spent.
  // EPC is $1,234.50 / 200 = $6.17 (net $4.94), AEPS / 25 = $49.38 (net $39.50), Spending CVR 5 / 25 = 20.00%.
  // Link two has no subs and earned $0.00; its EPC and AEPS are "—" (nothing to divide by).
  beforeEach(() => {
    earnings = {
      available: true,
      links: [
        { id: 1, earnings_cents: 123450, earnings_net_cents: 98760, fans_who_spent: 5, fans_counted: 25, net_missing_count: 0 },
        { id: 2, earnings_cents: 0, earnings_net_cents: 0, fans_who_spent: 0, fans_counted: 0, net_missing_count: 0 },
      ],
    };
  });

  async function mountWithEarnings() {
    await mount();
    await waitFor(() => expect(headers()).toContain("Earnings"));
  }

  it("draws Earnings, Fans who spent, Spending CVR, EPC and AEPS in the capture's order, net by default", async () => {
    await mountWithEarnings();
    expect(headers().slice(1)).toEqual([
      "Tracking link", "Date created", "Clicks", "Subs", "Subscription CVR", "Earnings", "Fans who spent", "Spending CVR", "EPC", "AEPS",
      "Actions",
    ]);
    expect(relayGet).toHaveBeenCalledWith(`/admin/of-tracking-links/earnings?account_id=${A.id}`);
    expect(screen.getByRole("switch", { name: "Show net earnings" }).getAttribute("aria-checked")).toBe("true");
    expect(cell("Link one", "Earnings").textContent).toBe("$987.60");
    expect(cell("Link one", "Fans who spent").textContent).toBe("5");
    expect(cell("Link one", "Spending CVR").textContent).toBe("20.00%");
    expect(cell("Link one", "EPC").textContent).toBe("$4.94");
    expect(cell("Link one", "AEPS").textContent).toBe("$39.50");
    expect(cell("Link two", "Earnings").textContent).toBe("$0.00");
    expect(cell("Link two", "EPC").textContent).toBe("—");
    expect(cell("Link two", "AEPS").textContent).toBe("—");
  });

  it("fits every drawn column in a 1600px window's 1,316px panel, so nothing hides under the sticky Actions", async () => {
    // Live check 2026-10-18: the capture's widths for these eleven heads summed to 1,718px and scrolled at 1600px.
    await mountWithEarnings();
    const ths = within(screen.getByRole("table", { name: "Links list" })).getAllByRole("columnheader");
    const sum = ths.reduce((n, th) => n + (parseInt(th.style.width, 10) || 48), 0);
    expect(ths).toHaveLength(12);
    expect(sum).toBeLessThanOrEqual(1316);
  });

  it("switches every money cell to gross with Show net earnings off, and the Dashboard follows the same switch", async () => {
    await mountWithEarnings();
    fireEvent.click(screen.getByRole("switch", { name: "Show net earnings" }));
    expect(cell("Link one", "Earnings").textContent).toBe("$1,234.50");
    expect(cell("Link one", "EPC").textContent).toBe("$6.17");
    expect(cell("Link one", "AEPS").textContent).toBe("$49.38");
    // One state across the tabs, as the bundle's `getSharedValues`.
    fireEvent.click(screen.getByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const sw = within(panel).getByRole("switch", { name: "Show net earnings" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    const total = () => (within(panel).getByText("Total earnings").closest("[data-kpi]") as HTMLElement).lastElementChild?.textContent;
    expect(total()).toBe("$1,234.50");
    fireEvent.click(sw);
    expect(total()).toBe("$987.60");
  });

  it("shows — for a link OnlyFans failed on, and the rest of the row still fills", async () => {
    earnings.links = [
      { id: 1, earnings_cents: 5000, earnings_net_cents: 4000, fans_who_spent: 1, fans_counted: 1, net_missing_count: 0 },
      { id: 2, earnings_cents: null, earnings_net_cents: null, fans_who_spent: null, fans_counted: null, net_missing_count: 0 },
    ];
    await mountWithEarnings();
    expect(cell("Link two", "Earnings").textContent).toBe("—");
    expect(cell("Link two", "Fans who spent").textContent).toBe("—");
    expect(cell("Link two", "Clicks").textContent).toBe("0");
  });

  it("keeps the earnings columns and the net switch hidden while the earnings read is unavailable", async () => {
    earnings = { available: false, links: [] };
    await mount();
    expect(headers()).not.toContain("Earnings");
    expect(screen.queryByRole("switch", { name: "Show net earnings" })).toBeNull();
  });

  it("marks a net Earnings figure partial when OnlyFans has no net for some of its transactions", async () => {
    (earnings.links[0] as Record<string, unknown>).net_missing_count = 2;
    await mountWithEarnings();
    const c = cell("Link one", "Earnings");
    expect(c.textContent).toBe("$987.60 *");
    expect(c.getAttribute("title")).toMatch(/^Partial/);
    // Gross has every cent: no marker.
    fireEvent.click(screen.getByRole("switch", { name: "Show net earnings" }));
    expect(cell("Link one", "Earnings").textContent).toBe("$1,234.50");
    expect(cell("Link one", "Earnings").getAttribute("title")).toBeNull();
  });

  it("uses the link's claimers for Spending CVR and AEPS, the fans its numerators are counted from", async () => {
    // 5 of 20 claimers spent (25.00%), $1,234.50 gross over 20 is $61.73; Subs (25) is OnlyFans' own count.
    (earnings.links[0] as Record<string, unknown>).fans_counted = 20;
    await mountWithEarnings();
    fireEvent.click(screen.getByRole("switch", { name: "Show net earnings" }));
    expect(cell("Link one", "Spending CVR").textContent).toBe("25.00%");
    expect(cell("Link one", "AEPS").textContent).toBe("$61.73");
  });

  it("sums Total earnings over every link, deactivated ones too, and marks it partial when a link has no figure", async () => {
    ofResult.links = [
      ...LINKS,
      LINK({ id: 3, code: 13, name: "Link gone", clicks: 50, subscribers: 4, is_deleted: true }),
      LINK({ id: 4, code: 14, name: "Link failed", clicks: 1, subscribers: 1 }),
    ];
    earnings.links = [
      ...earnings.links,
      { id: 3, earnings_cents: 10000, earnings_net_cents: 8000, fans_who_spent: 1, fans_counted: 4, net_missing_count: 0 },
      { id: 4, earnings_cents: null, earnings_net_cents: null, fans_who_spent: null, fans_counted: null, net_missing_count: 0 },
    ];
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const value = () => (within(panel).getByText("Total earnings").closest("[data-kpi]") as HTMLElement).lastElementChild as HTMLElement;
    // Net: $987.60 + $0.00 + $80.00 = $1,067.60, partial because Link failed has no figure.
    await waitFor(() => expect(value().textContent).toBe("$1,067.60 *"));
    expect(value().getAttribute("title")).toMatch(/^Partial/);
    // Clicks stay over the live links: 200 + 0 + 1.
    expect((within(panel).getByText("Total clicks").closest("[data-kpi]") as HTMLElement).lastElementChild?.textContent).toBe("201");
  });

  it("opens Details: the link's fans with Total, Subs, Posts, Messages, Streams, Tips, a Total: row and a fan search", async () => {
    const fan = (id: number, name: string, c: Record<string, number>, over: Record<string, unknown> = {}) => {
      const keys = ["subs", "posts", "messages", "streams", "tips", "other"];
      const row: Record<string, unknown> = { fan_id: id, name, username: `u${id}`, net_missing_count: 0, also_claimed_by: [] };
      for (const k of keys) { row[`${k}_cents`] = c[k] ?? 0; row[`${k}_net_cents`] = Math.round((c[k] ?? 0) * 0.8); }
      row.total_cents = keys.reduce((t, k) => t + (c[k] ?? 0), 0);
      row.total_net_cents = keys.reduce((t, k) => t + Math.round((c[k] ?? 0) * 0.8), 0);
      return { ...row, ...over };
    };
    fansResult = {
      fans: [
        fan(11, "Alice", { subs: 1000, messages: 2500, tips: 500 }),
        fan(12, "Bob", { posts: 300, streams: 200 }),
        fan(13, "Cara", {}, { also_claimed_by: [2] }),
      ],
      counted_from: "2026-07-20T00:00:00Z",
    };
    await mountWithEarnings();
    fireEvent.click(within(actions("Link one")).getByRole("button", { name: "Details" }));
    const details = await screen.findByRole("region", { name: "Details" });
    expect(within(details).getByText("Link one")).toBeTruthy();
    expect(relayGet).toHaveBeenCalledWith(`/admin/of-tracking-links/1/fans?account_id=${A.id}`);
    const t = within(details).getByRole("table", { name: "Link fans" });
    await waitFor(() => expect(within(t).getByText("Alice")).toBeTruthy());
    expect(within(t).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Fan", "Total", "Subs", "Posts", "Messages", "Streams", "Tips",
    ]);
    const row = (label: string) =>
      within(within(t).getByText(label).closest("tr") as HTMLElement).getAllByRole("cell").map((c) => c.textContent);
    // Net by default: Alice's $40.00 gross is $32.00 net.
    expect(row("Alice").slice(1)).toEqual(["$32.00", "$8.00", "$0.00", "$20.00", "$0.00", "$4.00"]);
    expect(row("Total:").slice(1)).toEqual(["$36.00", "$8.00", "$2.40", "$20.00", "$1.60", "$4.00"]);
    expect(within(t).getByText(/also came through another link/)).toBeTruthy();
    // The honest window: the later of the link's creation and the ledger's first row, in the report time zone.
    expect(within(details).getByText(/Spend from our ledger since .*2026/)).toBeTruthy();
    // The search narrows the rows and the Total: row with them.
    fireEvent.change(within(details).getByPlaceholderText("Search fan name"), { target: { value: "bob" } });
    expect(within(t).queryByText("Alice")).toBeNull();
    expect(row("Total:")[1]).toBe("$4.00");
    // Back to the list.
    fireEvent.click(within(details).getByRole("button", { name: /Tracking links/ }));
    expect(screen.getByRole("table", { name: "Links list" })).toBeTruthy();
  });

  it("says the bundle's \"Unable to load page\" when the Details read fails", async () => {
    relayGet.mockImplementation((path: string) => {
      const p = String(path);
      if (/\/fans/.test(p)) return Promise.reject(new Error("502"));
      if (p.startsWith("/admin/of-tracking-links/earnings")) return Promise.resolve(earnings);
      if (p.startsWith("/admin/of-tracking-links")) return Promise.resolve(ofResult);
      if (p === "/admin/accounts") return Promise.resolve({ accounts: [A, B], active_account_id: null });
      return Promise.resolve({});
    });
    await mountWithEarnings();
    fireEvent.click(within(actions("Link one")).getByRole("button", { name: "Details" }));
    expect(await screen.findByText("Unable to load page. Try again later")).toBeTruthy();
  });
});

describe("Edit: Promo cost, Source and Tag, and the columns they fill", () => {
  // Worked example: Link one cost $250.00 and earned $987.60 net over 200 clicks and 25 subs, so Profit $737.60,
  // CPC $250.00 / 200 = $1.25, CPS $250.00 / 25 = $10.00, ROI $737.60 / $250.00 x 100 = 295.04%. Link two has no
  // cost: every cost-based cell is "—".
  beforeEach(() => {
    ofResult = {
      ...ofResult,
      links: [
        { ...LINKS[0], promo_cost_cents: 25000, link_source: "Reddit", tags: ["spring", "ads"] },
        { ...LINKS[1], promo_cost_cents: null, link_source: null, tags: [] },
      ],
      sources: ["Reddit", "Twitter"],
      tags: ["ads", "spring"],
    } as typeof ofResult;
    earnings = {
      available: true,
      links: [
        { id: 1, earnings_cents: 123450, earnings_net_cents: 98760, fans_who_spent: 5, fans_counted: 25, net_missing_count: 0 },
        { id: 2, earnings_cents: 0, earnings_net_cents: 0, fans_who_spent: 0, fans_counted: 0, net_missing_count: 0 },
      ],
    };
  });

  it("fills Promo cost, Profit, CPC, CPS, ROI, Source and Tag, with — where there is no cost", async () => {
    await mount();
    await waitFor(() => expect(headers()).toContain("ROI"));
    expect(headers()).toEqual(expect.arrayContaining(["Promo cost", "Profit", "CPC", "CPS", "ROI", "Source", "Tag"]));
    expect(headers()).not.toContain("List");
    const one = (t: string) => cell("Link one", t).textContent;
    expect([one("Promo cost"), one("Profit"), one("CPC"), one("CPS"), one("ROI"), one("Source"), one("Tag")])
      .toEqual(["$250.00", "$737.60", "$1.25", "$10.00", "295.04%", "Reddit", "spring, ads"]);
    for (const t of ["Promo cost", "Profit", "CPC", "CPS", "ROI", "Source", "Tag"]) {
      expect(cell("Link two", t).textContent, t).toBe("—");
    }
    // Gross earnings move Profit and ROI with the switch.
    fireEvent.click(screen.getByRole("switch", { name: "Show net earnings" }));
    expect(one("Profit")).toBe("$984.50");
    expect(one("ROI")).toBe("393.80%");
  });

  it("prints a loss with its sign: a $1,000.00 cost over $987.60 net is Profit -$12.40, ROI -1.24%", async () => {
    ofResult.links[0] = { ...(ofResult.links[0] as object), promo_cost_cents: 100000 };
    await mount();
    await waitFor(() => expect(headers()).toContain("ROI"));
    expect(cell("Link one", "Profit").textContent).toBe("-$12.40");
    expect(cell("Link one", "ROI").textContent).toBe("-1.24%");
  });

  it("filters the rows by Source and Tag over the values in use", async () => {
    await mount();
    const source = screen.getByRole("combobox", { name: "Source" });
    expect(optionsOf(source)).toEqual(["All sources", "Reddit", "Twitter"]);
    choose(source, "Reddit");
    expect(screen.queryByText("Link two")).toBeNull();
    expect(screen.getByText("Link one")).toBeTruthy();
    choose(source, "Twitter");
    expect(screen.queryByText("Link one")).toBeNull();
    choose(source, "All sources");
    choose(screen.getByRole("combobox", { name: "Tag" }), "ads");
    expect(screen.queryByText("Link two")).toBeNull();
  });

  it("opens the editor on the link and saves Source, Promo cost and Tag to the relay, never OnlyFans", async () => {
    await mount();
    fireEvent.click(within(actions("Link one")).getByRole("button", { name: "Edit Link one" }));
    const dlg = screen.getByRole("dialog", { name: "Edit tracking link" });
    const name = within(dlg).getByRole("textbox", { name: "Tracking link name" }) as HTMLInputElement;
    expect([name.value, name.disabled]).toEqual(["Link one", true]);
    expect((within(dlg).getByRole("combobox", { name: "Source Optional" }) as HTMLInputElement).value).toBe("Reddit");
    const cost = within(dlg).getByRole("textbox", { name: "Promo cost Optional" }) as HTMLInputElement;
    expect(cost.value).toBe("250.00");
    fireEvent.change(cost, { target: { value: "1250.5" } });
    fireEvent.blur(cost);
    expect(cost.value).toBe("1,250.50");
    fireEvent.click(within(dlg).getByRole("button", { name: "Remove tag ads" }));
    const tag = within(dlg).getByRole("combobox", { name: "Tag Optional" });
    fireEvent.change(tag, { target: { value: "bio" } });
    fireEvent.keyDown(tag, { key: "Enter" });
    const list = within(dlg).getByRole("combobox", { name: "List Optional" }) as HTMLSelectElement;
    expect(list.disabled).toBe(false);
    // The account's custom lists; OnlyFans' built-ins are not offered (its add-to-list takes a list's number).
    await waitFor(() => expect([...list.options].map((o) => o.textContent)).toEqual(["None", "VIP", "Whales"]));
    fireEvent.change(list, { target: { value: "900001" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(relayPut).toHaveBeenCalledWith("/admin/link-meta", {
      account_id: A.id, kind: "campaign", of_id: 1, promo_cost: 1250.5, source: "Reddit", tags: ["spring", "bio"],
      list_id: "900001", list_name: "VIP",
    });
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("refuses a promo cost that is not an amount, and saves nothing", async () => {
    await mount();
    fireEvent.click(within(actions("Link two")).getByRole("button", { name: "Edit Link two" }));
    const dlg = screen.getByRole("dialog", { name: "Edit tracking link" });
    fireEvent.change(within(dlg).getByRole("textbox", { name: "Promo cost Optional" }), { target: { value: "12.345" } });
    expect(within(dlg).getByText(/Enter an amount/)).toBeTruthy();
    expect((within(dlg).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    expect(relayPut).not.toHaveBeenCalled();
  });

  it("fills the List column with the list's name, and keeps a stored List OnlyFans no longer lists", async () => {
    ofResult.links[0] = { ...(ofResult.links[0] as object), list_id: "900009", list_name: "Old promo fans" };
    await mount();
    await waitFor(() => expect(headers()).toContain("List"));
    expect(cell("Link one", "List").textContent).toBe("Old promo fans");
    expect(cell("Link two", "List").textContent).toBe("—");
    fireEvent.click(within(actions("Link one")).getByRole("button", { name: "Edit Link one" }));
    const dlg = screen.getByRole("dialog", { name: "Edit tracking link" });
    const list = within(dlg).getByRole("combobox", { name: "List Optional" }) as HTMLSelectElement;
    await waitFor(() =>
      expect([...list.options].map((o) => o.textContent)).toEqual(["None", "Old promo fans", "VIP", "Whales"]));
    expect(list.value).toBe("900009");
    // Under the select, what saving does: the List's helper while unchanged, Infloww's Modify copy on another list,
    // its Delete copy on None.
    expect(within(dlg).queryByRole("status")).toBeNull();
    // Later claimers are added by the next figures read (about hourly); the copy says so, not "as fans claim".
    expect(within(dlg).getByText(
      "Adds the link's fans to this OnlyFans list now. Fans who claim later are added when its figures are next read " +
      "from OnlyFans, about every hour. Changing it leaves fans already added in the old list.",
    )).toBeTruthy();
    fireEvent.change(list, { target: { value: "900001" } });
    expect(within(dlg).getByRole("status").textContent).toBe("Editing the list will not affect already-added fans.");
    fireEvent.change(list, { target: { value: "" } });
    expect(within(dlg).getByRole("status").textContent)
      .toBe("Once deleted, new subscribers will not be added to the list. Fans already added stay in it.");
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/link-meta", expect.objectContaining({
      of_id: 1, list_id: null, list_name: null,
    })));
  });

  it("fills Avg CPC, Avg CPS and Avg ROI pooled over the links with a Promo cost, net or gross", async () => {
    // Worked example: Link one cost $250.00 (200 clicks, 25 subs, $987.60 net / $1,234.50 gross), Link two $50.00
    // (0 clicks, 0 subs, $0.00). Avg CPC = $300.00 / 200 = $1.50, Avg CPS = $300.00 / 25 = $12.00, Avg ROI =
    // ($987.60 − $300.00) / $300.00 × 100 = 229.20% net, ($1,234.50 − $300.00) / $300.00 = 311.50% gross. The mean of
    // the two links' own ROIs (295.04% and −100.00%) would be 97.52%: pooled, a $50 link does not weigh like a $250 one.
    ofResult.links[1] = { ...(ofResult.links[1] as object), promo_cost_cents: 5000 };
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const value = (t: string) =>
      (within(panel).getByText(t).closest("[data-kpi]") as HTMLElement).lastElementChild?.textContent;
    await waitFor(() => expect(value("Avg ROI")).toBe("229.20%"));
    expect(value("Avg CPC")).toBe("$1.50");
    expect(value("Avg CPS")).toBe("$12.00");
    fireEvent.click(within(panel).getByRole("switch", { name: "Show net earnings" }));
    expect(value("Avg ROI")).toBe("311.50%");
    // A Source filter that leaves only uncosted links: "—".
    choose(within(panel).getByRole("combobox", { name: "Source" }), "Twitter");
    for (const t of ["Avg CPC", "Avg CPS", "Avg ROI"]) expect(value(t), t).toBe("—");
  });

  it("marks Avg ROI partial when a link with a Promo cost has no earnings figure", async () => {
    ofResult.links[1] = { ...(ofResult.links[1] as object), promo_cost_cents: 5000 };
    earnings.links = [earnings.links[0]];
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const val = () => (within(panel).getByText("Avg ROI").closest("[data-kpi]") as HTMLElement).lastElementChild;
    // Over Link one alone: ($987.60 − $250.00) / $250.00 = 295.04%, marked partial.
    await waitFor(() => expect(val()?.textContent).toBe("295.04% *"));
    expect(val()?.getAttribute("title")).toMatch(/^Partial/);
  });

  it("filters the Dashboard totals by Source", async () => {
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dashboard" }));
    const panel = screen.getByRole("tabpanel", { name: "Dashboard" });
    const clicks = () => (within(panel).getByText("Total clicks").closest("[data-kpi]") as HTMLElement).lastElementChild?.textContent;
    await waitFor(() => expect(clicks()).toBe("200"));
    choose(within(panel).getByRole("combobox", { name: "Source" }), "Twitter");
    expect(clicks()).toBe("0");
  });
});

describe("the HB frame (page-parity ticket 11)", () => {
  it("draws the whole frame with no Creator: the filters, a disabled Create, the table's No data", async () => {
    relayGet.mockImplementation((path: string) => {
      const p = String(path);
      if (p === "/admin/accounts") return Promise.resolve({ accounts: [], active_account_id: null });
      return Promise.resolve({});
    });
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Creator" }).textContent).toContain("Creator"));
    expect(screen.queryByText("No account connected yet.")).toBeNull();
    expect(screen.getByPlaceholderText("Search tracking link name")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Source" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Create tracking link" }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(table()).getByText("No data")).toBeTruthy();
  });

  it("puts the page on the HB body and Create on the HB primary (the CTA orange)", async () => {
    await mount();
    expect(screen.getByRole("heading", { level: 1, name: "Tracking links" }).closest(".bg-hb-bg")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create tracking link" }).classList.contains("bg-cta")).toBe(true);
    expect(screen.getByRole("button", { name: "Export" }).classList.contains("bg-cta")).toBe(false);
  });

  it("shows the bundle's reconnect state for a creator whose OnlyFans session is gone", async () => {
    relayGet.mockImplementation((path: string) => {
      const p = String(path);
      if (p === "/admin/accounts") return Promise.resolve({ accounts: [{ ...A, session_dead_at: "2026-10-01T00:00:00Z" }], active_account_id: null });
      if (p.startsWith("/admin/of-tracking-links")) return Promise.resolve({ links: [], username: null, url_verified: false, of_available: false });
      return Promise.resolve({});
    });
    renderWithProviders(<GrowthTabPage tab="tracking" />);
    expectInCapture("growth-tracking-links#68", "Relink OnlyFans account");
    expect(await screen.findByText("Creator's OnlyFans account is disconnected from Infloww")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Relink OnlyFans account" }).getAttribute("href")).toBe("/creators");
    expect(screen.queryByText(/OnlyFans not reachable/)).toBeNull();
  });
});
