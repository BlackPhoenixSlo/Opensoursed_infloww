/**
 * CreatorTabs — seam 1 of docs/spec/phase-01-window-chrome-tabs.md (Testing
 * Decisions): the Creator tabs strip renders through the house provider
 * wrapper with the real `ScopeProvider`, and the relay client mocked by path
 * (the Composer suites' harness). The realtime bus the scope pushes to is a
 * no-op. Assertions are on roles, names, `aria-selected`, document order and
 * the relay requests, never on hook state. Later Phase 1 tickets (reorder,
 * storage) add their cases here.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
const bus = vi.hoisted(() => ({ connected: true }));
vi.mock("@/lib/events", async (orig) => ({
  ...(await orig<typeof import("@/lib/events")>()),
  eventBus: {
    setScope: vi.fn(), on: () => () => {},
    onStateChange: (fn: (up: boolean) => void) => { fn(bus.connected); return () => {}; },
  },
}));
// The signed-in principal: an owner, unless a case signs in a chatter only;
// and the Employee at the keyboard, which a case may switch or leave pending
// (reset before each case).
type FixtureEmployee = { id: number; display_name: string; color: null; is_active: true };
const session = vi.hoisted(() => ({
  user: {
    user: { user_id: "u-owner", username: "owner" } as { user_id: string; username: string } | null,
    loading: false,
    logout: () => {},
  },
  chatter: {
    chatter: null as { chatter_id: string; username: string } | null,
    loading: false,
    logout: () => {},
  },
  employee: {
    current: null as FixtureEmployee | null,
    hydrated: true,
    pickedId: null as number | null,
  },
}));
vi.mock("@/contexts/UserContext", async (orig) => ({
  ...(await orig<typeof import("@/contexts/UserContext")>()),
  useUser: () => session.user, useOptionalUser: () => session.user,
}));
vi.mock("@/contexts/ChatterContext", async (orig) => ({
  ...(await orig<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => session.chatter, useOptionalChatter: () => session.chatter,
}));
vi.mock("@/contexts/EmployeeContext", async (orig) => ({
  ...(await orig<typeof import("@/contexts/EmployeeContext")>()),
  useEmployee: () => ({ ...session.employee, roster: [], pick: () => {}, clear: () => {} }),
}));

import { ScopeProvider, useScope } from "@/contexts/ScopeContext";
import { resetRosterCountsModuleState, type RosterCount } from "@/hooks/useRosterCounts";
import { renderWithProviders } from "@/test-utils";
import { expectDomOrder, relayGet, resetComposerHarness, routeRelay } from "./composerTestHarness";
import { CreatorTabs } from "./CreatorTabs";
import { useCreatorTabs, useShownCreatorTabs } from "./useCreatorTabs";

/* ── fixtures ───────────────────────────────────────────────────────────── */

// The relay's account order is Zed, Amy, Max. It is neither alphabetical nor
// most-recently-used first (Amy was used last), so a strip that reshuffles
// fails the order. Nia has no session, so she gets no tab.
const ZED = "100000011";
const AMY = "100000012";
const MAX = "100000013";
const NIA = "100000014";
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const account = (id: string, name: string, usedMinAgo: number, hasSession = true) => ({
  id, nickname: name, name, platform: "onlyfans", color: "#4a90d9",
  has_session: hasSession, session_dead_at: null as string | null, created_at: ago(43_200), last_used_at: ago(usedMinAgo),
});
const ACCOUNTS = [
  account(ZED, "Zed Creator", 90),
  account(AMY, "Amy Creator", 1),
  account(NIA, "Nia Creator", 2, false),
  account(MAX, "Max Creator", 30),
];
// Unread conversations per Creator: distinct, and Max has none (no badge). No Owe reply (no Amber circle) unless a
// case sets one.
const COUNTS: Record<string, RosterCount> = {
  [ZED]: { unread: 3, owe_reply: 0 },
  [AMY]: { unread: 12, owe_reply: 0 },
  [MAX]: { unread: 0, owe_reply: 0 },
};

/** The roster counts' read waits on this when a case sets it. */
let countsGate: Promise<void> | null = null;
/** What the relay's accounts read answers; a case may change the roster. */
let relayAccounts: Array<ReturnType<typeof account> & { freshness?: object }> = ACCOUNTS;

// Two Employees; the first is at the keyboard unless a case says otherwise.
const EMP_A: FixtureEmployee = { id: 300000001, display_name: "Fixture Employee A", color: null, is_active: true };
const EMP_B: FixtureEmployee = { id: 300000002, display_name: "Fixture Employee B", color: null, is_active: true };
/** Put `employee` at the keyboard, as the top bar's switcher does. */
function atKeyboard(employee: FixtureEmployee) {
  session.employee = { current: employee, hydrated: true, pickedId: employee.id };
}
/** The spec's Creator tabs key (Contracts) for an Employee key. */
const tabsKey = (employeeKey: string | number) => `chatterly:creator-tabs:v1:${employeeKey}`;

beforeEach(() => {
  window.localStorage.clear();
  session.user.user = { user_id: "u-owner", username: "owner" };
  session.user.loading = false;
  session.chatter.chatter = null;
  session.chatter.loading = false;
  atKeyboard(EMP_A);
  bus.connected = true;
  resetComposerHarness();
  // In-flight roster busts are module state: no case inherits another's.
  resetRosterCountsModuleState();
  countsGate = null;
  routeRelay("/admin/accounts/roster-counts", () => (countsGate ?? Promise.resolve()).then(() => ({ counts: COUNTS })));
  relayAccounts = ACCOUNTS;
  routeRelay("/admin/accounts", () => ({ accounts: relayAccounts, active_account_id: ZED }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
});

/** This window's scope as the real provider holds it. */
function ScopeProbe() {
  const { eventScope } = useScope();
  return <output aria-label="Scope">{eventScope}</output>;
}

function renderStrip() {
  return renderWithProviders(
    <ScopeProvider>
      <CreatorTabs />
      <ScopeProbe />
    </ScopeProvider>,
  );
}

const strip = () => within(screen.getByRole("tablist", { name: "Creator tabs" }));
const scopeText = () => screen.getByRole("status", { name: "Scope" }).textContent;
/** The relay's Fan List requests for `accountId` (the client's second
 *  argument, its context, names the Creator). */
const fanListReads = (accountId: string) =>
  relayGet.mock.calls.filter(([path, ctx]) =>
    path.startsWith("/api/of/v2/chats?") && ctx?.accountId === accountId);

describe("CreatorTabs", () => {
  it("shows one tab per session-bearing Creator, with its name and unread badge, in the relay's order", async () => {
    renderStrip();
    // The badge reads once the roster counts land.
    const zed = await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    const amy = strip().getByRole("tab", { name: "Amy Creator 9+ unread" });
    // No unread conversations, no badge.
    const max = strip().getByRole("tab", { name: "Max Creator" });

    expect(strip().getAllByRole("tab")).toEqual([zed, amy, max]);
    expectDomOrder([zed, amy, max]);
    expect(strip().queryByRole("tab", { name: /Nia Creator/ })).toBeNull();
    // The avatar falls back to the Creator's first two letters, as the Clone's.
    expect(within(zed).getByText("ZE")).toBeInTheDocument();
    expect(within(zed).getByText("3")).toBeInTheDocument();
  });

  it("with the Knob off the route's exact count takes the Red circle rule: 25 reads \"9+\"", async () => {
    const amyCount = COUNTS[AMY];
    COUNTS[AMY] = { unread: 25, owe_reply: 0 };
    try {
      renderStrip();
      const amy = await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
      expect(within(amy).getByText("9+")).toBeInTheDocument();
      expect(amy).toHaveAttribute("title", "Amy Creator — 9+ unread — 0 awaiting reply");
      expect(strip().getByRole("tab", { name: "Zed Creator 3 unread" })).toBeInTheDocument();
    } finally {
      COUNTS[AMY] = amyCount;
    }
  });

  it("clicking a tab sets the active Creator and marks it selected; Enter and Space do too", async () => {
    renderStrip();
    const zed = await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    const amy = strip().getByRole("tab", { name: "Amy Creator 9+ unread" });
    const max = strip().getByRole("tab", { name: "Max Creator" });
    // No saved scope: All Models, so no tab is selected.
    expect(scopeText()).toBe("all");
    for (const t of [zed, amy, max]) expect(t).toHaveAttribute("aria-selected", "false");

    await userEvent.click(amy);
    expect(scopeText()).toBe(`model:${AMY}`);
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${AMY}`);
    expect(amy).toHaveAttribute("aria-selected", "true");
    expect(zed).toHaveAttribute("aria-selected", "false");

    max.focus();
    await userEvent.keyboard("{Enter}");
    expect(scopeText()).toBe(`model:${MAX}`);
    expect(max).toHaveAttribute("aria-selected", "true");
    expect(amy).toHaveAttribute("aria-selected", "false");

    zed.focus();
    await userEvent.keyboard(" ");
    expect(scopeText()).toBe(`model:${ZED}`);
    expect(zed).toHaveAttribute("aria-selected", "true");
    expect(max).toHaveAttribute("aria-selected", "false");
  });

  it("picking a tab prefetches that Creator's Fan List and refreshes its unread count", async () => {
    renderStrip();
    const amy = await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
    expect(fanListReads(AMY)).toHaveLength(0);

    await userEvent.click(amy);
    await vi.waitFor(() => expect(fanListReads(AMY)).toHaveLength(1));
    await vi.waitFor(() =>
      expect(relayGet.mock.calls.map(([p]) => p)).toContain(`/admin/accounts/roster-counts?bust=${AMY}`));
  });

  it("hovering a tab for 250ms prefetches that Creator's Fan List; a shorter hover does not", async () => {
    renderStrip();
    const zed = await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    const max = strip().getByRole("tab", { name: "Max Creator" });
    vi.useFakeTimers();

    // 249ms, then the pointer leaves: nothing, even long after.
    fireEvent.mouseEnter(max);
    await act(() => vi.advanceTimersByTimeAsync(249));
    fireEvent.mouseLeave(max);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(fanListReads(MAX)).toHaveLength(0);

    // The full 250ms: the Fan List read goes out, for that Creator only.
    fireEvent.mouseEnter(zed);
    await act(() => vi.advanceTimersByTimeAsync(249));
    expect(fanListReads(ZED)).toHaveLength(0);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(fanListReads(ZED)).toHaveLength(1);
    expect(fanListReads(MAX)).toHaveLength(0);
    // Hovering does not switch the Creator.
    expect(scopeText()).toBe("all");
  });

  /* ── ✕, the empty strip and "+ Add a Creator" (ticket 67) ──────────── */

  const closeButton = (name: string) => screen.getByRole("button", { name: `Close ${name}` });
  const addCreator = () => screen.getByRole("button", { name: "Add a Creator" });
  const picker = () => screen.queryByRole("region", { name: "Creator picker" });
  const ALL_CLOSED = "All creator tabs closed — use “+ Add a Creator”";

  it("✕ on the active tab closes it, activates the first remaining tab and moves focus there", async () => {
    renderStrip();
    const amy = await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
    await userEvent.click(amy);
    expect(scopeText()).toBe(`model:${AMY}`);

    await userEvent.click(closeButton("Amy Creator"));
    // Amy's tab is gone; Zed (the first remaining, not the next one, Max)
    // becomes active and holds focus.
    const zed = strip().getByRole("tab", { name: "Zed Creator 3 unread" });
    const max = strip().getByRole("tab", { name: "Max Creator" });
    expect(strip().getAllByRole("tab")).toEqual([zed, max]);
    expect(zed).toHaveAttribute("aria-selected", "true");
    expect(max).toHaveAttribute("aria-selected", "false");
    expect(scopeText()).toBe(`model:${ZED}`);
    expect(document.activeElement).toBe(zed);
  });

  it("closing every tab shows the all-closed text, focuses \"+ Add a Creator\" and leaves the scope alone", async () => {
    renderStrip();
    const amy = await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
    await userEvent.click(amy);

    // An inactive tab: the active one (not the first remaining, Zed) stays
    // active and takes focus.
    await userEvent.click(closeButton("Max Creator"));
    expect(document.activeElement).toBe(amy);
    expect(scopeText()).toBe(`model:${AMY}`);
    await userEvent.click(closeButton("Zed Creator"));
    expect(screen.queryByText(ALL_CLOSED)).toBeNull();
    // The last one, active: nothing left to activate.
    await userEvent.click(closeButton("Amy Creator"));

    expect(strip().queryAllByRole("tab")).toHaveLength(0);
    expect(screen.getByText(ALL_CLOSED)).toBeInTheDocument();
    expect(strip().queryByText(ALL_CLOSED)).toBeNull();
    expect(screen.queryByText("No creators on this relay")).toBeNull();
    expect(document.activeElement).toBe(addCreator());
    expect(scopeText()).toBe(`model:${AMY}`);
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${AMY}`);
  });

  /** A reply the case settles by hand, so the read stays pending until then. */
  function held<T>() {
    let settle!: (value: T) => void;
    const promise = new Promise<T>((resolve) => { settle = resolve; });
    return { promise, settle };
  }
  const NONE = "No creators on this relay";
  /** Neither empty text, and no tab. */
  const expectNoEmptyText = () => {
    expect(screen.queryByText(NONE)).toBeNull();
    expect(screen.queryByText(ALL_CLOSED)).toBeNull();
    expect(strip().queryAllByRole("tab")).toHaveLength(0);
  };

  it("an owner's strip says nothing while the Creators load, then \"No creators on this relay\" for an empty roster", async () => {
    const reply = held<unknown>();
    resetComposerHarness();
    routeRelay("/admin/accounts", () => reply.promise);
    renderStrip();
    await vi.waitFor(() =>
      expect(relayGet.mock.calls.map(([p]) => p)).toContain("/admin/accounts"));
    expectNoEmptyText();

    await act(async () => reply.settle({ accounts: [], active_account_id: null }));
    expect(await screen.findByText(NONE)).toBeInTheDocument();
    // Beside the strip, not inside it: a tablist owns tabs only.
    expect(strip().queryByText(NONE)).toBeNull();
    expect(strip().queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByText(ALL_CLOSED)).toBeNull();
  });

  it("a chatter's strip says nothing while the Creators load, then \"No creators on this relay\" for none", async () => {
    session.user.user = null;
    session.chatter.chatter = { chatter_id: "c-chatter", username: "chatter" };
    session.employee = { current: null, hydrated: true, pickedId: null };
    const reply = held<Response>();
    const fetchMock = vi.fn((_url: string) => reply.promise);
    vi.stubGlobal("fetch", fetchMock);
    const { queryClient } = renderStrip();
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.map(([u]) => u)).toContain("/chatter/me/accounts"));
    expectNoEmptyText();

    await act(async () => reply.settle(new Response("[]", { status: 200 })));
    expect(await screen.findByText(NONE)).toBeInTheDocument();

    // A Creator granted later: closing her tab is filed under the chatter id.
    fetchMock.mockImplementation(async () =>
      new Response(JSON.stringify([{ account_id: ZED, nickname: "Zed Creator", color: null, is_active: true }]), { status: 200 }));
    await act(() => queryClient.invalidateQueries({ queryKey: ["chatter", "self", "accounts"] }));
    await screen.findByRole("tab", { name: /Zed Creator/ });
    await userEvent.click(closeButton("Zed Creator"));
    expect(storedTabKeys()).toEqual([tabsKey("c-chatter")]);
  });

  it("a failed accounts read says \"No creators on this relay\", not an empty strip", async () => {
    resetComposerHarness();
    routeRelay("/admin/accounts", () => Promise.reject(new Error("relay down")));
    renderStrip();
    expect(await screen.findByText(NONE)).toBeInTheDocument();
    expect(strip().queryAllByRole("tab")).toHaveLength(0);
  });

  it("\"+ Add a Creator\" lists each Creator as open or add; picking a closed one reopens it in place and activates it", async () => {
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    await userEvent.click(closeButton("Amy Creator"));
    expect(picker()).toBeNull();

    await userEvent.click(addCreator());
    const rows = within(picker()!).getAllByRole("button");
    // Every session-bearing Creator, Nia (no session) left out.
    expect(rows.map((r) => r.textContent)).toEqual([
      "ZEZed Creator open",
      "MAMax Creator open",
      "AMAmy Creator add",
    ]);
    expect(within(rows[2]).getByText("add")).toBeInTheDocument();

    await userEvent.click(within(picker()!).getByRole("button", { name: "Amy Creator add" }));
    expect(picker()).toBeNull();
    // Back in the relay's position, between Zed and Max, and active.
    const tabs = strip().getAllByRole("tab");
    expect(tabs.map((t) => t.getAttribute("title"))).toEqual([
      "Zed Creator — 3 unread — 0 awaiting reply",
      "Amy Creator — 9+ unread — 0 awaiting reply",
      "Max Creator — 0 unread — 0 awaiting reply",
    ]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("aria-selected", "false");
    expect(scopeText()).toBe(`model:${AMY}`);
    // Focus follows the pick to the reopened tab.
    expect(document.activeElement).toBe(tabs[1]);
  });

  it("the Creator picker closes on Escape and on a pointer-down outside it", async () => {
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });

    await userEvent.click(addCreator());
    expect(picker()).not.toBeNull();
    // A press inside it leaves it open.
    fireEvent.pointerDown(within(picker()!).getByText("Creators on this relay (3)"));
    expect(picker()).not.toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(picker()).toBeNull();

    await userEvent.click(addCreator());
    expect(picker()).not.toBeNull();
    fireEvent.pointerDown(document.body);
    expect(picker()).toBeNull();
  });

  /* ── remembered per Employee (ticket 68) ───────────────────────────── */

  /** The open tabs' Creator names, in strip order. */
  const tabNames = () =>
    strip().getAllByRole("tab").map((t) => within(t).getByText(/ Creator$/).textContent);
  /** Every Creator tabs key in this window's storage. */
  const storedTabKeys = () =>
    Object.keys(window.localStorage).filter((k) => k.startsWith("chatterly:creator-tabs:"));
  const save = (key: string, value: { order: string[]; closed: string[] }) =>
    window.localStorage.setItem(key, JSON.stringify(value));
  const stored = (key: string) => {
    const raw = window.localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  };
  /** Another window wrote `key`: the browser fires `storage` here. */
  const otherWindowWrites = (key: string, value: { order: string[]; closed: string[] }) =>
    act(() => {
      save(key, value);
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: JSON.stringify(value) }));
    });

  it("a closed tab stays closed across a remount, and a storage event from another window updates the strip", async () => {
    const first = renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    await userEvent.click(closeButton("Amy Creator"));
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [], closed: [AMY] });

    first.unmount();
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator"]);
    expect(screen.queryByRole("tab", { name: /Amy Creator/ })).toBeNull();

    // Another window closes Zed and Max and reopens Amy.
    await otherWindowWrites(tabsKey(EMP_A.id), { order: [], closed: [ZED, MAX] });
    expect(tabNames()).toEqual(["Amy Creator"]);
    // And then reopens everything.
    await otherWindowWrites(tabsKey(EMP_A.id), { order: [], closed: [] });
    expect(tabNames()).toEqual(["Zed Creator", "Amy Creator", "Max Creator"]);
  });

  it("a saved order survives a roster change: a new Creator is appended, a removed one is gone, the rest keep the saved order", async () => {
    // Saved order Max, Zed, Amy: not the relay's (Zed, Amy, Max).
    save(tabsKey(EMP_A.id), { order: [MAX, ZED, AMY], closed: [] });
    const { queryClient } = renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Max Creator", "Zed Creator", "Amy Creator"]);

    // The relay drops Zed and gains Ola, first in its order, so a strip that
    // followed the relay would put her first.
    const OLA = "100000015";
    relayAccounts = [account(OLA, "Ola Creator", 5), ...ACCOUNTS.filter((a) => a.id !== ZED)];
    await act(() => queryClient.invalidateQueries({ queryKey: ["accounts"] }));
    await screen.findByRole("tab", { name: "Ola Creator" });
    expect(tabNames()).toEqual(["Max Creator", "Amy Creator", "Ola Creator"]);
  });

  it("a different Employee sees different tabs, switched from the top bar", async () => {
    save(tabsKey(EMP_A.id), { order: [], closed: [AMY] });
    save(tabsKey(EMP_B.id), { order: [AMY, MAX, ZED], closed: [ZED] });
    const { rerender } = renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator"]);

    atKeyboard(EMP_B);
    rerender(<ScopeProvider><CreatorTabs /><ScopeProbe /></ScopeProvider>);
    expect(tabNames()).toEqual(["Amy Creator", "Max Creator"]);

    // B's change is B's alone.
    await userEvent.click(closeButton("Max Creator"));
    expect(stored(tabsKey(EMP_B.id))).toEqual({ order: [AMY, MAX, ZED], closed: [ZED, MAX] });
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [], closed: [AMY] });

    atKeyboard(EMP_A);
    rerender(<ScopeProvider><CreatorTabs /><ScopeProbe /></ScopeProvider>);
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator"]);
  });

  it("no tabs and no stored key until the Employee resolves, then the first change writes the key", async () => {
    // An owner session whose roster has not landed yet, so its own row is not known.
    session.employee = { current: null, hydrated: false, pickedId: null };
    const { rerender, queryClient } = renderStrip();
    // The Creators have loaded: only the Employee holds the tabs back.
    await vi.waitFor(() =>
      expect(queryClient.getQueryState(["accounts", "u-owner"])?.status).toBe("success"));
    await act(async () => {});
    expectNoEmptyText();
    expect(storedTabKeys()).toEqual([]);

    atKeyboard(EMP_A);
    rerender(<ScopeProvider><CreatorTabs /><ScopeProbe /></ScopeProvider>);
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Amy Creator", "Max Creator"]);
    expect(storedTabKeys()).toEqual([]);
    await userEvent.click(closeButton("Max Creator"));
    expect(storedTabKeys()).toEqual([tabsKey(EMP_A.id)]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [], closed: [MAX] });
  });

  /* ── reorder by drag and by ArrowLeft / ArrowRight (ticket 69) ─────── */

  /** A stub `dataTransfer`: jsdom has none. */
  const dataTransfer = () => ({ setData: vi.fn(), effectAllowed: "", dropEffect: "" });
  /** Drag `from` and drop it on `onto`, as a pointer does. */
  function dragOnto(from: HTMLElement, onto: HTMLElement) {
    const dt = dataTransfer();
    fireEvent.dragStart(from, { dataTransfer: dt });
    fireEvent.dragOver(onto, { dataTransfer: dt });
    fireEvent.drop(onto, { dataTransfer: dt });
    fireEvent.dragEnd(from, { dataTransfer: dt });
    return dt;
  }
  const tab = (name: RegExp) => strip().getByRole("tab", { name });

  it("dragging a tab onto another moves it there, and the order survives a remount", async () => {
    const first = renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });

    // Max, last, dropped on Amy: to the middle, not to the end or the start.
    const dt = dragOnto(tab(/^Max Creator/), tab(/^Amy Creator/));
    expect(dt.setData).toHaveBeenCalledWith("text/plain", MAX);
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator", "Amy Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [ZED, MAX, AMY], closed: [] });

    first.unmount();
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator", "Amy Creator"]);

    // Rightwards: Zed, first, dropped on Max lands in Max's place.
    dragOnto(tab(/^Zed Creator/), tab(/^Max Creator/));
    expect(tabNames()).toEqual(["Max Creator", "Zed Creator", "Amy Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [MAX, ZED, AMY], closed: [] });
  });

  it("the sort menu orders the strip by most unread, A – Z or Z – A, the choice survives a remount, and \"Custom order\" restores the saved order", async () => {
    const user = userEvent.setup();
    const sortBy = async (label: string) => {
      await user.click(screen.getByRole("button", { name: "Sort creator tabs" }));
      await user.click(within(screen.getByRole("region", { name: "Sort creator tabs" })).getByRole("button", { name: label }));
    };
    const first = renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });

    await sortBy("Most unread first");
    expect(tabNames()).toEqual(["Amy Creator", "Zed Creator", "Max Creator"]);
    await sortBy("A – Z");
    expect(tabNames()).toEqual(["Amy Creator", "Max Creator", "Zed Creator"]);
    await sortBy("Z – A");
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator", "Amy Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toMatchObject({ sort: "za" });

    first.unmount();
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator", "Amy Creator"]);

    await sortBy("Custom order");
    expect(tabNames()).toEqual(["Zed Creator", "Amy Creator", "Max Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [], closed: [] });
  });

  it("useShownCreatorTabs is the strip's order; sorted by unread, unknown until the counts land", async () => {
    window.localStorage.setItem(tabsKey(EMP_A.id), JSON.stringify({ order: [], closed: [], sort: "unread" }));
    let land!: () => void;
    countsGate = new Promise((r) => { land = r; });
    function Probe() {
      const { open, known } = useShownCreatorTabs(useCreatorTabs());
      return <output aria-label="Shown order">{known ? open.map((a) => a.nickname).join(",") : "unknown"}</output>;
    }
    renderWithProviders(<ScopeProvider><CreatorTabs /><Probe /></ScopeProvider>);
    await screen.findByRole("tab", { name: /^Zed Creator/ });
    expect(screen.getByRole("status", { name: "Shown order" })).toHaveTextContent("unknown");
    await act(async () => { land(); });
    await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
    expect(screen.getByRole("status", { name: "Shown order" })).toHaveTextContent("Amy Creator,Zed Creator,Max Creator");
    expect(tabNames()).toEqual(["Amy Creator", "Zed Creator", "Max Creator"]);
  });

  it("ArrowLeft and ArrowRight move the focused tab one place with focus following; Enter activates it", async () => {
    const first = renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });

    tab(/^Max Creator/).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator", "Amy Creator"]);
    expect(document.activeElement).toBe(tab(/^Max Creator/));
    await userEvent.keyboard("{ArrowLeft}");
    expect(tabNames()).toEqual(["Max Creator", "Zed Creator", "Amy Creator"]);
    expect(document.activeElement).toBe(tab(/^Max Creator/));
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [MAX, ZED, AMY], closed: [] });

    // At either end: nothing moves and nothing is written.
    await userEvent.keyboard("{ArrowLeft}");
    tab(/^Amy Creator/).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tabNames()).toEqual(["Max Creator", "Zed Creator", "Amy Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [MAX, ZED, AMY], closed: [] });
    expect(document.activeElement).toBe(tab(/^Amy Creator/));

    await userEvent.keyboard("{ArrowLeft}");
    expect(tabNames()).toEqual(["Max Creator", "Amy Creator", "Zed Creator"]);
    expect(document.activeElement).toBe(tab(/^Amy Creator/));

    first.unmount();
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Max Creator", "Amy Creator", "Zed Creator"]);

    tab(/^Amy Creator/).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tabNames()).toEqual(["Max Creator", "Zed Creator", "Amy Creator"]);
    expect(document.activeElement).toBe(tab(/^Amy Creator/));
    expect(scopeText()).toBe("all");
    await userEvent.keyboard("{Enter}");
    expect(scopeText()).toBe(`model:${AMY}`);
    expect(tab(/^Amy Creator/)).toHaveAttribute("aria-selected", "true");
  });

  it("a reorder keeps a closed tab's slot, so it reopens there", async () => {
    save(tabsKey(EMP_A.id), { order: [], closed: [AMY] });
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator"]);

    tab(/^Max Creator/).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(tabNames()).toEqual(["Max Creator", "Zed Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [MAX, AMY, ZED], closed: [AMY] });

    await userEvent.click(addCreator());
    await userEvent.click(within(picker()!).getByRole("button", { name: "Amy Creator add" }));
    expect(tabNames()).toEqual(["Max Creator", "Amy Creator", "Zed Creator"]);
  });

  it("a reorder keeps the slot of a saved Creator that has left the relay", async () => {
    // Gone is saved first but not on the relay, so a reorder that rebuilt the
    // order from the relay alone would drop her slot.
    const GONE = "100000016";
    save(tabsKey(EMP_A.id), { order: [GONE, ZED, AMY, MAX], closed: [] });
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Amy Creator", "Max Creator"]);

    tab(/^Max Creator/).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(tabNames()).toEqual(["Zed Creator", "Max Creator", "Amy Creator"]);
    expect(stored(tabsKey(EMP_A.id))).toEqual({ order: [GONE, ZED, MAX, AMY], closed: [] });
  });

  it("right-click offers \"Open in a new window\", which opens the Creator window URL for that Creator as a separate window", async () => {
    const windowOpen = vi.spyOn(window, "open").mockImplementation(() => null);
    renderStrip();
    const amy = await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
    const openItem = () => screen.queryByRole("button", { name: "Open in a new window" });
    expect(openItem()).toBeNull();

    // The browser's own context menu is suppressed.
    expect(fireEvent.contextMenu(amy)).toBe(false);
    await userEvent.click(openItem()!);

    // The Creator window URL (spec, Contracts), asked for as a popup.
    expect(windowOpen).toHaveBeenCalledTimes(1);
    expect(windowOpen).toHaveBeenCalledWith(`/messages-pro?account=${AMY}`, "_blank", "popup");
    expect(openItem()).toBeNull();
    // Opening a window is not picking the tab.
    expect(scopeText()).toBe("all");
    expect(amy).toHaveAttribute("aria-selected", "false");
    windowOpen.mockRestore();
  });

  it.each([
    ["not JSON", "{order:"],
    ["not the shape", JSON.stringify({ order: "Zed", closed: [AMY] })],
  ])("a stored value that is %s reads as the default tabs and is overwritten on the next change", async (_, raw) => {
    window.localStorage.setItem(tabsKey(EMP_A.id), raw);
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread" });
    expect(tabNames()).toEqual(["Zed Creator", "Amy Creator", "Max Creator"]);

    await userEvent.click(closeButton("Max Creator"));
    expect(window.localStorage.getItem(tabsKey(EMP_A.id))).toBe(JSON.stringify({ order: [], closed: [MAX] }));
  });
});

/* ── The No-live-connection / Disconnected mark (watched-creator-refresher tickets 17, 18) ── */

describe("CreatorTabs: the live mark", () => {
  /** The Shared refresher's snapshot on an accounts row (P1 C1), `live` for `sinceMs` on the Relay's clock. */
  const fresh = (id: string, live: "up" | "down" | "dead" | null, sinceMs: number | null) => {
    const now = Date.now();
    return { account_id: id, boot: now - 3_600_000, seq: 1, now, at: now - 30_000, cycle_s: 120, live,
             live_since: sinceMs === null ? null : now - sinceMs, values: {} };
  };
  const row = (a: ReturnType<typeof account>, f: ReturnType<typeof fresh> | null, deadAt: string | null = null) =>
    ({ ...a, session_dead_at: deadAt, ...(f ? { freshness: f } : {}) });
  const [zed, amy, nia, max] = ACCOUNTS;
  const mark = (el: HTMLElement) => el.querySelector("[data-live-mark]")?.getAttribute("data-live-mark") ?? null;
  const DOWN_3 = "No live connection for 3 min: new messages may arrive late";

  it("down past the 60 s grace: amber dot, the tooltip and \"no live connection\" ending the name; up or within grace: nothing", async () => {
    relayAccounts = [row(zed, fresh(ZED, "down", 210_000)), row(amy, fresh(AMY, "up", 600_000)), nia,
                     row(max, fresh(MAX, "down", 30_000))];
    renderStrip();
    const z = await screen.findByRole("tab", { name: "Zed Creator 3 unread no live connection" });
    expect(mark(z)).toBe("down");
    expect(z.querySelector("[data-live-mark]")).toHaveClass("bg-warn");
    expect(z).toHaveAttribute("title", `Zed Creator — 3 unread — 0 awaiting reply — ${DOWN_3}`);
    // The tab's unread number is today's DOM.
    expect(within(z).getByText("3")).toBeInTheDocument();
    const a = strip().getByRole("tab", { name: "Amy Creator 9+ unread" });
    expect(mark(a)).toBeNull();
    expect(a).toHaveAttribute("title", "Amy Creator — 9+ unread — 0 awaiting reply");
    // A routine reconnect (down 30 s): no dot.
    expect(mark(strip().getByRole("tab", { name: "Max Creator" }))).toBeNull();
    // No live region anywhere in the strip.
    expect(document.querySelector("[aria-live]")).toBeNull();
  });

  it("ages on the Relay's clock: a tab clock 5 min ahead of the seed's `now` marks nothing early", async () => {
    // The Relay's clock reads 5 min behind this tab's: Zed down 30 s, Amy down 3.5 min, on the Relay's clock.
    const skewed = (id: string, sinceMs: number) => {
      const f = fresh(id, "down", sinceMs);
      return { ...f, now: f.now - 300_000, live_since: f.live_since! - 300_000 };
    };
    relayAccounts = [row(zed, skewed(ZED, 30_000)), row(amy, skewed(AMY, 210_000)), nia, max];
    renderStrip();
    const a = await screen.findByRole("tab", { name: "Amy Creator 9+ unread no live connection" });
    expect(a).toHaveAttribute("title", `Amy Creator — 9+ unread — 0 awaiting reply — ${DOWN_3}`);
    expect(mark(strip().getByRole("tab", { name: "Zed Creator 3 unread" }))).toBeNull();
  });

  it("a Dead session shows red \"Disconnected\" at once, from the snapshot first, else the account's session_dead_at", async () => {
    relayAccounts = [
      // Re-captured: the snapshot reads up beside a stale session_dead_at.
      row(zed, fresh(ZED, "up", 3_000), ago(10)),
      // The snapshot says dead before the accounts row does.
      row(amy, fresh(AMY, "dead", 1_000)),
      nia,
      // No snapshot (the refresher off): the account's flag.
      row(max, null, ago(5)),
    ];
    renderStrip();
    const a = await screen.findByRole("tab", { name: "Amy Creator 9+ unread disconnected" });
    expect(mark(a)).toBe("dead");
    expect(a.querySelector("[data-live-mark]")).toHaveClass("bg-err");
    expect(a).toHaveAttribute("title", "Amy Creator — 9+ unread — 0 awaiting reply — Disconnected");
    const m = strip().getByRole("tab", { name: "Max Creator disconnected" });
    expect(mark(m)).toBe("dead");
    expect(mark(strip().getByRole("tab", { name: "Zed Creator 3 unread" }))).toBeNull();
  });

  it("\"+ Add a Creator\" shows the same dot and word on each Creator's row, open or closed", async () => {
    window.localStorage.setItem(tabsKey(EMP_A.id), JSON.stringify({ order: [], closed: [AMY] }));
    relayAccounts = [row(zed, fresh(ZED, "down", 210_000)), row(amy, fresh(AMY, "dead", 1_000)), nia,
                     row(max, fresh(MAX, "up", 600_000))];
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator 3 unread no live connection" });
    await userEvent.click(screen.getByRole("button", { name: "Add a Creator" }));
    const picker = within(screen.getByRole("region", { name: "Creator picker" }));
    const z = picker.getByRole("button", { name: "Zed Creator open no live connection" });
    expect(mark(z)).toBe("down");
    expect(z).toHaveAttribute("title", DOWN_3);
    const a = picker.getByRole("button", { name: "Amy Creator add disconnected" });
    expect(mark(a)).toBe("dead");
    expect(a).toHaveAttribute("title", "Disconnected");
    const m = picker.getByRole("button", { name: "Max Creator open" });
    expect(mark(m)).toBeNull();
    expect(m).not.toHaveAttribute("title");
  });
});

/* ── The Red circle from the Freshness store (creator-badges 0B, ticket 10) ── */

describe("CreatorTabs: the Red circle", () => {
  /** An accounts row whose `freshness` carries `values.unread_total` = `total`. */
  const withTotal = (a: ReturnType<typeof account>, total: object | null) => {
    const now = Date.now();
    return { ...a, freshness: { account_id: a.id, boot: now - 3_600_000, seq: 1, now, at: now - 30_000, cycle_s: 120,
                                live: "up", live_since: now - 600_000, values: { unread_total: total } } };
  };
  const total = (n: number | null, grey: string | null = null) => ({ n, at: Date.now() - 1_000, v: 1, grey });
  const [zed, amy, nia, max] = ACCOUNTS;
  const sortBy = async (label: string) => {
    await userEvent.click(screen.getByRole("button", { name: "Sort creator tabs" }));
    await userEvent.click(within(screen.getByRole("region", { name: "Sort creator tabs" })).getByRole("button", { name: label }));
  };
  const names = () => strip().getAllByRole("tab").map((t) => within(t).getByText(/ Creator$/).textContent);

  it("draws \"9+\", the digit or a Grey circle from the slot, never the route's count; the title says the same", async () => {
    relayAccounts = [withTotal(zed, total(35)), withTotal(amy, total(3)), nia, withTotal(max, total(4, "socket_down"))];
    renderStrip();
    const z = await screen.findByRole("tab", { name: "Zed Creator 9+ unread" });
    expect(z).toHaveAttribute("title", "Zed Creator — 9+ unread — 0 awaiting reply");
    const a = strip().getByRole("tab", { name: "Amy Creator 3 unread" });
    expect(a).toHaveAttribute("title", "Amy Creator — 3 unread — 0 awaiting reply");
    const m = strip().getByRole("tab", { name: "Max Creator unread count unknown" });
    expect(m).toHaveAttribute("title", "Max Creator — unread count unknown");
    expect(m.querySelector("[data-red-circle='grey']")).toBeInTheDocument();
    expect(m.textContent).not.toMatch(/\d/);
  });

  it("story 26: a slot {n: 3} renders \"3\" and the tab's text and title hold no other number", async () => {
    relayAccounts = [zed, withTotal(amy, { n: 3 }), nia, max];
    renderStrip();
    const a = await screen.findByRole("tab", { name: "Amy Creator 3 unread" });
    expect(a.textContent!.match(/\d+/g)).toEqual(["3"]);
    expect(a.getAttribute("title")!.match(/\d+/g)).toEqual(["3", "0"]);
  });

  it("0 draws no circle; \"Most unread first\" sorts by the shown number, grey as 0 whatever its `n`", async () => {
    // Custom order Zed, Amy, Max: grey with n 5, then 2, then 0. Raw `n` would put Zed first; grey-last would put it
    // after Max. Grey as 0 ties with Max and keeps its place before it.
    relayAccounts = [withTotal(zed, total(5, "socket_down")), withTotal(amy, total(2)), nia, withTotal(max, total(0))];
    renderStrip();
    const m = await screen.findByRole("tab", { name: "Max Creator" });
    expect(m).toHaveAttribute("title", "Max Creator — 0 unread — 0 awaiting reply");
    expect(strip().getByRole("tab", { name: "Zed Creator unread count unknown" })).toBeInTheDocument();
    await sortBy("Most unread first");
    expect(names()).toEqual(["Amy Creator", "Zed Creator", "Max Creator"]);
  });

  it("a non-OF Creator's null slot draws the route's count by the new rule", async () => {
    relayAccounts = [withTotal(zed, total(1)), withTotal(amy, null), nia, max];
    renderStrip();
    const a = await screen.findByRole("tab", { name: "Amy Creator 9+ unread" });
    expect(a).toHaveAttribute("title", "Amy Creator — 9+ unread — 0 awaiting reply");
  });

  it("the Relay's stream unreachable: every tab grey, route counts or not", async () => {
    bus.connected = false;
    relayAccounts = [withTotal(zed, total(3)), amy, nia, max];
    renderStrip();
    await screen.findByRole("tab", { name: "Zed Creator unread count unknown" });
    expect(strip().getByRole("tab", { name: "Amy Creator unread count unknown" })).toBeInTheDocument();
    expect(strip().getByRole("tab", { name: "Max Creator unread count unknown" })).toBeInTheDocument();
  });
});

describe("CreatorTabs: the Amber circle", () => {
  const withTotal = (a: ReturnType<typeof account>, total: object) => {
    const now = Date.now();
    return { ...a, freshness: { account_id: a.id, boot: now - 3_600_000, seq: 1, now, at: now - 30_000, cycle_s: 120,
                                live: "up", live_since: now - 600_000, values: { unread_total: total } } };
  };
  const total = (n: number, amber: number | null, grey: string | null = null) =>
    ({ n, at: Date.now() - 1_000, v: 1, grey, amber, amber_at: Date.now() - 2_000 });
  const [zed, amy, nia, max] = ACCOUNTS;
  const owe = (tab: HTMLElement) => tab.querySelector<HTMLElement>("[data-badge='owe']");

  it("draws \"3\", \"9+\" or a grey amber dot after the red one; the title and accessible name say \"awaiting reply\"", async () => {
    relayAccounts = [withTotal(zed, total(2, 3)), withTotal(amy, total(1, 40)), nia, withTotal(max, total(4, null))];
    renderStrip();
    const z = await screen.findByRole("tab", { name: "Zed Creator 2 unread 3 awaiting reply" });
    expect(z).toHaveAttribute("title", "Zed Creator — 2 unread — 3 awaiting reply");
    expect(owe(z)).toHaveTextContent("3");
    expectDomOrder([within(z).getByText("2"), owe(z)!]);
    const a = strip().getByRole("tab", { name: "Amy Creator 1 unread 9+ awaiting reply" });
    expect(a).toHaveAttribute("title", "Amy Creator — 1 unread — 9+ awaiting reply");
    expect(owe(a)).toHaveTextContent("9+");
    const m = strip().getByRole("tab", { name: "Max Creator 4 unread awaiting reply unknown" });
    expect(m).toHaveAttribute("title", "Max Creator — 4 unread — awaiting reply unknown");
    expect(owe(m)).toHaveAttribute("data-amber-circle", "grey");
    expect(owe(m)!.textContent).not.toMatch(/\d/);
  });

  it("0 draws none; a whole-Creator grey draws exactly one grey circle; a slot with no `amber` key draws the route's owe_reply", async () => {
    relayAccounts = [withTotal(zed, total(2, 0)), withTotal(amy, total(5, 2, "socket_down")), nia,
                     withTotal(max, { n: 0, at: Date.now() - 1_000, v: 1, grey: null })];
    COUNTS[MAX] = { unread: 0, owe_reply: 4 };
    onTestFinished(() => { COUNTS[MAX] = { unread: 0, owe_reply: 0 }; });
    renderStrip();
    const z = await screen.findByRole("tab", { name: "Zed Creator 2 unread" });
    expect(owe(z)).toBeNull();
    expect(z).toHaveAttribute("title", "Zed Creator — 2 unread — 0 awaiting reply");
    const a = strip().getByRole("tab", { name: "Amy Creator unread count unknown" });
    expect(a.querySelectorAll("[data-red-circle='grey'], [data-badge='owe']")).toHaveLength(1);
    expect(a).toHaveAttribute("title", "Amy Creator — unread count unknown");
    const m = strip().getByRole("tab", { name: "Max Creator 4 awaiting reply" });
    expect(owe(m)).toHaveTextContent("4");
  });
});
