/**
 * SecurityOrgTab — the Security (organization) Panel (docs/spec/settings-tabs/phase-02-security.md, Seam 1).
 *
 * Rendered inside `UserProvider`, with the relay mocked at `fetch` by URL: `/auth/me` is a synthetic
 * owner, `/admin/employees` the roster and `/admin/settings/security` the `security` blob, so every
 * write is an assertion about the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { UserProvider } from "@/contexts/UserContext";
import SecurityOrgTab from "@/components/settings/SecurityOrgTab";

const ROSTER = {
  employees: [
    { id: 1, display_name: "Alpha One", color: "#a78bfa", is_active: true, chatter_id: "c1",
      two_factor: true, last_login_at: "2026-10-01T10:00:00Z" },
    { id: 2, display_name: "Beta Two", color: "#60a5fa", is_active: true, chatter_id: "c2",
      two_factor: false, last_login_at: null },
    { id: 3, display_name: "Gamma Three", color: "#34d399", is_active: false, chatter_id: "c3" },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET /admin/employees answers. */
let rosterReply: () => Response;
let stored: Record<string, unknown>;

const calls = () =>
  fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body as string | undefined,
  }));
const writes = () => calls().filter((c) => c.method !== "GET");

beforeEach(() => {
  rosterReply = () => jsonRes(ROSTER);
  stored = { version: 1 };
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
    if (url === "/admin/employees?include_disabled=true") return rosterReply();
    if (url === "/admin/settings/security") {
      if (init?.method === "PUT") stored = { ...JSON.parse(String(init.body)), version: 1 };
      return jsonRes({ tab: "security", config: stored });
    }
    if (url === "/admin/employees/1/2fa/reset") return jsonRes({ ok: true, employee_id: 1 });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  return renderWithProviders(
    <UserProvider>
      <SecurityOrgTab />
    </UserProvider>,
  );
}

/** The table's body rows (every row but the header row). */
const bodyRows = () => within(screen.getByRole("table")).getAllByRole("row").slice(1);

describe("SecurityOrgTab", () => {
  it("lists the roster rows with each login's 2FA status and last login", async () => {
    mount();
    expect(screen.getByRole("heading", { name: "Security (organization)" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Gamma Three")).toBeInTheDocument());
    expect(
      within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent),
    ).toEqual(["Name", "2FA status", "Last login", "Operations"]);
    expect(bodyRows().map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))).toEqual([
      ["Alpha One", "Enabled", new Date("2026-10-01T10:00:00Z").toLocaleString(), "Reset"],
      ["Beta Two", "Disabled", "—", "Reset"],
      ["Gamma Three", "—", "—", "Reset"],
    ]);
  });

  it("greys a disabled Employee's row with aria-disabled, and only that row", async () => {
    mount();
    await waitFor(() => expect(screen.getByText("Gamma Three")).toBeInTheDocument());
    expect(bodyRows().map((r) => r.getAttribute("aria-disabled"))).toEqual([null, null, "true"]);
  });

  it("puts the table in its own horizontally scrolling box", () => {
    mount();
    expect(screen.getByRole("table").parentElement).toHaveClass("overflow-x-auto");
  });

  it("turning the switch on asks first, then PUTs require_2fa: true", async () => {
    mount();
    const sw = screen.getByRole("switch", { name: "Two-factor authentication" });
    await waitFor(() => expect(calls().map((c) => c.url)).toContain("/admin/settings/security"));
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    const dialog = await screen.findByRole("dialog", { name: "Enable two-factor authentication for organization?" });
    expect(writes()).toEqual([]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(sw).toHaveAttribute("aria-checked", "true"));
    expect(writes()).toEqual([
      { method: "PUT", url: "/admin/settings/security", body: JSON.stringify({ require_2fa: true, version: 1 }) },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Cancel on the confirm sends nothing", async () => {
    mount();
    await waitFor(() => expect(calls().map((c) => c.url)).toContain("/admin/settings/security"));
    fireEvent.click(screen.getByRole("switch", { name: "Two-factor authentication" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);
  });

  it("Reset is on only for an active login with 2FA, and posts the reset after the confirm", async () => {
    mount();
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Reset" })).toHaveLength(3));
    const [alpha, beta, gamma] = screen.getAllByRole("button", { name: "Reset" });
    expect(alpha).toBeEnabled();
    expect(beta).toBeDisabled();
    expect(gamma).toBeDisabled();
    fireEvent.click(alpha);
    const dialog = await screen.findByRole("dialog", { name: "Reset two-factor authentication for employee's account?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes().map((c) => [c.method, c.url])).toEqual([["POST", "/admin/employees/1/2fa/reset"]]);
  });

  it("an empty roster shows exactly one \"No employees\" row", async () => {
    rosterReply = () => jsonRes({ employees: [] });
    mount();
    await waitFor(() => expect(screen.getByText("No employees")).toBeInTheDocument());
    expect(bodyRows().map((r) => r.textContent)).toEqual(["No employees"]);
  });

  it("a failed roster load shows the error line and no body row", async () => {
    rosterReply = () => jsonRes({ detail: "bad request" }, 400);
    mount();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/^Failed to load: bad request$/));
    expect(bodyRows()).toEqual([]);
  });
});
