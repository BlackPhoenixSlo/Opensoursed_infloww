/**
 * AuthGate — /login renders the bare sign-in form for everyone (the public
 * site's Log in and Register links, a signed-in owner adding an account),
 * never the app shell + picker.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import AuthGate from "@/components/auth/AuthGate";

let mockPath = "/login";
let mockUser: { user: unknown; loading: boolean } = { user: null, loading: false };
const mockChatter: { chatter: unknown; loading: boolean } = { chatter: null, loading: false };
vi.mock("next/navigation", () => ({
  usePathname: () => mockPath,
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ ...mockUser, login: vi.fn(), register: vi.fn(), clearUserLocally: vi.fn() }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ ...mockChatter, login: vi.fn() }),
}));

afterEach(cleanup);

describe("AuthGate on /login", () => {
  it("signed out: the bare form, not the shell", () => {
    mockPath = "/login";
    mockUser = { user: null, loading: false };
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });

  it("signed in: still the bare form, not the shell", () => {
    mockPath = "/login";
    mockUser = { user: { user_id: "u1", username: "owner" }, loading: false };
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });

  it("still loading: the bare form, no flash of the shell", () => {
    mockPath = "/login";
    mockUser = { user: null, loading: true };
    render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
  });
});

describe("AuthGate on /chatter-login", () => {
  it("renders the bare invite page, not the shell, even for a signed-in owner", () => {
    mockPath = "/chatter-login";
    mockUser = { user: { user_id: "u1", username: "owner" }, loading: false };
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
    mockUser = { user: null, loading: true };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.queryByText("SHELL")).toBeNull();
    expect(document.querySelector("[data-boot-skeleton]")?.getAttribute("data-boot-skeleton")).toBe("dashboard");
  });

  it("a browser without one sees nothing, so a signed-out visitor never sees the app's frame flash", () => {
    mockPath = "/";
    mockUser = { user: null, loading: true };
    const { container } = render(<AuthGate><div>SHELL</div></AuthGate>);
    expect(container.innerHTML).toBe("");
  });

  it("once signed in, the page replaces the skeleton", () => {
    mockPath = "/";
    mockUser = { user: { user_id: "u1", username: "owner" }, loading: false };
    render(<AuthGate signedIn><div>SHELL</div></AuthGate>);
    expect(screen.getByText("SHELL")).toBeTruthy();
    expect(document.querySelector("[data-boot-skeleton]")).toBeNull();
  });
});
