/**
 * The owner's agency notification centre (AgencyNotifications), folded into the top bar's one bell
 * (TopBar's `HeaderBell`) as the panel's "Agency" tab: the server's unread count joins the bell's badge and
 * opens the panel on Agency, a row click reads it, "Mark all read" reads the rest, the gear's switches save
 * `preferences.notifications`, the OnlyFans tab is still the bell's feed, and a chatter's bell has no Agency
 * tab and reads nothing of it.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
let session: { user: object | null; chatter: object | null } = { user: { username: "owner" }, chatter: null };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: session.user }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: session.chatter }) }));
// The bell's OnlyFans side: no Creators, so no OnlyFans reads.
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [] }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));

import { renderWithProviders } from "@/test-utils";
import { relay } from "@/lib/relay";
import { HeaderBell } from "@/components/shell/TopBar";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;

const LIST = {
  unread: 1,
  notifications: [
    { id: 7, kind: "employee_deactivated", text: "Ana was deactivated", account_id: null, employee_id: 3,
      data: null, created_at: "2026-10-20T10:00:00Z", read: false },
    { id: 6, kind: "role_changed", text: "Bo's role changed from Chatter to Manager", account_id: null,
      employee_id: 4, data: null, created_at: "2026-10-19T10:00:00Z", read: true },
  ],
};

function route(path: string) {
  if (path.startsWith("/admin/agency-notifications")) return Promise.resolve(LIST);
  if (path === "/admin/settings/preferences") return Promise.resolve({ tab: "preferences", config: { notifications: { clock_in_missed: false } } });
  return Promise.reject(new Error(`unexpected GET ${path}`));
}

afterEach(() => {
  cleanup();
  get.mockReset(); post.mockReset(); put.mockReset();
  session = { user: { username: "owner" }, chatter: null };
});

const openBell = async () => fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));

describe("AgencyNotifications in the top bar's one bell", () => {
  it("adds the unread count to the bell, opens on Agency, and reads one row or all of them", async () => {
    get.mockImplementation(route);
    post.mockResolvedValue({ unread: 0 });
    renderWithProviders(<HeaderBell />);
    expect(await screen.findByTestId("bell-count")).toHaveTextContent("1");
    expect(screen.queryByRole("button", { name: /Agency notifications/ })).toBeNull();
    await openBell();
    expect(screen.getByRole("tab", { name: /Agency/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(await screen.findByText("Ana was deactivated"));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/agency-notifications/7/read"));
    // A read row's click files nothing.
    fireEvent.click(screen.getByText("Bo's role changed from Chatter to Manager"));
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/agency-notifications/read-all"));
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("keeps the OnlyFans feed on its own tab, with its \"See all\"", async () => {
    get.mockImplementation(route);
    renderWithProviders(<HeaderBell />);
    await screen.findByTestId("bell-count");
    await openBell();
    fireEvent.click(screen.getByRole("tab", { name: "OnlyFans" }));
    expect(screen.getByRole("link", { name: "See all" })).toHaveAttribute("href", "/notifications");
    expect(screen.queryByText("Ana was deactivated")).toBeNull();
  });

  it("saves a kind's switch into the preferences blob, keeping the others", async () => {
    get.mockImplementation(route);
    put.mockResolvedValue({ ok: true });
    renderWithProviders(<HeaderBell />);
    await screen.findByTestId("bell-count");
    await openBell();
    fireEvent.click(screen.getByRole("button", { name: "Notification settings" }));
    const missed = await screen.findByRole("checkbox", { name: "Missed clock-ins" });
    await waitFor(() => expect(missed).not.toBeDisabled());
    expect(missed).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "Unsent messages" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    const [path, body] = put.mock.calls[0];
    expect(path).toMatch(/^\/admin\/settings\/preferences/);
    expect(body).toEqual({ notifications: { clock_in_missed: false, message_unsent: false } });
  });

  it("gives a chatter the bell without an Agency tab, and reads nothing of it", async () => {
    session = { user: null, chatter: { id: 1 } };
    renderWithProviders(<HeaderBell />);
    await openBell();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(get.mock.calls.some(([p]) => String(p).startsWith("/admin/agency-notifications"))).toBe(false);
  });
});
