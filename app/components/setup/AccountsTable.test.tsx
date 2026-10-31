/**
 * AccountsTable — dropping a model evicts ALL of its cached data.
 *
 * The delete used to only `invalidateQueries(["accounts"])`, leaving 30+
 * per-account React Query keys (chats, vault-media, of-user, fan-*,
 * *-config/*-rules, automation-*, nudge-*) + the persisted localStorage
 * snapshot holding the dropped account's data until staleTime expiry — so a
 * manual logout/login was the only way to clear it.
 *
 * The fix runs `removeQueries` with a predicate that matches the dropped
 * accountId anywhere in a query key (including the unified "all"-scope chat
 * key, whose accountKey is a comma-joined list of every fanned-out id). These
 * cases assert: the dropped account's per-account caches are HARD-removed,
 * another account's caches survive untouched, and the accounts list refetches
 * (the deleted row disappears).
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), delete: vi.fn(), post: vi.fn(), put: vi.fn() } }));

import AccountsTable, { connectivity } from "@/components/setup/AccountsTable";
import AddCreatorModal from "@/components/setup/AddCreatorModal";
import { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import { relay, type AccountMeta } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  relayGet.mockReset();
  relayDelete.mockReset();
  relayPost.mockReset();
  relayPut.mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** Each row's actions sit in its "⋮" menu (ticket 16): open the row's menu and pick one. */
function pick(row: string, item: string) {
  fireEvent.click(screen.getByRole("button", { name: `More actions for ${row}` }));
  fireEvent.click(screen.getByRole("menuitem", { name: item }));
}

describe("AccountsTable delete — full per-account cache eviction", () => {
  it("hard-removes every per-account query for the dropped account and spares others", async () => {
    let accountsCalls = 0;
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        accountsCalls += 1;
        // First load lists both; the post-delete refetch drops acct-del.
        return Promise.resolve(
          accountsCalls === 1
            ? { accounts: [{ id: "acct-del" }, { id: "acct-keep" }], active_account_id: "acct-keep" }
            : { accounts: [{ id: "acct-keep" }], active_account_id: "acct-keep" },
        );
      }
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [] });
      return Promise.resolve({});
    });
    relayDelete.mockResolvedValue({ ok: true });

    // Seed the cache the way the live app would — per-account keys for BOTH
    // accounts plus the unified "all"-scope chat key (comma-joined ids).
    client.setQueryData(["chats", "model", "acct-del", null, null, null, 30], "del-chats");
    client.setQueryData(["chats", "model", "acct-keep", null, null, null, 30], "keep-chats");
    client.setQueryData(["chats", "all", "acct-del,acct-keep", null, null, null, 30], "combined-chats");
    client.setQueryData(["vault-media", "acct-del"], "del-vault");
    client.setQueryData(["vault-media", "acct-keep"], "keep-vault");
    client.setQueryData(["of-user", "acct-del", "fan1"], "del-ofuser");
    // A key with a non-string part — predicate must not throw on .split().
    client.setQueryData(["fan", "acct-del", 12345], "del-fan");

    render(<AccountsTable />, { wrapper });

    // Wait for the table to paint both rows (the id shows in two cells —
    // the name + the Creator ID — so match on the rows' menu buttons).
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^More actions for / })).toHaveLength(2),
    );

    // Delete, from acct-del's own menu, through the Delete modal's two steps (creators-manage#78).
    pick("acct-del", "Delete");
    expect(relayDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete creator" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    // The DELETE relay call goes out for the right account.
    await waitFor(() =>
      expect(relayDelete).toHaveBeenCalledWith("/admin/accounts/acct-del"),
    );

    // The dropped account's per-account caches are HARD-gone...
    await waitFor(() => {
      expect(client.getQueryData(["chats", "model", "acct-del", null, null, null, 30])).toBeUndefined();
    });
    expect(client.getQueryData(["vault-media", "acct-del"])).toBeUndefined();
    expect(client.getQueryData(["of-user", "acct-del", "fan1"])).toBeUndefined();
    expect(client.getQueryData(["fan", "acct-del", 12345])).toBeUndefined();
    // ...including the unified key whose accountKey lists the dropped id.
    expect(client.getQueryData(["chats", "all", "acct-del,acct-keep", null, null, null, 30])).toBeUndefined();

    // The OTHER account's caches survive untouched.
    expect(client.getQueryData(["chats", "model", "acct-keep", null, null, null, 30])).toBe("keep-chats");
    expect(client.getQueryData(["vault-media", "acct-keep"])).toBe("keep-vault");

    // The accounts list refetched and the deleted row is gone.
    await waitFor(() => expect(screen.queryByText("acct-del")).not.toBeInTheDocument());
    expect(screen.getAllByText("acct-keep").length).toBeGreaterThanOrEqual(1);
    expect(accountsCalls).toBeGreaterThanOrEqual(2);
  });
});

/**
 * A dead OF session pauses EVERY automation for that account
 * (service/account_health.py), but the relay's `session_dead_at` stamp had no
 * reader — so twelve accounts sat in the fleet with rules showing as enabled
 * while nothing ran, indistinguishable from accounts that were merely quiet.
 * These cases pin the badge that closes that gap.
 */
describe("AccountsTable — a paused account says it is paused", () => {
  it("badges the dead account, spares the healthy one, and names the repair", async () => {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        return Promise.resolve({
          accounts: [
            {
              id: "acct-dead",
              has_session: true,
              session_dead_at: "2026-07-10T14:14:37Z",
              session_dead_reason: "no_session",
            },
            { id: "acct-live", has_session: true },
          ],
          active_account_id: "acct-live",
        });
      }
      if (path.startsWith("/health")) {
        // OF answers the health probe for BOTH. The pause is a separate fact
        // from liveness — an account can pass this probe while its automations
        // stay parked — so a green probe must NOT hide the badge.
        return Promise.resolve({
          ok: true,
          accounts: [
            { account_id: "acct-dead", ok: true, name: "Dead" },
            { account_id: "acct-live", ok: true, name: "Live" },
          ],
        });
      }
      return Promise.resolve({});
    });

    render(<AccountsTable />, { wrapper });

    await waitFor(() =>
      expect(screen.getByText("automations paused")).toBeInTheDocument(),
    );
    // Exactly one row is badged — the healthy account is untouched.
    expect(screen.getAllByText("automations paused")).toHaveLength(1);
    // The operator is told WHICH repair, not shown the raw enum.
    expect(screen.getByTitle(/captured in Manage creators/i)).toBeInTheDocument();
    expect(screen.queryByText("no_session")).not.toBeInTheDocument();
    // …and how long it has been down, so a month-dead account is obvious.
    expect(screen.getByText(/^unlinked /)).toBeInTheDocument();
  });

  it("names Browserbase login as the repair when OnlyFans wants a 2FA code", async () => {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        return Promise.resolve({
          accounts: [{ id: "acct-otp", has_session: true, session_dead_at: "2026-10-25T09:00:00Z", session_dead_reason: "otp_required" }],
          active_account_id: "acct-otp",
        });
      }
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [] });
      return Promise.resolve({});
    });

    render(<AccountsTable />, { wrapper });

    const badge = await screen.findByText("automations paused");
    expect(badge.closest("[title]")).toHaveAttribute("title", expect.stringMatching(/2FA code.*Browserbase login/));
    expect(screen.queryByText("otp_required")).not.toBeInTheDocument();
  });

  it("leaves a fleet with no dead sessions completely unbadged", async () => {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        return Promise.resolve({
          accounts: [{ id: "acct-live", has_session: true }],
          active_account_id: "acct-live",
        });
      }
      if (path.startsWith("/health")) {
        return Promise.resolve({
          ok: true,
          accounts: [{ account_id: "acct-live", ok: true, name: "Live" }],
        });
      }
      return Promise.resolve({});
    });

    render(<AccountsTable />, { wrapper });

    // The id shows in two cells (name + Creator ID), so wait on the row's
    // menu button instead — same reason as the delete case above.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^More actions for / })).toHaveLength(1),
    );
    expect(screen.queryByText("automations paused")).not.toBeInTheDocument();
    expect(screen.queryByText(/^unlinked /)).not.toBeInTheDocument();
  });
});

describe("AccountsTable Creator avatar — no Display image picked", () => {
  function serve(accounts: object[]) {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") return Promise.resolve({ accounts, active_account_id: null });
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [] });
      if (path === "/api/of/v2/users/me") return Promise.resolve({ avatar: "https://public.onlyfans.com/files/a/av.jpg" });
      return Promise.resolve({});
    });
  }

  it("falls back to the OF profile picture, through the /img proxy", async () => {
    serve([{ id: "acct-of", nickname: "Oscar", platform: "onlyfans" }]);
    const { container } = render(<AccountsTable />, { wrapper });
    await waitFor(() => expect(container.querySelector('img[src^="/img?"]')).not.toBeNull());
    const src = container.querySelector('img[src^="/img?"]')!.getAttribute("src")!;
    expect(new URLSearchParams(src.slice(5)).get("u")).toBe("https://public.onlyfans.com/files/a/av.jpg");
    expect(new URLSearchParams(src.slice(5)).get("account_id")).toBe("acct-of");
  });

  it("does not ask OF for a Fansly row's avatar", async () => {
    serve([{ id: "acct-fy", nickname: "Fiona", platform: "fansly" }]);
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Fiona");
    expect(relayGet.mock.calls.map(([p]) => p)).not.toContain("/api/of/v2/users/me");
  });
});

/**
 * Creator deactivate (07 M28): the ⋮ menu's Deactivate asks first (Infloww's "fees still apply"), then posts the
 * switch; a deactivated row keeps its place, wears the "Deactivated" chip, offers Activate, and the Account status
 * filter narrows on it.
 */
describe("AccountsTable — deactivate / activate a creator", () => {
  function serve() {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        return Promise.resolve({
          accounts: [
            { id: "acct-on", nickname: "Onna", has_session: true, is_active: true },
            { id: "acct-off", nickname: "Offie", has_session: true, is_active: false },
          ],
          active_account_id: "acct-on",
        });
      }
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [] });
      return Promise.resolve({});
    });
    relayPost.mockResolvedValue({ ok: true });
  }

  it("confirms, then posts active:false for an active creator", async () => {
    serve();
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Onna");
    pick("Onna", "Deactivate");
    expect(screen.getByText(/Fees still apply/)).toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/accounts/acct-on/active", { active: false }));
  });

  it("keeps the deactivated row, chips it, and offers Activate", async () => {
    serve();
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Offie");
    expect(screen.getAllByText("Deactivated", { selector: "span" }).length).toBeGreaterThan(0);
    pick("Offie", "Activate");
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/accounts/acct-off/active", { active: true }));
  });

  it("badges a Creator whose proxy the relay holds bad", async () => {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        return Promise.resolve({
          accounts: [
            { id: "acct-on", nickname: "Onna", has_session: true, is_active: true, proxy_down: true },
            { id: "acct-ok", nickname: "Okko", has_session: true, is_active: true, proxy_down: false },
          ],
          active_account_id: "acct-on",
        });
      }
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [] });
      return Promise.resolve({});
    });
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Onna");
    expect(screen.getAllByText("proxy unreachable")).toHaveLength(1);
  });

  it("filters on Account status", async () => {
    serve();
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Offie");
    const status = screen.getByRole("combobox", { name: "Account status" });
    fireEvent.change(status, { target: { value: "Deactivated" } });
    expect(screen.queryAllByText("Onna")).toHaveLength(0);
    expect(screen.getAllByText("Offie").length).toBeGreaterThan(0);
    fireEvent.change(status, { target: { value: "Activated" } });
    expect(screen.queryAllByText("Offie")).toHaveLength(0);
  });
});

/** The footer pages the rows on the client; a filter or per-page change goes back to page 1. */
describe("AccountsTable — paging", () => {
  const ACCOUNTS = Array.from({ length: 25 }, (_, i) => ({
    id: `acct-${i + 1}`, nickname: `Model ${String(i + 1).padStart(2, "0")}`, has_session: true, is_active: true,
  }));
  const currentPage = () =>
    within(screen.getByRole("navigation", { name: "Pagination" }))
      .getAllByRole("button").find((b) => b.getAttribute("aria-current") === "page")?.textContent;
  const toPage2 = () => {
    fireEvent.click(screen.getByRole("button", { name: "Page 2" }));
    expect(currentPage()).toBe("2");
  };

  it("goes back to page 1 when a filter or the page size changes", async () => {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") return Promise.resolve({ accounts: ACCOUNTS, active_account_id: "acct-1" });
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [] });
      return Promise.resolve({});
    });
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Model 01");

    toPage2();
    expect(screen.getAllByText("Model 11").length).toBeGreaterThan(0);
    // Every row is active, so the filter keeps all 25 — only the page moves.
    fireEvent.change(screen.getByRole("combobox", { name: "Account status" }), { target: { value: "Activated" } });
    expect(currentPage()).toBe("1");
    expect(screen.getAllByText("Model 01").length).toBeGreaterThan(0);

    toPage2();
    // 20 per page still leaves 2 pages.
    fireEvent.click(screen.getByRole("combobox", { name: "Per page" }));
    fireEvent.click(screen.getByRole("option", { name: "20" }));
    expect(currentPage()).toBe("1");
    expect(screen.getAllByText("Model 20").length).toBeGreaterThan(0);
  });
});

/** The connectivity mapping (creators-manage#23, #40): the accounts read outranks the live probe. */
describe("connectivity", () => {
  type H = Parameters<typeof connectivity>[1];
  const LIVE = { id: "a", has_session: true, is_active: true } as AccountMeta;
  const LOADED = { loaded: true, error: null };
  it.each<[string, AccountMeta, H, { loaded: boolean; error: Error | null }, { label: string; tone: string; title?: string }]>([
    ["loaded, ok", LIVE, { account_id: "a", ok: true, name: "Bella" }, LOADED, { label: "Connected", tone: "ok", title: "Bella" }],
    ["loaded, timed out", LIVE, { account_id: "a", ok: false, timed_out: true, message: "slow" }, LOADED,
      { label: "Pending connection", tone: "muted", title: "slow" }],
    ["loaded, no session", LIVE, { account_id: "a", ok: false, error: "no_session" }, LOADED, { label: "Not connected", tone: "muted" }],
    ["loaded, down", LIVE, { account_id: "a", ok: false, error: "401" }, LOADED, { label: "Disconnected", tone: "err", title: "401" }],
    ["loaded, Fansly down", { ...LIVE, platform: "fansly" }, { account_id: "a", ok: false, error: "401" }, LOADED,
      { label: "Disconnected", tone: "err", title: FANSLY_T.rebind }],
    ["health read failed", LIVE, undefined, { loaded: false, error: new Error("boom") }, { label: "—", tone: "muted", title: "boom" }],
    ["health still loading", LIVE, undefined, { loaded: false, error: null }, { label: "Pending connection", tone: "muted" }],
    ["no health row", LIVE, undefined, LOADED, { label: "—", tone: "muted", title: "no health answer for this Creator" }],
    ["deactivated (not probed), even with an ok probe", { ...LIVE, is_active: false }, { account_id: "a", ok: true, name: "B" }, LOADED,
      { label: "—", tone: "muted", title: "deactivated: not probed" }],
    ["no session outranks the probe", { ...LIVE, has_session: false }, { account_id: "a", ok: true }, LOADED,
      { label: "Not connected", tone: "muted" }],
    ["a dead session outranks a failed read", { ...LIVE, session_dead_at: "t" }, undefined, { loaded: false, error: new Error("x") },
      { label: "Disconnected", tone: "err" }],
    ["a dead Fansly session names the rebind", { ...LIVE, platform: "fansly", session_dead_at: "t" }, { account_id: "a", ok: true },
      LOADED, { label: "Disconnected", tone: "err", title: FANSLY_T.rebind }],
  ])("%s", (_name, a, h, read, want) => {
    expect(connectivity(a, h, read)).toMatchObject(want);
  });
});

/** Escape closes only the top modal (the modal stack in ui/infloww), and the Delete modal deletes only on step 2. */
describe("AccountsTable modals — Escape", () => {
  function serve() {
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/accounts") {
        return Promise.resolve({ accounts: [{ id: "acct-on", nickname: "Onna", has_session: true, is_active: true }], active_account_id: null });
      }
      if (path.startsWith("/health")) return Promise.resolve({ ok: true, accounts: [{ account_id: "acct-on", ok: true, name: "Onna" }] });
      if (path === "/admin/proxies") return Promise.resolve({ proxies: [] });
      return Promise.resolve({});
    });
  }
  const esc = () => fireEvent.keyDown(document, { key: "Escape" });

  it("Change proxy over Edit account details: Escape closes Change proxy only", async () => {
    serve();
    render(<AccountsTable />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByRole("dialog", { name: "Edit account details" });
    const change = screen.getByRole("button", { name: "Change" });
    await waitFor(() => expect(change).toBeEnabled());
    fireEvent.click(change);
    await screen.findByRole("dialog", { name: "Change proxy" });
    esc();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Change proxy" })).not.toBeInTheDocument());
    expect(screen.getByRole("dialog", { name: "Edit account details" })).toBeInTheDocument();
    esc();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Escape on the Delete modal's step 2 closes it and deletes nothing", async () => {
    serve();
    render(<AccountsTable />, { wrapper });
    await screen.findAllByText("Onna");
    pick("Onna", "Delete");
    fireEvent.click(screen.getByRole("button", { name: "Delete creator" }));
    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();
    esc();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(relayDelete).not.toHaveBeenCalled();
  });
});

/** The header's Add creator modal, step 1: a double-click on "Next: Link creator account" saves the Creator once
 *  (the second click lands before React re-renders, on the step the first left busy). */
describe("AddCreatorModal — Next: Link creator account", () => {
  it("a double-click saves the Creator once, then Back walks proxy → platform → details", async () => {
    let release = () => {};
    relayGet.mockImplementation((p: string) => p === "/admin/settings/account"
      ? Promise.resolve({ tab: "account", config: { language: "en" } })
      : p === "/admin/proxies" ? Promise.resolve({ proxies: [], pool: { size: 0, account_ids: [] }, accounts: [] })
        : Promise.resolve({}));
    relayPut.mockImplementation((_p: string, body: unknown) =>
      new Promise((r) => { release = () => r({ tab: "account", config: body }); }));
    render(<AddCreatorModal extInstalled={null} onClose={() => {}} />, { wrapper });
    const d = () => screen.getByRole("dialog");
    const btn = (n: string) => within(d()).getByRole("button", { name: n });
    fireEvent.change(within(d()).getByLabelText("Creator name"), { target: { value: "Nova" } });
    fireEvent.change(within(d()).getByLabelText("Gender"), { target: { value: "Female" } });
    await waitFor(() => expect(btn("Done")).toBeEnabled());
    const next = btn("Next: Link creator account");
    // Both clicks inside ONE act: no re-render between them.
    act(() => { next.click(); next.click(); });
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(relayPut.mock.calls.filter(([p]) => p === "/admin/settings/account")).toHaveLength(1);
    await act(async () => { release(); });
    await within(d()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Next"));
    await within(d()).findByText("Proxy selection");
    fireEvent.click(btn("Back"));
    await within(d()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Back"));
    expect(within(d()).getByLabelText("Creator name")).toHaveValue("Nova");
  });
});
