/**
 * The platform selector (Infloww's `SelectPlatform`, index.9f50f370.js @11125100) and what the platform drives: the
 * creator list (usePlatformAccounts; useActiveAccounts stays neutral), the sidebar's page set (lib/nav `sidebarFor`),
 * the scope/route reconcile on any platform change (PlatformSync) and the "Fansly Login" prompt (PlatformGate). The Relay client is mocked; fixture ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let pathname = "/";
const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const owner = { user_id: "u1", username: "owner" };
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: owner, loading: false, logout: vi.fn() }),
  useOptionalUser: () => ({ user: owner }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: null }),
  useOptionalChatter: () => ({ chatter: null }),
}));
let counts: Record<string, { unread: number; owe_reply: number }> = {};
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCounts: () => counts }));
vi.mock("@/lib/appliedSettings", () => ({ useAppliedSettings: () => ({ data: undefined }) }));
// ScopeProvider pushes its scope to the SSE bus.
vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {} } }));

import PlatformGate, { LOAD_FAILED_LINE, PlatformSync } from "@/components/shell/PlatformGate";
import PlatformSwitcher from "@/components/shell/PlatformSwitcher";
import Sidebar from "@/components/shell/Sidebar";
import { ScopeProvider, useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { PLATFORM_KEY, resetPlatformForTests, setPlatform, usePlatform } from "@/lib/platform";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;

type Acct = { id: string; nickname?: string; platform?: "onlyfans" | "fansly" | null; has_session?: boolean; session_dead_at?: string };
let accounts: Acct[];
let client: QueryClient;

function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <ScopeProvider>{children}</ScopeProvider>
    </QueryClientProvider>
  );
}

function Probe() {
  const { scope } = useScope();
  return <output data-testid="probe">{`${usePlatform()} ${scope.kind === "model" ? scope.accountId : "all"}`}</output>;
}
const probe = () => screen.getByTestId("probe").textContent;

beforeEach(() => {
  window.localStorage.clear();
  resetPlatformForTests();
  pathname = "/";
  push.mockReset();
  counts = {};
  accounts = [
    { id: "of-1", nickname: "Oscar", platform: "onlyfans", has_session: true },
    { id: "of-2", nickname: "Olive", has_session: true }, // no platform: OnlyFans
    { id: "fy-1", nickname: "Fiona", platform: "fansly", has_session: true },
    { id: "fy-2", nickname: "Faye", platform: "fansly", has_session: false },
  ];
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  relayGet.mockReset();
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/accounts") return Promise.resolve({ accounts, active_account_id: null });
    return Promise.resolve({});
  });
});
afterEach(cleanup);

describe("usePlatformAccounts follows the platform", () => {
  it("lists the platform's accounts with a session; an account with no platform is OnlyFans'", async () => {
    const { result } = renderHook(() => usePlatformAccounts().map((a) => a.id), { wrapper: Providers });
    await waitFor(() => expect(result.current).toEqual(["of-1", "of-2"]));
    act(() => setPlatform("fansly"));
    expect(result.current).toEqual(["fy-1"]);
  });

  it("useActiveAccounts stays on every platform, so global listeners keep hearing OnlyFans in Fansly mode", async () => {
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
    const { result } = renderHook(() => useActiveAccounts().map((a) => a.id), { wrapper: Providers });
    await waitFor(() => expect(result.current).toEqual(["of-1", "of-2", "fy-1"]));
  });
});

describe("PlatformSwitcher", () => {
  const trigger = () => screen.getByRole("button", { name: /OnlyFans|Fansly/ });
  const row = (name: string) => screen.getByRole("menuitemradio", { name: new RegExp(`^${name}`) });

  it("lists OnlyFans and Fansly, checks the active one, and counts each platform's unread", async () => {
    counts = { "of-1": { unread: 3, owe_reply: 0 }, "of-2": { unread: 2, owe_reply: 1 }, "fy-1": { unread: 120, owe_reply: 0 }, "fy-2": { unread: 9, owe_reply: 0 } };
    render(<Providers><PlatformSwitcher /></Providers>);
    await waitFor(() => expect(screen.getByTestId("platform-unread-dot")).toBeInTheDocument());
    expect(trigger()).toHaveTextContent("OnlyFans");
    fireEvent.click(trigger());
    const menu = screen.getByRole("menu", { name: "Platform" });
    expect(within(menu).getAllByRole("menuitemradio").map((r) => r.textContent)).toEqual(["OnlyFans5", "Fansly99+"]);
    expect(row("OnlyFans")).toHaveAttribute("aria-checked", "true");
    expect(row("Fansly")).toHaveAttribute("aria-checked", "false");
  });

  it("lists mym and Fanvue after them as disabled Coming soon rows that pick nothing", async () => {
    render(<Providers><PlatformSwitcher /></Providers>);
    fireEvent.click(trigger());
    const menu = screen.getByRole("menu", { name: "Platform" });
    const soon = within(menu).getAllByRole("menuitem");
    // Each row's name, then its chip (mym's wordmark is SVG text, so not the row's textContent).
    expect(soon.map((r) => [...r.querySelectorAll("span")].map((s) => s.textContent))).toEqual([
      ["mym", "Coming soon"],
      ["Fanvue", "Coming soon"],
    ]);
    for (const r of soon) expect(r).toBeDisabled();
    expect(within(soon[0]).getByTestId("platform-logo-mym")).toBeInTheDocument();
    expect(within(soon[1]).getByTestId("platform-logo-fanvue")).toBeInTheDocument();
    fireEvent.click(soon[1]);
    expect(screen.getByRole("menu", { name: "Platform" })).toBeInTheDocument();
    expect(window.localStorage.getItem(PLATFORM_KEY)).toBeNull();
    expect(trigger()).toHaveTextContent("OnlyFans");
  });

  it("no unread: no chip and no dot", async () => {
    render(<Providers><PlatformSwitcher /></Providers>);
    fireEvent.click(trigger());
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    expect(screen.queryByTestId("platform-unread-dot")).toBeNull();
    expect(row("Fansly").textContent).toBe("Fansly");
  });

  it("picking Fansly saves it, drops a scope on an OnlyFans creator, and leaves an OnlyFans-only page", async () => {
    window.localStorage.setItem("chatterly:scope", "model:of-1");
    pathname = "/analytics/fan-reports";
    render(<Providers><PlatformSync /><PlatformSwitcher /><Probe /></Providers>);
    await waitFor(() => expect(probe()).toBe("onlyfans of-1"));
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    fireEvent.click(trigger());
    fireEvent.click(row("Fansly"));
    expect(probe()).toBe("fansly all");
    expect(window.localStorage.getItem(PLATFORM_KEY)).toBe("fansly");
    expect(push).toHaveBeenCalledWith("/growth/scripts");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger()).toHaveTextContent("Fansly");
  });

  it("on a page both platforms show, switching stays put and keeps a scope on that platform's creator", async () => {
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
    window.localStorage.setItem("chatterly:scope", "model:fy-1");
    pathname = "/growth/scripts";
    render(<Providers><PlatformSync /><PlatformSwitcher /><Probe /></Providers>);
    await waitFor(() => expect(probe()).toBe("fansly fy-1"));
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    fireEvent.click(trigger());
    fireEvent.click(row("OnlyFans"));
    expect(probe()).toBe("onlyfans all");
    expect(push).not.toHaveBeenCalled();
  });

  it("the rail draws the logo and the dot, named for screen readers", () => {
    render(<Providers><PlatformSwitcher collapsed /></Providers>);
    expect(screen.getByRole("button", { name: "Platform: OnlyFans" })).not.toHaveTextContent("OnlyFans");
  });

  it("draws Infloww's 20px brand marks: the OnlyFans swirl on the trigger, the Fansly one in the list", () => {
    render(<Providers><PlatformSwitcher /></Providers>);
    const logo = within(trigger()).getByTestId("platform-logo-onlyfans");
    expect(logo.tagName.toLowerCase()).toBe("svg");
    expect(logo).toHaveClass("w-5", "h-5");
    expect([...logo.querySelectorAll("path")].map((p) => p.getAttribute("fill"))).toEqual(["#00AEEF", "#008CCF"]);
    fireEvent.click(trigger());
    expect(within(row("Fansly")).getByTestId("platform-logo-fansly").querySelector("path")).toHaveAttribute("fill", "#2699F7");
  });
});

describe("PlatformSync: a platform change from another window", () => {
  /** What another tab's setPlatform looks like here: the write lands, then the storage event fires. */
  const otherTabPicks = (p: "onlyfans" | "fansly") =>
    act(() => {
      window.localStorage.setItem(PLATFORM_KEY, p);
      window.dispatchEvent(new StorageEvent("storage", { key: PLATFORM_KEY, newValue: p }));
    });

  it("drops a scope on the other platform's creator and leaves a page only the other platform shows", async () => {
    window.localStorage.setItem("chatterly:scope", "model:of-1");
    pathname = "/analytics/fan-reports";
    render(<Providers><PlatformSync /><Probe /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    await waitFor(() => expect(probe()).toBe("onlyfans of-1"));
    otherTabPicks("fansly");
    await waitFor(() => expect(probe()).toBe("fansly all"));
    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/growth/scripts");
  });

  it("keeps a scope until accounts load, then drops it only if the creator is on the other platform", async () => {
    let release!: () => void;
    relayGet.mockImplementation((path: string) =>
      path === "/admin/accounts"
        ? new Promise((r) => { release = () => r({ accounts, active_account_id: null }); })
        : Promise.resolve({}),
    );
    window.localStorage.setItem("chatterly:scope", "model:of-1");
    pathname = "/growth/scripts";
    render(<Providers><PlatformSync /><Probe /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    otherTabPicks("fansly");
    expect(probe()).toBe("fansly of-1");
    await act(async () => release());
    await waitFor(() => expect(probe()).toBe("fansly all"));
    expect(push).not.toHaveBeenCalled();
  });

  it("keeps a scope on an unknown creator and a creator already on the new platform", async () => {
    window.localStorage.setItem("chatterly:scope", "model:fy-1");
    pathname = "/growth/scripts";
    render(<Providers><PlatformSync /><Probe /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    otherTabPicks("fansly");
    await waitFor(() => expect(probe()).toBe("fansly fy-1"));
    accounts = accounts.filter((a) => a.id !== "fy-1");
    await act(async () => { await client.invalidateQueries({ queryKey: ["accounts"] }); });
    otherTabPicks("onlyfans");
    await waitFor(() => expect(probe()).toBe("onlyfans fy-1"));
    expect(push).not.toHaveBeenCalled();
  });
});

describe("Sidebar per platform", () => {
  it("swaps to Fansly's page set and back", async () => {
    render(<Providers><Sidebar /></Providers>);
    const nav = () => screen.getByRole("navigation", { name: "Main" });
    expect(within(nav()).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(within(nav()).queryByRole("button", { name: "Fansly Manager" })).toBeNull();

    act(() => setPlatform("fansly"));
    expect(within(nav()).queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(within(nav()).getByRole("button", { name: "Fansly Manager" })).toBeInTheDocument();
    expect(within(nav()).getAllByRole("link").map((l) => l.textContent)).toEqual(["Scripts", "Message pro", "Vault pro"]);
    expect(within(nav()).getByRole("button", { name: "Creators" })).toBeInTheDocument();

    act(() => setPlatform("onlyfans"));
    expect(within(nav()).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("the rail swaps too", () => {
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
    render(<Providers><Sidebar collapsed /></Providers>);
    expect(screen.getByRole("button", { name: "Platform: Fansly" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fansly Manager" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Vault pro" })).toBeInTheDocument();
  });
});

describe("PlatformGate", () => {
  it("a page only one platform shows switches the shell to it", async () => {
    pathname = "/fansly-manager/home";
    render(<Providers><PlatformSync /><PlatformGate /><Probe /></Providers>);
    await waitFor(() => expect(probe()).toBe("fansly all"));
  });

  it("does not undo a switch made on a shared page", async () => {
    pathname = "/growth/scripts";
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
    render(<Providers><PlatformSync /><PlatformGate /><Probe /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    expect(probe()).toBe("fansly all");
  });

  it("Fansly mode with no live Fansly session prompts the Fansly login, which opens the Fansly paste step", async () => {
    accounts = [{ id: "fy-1", platform: "fansly", has_session: true, session_dead_at: "2026-10-01T00:00:00Z" }];
    pathname = "/growth/scripts";
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
    render(<Providers><PlatformGate /></Providers>);
    const d = await screen.findByRole("dialog", { name: "Fansly Login" });
    expect(d).toHaveTextContent("Please login Fansly");
    fireEvent.click(within(d).getByRole("button", { name: "Log in" }));
    // Never a blank between the two: the prompt stays until the Add creator flow has loaded.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByText("Link Fansly account")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Fansly paste session" })).toBeInTheDocument();
  });

  // PlatformGate loads the Add creator flow with import(); these hold that load, or fail it, until the test says. The
  // module is a stand-in that shows the flow's title.
  const ADD_CREATOR = "@/components/setup/AddCreatorModal";
  afterEach(() => {
    vi.doUnmock(ADD_CREATOR);
  });
  const AddCreatorStandIn = () => <p>Link Fansly account</p>;
  async function holdAddCreator() {
    let release!: () => void;
    let fail!: () => void;
    const gate = new Promise<void>((res, rej) => {
      release = res;
      fail = () => rej(new Error("chunk load failed"));
    });
    gate.catch(() => {}); // the import may not be waiting on it yet when it fails
    vi.doMock(ADD_CREATOR, async () => {
      await gate;
      return { default: AddCreatorStandIn };
    });
    // Applies the queued mock now. vitest applies it on the next import that fetches; the module is cached from
    // the real-flow test, so an import() racing the one that applies it (the preload and Log in) gets the real one.
    await vi.importActual(ADD_CREATOR);
    return { release, fail };
  }
  // Lets every import waiting on the gate land, and React render what it set.
  const settle = async () => {
    await act(async () => {
      await import(ADD_CREATOR).catch(() => {});
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
  };
  const fanslyPrompt = () => {
    accounts = [];
    pathname = "/growth/scripts";
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
  };

  it("Log in, then Cancel before the flow has loaded: the late load opens nothing", async () => {
    const chunk = await holdAddCreator();
    fanslyPrompt();
    render(<Providers><PlatformGate /></Providers>);
    const d = await screen.findByRole("dialog", { name: "Fansly Login" });
    fireEvent.click(within(d).getByRole("button", { name: "Log in" }));
    fireEvent.click(within(d).getByRole("button", { name: "Cancel" }));
    chunk.release();
    await settle();
    expect(screen.queryByText("Link Fansly account")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a failed preload is silent: the prompt shows no error before a Log in", async () => {
    const chunk = await holdAddCreator();
    fanslyPrompt();
    render(<Providers><PlatformGate /></Providers>);
    await screen.findByRole("dialog", { name: "Fansly Login" });
    chunk.fail();
    await settle();
    // The stand-in failed (vitest wraps a mock factory's error), not the real module loaded.
    await expect(import(ADD_CREATOR)).rejects.toHaveProperty("cause.message", "chunk load failed");
    expect(screen.getByRole("dialog", { name: "Fansly Login" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Log in, then Cancel, then the load fails: the next Fansly page's prompt shows no error", async () => {
    const chunk = await holdAddCreator();
    fanslyPrompt();
    const { rerender } = render(<Providers><PlatformGate /></Providers>);
    const d = await screen.findByRole("dialog", { name: "Fansly Login" });
    fireEvent.click(within(d).getByRole("button", { name: "Log in" }));
    fireEvent.click(within(d).getByRole("button", { name: "Cancel" }));
    chunk.fail();
    await settle();
    await expect(import(ADD_CREATOR)).rejects.toHaveProperty("cause.message", "chunk load failed");
    pathname = "/growth/vault-pro";
    rerender(<Providers><PlatformGate /></Providers>);
    expect(await screen.findByRole("dialog", { name: "Fansly Login" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a failed load drops the Log in: the prompt stays, a later load opens nothing unasked, and Log in retries", async () => {
    let chunk = await holdAddCreator();
    fanslyPrompt();
    const { rerender } = render(<Providers><PlatformGate /></Providers>);
    const d = await screen.findByRole("dialog", { name: "Fansly Login" });
    fireEvent.click(within(d).getByRole("button", { name: "Log in" }));
    chunk.fail();
    await settle();
    expect(screen.getByRole("dialog", { name: "Fansly Login" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(LOAD_FAILED_LINE);
    expect(screen.queryByText("Link Fansly account")).toBeNull();

    // Away to a common page and back: the prompt loads the flow again, and that alone opens nothing.
    chunk = await holdAddCreator();
    pathname = "/creators";
    rerender(<Providers><PlatformGate /></Providers>);
    pathname = "/growth/scripts";
    rerender(<Providers><PlatformGate /></Providers>);
    chunk.release();
    await settle();
    expect(screen.queryByText("Link Fansly account")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull(); // a load landed: the error line clears

    fireEvent.click(within(screen.getByRole("dialog", { name: "Fansly Login" })).getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Link Fansly account")).toBeInTheDocument();
  });

  it("Cancel hides the prompt on this page", async () => {
    accounts = [];
    pathname = "/fansly-manager/home";
    render(<Providers><PlatformSync /><PlatformGate /></Providers>);
    const d = await screen.findByRole("dialog", { name: "Fansly Login" });
    fireEvent.click(within(d).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("no prompt with a live Fansly session, in OnlyFans mode, or on a common page", async () => {
    window.localStorage.setItem(PLATFORM_KEY, "fansly");
    pathname = "/growth/scripts";
    const { unmount } = render(<Providers><PlatformGate /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    expect(screen.queryByRole("dialog")).toBeNull();
    unmount();

    accounts = [];
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    pathname = "/creators";
    render(<Providers><PlatformGate /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).toBeNull();
    act(() => setPlatform("onlyfans"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
