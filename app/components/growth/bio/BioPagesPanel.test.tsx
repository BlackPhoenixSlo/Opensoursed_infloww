/**
 * Growth → Tracking links → Bio pages, rendered as the route renders it (`TrackingLinksPage`) over a mocked relay:
 * the owner gets the tab (last, tagged as ours) and its rows from `/admin/bio-pages`; a chatter gets no tab;
 * `?tab=bio` opens on it (the editor's back link); "New bio page" refuses a reserved username before any write, and a
 * create sends the normalized body and opens the editor.
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
  usePathname: () => "/growth/tracking-links",
  useSearchParams: () => new URLSearchParams(route.search),
  useParams: () => ({}),
}));
const route = vi.hoisted(() => ({ search: "" }));
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

import { TrackingLinksPage } from "@/components/growth/TrackingLinksTab";
import { relay, RelayError } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const ROW = (over: Record<string, unknown>) => ({
  id: "p00000000000001", username: "alice", display_name: "Alice A", avatar_url: "", account_id: "1000001",
  mode: "escape_ig", verified: true, link_count: 3, custom_domain: null, public_url: "https://bio.test/alice",
  views_30d: 1234, clicks_30d: 56, updated_at: "2026-11-10T00:00:00Z", ...over,
});
let list: { serving: boolean; public_base: string | null; profiles: unknown[] };

beforeEach(() => {
  session.chatter = null;
  route.search = "";
  push.mockReset();
  list = {
    serving: true, public_base: "https://bio.test",
    profiles: [ROW({}), ROW({ id: "p00000000000002", username: "bob", display_name: "Bob", account_id: null, public_url: "https://bio.test/bob", views_30d: 0, clicks_30d: 0, link_count: 0 })],
  };
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/accounts") return Promise.resolve({ accounts: [{ id: "1000001", nickname: "Creator A", has_session: true }] });
    if (path === "/admin/bio-pages") return Promise.resolve(list);
    return new Promise(() => {}); // every other read stays pending: not this test's
  });
  window.history.replaceState(null, "", "/growth/tracking-links");
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const rowOf = (username: string) => document.querySelector(`[data-bio-page="${username}"]`) as HTMLElement;

describe("Bio pages tab", () => {
  it("is the owner's last tab, tagged as ours, and lists every page with its Creator and 30-day counts", async () => {
    renderWithProviders(<TrackingLinksPage />);
    const tab = await screen.findByRole("tab", { name: /^Bio pages/ });
    expect(tab.getAttribute("title")).toBe(`${EXTRA_LABEL}: Bio pages`);
    expect(screen.getAllByRole("tab").at(-1)).toBe(tab);
    fireEvent.click(tab);
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
    expect(push).toHaveBeenCalledWith("/growth/tracking-links/bio/p00000000000001");
  });

  it("gives a chatter no Bio pages tab", async () => {
    session.chatter = { chatter_id: "chatter-1", username: "helper", display_name: "Helper", color: null, owners: [] };
    renderWithProviders(<TrackingLinksPage />);
    await waitFor(() => expect(screen.getAllByRole("tab").length).toBe(3));
    expect(screen.queryByRole("tab", { name: /Bio pages/ })).toBeNull();
    expect(relayGet).not.toHaveBeenCalledWith("/admin/bio-pages");
  });

  it("?tab=bio opens on it; no public address shows the note and paths", async () => {
    list = { serving: false, public_base: null, profiles: [ROW({ public_url: null })] };
    window.history.replaceState(null, "", "/growth/tracking-links?tab=bio");
    route.search = "tab=bio";
    const client = makeTestQueryClient();
    client.setQueryData(["accounts", "owner-1"], { accounts: [{ id: "1000001", nickname: "Creator A", has_session: true }], active_account_id: "1000001" });
    renderWithProviders(<TrackingLinksPage />, client);
    await waitFor(() => expect(screen.getByRole("tab", { name: /^Bio pages/ }).getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(rowOf("alice")).toBeTruthy());
    expect(relayGet).not.toHaveBeenCalledWith(expect.stringContaining("/admin/of-tracking-links"));
    expect(relayGet).not.toHaveBeenCalledWith(expect.stringContaining("/admin/tracking-links/earnings"));
    expect(within(rowOf("alice")).getByText("/alice")).toBeTruthy();
    expect(screen.getByText(/Not public here yet/)).toBeTruthy();
  });

  it("client navigation back selects Bio pages before the Links list can read OF", async () => {
    const client = makeTestQueryClient();
    client.setQueryData(["accounts", "owner-1"], { accounts: [{ id: "1000001", nickname: "Creator A", has_session: true }], active_account_id: "1000001" });
    route.search = "tab=redirects";
    window.history.replaceState(null, "", "/growth/tracking-links?tab=redirects");
    const view = renderWithProviders(<TrackingLinksPage />, client);
    await waitFor(() => expect(screen.getByRole("tab", { name: /^Redirect links/ }).getAttribute("aria-selected")).toBe("true"));
    relayGet.mockClear();
    route.search = "tab=bio";
    window.history.replaceState(null, "", "/growth/tracking-links?tab=list");
    view.rerender(<TrackingLinksPage />);
    await waitFor(() => expect(rowOf("alice")).toBeTruthy());
    expect(screen.getByRole("tab", { name: /^Bio pages/ }).getAttribute("aria-selected")).toBe("true");
    expect(relayGet).not.toHaveBeenCalledWith(expect.stringContaining("/admin/of-tracking-links"));
    expect(relayGet).not.toHaveBeenCalledWith(expect.stringContaining("/admin/tracking-links/earnings"));
  });

  it("shows the empty state with no pages", async () => {
    list = { serving: true, public_base: "https://bio.test", profiles: [] };
    window.history.replaceState(null, "", "/growth/tracking-links?tab=bio");
    route.search = "tab=bio";
    renderWithProviders(<TrackingLinksPage />);
    expect(await screen.findByText("No bio pages yet.")).toBeTruthy();
  });
});

describe("New bio page", () => {
  async function openDialog() {
    window.history.replaceState(null, "", "/growth/tracking-links?tab=bio");
    route.search = "tab=bio";
    renderWithProviders(<TrackingLinksPage />);
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
    await waitFor(() => expect(push).toHaveBeenCalledWith("/growth/tracking-links/bio/p00000000000003"));
  });
});
