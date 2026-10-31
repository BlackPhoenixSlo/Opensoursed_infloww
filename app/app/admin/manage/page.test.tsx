/**
 * /admin/manage over the two independent refresh calls, through the real
 * page: an EMPTY roster that loaded filters (nobody is live), a FAILED roster
 * does not and says so, and a failed FIRST /admin/users load shows its error —
 * not a skeleton forever, not "No users registered yet.". Only the relay wire
 * and useUser are faked.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } };
});
const me = vi.hoisted(() => ({
  user: { user_id: "me", username: "me", is_admin: true } as AuthedUserDTO | null,
  loading: false,
}));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: me.user, loading: me.loading }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

import AdminUsersPage from "./page";
import type { AuthedUserDTO } from "@/contexts/UserContext";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const USERS = ["1", "2", "3"].map((id) => ({
  id, username: `agency${id}`, created_at: "2026-01-01T00:00:00Z", last_seen_at: "2026-01-01T00:00:00Z", account_count: 0,
}));
const FILTER = /Only agencies with a live model session/;

function serve(roster: () => Promise<unknown>, users: () => Promise<unknown> = () => Promise.resolve(USERS)) {
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/users") return users();
    if (path === "/admin/users/llm-key-status") return roster();
    return Promise.resolve({});
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  me.user = { user_id: "me", username: "me", is_admin: true };
  me.loading = false;
});

describe("/admin/manage master gate", () => {
  it.each<[string, AuthedUserDTO | null]>([
    ["an owner who is not the master", { user_id: "me", username: "me", is_admin: false }],
    ["an owner with no role field", { user_id: "me", username: "me" }],
    ["no owner session (a chatter)", null],
  ])("%s: one 'master account required' line, no rows, no request", (_name, user) => {
    me.user = user;
    serve(() => Promise.resolve({ agencies: [] }));
    const { container } = render(<AdminUsersPage />);
    expect(screen.getAllByText("master account required")).toHaveLength(1);
    expect(screen.queryByText("@agency1")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.querySelector(".animate-pulse")).toBeNull();
    expect(relayGet).not.toHaveBeenCalled();
  });

  it("while /auth/me loads: nothing drawn (no line to flash at the master), no request", () => {
    me.user = null;
    me.loading = true;
    serve(() => Promise.resolve({ agencies: [] }));
    const { container } = render(<AdminUsersPage />);
    expect(container.innerHTML).toBe("");
    expect(relayGet).not.toHaveBeenCalled();
  });
});

describe("/admin/manage live-only filter", () => {
  it("an empty roster that LOADED filters: no agency has a live model", async () => {
    serve(() => Promise.resolve({ agencies: [] }));
    render(<AdminUsersPage />);
    await screen.findByText("@agency1");
    fireEvent.click(screen.getByLabelText(FILTER));
    expect(screen.getByText("(0 of 3)")).toBeTruthy();
    expect(screen.queryByText("@agency1")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a FAILED roster does not filter, and says the filter is off — not '(3 of 3)'", async () => {
    serve(() => Promise.reject(new Error("forbidden")));
    render(<AdminUsersPage />);
    await screen.findByText("@agency1");
    fireEvent.click(screen.getByLabelText(FILTER));
    expect(screen.getByText("@agency3")).toBeTruthy();
    expect(screen.getByText("(key status unavailable — filter off)")).toBeTruthy();
    expect(screen.queryByText("(3 of 3)")).toBeNull();
    expect(screen.getByRole("alert").textContent).toBe("Key status unavailable — forbidden");
  });

  it("the filter-off note outlives the error: a refresh whose users call fails still says it", async () => {
    serve(() => Promise.reject(new Error("forbidden")));
    render(<AdminUsersPage />);
    await screen.findByText("@agency1");
    serve(() => Promise.reject(new Error("forbidden")), () => Promise.reject(new Error("502")));
    fireEvent.click(screen.getByRole("button", { name: /Refresh/ }));
    expect(screen.getByText("(key status unavailable — filter off)")).toBeTruthy();
    await screen.findByText("502 · Key status unavailable — forbidden");
    expect(screen.getByText("@agency1")).toBeTruthy();
    expect(screen.getByText("(key status unavailable — filter off)")).toBeTruthy();
  });
});

describe("/admin/manage failed loads", () => {
  it("a failed FIRST /admin/users load shows the error: no skeleton, no 'No users registered yet.'", async () => {
    serve(() => Promise.resolve({ agencies: [] }), () => Promise.reject(new Error("upstream 502")));
    const { container } = render(<AdminUsersPage />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull(); // loading: the skeleton
    expect((await screen.findByRole("alert")).textContent).toBe("upstream 502");
    expect(container.querySelector(".animate-pulse")).toBeNull();
    expect(screen.queryByText("No users registered yet.")).toBeNull();
    expect(screen.getByRole("button", { name: /Refresh/ }).hasAttribute("disabled")).toBe(false);
  });

  it("a refresh failing after a good load keeps the rows and shows the error", async () => {
    serve(() => Promise.resolve({ agencies: [] }));
    render(<AdminUsersPage />);
    await screen.findByText("@agency1");
    serve(() => Promise.resolve({ agencies: [] }), () => Promise.reject(new Error("upstream 502")));
    fireEvent.click(screen.getByRole("button", { name: /Refresh/ }));
    expect((await screen.findByRole("alert")).textContent).toBe("upstream 502");
    expect(screen.getByText("@agency1")).toBeTruthy();
    expect(screen.getByText("(3 of 3)")).toBeTruthy();
  });
});
