import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const nav = vi.hoisted(() => ({ path: "/of-manager/new-post" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.path,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {}, onStreamState: () => () => {} } }));
vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q, addEventListener: () => {}, removeEventListener: () => {} }));
vi.mock("@/components/ui/AccountAvatarPicture", () => ({ AccountAvatarPicture: () => null }));
vi.mock("@/contexts/UserContext", () => { const v = () => ({ user: { user_id: "owner-1" } }); return { useUser: v, useOptionalUser: v }; });
vi.mock("@/contexts/ChatterContext", () => { const v = () => ({ chatter: null }); return { useChatter: v, useOptionalChatter: v }; });
vi.mock("@/components/shell/useGrantedPages", () => ({ useGrantedPages: () => null }));
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCounts: () => ({}) }));
type Row = { id: string; nickname: string; has_session: boolean; platform?: "onlyfans" | "fansly"; session_dead_at?: string };
let accounts: Row[] = [];
const watchers = [{ id: "w-1", nickname: "Company Account", has_session: true }];
vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: {
    get: vi.fn(async (path: string) => (path === "/admin/accounts" ? { accounts, active_account_id: null, watchers } : {})),
  },
}));

import { PlatformSync } from "@/components/shell/PlatformGate";
import { ScopeProvider, useScope } from "@/contexts/ScopeContext";
import { useStandIn } from "@/lib/ofMirrorProfile";
import { PLATFORM_KEY, resetPlatformForTests } from "@/lib/platform";
import { OfManagerChrome } from "./OfManagerChrome";

const FANSLY = { id: "900539700124344320", nickname: "Nova Reyes", has_session: true, platform: "fansly" } as const;
const OF_DEAD = { id: "of-1", nickname: "Oscar", has_session: true, platform: "onlyfans", session_dead_at: "x" } as const;
const OF_LIVE = { id: "of-2", nickname: "Olive", has_session: true } as const;

const seen: (string | null)[] = [];
function Frame() {
  seen.push(useScope().accountId);
  return <p data-testid="stand-in">{useStandIn("/of-mirror/pages/new-post/index.html") ?? "none"}</p>;
}

function newPost(search = "", cached = false, sync = true) {
  window.history.replaceState(null, "", `/of-manager/new-post${search}`);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (cached) {
    const all = accounts.map((a) => ({ ...a, is_active: true }));
    client.setQueryData(["accounts", "owner-1"], { accounts: all, active_account_id: null, watchers: watchers.map((w) => ({ ...w, is_active: true, role: "watcher" })) });
  }
  render(
    <QueryClientProvider client={client}>
      <ScopeProvider>
        {sync && <PlatformSync />}
        <OfManagerChrome><Frame /></OfManagerChrome>
      </ScopeProvider>
    </QueryClientProvider>,
  );
}
const column = () => screen.getAllByTestId("of-creator-row").map((r) => r.getAttribute("title"));
const current = () => screen.getAllByTestId("of-creator-row").find((r) => r.getAttribute("aria-current") === "true")?.getAttribute("title");
const phoneSelect = () => {
  fireEvent.click(screen.getByRole("combobox", { name: "Creator" }));
  const names = screen.getAllByRole("option").map((o) => o.textContent);
  fireEvent.click(screen.getByRole("combobox", { name: "Creator" }));
  return names;
};

beforeEach(() => {
  localStorage.clear();
  resetPlatformForTests();
  nav.path = "/of-manager/new-post";
  seen.length = 0;
});
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("Post handoff: New post from Messages Pro lists only OnlyFans Creators", () => {
  it.each(["onlyfans", "fansly"] as const)(
    "with a Fansly Creator saved in Messages Pro (switch was %s): OnlyFans column, phone select and stand-in; the saved scope stays",
    async (was) => {
      accounts = [FANSLY, OF_DEAD, OF_LIVE];
      localStorage.setItem(PLATFORM_KEY, was);
      localStorage.setItem("chatterly:scope", `model:${FANSLY.id}`);
      newPost();
      await waitFor(() => expect(current()).toBe("Olive"));
      expect(column()).toEqual(["Oscar · Disconnected", "Olive", "Company Account"]);
      expect(screen.getByTestId("stand-in")).toHaveTextContent("of-2");
      expect(phoneSelect()).toEqual(["Oscar", "Olive", "Company Account (watcher)"]);
      expect(localStorage.getItem("chatterly:scope")).toBe(`model:${FANSLY.id}`);
    },
  );

  it("shows no New Post stand-in when only the switch Platform has creators", () => {
    accounts = [FANSLY];
    localStorage.setItem(PLATFORM_KEY, "fansly");
    localStorage.setItem("chatterly:scope", "all");
    newPost("", true, false);
    expect(screen.getByTestId("stand-in")).toHaveTextContent("none");
  });

  it.each(["onlyfans", "fansly"] as const)("`?account=<fansly id>` is not applied (switch was %s)", async (was) => {
    accounts = [FANSLY, OF_DEAD, OF_LIVE];
    localStorage.setItem(PLATFORM_KEY, was);
    newPost(`?account=${FANSLY.id}`);
    await waitFor(() => expect(current()).toBe("Olive"));
    await new Promise((r) => setTimeout(r, 20));
    expect(current()).toBe("Olive");
    expect(screen.getByTestId("stand-in")).toHaveTextContent("of-2");
  });

  it("storage says Fansly and the accounts are cached: an OnlyFans `?account=` is applied (the route's Platform decides)", async () => {
    accounts = [FANSLY, OF_DEAD, OF_LIVE];
    localStorage.setItem(PLATFORM_KEY, "fansly");
    newPost("?account=of-1", true);
    await waitFor(() => expect(current()).toBe("Oscar · Disconnected"));
    await new Promise((r) => setTimeout(r, 20));
    expect(current()).toBe("Oscar · Disconnected");
  });

  it("a saved Fansly Creator with the roster known: the page never reads as her, even before PlatformSync drops the scope", async () => {
    accounts = [FANSLY, OF_DEAD, OF_LIVE];
    localStorage.setItem("chatterly:scope", `model:${FANSLY.id}`);
    newPost("", true, false);
    await waitFor(() => expect(screen.getByTestId("stand-in")).toHaveTextContent("of-2"));
    expect(seen).not.toContain(FANSLY.id);
    expect(seen.at(-1)).toBe("of-2");
  });

  it("on a path no Platform owns, `?account=<fansly id>` is still not applied", async () => {
    accounts = [FANSLY, OF_DEAD, OF_LIVE];
    nav.path = "/of-manager-unlisted";
    newPost(`?account=${FANSLY.id}`, true, false);
    await waitFor(() => expect(current()).toBe("Olive"));
    await new Promise((r) => setTimeout(r, 20));
    expect(current()).toBe("Olive");
  });

  it.each([false, true])("`?account=<fansly id>` is not applied with the switch on Fansly (accounts cached: %s)", async (cached) => {
    accounts = [FANSLY, OF_DEAD, OF_LIVE];
    localStorage.setItem(PLATFORM_KEY, "fansly");
    newPost(`?account=${FANSLY.id}`, cached);
    await waitFor(() => expect(current()).toBe("Olive"));
    await new Promise((r) => setTimeout(r, 20));
    expect(current()).toBe("Olive");
  });

  it("OnlyFans only: every active Creator and the watcher listed, `?account=` applied, the stand-in the first live one", async () => {
    accounts = [OF_DEAD, OF_LIVE];
    newPost();
    await waitFor(() => expect(current()).toBe("Olive"));
    expect(screen.getByTestId("stand-in")).toHaveTextContent("of-2");
    expect(column()).toEqual(["Oscar · Disconnected", "Olive", "Company Account"]);
    expect(phoneSelect()).toEqual(["Oscar", "Olive", "Company Account (watcher)"]);
    cleanup();
    localStorage.setItem("chatterly:scope", "model:of-2");
    newPost("?account=of-1");
    await waitFor(() => expect(current()).toBe("Oscar · Disconnected"));
    expect(localStorage.getItem("chatterly:scope")).toBe("model:of-2");
  });
});
