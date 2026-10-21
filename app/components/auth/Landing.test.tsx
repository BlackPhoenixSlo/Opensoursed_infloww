/**
 * Landing — the public site sends visitors here as /login?mode=register and
 * /login?username=<u>: the form opens on the right tab, prefills the username,
 * focuses the password, and links back to the site.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import Landing from "@/components/auth/Landing";
import { SITE_URL } from "@/lib/site";
import { RelayError } from "@/lib/relay";
import { TwoFactorRequired } from "@/lib/twoFactor";

let mockQuery = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mockQuery),
}));
// What POST /auth/sign-in does; each case sets it, the default signs an owner in.
let signInImpl: (u: string, p: string) => Promise<unknown> = async () => "user";
const signInCalls: [string, string][] = [];
const clearUserLocally = vi.fn();
vi.mock("@/lib/twoFactor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/twoFactor")>()),
  signIn: (u: string, p: string) => { signInCalls.push([u, p]); return signInImpl(u, p); },
}));
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ register: vi.fn(), clearUserLocally }),
}));

afterEach(() => {
  cleanup();
  signInImpl = async () => "user";
  signInCalls.length = 0;
  clearUserLocally.mockReset();
});

function signIn() {
  fireEvent.change(document.querySelector('input[autocomplete="username"]')!, { target: { value: "ann" } });
  fireEvent.change(document.querySelector('input[type="password"]')!, { target: { value: "secret-pw" } });
  fireEvent.submit(document.querySelector("form")!);
}

describe("Landing typed sign-in refusals", () => {
  it("signs in with one request and starts the app over as the new principal", async () => {
    mockQuery = "";
    render(<Landing />);
    signIn();
    await vi.waitFor(() => expect(clearUserLocally).toHaveBeenCalledTimes(1));
    expect(signInCalls).toEqual([["ann", "secret-pw"]]);
  });

  it("a wrong password is one request and shows the Relay's words", async () => {
    mockQuery = "";
    signInImpl = async () => { throw new RelayError(401, { detail: "invalid username or password" }, "invalid username or password"); };
    render(<Landing />);
    signIn();
    expect(await screen.findByText("invalid username or password")).toBeInTheDocument();
    expect(signInCalls).toHaveLength(1);
    expect(clearUserLocally).not.toHaveBeenCalled();
  });

  it("a deactivated employee gets the reason in a banner, and can start over", async () => {
    mockQuery = "";
    const detail = { code: "account_deactivated", message: "Your account has been deactivated." };
    signInImpl = async () => { throw new RelayError(403, { detail }, detail.message); };
    render(<Landing />);
    signIn();
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Account deactivated");
    expect(banner).toHaveTextContent("Your account has been deactivated.");
    fireEvent.click(screen.getByRole("button", { name: "Sign in with another account" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect((document.querySelector('input[autocomplete="username"]') as HTMLInputElement).value).toBe("");
  });

  it("a 2FA challenge swaps the password form for the code step", async () => {
    mockQuery = "";
    signInImpl = async () => { throw new TwoFactorRequired({ two_factor: "verify", ticket: "t", username: "ann" }); };
    render(<Landing />);
    signIn();
    expect(await screen.findByLabelText("Verification code")).toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });
});

describe("Landing mode from the URL", () => {
  it("opens on Sign in by default, with a Sign up link instead of a switch", () => {
    mockQuery = "";
    render(<Landing />);
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Login");
    expect(document.querySelector("[aria-pressed]:not([aria-controls])")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sign up" }));
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Create account");
  });

  it("shows Remember me and Forgot password? on Sign in only", () => {
    mockQuery = "";
    render(<Landing />);
    expect(screen.getByText(/Remember me/)).toBeTruthy();
    expect(document.querySelector("summary")?.textContent).toBe("Forgot password?");
    cleanup();
    mockQuery = "mode=register";
    render(<Landing />);
    expect(screen.queryByText(/Remember me/)).toBeNull();
    expect(document.querySelector("summary")).toBeNull();
  });

  it("opens on Register for ?mode=register", () => {
    mockQuery = "mode=register";
    render(<Landing />);
    const submit = document.querySelector('button[type="submit"]');
    expect(submit?.textContent).toBe("Create account");
  });
});

describe("Landing hand-off from the public site", () => {
  it("prefills the username from ?username= and focuses the password", () => {
    mockQuery = "username=alice";
    render(<Landing />);
    const user = document.querySelector('input[autocomplete="username"]') as HTMLInputElement;
    const pass = document.querySelector('input[type="password"]');
    expect(user.value).toBe("alice");
    expect(document.activeElement).toBe(pass);
  });

  it("keeps the register tab with ?mode=register&username=", () => {
    mockQuery = "mode=register&username=bob";
    render(<Landing />);
    const user = document.querySelector('input[autocomplete="username"]') as HTMLInputElement;
    expect(user.value).toBe("bob");
    expect(document.querySelector('button[type="submit"]')?.textContent).toBe("Create account");
  });

  it("does not steal focus without a username", () => {
    mockQuery = "";
    render(<Landing />);
    const user = document.querySelector('input[autocomplete="username"]') as HTMLInputElement;
    expect(user.value).toBe("");
    expect(document.activeElement).not.toBe(document.querySelector('input[type="password"]'));
  });

  it("links back to the site", () => {
    mockQuery = "";
    render(<Landing />);
    const back = screen.getByRole("link", { name: /back to the site/i });
    expect(back.getAttribute("href")).toBe(SITE_URL);
  });
});

describe("Landing desktop app link", () => {
  const shell = window as Window & { fasttShell?: { isDesktop: boolean } };
  afterEach(() => {
    delete shell.fasttShell;
  });

  it.each(["", "mode=register"])("links to /download on the web (%s)", (q) => {
    mockQuery = q;
    render(<Landing />);
    const link = screen.getByRole("link", { name: "Download the desktop app" });
    expect(link).toHaveAttribute("href", "/download");
    expect(link).not.toHaveAttribute("target");
  });

  it.each(["", "mode=register"])("leaves it out inside the desktop app (%s)", (q) => {
    mockQuery = q;
    shell.fasttShell = { isDesktop: true };
    render(<Landing />);
    expect(document.querySelector('a[href="/download"]')).toBeNull();
  });
});
