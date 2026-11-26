import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("@/lib/events", async (orig) => ({
  ...(await orig<typeof import("@/lib/events")>()),
  eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {}, onStreamState: () => () => {} },
}));
type FixtureEmployee = { id: number; display_name: string; color: null; is_active: true };
const session = vi.hoisted(() => ({
  user: { user: { user_id: "u-owner", username: "owner" }, loading: false, logout: () => {} },
  chatter: { chatter: null, loading: false, logout: () => {} },
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

import { ScopeProvider } from "@/contexts/ScopeContext";
import { resetRosterCountsModuleState } from "@/hooks/useRosterCounts";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { expectDomOrder, relayGet, resetComposerHarness, routeRelay, tooltipOf } from "./composerTestHarness";
import { CreatorTabs } from "./CreatorTabs";
import { FanTabs, OpenInNewTabButton } from "./FanTabs";
import { fanTabKey } from "./useFanTabs";


const ZED = "100000021";
const AMY = "100000022";
const account = (id: string, name: string) => ({
  id, nickname: name, name, platform: "onlyfans", color: "#4a90d9",
  has_session: true, session_dead_at: null, created_at: null, last_used_at: null,
});
// A Fansly snowflake past 2^53: `Number()` would round it to another Fan.
const SNOWFLAKE = "900604711209099264";

const EMP_A: FixtureEmployee = { id: 300000001, display_name: "Fixture Employee A", color: null, is_active: true };
const EMP_B: FixtureEmployee = { id: 300000002, display_name: "Fixture Employee B", color: null, is_active: true };
function atKeyboard(employee: FixtureEmployee) {
  session.employee = { current: employee, hydrated: true, pickedId: employee.id };
}
const fanTabsKey = (employeeKey: string | number) => `chatterly:fan-tabs:v1:${employeeKey}`;

beforeEach(() => {
  atKeyboard(EMP_A);
  resetComposerHarness();
  routeRelay("/admin/accounts", () => ({
    accounts: [account(ZED, "Zed Creator"), account(AMY, "Amy Creator")], active_account_id: ZED,
  }));
});

afterEach(() => {
  cleanup();
});

const strip = () => within(screen.getByRole("tablist", { name: "Fan tabs strip" }));

describe("FanTabs with OpenInNewTabButton", () => {
  it('"Open in new tab" adds a Fan tab, and a second press adds no duplicate', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />
        <FanTabs activeKey={null} onActivate={vi.fn()} onClosed={vi.fn()} />
      </>,
    );
    expect(strip().queryAllByRole("tab")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    expect(strip().getAllByRole("tab").map((t) => t.textContent)).toEqual(["Fixture Fan One"]);

    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    expect(strip().getAllByRole("tab").map((t) => t.textContent)).toEqual(["Fixture Fan One"]);
  });

  it("a tab's tooltip names the Fan and the Creator, and the active key's tab is selected", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(
      <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));

    rerender(<FanTabs activeKey={fanTabKey(AMY, SNOWFLAKE)} onActivate={vi.fn()} onClosed={vi.fn()} />);
    const one = strip().getByRole("tab", { name: "Fixture Fan One" });
    const two = strip().getByRole("tab", { name: "Fixture Fan Two" });
    expect(strip().getAllByRole("tab")).toEqual([one, two]);
    expect(await screen.findByTitle("Fixture Fan One · Zed Creator")).toBe(one);
    expect(tooltipOf(two)).toBe("Fixture Fan Two · Amy Creator");
    expect(one).toHaveAttribute("aria-selected", "false");
    expect(two).toHaveAttribute("aria-selected", "true");
  });

  it("clicking a tab calls onActivate with that tab", async () => {
    const user = userEvent.setup();
    const onActivate = vi.fn();
    const { rerender } = renderWithProviders(
      <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<FanTabs activeKey={fanTabKey(ZED, 501)} onActivate={onActivate} onClosed={vi.fn()} />);

    await user.click(strip().getByRole("tab", { name: "Fixture Fan Two" }));
    expect(onActivate).toHaveBeenCalledTimes(1);
    expect(onActivate).toHaveBeenLastCalledWith({ accountId: AMY, fanId: SNOWFLAKE, name: "Fixture Fan Two" });

    await user.click(strip().getByRole("tab", { name: "Fixture Fan One" }));
    expect(onActivate).toHaveBeenCalledTimes(2);
    expect(onActivate).toHaveBeenLastCalledWith({ accountId: ZED, fanId: 501, name: "Fixture Fan One" });
  });

  it("a tab shows the online dot, the name, the unread badge and 🔥 from a cache seeded under the Fan List row's keys", async () => {
    const user = userEvent.setup();
    const client = makeTestQueryClient();
    client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, gcTime: Infinity } });
    const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
    client.setQueryData(["chats", "model", ZED, null, null, null, 50], {
      pages: [{
        rows: [{
          withUser: { id: 501, name: "Fixture Fan One" }, __accountId: ZED,
          isOnline: true, hasUnread: true, unreadMessagesCount: 3,
          lastMessage: { id: 9001, text: "hi", createdAt: ago(60_000) },
        }],
        hasMore: false,
      }],
      pageParams: [0],
    });
    client.setQueryData(["of-user", ZED, 501], { id: 501, name: "Fixture Fan One", username: "fixturefan1" });
    client.setQueryData(["last-purchases", ZED], [{
      amount: 12, createdAt: ago(3_600_000), user: { id: 501 },
      description: "Payment for message from Fixture Fan One", status: "done",
    }]);
    renderWithProviders(
      <>
        <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />
        <FanTabs activeKey={null} onActivate={vi.fn()} onClosed={vi.fn()} />
      </>,
      client,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));

    const tab = strip().getByRole("tab", { name: "Fixture Fan One 3 unread Bought a PPV within 7 days" });
    const dot = strip().getByRole("img", { name: "Online" });
    const badge = within(tab).getByText("3");
    const signal = within(tab).getByRole("img", { name: "Bought a PPV within 7 days" });
    expect(signal).toHaveTextContent("🔥");
    expectDomOrder([dot, within(tab).getByText("Fixture Fan One"), badge, signal,
      strip().getByRole("button", { name: "Close Fixture Fan One" })]);
  });

  it("a tab with nothing cached shows its stored name and the offline dot, and no badge or signal", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />
        <FanTabs activeKey={null} onActivate={vi.fn()} onClosed={vi.fn()} />
      </>,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));

    const tab = strip().getByRole("tab", { name: "Fixture Fan Two" });
    expect(tab).toHaveTextContent(/^Fixture Fan Two$/);
    expect(strip().getByRole("img", { name: "Offline" })).toBeInTheDocument();
    expect(strip().queryByRole("img", { name: "Online" })).not.toBeInTheDocument();
    expect(within(tab).queryByRole("img")).not.toBeInTheDocument();
  });

  it("closing the active tab calls onClosed with the last remaining tab, and focus lands on it", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    const { rerender } = renderWithProviders(
      <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={ZED} fanId={503} name="Fixture Fan Three" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={ZED} fanId={504} name="Fixture Fan Four" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<FanTabs activeKey={fanTabKey(ZED, 501)} onActivate={vi.fn()} onClosed={onClosed} />);

    await user.click(strip().getByRole("button", { name: "Close Fixture Fan Two" }));
    expect(strip().getAllByRole("tab").map((t) => t.textContent))
      .toEqual(["Fixture Fan One", "Fixture Fan Three", "Fixture Fan Four"]);
    expect(onClosed).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(strip().getByRole("tab", { name: "Fixture Fan One" }));

    await user.click(strip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(strip().getAllByRole("tab").map((t) => t.textContent)).toEqual(["Fixture Fan Three", "Fixture Fan Four"]);
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(onClosed).toHaveBeenLastCalledWith({ accountId: ZED, fanId: 504, name: "Fixture Fan Four" });
    expect(document.activeElement).toBe(strip().getByRole("tab", { name: "Fixture Fan Four" }));
  });

  it("closing an inactive tab while the open Fan has no tab calls nothing, and focus lands on the last remaining tab", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    const { rerender } = renderWithProviders(
      <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={ZED} fanId={503} name="Fixture Fan Three" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<OpenInNewTabButton accountId={ZED} fanId={504} name="Fixture Fan Four" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<FanTabs activeKey={fanTabKey(AMY, SNOWFLAKE)} onActivate={vi.fn()} onClosed={onClosed} />);

    await user.click(strip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(strip().getAllByRole("tab").map((t) => t.textContent)).toEqual(["Fixture Fan Three", "Fixture Fan Four"]);
    expect(onClosed).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(strip().getByRole("tab", { name: "Fixture Fan Four" }));
  });

  it("closing the only tab while another Fan is open calls onClosed(null), and focus lands on the strip", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    const { rerender } = renderWithProviders(
      <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    rerender(<FanTabs activeKey={fanTabKey(AMY, SNOWFLAKE)} onActivate={vi.fn()} onClosed={onClosed} />);

    await user.click(strip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(strip().queryAllByRole("tab")).toHaveLength(0);
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(onClosed).toHaveBeenLastCalledWith(null);
    expect(document.activeElement).toBe(screen.getByRole("tablist", { name: "Fan tabs strip" }));
  });

  type StoredTab = { accountId: string; fanId: string; name: string };
  const tabNames = () => strip().queryAllByRole("tab").map((t) => t.textContent);
  const storedTabKeys = () =>
    Object.keys(window.localStorage).filter((k) => k.startsWith("chatterly:fan-tabs:"));
  const stored = (key: string) => {
    const raw = window.localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  };
  const otherWindowWrites = (key: string, value: StoredTab[]) =>
    act(() => {
      window.localStorage.setItem(key, JSON.stringify(value));
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: JSON.stringify(value) }));
    });

  it("tabs survive a remount, a different Employee sees different tabs, and nothing is written while the Employee is unresolved", async () => {
    const user = userEvent.setup();
    const onActivate = vi.fn();
    const onClosed = vi.fn();
    window.localStorage.setItem(fanTabsKey(EMP_B.id), JSON.stringify([
      { accountId: AMY, fanId: "502", name: "Fixture Fan Three" },
      { accountId: ZED, fanId: "0", name: "Fixture Fan Broken" },
    ]));
    const first = renderWithProviders(
      <OpenInNewTabButton accountId={ZED} fanId={501} name="Fixture Fan One" />,
    );
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    first.rerender(<OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />);
    await user.click(screen.getByRole("button", { name: "Open in new tab" }));
    expect(stored(fanTabsKey(EMP_A.id))).toEqual([
      { accountId: ZED, fanId: "501", name: "Fixture Fan One" },
      { accountId: AMY, fanId: SNOWFLAKE, name: "Fixture Fan Two" },
    ]);
    first.unmount();

    const page = () => (
      <>
        <OpenInNewTabButton accountId={ZED} fanId={503} name="Fixture Fan Four" />
        <FanTabs activeKey={fanTabKey(ZED, 501)} onActivate={onActivate} onClosed={onClosed} />
      </>
    );
    const { rerender } = renderWithProviders(page());
    expect(tabNames()).toEqual(["Fixture Fan One", "Fixture Fan Two"]);
    await user.click(strip().getByRole("tab", { name: "Fixture Fan One" }));
    expect(onActivate).toHaveBeenLastCalledWith({ accountId: ZED, fanId: 501, name: "Fixture Fan One" });
    await user.click(strip().getByRole("tab", { name: "Fixture Fan Two" }));
    expect(onActivate).toHaveBeenLastCalledWith({ accountId: AMY, fanId: SNOWFLAKE, name: "Fixture Fan Two" });

    atKeyboard(EMP_B);
    rerender(page());
    expect(tabNames()).toEqual(["Fixture Fan Three"]);

    session.employee = { current: null, hydrated: false, pickedId: null };
    const before = { ...window.localStorage };
    rerender(page());
    expect(tabNames()).toEqual([]);
    const button = screen.getByRole("button", { name: "Open in new tab" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(tabNames()).toEqual([]);
    expect({ ...window.localStorage }).toEqual(before);
    expect(storedTabKeys().sort()).toEqual([fanTabsKey(EMP_A.id), fanTabsKey(EMP_B.id)]);

    atKeyboard(EMP_A);
    rerender(page());
    expect(tabNames()).toEqual(["Fixture Fan One", "Fixture Fan Two"]);
    expect(onClosed).not.toHaveBeenCalled();
  });

  it("storage events from another window add a tab and remove one, and removing the active one calls onClosed", async () => {
    const onClosed = vi.fn();
    const one = { accountId: ZED, fanId: "501", name: "Fixture Fan One" };
    const two = { accountId: AMY, fanId: SNOWFLAKE, name: "Fixture Fan Two" };
    const three = { accountId: ZED, fanId: "503", name: "Fixture Fan Three" };
    window.localStorage.setItem(fanTabsKey(EMP_A.id), JSON.stringify([one, two]));
    const { rerender } = renderWithProviders(
      <FanTabs activeKey={fanTabKey(AMY, SNOWFLAKE)} onActivate={vi.fn()} onClosed={onClosed} />,
    );
    expect(tabNames()).toEqual(["Fixture Fan One", "Fixture Fan Two"]);

    await otherWindowWrites(fanTabsKey(EMP_A.id), [one, two, three]);
    expect(tabNames()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    expect(onClosed).not.toHaveBeenCalled();

    await otherWindowWrites(fanTabsKey(EMP_A.id), [one, three]);
    expect(tabNames()).toEqual(["Fixture Fan One", "Fixture Fan Three"]);
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(onClosed).toHaveBeenLastCalledWith({ accountId: ZED, fanId: 503, name: "Fixture Fan Three" });

    rerender(<FanTabs activeKey={fanTabKey(ZED, 503)} onActivate={vi.fn()} onClosed={onClosed} />);
    await otherWindowWrites(fanTabsKey(EMP_A.id), [three]);
    expect(tabNames()).toEqual(["Fixture Fan Three"]);
    expect(onClosed).toHaveBeenCalledTimes(1);
  });


  const LIMIT = "Fan tab limit reached (100)";
  const seeded = (n: number, accountId = ZED): StoredTab[] =>
    Array.from({ length: n }, (_, i) => ({ accountId, fanId: String(600 + i), name: `Fixture Fan ${600 + i}` }));
  function held<T>() {
    let settle!: (value: T) => void;
    const promise = new Promise<T>((resolve) => { settle = resolve; });
    return { promise, settle };
  }

  it('100 seeded tabs leave "Open in new tab" disabled with "Fan tab limit reached (100)"; nothing is evicted, and a close enables it again', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(fanTabsKey(EMP_A.id), JSON.stringify(seeded(100)));
    renderWithProviders(
      <>
        <OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />
        <FanTabs activeKey={null} onActivate={vi.fn()} onClosed={vi.fn()} />
      </>,
    );
    await screen.findByTitle("Fixture Fan 600 · Zed Creator");
    expect(tabNames()).toHaveLength(100);
    const button = screen.getByRole("button", { name: "Open in new tab" });
    expect(button).toBeDisabled();
    expect(tooltipOf(button)).toBe(LIMIT);

    await user.click(button);
    expect(tabNames()).toHaveLength(100);
    expect(stored(fanTabsKey(EMP_A.id))).toEqual(seeded(100));

    await user.click(strip().getByRole("button", { name: "Close Fixture Fan 600" }));
    expect(button).toBeEnabled();
    expect(tooltipOf(button)).toBe("Pin this chat as a tab so you can switch between conversations without losing it");
    await user.click(button);
    expect(tabNames()).toHaveLength(100);
    expect(tabNames().at(-1)).toBe("Fixture Fan Two");
    expect(button).toBeDisabled();
  });

  it("a seeded tab whose Creator is not loaded is hidden but still counts toward the cap, and shows again when the Creator returns", async () => {
    const GONE = "100000029";
    const gone: StoredTab = { accountId: GONE, fanId: "700", name: "Fixture Fan Gone" };
    const onClosed = vi.fn();
    const reply = held<unknown>();
    let accountsReply: unknown = reply.promise;
    resetComposerHarness();
    window.localStorage.setItem(fanTabsKey(EMP_A.id), JSON.stringify([gone, ...seeded(99)]));
    routeRelay("/admin/accounts", () => accountsReply);
    const { queryClient } = renderWithProviders(
      <>
        <OpenInNewTabButton accountId={AMY} fanId={SNOWFLAKE} name="Fixture Fan Two" />
        <FanTabs activeKey={fanTabKey(GONE, 700)} onActivate={vi.fn()} onClosed={onClosed} />
      </>,
    );
    await vi.waitFor(() => expect(relayGet.mock.calls.map(([p]) => p)).toContain("/admin/accounts"));
    expect(tabNames()).toHaveLength(100);
    expect(tabNames()[0]).toBe("Fixture Fan Gone");

    const loaded = { accounts: [account(ZED, "Zed Creator"), account(AMY, "Amy Creator")], active_account_id: ZED };
    await act(async () => reply.settle(loaded));
    await vi.waitFor(() => expect(tabNames()).toHaveLength(99));
    expect(tabNames()).not.toContain("Fixture Fan Gone");
    const button = screen.getByRole("button", { name: "Open in new tab" });
    expect(button).toBeDisabled();
    expect(tooltipOf(button)).toBe(LIMIT);
    expect(stored(fanTabsKey(EMP_A.id))).toEqual([gone, ...seeded(99)]);
    expect(onClosed).not.toHaveBeenCalled();

    accountsReply = { ...loaded, accounts: [...loaded.accounts, account(GONE, "Gone Creator")] };
    await act(() => queryClient.invalidateQueries({ queryKey: ["accounts"] }));
    await vi.waitFor(() => expect(tabNames()).toHaveLength(100));
    expect(tabNames()[0]).toBe("Fixture Fan Gone");
    expect(onClosed).not.toHaveBeenCalled();
  });

  it("with the active tab hidden, closing the last shown tab empties the strip and calls onClosed(null)", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    const gone: StoredTab = { accountId: "100000029", fanId: "700", name: "Fixture Fan Gone" };
    const one: StoredTab = { accountId: ZED, fanId: "501", name: "Fixture Fan One" };
    window.localStorage.setItem(fanTabsKey(EMP_A.id), JSON.stringify([gone, one]));
    renderWithProviders(
      <FanTabs activeKey={fanTabKey("100000029", 700)} onActivate={vi.fn()} onClosed={onClosed} />,
    );
    await vi.waitFor(() => expect(tabNames()).toEqual(["Fixture Fan One"]));
    expect(onClosed).not.toHaveBeenCalled();

    await user.click(strip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(tabNames()).toEqual([]);
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(onClosed).toHaveBeenLastCalledWith(null);
    expect(stored(fanTabsKey(EMP_A.id))).toEqual([gone]);
  });

  it("with the Creator tabs rendered beside the Fan tabs, closing a Creator tab leaves its Fan tabs in the strip", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    const one: StoredTab = { accountId: ZED, fanId: "501", name: "Fixture Fan One" };
    const two: StoredTab = { accountId: AMY, fanId: SNOWFLAKE, name: "Fixture Fan Two" };
    const three: StoredTab = { accountId: ZED, fanId: "503", name: "Fixture Fan Three" };
    resetComposerHarness();
    resetRosterCountsModuleState();
    routeRelay("/admin/accounts/roster-counts", () => ({ counts: {} }));
    routeRelay("/admin/accounts", () => ({
      accounts: [account(ZED, "Zed Creator"), account(AMY, "Amy Creator")], active_account_id: ZED,
    }));
    window.localStorage.setItem(fanTabsKey(EMP_A.id), JSON.stringify([one, two, three]));
    renderWithProviders(
      <ScopeProvider>
        <CreatorTabs />
        <FanTabs activeKey={fanTabKey(ZED, 501)} onActivate={vi.fn()} onClosed={onClosed} />
      </ScopeProvider>,
    );
    const creatorStrip = () => within(screen.getByRole("tablist", { name: "Creator tabs" }));
    await creatorStrip().findByRole("tab", { name: /Zed Creator/ });

    await user.click(creatorStrip().getByRole("button", { name: "Close Zed Creator" }));
    expect(creatorStrip().queryByRole("tab", { name: /Zed Creator/ })).toBeNull();
    expect(tabNames()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    expect(stored(fanTabsKey(EMP_A.id))).toEqual([one, two, three]);
    expect(onClosed).not.toHaveBeenCalled();
  });

  describe("right-click menu", () => {
    const openItem = () => screen.queryByRole("button", { name: "Open in a new window" });
    const one: StoredTab = { accountId: ZED, fanId: "501", name: "Fixture Fan One" };
    const two: StoredTab = { accountId: AMY, fanId: SNOWFLAKE, name: "Fixture Fan Two" };
    let windowOpen: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      windowOpen = vi.spyOn(window, "open").mockImplementation(() => null);
      window.localStorage.setItem(fanTabsKey(EMP_A.id), JSON.stringify([one, two]));
    });
    afterEach(() => windowOpen.mockRestore());

    it("\"Open in a new window\" opens the Fan window URL as a separate window, without activating the tab", async () => {
      const user = userEvent.setup();
      const onActivate = vi.fn();
      renderWithProviders(<FanTabs activeKey={fanTabKey(ZED, 501)} onActivate={onActivate} onClosed={vi.fn()} />);
      const fanTwo = await strip().findByRole("tab", { name: "Fixture Fan Two" });
      expect(openItem()).toBeNull();

      expect(fireEvent.contextMenu(fanTwo)).toBe(false);
      await user.click(openItem()!);

      expect(windowOpen).toHaveBeenCalledTimes(1);
      expect(windowOpen).toHaveBeenCalledWith(`/messages-pro/${AMY}/${SNOWFLAKE}`, "_blank", "popup");
      expect(openItem()).toBeNull();
      expect(onActivate).not.toHaveBeenCalled();
      expect(fanTwo).toHaveAttribute("aria-selected", "false");
    });

    it("Escape and a press outside close the menu without opening anything; a left click still activates", async () => {
      const user = userEvent.setup();
      const onActivate = vi.fn();
      renderWithProviders(<FanTabs activeKey={null} onActivate={onActivate} onClosed={vi.fn()} />);
      const fanOne = await strip().findByRole("tab", { name: "Fixture Fan One" });

      fireEvent.contextMenu(fanOne);
      expect(openItem()).toBeInTheDocument();
      await user.keyboard("{Escape}");
      expect(openItem()).toBeNull();

      fireEvent.contextMenu(fanOne);
      expect(openItem()).toBeInTheDocument();
      fireEvent.pointerDown(document.body);
      expect(openItem()).toBeNull();
      expect(windowOpen).not.toHaveBeenCalled();

      await user.click(fanOne);
      expect(onActivate).toHaveBeenCalledTimes(1);
      expect(onActivate).toHaveBeenLastCalledWith({ ...one, fanId: 501 });
      expect(openItem()).toBeNull();
      expect(windowOpen).not.toHaveBeenCalled();
    });

    it("a scroll or a resize while the menu is open closes it without opening anything", async () => {
      renderWithProviders(<FanTabs activeKey={null} onActivate={vi.fn()} onClosed={vi.fn()} />);
      const fanOne = await strip().findByRole("tab", { name: "Fixture Fan One" });

      fireEvent.contextMenu(fanOne);
      expect(openItem()).toBeInTheDocument();
      fireEvent.scroll(screen.getByRole("tablist", { name: "Fan tabs strip" }));
      expect(openItem()).toBeNull();

      fireEvent.contextMenu(fanOne);
      expect(openItem()).toBeInTheDocument();
      fireEvent(window, new Event("resize"));
      expect(openItem()).toBeNull();

      expect(windowOpen).not.toHaveBeenCalled();
    });
  });
});
