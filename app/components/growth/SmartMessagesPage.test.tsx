/**
 * Seam 1 of docs/spec/infloww-parity-round-2/phase-02-growth-pages.md: the
 * Smart Messages page rendered with `@/lib/relay` mocked, a fresh QueryClient,
 * two placeholder Creators, and `MassMessagesSection` mocked (Phase 2b's tab,
 * pinned by its own file, `MassMessagesSection.test.tsx`).
 *
 * Ticket 41: the "Automated Messages" tab opens by default, holds the
 * capture's filter bar and table, and lists the Nudge message (`nudge_online`)
 * as a row that opens the existing nudge editor. Every label it checks is read
 * from the Layout capture on disk by its Item ID, never typed from memory.
 *
 * Delayed welcome (ticket 43, rebound by the owner's ruling of 2026-10-18,
 * Phase 2 N1): the row is our `send_welcome` automation, present only when the
 * Creator has a `send_welcome` rule, whose Status maps the rule's on/off; the
 * row and the pop-up's "Subscriber welcome" card open the Delayed welcome
 * editor, which saves the rule's on/off, check interval and message through
 * the automation-rules routes, the payload merged. The OnlyFans welcome slot is
 * no longer a row, and OnlyFans' own welcome switch neither blocks nor is read
 * (Infloww has no such rule).
 *
 * Ticket 44 (owner ruling N2, position B): the "Purchased" Trigger is wired.
 * The account's `purchase_followup` rule is a "Purchased" row; the row and the
 * pop-up's "Purchases" card open its editor, which reads and saves through
 * `/admin/purchase-followup-config`.
 *
 * The lifecycle Triggers (Nearing expiry, Expired, Resubscribe, Birthday) are
 * wired the same way: each is the account's rule of its kind, a row and a card
 * that open `LifecycleMessageEditor`, saved through
 * `/admin/lifecycle-message-config`. "Not Purchased" stays Not wired. The
 * Actions cell cancels an Active row; Date created filters the rows.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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

// An owner session: /admin/accounts is the account source.
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: { user_id: 1 } }),
  useOptionalUser: () => ({ user: { user_id: 1 } }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: null }),
  useOptionalChatter: () => ({ chatter: null }),
}));
// No global creator: the Priority mass composer's "Post as" would seed the first Creator unless handed the chip's.
vi.mock("@/contexts/ScopeContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ScopeContext")>()),
  useScope: () => ({ scope: { kind: "all" }, accountId: null, setScope: () => {} }),
}));
// The creator column's unread chips poll the roster counts; not this page's reads.
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCounts: () => ({}) }));
vi.mock("@/components/growth/MassMessagesSection", () => ({
  default: () => <div data-testid="mass-section">mass section</div>,
}));

import SmartMessagesPage from "@/components/growth/SmartMessagesPage";
import { SM, SM_AUTOMATED_COLUMNS, SM_TRIGGERS } from "@/components/growth/smartMessagesControls";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPatch = relay.patch as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;
const relayUpload = relay.uploadFile as unknown as Mock;
const allMocks = [relayGet, relayPost, relayPatch, relayPut, relayDelete, relayUpload];
const relayCalls = () => allMocks.map((m) => m.mock.calls.length);

// Two placeholder Creators.
const A = { id: "acc-1", nickname: "Model A", has_session: true };
const B = { id: "acc-2", nickname: "Model B", has_session: true };
const RULE_ID: Record<string, number> = { [A.id]: 11, [B.id]: 12 };

// ── The Layout capture on disk ───────────────────────────────────────────
const capture = readFileSync(
  resolve(__dirname, "../../../docs/infloww-layouts/growth-smart-messages.md"), "utf-8",
);
const rowOf = (n: number) => {
  const row = capture.split("\n").find((l) => l.startsWith(`| growth-smart-messages#${n} |`));
  if (!row) throw new Error(`growth-smart-messages#${n} is not a row of the capture`);
  return row.split("|").map((c) => c.trim());
};
/** An Items row's Value cell. */
const valueOf = (n: number) => rowOf(n)[4];
/** The label an Items row records: its Value up to the first ", " (the width follows). */
const labelOf = (n: number) => valueOf(n).split(", ")[0];
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
/** The Triggers section's list labels, in its order (#116 to #123). */
const triggerLabels = range(116, 123).map((n) => /list label "([^"]+)"/.exec(rowOf(n)[2])![1]);
const statusValues = valueOf(28).split(" / ");

/** The quoted label a tab row records ("Automated Messages", rendered as …). */
const quoted = (n: number) => /"([^"]+)"/.exec(valueOf(n))![1];
const TAB_AUTOMATED = quoted(5);
const TAB_MASS = quoted(6);
const NO_DATA = valueOf(53);

let client: QueryClient;
let expectedWrites: string[] = [];

beforeEach(() => {
  allMocks.forEach((m) => m.mockReset());
  relayPut.mockImplementation((_p: string, body: { account_id: string; config: unknown }) =>
    Promise.resolve({ account_id: body.account_id, config: body.config }));
  relayPatch.mockImplementation((p: string) => Promise.resolve({ id: Number(String(p).split("/").pop()) }));
});
afterEach(() => {
  // No relay write but the ones the test named.
  const writes = { POST: relayPost, PATCH: relayPatch, PUT: relayPut, DELETE: relayDelete, UPLOAD: relayUpload };
  const made = Object.entries(writes).flatMap(([verb, m]) =>
    m.mock.calls.map(([path]) => `${verb} ${String(path).split("?")[0]}`));
  const allowed = expectedWrites;
  expectedWrites = [];
  cleanup();
  vi.unstubAllGlobals();
  for (const w of made) expect(allowed, `unexpected relay write: ${w}`).toContain(w);
});

const WELCOME_RULE_ID: Record<string, number> = { [A.id]: 21, [B.id]: 22 };
const welcomeRule = (accountId: string, isEnabled: boolean, everySeconds = 300, message?: string | string[]) => ({
  id: WELCOME_RULE_ID[accountId], account_id: accountId, name: "Welcome new subscribers", kind: "send_welcome",
  is_enabled: isEnabled, every_seconds: everySeconds, trigger: { type: "interval" },
  payload: { question: "what's yours?", follow_back: true, follow_back_gate: true, ...(message ? { message } : {}) },
  quiet_hours: null, created_at: "2026-02-03T12:00:00Z", last_run: null, next_due_at: null,
  has_pending_job: false,
});

const nudgeRule = (accountId: string, isEnabled: boolean) => ({
  id: RULE_ID[accountId], account_id: accountId, name: "Nudge online", kind: "nudge_online",
  is_enabled: isEnabled, every_seconds: 60, trigger: { type: "interval" }, payload: {},
  quiet_hours: null, created_at: "2026-01-05T12:00:00Z", last_run: null, next_due_at: null,
  has_pending_job: false,
});

const PURCHASE_RULE_ID: Record<string, number> = { [A.id]: 31, [B.id]: 32 };
/** A rule's Smart Message settings as its payload stores them (smart_message_extras). */
type ExtrasFixture = { media_ids?: number[]; price_cents?: number; starts_at?: string | null; ends_at?: string | null };
type PurchaseFixture = { on: boolean; text: string } & ExtrasFixture;
const purchaseRule = (accountId: string, { on, text, ...extras }: PurchaseFixture) => ({
  id: PURCHASE_RULE_ID[accountId], account_id: accountId, name: "Message on purchase", kind: "purchase_followup",
  is_enabled: on, every_seconds: 60, trigger: { every_seconds: 60 },
  payload: { enabled: on, text, delay_range: [1, 3], ...extras },
  quiet_hours: null, created_at: "2026-01-06T12:00:00Z", last_run: null, next_due_at: null,
  has_pending_job: false,
});

const LIFECYCLE_RULE_ID: Record<string, number> = {
  expiry_message: 41, expired_message: 42, resubscribe_message: 43, birthday_message: 44,
};
type LifecycleFixture = { on: boolean; text: string; hours?: number | null; createdAt?: string; sent?: number } & ExtrasFixture;
const lifecycleRule = (accountId: string, kind: string, p: LifecycleFixture) => ({
  id: LIFECYCLE_RULE_ID[kind] + (accountId === A.id ? 0 : 100), account_id: accountId, name: kind, kind,
  is_enabled: p.on, every_seconds: 1800, trigger: { every_seconds: 1800 },
  payload: {
    enabled: p.on, text: p.text, hours: p.hours ?? null,
    ...Object.fromEntries((["media_ids", "price_cents", "starts_at", "ends_at"] as const)
      .filter((k) => p[k] !== undefined).map((k) => [k, p[k]])),
  },
  quiet_hours: null, created_at: p.createdAt ?? "2026-01-07T12:00:00Z", last_run: null, next_due_at: null,
  has_pending_job: false,
  ...(p.sent === undefined ? {} : { sent: p.sent }),
});

type Fixture = {
  /** Per Creator, its lifecycle rules by kind; absent, none. */
  lifecycle?: Record<string, Record<string, LifecycleFixture>>;
  nudge?: Record<string, boolean>;
  /** Per Creator, its purchase_followup rule's on/off and text; absent, no rule. */
  purchase?: Record<string, PurchaseFixture>;
  lines?: Record<string, string>;
  /** Per Creator, its OnlyFans welcome slot's text; absent, no slot. Never a row since the 2026-10-18 ruling. */
  welcome?: Record<string, string>;
  /** Per Creator, OnlyFans' own reply-on-subscribe switch; absent, off. Mutable: a PATCH to it updates the read. */
  ofOn?: Record<string, boolean>;
  /** Per Creator, its `send_welcome` rule (on or off, and its delay in seconds); absent, none. */
  welcomeRules?: Record<string, { on: boolean; everySeconds?: number; message?: string | string[] }>;
  /** The Agency's report time zone, from the Applied settings read; absent, none saved. */
  reportTz?: string;
  /** Per Creator, OnlyFans' subscription price (0 = a free page); absent, unknown. */
  subscribePrice?: Record<string, number>;
  /** The automation-rules read fails. */
  failRules?: boolean;
  /** The Creators read lists none. */
  noCreators?: boolean;
};

/** The Relay's Smart Message settings before anything is saved. */
const EXTRAS_DEFAULTS = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0 };

const TEMPLATES_READ = "/api/of/v2/messages/templates";
const SETTINGS = "/api/of/v2/users/me/settings";
const TOGGLE = "/api/of/v2/users/me/reply-on-subscribe";

/** Answer the page's reads: two active Creators; per Creator, its nudge rule
 *  (on or off, or none), one tease line in its nudge config, and its welcome
 *  slot (or none) beside a saved-reply template, which is not a row. */
function stubReads({
  lifecycle = {}, nudge = {}, purchase = {}, lines = {}, welcome = {}, ofOn = {}, welcomeRules = {}, subscribePrice = {}, reportTz, failRules, noCreators,
}: Fixture) {
  const acc = (p: string) => new URLSearchParams(p.split("?")[1] ?? "").get("account_id") ?? "";
  relayGet.mockImplementation((path: string, ctx?: { accountId?: string }) => {
    const p = String(path);
    const of = ctx?.accountId ?? "";
    if (p === TEMPLATES_READ) {
      const reply = { id: `r-${of}`, template: null, text: "A saved reply, not a row", media: [] };
      const w = welcome[of];
      const slot = w && { id: `w-${of}`, template: "reply_on_subscribe", text: w, price: 0, mediaCount: 0, media: [] };
      return Promise.resolve(slot ? [reply, slot] : [reply]);
    }
    if (p === "/api/of/v2/users/me") {
      return Promise.resolve(of in subscribePrice ? { name: `${of} page`, subscribePrice: subscribePrice[of] } : {});
    }
    if (p === SETTINGS) {
      return Promise.resolve({ replyOnSubscribe: !!ofOn[of] });
    }
    if (p === "/admin/settings/applied") {
      return Promise.resolve({ preferences: { tz: null, report_tz: reportTz ?? null, week_start: "monday" } });
    }
    if (p.startsWith("/admin/accounts")) {
      return Promise.resolve(noCreators ? { accounts: [], active_account_id: null } : { accounts: [A, B], active_account_id: A.id });
    }
    if (p.startsWith("/admin/automation-rules")) {
      if (failRules) return Promise.reject(new Error("fixture failure"));
      const id = acc(p);
      const w = welcomeRules[id];
      return Promise.resolve({ rules: [
        ...(id in nudge ? [nudgeRule(id, nudge[id])] : []),
        ...(w ? [welcomeRule(id, w.on, w.everySeconds, w.message)] : []),
        ...(id in purchase ? [purchaseRule(id, purchase[id])] : []),
        ...Object.entries(lifecycle[id] ?? {}).map(([kind, l]) => lifecycleRule(id, kind, l)),
      ] });
    }
    if (p.startsWith("/admin/lifecycle-message-config/buyers")) return Promise.resolve({ window_days: 7, buyers: [] });
    if (p.startsWith("/admin/lifecycle-message-config")) {
      const id = acc(p);
      const kind = new URLSearchParams(p.split("?")[1] ?? "").get("kind") ?? "";
      const hours = kind === "expiry_message" || kind === "expired_message" ? 24 : null;
      const defaults = { enabled: false, text: "", hours, messages: [], ...EXTRAS_DEFAULTS, frequency: "once" };
      const c = lifecycle[id]?.[kind];
      return Promise.resolve({
        account_id: id, kind, defaults,
        config: c ? {
          ...defaults, enabled: c.on, text: c.text, hours: c.hours ?? hours, frequency: "every",
          messages: [{ variants: [c.text], follow_ups: [], discount: null }],
        } : defaults,
      });
    }
    if (p.startsWith("/admin/purchase-followup-config")) {
      const id = acc(p);
      const defaults = { enabled: false, text: "", ...EXTRAS_DEFAULTS, frequency: "every", delay_range: [1, 3] };
      const c = purchase[id];
      return Promise.resolve({
        account_id: id, defaults,
        config: c ? (({ on, text, ...extras }) => ({ ...defaults, enabled: on, text, ...extras }))(c) : defaults,
      });
    }
    if (p.startsWith("/admin/nudge-config")) {
      const id = acc(p);
      const text = lines[id] ? [lines[id]] : [];
      return Promise.resolve({
        account_id: id, config: { enabled: true, slots: { default: { morning_1: { text } } } }, defaults: {},
      });
    }
    return Promise.resolve({});
  });
}

async function mount(url = "/growth/smart-messages", fixture: Fixture = {}) {
  window.history.replaceState(null, "", url);
  relayGet.mockClear(); // the wait below reads this mount's calls only
  stubReads(fixture);
  // A fresh cache per mount, so a second mount in one test reads its own fixture.
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
  // The Creators load first; the tab's reads start once the chip holds one.
  await waitFor(() => {
    const paths = relayGet.mock.calls.map(([p]) => String(p));
    expect(paths.some((p) => p.startsWith("/admin/accounts"))).toBe(true);
    if (screen.queryByRole("tabpanel", { name: TAB_AUTOMATED })) {
      expect(paths.some((p) => p.startsWith("/admin/automation-rules"))).toBe(true);
    }
    expect(client.isFetching()).toBe(0);
  });
}

const parentTabs = () => screen.getByRole("tablist", { name: "Smart Messages" });
const tabNames = () => within(parentTabs()).getAllByRole("tab").map((t) => t.textContent);
const selected = () => within(parentTabs()).getAllByRole("tab")
  .filter((t) => t.getAttribute("aria-selected") === "true").map((t) => t.textContent);
const panel = () => screen.getByRole("tabpanel", { name: TAB_AUTOMATED });
const rows = () => within(panel()).getAllByRole("row").slice(1);
const before = (a: Element, b: Element) =>
  !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
/** The Automated tab's creator column (`CreatorRail`, Smart lists'), and its row for a Creator. */
const column = () => screen.getByTestId("of-creator-column");
const creatorRow = (nickname: string) =>
  within(column()).getByRole("button", { name: new RegExp(nickname) });
/** Picks a Creator on the creator column. */
const pickCreator = (nickname: string) => act(async () => { fireEvent.click(creatorRow(nickname)); });

/** The filter bar's controls, in the capture's order (#24 to #37), found by
 *  the capture's labels. */
function filterBar() {
  const p = within(panel());
  return {
    search: p.getByRole("textbox", { name: labelOf(24) }),
    status: p.getByRole("combobox", { name: labelOf(27) }),
    trigger: p.getByRole("combobox", { name: labelOf(29) }),
    sentTo: p.getByRole("combobox", { name: labelOf(30) }),
    startDate: p.getByLabelText(labelOf(31)),
    dateCreated: p.getByLabelText(labelOf(32)),
    createdBy: p.getByRole("combobox", { name: labelOf(33) }),
    reset: p.getByRole("button", { name: labelOf(36) }),
    apply: p.getByRole("button", { name: labelOf(37) }),
  };
}

/** Open a listbox select (`IfSelect`, `IfCreatorSelect`) and pick the option named `name`. */
async function choose(box: HTMLElement, name: string | RegExp) {
  await act(async () => { fireEvent.click(box); });
  await act(async () => { fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name })); });
}

/** A listbox select's options, read with it open, then closed again. */
function optionsOf(box: HTMLElement) {
  fireEvent.click(box);
  const options = within(screen.getByRole("listbox")).getAllByRole("option");
  fireEvent.click(box);
  return options;
}

/** "" picks the placeholder option "All". */
async function applyFilters(set: { search?: string; status?: string; trigger?: string }) {
  const bar = filterBar();
  await act(async () => {
    if (set.search !== undefined) fireEvent.change(bar.search, { target: { value: set.search } });
  });
  if (set.status !== undefined) await choose(bar.status, set.status || "All");
  if (set.trigger !== undefined) await choose(bar.trigger, set.trigger || "All");
  await act(async () => { fireEvent.click(bar.apply); });
}

describe("the Automated Messages catalogue matches the Layout capture on disk", () => {
  const sourcesOf = (cell: string) => cell.split(";").map((s) => s.trim());

  it.each(SM_AUTOMATED_COLUMNS.map((c) => [c.id, c] as const))("%s: its label, width and sources", (_id, c) => {
    const row = rowOf(Number(c.id.split("#")[1]));
    expect(row[4]).toBe(`${c.label}, ${c.width}px`);
    for (const s of c.sources) expect(sourcesOf(row[5])).toContain(s);
  });

  it.each(SM_TRIGGERS.map((t) => [t.id, t] as const))("%s: its list label and that label's source", (_id, t) => {
    const row = rowOf(Number(t.id.split("#")[1]));
    expect(row[2]).toContain(`list label "${t.label}"`);
    for (const s of t.sources) expect(sourcesOf(row[3])).toContain(s);
  });
});

describe("Automated Messages tab (ticket 41)", () => {
  it("renders before Mass Messages and is the default; ?tab=mass and ?tab=scheduled still open Mass Messages", async () => {
    for (const url of ["", "?tab=bogus", "?tab=automated"]) {
      await mount(`/growth/smart-messages${url}`);
      expect(tabNames()).toEqual([TAB_AUTOMATED, TAB_MASS]);
      expect(selected()).toEqual([TAB_AUTOMATED]);
      expect(panel()).toBeTruthy();
      expect(screen.queryByTestId("mass-section")).toBeNull();
      cleanup();
    }
    for (const url of ["?tab=mass", "?tab=scheduled"]) {
      await mount(`/growth/smart-messages${url}`);
      expect(selected()).toEqual([TAB_MASS]);
      const mass = screen.getByRole("tabpanel", { name: TAB_MASS });
      expect(within(mass).getByTestId("mass-section")).toBeTruthy();
      expect(screen.queryByRole("tabpanel", { name: TAB_AUTOMATED })).toBeNull();
      cleanup();
    }
  });

  it("the filter bar and the column headers follow the capture's order", async () => {
    await mount();
    const bar = Object.values(filterBar());
    for (let i = 1; i < bar.length; i++) expect(before(bar[i - 1], bar[i])).toBe(true);
    const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(range(39, 52).map(labelOf));
    // The bar sits above the table.
    expect(before(bar[bar.length - 1], within(panel()).getByRole("table"))).toBe(true);
  });

  it("with no nudge configured there is no row, and the capture's empty state shows", async () => {
    await mount();
    expect(within(panel()).getByText(NO_DATA)).toBeTruthy();
    // The one body row is the empty state; no row carries a Trigger.
    expect(rows()).toHaveLength(1);
    expect(within(rows()[0]).queryByText(triggerLabels[0])).toBeNull();
  });

  it("the Nudge row exists when configured; its Status maps on to Active and off to Canceled", async () => {
    await mount(undefined, { nudge: { [A.id]: true }, lines: { [A.id]: "Hey you, fixture line" } });
    expect(rows()).toHaveLength(1);
    const cells = within(rows()[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[0]).toBe("Hey you, fixture line");
    expect(cells[1]).toBe(statusValues[1]); // Active
    expect(cells[2]).toBe(triggerLabels[0]); // Nudge
    expect(within(panel()).queryByText(NO_DATA)).toBeNull();
    cleanup();

    await mount(undefined, { nudge: { [A.id]: false } });
    const off = within(rows()[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(off[1]).toBe(statusValues[3]); // Canceled
    expect(off[2]).toBe(triggerLabels[0]);
  });

  it("opening the Nudge row opens the existing nudge editor, labelled Inflowwww extra", async () => {
    await mount(undefined, { nudge: { [A.id]: true }, lines: { [A.id]: "Hey you, fixture line" } });
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => { fireEvent.click(within(rows()[0]).getByRole("button", { name: "Hey you, fixture line" })); });
    const dialog = screen.getByRole("dialog", { name: triggerLabels[0] });
    // The editor, mounted unchanged: its own heading and its save.
    expect(within(dialog).getByRole("heading", { name: "Nudge online" })).toBeTruthy();
    const tag = within(dialog).getByText(EXTRA_LABEL);
    expect(tag.getAttribute("title")).toBe(EXTRA_LABEL);
    await waitFor(() => expect(within(dialog).getAllByRole("button", { name: /Save changes/ }).length).toBeGreaterThan(0));
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Close" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("no mass label appears inside the tab, and the page imports none of the mass components", async () => {
    await mount(undefined, { nudge: { [A.id]: true }, lines: { [A.id]: "Hey you, fixture line" } });
    const text = panel().textContent ?? "";
    // The capture's mass strings (#56, #57, #66, #73, #79, #106 to #108) and ours.
    const mass = [labelOf(56), labelOf(57), labelOf(66), labelOf(73), labelOf(79), labelOf(106),
      valueOf(107).split(" / ")[0], valueOf(108).split(" / ")[0],
      "Message online fans", "Mass Nudge", "Auto-unsend"];
    for (const m of mass) expect(text, m).not.toContain(m);
    expect(text).not.toMatch(/mass/i);

    const src = readFileSync(resolve(__dirname, "SmartMessagesPage.tsx"), "utf-8");
    expect(src).not.toMatch(/MassMessagesTab|ScheduledTab|LazyMassMessageComposer|AutoUnsendPanel/);
    expect(src).toContain("<MassMessagesSection");
  });

  it("search, Status and Trigger filter the rows; Reset clears them", async () => {
    await mount(undefined, { nudge: { [A.id]: true }, lines: { [A.id]: "Hey you, fixture line" } });
    const calls = relayCalls();

    await applyFilters({ search: "nothing like it" });
    expect(within(panel()).getByText(NO_DATA)).toBeTruthy();
    await applyFilters({ search: "FIXTURE" });
    expect(rows()).toHaveLength(1);

    await applyFilters({ search: "", status: statusValues[3] }); // Canceled
    expect(within(panel()).getByText(NO_DATA)).toBeTruthy();
    await applyFilters({ status: statusValues[1] }); // Active
    expect(rows()).toHaveLength(1);

    await applyFilters({ status: "", trigger: triggerLabels[0] }); // Nudge
    expect(rows()).toHaveLength(1);

    await applyFilters({ search: "nothing like it" });
    expect(within(panel()).getByText(NO_DATA)).toBeTruthy();
    await act(async () => { fireEvent.click(filterBar().reset); });
    expect(rows()).toHaveLength(1);
    expect((filterBar().search as HTMLInputElement).value).toBe("");
    // Filtering is on the rows already read: no relay call.
    expect(relayCalls()).toEqual(calls);
  });

  it("the Status and Trigger options are the capture's, in its order; those with nothing behind them are Not wired", async () => {
    await mount();
    // The first option is the placeholder "All".
    const options = (el: HTMLElement) => optionsOf(el).slice(1);
    const { status, trigger } = filterBar();
    const notWired = (o: HTMLElement) => !!o.querySelector('[title="not wired"]');

    const statusOptions = options(status);
    expect(statusOptions.map((o) => o.textContent)).toEqual(statusValues);
    // A rule on or off, and one that is on before its Effective date or past its Expiry.
    for (const o of statusOptions) {
      expect(o, o.textContent!).not.toHaveAttribute("aria-disabled");
      expect(notWired(o)).toBe(false);
    }

    const triggerOptions = options(trigger);
    expect(triggerOptions.map((o) => o.textContent)).toEqual(triggerLabels);
    for (const o of triggerOptions) {
      const wired = triggerLabels.slice(0, 7).includes(o.textContent!); // all but Not Purchased
      expect(o.getAttribute("aria-disabled") === "true", o.textContent!).toBe(!wired);
      expect(notWired(o)).toBe(!wired);
    }
  });

  it("every other filter is disabled, titled not wired and calls nothing; Sent and Purchased are Not wired cells", async () => {
    await mount(undefined, { nudge: { [A.id]: true } });
    const { sentTo, startDate, createdBy } = filterBar();
    const calls = relayCalls();
    for (const c of [sentTo, startDate, createdBy]) {
      expect(c).toBeDisabled();
      expect(c.closest("[title]")).toHaveAttribute("title", "not wired");
      await act(async () => { fireEvent.click(c); });
    }
    expect(relayCalls()).toEqual(calls);

    const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
    const cells = within(rows()[0]).getAllByRole("cell");
    for (const name of [labelOf(42), labelOf(43)]) { // Sent, Purchased
      const cell = cells[headers.indexOf(name)];
      expect(cell.textContent, name).toBe("—");
      expect(cell).toHaveAttribute("title", "not wired");
    }
  });

  it("Sent shows the rules list's count on a smart message's row; Nudge's stays Not wired", async () => {
    await mount(undefined, {
      nudge: { [A.id]: true },
      lifecycle: { [A.id]: { resubscribe_message: { on: true, text: "Welcome back, fixture", sent: 1234 } } },
    });
    const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
    const sentOf = (trigger: string) => within(rowOfTrigger(trigger)!).getAllByRole("cell")[headers.indexOf(labelOf(42))];
    expect(sentOf(triggerLabels[5]).textContent).toBe("1,234");
    expect(sentOf(triggerLabels[5])).not.toHaveAttribute("title", "not wired");
    expect(sentOf(triggerLabels[0]).textContent).toBe("—");
    expect(sentOf(triggerLabels[0])).toHaveAttribute("title", "not wired");
  });

  it("the creator chip picks the Creator: the next nudge-config read and write carry the second Creator's account_id", async () => {
    await mount(undefined, {
      nudge: { [A.id]: true, [B.id]: false },
      lines: { [A.id]: "Line of Model A", [B.id]: "Line of Model B" },
    });
    // The first Creator is the pick until another is clicked on the creator column.
    expect(creatorRow(A.nickname)).toHaveAttribute("aria-current", "true");
    expect(creatorRow(B.nickname)).not.toHaveAttribute("aria-current");
    expect(within(rows()[0]).getAllByRole("cell")[0].textContent).toBe("Line of Model A");

    const reads = relayGet.mock.calls.length;
    await pickCreator(B.nickname);
    expect(creatorRow(B.nickname)).toHaveAttribute("aria-current", "true");
    expect(creatorRow(A.nickname)).not.toHaveAttribute("aria-current");
    await waitFor(() => expect(within(rows()[0]).getAllByRole("cell")[0].textContent).toBe("Line of Model B"));
    const nudgeReads = relayGet.mock.calls.slice(reads).map(([p]) => String(p))
      .filter((p) => p.startsWith("/admin/nudge-config"));
    expect(nudgeReads).toEqual([`/admin/nudge-config?account_id=${B.id}`]);
    expect(within(rows()[0]).getAllByRole("cell")[1].textContent).toBe(statusValues[3]);

    // The row's editor opens on the same Creator, and its save writes for it.
    // The PUT is the only write: the relay syncs B's nudge_online rule inside it.
    expectedWrites.push("PUT /admin/nudge-config");
    await act(async () => { fireEvent.click(within(rows()[0]).getByRole("button", { name: "Line of Model B" })); });
    const dialog = screen.getByRole("dialog", { name: triggerLabels[0] });
    const save = await waitFor(() => {
      const b = within(dialog).getAllByRole("button", { name: /Save changes/ })[0];
      expect(b).not.toBeDisabled();
      return b;
    });
    await act(async () => { fireEvent.click(save); });
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    const [path, body] = relayPut.mock.calls[0] as [string, { account_id: string }];
    expect(path).toBe("/admin/nudge-config");
    expect(body.account_id).toBe(B.id);
    expect(relayPatch).not.toHaveBeenCalled();
  });
});

// ── Ticket 42: the Create message pop-up's Automated messages section ────

/** A Triggers row's pop-up card, as the capture records it: `card "<title>",
 *  "<second line>"`, then `tag "<tag>"` where the card has one; null for a
 *  Trigger with no card (#123, a list label only). */
const cardOf = (n: number) => {
  const m = /^card "([^"]+)", "([^"]+)"(?:, tag "([^"]+)")?;/.exec(rowOf(n)[2]);
  return m ? { title: m[1], desc: m[2], tag: m[3] ?? null } : null;
};
const triggerRows = range(116, 123);
/** The capture's cards, in its Triggers order. */
const captureCards = triggerRows.map(cardOf).filter((c) => c !== null);
const NUDGE_CARD = cardOf(116)!;
const WELCOME_CARD = cardOf(117)!;
const PURCHASE_CARD = cardOf(118)!;
const POP_UP = labelOf(103); // "Create message"
/** "Start from scratch" (#104), the template line (#105) and the section (#109): Value cells verbatim. */
const SCRATCH = valueOf(104);
const TEMPLATES = valueOf(105);
const AUTOMATED = valueOf(109);

const popUp = () => screen.getByRole("dialog", { name: POP_UP });
const automatedSection = () => within(popUp()).getByRole("region", { name: AUTOMATED });
/** A card's title: the first line its button renders. */
const titleOf = (b: HTMLElement) => b.querySelector("span span")?.textContent;
/** The section's cards, in DOM order: every button but "Start from scratch". */
const automatedCards = () => within(automatedSection()).getAllByRole("button")
  .filter((b) => b.textContent !== SCRATCH);
const cardNamed = (title: string) => automatedCards().find((b) => titleOf(b) === title)!;
const nextButton = () => within(popUp()).getByRole("button", { name: labelOf(110) });

async function openPopUp() {
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: labelOf(15) })); });
  return popUp();
}

describe("the Trigger catalogue's pop-up cards match the Layout capture on disk", () => {
  const sourcesOf = (cell: string) => cell.split(";").map((s) => s.trim());

  it.each(SM_TRIGGERS.map((t) => [t.id, t] as const))("%s: its card title, second line, tag and their sources", (_id, t) => {
    const n = Number(t.id.split("#")[1]);
    const want = cardOf(n);
    if (!want) { expect(t.card).toBeNull(); return; }
    expect(t.card).toMatchObject({ label: want.title, desc: want.desc });
    expect(t.card && "tag" in t.card ? t.card.tag : null).toBe(want.tag);
    for (const s of t.card!.sources) expect(sourcesOf(rowOf(n)[3])).toContain(s);
  });
});

describe("the Create message pop-up's Automated messages section (ticket 42)", () => {
  it("follows Mass messages, opens with Start from scratch and the template line, then the capture's cards in its Triggers order", async () => {
    await mount();
    const dialog = await openPopUp();
    const regions = within(dialog).getAllByRole("region");
    expect(regions.map((r) => r.querySelector("h3")?.textContent)).toEqual([labelOf(106), AUTOMATED]);
    const section = automatedSection();
    const scratch = within(section).getByRole("button", { name: SCRATCH });
    expect(section.textContent).toContain(TEMPLATES);
    const cards = automatedCards();
    expect(before(scratch, cards[0])).toBe(true);
    // Each card: its title, its second line, and the Nudge card's tag, as the capture spells them.
    expect(cards.map((c) => c.textContent)).toEqual(
      captureCards.map((c) => c.title + c.desc + (c.tag ?? "")),
    );
    // The section sits before the buttons.
    expect(before(cards[cards.length - 1], within(dialog).getByRole("button", { name: labelOf(111) }))).toBe(true);
  });

  it("the section and the Trigger filter read one catalogue: same Triggers, same order, same ones wired", async () => {
    await mount();
    const { trigger } = filterBar();
    const options = optionsOf(trigger).slice(1);
    // The filter lists every list label; the pop-up every Trigger with a card,
    // in the same order (#123, "Not Purchased", has no card in the bundle).
    expect(options.map((o) => o.textContent)).toEqual(triggerLabels);
    await openPopUp();
    const withCard = triggerRows.filter((n) => cardOf(n) !== null);
    expect(automatedCards().map(titleOf)).toEqual(withCard.map((n) => cardOf(n)!.title));
    // The wired Triggers are the same in both: every one with a card ("Not
    // Purchased" has no rule in the bundle's rules enum).
    const wiredOptions = options.filter((o) => o.getAttribute("aria-disabled") !== "true").map((o) => o.textContent);
    const wiredCards = automatedCards().filter((c) => !(c as HTMLButtonElement).disabled).map(titleOf);
    expect(wiredOptions).toEqual(triggerLabels.slice(0, 7));
    expect(wiredCards).toEqual(withCard.map((n) => cardOf(n)!.title));
  });

  it('"Nudge", then Next, closes the pop-up and opens the existing nudge editor on the chip\'s Creator', async () => {
    await mount(undefined, { nudge: { [A.id]: true, [B.id]: true }, lines: { [B.id]: "Line of Model B" } });
    await pickCreator(B.nickname);
    await waitFor(() => expect(client.isFetching()).toBe(0));
    await openPopUp();
    expect(nextButton()).toBeDisabled();
    const nudge = cardNamed(NUDGE_CARD.title);
    expect(nudge).not.toBeDisabled();
    expect(nudge).not.toHaveAttribute("title", "not wired");
    await act(async () => { fireEvent.click(nudge); });
    expect(nudge).toHaveAttribute("aria-pressed", "true");
    const reads = relayGet.mock.calls.length;
    await act(async () => { fireEvent.click(nextButton()); });

    expect(screen.queryByRole("dialog", { name: POP_UP })).toBeNull();
    const dialog = screen.getByRole("dialog", { name: triggerLabels[0] });
    // The same editor the Nudge row opens: its own heading, the extra tag, and its save.
    expect(within(dialog).getByRole("heading", { name: "Nudge online" })).toBeTruthy();
    expect(within(dialog).getByText(EXTRA_LABEL).getAttribute("title")).toBe(EXTRA_LABEL);
    await waitFor(() => expect(within(dialog).getAllByRole("button", { name: /Save changes/ }).length).toBeGreaterThan(0));
    await waitFor(() => expect(client.isFetching()).toBe(0));
    // Its reads are the chip's Creator's.
    const nudgeReads = relayGet.mock.calls.slice(reads).map(([p]) => String(p))
      .filter((p) => p.startsWith("/admin/nudge-config"));
    for (const p of nudgeReads) expect(p).toBe(`/admin/nudge-config?account_id=${B.id}`);
    expect((within(dialog).getAllByRole("combobox")[0] as HTMLSelectElement).value).toBe(B.id);
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Close" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it('"Priority mass message", then Next, opens its composer posting as the chip\'s Creator', async () => {
    await mount();
    await pickCreator(B.nickname);
    await openPopUp();
    const priority = within(popUp()).getByRole("button", { name: new RegExp(`^${valueOf(107).split(" / ")[0]}`) });
    await act(async () => { fireEvent.click(priority); });
    await act(async () => { fireEvent.click(nextButton()); });
    const dialog = screen.getByRole("dialog", { name: "Priority mass message" });
    await waitFor(() => expect((within(dialog).getAllByRole("combobox")[0] as HTMLSelectElement).value).toBe(B.id));
  });

  it("Start from scratch is disabled, titled not wired, picks nothing and calls nothing; every card is wired", async () => {
    await mount();
    await openPopUp();
    const scratch = within(automatedSection()).getByRole("button", { name: SCRATCH });
    expect(automatedCards()).toHaveLength(captureCards.length);
    for (const c of automatedCards()) expect(c, c.textContent!).not.toBeDisabled();
    const calls = relayCalls();
    for (const c of [scratch]) {
      expect(c, c.textContent!).toBeDisabled();
      expect(c).toHaveAttribute("title", "not wired");
      await act(async () => { fireEvent.click(c); });
    }
    expect(relayCalls()).toEqual(calls);
    for (const c of automatedCards()) expect(c).toHaveAttribute("aria-pressed", "false");
    expect(nextButton()).toBeDisabled();
  });

  it("a Mass card and an Automated card share the one pick: picking one unpicks the other", async () => {
    await mount();
    await openPopUp();
    const of = within(popUp()).getByRole("button", { name: new RegExp(`^${valueOf(108).split(" / ")[0]}`) });
    const nudge = cardNamed(NUDGE_CARD.title);
    await act(async () => { fireEvent.click(of); });
    expect(of).toHaveAttribute("aria-pressed", "true");
    await act(async () => { fireEvent.click(nudge); });
    expect(nudge).toHaveAttribute("aria-pressed", "true");
    expect(of).toHaveAttribute("aria-pressed", "false");
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: labelOf(111) })); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// ── Ticket 43, rebound 2026-10-18: the Delayed welcome row is our send_welcome automation ──

const WELCOME = triggerLabels[1]; // "Delayed welcome"
const triggerOf = (r: HTMLElement) => within(r).getAllByRole("cell")[2]?.textContent;
const welcomeRow = () => rows().find((r) => triggerOf(r) === WELCOME);
/** The calls a relay mock got for `path`: [path, body (writes only), the Creator its context named]. */
const callsTo = (m: Mock, path: string) => m.mock.calls
  .filter(([p]) => p === path)
  .map(([p, ...rest]) => [p, ...rest.slice(0, -1), (rest[rest.length - 1] as { accountId?: string } | undefined)?.accountId]);
const RULES = "/admin/automation-rules";
/** Every call a relay mock got for `path`, verbatim: [path, body] for a rule write, which names no Creator context. */
const rawCalls = (m: Mock, path: string) => m.mock.calls.filter(([p]) => p === path);
const ruleAt = (accountId: string) => `${RULES}/${WELCOME_RULE_ID[accountId]}`;
/** The editor's controls, by their labels. */
const welcomeEditor = () => {
  const d = screen.getByRole("dialog", { name: WELCOME });
  return {
    dialog: d,
    enabled: within(d).getByRole("checkbox", { name: "Enabled" }) as HTMLInputElement,
    delay: within(d).getByRole("spinbutton", { name: "Check every (minutes)" }) as HTMLInputElement,
    message: within(d).getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement,
    save: within(d).getByRole("button", { name: "Save" }),
  };
};

describe("the Delayed welcome row (ticket 43, bound to send_welcome by the 2026-10-18 ruling)", () => {
  it("exists only when the Creator has a send_welcome rule; its Status maps the rule on to Active and off to Canceled", async () => {
    await mount();
    expect(welcomeRow()).toBeUndefined();
    expect(within(panel()).getByText(NO_DATA)).toBeTruthy();
    cleanup();

    // An OnlyFans welcome slot, switched on, is not a row any more, and the tab no longer reads it.
    await mount(undefined, { welcome: { [A.id]: "Welcome in, fixture greeting" }, ofOn: { [A.id]: true } });
    expect(welcomeRow()).toBeUndefined();
    expect(callsTo(relayGet, TEMPLATES_READ)).toEqual([]);
    cleanup();

    await mount(undefined, { welcomeRules: { [A.id]: { on: true } } });
    expect(rows()).toHaveLength(1);
    const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
    const cells = within(welcomeRow()!).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[0]).toBe("Welcome new subscribers");
    expect(cells[1]).toBe(statusValues[1]); // Active
    expect(cells[2]).toBe(WELCOME);
    expect(cells[headers.indexOf(labelOf(51))]).toBe("Feb 3, 2026");
    cleanup();

    await mount(undefined, { welcomeRules: { [A.id]: { on: false } } });
    expect(within(welcomeRow()!).getAllByRole("cell")[1].textContent).toBe(statusValues[3]); // Canceled
  });

  it("names the row by its message, the first of several variants", async () => {
    await mount(undefined, { welcomeRules: { [A.id]: { on: true, message: ["Hey {name}, one", "Hey {name}, two"] } } });
    expect(within(welcomeRow()!).getAllByRole("cell")[0].textContent).toBe("Hey {name}, one");
  });

  it("follows the Nudge row, in the catalogue's order, and the Trigger filter and search pick it out", async () => {
    await mount(undefined, {
      nudge: { [A.id]: true }, lines: { [A.id]: "Hey you, fixture line" }, welcomeRules: { [A.id]: { on: true } },
    });
    expect(rows().map(triggerOf)).toEqual([triggerLabels[0], WELCOME]);
    await applyFilters({ trigger: WELCOME });
    expect(rows().map(triggerOf)).toEqual([WELCOME]);
    await applyFilters({ trigger: "", search: "new subscribers" });
    expect(rows().map(triggerOf)).toEqual([WELCOME]);
  });

  it("opening the row opens the Delayed welcome editor on the rule, labelled Inflowwww extra; Save writes its on/off, check interval and message", async () => {
    await mount(undefined, { welcomeRules: { [A.id]: { on: true, everySeconds: 600 } } });
    await act(async () => { fireEvent.click(within(welcomeRow()!).getByRole("button", { name: "Welcome new subscribers" })); });
    const e = welcomeEditor();
    expect(within(e.dialog).getByText(EXTRA_LABEL).getAttribute("title")).toBe(EXTRA_LABEL);
    // Not the OnlyFans welcome slot's editor.
    expect(within(e.dialog).queryByRole("heading", { name: "Welcome message" })).toBeNull();
    await waitFor(() => expect(welcomeEditor().save).not.toBeDisabled());
    expect(e.enabled.checked).toBe(true);
    expect(e.delay.value).toBe("10");
    expect(e.message.value).toBe("");
    expect(e.message.placeholder).toBe("Enter your message...");
    expect(within(e.dialog).queryByText(/Creator's voice/)).toBeNull();

    expectedWrites.push(`PATCH ${ruleAt(A.id)}`);
    fireEvent.change(e.delay, { target: { value: "15" } });
    fireEvent.change(e.message, { target: { value: "  Hey {name}, welcome in!  " } });
    await act(async () => { fireEvent.click(e.save); });
    // The payload is written back merged (a PATCH replaces it whole): the rule's other knobs stay as they are.
    await waitFor(() => expect(rawCalls(relayPatch, ruleAt(A.id))).toEqual([[ruleAt(A.id), {
      is_enabled: true, every_seconds: 900,
      payload: {
        question: "what's yours?", follow_back: true, follow_back_gate: true, message: "Hey {name}, welcome in!",
        // Its Smart Message settings; a rule saved before them sends immediately.
        ...EXTRAS_DEFAULTS, delay_range: null,
      },
    }]]));
    expect(callsTo(relayPatch, TOGGLE)).toEqual([]);

    await act(async () => { fireEvent.click(within(e.dialog).getByRole("button", { name: "Close" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("switches our welcome on whatever OnlyFans' own welcome reads, and never reads or writes that switch", async () => {
    await mount(undefined, { welcomeRules: { [A.id]: { on: false } }, ofOn: { [A.id]: true } });
    await act(async () => { fireEvent.click(within(welcomeRow()!).getByRole("button", { name: "Welcome new subscribers" })); });
    const e = welcomeEditor();
    expect(within(e.dialog).queryByText(/OnlyFans' own welcome/)).toBeNull();
    expect(within(e.dialog).queryByRole("button", { name: /Turn off OnlyFans/ })).toBeNull();
    fireEvent.click(e.enabled);
    expect(e.save).not.toBeDisabled();

    expectedWrites.push(`PATCH ${ruleAt(A.id)}`);
    await act(async () => { fireEvent.click(e.save); });
    await waitFor(() => expect(rawCalls(relayPatch, ruleAt(A.id))).toHaveLength(1));
    expect(rawCalls(relayPatch, ruleAt(A.id))[0][1]).toMatchObject({ is_enabled: true, every_seconds: 300 });
    expect(callsTo(relayGet, SETTINGS)).toEqual([]);
    expect(callsTo(relayPatch, TOGGLE)).toEqual([]);
  });

  it('"Subscriber welcome", then Next, opens the editor on the chip\'s Creator, where a rule is created off, with the Brain\'s defaults', async () => {
    await mount(undefined, { welcomeRules: { [A.id]: { on: true } } });
    await pickCreator(B.nickname);
    await waitFor(() => expect(client.isFetching()).toBe(0));
    // Model B has no rule, so no row.
    expect(welcomeRow()).toBeUndefined();

    await openPopUp();
    const card = cardNamed(WELCOME_CARD.title);
    expect(card).not.toBeDisabled();
    expect(card).not.toHaveAttribute("title", "not wired");
    await act(async () => { fireEvent.click(card); });
    expect(card).toHaveAttribute("aria-pressed", "true");
    await act(async () => { fireEvent.click(nextButton()); });

    expect(screen.queryByRole("dialog", { name: POP_UP })).toBeNull();
    const e = welcomeEditor();
    expect(within(e.dialog).getByText(EXTRA_LABEL).getAttribute("title")).toBe(EXTRA_LABEL);
    await waitFor(() => expect(welcomeEditor().save).not.toBeDisabled());
    // A new rule is off until the owner ticks it, with the Brain's 5-minute check.
    expect(e.enabled.checked).toBe(false);
    expect(e.delay.value).toBe("5");

    relayPost.mockResolvedValue({ id: 99 });
    expectedWrites.push(`POST ${RULES}`);
    await act(async () => { fireEvent.click(e.save); });
    // What an untouched welcome lane creates (DelayedWelcomeEditor's `WELCOME_CREATE_DEFAULTS`).
    await waitFor(() => expect(rawCalls(relayPost, RULES)).toEqual([[RULES, {
      account_id: B.id, kind: "send_welcome", name: "Welcome new subscribers", every_seconds: 300, is_enabled: false,
      payload: {
        time_only: true, skip_time_bubble: false, human_pace: true, stop_on_reply: true,
        follow_back: true, follow_back_gate: true, question: "what's yours?", gif_id: "", message: "",
        // Infloww's start for a new welcome: a 2～5 minute delay.
        ...EXTRAS_DEFAULTS, delay_range: [2, 5],
      },
    }]]));
  });
});

// ── Ticket 44: the Purchased row and editor, the purchase_followup rule ──

const PURCHASED = triggerLabels[2]; // "Purchased"
const purchasedRow = () => rows().find((r) => triggerOf(r) === PURCHASED);
const PF_CONFIG = "/admin/purchase-followup-config";
const FIXTURE_PURCHASE = { on: true, text: "Thanks for the unlock, fixture line" };

describe("the Purchased row and editor (ticket 44)", () => {
  it("exists only when the Creator has a purchase_followup rule; its Status maps the rule on to Active and off to Canceled", async () => {
    await mount();
    expect(purchasedRow()).toBeUndefined();
    cleanup();

    await mount(undefined, { purchase: { [A.id]: FIXTURE_PURCHASE } });
    expect(rows()).toHaveLength(1);
    const cells = within(purchasedRow()!).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[0]).toBe(FIXTURE_PURCHASE.text);
    expect(cells[1]).toBe(statusValues[1]); // Active
    expect(cells[2]).toBe(PURCHASED);
    cleanup();

    await mount(undefined, { purchase: { [A.id]: { ...FIXTURE_PURCHASE, on: false } } });
    expect(within(purchasedRow()!).getAllByRole("cell")[1].textContent).toBe(statusValues[3]); // Canceled
  });

  it("follows the Nudge and Delayed welcome rows, in the catalogue's order, and the Trigger filter picks it out", async () => {
    await mount(undefined, {
      nudge: { [A.id]: true }, lines: { [A.id]: "Hey you, fixture line" },
      welcomeRules: { [A.id]: { on: true } }, purchase: { [A.id]: FIXTURE_PURCHASE },
    });
    expect(rows().map(triggerOf)).toEqual([triggerLabels[0], WELCOME, PURCHASED]);
    await applyFilters({ trigger: PURCHASED });
    expect(rows().map(triggerOf)).toEqual([PURCHASED]);
  });

  it('"Purchases", then Next, opens the editor on the chip\'s Creator, off by default; Save writes its config', async () => {
    await mount();
    await pickCreator(B.nickname);
    await waitFor(() => expect(client.isFetching()).toBe(0));
    await openPopUp();
    const card = cardNamed(PURCHASE_CARD.title);
    expect(card).not.toBeDisabled();
    expect(card).not.toHaveAttribute("title", "not wired");
    await act(async () => { fireEvent.click(card); });
    await act(async () => { fireEvent.click(nextButton()); });

    expect(screen.queryByRole("dialog", { name: POP_UP })).toBeNull();
    const dialog = screen.getByRole("dialog", { name: PURCHASED });
    expect(within(dialog).getByText(EXTRA_LABEL).getAttribute("title")).toBe(EXTRA_LABEL);
    expect(await within(dialog).findByRole("heading", { name: "Message on purchase" })).toBeTruthy();
    expect(callsTo(relayGet, `${PF_CONFIG}?account_id=${B.id}`).length).toBeGreaterThan(0);
    // Off by default, the message starting as Infloww's first default script; on with no text cannot be saved.
    const on = within(dialog).getByRole("checkbox", { name: "On" });
    expect(on).not.toBeChecked();
    expect((within(dialog).getByLabelText("Message") as HTMLTextAreaElement).value)
      .toBe("Thanks for your purchase, {name}! You're in for a treat!");
    expect(within(dialog).queryByText(/Purchases more than a day old/)).toBeNull();
    await act(async () => { fireEvent.click(on); });
    expect(within(dialog).getByRole("button", { name: "Save" })).not.toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "  " } });
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(dialog).getByText("Write a message to turn this on.")).toBeTruthy();

    expectedWrites.push(`PUT ${PF_CONFIG}`);
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "  Thank you, fixture fan  " } });
    // Infloww's start for Purchased: after a random 1～3 minute delay, every time.
    expect((within(dialog).getByLabelText("Send message to fans") as HTMLSelectElement).value).toBe("on");
    expect(within(dialog).getByRole("radio", { name: "Send every time the fan matches the trigger" })).toBeChecked();
    fireEvent.change(within(dialog).getByLabelText("Delay from (minutes)"), { target: { value: "15" } });
    fireEvent.change(within(dialog).getByLabelText("Delay to (minutes)"), { target: { value: "15" } });
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(relayPut.mock.calls.filter(([p]) => p === PF_CONFIG).map(([, body]) => body)).toEqual([
      { account_id: B.id, config: {
        enabled: true, text: "Thank you, fixture fan", ...EXTRAS_DEFAULTS, frequency: "every",
        delay_range: [15, 16], // equal ends widen by a minute, as Infloww's clamp does
      } },
    ]));
    expect(await within(dialog).findByText("Saved.")).toBeTruthy();
  });

  it("opening the row opens the same editor with the rule's saved config", async () => {
    await mount(undefined, { purchase: { [A.id]: FIXTURE_PURCHASE } });
    await act(async () => { fireEvent.click(within(purchasedRow()!).getByRole("button", { name: FIXTURE_PURCHASE.text })); });
    const dialog = screen.getByRole("dialog", { name: PURCHASED });
    expect(await within(dialog).findByRole("heading", { name: "Message on purchase" })).toBeTruthy();
    expect(within(dialog).getByRole("checkbox", { name: "On" })).toBeChecked();
    expect((within(dialog).getByLabelText("Message") as HTMLTextAreaElement).value).toBe(FIXTURE_PURCHASE.text);
  });
});

// ── The lifecycle Triggers, the Actions cell and the Date created filter ──

const LM_CONFIG = "/admin/lifecycle-message-config";
const SWITCH = "/admin/automation-rules/switch";

/** A row's Cancel, confirmed in the bundle's "Cancel message" dialog. */
async function cancelRow(trigger: string) {
  await act(async () => {
    fireEvent.click(within(actionsCell(rowOfTrigger(trigger)!)).getByRole("button", { name: `Cancel ${trigger}` }));
  });
  await act(async () => {
    fireEvent.click(within(screen.getByRole("dialog", { name: "Cancel message" })).getByRole("button", { name: "Proceed with cancellation" }));
  });
}
const LIFECYCLE_ROWS: [string, string][] = [
  [triggerLabels[3], "expiry_message"], [triggerLabels[4], "expired_message"],
  [triggerLabels[5], "resubscribe_message"], [triggerLabels[6], "birthday_message"],
];
const rowOfTrigger = (t: string) => rows().find((r) => triggerOf(r) === t);
const actionsCell = (r: HTMLElement) => {
  const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
  return within(r).getAllByRole("cell")[headers.indexOf(labelOf(52))];
};

describe("the lifecycle Triggers, the Actions cell and Date created", () => {
  it("each lifecycle rule is a row after Purchased, in the catalogue's order, with its text and Status", async () => {
    await mount(undefined, {
      purchase: { [A.id]: FIXTURE_PURCHASE },
      lifecycle: { [A.id]: {
        birthday_message: { on: false, text: "Happy birthday, fixture" },
        expiry_message: { on: true, text: "Your sub ends soon, fixture", hours: 12 },
        expired_message: { on: true, text: "Come back, fixture", hours: 48 },
        resubscribe_message: { on: true, text: "Welcome back, fixture" },
      } },
    });
    expect(rows().map(triggerOf)).toEqual([PURCHASED, ...LIFECYCLE_ROWS.map(([t]) => t)]);
    const cells = within(rowOfTrigger(triggerLabels[6])!).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[0]).toBe("Happy birthday, fixture");
    expect(cells[1]).toBe(statusValues[3]); // Canceled
    expect(within(rowOfTrigger(triggerLabels[3])!).getAllByRole("cell")[1].textContent).toBe(statusValues[1]);
    await applyFilters({ trigger: triggerLabels[4] });
    expect(rows().map(triggerOf)).toEqual([triggerLabels[4]]);
  });

  it("the Expired row opens its editor with the rule's text and hours; Save writes kind, text and hours", async () => {
    await mount(undefined, {
      lifecycle: { [A.id]: { expired_message: { on: true, text: "Come back, fixture", hours: 48 } } },
    });
    await act(async () => { fireEvent.click(within(rowOfTrigger(triggerLabels[4])!).getByRole("button", { name: "Come back, fixture" })); });
    const dialog = screen.getByRole("dialog", { name: triggerLabels[4] });
    expect(within(dialog).getByText(EXTRA_LABEL)).toBeTruthy();
    expect(await within(dialog).findByRole("heading", { name: "Expired" })).toBeTruthy();
    expect(callsTo(relayGet, `${LM_CONFIG}?account_id=${A.id}&kind=expired_message`).length).toBeGreaterThan(0);
    expect(within(dialog).getByRole("checkbox", { name: "On" })).toBeChecked();
    const hours = within(dialog).getByLabelText("Fan’s subscription expired") as HTMLInputElement;
    expect(hours.value).toBe("48");
    // Infloww's bounds: Expired is 12..120 hours.
    fireEvent.change(hours, { target: { value: "6" } });
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(dialog).getByText("Hours must be a whole number from 12 to 120.")).toBeTruthy();

    expectedWrites.push(`PUT ${LM_CONFIG}`);
    fireEvent.change(hours, { target: { value: "72" } });
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "  Miss you, {name}  " } });
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(relayPut.mock.calls.filter(([p]) => p === LM_CONFIG).map(([, body]) => body)).toEqual([
      { account_id: A.id, kind: "expired_message", config: {
        enabled: true, hours: 72, messages: [{ variants: ["Miss you, {name}"], follow_ups: [], discount: null }],
        ...EXTRAS_DEFAULTS, frequency: "every",
      } },
    ]));
    expect(await within(dialog).findByText("Saved.")).toBeTruthy();
  });

  it('"Birthday greetings", then Next, opens the Birthday editor, off by default, with no hours and Infloww\'s script as its text', async () => {
    await mount();
    await openPopUp();
    await act(async () => { fireEvent.click(cardNamed(cardOf(122)!.title)); });
    await act(async () => { fireEvent.click(nextButton()); });
    const dialog = screen.getByRole("dialog", { name: triggerLabels[6] });
    // The dialog's title and, once loaded, the editor's own heading share the name.
    expect((await within(dialog).findAllByRole("heading", { name: "Birthday" })).length).toBeGreaterThan(0);
    await waitFor(() => expect(within(dialog).getByRole("checkbox", { name: "On" })).toBeTruthy());
    expect(within(dialog).getByRole("checkbox", { name: "On" })).not.toBeChecked();
    expect(within(dialog).queryByRole("spinbutton")).toBeNull();
    const text = within(dialog).getByLabelText("Message") as HTMLTextAreaElement;
    expect(text.value).toBe("It's your special day, {name}! Have a fantastic birthday!");
    await act(async () => { fireEvent.click(within(dialog).getByRole("checkbox", { name: "On" })); });
    expect(within(dialog).getByRole("button", { name: "Save" })).not.toBeDisabled();
    fireEvent.change(text, { target: { value: "" } });
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("an Active row's Cancel switches its kind off without opening the row; a Canceled row has none; Duplicate is Not wired", async () => {
    await mount(undefined, {
      nudge: { [A.id]: false },
      lifecycle: { [A.id]: { resubscribe_message: { on: true, text: "Welcome back, fixture" } } },
    });
    expect(within(actionsCell(rowOfTrigger(triggerLabels[0])!)).queryByRole("button", { name: /^Cancel/ })).toBeNull();
    for (const r of rows()) {
      const dup = within(actionsCell(r)).getByRole("button", { name: "Duplicate" });
      expect(dup).toBeDisabled();
      expect(dup).toHaveAttribute("title", "not wired");
    }
    expectedWrites.push(`POST ${SWITCH}`);
    relayPost.mockResolvedValue({ action: "parked" });
    await cancelRow(triggerLabels[5]);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      SWITCH, { account_id: A.id, kind: "resubscribe_message", enable: false }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Cancel asks first in Infloww's dialog; Not now closes it and writes nothing", async () => {
    await mount(undefined, { lifecycle: { [A.id]: { resubscribe_message: { on: true, text: "Welcome back, fixture" } } } });
    const calls = relayCalls();
    await act(async () => {
      fireEvent.click(within(actionsCell(rowOfTrigger(triggerLabels[5])!)).getByRole("button", { name: `Cancel ${triggerLabels[5]}` }));
    });
    const dialog = screen.getByRole("dialog", { name: "Cancel message" });
    expect(within(dialog).getByText("The selected smart message will no longer be sent.")).toBeTruthy();
    // The shared Modal is Infloww's antd modal now (page-parity ticket 17), with a corner Close.
    expect(within(dialog).getAllByRole("button").filter((b) => b.getAttribute("aria-label") !== "Close").map((b) => b.textContent))
      .toEqual(["Not now", "Proceed with cancellation"]);
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Not now" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(relayPost).not.toHaveBeenCalled();
    expect(relayCalls()).toEqual(calls);
  });

  it("after a row's Cancel, its editor reopens on the rule as it is now, not a stale On", async () => {
    const lifecycle = { [A.id]: { resubscribe_message: { on: true, text: "Welcome back, fixture" } } };
    await mount(undefined, { lifecycle });
    // Keep an unmounted editor's read cached, as the app's default does.
    client.setQueryDefaults(["lifecycle-message-config"], { gcTime: 5 * 60_000 });
    const open = async () => {
      await act(async () => { fireEvent.click(within(rowOfTrigger(triggerLabels[5])!).getByRole("button", { name: "Welcome back, fixture" })); });
      const dialog = screen.getByRole("dialog", { name: triggerLabels[5] });
      await within(dialog).findByRole("heading", { name: "Resubscribe" });
      return dialog;
    };
    let dialog = await open();
    expect(within(dialog).getByRole("checkbox", { name: "On" })).toBeChecked();
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Close" })); });

    expectedWrites.push(`POST ${SWITCH}`);
    relayPost.mockImplementation(() => { lifecycle[A.id].resubscribe_message.on = false; return Promise.resolve({ action: "parked" }); });
    await cancelRow(triggerLabels[5]);
    await waitFor(() => expect(client.isFetching()).toBe(0));
    dialog = await open();
    await waitFor(() => expect(within(screen.getByRole("dialog", { name: triggerLabels[5] })).getByRole("checkbox", { name: "On" })).not.toBeChecked());
  });

  it("on a free page, Expiring soon, Expired and Resubscribe are refused with Infloww's message, in the pop-up and the editor", async () => {
    const refusal = `${A.id} page is a free subscription profile and is unable to create this message`;
    await mount(undefined, {
      subscribePrice: { [A.id]: 0 },
      lifecycle: { [A.id]: { expired_message: { on: false, text: "Come back, fixture", hours: 48 } } },
    });
    await openPopUp();
    await waitFor(() => expect(cardNamed(cardOf(119)!.title)).toBeDisabled());
    for (const n of [119, 120, 121]) {
      const card = cardNamed(cardOf(n)!.title);
      expect(card).toBeDisabled();
      expect(card).toHaveAttribute("title", refusal);
      expect(within(card).getByText(refusal)).toBeTruthy();
    }
    expect(cardNamed(cardOf(122)!.title)).not.toBeDisabled(); // Birthday
    await act(async () => { fireEvent.click(within(popUp()).getByRole("button", { name: labelOf(111) })); });

    await act(async () => { fireEvent.click(within(rowOfTrigger(triggerLabels[4])!).getByRole("button", { name: "Come back, fixture" })); });
    const dialog = screen.getByRole("dialog", { name: triggerLabels[4] });
    await within(dialog).findByRole("heading", { name: "Expired" });
    expect(within(dialog).getByRole("checkbox", { name: "On" })).toBeDisabled();
    expect(within(dialog).getByText(refusal)).toBeTruthy();
  });

  it("on a paid page the three cards stay wired", async () => {
    await mount(undefined, { subscribePrice: { [A.id]: 9.99 } });
    await openPopUp();
    for (const n of [119, 120, 121]) expect(cardNamed(cardOf(n)!.title)).not.toBeDisabled();
  });

  it("Date created keeps the rows created inside the picked days, applied by Search; Reset clears it", async () => {
    await mount(undefined, {
      nudge: { [A.id]: true }, // created 2026-01-05
      lifecycle: { [A.id]: {
        birthday_message: { on: true, text: "Happy birthday, fixture", createdAt: "2026-03-10T12:00:00Z" },
      } },
      reportTz: "UTC",
    });
    expect(rows()).toHaveLength(2);
    const field = filterBar().dateCreated.closest("[role=group]") as HTMLElement;
    const [from, to] = Array.from(field.querySelectorAll("input"));
    await act(async () => { fireEvent.change(from, { target: { value: "2026-03-01" } }); });
    expect(rows()).toHaveLength(2); // not until Search
    await act(async () => { fireEvent.click(filterBar().apply); });
    expect(rows().map(triggerOf)).toEqual([triggerLabels[6]]);
    await act(async () => { fireEvent.change(to, { target: { value: "2026-03-09" } }); });
    await act(async () => { fireEvent.click(filterBar().apply); });
    expect(within(panel()).getByText(NO_DATA)).toBeTruthy();
    await act(async () => { fireEvent.click(filterBar().reset); });
    expect(rows()).toHaveLength(2);
  });
});

// ── Ticket 54: the header row, the filter bar and the table against the bundle shots ──

describe("the header row and the Automated filter bar and table read like the bundle (ticket 54)", () => {
  it("the header row holds the title, then Learn and New Message, all above the tab strip; the creator column sits under it, left of the Automated tab", async () => {
    await mount();
    const title = screen.getByRole("heading", { level: 1 });
    const learn = screen.getByRole("button", { name: labelOf(11) });
    const create = screen.getByRole("button", { name: labelOf(15) });
    // One row: title, Learn, New Message, in that order (#3, #11, #15, #18).
    const header = screen.getByRole("banner");
    expect(header.contains(title)).toBe(true);
    expect(title.textContent).toBe(SM.title.label);
    for (const el of [learn, create]) expect(header.contains(el)).toBe(true);
    expect(before(title, learn) && before(learn, create)).toBe(true);
    // The header holds no creator select: the Creator is picked on the creator column.
    expect(within(header).queryByRole("combobox", { name: "Creator" })).toBeNull();
    expect(within(header).queryByTestId("of-creator-column")).toBeNull();
    // The tab strip follows the header row, full width, and holds only the two tabs.
    expect(before(create, parentTabs())).toBe(true);
    expect(header.contains(parentTabs())).toBe(false);
    expect(parentTabs().contains(column())).toBe(false);
    // The column sits under the tab strip, in the Automated tab, left of its body (the list).
    expect(before(parentTabs(), column())).toBe(true);
    expect(panel().contains(column())).toBe(true);
    expect(column().nextElementSibling!.contains(rows()[0])).toBe(true);
  });

  it("Learn carries the book icon and stays disabled; New Message carries the plus; the picked tab is M1", async () => {
    await mount();
    const learn = screen.getByRole("button", { name: labelOf(11) });
    expect(learn.querySelector("svg.lucide-book-open")).toBeTruthy();
    expect(learn).toBeDisabled();
    expect(learn).toHaveAttribute("title", "not wired");
    expect(learn).toHaveClass("text-accent");
    const create = screen.getByRole("button", { name: labelOf(15) });
    expect(create.querySelector("svg.lucide-plus")).toBeTruthy();
    const [automated, mass] = within(parentTabs()).getAllByRole("tab");
    expect(automated).toHaveAttribute("aria-selected", "true");
    expect(automated).toHaveClass("text-accent");
    expect(automated).toHaveAttribute("aria-controls", "sm-panel-automated");
    expect(mass).toHaveAttribute("aria-selected", "false");
    expect(mass).not.toHaveClass("text-accent");
    await act(async () => { fireEvent.click(mass); });
    expect(mass).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: TAB_MASS }).id).toBe(mass.getAttribute("aria-controls"));
  });

  it("Start date and Date created are ranges, Start date to End date; Start date's ends are Not wired, Date created's are day pickers", async () => {
    await mount();
    const calls = relayCalls();
    for (const n of [31, 32]) {
      const field = filterBar()[n === 31 ? "startDate" : "dateCreated"].closest("[role=group]") as HTMLElement | null;
      expect(field, labelOf(n)).toBeTruthy();
      const ends = Array.from(field!.querySelectorAll("input"));
      // antd's RangePicker placeholders (index.9f50f370.js @1623380).
      expect(ends.map((e) => e.getAttribute("placeholder"))).toEqual(["Start date", "End date"]);
      for (const e of ends) {
        if (n === 31) {
          expect(e).toBeDisabled();
          expect(e).toHaveAttribute("title", "not wired");
        } else {
          expect(e).not.toBeDisabled();
          // An empty end shows the placeholder until it has focus, then is a day picker.
          await act(async () => { fireEvent.focus(e); });
          expect(e.type).toBe("date");
          await act(async () => { fireEvent.blur(e); });
        }
        await act(async () => { fireEvent.click(e); });
      }
    }
    expect(relayCalls()).toEqual(calls);
  });

  it('every filter select shows the bundle\'s placeholder "All" (#27, #29, #30, #33)', async () => {
    await mount();
    const { status, trigger, sentTo, createdBy } = filterBar();
    for (const s of [status, trigger, sentTo, createdBy]) {
      expect(s.textContent).toBe("All");
      if ((s as HTMLButtonElement).disabled) continue;
      expect(optionsOf(s)[0].textContent).toBe("All");
    }
  });

  it("Date created renders in the Agency's report time zone (#51)", async () => {
    // The fixture rule was created 2026-01-05 12:00 UTC: Jan 6 at UTC+14, Jan 5 at UTC-11.
    for (const [reportTz, want] of [["Pacific/Kiritimati", "Jan 6, 2026"], ["Pacific/Pago_Pago", "Jan 5, 2026"]]) {
      await mount(undefined, { nudge: { [A.id]: true }, reportTz });
      const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
      await waitFor(() => {
        const cell = within(rows()[0]).getAllByRole("cell")[headers.indexOf(labelOf(51))];
        expect(cell.textContent, reportTz).toBe(want);
      });
      cleanup();
    }
  });

  it("loading draws placeholder rows (no text); the read-failure line carries the Inflowwww extra label; No Data does not", async () => {
    // Loading: the rules read never answers.
    window.history.replaceState(null, "", "/growth/smart-messages");
    stubReads({});
    const answer = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string, ctx?: unknown) =>
      String(path).startsWith("/admin/automation-rules") ? new Promise(() => {}) : answer(path, ctx));
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
    await waitFor(() => expect(panel().querySelectorAll("tbody [data-loading]").length).toBeGreaterThan(0));
    expect(within(panel()).queryByText(/Loading/)).toBeNull();
    expect(within(panel()).queryByText(NO_DATA)).toBeNull();
    cleanup();

    await mount(undefined, { failRules: true });
    expect(within(panel()).getByText("Couldn't load this Creator's automations.")).toHaveAttribute("title", EXTRA_LABEL);
    cleanup();

    await mount();
    expect(within(panel()).getByText(NO_DATA)).not.toHaveAttribute("title");
  });

  it("with no Creator the creator column lists none and no creator select shows", async () => {
    // No Creator, so no rules read: the mount waits on the Creators read alone.
    window.history.replaceState(null, "", "/growth/smart-messages");
    stubReads({ noCreators: true });
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SmartMessagesPage /></QueryClientProvider>);
    await waitFor(() => {
      expect(relayGet.mock.calls.some(([p]) => String(p).startsWith("/admin/accounts"))).toBe(true);
      expect(client.isFetching()).toBe(0);
    });
    expect(within(column()).queryAllByTestId("of-creator-row")).toEqual([]);
    // The narrow-screen fallback select shows only once there are Creators to pick.
    expect(screen.queryByRole("combobox", { name: "Creator" })).toBeNull();
  });
});

// ── The Smart Message settings: media and price, Frequency & scheduling, Auto-unsend ──

const cellOf = (r: HTMLElement, label: string) => {
  const headers = within(panel()).getAllByRole("columnheader").map((h) => h.textContent);
  return within(r).getAllByRole("cell")[headers.indexOf(label)];
};

describe("the Smart Message settings on the Trigger editors and the list", () => {
  it("the Purchased editor saves media at a price, Frequency, an Effective date in the report time zone and Auto-unsend", async () => {
    await mount(undefined, { purchase: { [A.id]: { ...FIXTURE_PURCHASE, media_ids: [7, 8] } }, reportTz: "Europe/Berlin" });
    await act(async () => { fireEvent.click(within(purchasedRow()!).getByRole("button", { name: FIXTURE_PURCHASE.text })); });
    const dialog = screen.getByRole("dialog", { name: PURCHASED });
    expect(await within(dialog).findByRole("heading", { name: "Message on purchase" })).toBeTruthy();
    const save = within(dialog).getByRole("button", { name: "Save" });
    // Infloww's floor on a price: under $3 cannot be saved.
    const price = within(dialog).getByLabelText("Message price:$");
    fireEvent.change(price, { target: { value: "2" } });
    expect(save).toBeDisabled();
    expect(within(dialog).getAllByText("Minimum $3 USD")).toHaveLength(2);
    // ...nor over OnlyFans' $200 PPV ceiling.
    fireEvent.change(price, { target: { value: "200.01" } });
    expect(save).toBeDisabled();
    expect(within(dialog).getByText("Maximum $200 USD")).toBeTruthy();
    fireEvent.change(price, { target: { value: "12.5" } });
    expect(save).not.toBeDisabled();

    fireEvent.click(within(dialog).getByRole("radio", { name: "Send only once when the fan matches the trigger" }));
    const effective = within(dialog).getByRole("radiogroup", { name: "Effective" });
    fireEvent.click(within(effective).getByRole("radio", { name: "Scheduled date" }));
    expect(save).toBeDisabled(); // a scheduled date with no date
    fireEvent.change(within(dialog).getByLabelText("Effective date"), { target: { value: "2026-11-01T09:30" } });
    expect(within(dialog).getByText("Times in Europe/Berlin.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Unsend messages" }));
    // At most 23 hours: inside OnlyFans' ~24h per-chat delete window.
    fireEvent.change(within(dialog).getByLabelText("Unsend after (hours)"), { target: { value: "24" } });
    expect(within(dialog).getByText("Unsend after 1 minute to 23 hours")).toBeTruthy();
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Unsend after (hours)"), { target: { value: "1" } });
    fireEvent.change(within(dialog).getByLabelText("Unsend after (minutes)"), { target: { value: "30" } });
    // The house differs here: a paid message is never unsent.
    expect(within(dialog).getByText("A paid message is never unsent: only a free one is.")).toBeTruthy();

    expectedWrites.push(`PUT ${PF_CONFIG}`);
    await act(async () => { fireEvent.click(save); });
    await waitFor(() => expect(relayPut.mock.calls.filter(([p]) => p === PF_CONFIG).map(([, body]) => body)).toEqual([
      { account_id: A.id, config: {
        enabled: true, text: FIXTURE_PURCHASE.text, media_ids: [7, 8], price_cents: 1250, frequency: "once",
        // The delay row was left as it opened, so it is not sent: the Relay
        // keeps what it stored (an old fixed delay stays exact).
        starts_at: "2026-11-01T08:30:00.000Z", ends_at: null, unsend_minutes: 90,
      } },
    ]));
  });

  it("a lifecycle editor refuses a price with no media and an Expiry before its Effective date", async () => {
    await mount(undefined, { lifecycle: { [A.id]: { birthday_message: { on: true, text: "Happy birthday, fixture" } } } });
    await act(async () => { fireEvent.click(within(rowOfTrigger(triggerLabels[6])!).getByRole("button", { name: "Happy birthday, fixture" })); });
    const dialog = screen.getByRole("dialog", { name: triggerLabels[6] });
    // The dialog's title and, once loaded, the editor's own heading share the name.
    expect((await within(dialog).findAllByRole("heading", { name: "Birthday" })).length).toBeGreaterThan(0);
    await waitFor(() => expect(within(dialog).getByRole("checkbox", { name: "On" })).toBeTruthy());
    const save = within(dialog).getByRole("button", { name: "Save" });
    // No delay row on a lifecycle Trigger.
    expect(within(dialog).queryByLabelText("Send message to fans")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Message price:$"), { target: { value: "5" } });
    expect(within(dialog).getByText("Add media to set a price")).toBeTruthy();
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Message price:$"), { target: { value: "" } });

    fireEvent.click(within(within(dialog).getByRole("radiogroup", { name: "Effective" })).getByRole("radio", { name: "Scheduled date" }));
    fireEvent.change(within(dialog).getByLabelText("Effective date"), { target: { value: "2026-11-02T10:00" } });
    fireEvent.click(within(within(dialog).getByRole("radiogroup", { name: "Expiry" })).getByRole("radio", { name: "Scheduled date" }));
    fireEvent.change(within(dialog).getByLabelText("Expiry date"), { target: { value: "2026-11-01T10:00" } });
    expect(within(dialog).getByText("The Expiry must come after the Effective date")).toBeTruthy();
    expect(save).toBeDisabled();
    fireEvent.click(within(within(dialog).getByRole("radiogroup", { name: "Expiry" })).getByRole("radio", { name: "Never" }));
    expect(save).not.toBeDisabled();
  });

  it("the list fills Attachment(s), Price, Start date and End date from a rule's settings, and its Status from its dates", async () => {
    await mount(undefined, {
      purchase: { [A.id]: { ...FIXTURE_PURCHASE, media_ids: [1, 2], price_cents: 1500, starts_at: "2099-01-01T12:00:00+00:00" } },
      lifecycle: { [A.id]: {
        birthday_message: { on: true, text: "Happy birthday, fixture", ends_at: "2020-01-02T12:00:00+00:00" },
        resubscribe_message: { on: true, text: "Welcome back, fixture" },
      } },
    });
    const purchased = purchasedRow()!;
    expect(cellOf(purchased, "Attachment(s)").textContent).toBe("2 media");
    expect(cellOf(purchased, "Price").textContent).toBe("$15");
    expect(cellOf(purchased, "Start date").textContent).toBe("Jan 1, 2099");
    expect(cellOf(purchased, "End date").textContent).toBe("--");
    expect(cellOf(purchased, "Status").textContent).toBe("Scheduled");
    const birthday = rowOfTrigger(triggerLabels[6])!;
    expect(cellOf(birthday, "Status").textContent).toBe("Completed");
    expect(cellOf(birthday, "End date").textContent).toBe("Jan 2, 2020");
    const resub = rowOfTrigger(triggerLabels[5])!;
    expect(cellOf(resub, "Status").textContent).toBe("Active");
    expect(["Attachment(s)", "Price", "Start date"].map((c) => cellOf(resub, c).textContent)).toEqual(["--", "--", "--"]);
    await applyFilters({ status: "Scheduled" });
    expect(rows().map(triggerOf)).toEqual([PURCHASED]);
  });
});
