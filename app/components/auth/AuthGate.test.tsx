/**
 * AuthGate — /login renders the bare sign-in form for everyone (the public
 * site's Log in and Register links, a signed-in owner adding an account),
 * never the app shell + picker.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import AuthGate from "@/components/auth/AuthGate";
import { forgetScope, rememberScope } from "@/lib/screenEntry";
import type { AuthBanner, BootStatus } from "@/contexts/userSessionReducer";

let mockPath = "/login";
type MockUser = { user: unknown; boot: BootStatus; banner: AuthBanner | null; formUp: boolean };
/** A session as useUser gives it: no banner by default; a banner puts the form up. */
const me = (s: Pick<MockUser, "user" | "boot"> & Partial<MockUser>): MockUser => ({ banner: null, formUp: !!s.banner, ...s });
let mockUser: MockUser = me({ user: null, boot: "settled" });
let mockChatter: { chatter: unknown; loading: boolean } = { chatter: null, loading: false };
const mockRetry = vi.fn();
const mockReprobe = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => mockPath,
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ ...mockUser, login: vi.fn(), register: vi.fn(), clearUserLocally: vi.fn(), retry: mockRetry }),
}));
const mockPrefetch = vi.fn();
vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()), prefetchScreenBundle: (s: unknown) => mockPrefetch(s),
}));
vi.mock("@/lib/twoFactor", async (orig) => ({
  ...(await orig<typeof import("@/lib/twoFactor")>()), signIn: async () => "user",
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ ...mockChatter, login: vi.fn(), reprobe: mockReprobe }),
}));

beforeEach(() => {
  mockChatter = { chatter: null, loading: false };
  mockRetry.mockClear();
  mockReprobe.mockClear();
});
afterEach(cleanup);

describe("AuthGate on /login", () => {
  it("signed out: the bare form, not the shell", () => {
    mockPath = "/login";
    mockUser = me({ user: null, boot: "settled" });
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });

  it("signed in: still the bare form, not the shell", () => {
    mockPath = "/login";
    mockUser = me({ user: { user_id: "u1", username: "owner" }, boot: "settled" });
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });

  it("still loading: the bare form, no flash of the shell", () => {
    mockPath = "/login";
    mockUser = me({ user: null, boot: "probing" });
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });
});

describe("AuthGate on /chatter-login", () => {
  it("renders the bare invite page, not the shell, even for a signed-in owner", async () => {
    mockPath = "/chatter-login";
    mockUser = me({ user: { user_id: "u1", username: "owner" }, boot: "settled" });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthGate><div>SHELL</div></AuthGate>
      </QueryClientProvider>,
    );
    expect(screen.queryByText("SHELL")).toBeNull();
    // Its own chunk (next/dynamic; the server-rendered page preloads it).
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Back for another shift?");
  });
});

describe("AuthGate while the principal probes run", () => {
  it("a browser with a session cookie sees the route's skeleton frame, not a blank page", () => {
    mockPath = "/";
    mockUser = me({ user: null, boot: "probing" });
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector("[data-boot-skeleton]")?.getAttribute("data-boot-skeleton")).toBe("dashboard");
  });

  it("a browser without one sees nothing, so a signed-out visitor never sees the app's frame flash", () => {
    mockPath = "/";
    mockUser = me({ user: null, boot: "probing" });
    const { container } = render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(container.innerHTML).toBe("");
  });

  it("once signed in, the page replaces the skeleton", () => {
    mockPath = "/";
    mockUser = me({ user: { user_id: "u1", username: "owner" }, boot: "settled" });
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.getByText("SHELL")).toBeTruthy();
    expect(document.querySelector("[data-boot-skeleton]")).toBeNull();
  });
});

describe("AuthGate when the boot probe could not reach the relay", () => {
  it("a retry screen, not the sign-in form; Retry re-probes the user and the chatter", () => {
    mockPath = "/";
    mockUser = me({ user: null, boot: "unreachable" });
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')).toBeNull();
    expect(document.querySelector("[data-auth-unreachable]")).toBeTruthy();
    screen.getByRole("button", { name: "Retry" }).click();
    expect(mockRetry).toHaveBeenCalledTimes(1);
    expect(mockReprobe).toHaveBeenCalledTimes(1);
  });

  it("a signed-in chatter still gets the shell", () => {
    mockPath = "/";
    mockUser = me({ user: null, boot: "unreachable" });
    mockChatter = { chatter: { chatter_id: "c1" }, loading: false };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.getByText("SHELL")).toBeTruthy();
  });
});

describe("AuthGate with a banner: the sign-in form at once", () => {
  const usernameInput = () => document.querySelector<HTMLInputElement>('input[autocomplete="username"]')!;

  it.each<[AuthBanner, BootStatus, string]>([
    ["blocked", "unreachable", "Proxy blocked (403)"],
    ["blocked", "probing", "Proxy blocked (403)"],
    ["slow", "probing", "Relay not answering"],
    ["slow", "unreachable", "Relay not answering"],
  ])("%s (%s): the form under a status banner, even while the chatter probe runs", (banner, boot, text) => {
    mockPath = "/";
    mockUser = me({ user: null, boot, banner });
    mockChatter = { chatter: null, loading: true };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    const el = document.querySelector("[data-auth-blocked]")!;
    expect(el.getAttribute("role")).toBe("status");
    expect(el.textContent).toBe(`${text}—Retry`);
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
    expect(document.querySelector("[data-auth-unreachable]")).toBeNull();
    expect(screen.queryByText("SHELL")).toBeNull();
  });

  it("Retry re-probes the user only and the form stays mounted (typed username kept) as the banner goes", () => {
    mockPath = "/";
    mockUser = me({ user: null, boot: "unreachable", banner: "blocked" });
    const { rerender } = render(<AuthGate><div>SHELL</div></AuthGate>);
    fireEvent.change(usernameInput(), { target: { value: "typed.name" } });
    screen.getByRole("button", { name: "Retry" }).click();
    expect(mockRetry).toHaveBeenCalledTimes(1);
    expect(mockReprobe).not.toHaveBeenCalled();
    mockUser = me({ user: null, boot: "probing", banner: "blocked" });
    rerender(<AuthGate><div>SHELL</div></AuthGate>);
    expect(usernameInput().value).toBe("typed.name");
    // its probe still in flight: Retry is off (that answer is applied when it comes)
    expect(screen.getByRole("button", { name: "Retry" }).hasAttribute("disabled")).toBe(true);
    // a late null/401 settles the boot: the banner goes, the form stays up even while the chatter probe hangs
    mockUser = me({ user: null, boot: "settled", banner: null, formUp: true });
    mockChatter = { chatter: null, loading: true };
    rerender(<AuthGate><div>SHELL</div></AuthGate>);
    expect(document.querySelector("[data-auth-blocked]")).toBeNull();
    expect(usernameInput().value).toBe("typed.name");
  });

  it("a late signed-in answer replaces the form with the shell", () => {
    mockPath = "/";
    mockUser = me({ user: null, boot: "probing", banner: "slow" });
    const { rerender } = render(<AuthGate><div>SHELL</div></AuthGate>);
    mockUser = me({ user: { user_id: "u1", username: "owner" }, boot: "settled", banner: null, formUp: true });
    mockChatter = { chatter: null, loading: true };
    rerender(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.getByText("SHELL")).toBeTruthy();
    expect(document.querySelector("[data-auth-blocked]")).toBeNull();
  });
});

describe("AuthGate on a document load of Messages Pro: the inbox bundle with the probes", () => {
  afterEach(() => {
    forgetScope();
    window.history.replaceState(null, "", "/");
    mockPrefetch.mockClear();
  });

  it.each([
    { name: "All Models saved: started", saved: false, started: true },
    { name: "nothing saved: started", saved: null, started: true },
    { name: "one Creator saved: none (the page reads that Creator's own routes)", saved: true, started: false },
  ])("$name", ({ saved, started }) => {
    mockPath = "/messages-pro";
    mockUser = me({ user: null, boot: "probing" });
    window.history.replaceState(null, "", "/messages-pro");
    if (saved != null) rememberScope(saved);
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(mockPrefetch.mock.calls).toEqual(started ? [[{ kind: "inbox", cursor: 0 }]] : []);
  });
});

describe("AuthGate signed out on an Ultra plan page (an MCP client's open_url)", () => {
  it.each([
    ["/ultra/plans/0123abcd", "/ultra/plans/0123abcd"],
    ["/growth/vault-pro", "/"],  // any other page: Landing's default, the Dashboard
  ])("the in-place sign-in on %s lands on %s", async (path, want) => {
    mockPath = path;
    mockUser = me({ user: null, boot: "settled" });
    const realLocation = window.location;
    const replace = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, replace } });
    try {
      render(<AuthGate><div>SHELL</div></AuthGate>);
      expect(screen.queryByText("SHELL")).toBeNull();
      fireEvent.change(document.querySelector('input[autocomplete="username"]')!, { target: { value: "ann" } });
      fireEvent.change(document.querySelector('input[type="password"]')!, { target: { value: "secret-pw" } });
      fireEvent.submit(document.querySelector("form")!);
      await vi.waitFor(() => expect(replace).toHaveBeenCalledWith(want));
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: realLocation });
    }
  });
});
