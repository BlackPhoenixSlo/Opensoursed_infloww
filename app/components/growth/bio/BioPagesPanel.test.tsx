/**
 * Growth → Bio pages, rendered as the route renders it (`BioPagesPage`) over a mocked relay: the owner gets its rows
 * from `/admin/bio-pages` (a row opens /growth/bio-pages/<id>); a chatter gets the owner-only note and no read; "New
 * bio page" refuses a reserved username before any write, a create sends the normalized body and opens the editor,
 * and a picked Creator prefills the name and a username from its `/users/me`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ChatterFlatAccountDTO, ChatterMeDTO } from "@/contexts/ChatterContext";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const session = vi.hoisted(() => ({ chatter: null as ChatterMeDTO | null }));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/growth/bio-pages",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/UserContext")>()),
  useUser: () => ({ user: session.chatter ? null : { user_id: "owner-1" } }),
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/ChatterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => ({ chatter: session.chatter }),
}));
vi.mock("@/lib/chatterAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/chatterAccounts")>();
  return {
    ...mod,
    chatterAccountsQuery: {
      ...mod.chatterAccountsQuery,
      queryFn: async (): Promise<ChatterFlatAccountDTO[]> => [
        { account_id: "1000001", nickname: "Creator A", color: null, owner_id: "owner-1", owner_username: "Owner", is_active: true },
      ],
    },
  };
});

import { BioPagesPage } from "@/components/growth/bio/BioPagesPanel";
import { relay, RelayError } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const ROW = (over: Record<string, unknown>) => ({
  id: "p00000000000001", username: "alice", display_name: "Alice A", avatar_url: "", account_id: "1000001",
  mode: "escape_ig", verified: true, link_count: 3, custom_domain: null, public_url: "https://bio.test/alice",
  views_30d: 1234, clicks_30d: 56, updated_at: "2026-11-10T00:00:00Z", ...over,
});
let list: { serving: boolean; public_base: string | null; profiles: unknown[] };
let me: { name?: string | null; username?: string | null };

beforeEach(() => {
  session.chatter = null;
  push.mockReset();
  list = {
    serving: true, public_base: "https://bio.test",
    profiles: [ROW({}), ROW({ id: "p00000000000002", username: "bob", display_name: "Bob", account_id: null, public_url: "https://bio.test/bob", views_30d: 0, clicks_30d: 0, link_count: 0 })],
  };
  me = { name: "Carol C", username: "Carol.C" };
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/accounts") return Promise.resolve({ accounts: [{ id: "1000001", nickname: "Creator A", has_session: true }] });
    if (path === "/admin/bio-pages") return Promise.resolve(list);
    if (path === "/api/of/v2/users/me") return Promise.resolve(me);
    return new Promise(() => {}); // every other read stays pending: not this test's
  });
  window.history.replaceState(null, "", "/growth/bio-pages");
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const rowOf = (username: string) => document.querySelector(`[data-bio-page="${username}"]`) as HTMLElement;

describe("Bio pages", () => {
  it("lists every page with its Creator and 30-day counts; a row opens its editor", async () => {
    renderWithProviders(<BioPagesPage />);
    expect(await screen.findByRole("heading", { level: 1, name: "Bio pages" })).toBeTruthy();
    await waitFor(() => expect(rowOf("alice")).toBeTruthy());
    const alice = within(rowOf("alice"));
    expect(alice.getByText("Alice A")).toBeTruthy();
    expect(alice.getByText("@alice")).toBeTruthy();
    expect(alice.getByText("https://bio.test/alice")).toBeTruthy();
    expect(alice.getByText("Creator A")).toBeTruthy();
    expect(rowOf("alice").querySelector("[data-views]")?.textContent).toContain("1,234");
    expect(rowOf("alice").querySelector("[data-clicks]")?.textContent).toContain("56");
    expect(within(rowOf("bob")).getByText("—")).toBeTruthy();
    expect(screen.queryByText(/Not public here yet/)).toBeNull();
    fireEvent.click(alice.getByText("@alice"));
    expect(push).toHaveBeenCalledWith("/growth/bio-pages/p00000000000001");
  });

  it("is owner-only: a chatter gets the note and no read", async () => {
    session.chatter = { chatter_id: "chatter-1", username: "helper", display_name: "Helper", color: null, owners: [] };
    renderWithProviders(<BioPagesPage />);
    expect(await screen.findByText("Bio pages are owner-only.")).toBeTruthy();
    expect(relayGet).not.toHaveBeenCalledWith("/admin/bio-pages");
  });

  it("no public address shows the note and paths, and reads nothing from OF", async () => {
    list = { serving: false, public_base: null, profiles: [ROW({ public_url: null })] };
    const client = makeTestQueryClient();
    client.setQueryData(["accounts", "owner-1"], { accounts: [{ id: "1000001", nickname: "Creator A", has_session: true }], active_account_id: "1000001" });
    renderWithProviders(<BioPagesPage />, client);
    await waitFor(() => expect(rowOf("alice")).toBeTruthy());
    expect(relayGet).not.toHaveBeenCalledWith(expect.stringContaining("/admin/of-tracking-links"));
    expect(relayGet).not.toHaveBeenCalledWith(expect.stringContaining("/api/of/"), expect.anything(), expect.anything());
    expect(within(rowOf("alice")).getByText("/alice")).toBeTruthy();
    expect(screen.getByText(/Not public here yet/)).toBeTruthy();
  });

  it("shows the empty state with no pages", async () => {
    list = { serving: true, public_base: "https://bio.test", profiles: [] };
    renderWithProviders(<BioPagesPage />);
    expect(await screen.findByText("No bio pages yet.")).toBeTruthy();
  });
});

describe("New bio page", () => {
  async function openDialog() {
    renderWithProviders(<BioPagesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "New bio page" }));
    return screen.findByRole("dialog", { name: "New bio page" });
  }

  it("refuses a reserved username before any write", async () => {
    const dialog = within(await openDialog());
    fireEvent.change(dialog.getByLabelText(/Username/), { target: { value: "API" } });
    fireEvent.change(dialog.getByLabelText(/Display name/), { target: { value: "X" } });
    fireEvent.click(dialog.getByRole("button", { name: "Create" }));
    expect(await dialog.findByRole("alert")).toHaveProperty("textContent", "That username is reserved.");
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("creates with the normalized body and opens the editor; a taken username shows the API's message", async () => {
    const dialog = within(await openDialog());
    relayPost.mockRejectedValueOnce(new RelayError(409, { detail: { field: "username", msg: "That username is taken." } }));
    fireEvent.change(dialog.getByLabelText(/Username/), { target: { value: " @Carol_1 " } });
    fireEvent.change(dialog.getByLabelText(/Display name/), { target: { value: " Carol " } });
    fireEvent.click(dialog.getByRole("button", { name: "Create" }));
    expect(await dialog.findByText("That username is taken.")).toBeTruthy();
    expect(relayPost).toHaveBeenCalledWith("/admin/bio-pages", { username: "carol_1", display_name: "Carol" });

    relayPost.mockResolvedValueOnce({ profile: { ...ROW({ id: "p00000000000003", username: "carol_1" }), bio: "" }, links: [] });
    fireEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/growth/bio-pages/p00000000000003"));
  });

  it("a picked Creator prefills the name and a username from its OnlyFans profile, and creates with it", async () => {
    const dialog = within(await openDialog());
    fireEvent.click(dialog.getByRole("combobox", { name: "Creator" }));
    fireEvent.click(within(await screen.findByRole("listbox")).getByRole("option", { name: /Creator A/ }));
    await waitFor(() => expect((dialog.getByLabelText(/Display name/) as HTMLInputElement).value).toBe("Carol C"));
    expect((dialog.getByLabelText(/Username/) as HTMLInputElement).value).toBe("carolc");
    expect(relayGet).toHaveBeenCalledWith("/api/of/v2/users/me", expect.objectContaining({ accountId: "1000001" }), expect.anything());

    relayPost.mockResolvedValueOnce({ profile: { ...ROW({ id: "p00000000000004", username: "carolc" }), bio: "" }, links: [] });
    fireEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/growth/bio-pages/p00000000000004"));
    expect(relayPost).toHaveBeenCalledWith("/admin/bio-pages", { username: "carolc", display_name: "Carol C", account_id: "1000001" });
  });
});
