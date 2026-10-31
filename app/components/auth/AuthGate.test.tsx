/**
 * AuthGate — /login renders the bare sign-in form for everyone (the public
 * site's Log in and Register links, a signed-in owner adding an account),
 * never the app shell + picker.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import AuthGate from "@/components/auth/AuthGate";
import type { BootStatus } from "@/contexts/userSessionReducer";

let mockPath = "/login";
let mockUser: { user: unknown; boot: BootStatus } = { user: null, boot: "settled" };
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
    mockUser = { user: null, boot: "settled" };
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });

  it("signed in: still the bare form, not the shell", () => {
    mockPath = "/login";
    mockUser = { user: { user_id: "u1", username: "owner" }, boot: "settled" };
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });

  it("still loading: the bare form, no flash of the shell", () => {
    mockPath = "/login";
    mockUser = { user: null, boot: "probing" };
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });
});

describe("AuthGate on /chatter-login", () => {
  it("renders the bare invite page, not the shell, even for a signed-in owner", () => {
    mockPath = "/chatter-login";
    mockUser = { user: { user_id: "u1", username: "owner" }, boot: "settled" };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthGate><div>SHELL</div></AuthGate>
      </QueryClientProvider>,
    );
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Back for another shift?");
  });
});

describe("AuthGate while the principal probes run", () => {
  it("a browser with a session cookie sees the route's skeleton frame, not a blank page", () => {
    mockPath = "/";
    mockUser = { user: null, boot: "probing" };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector("[data-boot-skeleton]")?.getAttribute("data-boot-skeleton")).toBe("dashboard");
  });

  it("a browser without one sees nothing, so a signed-out visitor never sees the app's frame flash", () => {
    mockPath = "/";
    mockUser = { user: null, boot: "probing" };
    const { container } = render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(container.innerHTML).toBe("");
  });

  it("once signed in, the page replaces the skeleton", () => {
    mockPath = "/";
    mockUser = { user: { user_id: "u1", username: "owner" }, boot: "settled" };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.getByText("SHELL")).toBeTruthy();
    expect(document.querySelector("[data-boot-skeleton]")).toBeNull();
  });
});

describe("AuthGate when the boot probe could not reach the relay", () => {
  it("a retry screen, not the sign-in form; Retry re-probes the user and the chatter", () => {
    mockPath = "/";
    mockUser = { user: null, boot: "unreachable" };
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
    mockUser = { user: null, boot: "unreachable" };
    mockChatter = { chatter: { chatter_id: "c1" }, loading: false };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.getByText("SHELL")).toBeTruthy();
  });
});
