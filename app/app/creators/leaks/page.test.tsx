import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

const url = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  return {
    subscribe: (cb: () => void) => { listeners.add(cb); return () => listeners.delete(cb); },
    go: (to: string) => { window.history.replaceState({}, "", to); listeners.forEach((cb) => cb()); },
  };
});
const replace = vi.fn((to: string) => url.go(to));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useRouter: () => ({ replace, push: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
    usePathname: () => "/creators/leaks",
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(url.subscribe, () => window.location.search)),
  };
});

vi.mock("@/lib/relay", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});

let flags: { fansly_manager: boolean; leak_tracker: boolean } | undefined;
vi.mock("@/components/shell/useFlags", () => ({ useFlags: () => flags }));
let scopeAccount: string | null = null;
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: scopeAccount }) }));
const ACCOUNTS = [{ id: "acc-a", nickname: "Creator A" }, { id: "acc-b", nickname: "Creator B" }, { id: "acc-c", nickname: "Creator C" }];
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => ACCOUNTS }));
vi.mock("@/hooks/useEmployeeKey", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useEmployeeKey")>()),
  useEmployeeKey: () => null,
}));

import Page from "@/app/creators/leaks/page";
import { IfConfirmHost } from "@/components/ui/ifConfirm";
import { relay, RelayError } from "@/lib/relay";
import { QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;
const KEY = "ltk_" + "a".repeat(40);
const setupGets = () => relayGet.mock.calls.filter(([path]) => path === "/admin/leaks/setup").length;
const setup = (over: Record<string, unknown> = {}) =>
  ({ key: "missing", masked: null, is_owner: true, can_write: true, brand: null, ...over });
const UNKNOWN = { seeded: false, paused: false, paused_since: null, last_checked_at: null, next_check_at: null, counts: null, today: null };
const LOCAL = { platform: "onlyfans", username: "miavale", display_name: "Mia Vale", on: true, synced: true, reachable: true };
const ROSTER = {
  rows: [{ account_id: "acc-a", name: "Creator A", ...LOCAL, ...UNKNOWN }],
  untracked: [{ account_id: "acc-b", name: "Creator B" }],
  stale: false,
  fetched_at: "2026-11-27T12:00:00+00:00",
};
const MIA_SERVICE = {
  seeded: true, paused: false, paused_since: null, last_checked_at: "2026-11-27T04:05:00Z", next_check_at: "2026-11-28T04:00:00Z",
  counts: { cached: 1, came_back_30d: 1, found_on_first_scan: 3, gone: 0, listed: 1, live: 1, new_today: 1, not_checked: 1 },
};
const ROWAN_SERVICE = {
  seeded: false, paused: true, paused_since: "2026-11-20T09:00:00Z", last_checked_at: null, next_check_at: "2026-11-28T04:00:00Z",
  counts: { cached: 0, came_back_30d: 0, found_on_first_scan: 0, gone: 0, listed: 0, live: 0, new_today: 0, not_checked: 0 },
};
const MERGED = {
  ...ROSTER,
  rows: [
    { account_id: "acc-a", name: "Creator A", ...LOCAL, ...MIA_SERVICE },
    { account_id: "acc-c", name: "Creator C", ...LOCAL, username: "rowanash", ...ROWAN_SERVICE },
  ],
};
const MIA = { username: "miavale", verified: true, display_name: "Mia Vale" };
const untracked = (suggested: Record<string, unknown> = MIA) => ({ tracked: false, identity: null, suggested, synced: false });
const tracked = (synced = true) => ({
  tracked: true, synced, suggested: null,
  identity: { platform: "onlyfans", ...MIA, aliases: [], instagram: null, x: null, on: true },
});
const NO_LEAKS = { leaks: [], next_cursor: null, stale: false, fetched_at: null };
const golden = (name: string) => JSON.parse(readFileSync(
  resolve(__dirname, "../../../../service/tests/fixtures/leak_tracker_v1", `${name}.json`), "utf8")).response;
const ACCOUNT_OF: Record<string, string> = { w_miavale_0001: "acc-a", w_rowanash_0002: "acc-c" };
const asAll = (name: string) => {
  const { leaks, next_cursor } = golden(name);
  return {
    leaks: leaks.map(({ watch_id, ...l }: { watch_id: string }) => ({ ...l, account_id: ACCOUNT_OF[watch_id] })),
    next_cursor, stale: false, fetched_at: "2026-11-27T12:00:00+00:00",
  };
};
const CREATOR_LEAKS = golden("creator_leaks").leaks;
const CURSOR = golden("leaks").next_cursor as string;
const drill = (leaks: unknown[], next_cursor: string | null = null, stale = false) =>
  ({ ...tracked(), leaks, next_cursor, stale, fetched_at: "2026-11-27T12:00:00+00:00" });
const MEDIA = "img, video, audio, picture, iframe, source, object, embed";
const leakIds = (list: HTMLElement) => within(list).getAllByRole("listitem").filter((li) => li.dataset.leak).map((li) => li.dataset.leak);
type Answer = unknown | (() => unknown);
const serve = (s: Record<string, unknown>, routes: Record<string, Answer> = {}) =>
  relayGet.mockImplementation(async (path: string) => {
    const all: Record<string, Answer> = {
      "/admin/leaks/setup": s, "/admin/leaks/roster": ROSTER, "/admin/leaks/all": NO_LEAKS,
      "/admin/leaks/watches/acc-a": tracked(), "/admin/leaks/watches/acc-b": untracked(), ...routes,
    };
    if (!(path in all)) throw new RelayError(404, "Not Found");
    const v = all[path];
    return typeof v === "function" ? (v as () => unknown)() : v;
  });
const saveIn = () => within(screen.getByRole("form", { name: "Leak identity" })).getByRole("button", { name: "Save" });
const row = (name: string) => screen.getAllByTestId("of-creator-row").find((r) => r.textContent?.includes(name));
const pick = async (name: string) => {
  await waitFor(() => expect(row(name)).toBeTruthy());
  fireEvent.click(row(name)!);
  return screen.findByRole("region", { name });
};

beforeEach(() => {
  flags = { fansly_manager: false, leak_tracker: true };
  relayGet.mockReset();
  relayPut.mockReset();
  relayPost.mockReset();
  relayDelete.mockReset();
  replace.mockClear();
  scopeAccount = null;
  window.history.replaceState({}, "", "/creators/leaks");
});
afterEach(() => cleanup());

describe("/creators/leaks", () => {
  it("shows the owner the setup card when no key is stored", async () => {
    relayGet.mockResolvedValue(setup());
    renderWithProviders(<Page />);
    expect(await screen.findByRole("region", { name: "Connect the removal service" })).toBeTruthy();
    expect(screen.queryByText(/agency owner has not connected/)).toBeNull();
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/setup", { accountId: null });
  });

  it("shows a Team Leader one line instead of the card", async () => {
    relayGet.mockResolvedValue(setup({ is_owner: false, can_write: false }));
    renderWithProviders(<Page />);
    expect(await screen.findByText("The agency owner has not connected the removal service yet.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Connect the removal service" })).toBeNull();
  });

  it("with a key, draws the Creator column with All Models on top and selected", async () => {
    serve(setup({ key: "set" }));
    const { container } = renderWithProviders(<Page />);
    const view = () => container.querySelector("[data-leak-view]")?.getAttribute("data-leak-view");
    await waitFor(() => expect(view()).toBe("all"));
    expect(screen.queryByRole("region", { name: "Connect the removal service" })).toBeNull();
    const allRow = screen.getByTestId("of-all-creators-row");
    expect(allRow.getAttribute("aria-label")).toBe("All Models");
    expect(allRow.getAttribute("aria-current")).toBe("true");
    await waitFor(() => expect(row("Creator A")).toBeTruthy());
    fireEvent.click(row("Creator A")!);
    expect(view()).toBe("acc-a");
    expect(screen.getByTestId("of-all-creators-row").getAttribute("aria-current")).toBeNull();
    fireEvent.click(screen.getByTestId("of-all-creators-row"));
    expect(view()).toBe("all");
  });

  it("flag off: not available, and the Relay is never asked", async () => {
    flags = { fansly_manager: false, leak_tracker: false };
    renderWithProviders(<Page />);
    expect(await screen.findByText("Leak tracker is not available.")).toBeTruthy();
    expect(relayGet).not.toHaveBeenCalled();
  });

  it("a 404 from the gates reads as not available", async () => {
    relayGet.mockRejectedValue(new RelayError(404, "Not Found"));
    renderWithProviders(<Page />);
    expect(await screen.findByText("Leak tracker is not available.")).toBeTruthy();
  });

  it.each([
    ["a 500", new RelayError(500, "boom")],
    ["a network failure", new TypeError("Failed to fetch")],
  ])("%s shows the error state with Retry, not 'not available'", async (_label, err) => {
    relayGet.mockRejectedValueOnce(err).mockResolvedValue(setup());
    renderWithProviders(<Page />);
    expect(await screen.findByText("Couldn't load the Leak tracker.")).toBeTruthy();
    expect(screen.queryByText("Leak tracker is not available.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("region", { name: "Connect the removal service" })).toBeTruthy();
  });

  it("the owner pastes a key, the Relay checks it, and the card reads set from the PUT answer alone", async () => {
    serve(setup());
    relayPut.mockResolvedValue({ key: "set", masked: "••••aaaa", brand: "Example Removal" });
    renderWithProviders(<Page />);
    fireEvent.change(await screen.findByLabelText("Tracker key"), { target: { value: `  ${KEY} ` } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/key", { key: KEY }, { accountId: null }));
    const card = await screen.findByRole("region", { name: "Removal service key" });
    expect(card.textContent).toContain("Connected to Example Removal · ••••aaaa");
    expect(document.body.textContent).not.toContain(KEY);
    expect(screen.getByTestId("of-all-creators-row").getAttribute("aria-current")).toBe("true");
    expect(setupGets()).toBe(1);
  });

  it("a saved key reads set in every scope of the Agency without a refetch", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    relayGet.mockResolvedValue(setup());
    scopeAccount = "acc-b";
    renderWithProviders(<Page />, client);
    expect(await screen.findByLabelText("Tracker key")).toBeTruthy();
    cleanup();
    scopeAccount = null;
    relayPut.mockResolvedValue({ key: "set", masked: "••••aaaa", brand: "Example Removal" });
    renderWithProviders(<Page />, client);
    fireEvent.change(await screen.findByLabelText("Tracker key"), { target: { value: KEY } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("region", { name: "Removal service key" });
    cleanup();
    scopeAccount = "acc-b";
    renderWithProviders(<Page />, client);
    const card = await screen.findByRole("region", { name: "Removal service key" });
    expect(card.textContent).toContain("Connected to Example Removal · ••••aaaa");
    expect(setupGets()).toBe(2);
  });

  it.each([
    ["a refused key", new RelayError(422, { detail: "Key not accepted" }, "Key not accepted"), "Key not accepted"],
    ["another tenant's key", new RelayError(422, {}, "Key belongs to another tracker account"), "Key belongs to another tracker account"],
    ["an unreachable service", new RelayError(503, {}, "The removal service is not reachable; nothing was saved"),
      "The removal service is not reachable; nothing was saved"],
  ])("%s keeps the card and says why", async (_label, err, text) => {
    relayGet.mockResolvedValue(setup());
    relayPut.mockRejectedValue(err);
    renderWithProviders(<Page />);
    fireEvent.change(await screen.findByLabelText("Tracker key"), { target: { value: KEY } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe(text);
    expect(screen.getByRole("region", { name: "Connect the removal service" })).toBeTruthy();
    expect(relayGet).toHaveBeenCalledTimes(1);
  });

  it("an empty field sends nothing", async () => {
    relayGet.mockResolvedValue(setup());
    renderWithProviders(<Page />);
    fireEvent.change(await screen.findByLabelText("Tracker key"), { target: { value: "   " } });
    fireEvent.submit(screen.getByRole("button", { name: "Save" }).closest("form")!);
    expect(relayPut).not.toHaveBeenCalled();
  });

  it("a key the service no longer accepts offers the card again to the owner", async () => {
    relayGet.mockResolvedValue(setup({ key: "invalid", masked: "••••aaaa" }));
    renderWithProviders(<Page />);
    expect(await screen.findByText(/Key no longer valid/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Connect the removal service" })).toBeTruthy();
    expect(screen.getByLabelText("Tracker key")).toBeTruthy();
    expect(screen.queryByTestId("of-all-creators-row")).toBeNull();
  });

  it("a Team Leader with an invalid key reads one line and no card", async () => {
    relayGet.mockResolvedValue(setup({ key: "invalid", is_owner: false, can_write: false }));
    renderWithProviders(<Page />);
    expect(await screen.findByText("Key no longer valid. Ask the agency owner to connect the removal service again.")).toBeTruthy();
    expect(screen.queryByLabelText("Tracker key")).toBeNull();
  });

  it("the owner can disconnect a set key", async () => {
    serve(setup({ key: "set", masked: "••••aaaa" }));
    relayPut.mockResolvedValue({ key: "missing", masked: null, brand: null });
    renderWithProviders(<Page />);
    const card = await screen.findByRole("region", { name: "Removal service key" });
    expect(card.textContent).toContain("Connected to the removal service · ••••aaaa");
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/key", { key: "" }, { accountId: null }));
    expect(await screen.findByRole("region", { name: "Connect the removal service" })).toBeTruthy();
    expect(setupGets()).toBe(1);
  });

  it("a Team Leader with a set key sees no key card", async () => {
    serve(setup({ key: "set", is_owner: false, can_write: false }));
    const { container } = renderWithProviders(<Page />);
    await waitFor(() => expect(container.querySelector("[data-leak-view]")).toBeTruthy());
    expect(screen.queryByRole("region", { name: "Removal service key" })).toBeNull();
  });

  it("the column lists the roster's Creators, untracked ones as Not tracked", async () => {
    serve(setup({ key: "set" }));
    renderWithProviders(<Page />);
    await waitFor(() => expect(row("Creator B")?.textContent).toContain("Not tracked"));
    expect(row("Creator A")?.textContent).toContain("Not checked yet");
    expect(row("Creator C")).toBeUndefined();
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/roster", { accountId: null });
  });

  it("the column waits on the roster and a failed roster offers Retry, never every active Creator", async () => {
    let fail = true;
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": async () => {
        await gate;
        if (fail) throw new RelayError(500, "boom");
        return ROSTER;
      },
    });
    const { container } = renderWithProviders(<Page />);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/leaks/roster", { accountId: null }));
    expect(container.querySelector("[data-loading]")).toBeTruthy();
    expect(screen.queryAllByTestId("of-creator-row")).toEqual([]);
    release();
    expect(await screen.findByText("Couldn't load the Creators.")).toBeTruthy();
    expect(screen.queryAllByTestId("of-creator-row")).toEqual([]);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Not checked yet"));
    expect(row("Creator B")?.textContent).toContain("Not tracked");
    expect(row("Creator C")).toBeUndefined();
  });

  it("each entry carries its count line from the merged roster", async () => {
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": { ...MERGED, rows: [...MERGED.rows, {
        account_id: "acc-d", name: "Creator D", ...LOCAL, ...MIA_SERVICE,
        counts: { ...MIA_SERVICE.counts, live: 2, new_today: 0, found_on_first_scan: 5 },
      }] },
    });
    ACCOUNTS.push({ id: "acc-d", nickname: "Creator D" });
    try {
      renderWithProviders(<Page />);
      await waitFor(() => expect(row("Creator A")).toBeTruthy());
      const notes = Object.fromEntries(screen.getAllByTestId("of-creator-row").map((r) => [
        r.textContent?.match(/Creator [A-D]/)?.[0], within(r).getByTestId("of-creator-note").textContent,
      ]));
      expect(notes).toEqual({
        "Creator A": "1 up now · 1 new today",
        "Creator B": "Not tracked",
        "Creator C": "Paused since 20 Nov",
        "Creator D": "Found on first scan · 5",
      });
      const allRow = screen.getByTestId("of-all-creators-row");
      expect(allRow.compareDocumentPosition(row("Creator A")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(allRow.getAttribute("aria-current")).toBe("true");
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      ACCOUNTS.pop();
    }
  });

  it("a roster that finds the key refused sends the page to Key no longer valid", async () => {
    let key = "set";
    serve(setup(), {
      "/admin/leaks/setup": () => setup({ key, masked: "••••aaaa" }),
      "/admin/leaks/roster": () => {
        key = "invalid";
        throw new RelayError(409, { detail: { error: "key_invalid", message: "Key no longer valid" } }, "Key no longer valid");
      },
    });
    renderWithProviders(<Page />);
    expect(await screen.findByText("Key no longer valid. Paste a new key from the removal service.")).toBeTruthy();
    expect(screen.getByLabelText("Tracker key")).toBeTruthy();
    expect(screen.queryByText("Couldn't load the Creators.")).toBeNull();
    expect(setupGets()).toBe(2);
  });

  it("a stale copy shows the banner and each row's last checked time", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": { ...MERGED, stale: true } });
    renderWithProviders(<Page />);
    expect((await screen.findByRole("status")).textContent).toBe("The removal service is not reachable. Showing the last good copy.");
    const note = within(row("Creator A")!).getByTestId("of-creator-note").textContent ?? "";
    expect(note).toMatch(/^1 up now · 1 new today · last checked (Today|Yesterday) \d\d:05$/);
    expect(document.body.textContent).not.toContain("12:00");
  });

  it("with no copy the tracked Creators read not reachable", async () => {
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": { ...ROSTER, fetched_at: null, rows: ROSTER.rows.map((r) => ({ ...r, reachable: false })) },
    });
    renderWithProviders(<Page />);
    expect((await screen.findByRole("status")).textContent).toBe("The removal service is not reachable.");
    expect(within(row("Creator A")!).getByTestId("of-creator-note").textContent).toBe("Not reachable");
    expect(within(row("Creator B")!).getByTestId("of-creator-note").textContent).toBe("Not tracked");
  });

  it("at phone width the Creator dropdown with All Models on top replaces the column, with no sideways scroll", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED });
    const { container } = renderWithProviders(<Page />);
    const select = await screen.findByRole("combobox", { name: "Creator" });
    expect(select.closest(".md\\:hidden")).toBeTruthy();
    const column = screen.getByTestId("of-all-creators-row").closest("aside")!;
    expect(column).toHaveClass("hidden", "md:flex");
    expect(column).not.toContainElement(select);
    expect(select).toHaveTextContent("All Models");
    fireEvent.click(select);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(
      ["All Models", ...["Creator A", "Creator B", "Creator C"].map((n) => expect.stringMatching(new RegExp(`${n}$`)))]);
    fireEvent.click(screen.getByRole("option", { name: /Creator C/ }));
    expect(container.querySelector("[data-leak-view]")?.getAttribute("data-leak-view")).toBe("acc-c");
    for (let el = container.querySelector("[data-leak-view]"); el && el !== container; el = el.parentElement) {
      expect(el.className).not.toMatch(/(^|\s)(w-\[\d{3,}px\]|min-w-\[\d{3,}px\]|overflow-x-(auto|scroll))/);
    }
  });

  it("an owner tracks a Not tracked Creator with consent, and the entry reads Not checked yet", async () => {
    let saved = false;
    serve(setup({ key: "set", brand: "Example Removal" }), {
      "/admin/leaks/roster": () => (saved ? { ...ROSTER, rows: [...ROSTER.rows, { ...ROSTER.rows[0], account_id: "acc-b", name: "Creator B" }], untracked: [] } : ROSTER),
      "/admin/leaks/watches/acc-b": () => (saved ? tracked() : untracked()),
    });
    relayPut.mockImplementation(async () => { saved = true; return { synced: true }; });
    renderWithProviders(<Page />);
    const pane = await pick("Creator B");
    expect(pane.textContent).toContain("Not tracked");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    const handle = (await screen.findByLabelText(/^Handle/)) as HTMLInputElement;
    expect(handle.value).toBe("miavale");
    expect(handle.readOnly).toBe(true);
    expect(screen.getByText("Verified from the live session")).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe("Mia Vale");
    expect(screen.getByTestId("leak-consent-text").textContent).toBe(
      "I confirm this Creator agreed to leak tracking. This sends their handle, display name, aliases and linked socials to "
      + "Example Removal, which checks leak sites daily and keeps the list of leak links and any removal notices while tracking "
      + "is on. Pausing keeps it; deleting removes it within 30 days (removal-case records stay with Example Removal if you're "
      + "their client).");
    const save = saveIn() as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/watches/acc-b", {
      username: "miavale", verified: true, display_name: "Mia Vale", aliases: [], instagram: null, x: null, consent: true,
    }, { accountId: "acc-b" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Creator B" }).textContent).toContain("Not checked yet"));
    await waitFor(() => expect(row("Creator B")?.textContent).toContain("Not checked yet"));
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-b", { accountId: "acc-b" });
  });

  it("tracking the first Creator refreshes All Models without a reload", async () => {
    let saved = false;
    serve(setup({ key: "set", brand: "Example Removal" }), {
      "/admin/leaks/all": () => (saved ? asAll("leaks") : NO_LEAKS),
      "/admin/leaks/watches/acc-b": () => (saved ? tracked() : untracked()),
    });
    relayPut.mockImplementation(async () => { saved = true; return { synced: true }; });
    renderWithProviders(<Page />, new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } }));
    await waitFor(() => expect(screen.getByRole("region", { name: "All Models" }).textContent).toContain("No Leaks found yet."));
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    await screen.findByLabelText(/^Handle/);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(saveIn());
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("of-all-creators-row"));
    expect(await screen.findByRole("list", { name: "All Leaks" })).toBeTruthy();
  });

  it("with no live identity the handle is typed and sent unverified", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/watches/acc-b": untracked({ username: "", display_name: "", verified: false }) });
    relayPut.mockResolvedValue({ synced: true });
    renderWithProviders(<Page />);
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    const handle = (await screen.findByLabelText(/^Handle/)) as HTMLInputElement;
    expect(handle.readOnly).toBe(false);
    expect(screen.getByText("Typed, not verified")).toBeTruthy();
    fireEvent.change(handle, { target: { value: "mia_vale" } });
    fireEvent.change(screen.getByLabelText(/^Aliases/), { target: { value: "mia.v" } });
    fireEvent.click(screen.getByRole("button", { name: "Add alias" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(saveIn());
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/watches/acc-b", expect.objectContaining({
      username: "mia_vale", verified: false, aliases: ["mia.v"], consent: true,
    }), { accountId: "acc-b" }));
  });

  it("each alias says whether it is searched on its own, and the display name only confirms", async () => {
    serve(setup({ key: "set" }));
    renderWithProviders(<Page />);
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    expect(await screen.findByText("Only used to confirm matches")).toBeTruthy();
    for (const value of ["miav", "vale.mia"]) {
      fireEvent.change(screen.getByLabelText(/^Aliases/), { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "Add alias" }));
    }
    const aliasRow = (name: string) => screen.getByRole("button", { name: `Remove ${name}` }).closest("li")!;
    expect(aliasRow("miav").textContent).toContain("Only with the handle");
    expect(aliasRow("vale.mia").textContent).toContain("Searched on its own");
  });

  it("the consent box names the removal service when /v1/me gives no brand", async () => {
    serve(setup({ key: "set", brand: null }));
    renderWithProviders(<Page />);
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    const text = (await screen.findByTestId("leak-consent-text")).textContent ?? "";
    expect(text).toContain("linked socials to the removal service, which checks");
    expect(text).toContain("records stay with the removal service if you're their client");
  });

  it("a Team Leader reads Not tracked and gets no form", async () => {
    serve(setup({ key: "set", is_owner: false, can_write: false }));
    renderWithProviders(<Page />);
    const pane = await pick("Creator B");
    expect(pane.textContent).toContain("Not tracked");
    expect(screen.queryByRole("button", { name: "Track this Creator" })).toBeNull();
    const done = await pick("Creator A");
    expect(done.textContent).toContain("Not checked yet");
    expect(screen.queryByRole("button", { name: "Edit identity" })).toBeNull();
  });

  it("the owner flips Tracking off and the entry and drill-in read Paused, then on resumes", async () => {
    let on = true;
    const rowOf = () => ({ ...ROSTER.rows[0], on });
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": () => ({ ...ROSTER, rows: [rowOf()] }),
      "/admin/leaks/watches/acc-a": () => ({ ...tracked(), identity: { ...tracked().identity, on } }),
    });
    relayPost.mockImplementation(async (_p: string, body: { on: boolean }) => { on = body.on; return { on }; });
    renderWithProviders(<Page />);
    await pick("Creator A");
    const sw = await screen.findByRole("switch", { name: "Tracking" });
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(sw.textContent).toContain("Tracking on");
    fireEvent.click(sw);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/tracking", { on: false }, { accountId: "acc-a" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Tracking" }).getAttribute("aria-checked")).toBe("false"));
    expect(screen.getByRole("switch", { name: "Tracking" }).textContent).toContain("Paused");
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Paused"));
    fireEvent.click(screen.getByRole("switch", { name: "Tracking" }));
    await waitFor(() => expect(relayPost).toHaveBeenLastCalledWith("/admin/leaks/watches/acc-a/tracking", { on: true }, { accountId: "acc-a" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Tracking" }).textContent).toContain("Tracking on"));
  });

  it("a Creator paused by the service reads Paused since its date", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-c": tracked() });
    renderWithProviders(<Page />);
    await pick("Creator C");
    expect((await screen.findByRole("switch", { name: "Tracking" })).textContent).toContain("Paused since 20 Nov");
  });

  it("a refused flip says why and keeps the switch", async () => {
    serve(setup({ key: "set" }));
    relayPost.mockRejectedValue(new RelayError(403, {}, "Only the owner or an Admin can change this"));
    renderWithProviders(<Page />);
    await pick("Creator A");
    fireEvent.click(await screen.findByRole("switch", { name: "Tracking" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Only the owner or an Admin can change this");
    expect(screen.getByRole("switch", { name: "Tracking" }).getAttribute("aria-checked")).toBe("true");
  });

  it("a Team Leader reads the tracking state with no switch", async () => {
    serve(setup({ key: "set", is_owner: false, can_write: false }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-c": tracked() });
    renderWithProviders(<Page />);
    const pane = await pick("Creator C");
    await waitFor(() => expect(pane.textContent).toContain("Paused since 20 Nov"));
    expect(screen.queryByRole("switch")).toBeNull();
    const a = await pick("Creator A");
    await waitFor(() => expect(a.textContent).toContain("Tracking on"));
    expect(within(a).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("the owner deletes a tracked Creator: the entry reads Not tracked at once and the page goes back to All Models", async () => {
    let deleted = false;
    const later = () => new Promise(() => {});
    serve(setup({ key: "set", brand: "Example Removal" }), {
      "/admin/leaks/roster": () => (deleted ? later() : MERGED),
      "/admin/leaks/all": () => (deleted ? NO_LEAKS : asAll("leaks")),
    });
    relayDelete.mockImplementation(async () => { deleted = true; return { tracked: false }; });
    renderWithProviders(<><Page /><IfConfirmHost /></>);
    await screen.findByRole("list", { name: "All Leaks" });
    const pane = await pick("Creator A");
    fireEvent.click(await within(pane).findByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("dialog", { name: "Confirm" });
    expect(ask.textContent).toContain("Delete Leak tracking for Creator A?");
    expect(ask.textContent).toContain("Tracking stops now, and Example Removal removes the data within 30 days.");
    expect(relayDelete).not.toHaveBeenCalled();
    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith("/admin/leaks/watches/acc-a", { accountId: "acc-a" }));
    expect(await screen.findByRole("region", { name: "All Models" })).toBeTruthy();
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks", { scroll: false });
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Not tracked"));
    const all = screen.getByRole("region", { name: "All Models" });
    expect(all.textContent).toContain("No Leaks found yet.");
    expect(within(all).queryByRole("button", { name: "Creator A" })).toBeNull();
    expect(relayDelete).toHaveBeenCalledTimes(1);
  });

  it("cancelling the delete sends nothing and keeps the drill-in", async () => {
    serve(setup({ key: "set" }));
    renderWithProviders(<><Page /><IfConfirmHost /></>);
    const pane = await pick("Creator A");
    fireEvent.click(await within(pane).findByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("dialog", { name: "Confirm" });
    expect(ask.textContent).toContain("the removal service removes the data within 30 days");
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Confirm" })).toBeNull());
    expect(relayDelete).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Creator A" })).toBeTruthy();
  });

  it("a refused delete says why and keeps the drill-in", async () => {
    serve(setup({ key: "set" }));
    relayDelete.mockRejectedValue(new RelayError(409, {}, "Connect the removal service again before deleting"));
    renderWithProviders(<><Page /><IfConfirmHost /></>);
    const pane = await pick("Creator A");
    fireEvent.click(await within(pane).findByRole("button", { name: "Delete" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Confirm" })).getByRole("button", { name: "Delete" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Connect the removal service again before deleting");
    expect(screen.getByRole("region", { name: "Creator A" })).toBeTruthy();
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a", { scroll: false });
  });

  it("an edit the service already deleted reopens as the Track form with consent, and saving with consent tracks anew", async () => {
    let state: "tracked" | "gone" | "again" = "tracked";
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": () => (state === "gone" ? { ...ROSTER, rows: [], untracked: [...ROSTER.untracked, { account_id: "acc-a", name: "Creator A" }] } : ROSTER),
      "/admin/leaks/watches/acc-a": () => (state === "gone" ? untracked() : tracked()),
    });
    relayPut.mockImplementation(async (_p: string, body: { consent?: boolean }) => {
      if (state === "tracked") {
        state = "gone";
        throw new RelayError(409, {}, "The removal service already deleted this watch; save again to track this Creator anew");
      }
      if (!body.consent) throw new RelayError(422, {}, "consent missing");
      state = "again";
      return { synced: true };
    });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    fireEvent.click(await within(pane).findByRole("button", { name: "Edit identity" }));
    expect(await screen.findByRole("heading", { name: "Edit Creator A" })).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    fireEvent.click(saveIn());
    expect(await screen.findByRole("heading", { name: "Track Creator A" })).toBeTruthy();
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Not tracked"));
    const save = saveIn() as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenLastCalledWith("/admin/leaks/watches/acc-a",
      expect.objectContaining({ consent: true }), { accountId: "acc-a" }));
    await waitFor(() => expect(screen.queryByRole("form", { name: "Leak identity" })).toBeNull());
    expect(relayPut).toHaveBeenCalledTimes(2);
    expect(await within(screen.getByRole("region", { name: "Creator A" })).findByRole("button", { name: "Edit identity" })).toBeTruthy();
  });

  it("a refused save keeps the form and says why", async () => {
    serve(setup({ key: "set" }));
    relayPut.mockRejectedValue(new RelayError(409, {}, "Another Creator in this agency already uses that handle"));
    renderWithProviders(<Page />);
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(saveIn());
    expect((await screen.findByRole("alert")).textContent).toBe("Another Creator in this agency already uses that handle");
    expect(screen.getByRole("form", { name: "Leak identity" })).toBeTruthy();
  });

  it("a save the service did not take yet reads saved, synced later", async () => {
    let saved = false;
    serve(setup({ key: "set", brand: "Example Removal" }), { "/admin/leaks/watches/acc-b": () => (saved ? tracked(false) : untracked()) });
    relayPut.mockImplementation(async () => { saved = true; return { synced: false }; });
    renderWithProviders(<Page />);
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(saveIn());
    expect((await screen.findByRole("status")).textContent).toBe("Saved. It reaches Example Removal on the next sync.");
  });
});

describe("/creators/leaks lists the Leaks", () => {
  const KEY_REFUSED = () => new RelayError(409, { detail: { error: "key_invalid", message: "Key no longer valid" } }, "Key no longer valid");

  it("switching Agency closes the Start removal popup", async () => {
    const offer = { brand: "Example Removal", contact_url: "https://removal.example/contact", angle: "came_back", n: 1 };
    const removal = { status: "none", view: "offer", notices_updated_at: "2026-11-27T04:05:00Z", stale: false, counts: null };
    const scenes = { google: [], google_images: [], mega: [], forum: [], x: [] };
    window.history.replaceState({}, "", "/creators/leaks?open=acc-a");
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": MERGED,
      "/admin/leaks/watches/acc-a": { ...drill(CREATOR_LEAKS), removal, offer },
      "/admin/leaks/watches/acc-a/offer": { offer, preview_leak: null, video: null, scenes, last_checked_at: null },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(["leak-tracker", "setup", "acc-b"], setup({ key: "set" }));
    client.setQueryData(["leak-tracker", "roster", "acc-b"], MERGED);
    const { rerender } = renderWithProviders(<Page />, client);
    const pane = await screen.findByRole("region", { name: "Creator A" });
    fireEvent.click(await within(pane).findByRole("button", { name: "Contact us to start removal" }));
    expect(await screen.findByRole("dialog", { name: "Start removal with Example Removal" })).toBeTruthy();
    scopeAccount = "acc-b";
    rerender(<Page />);
    await screen.findByRole("region", { name: "Creator A" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("?open= selects that Creator in the main pane, with no dialog or sheet", async () => {
    window.history.replaceState({}, "", "/creators/leaks?open=acc-a");
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": drill(CREATOR_LEAKS) });
    const { container } = renderWithProviders(<Page />);
    const pane = await screen.findByRole("region", { name: "Creator A" });
    expect(container.querySelector("[data-leak-view]")?.getAttribute("data-leak-view")).toBe("acc-a");
    expect(row("Creator A")?.getAttribute("aria-current")).toBe("true");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container.querySelector("[role=dialog], [role=alertdialog], [data-sheet], [data-vaul-drawer]")).toBeNull();
    expect(pane.closest("[data-leak-view]")).toBeTruthy();
    expect(relayGet).not.toHaveBeenCalledWith("/admin/leaks/all", expect.anything());
  });

  it("an out-of-scope ?open= falls back to All Models and never reads that Creator", async () => {
    window.history.replaceState({}, "", "/creators/leaks?open=acc-z");
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED });
    const { container } = renderWithProviders(<Page />);
    expect(await screen.findByRole("region", { name: "All Models" })).toBeTruthy();
    expect(container.querySelector("[data-leak-view]")?.getAttribute("data-leak-view")).toBe("all");
    expect(screen.getByTestId("of-all-creators-row").getAttribute("aria-current")).toBe("true");
    expect(relayGet.mock.calls.some(([path]) => String(path).startsWith("/admin/leaks/watches/"))).toBe(false);
  });

  it("picking writes ?open= into the URL and All Models clears it", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED });
    renderWithProviders(<Page />);
    await pick("Creator A");
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a", { scroll: false });
    fireEvent.click(screen.getByTestId("of-all-creators-row"));
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks", { scroll: false });
    expect(await screen.findByRole("region", { name: "All Models" })).toBeTruthy();
  });

  it("All Models lists every Leak newest first with its Creator, and the Creator opens the drill-in", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/all": asAll("leaks"),
      [`/admin/leaks/all?cursor=${encodeURIComponent(CURSOR)}`]: asAll("leaks_page2") });
    renderWithProviders(<Page />);
    const list = await screen.findByRole("list", { name: "All Leaks" });
    expect(leakIds(list)).toEqual(["lk_0004", "lk_0003"]);
    expect(within(list).getAllByRole("button", { name: "Creator A" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(leakIds(screen.getByRole("list", { name: "All Leaks" })))
      .toEqual(["lk_0004", "lk_0003", "lk_0001", "lk_0002"]));
    expect(relayGet).toHaveBeenCalledWith(`/admin/leaks/all?cursor=${encodeURIComponent(CURSOR)}`, { accountId: null });
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    fireEvent.click(within(screen.getByRole("list", { name: "All Leaks" })).getAllByRole("button", { name: "Creator A" })[0]);
    expect(await screen.findByRole("region", { name: "Creator A" })).toBeTruthy();
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a", { scroll: false });
  });

  it("every Leak link opens in a new tab with no referrer, and no media element renders anywhere", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/all": asAll("leaks") });
    const { container } = renderWithProviders(<Page />);
    const all = await screen.findByRole("list", { name: "All Leaks" });
    const check = (list: HTMLElement) => {
      const links = within(list).getAllByRole("link");
      expect(links.length).toBeGreaterThan(0);
      for (const a of links) {
        expect(a.getAttribute("target")).toBe("_blank");
        expect(a.getAttribute("rel")).toBe("noreferrer noopener");
      }
      expect(container.querySelector(MEDIA)).toBeNull();
    };
    check(all);
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": drill(CREATOR_LEAKS) });
    await pick("Creator A");
    check(await screen.findByRole("list", { name: "Creator A Leaks" }));
  });

  it("the drill-in shows the header, the timeline and the legend, and seeded Leaks never read new", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": drill(CREATOR_LEAKS) });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    const list = await within(pane).findByRole("list", { name: "Creator A Leaks" });
    expect(leakIds(list)).toEqual(["lk_0004", "lk_0003", "lk_0001", "lk_0002"]);
    expect(pane.textContent).toContain("@miavale · verified · Tracking on · Last checked");
    const counts = pane.querySelector('dl[aria-label="Counts"]')!;
    expect([...counts.querySelectorAll("div")].map((d) => d.textContent)).toEqual(
      ["Up now11 cached", "Gone0", "Listed1", "New today1"]);
    const item = (id: string) => list.querySelector(`[data-leak="${id}"]`) as HTMLElement;
    for (const id of ["lk_0003", "lk_0001", "lk_0002"]) {
      expect(item(id).textContent).toContain("Found on first scan");
      expect(item(id).textContent).not.toContain("New today");
    }
    expect(item("lk_0001").textContent).toContain("Came back");
    expect(within(item("lk_0001")).getByRole("list", { name: "Timeline" }).textContent).toMatch(/Came back/);
    expect(within(pane).getByRole("list", { name: "Pills legend" }).textContent).toContain("Gone from the site, but Google still shows it.");
  });

  it("a gone Leak whose Google visibility turned unknown reads Gone, not Cached", async () => {
    const unknown = CREATOR_LEAKS.map((l: { leak_id: string; events: unknown[] }) => (l.leak_id !== "lk_0002" ? l : {
      ...l, pill: "gone", events: [...l.events, { at: "2026-11-26T04:00:00Z", type: "google_seen", data: { visible: null } }],
    }));
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": drill(unknown) });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    const item = (await within(pane).findByRole("list", { name: "Creator A Leaks" })).querySelector('[data-leak="lk_0002"]') as HTMLElement;
    expect(item.textContent).toContain("Gone");
    expect(item.textContent).not.toContain("Cached");
    expect(within(item).getByRole("list", { name: "Timeline" }).textContent).not.toContain("Google");
  });

  it("the legend renders under All Models too", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/all": asAll("leaks") });
    renderWithProviders(<Page />);
    const legend = await screen.findByRole("list", { name: "Pills legend" });
    expect(within(legend).getAllByRole("listitem")).toHaveLength(5);
    const seeded = (await screen.findByRole("list", { name: "All Leaks" })).querySelector('[data-leak="lk_0003"]')!;
    expect(seeded.textContent).toContain("Found on first scan");
    expect(seeded.textContent).not.toContain("New today");
  });

  it("the drill-in pages by cursor", async () => {
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": MERGED,
      "/admin/leaks/watches/acc-a": drill(CREATOR_LEAKS.slice(0, 2), "c2"),
      "/admin/leaks/watches/acc-a?cursor=c2": drill(CREATOR_LEAKS.slice(2)),
    });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    expect(leakIds(await within(pane).findByRole("list", { name: "Creator A Leaks" }))).toEqual(["lk_0004", "lk_0003"]);
    fireEvent.click(within(pane).getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(leakIds(within(pane).getByRole("list", { name: "Creator A Leaks" })))
      .toEqual(["lk_0004", "lk_0003", "lk_0001", "lk_0002"]));
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-a?cursor=c2", { accountId: "acc-a" });
  });

  it("a later page that fails says so and Load more retries it", async () => {
    let down = true;
    const more = `/admin/leaks/all?cursor=${encodeURIComponent(CURSOR)}`;
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/all": asAll("leaks"),
      [more]: () => {
        if (down) throw new RelayError(503, { detail: "The removal service is not reachable" }, "The removal service is not reachable");
        return asAll("leaks_page2");
      } });
    renderWithProviders(<Page />);
    await screen.findByRole("list", { name: "All Leaks" });
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Couldn't load more Leaks.");
    expect(leakIds(screen.getByRole("list", { name: "All Leaks" }))).toEqual(["lk_0004", "lk_0003"]);
    down = false;
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(leakIds(screen.getByRole("list", { name: "All Leaks" })))
      .toEqual(["lk_0004", "lk_0003", "lk_0001", "lk_0002"]));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("with no copy the lists say not reachable, and a stale copy says so", async () => {
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": MERGED,
      "/admin/leaks/all": { ...NO_LEAKS, leaks: null },
      "/admin/leaks/watches/acc-a": { ...drill(CREATOR_LEAKS), stale: true },
    });
    renderWithProviders(<Page />);
    expect(await screen.findByText("The removal service is not reachable. Leaks show again once it answers.")).toBeTruthy();
    const pane = await pick("Creator A");
    expect(await within(pane).findByText("Showing the last good copy.")).toBeTruthy();
  });

  const LANES = golden("creator_one").lanes as Record<string, unknown>[];
  const TRIMMED = [{ field: "alias:0", value: "Mia V" }, { field: "instagram", value: "mia.vale" }];
  const COVERED = [
    LANES[0], LANES[1],
    { ...LANES[2], state: "reduced", reason: "listing_rotated", last_success_at: "2026-11-27T04:03:00Z", next_attempt_on: "2026-11-28" },
    { ...LANES[3], state: "waiting", reason: "cap_global", next_attempt_on: "2026-11-28" },
    { ...LANES[4], state: "reduced", reason: "cap_global", last_success_at: "2026-11-26T05:00:00Z", trimmed: TRIMMED },
    LANES[5],
  ];
  const covered = { ...drill(CREATOR_LEAKS), lanes: COVERED };
  const laneText = (pane: HTMLElement, lane: string) => pane.querySelector(`[data-lane="${lane}"]`)?.textContent ?? "";
  const WIDE = /(^|\s)(w-\[\d{3,}px\]|min-w-\[\d{3,}px\]|overflow-x-(auto|scroll))/;

  it("the drill-in Coverage section lists every lane with its chip, last OK, next attempt and skipped names", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": covered });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    const coverage = await within(pane).findByRole("region", { name: "Coverage" });
    expect(within(coverage).getAllByRole("listitem").map((li) => li.dataset.lane)).toEqual(
      ["origin_probe", "mega_lookup", "listing_recheck", "google_fresh", "google_full", "registry_crawl"]);
    expect(laneText(coverage, "origin_probe")).toMatch(/^Link checkOKlast OK .+ agonext attempt Sat 28 Nov( 2026)?$/);
    expect(laneText(coverage, "mega_lookup")).toMatch(/^MegaFailedlast OK .+ ago/);
    expect(laneText(coverage, "listing_recheck")).toContain("Leak-site pagesReduced");
    expect(laneText(coverage, "listing_recheck")).toContain("each is re-read every few days");
    expect(laneText(coverage, "google_fresh")).toMatch(/^Google \(past day\)Waiting on budgetnext attempt Sat 28 Nov( 2026)?/);
    expect(laneText(coverage, "google_full")).toContain("Google full searchReduced");
    expect(laneText(coverage, "google_full")).toContain("Skipped: Mia V, Instagram");
    expect(laneText(coverage, "registry_crawl")).toBe("Leak-site searchNot run yet");
    expect(coverage.textContent).toContain("Known links are checked daily.");
    expect(pane.textContent?.toLowerCase()).not.toContain("next full search");
  });

  it("at phone width the Coverage section renders in the drill-in with no sideways scroll", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": covered });
    const { container } = renderWithProviders(<Page />);
    const select = await screen.findByRole("combobox", { name: "Creator" });
    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: /Creator A/ }));
    const coverage = await screen.findByRole("region", { name: "Coverage" });
    expect(within(coverage).getAllByRole("listitem")).toHaveLength(6);
    for (let el: HTMLElement | null = coverage; el && el !== container; el = el.parentElement) {
      expect(el.className).not.toMatch(WIDE);
    }
    for (const el of coverage.querySelectorAll("*")) expect(el.getAttribute("class") ?? "").not.toMatch(WIDE);
  });

  it("with no lanes read the drill-in shows no Coverage section", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": { ...drill(CREATOR_LEAKS), lanes: null } });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    await within(pane).findByRole("list", { name: "Creator A Leaks" });
    expect(within(pane).queryByRole("region", { name: "Coverage" })).toBeNull();
  });

  it("the identity form notes the names the last full Google search skipped", async () => {
    const identity = { ...tracked().identity, aliases: ["Mia V", "miavale.x"], instagram: "mia.vale", x: "miavale" };
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": { ...covered, identity } });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    fireEvent.click(await within(pane).findByRole("button", { name: "Edit identity" }));
    const form = await screen.findByRole("form", { name: "Leak identity" });
    expect(within(form).getByText("Skipped in the last full Google search to stay within budget: Mia V")).toBeTruthy();
    expect(within(form).getAllByText("Skipped in the last full Google search to stay within budget")).toHaveLength(1);
    fireEvent.change(within(form).getByLabelText("Instagram"), { target: { value: "mia.new" } });
    expect(within(form).queryByText("Skipped in the last full Google search to stay within budget")).toBeNull();
  });

  it.each([
    ["All Models", "/admin/leaks/all", null],
    ["the drill-in", "/admin/leaks/watches/acc-a", "acc-a"],
  ])("a refused key on %s sends the page to Key no longer valid", async (_label, path, open) => {
    if (open) window.history.replaceState({}, "", `/creators/leaks?open=${open}`);
    let key = "set";
    serve(setup(), {
      "/admin/leaks/setup": () => setup({ key, masked: "••••aaaa" }),
      "/admin/leaks/roster": MERGED,
      [path]: () => {
        key = "invalid";
        throw KEY_REFUSED();
      },
    });
    renderWithProviders(<Page />);
    expect(await screen.findByText("Key no longer valid. Paste a new key from the removal service.")).toBeTruthy();
    expect(screen.getByLabelText("Tracker key")).toBeTruthy();
    expect(setupGets()).toBe(2);
  });
});

describe("/creators/leaks shows the day's change", () => {
  type Service = { watch_id: string; account_id: string; today: Record<string, unknown> } & Record<string, unknown>;
  const service = ({ watch_id: _w, account_id: _a, lanes: _l, ...rest }: Service & { lanes?: unknown }) => rest;
  const [MIA_DAY, ROWAN_DAY] = golden("creators").creators as Service[];
  const PARTIAL_DAY = golden("creator_one") as Service;
  const EXTRA = [{ id: "acc-d", nickname: "Creator D" }, { id: "acc-e", nickname: "Creator E" }, { id: "acc-f", nickname: "Creator F" }];
  const TODAY_ROSTER = {
    ...ROSTER,
    rows: [
      { account_id: "acc-a", name: "Creator A", ...LOCAL, ...service(MIA_DAY) },
      { account_id: "acc-c", name: "Creator C", ...LOCAL, username: "rowanash", ...service(ROWAN_DAY) },
      { account_id: "acc-d", name: "Creator D", ...LOCAL, ...service(PARTIAL_DAY) },
      { account_id: "acc-e", name: "Creator E", ...LOCAL, ...MIA_SERVICE,
        today: { ...MIA_DAY.today, state: "pending", new: 0, first_scan: 3 } },
      { account_id: "acc-f", name: "Creator F", ...LOCAL, ...MIA_SERVICE, today: { ...MIA_DAY.today, state: "coverage_reduced", new: 0 } },
      { account_id: "acc-x", name: "Creator X", ...LOCAL, ...MIA_SERVICE,
        today: { ...MIA_DAY.today, state: "partial", new: 5, gone: 2, first_scan: 7 } },
    ],
  };
  const LINE = "2 new today · 0 came back · 0 gone · checked 1 of 4 · 2 partial · 3 found on first scans";
  const WIDE = /(^|\s)(w-\[\d{3,}px\]|min-w-\[\d{3,}px\]|overflow-x-(auto|scroll))/;
  const chipOf = (r: HTMLElement | undefined) => (r && within(r).queryByTestId("of-creator-chip")?.textContent) ?? null;

  beforeEach(() => { ACCOUNTS.push(...EXTRA); });
  afterEach(() => { ACCOUNTS.splice(3); });

  it("opens with the Agency's Today line over the Creators in the column, and each entry shows New today and its day marker", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": TODAY_ROSTER, "/admin/leaks/watches/acc-d": drill(CREATOR_LEAKS) });
    const { container } = renderWithProviders(<Page />);
    const today = await screen.findByRole("region", { name: "Today" });
    expect(today.textContent).toBe(LINE);
    const main = container.querySelector("[data-leak-view]")!.parentElement!;
    expect(main.firstElementChild).toBe(today);
    await waitFor(() => expect(row("Creator F")).toBeTruthy());
    expect(row("Creator X")).toBeUndefined();
    const entries = Object.fromEntries(["A", "B", "C", "D", "E", "F"].map((n) => {
      const r = row(`Creator ${n}`);
      return [n, [r && within(r).getByTestId("of-creator-note").textContent, chipOf(r)]];
    }));
    expect(entries).toEqual({
      A: ["1 up now · 1 new today", null],
      B: ["Not tracked", null],
      C: ["Paused since 20 Nov", "Paused"],
      D: ["1 up now · 1 new today", "Partial check"],
      E: ["1 up now", "Checking…"],
      F: ["1 up now", "Reduced"],
    });
    fireEvent.click(row("Creator D")!);
    await screen.findByRole("region", { name: "Creator D" });
    expect(screen.getByRole("region", { name: "Today" }).textContent).toBe(LINE);
  });

  it("at phone width the Today line tops the main pane and the Creator dropdown carries the day markers", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": TODAY_ROSTER });
    const { container } = renderWithProviders(<Page />);
    const select = await screen.findByRole("combobox", { name: "Creator" });
    const today = await screen.findByRole("region", { name: "Today" });
    expect(today.textContent).toBe(LINE);
    expect(today.closest(".md\\:hidden")).toBeNull();
    fireEvent.click(select);
    const chips = Object.fromEntries(screen.getAllByRole("option").map((o) => [
      o.textContent?.match(/Creator [A-F]|All Models/)?.[0], within(o).queryByTestId("of-creator-chip")?.textContent ?? null,
    ]));
    expect(chips).toEqual({
      "All Models": null, "Creator A": null, "Creator B": null, "Creator C": "Paused", "Creator D": "Partial check",
      "Creator E": "Checking…", "Creator F": "Reduced",
    });
    fireEvent.click(screen.getByRole("option", { name: /Creator D/ }));
    expect(container.querySelector("[data-leak-view]")?.getAttribute("data-leak-view")).toBe("acc-d");
    for (let el: HTMLElement | null = today; el && el !== container; el = el.parentElement) expect(el.className).not.toMatch(WIDE);
    for (const el of today.querySelectorAll("*")) expect(el.getAttribute("class") ?? "").not.toMatch(WIDE);
  });

  it("with no day read from the service there is no Today line and no marker", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED });
    renderWithProviders(<Page />);
    await waitFor(() => expect(row("Creator C")).toBeTruthy());
    expect(screen.queryByRole("region", { name: "Today" })).toBeNull();
    expect(screen.queryAllByTestId("of-creator-chip")).toEqual([]);
  });
});
