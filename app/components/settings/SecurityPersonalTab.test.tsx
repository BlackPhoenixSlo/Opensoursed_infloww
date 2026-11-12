/**
 * SecurityPersonalTab — the Security (personal) Panel (docs/spec/settings-tabs/phase-02-security.md, Seam 2).
 *
 * Rendered inside `UserProvider`, with the relay mocked at `fetch` by URL and `window.location`
 * replaced by a stub, so "Sign out" is asserted on the wire, on the navigation and on the cache
 * `useUser().logout` wipes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { UserProvider } from "@/contexts/UserContext";
import SecurityPersonalTab from "@/components/settings/SecurityPersonalTab";

let fetchMock: ReturnType<typeof vi.fn>;
let replace: ReturnType<typeof vi.fn>;
const realLocation = window.location;

const calls = () =>
  fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body as string | undefined,
  }));

beforeEach(() => {
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
    if (url === "/auth/logout") return jsonRes({ ok: true });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  replace = vi.fn();
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, replace } });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

function mount() {
  return renderWithProviders(
    <UserProvider>
      <SecurityPersonalTab />
    </UserProvider>,
  );
}

describe("SecurityPersonalTab", () => {
  it("names the /auth/me username in the Current session card's tip", async () => {
    mount();
    expect(screen.getByRole("heading", { name: "Security (personal)" })).toBeInTheDocument();
    expect(screen.getByText("Current session")).toBeInTheDocument();
    expect(await screen.findByText("You are signed in as alphaone.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("has no Password card (no password-change route)", () => {
    mount();
    expect(screen.queryByRole("button", { name: "Change password" })).toBeNull();
    expect(screen.queryByText("Password")).toBeNull();
  });

  it("offers Enable 2FA while 2FA is off, and Disable (off while required) once it is on", async () => {
    let status = { enabled: false, enabled_at: null as string | null, recovery_codes_left: 0, required: false };
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
      if (url === "/auth/2fa") return jsonRes(status);
      return jsonRes({ detail: "unmocked" }, 404);
    });
    const { unmount } = mount();
    expect(await screen.findByRole("button", { name: "Enable 2FA" })).toBeEnabled();
    unmount();
    status = { enabled: true, enabled_at: "2026-10-01T00:00:00Z", recovery_codes_left: 7, required: true };
    mount();
    expect(await screen.findByText(/7 backup codes left\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New backup codes" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
  });

  it("Enable 2FA shows the setup key as a QR code and copies the bare key", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const uri = "otpauth://totp/Fasttt:alphaone?secret=OPAA6ENPFLYZCLRG&issuer=Fasttt&digits=6&period=30";
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
      if (url === "/auth/2fa") return jsonRes({ enabled: false, enabled_at: null, recovery_codes_left: 0, required: false });
      if (url === "/auth/2fa/init") return jsonRes({ secret: "OPAA6ENPFLYZCLRG", otpauth_uri: uri, enrol_token: "t" });
      return jsonRes({ detail: "unmocked" }, 404);
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Enable 2FA" }));
    const qr = await screen.findByRole("img", { name: "QR code for your authenticator app" });
    expect(qr.getAttribute("src")).toMatch(/^data:image\/png;base64,/);
    expect(screen.getByLabelText("Setup key")).toHaveTextContent("OPAA 6ENP FLYZ CLRG");
    expect(screen.getByRole("link", { name: "Open in authenticator app" })).toHaveAttribute("href", uri);
    fireEvent.click(screen.getByRole("button", { name: "Copy setup key" }));
    expect(writeText).toHaveBeenCalledWith("OPAA6ENPFLYZCLRG");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("Log out other sessions posts to /auth/sessions/revoke-others and says so", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
      if (url === "/auth/sessions/revoke-others") return jsonRes({ ok: true });
      return jsonRes({ detail: "unmocked" }, 404);
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Log out other sessions" }));
    expect(await screen.findByText(/Every other session is signed out/)).toBeInTheDocument();
    expect(calls().filter((c) => c.method !== "GET").map((c) => c.url)).toEqual(["/auth/sessions/revoke-others"]);
  });

  it("Sign out posts {} to /auth/logout once, wipes the query cache and replaces the page with /", async () => {
    const { queryClient } = mount();
    await screen.findByText("You are signed in as alphaone.");
    // The test client's gcTime is 0, which would empty the cache on its own; this key is kept
    // until something clears it, so "empty" below can only come from logout's cache wipe.
    queryClient.setQueryDefaults(["employees", "all"], { gcTime: Infinity });
    queryClient.setQueryData(["employees", "all"], [{ id: 1, display_name: "Alpha One" }]);
    await new Promise((r) => setTimeout(r, 20));
    expect(queryClient.getQueryCache().getAll().map((q) => q.queryKey)).toContainEqual(["employees", "all"]);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(replace).toHaveBeenCalledTimes(1);
    expect(calls().filter((c) => c.method !== "GET")).toEqual([
      { method: "POST", url: "/auth/logout", body: "{}" },
    ]);
    // The still-mounted 2FA card may re-read its status after the wipe; nothing else survives it.
    expect(queryClient.getQueryCache().getAll().map((q) => q.queryKey).filter((k) => k[0] !== "auth")).toEqual([]);
    expect(calls().filter((c) => c.url.includes("/admin/settings/"))).toEqual([]);
  });

  it("disables Sign out while the POST is in flight", async () => {
    let release: (r: Response) => void = () => {};
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
      return new Promise<Response>((r) => { release = r; });
    });
    mount();
    const b = screen.getByRole("button", { name: "Sign out" });
    expect(b).toBeEnabled();
    fireEvent.click(b);
    await waitFor(() => expect(b).toBeDisabled());
    release(jsonRes({ ok: true }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });
});
