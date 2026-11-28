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
let chatterOnly = false;
const chatter = { chatter_id: "c1" };
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: chatterOnly ? null : owner, loading: false, logout: vi.fn() }),
  useOptionalUser: () => ({ user: chatterOnly ? null : owner }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: chatterOnly ? chatter : null }),
  useOptionalChatter: () => ({ chatter: chatterOnly ? chatter : null }),
}));
let counts: Record<string, { unread: number; owe_reply: number }> = {};
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCounts: () => counts }));
vi.mock("@/lib/appliedSettings", () => ({ useAppliedSettings: () => ({ data: undefined }) }));
// ScopeProvider pushes its scope to the SSE bus.
vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {}, onStreamState: () => () => {} } }));

import PlatformGate, { LOAD_FAILED_LINE, PlatformSync } from "@/components/shell/PlatformGate";
import PlatformSwitcher, { platformUnread } from "@/components/shell/PlatformSwitcher";
import Sidebar from "@/components/shell/Sidebar";
import { ScopeProvider, useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { PLATFORMS, PLATFORM_KEY, resetPlatformForTests, setPlatform, usePlatform } from "@/lib/platform";
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
  chatterOnly = false;
  push.mockReset();
  counts = {};
  accounts = [
    { id: "of-1", nickname: "Oscar", platform: "onlyfans", has_session: true },
    { id: "of-2", nickname: "Olive", has_session: true },
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

  it.each([
    [25, "27"],
    [120, "99+"],
  ])("a platform's sum is the exact count, never \"N+\" (%i + 2 → %s)", async (n, chip) => {
    counts = { "of-1": { unread: n, owe_reply: 0 }, "of-2": { unread: 2, owe_reply: 1 } };
    render(<Providers><PlatformSwitcher /></Providers>);
    await waitFor(() => expect(screen.getByTestId("platform-unread-dot")).toBeInTheDocument());
    fireEvent.click(trigger());
    expect(row("OnlyFans").textContent).toBe(`OnlyFans${chip}`);
    expect(within(row("OnlyFans")).getByLabelText(`${n + 2} unread`)).toBeInTheDocument();
  });

  it("builds one unread bucket per Platform table row", () => {
    expect(Object.keys(platformUnread(undefined, {}))).toEqual(PLATFORMS.map((p) => p.key));
  });

  it("counts an account with an unknown platform (mym) as OnlyFans", () => {
    const out = platformUnread([{ id: "x-1", platform: "mym", has_session: true }], { "x-1": { unread: 4, owe_reply: 0 } });
    expect(out).toEqual({ onlyfans: { count: 4 }, fansly: { count: 0 } });
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

describe("PlatformSync: the scope fix-up stays in memory, so Messages Pro keeps its saved Creator", () => {
  const SCOPE_KEY = "chatterly:scope";
  const cookie = () => document.cookie.match(/(?:^|; )chatterly_scope=([^;]*)/)?.[1];
  afterEach(() => { document.cookie = "chatterly_scope=; path=/; max-age=0"; });

  it("waits for a delayed chatter roster before dropping a foreign saved Creator", async () => {
    chatterOnly = true;
    localStorage.setItem(SCOPE_KEY, "model:fy-1");
    let answer!: (response: Response) => void;
    const roster = new Promise<Response>((resolve) => { answer = resolve; });
    const fetch = vi.fn(() => roster);
    vi.stubGlobal("fetch", fetch);
    try {
      render(<Providers><PlatformSync /><Probe /></Providers>);
      await waitFor(() => expect(fetch).toHaveBeenCalledWith("/chatter/me/accounts", expect.anything()));
      expect(probe()).toBe("onlyfans fy-1");
      answer(Response.json([{ account_id: "fy-1", platform: "fansly" }]));
      await waitFor(() => expect(probe()).toBe("onlyfans all"));
      expect(localStorage.getItem(SCOPE_KEY)).toBe("model:fy-1");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it.each([["fetched", false], ["already cached", true]])("on load (accounts %s), a saved Creator from the other Platform drops to All; the saved scope and the boot cookie keep their value", async (_, cached) => {
    if (cached) client.setQueryData(["accounts", "u1"], { accounts, active_account_id: null });
    window.localStorage.setItem(SCOPE_KEY, "model:fy-1");
    pathname = "/growth/scripts";
    render(<Providers><PlatformSync /><Probe /></Providers>);
    await waitFor(() => expect(cookie()).toBe("model"));
    await waitFor(() => expect(probe()).toBe("onlyfans all"));
    expect(window.localStorage.getItem(SCOPE_KEY)).toBe("model:fy-1");
    expect(cookie()).toBe("model");
  });

  it.each([
    ["the selector", () => { fireEvent.click(screen.getByRole("button", { name: /OnlyFans/ })); fireEvent.click(screen.getByRole("menuitemradio", { name: /^Fansly/ })); }],
    ["another tab", () => act(() => {
      window.localStorage.setItem(PLATFORM_KEY, "fansly");
      window.dispatchEvent(new StorageEvent("storage", { key: PLATFORM_KEY, newValue: "fansly" }));
    })],
  ])("on a switch from %s, a Creator from the other Platform drops to All without a write", async (_, pick) => {
    window.localStorage.setItem(SCOPE_KEY, "model:of-1");
    pathname = "/growth/scripts";
    render(<Providers><PlatformSync /><PlatformSwitcher /><Probe /></Providers>);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
    await waitFor(() => expect(probe()).toBe("onlyfans of-1"));
    pick();
    await waitFor(() => expect(probe()).toBe("fansly all"));
    expect(window.localStorage.getItem(SCOPE_KEY)).toBe("model:of-1");
    expect(cookie()).toBe("model");
  });

  it("OnlyFans only: a saved OnlyFans Creator stays on load and nothing is written", async () => {
    accounts = accounts.filter((a) => a.platform !== "fansly");
    window.localStorage.setItem(SCOPE_KEY, "model:of-2");
    pathname = "/of-manager/new-post";
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    try {
      render(<Providers><PlatformSync /><Probe /></Providers>);
      await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/accounts"));
      await act(async () => { await client.refetchQueries({ queryKey: ["accounts"] }); });
      expect(probe()).toBe("onlyfans of-2");
      expect(setItem).not.toHaveBeenCalled();
      expect(cookie()).toBe("model");
    } finally {
      setItem.mockRestore();
    }
  });
});

describe("Sidebar per platform", () => {
  it("swaps to Fansly's page set and back (Fansly Manager on by default)", async () => {
    render(<Providers><Sidebar /></Providers>);
    const nav = () => screen.getByRole("navigation", { name: "Main" });
    expect(within(nav()).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(within(nav()).queryByRole("button", { name: "Fansly Manager" })).toBeNull();

    act(() => setPlatform("fansly"));
    expect(within(nav()).queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(within(nav()).getByRole("button", { name: "Fansly Manager" })).toBeInTheDocument();
    expect(within(nav()).getAllByRole("link").map((l) => l.textContent)).toEqual(expect.arrayContaining(["Scripts", "Message pro", "Vault pro"]));
    expect(within(nav()).getByRole("button", { name: "Creators" })).toBeInTheDocument();

    act(() => setPlatform("onlyfans"));
    expect(within(nav()).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("a build without the Fansly mirror has no Fansly Manager group", () => {
    vi.stubEnv("NEXT_PUBLIC_FANSLY_MIRROR_ABSENT", "1");
    try {
      window.localStorage.setItem(PLATFORM_KEY, "fansly");
      render(<Providers><Sidebar /></Providers>);
      const nav = screen.getByRole("navigation", { name: "Main" });
      expect(within(nav).queryByRole("button", { name: "Fansly Manager" })).toBeNull();
      expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(["Scripts", "Message pro", "Vault pro"]);
    } finally {
      vi.unstubAllEnvs();
    }
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
    pathname = "/fansly-manager/lists";
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
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Fansly paste session" })).toBeInTheDocument();
  });

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
    gate.catch(() => {});
    vi.doMock(ADD_CREATOR, async () => {
      await gate;
      return { default: AddCreatorStandIn };
    });
    await vi.importActual(ADD_CREATOR);
    return { release, fail };
  }
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

    chunk = await holdAddCreator();
    pathname = "/creators";
    rerender(<Providers><PlatformGate /></Providers>);
    pathname = "/growth/scripts";
    rerender(<Providers><PlatformGate /></Providers>);
    chunk.release();
    await settle();
    expect(screen.queryByText("Link Fansly account")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(within(screen.getByRole("dialog", { name: "Fansly Login" })).getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Link Fansly account")).toBeInTheDocument();
  });

  it("Cancel hides the prompt on this page", async () => {
    accounts = [];
    pathname = "/fansly-manager/lists";
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
