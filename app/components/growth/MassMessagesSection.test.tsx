/**
 * Seam 1 of docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md:
 * the Smart Messages page rendered with `@/lib/relay` mocked, every verb
 * stubbed, so an unexpected call fails loudly instead of reaching a relay.
 *
 * Ticket 29 started this file with the hourly "Auto-unsend (automation)"
 * card's data-loss guard: with text, media and price all off it must never
 * send a policy, because the Relay reads an empty policy as the old per-chat
 * sweep of outbound DMs (service/automations/unsend_messages.py,
 * `not wants_mass`). Ticket 30 adds the page frame (header, parent tab strip,
 * the Automated Messages slot) and the Mass Messages tab, checked against the
 * Layout capture on disk. Ticket 31 adds the Create message pop-up, its
 * Automated messages slot, and the composer's per-broadcast Auto-unsend label
 * (the real composer, rendered on its own over the same mocked relay).
 * Ticket 41 fills the Automated Messages slot and makes it the default tab,
 * so the Mass Messages cases open `?tab=mass`; the Automated Messages tab is
 * pinned in `SmartMessagesPage.test.tsx`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

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

// An owner session by default: /admin/accounts is the account source. A
// chatter-only case clears `user` and sets `chatter`, and its Creators then
// come from /chatter/me/accounts (a plain fetch, stubbed per case).
const session = vi.hoisted(() => ({
  user: { user_id: 1 } as { user_id: number } | null,
  chatter: null as { id: number } | null,
}));
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: session.user }),
  useOptionalUser: () => ({ user: session.user }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: session.chatter }),
  useOptionalChatter: () => ({ chatter: session.chatter }),
}));

// The lazy composer stands in as its mode, so a click shows which one opened,
// and whether the page asked it to label its extras. With `composer.real` set,
// it passes the page's props through to the real composer instead.
const composer = vi.hoisted(() => ({ real: false }));
vi.mock("@/components/compose/LazyMassMessageComposer", async () => {
  const { MassMessageComposer } = await vi.importActual<
    typeof import("@/components/compose/MassMessageComposer")
  >("@/components/compose/MassMessageComposer");
  type Props = Parameters<typeof MassMessageComposer>[0];
  return {
    LazyMassMessageComposer: (props: Props) => composer.real
      ? <MassMessageComposer {...props} />
      : <div data-testid="composer" data-label-extras={String(!!props.labelExtras)}>{props.mode}</div>,
  };
});
// The real composer reads the acting employee, the window's scope and the All
// Models include set; nothing else on the page reads any of them.
vi.mock("@/contexts/EmployeeContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/EmployeeContext")>()),
  useEmployee: () => ({ current: null }),
}));
vi.mock("@/contexts/ScopeContext", async (importOriginal) => {
  const all = { scope: { kind: "all" } };
  return { ...(await importOriginal<typeof import("@/contexts/ScopeContext")>()), useScope: () => all };
});
vi.mock("@/hooks/useAllModelsInclude", () => ({
  useAllModelsInclude: () => ({ isIncluded: () => true, toggle: vi.fn() }),
}));

import SmartMessagesPage from "@/components/growth/SmartMessagesPage";
import { SM, SM_MASS_ACTIONS, SM_MASS_COLUMNS, type CapturedControl } from "@/components/growth/smartMessagesControls";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPatch = relay.patch as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;
const relayUpload = relay.uploadFile as unknown as Mock;
const allMocks = [relayGet, relayPost, relayPatch, relayPut, relayDelete, relayUpload];

const ACC = "acc-1";
const RULE_ID = 77;
const REASON = /turn on at least one class/i;
/** The wait for a mount to settle. The tab mounts every panel at once (Mass
 *  Nudge's long form among them), so a first render under a loaded machine can
 *  outlast waitFor's 1s default; a click's own wait keeps the default. */
const SETTLE = { timeout: 5000 };

let client: QueryClient;

const ONE_BROADCAST = [{ id: 1, date: "2026-01-01T00:00:00Z", text: "hi", isFree: true, canUnsend: true }];
/** The cached broadcasts the list read answers with; one by default. */
let massItems: unknown[] = ONE_BROADCAST;

/** The relay writes the running test expects, as "VERB path" (query dropped). */
let expectedWrites: string[] = [];
const expectWrites = (...writes: string[]) => { expectedWrites.push(...writes); };

beforeEach(() => {
  // The Mass Messages tab; Automated Messages is the default (ticket 41).
  window.history.replaceState(null, "", "/growth/smart-messages?tab=mass");
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  allMocks.forEach((m) => m.mockReset());
  massItems = ONE_BROADCAST;
  relayPost.mockResolvedValue({ id: RULE_ID, kind: "unsend_messages" });
  relayPatch.mockResolvedValue({ id: RULE_ID, kind: "unsend_messages" });
});
afterEach(() => {
  // No relay write but the ones this test named: any other non-GET call, under
  // /api/of or not (an /admin route can write to OnlyFans server-side), fails.
  const writes = { POST: relayPost, PATCH: relayPatch, PUT: relayPut, DELETE: relayDelete, UPLOAD: relayUpload };
  const made = Object.entries(writes).flatMap(([verb, m]) =>
    m.mock.calls.map(([path]) => `${verb} ${String(path).split("?")[0]}`));
  const allowed = expectedWrites;
  expectedWrites = [];
  cleanup();
  for (const w of made) expect(allowed, `unexpected relay write: ${w}`).toContain(w);
});

/** The rule writes the card made: posts to the automation-rules create. Today's
 *  tab also fires a mount-time `/admin/mass-messages/refresh` (a cache warm,
 *  not this card's), so the create is picked out by its path. */
const rulePosts = () =>
  relayPost.mock.calls.filter(([path]) => String(path) === "/admin/automation-rules");

const savedRule = (policy: Record<string, number>) => ({
  id: RULE_ID, account_id: ACC, kind: "unsend_messages", name: "Auto-unsend mass",
  every_seconds: 3600, is_enabled: true, payload: { policy }, last_run: null,
});

/** Answer the page's reads: one active Creator, a rules list of `rules`. Every
 *  mount also expects today's tab's cache warm, which reads OF and writes only
 *  the Relay's own cache. */
function stubReads(rules: unknown[]) {
  expectWrites("POST /admin/mass-messages/refresh");
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/accounts")) {
      return Promise.resolve({
        accounts: [{ id: ACC, nickname: "Model A", has_session: true }],
        active_account_id: ACC,
      });
    }
    if (p.startsWith("/admin/automation-rules")) return Promise.resolve({ rules });
    // One cached broadcast for the list (the mount-time refresh may still fire).
    if (p.startsWith("/admin/mass-messages")) return Promise.resolve({ items: massItems });
    return Promise.resolve({});
  });
}

/** Mount the REAL page over one active Creator and a rules list of `rules`. */
async function mount(rules: unknown[]) {
  stubReads(rules);
  render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
  // Wait for the button the loaded state shows: "Save" is also the pre-fetch
  // state, so a saved rule must have turned it into "Update" first.
  const settled = rules.length ? "Update" : "Save";
  await waitFor(() => expect(screen.getByRole("button", { name: settled })).toBeTruthy(), SETTLE);
  // Let the tab's mount-time cache warm finish, so a click is the only actor.
  await waitFor(() => expect(client.isFetching() + client.isMutating()).toBe(0), SETTLE);
}

const classBox = (label: string) =>
  screen.getByText(label).closest("label")!.querySelector("input[type=checkbox]") as HTMLInputElement;

async function setClass(label: string, on: boolean) {
  const box = classBox(label);
  if (box.checked !== on) await act(async () => { fireEvent.click(box); });
  expect(box.checked).toBe(on);
}

describe("the hourly Auto-unsend card on Smart Messages", () => {
  it("disables Save with every class off, shows the reason, and sends nothing", async () => {
    await mount([]);
    await setClass("Free text-only", false);
    await setClass("With image / video", false);
    await setClass("PPV (priced)", false);

    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(screen.getByText(REASON)).toBeTruthy();

    const before = allMocks.map((m) => m.mock.calls.length);
    await act(async () => { fireEvent.click(save); });
    expect(allMocks.map((m) => m.mock.calls.length)).toEqual(before);
    expect(rulePosts()).toHaveLength(0);
    expect(relayPatch).not.toHaveBeenCalled();
  });

  it("with one class on, Save creates the 'Auto-unsend mass' rule holding that class only", async () => {
    expectWrites("POST /admin/automation-rules");
    await mount([]);
    await setClass("Free text-only", false);
    await setClass("With image / video", true);
    expect(screen.queryByText(REASON)).toBeNull();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(rulePosts()).toHaveLength(1));
    const [, body] = rulePosts()[0] as [string, Record<string, unknown>];
    expect(body.kind).toBe("unsend_messages");
    expect(body.name).toBe("Auto-unsend mass");
    expect(body.account_id).toBe(ACC);
    // The card's default media hours (24) — the class's own field.
    expect(body.payload).toEqual({ policy: { mass_media_hours: 24 } });
    expect(relayPatch).not.toHaveBeenCalled();
  });

  it("an Update on a saved rule sends the same one-class policy shape", async () => {
    expectWrites(`PATCH /admin/automation-rules/${RULE_ID}`);
    await mount([savedRule({ mass_text_hours: 6 })]);
    await setClass("Free text-only", false);
    await setClass("PPV (priced)", true);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Update" })); });
    await waitFor(() => expect(relayPatch).toHaveBeenCalledTimes(1));
    const [path, body] = relayPatch.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe(`/admin/automation-rules/${RULE_ID}`);
    expect(body.payload).toEqual({ policy: { mass_price_hours: 48 } });
    expect(rulePosts()).toHaveLength(0);
  });

  it("a saved rule with an empty policy hydrates to every class off, a disabled Update and the reason", async () => {
    await mount([savedRule({})]);
    expect(classBox("Free text-only").checked).toBe(false);
    expect(classBox("With image / video").checked).toBe(false);
    expect(classBox("PPV (priced)").checked).toBe(false);

    const update = screen.getByRole("button", { name: "Update" }) as HTMLButtonElement;
    expect(update.disabled).toBe(true);
    expect(screen.getByText(REASON)).toBeTruthy();
    await act(async () => { fireEvent.click(update); });
    expect(relayPatch).not.toHaveBeenCalled();
    expect(rulePosts()).toHaveLength(0);
  });

  it("carries the visible 'Inflowwww extra' tag with title={EXTRA_LABEL}", async () => {
    await mount([]);
    const heading = screen.getByText("Auto-unsend (automation)");
    const tag = within(heading.parentElement!).getByText(EXTRA_LABEL);
    expect(tag.textContent).toBe("Inflowwww extra");
    expect(tag.getAttribute("title")).toBe(EXTRA_LABEL);
  });
});

// ── Ticket 30: the frame and the Mass Messages tab ────────────────────

/** Mount the page at `url`, on the Mass Messages tab unless `url` says otherwise. */
async function mountFrame(url = "/growth/smart-messages?tab=mass") {
  window.history.replaceState(null, "", url);
  stubReads([]);
  render(
    <QueryClientProvider client={client}>
      <SmartMessagesPage />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(client.isFetching() + client.isMutating()).toBe(0), SETTLE);
}

const tabNames = (list: HTMLElement) =>
  within(list).getAllByRole("tab").map((t) => t.textContent);
const parentTabs = () => screen.getByRole("tablist", { name: "Smart Messages" });
const childTabs = () => screen.getByRole("tablist", { name: "Mass Messages" });
const selected = (list: HTMLElement) =>
  within(list).getAllByRole("tab").filter((t) => t.getAttribute("aria-selected") === "true").map((t) => t.textContent);
const relayCalls = () => allMocks.map((m) => m.mock.calls.length);
const before = (a: Element, b: Element) =>
  !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
/** The visible tag beside `el`: inside its parent, with title={EXTRA_LABEL}. */
const extraTagBeside = (el: HTMLElement) => {
  const tag = within(el.parentElement!).getByText(EXTRA_LABEL);
  expect(tag.getAttribute("title")).toBe(EXTRA_LABEL);
  return tag;
};

describe("the control catalogue matches the Layout capture on disk", () => {
  const capture = readFileSync(
    resolve(__dirname, "../../../docs/infloww-layouts/growth-smart-messages.md"), "utf-8",
  );
  const rowOf = (id: string) => capture.split("\n").find((l) => l.startsWith(`| ${id} |`));

  const inventory = readFileSync(resolve(__dirname, "../../../docs/infloww-screens.md"), "utf-8");
  const smartMessages = inventory.slice(
    inventory.indexOf("#### 3.5.1 Smart Messages"), inventory.indexOf("#### 3.5.2"),
  );

  it.each(Object.entries(SM) as Array<[string, CapturedControl]>)(
    "%s: its Inventory tag is one §3.5.1 cites",
    (_key, c) => {
      if (c.inventory !== null) expect(smartMessages).toContain(c.inventory);
    },
  );

  it.each(Object.entries(SM) as Array<[string, CapturedControl]>)(
    "%s: its Items row carries the label and every cited source",
    (_key, c) => {
      const row = rowOf(c.id);
      expect(row, `${c.id} is not an Items row`).toBeTruthy();
      // The label must sit in the Value cell, not merely anywhere in the row.
      const value = row!.split("|")[4];
      if (c.label !== null) expect(value).toContain(c.label);
      if (c.desc) expect(value).toContain(c.desc);
      const sources = row!.split("|")[5].split(";").map((s) => s.trim());
      for (const s of c.sources) expect(sources).toContain(s);
    },
  );
});

describe("Smart Messages frame and Mass Messages tab (ticket 30)", () => {
  it("the header, tab strip and child tabs show the capture's labels in its order", async () => {
    await mountFrame();
    const title = screen.getByRole("heading", { level: 1 });
    expect(title.textContent).toBe("Smart Messages List");
    // Mass Messages takes no Creator (its panels list every active Creator): no creator select in the header,
    // and no creator column (that is the Automated Messages tab's).
    expect(screen.queryByRole("combobox", { name: "Creator" })).toBeNull();
    expect(screen.queryByTestId("of-creator-column")).toBeNull();

    expect(tabNames(parentTabs())).toEqual(["Automated Messages", "Mass Messages"]);
    expect(tabNames(childTabs())).toEqual(["Priority mass messages", "OF mass messages"]);

    // The right box: Learn (Not wired), then New Message, in the header row
    // above the tab strip, where the bundle's `-40px` lifts it (ticket 54).
    const learn = screen.getByRole("button", { name: "Learn" });
    const create = screen.getByRole("button", { name: "New Message" });
    expect(learn).toBeDisabled();
    expect(learn).toHaveAttribute("title", "not wired");
    expect(before(learn, create)).toBe(true);
    expect(before(create, parentTabs())).toBe(true);
  });

  it("?tab=mass and ?tab=scheduled open Mass Messages; an unknown or absent value opens the default, Automated Messages (ticket 41)", async () => {
    for (const url of ["?tab=mass", "?tab=scheduled"]) {
      await mountFrame(`/growth/smart-messages${url}`);
      expect(selected(parentTabs())).toEqual(["Mass Messages"]);
      expect(screen.getByText("Auto-unsend (automation)")).toBeTruthy();
      cleanup();
    }
    for (const url of ["?tab=bogus", ""]) {
      await mountFrame(`/growth/smart-messages${url}`);
      expect(selected(parentTabs())).toEqual(["Automated Messages"]);
      expect(screen.queryByText("Auto-unsend (automation)")).toBeNull();
      cleanup();
    }
  });

  it('"Priority mass messages" lists the Creator\'s runs with their progress, and Cancel cancels one', async () => {
    await mountFrame();
    const reads = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string) => String(path).startsWith("/admin/priority-mass/runs")
      ? Promise.resolve({
        max_recipients: 5000, hourly_rate: 300,
        runs: [{
          id: 9, account_id: ACC, status: "running", text: "hey you", media_count: 1, price: 0,
          created_at: "2026-10-20T10:00:00", completed_at: null, last_error: null,
          resolved: 25, excluded: 5, capped: 0, total: 20, counts: { sent: 5, pending: 15 }, stalled: false,
        }],
      })
      : reads(path));
    const pmm = within(childTabs()).getByRole("tab", { name: "Priority mass messages" });
    await act(async () => { fireEvent.click(pmm); });
    expect(selected(childTabs())).toEqual(["Priority mass messages"]);
    const panel = screen.getByRole("tabpanel", { name: "Priority mass messages" });
    await waitFor(() => expect(within(panel).getByText(/5 of 20 sent/)).toBeTruthy());
    expect(within(panel).getByText(/about 300 fans an hour, at most 5,000 fans/)).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: "Resume" })).toBeNull();
    expect(relayGet.mock.calls.map(([p]) => String(p))).toContain(`/admin/priority-mass/runs?account_id=${ACC}`);

    expectWrites("POST /admin/priority-mass/runs/9/cancel");
    await act(async () => { fireEvent.click(within(panel).getByRole("button", { name: "Cancel" })); });
    await waitFor(() => expect(relayPost.mock.calls.map(([p]) => String(p)))
      .toContain("/admin/priority-mass/runs/9/cancel"));
  });

  it('the sent history, its bulk unsend and the Auto-unsend card render under "OF mass messages"', async () => {
    await mountFrame();
    const of = within(childTabs()).getByRole("tab", { name: "OF mass messages" });
    const panel = screen.getByRole("tabpanel", { name: "OF mass messages" });
    expect(of.getAttribute("aria-controls")).toBe(panel.id);
    expect(within(panel).getByText("Auto-unsend (automation)")).toBeTruthy();
    expect(within(panel).getByRole("heading", { name: "Mass messages" })).toBeTruthy();
    // Ours, each with the extra tag: the bulk-unsend toolbar and the list's own filters.
    extraTagBeside(within(panel).getByText(/^Bulk actions/));
    extraTagBeside(within(panel).getByText("Hide unsent").closest("label")!);
  });

  it("the sent history's Models chips, shown for two or more Creators, carry the extra tag", async () => {
    stubReads([]);
    const reads = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string) =>
      String(path).startsWith("/admin/accounts")
        ? Promise.resolve({
          accounts: [
            { id: ACC, nickname: "Model A", has_session: true },
            { id: "acc-2", nickname: "Model B", has_session: true },
          ],
          active_account_id: ACC,
        })
        : reads(path));
    render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByText("Models")).toBeTruthy());
    await waitFor(() => expect(client.isFetching() + client.isMutating()).toBe(0), SETTLE);
    extraTagBeside(screen.getByText("Models"));
  });

  it("the OF filter bar follows the capture, every control Not wired", async () => {
    await mountFrame();
    const panel = screen.getByRole("tabpanel", { name: "OF mass messages" });
    const controls = [
      within(panel).getByRole("textbox", { name: "Search for message" }),
      within(panel).getByLabelText("Sending Date:"),
      within(panel).getByRole("textbox", { name: "End date" }),
      within(panel).getByRole("button", { name: "Reset" }),
      within(panel).getByRole("button", { name: "Search" }),
      within(panel).getByRole("button", { name: "Export" }),
    ];
    for (let i = 0; i < controls.length; i++) {
      expect(controls[i]).toBeDisabled();
      expect(controls[i]).toHaveAttribute("title", "not wired");
      if (i) expect(before(controls[i - 1], controls[i])).toBe(true);
    }
    // The bar sits above the list.
    expect(before(controls[0], within(panel).getByText("Auto-unsend (automation)"))).toBe(true);
  });

  it("the scheduled list is its own list, headed for every scheduled send, direct and mass, labelled Inflowwww extra", async () => {
    await mountFrame();
    const heading = screen.getByRole("heading", { name: "Every scheduled send, direct and mass" });
    extraTagBeside(heading);
    const list = heading.closest("section")!;
    expect(within(list).getByText("Scheduled messages")).toBeTruthy();
    // Not filed under a send type.
    const panel = screen.getByRole("tabpanel", { name: "OF mass messages" });
    expect(panel.contains(list)).toBe(false);
    expect(screen.getByRole("tabpanel", { name: "Mass Messages" }).contains(list)).toBe(true);
  });
});

// ── Ticket 55: the OF child's sent list is the capture's table ───────────

/** Mount the Mass Messages tab over `items`, with the report time zone UTC. */
async function mountSentList(items: unknown[]) {
  massItems = items;
  window.history.replaceState(null, "", "/growth/smart-messages?tab=mass");
  stubReads([]);
  const reads = relayGet.getMockImplementation()!;
  relayGet.mockImplementation((path: string) =>
    String(path).startsWith("/admin/settings/applied")
      ? Promise.resolve({ preferences: { tz: null, report_tz: "UTC", week_start: "monday" } })
      : reads(path));
  render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
  await waitFor(() => expect(client.isFetching() + client.isMutating()).toBe(0), SETTLE);
  return within(screen.getByRole("tabpanel", { name: "OF mass messages" })).getByRole("table");
}

/** A body row's cells, keyed by their column header's text. */
const cellsOf = (table: HTMLElement, row: HTMLElement) => {
  const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent ?? "");
  const cells = within(row).getAllByRole("cell");
  return Object.fromEntries(heads.map((h, i) => [h, cells[i]]));
};
const bodyRows = (table: HTMLElement) => within(table).getAllByRole("row").slice(1);
const notWired = (cell: HTMLElement) => {
  expect(cell.textContent).toBe("—");
  expect(cell).toHaveAttribute("title", "not wired");
};

describe("the OF child's sent list is the capture's table (ticket 55)", () => {
  const capture = readFileSync(
    resolve(__dirname, "../../../docs/infloww-layouts/growth-smart-messages.md"), "utf-8",
  );
  const rowOf = (id: string) => capture.split("\n").find((l) => l.startsWith(`| ${id} |`))!.split("|").map((c) => c.trim());

  it.each(SM_MASS_COLUMNS.map((c) => [c.id, c] as const))("%s: its label, width and sources match the capture", (_id, c) => {
    const row = rowOf(c.id);
    expect(row[4]).toBe(`${c.label}, ${c.width}px`);
    for (const s of c.sources) expect(row[5].split(";").map((x) => x.trim())).toContain(s);
  });

  it("heads the list with the capture's OF columns, then our Creator column labelled Inflowwww extra, then Actions", async () => {
    const table = await mountSentList(ONE_BROADCAST);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Message", "Sent date & time", "Sender", "Attachment", "Status", "Price", "Sent", "Viewed",
      "Purchased", "Earnings", "Withdrawn by", "Withdrawn date & time", "Creator" + EXTRA_LABEL, "Actions",
    ]);
    const creator = within(table).getAllByRole("columnheader")[12];
    expect(within(creator).getByText(EXTRA_LABEL)).toHaveAttribute("title", EXTRA_LABEL);
  });

  it("a sent broadcast reads as a row: its cells, a Sent pill, and Not wired cells where no read backs them", async () => {
    const table = await mountSentList([{
      id: 7, date: "2026-01-01T15:05:00Z", text: "<p>New set &amp; more</p>", isFree: false, canUnsend: true,
      sentCount: 1240, viewedCount: 512, mediaCount: 3, automationKind: "online_blast",
      purchasedCount: 3, earningsCents: 4500,
    }]);
    const [row] = bodyRows(table);
    const c = cellsOf(table, row);
    expect(c["Message"].textContent).toBe("New set & more");
    expect(c["Sent date & time"].textContent).toBe("Jan 1, 2026 at 3:05 PM");
    expect(c["Sender"].textContent).toBe("Online blast");
    expect(c["Attachment"].textContent).toContain("3");
    expect(within(c["Status"]).getByText("Sent")).toBeTruthy();
    // Priced, but the cache keeps no amount: the amount is Not wired.
    expect(c["Price"].textContent).toBe("PPV");
    expect(c["Price"]).toHaveAttribute("title", "not wired");
    expect(c["Sent"].textContent).toBe("1240");
    expect(c["Viewed"].textContent).toBe("512");
    // Purchased / Earnings: the relay's local attribution (roadmap 5.8).
    expect(c["Purchased"].textContent).toBe("3");
    expect(c["Earnings"].textContent).toBe("$45");
    for (const h of ["Withdrawn by", "Withdrawn date & time"]) notWired(c[h]);
    expect(c["Creator" + EXTRA_LABEL].textContent).toBe("Model A");
    expect(within(c["Actions"]).getByRole("button", { name: "Actions" })).toBeEnabled();
  });

  it("an unsent broadcast, shown once Hide unsent is off, carries the Unsent pill and the bundle's -- cells", async () => {
    const table = await mountSentList([{
      id: 8, date: "2026-01-02T09:00:00Z", text: "", isFree: true, canUnsend: false, isCanceled: true,
      sentCount: 10, viewedCount: 2, mediaCount: 0,
    }]);
    await act(async () => { fireEvent.click(screen.getByLabelText("Hide unsent")); });
    const [row] = bodyRows(table);
    const c = cellsOf(table, row);
    expect(within(c["Status"]).getByText("Unsent")).toBeTruthy();
    expect(c["Message"].textContent).toBe("--");
    expect(c["Attachment"].textContent).toBe("--");
    expect(c["Price"].textContent).toBe("--");
    notWired(c["Sender"]);
    fireEvent.click(within(c["Actions"]).getByRole("button", { name: "Actions" }));
    expect(screen.getByRole("menuitem", { name: SM_MASS_ACTIONS.unsend.label })).toBeDisabled();
  });

  it("with nothing sent in the range, the table shows the capture's empty line for the OF child", async () => {
    expectWrites("POST /admin/mass-messages/refresh");
    const table = await mountSentList([]);
    expect(within(table).getByText(SM.massEmpty.label)).toBeTruthy();
    expect(SM.massEmpty.label).toBe("There are no more messages for the selected time period");
  });
});

// ── The sent list's head, empty row and Actions menu, as the bundle draws them ──

describe("the sent list's head, empty row and Actions menu follow the bundle", () => {
  const capture = readFileSync(
    resolve(__dirname, "../../../docs/infloww-layouts/growth-smart-messages.md"), "utf-8",
  );
  const notes = capture.slice(capture.indexOf("## Notes"), capture.indexOf("## Triggers"));

  it.each(Object.entries(SM_MASS_ACTIONS))("%s: its label and every source sit in one of the capture's Notes", (_k, a) => {
    const line = notes.split("\n").find((l) => l.includes("OFMMOperateMenu"));
    expect(line, "the capture's Note on the Actions menu").toBeTruthy();
    if (a.label) expect(line).toContain(`"${a.label}"`);
    for (const s of a.sources) expect(line).toContain(s.replace("index.9f50f370.js ", ""));
  });

  it("fills the head and rules a 22px divider after every column but the last", async () => {
    const table = await mountSentList(ONE_BROADCAST);
    const heads = within(table).getAllByRole("columnheader");
    // IF_TABLE's head: 46px on #353535 (bg-bg-elev-2), a 22px divider drawn by `before:` that the last cell hides.
    for (const h of heads) expect(h).toHaveClass("bg-bg-elev-2", "h-[46px]", "before:h-[22px]", "last:before:hidden");
    // Actions is fixed right with the left shadow.
    expect(heads.at(-1)).toHaveClass("sticky", "right-0");
    expect(heads.at(-1)!.className).toContain("shadow-");
  });

  it("gives the empty row the bundle's height: 220px above and below the illustration's 90px and the line", async () => {
    expectWrites("POST /admin/mass-messages/refresh");
    const table = await mountSentList([]);
    const line = within(table).getByText(SM.massEmpty.label);
    // EmptyState's 90px art over the line, 232px (12px padding + 220px margin) above and below.
    const box = line.parentElement!;
    expect(box).toHaveClass("py-[232px]");
    expect(box.querySelector("svg")).toHaveAttribute("height", "90");
  });

  it("opens Actions as a menu: Unsent unsends after a confirm, Duplicate is Not wired", async () => {
    vi.stubGlobal("confirm", () => true);
    expectWrites("DELETE /api/of/v2/messages/queue/7");
    relayDelete.mockResolvedValue({});
    const table = await mountSentList([{ id: 7, date: "2026-01-01T15:05:00Z", text: "hi", isFree: true, canUnsend: true, sentCount: 3 }]);
    const c = cellsOf(table, bodyRows(table)[0]);
    const trigger = within(c["Actions"]).getByRole("button", { name: "Actions" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Unsent", "Duplicate"]);
    const dup = within(menu).getByRole("menuitem", { name: SM_MASS_ACTIONS.duplicate.label });
    expect(dup).toBeDisabled();
    expect(dup).toHaveAttribute("title", "not wired");
    const unsend = within(menu).getByRole("menuitem", { name: SM_MASS_ACTIONS.unsend.label });
    expect(unsend).toHaveAttribute("title", SM_MASS_ACTIONS.unsendTip.label);
    await act(async () => { fireEvent.click(unsend); });
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(1));
    expect(relayDelete.mock.calls[0][0]).toBe("/api/of/v2/messages/queue/7");
    expect(screen.queryByRole("menu")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("keeps bulk unsend working beside the menu", async () => {
    vi.stubGlobal("confirm", () => true);
    expectWrites("DELETE /api/of/v2/messages/queue/7");
    relayDelete.mockResolvedValue({});
    await mountSentList([{ id: 7, date: "2026-01-01T15:05:00Z", text: "hi", isFree: true, canUnsend: true }]);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Unsend all (1)" })); });
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(1));
    expect(relayDelete.mock.calls[0][0]).toBe("/api/of/v2/messages/queue/7");
    vi.unstubAllGlobals();
  });
});

// ── Ticket 31: the Create message pop-up ────────────────────────────────

const popUp = () => screen.getByRole("dialog", { name: "Create message" });
const card = (name: string | RegExp) => within(popUp()).getByRole("button", { name });

async function openPopUp(url?: string, automatedCards?: ReactNode) {
  window.history.replaceState(null, "", url ?? "/growth/smart-messages");
  stubReads([]);
  render(
    <QueryClientProvider client={client}>
      <SmartMessagesPage automatedMessageCards={automatedCards} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(client.isFetching() + client.isMutating()).toBe(0), SETTLE);
  expect(screen.queryByRole("dialog")).toBeNull();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "New Message" })); });
  return popUp();
}

describe("the Create message pop-up (ticket 31)", () => {
  it("the header has no separate online button; New Message opens the pop-up titled as the capture records", async () => {
    await mountFrame();
    expect(screen.queryByRole("button", { name: /Message online fans/ })).toBeNull();
    cleanup();

    const dialog = await openPopUp();
    expect(within(dialog).getByRole("heading", { level: 2 }).textContent).toBe("Create message");
    expect(screen.queryByTestId("composer")).toBeNull();
  });

  it("its Mass messages section lists the capture's cards in order, then ours, then Cancel and Next", async () => {
    const dialog = await openPopUp();
    const section = within(dialog).getByRole("region", { name: "Mass messages" });
    const cards = within(section).getAllByRole("button");
    expect(cards.map((c) => c.textContent)).toEqual([
      "Priority mass messageSent to priority inbox",
      "OF mass messageSent to general inbox",
      "Message online fans" + EXTRA_LABEL,
    ]);
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const next = within(dialog).getByRole("button", { name: "Next" });
    expect(before(cards[2], cancel)).toBe(true);
    expect(before(cancel, next)).toBe(true);
    // Nothing picked yet: Next waits for a card, as the bundle's xConfirmDisabled.
    expect(next).toBeDisabled();
  });

  it('"Priority mass message", then Next, opens its composer, whose Send starts a run for the Creator', async () => {
    await openPopUp();
    const pmm = card(/^Priority mass message/);
    const calls = relayCalls();
    await act(async () => { fireEvent.click(pmm); });
    expect(relayCalls()).toEqual(calls);
    expect(pmm).toHaveAttribute("aria-pressed", "true");
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: "Next" })); });
    expect(screen.queryByRole("dialog", { name: "Create message" })).toBeNull();
    expect(screen.queryByTestId("composer")).toBeNull();
    const form = screen.getByRole("dialog", { name: "Priority mass message" });
    expect(within(form).getByText(/about 300 fans an hour, at most 5,000 fans/)).toBeTruthy();
    // The Creator seeds from the active sessions.
    await waitFor(() => expect((within(form).getByRole("combobox") as HTMLSelectElement).value).toBe(ACC));
    fireEvent.change(within(form).getByRole("textbox", { name: "Message" }), { target: { value: "hey {name}" } });

    expectWrites("POST /admin/priority-mass/runs");
    await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Send" })); });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Priority mass message" })).toBeNull());
    const posts = relayPost.mock.calls.filter(([p]) => String(p) === "/admin/priority-mass/runs");
    expect(posts).toHaveLength(1);
    expect(posts[0][1]).toEqual({
      account_id: ACC, text: "hey {name}", media_files: [], previews: [], price: 0,
      locked_text: false, user_lists: ["fans", "following"], excluded_user_lists: [],
    });
  });

  it('"OF mass message", then Next, opens the composer in standard mode and closes the pop-up', async () => {
    await openPopUp();
    const of = card(/^OF mass message/);
    await act(async () => { fireEvent.click(of); });
    expect(of).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("composer")).toBeNull();
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: "Next" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("composer").textContent).toBe("standard");
    expect(screen.getByTestId("composer").getAttribute("data-label-extras")).toBe("true");
  });

  it('"Message online fans" carries "Inflowwww extra" and, then Next, opens the composer in online mode', async () => {
    await openPopUp();
    const online = card(/^Message online fans/);
    expect(online).toHaveAttribute("title", EXTRA_LABEL);
    const tag = within(online).getByText(EXTRA_LABEL);
    expect(tag.getAttribute("title")).toBe(EXTRA_LABEL);
    await act(async () => { fireEvent.click(online); });
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: "Next" })); });
    expect(screen.getByTestId("composer").textContent).toBe("online");
    expect(screen.getByTestId("composer").getAttribute("data-label-extras")).toBe("true");
  });

  it("Cancel closes the pop-up and opens nothing", async () => {
    await openPopUp();
    await act(async () => { fireEvent.click(card(/^OF mass message/)); });
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: "Cancel" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByTestId("composer")).toBeNull();
  });

  // Ticket 42 fills the slot by default with the Triggers' cards, pinned in
  // SmartMessagesPage.test.tsx; it was empty, and rendered nothing, until then.
  it("with no child given, the Automated messages slot holds the page's own section after Mass messages", async () => {
    const dialog = await openPopUp();
    expect(within(dialog).getAllByRole("region").map((r) => r.querySelector("h3")?.textContent))
      .toEqual(["Mass messages", "Automated messages"]);
  });

  it("a child in the Automated messages slot renders in its own section after Mass messages, before the buttons", async () => {
    const dialog = await openPopUp(undefined, <p>automated cards stub</p>);
    const regions = within(dialog).getAllByRole("region");
    expect(regions.map((r) => r.querySelector("h3")?.textContent)).toEqual(["Mass messages", "Automated messages"]);
    expect(within(regions[1]).getByRole("heading", { name: "Automated messages" })).toBeTruthy();
    const stub = within(regions[1]).getByText("automated cards stub");
    expect(before(stub, within(dialog).getByRole("button", { name: "Cancel" }))).toBe(true);
  });
});

describe("the composer's per-broadcast Auto-unsend field (ticket 31)", () => {
  afterEach(() => { composer.real = false; });

  it("opened from the pop-up, it carries the visible tag and title={EXTRA_LABEL}", async () => {
    composer.real = true;
    await openPopUp();
    await act(async () => { fireEvent.click(card(/^Message online fans/)); });
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: "Next" })); });
    const field = (await screen.findByText("Auto-unsend this broadcast after")).closest("label")!;
    expect(field).toHaveAttribute("title", EXTRA_LABEL);
    const tag = within(field).getByText(EXTRA_LABEL);
    expect(tag.getAttribute("title")).toBe(EXTRA_LABEL);
    // Its scheduled-send caveat is untouched: no schedule, no caveat.
    expect(screen.queryByText(/Auto-unsend applies to immediate sends only/)).toBeNull();
    await waitFor(() => expect(client.isFetching()).toBe(0));
  });
});

// ── A chatter-only session ──────────────────────────────────────────────

/** Mount the page at `?tab=mass`. */
async function mountMass() {
  window.history.replaceState(null, "", "/growth/smart-messages?tab=mass");
  stubReads([]);
  render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText("Auto-unsend (automation)")).toBeTruthy(), SETTLE);
  await waitFor(() => expect(client.isFetching() + client.isMutating()).toBe(0), SETTLE);
}

/** Every relay call the page made, of any verb, as its path. */
const calledPaths = () => allMocks.flatMap((m) => m.mock.calls.map(([path]) => String(path)));
/** Today's tab's mount-time cache warm: it reads OF and writes only the Relay's own cache. */
const CACHE_WARM = "POST /admin/mass-messages/refresh";
/** The relay writes (every verb but GET) the page made, as "VERB path", distinct. */
const writesMade = () => [...new Set(
  ([["POST", relayPost], ["PATCH", relayPatch], ["PUT", relayPut], ["DELETE", relayDelete], ["UPLOAD", relayUpload]] as const)
    .flatMap(([verb, m]) => m.mock.calls.map(([path]) => `${verb} ${String(path).split("?")[0]}`)),
)];

describe("the Mass Messages tab in a chatter-only session", () => {
  afterEach(() => {
    session.user = { user_id: 1 };
    session.chatter = null;
    vi.unstubAllGlobals();
  });

  it("a chatter-only session: the tab renders from the chatter's own Creators", async () => {
    session.user = null;
    session.chatter = { id: 7 };
    const fetchMock = vi.fn((url: string) => Promise.resolve(
      String(url) === "/chatter/me/accounts"
        ? new Response(JSON.stringify([{ account_id: ACC, nickname: "Model A" }]), { status: 200 })
        : new Response("{}", { status: 404 }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    await mountMass();

    // The rest of the tab: the child tabs, the sent history with its
    // Auto-unsend card, the scheduled list, and the header's New Message.
    expect(tabNames(childTabs())).toEqual(["Priority mass messages", "OF mass messages"]);
    const panel = screen.getByRole("tabpanel", { name: "OF mass messages" });
    expect(within(panel).getByRole("heading", { name: "Mass messages" })).toBeTruthy();
    expect(within(panel).getByText("Auto-unsend (automation)")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Every scheduled send, direct and mass" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "New Message" })).toBeTruthy();
    // Its Creators came from the chatter's own list, never the owner registry.
    expect(fetchMock).toHaveBeenCalledWith("/chatter/me/accounts", expect.anything());
    const paths = calledPaths();
    // The roster badge counts are the principal's own (a chatter's union of linked Creators), not the registry.
    expect(paths.filter((p) => p.startsWith("/admin/accounts") && p !== "/admin/accounts/roster-counts")).toEqual([]);
    expect(writesMade().filter((w) => w !== CACHE_WARM)).toEqual([]);
  });
});
