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

import { leakKeys } from "@/components/leaks/leakKeys";
import Page from "@/app/creators/leaks/page";
import { IfConfirmHost } from "@/components/ui/ifConfirm";
import { relay, RelayError } from "@/lib/relay";
import { focusManager, QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "@/test-utils";
import { asAll, CREATOR_LEAKS, CURSOR, drill, golden, LOCAL, MERGED, MIA_SERVICE, NO_LEAKS, ROSTER, row, serve, setup, tracked, untracked } from "./leakPageHarness";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;
const KEY = "ltk_" + "a".repeat(40);
const setupGets = () => relayGet.mock.calls.filter(([path]) => path === "/admin/leaks/setup").length;
const MEDIA = "img, video, audio, picture, iframe, source, object, embed";
const leakIds = (list: HTMLElement) => within(list).getAllByRole("listitem").filter((li) => li.dataset.leak).map((li) => li.dataset.leak);
const saveIn = () => within(screen.getByRole("form", { name: "Leak identity" })).getByRole("button", { name: "Save" });
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

  it("the owner pastes a key, the Relay checks it, and the page opens from the PUT answer alone with no key card or brand", async () => {
    serve(setup());
    relayPut.mockResolvedValue({ key: "set", masked: "••••aaaa", brand: "Example Removal" });
    renderWithProviders(<Page />);
    fireEvent.change(await screen.findByLabelText("Tracker key"), { target: { value: `  ${KEY} ` } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/key", { key: KEY }, { accountId: null }));
    expect((await screen.findByTestId("of-all-creators-row")).getAttribute("aria-current")).toBe("true");
    expect(screen.queryByRole("region", { name: "Connect the removal service" })).toBeNull();
    expect(document.body.textContent).not.toContain(KEY);
    expect(document.body.textContent).not.toContain("••••aaaa");
    expect(setupGets()).toBe(1);
  });

  it("a saved key reads set in every scope of the Agency without a refetch", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    serve(setup());
    scopeAccount = "acc-b";
    renderWithProviders(<Page />, client);
    expect(await screen.findByLabelText("Tracker key")).toBeTruthy();
    cleanup();
    scopeAccount = null;
    relayPut.mockResolvedValue({ key: "set", masked: "••••aaaa", brand: "Example Removal" });
    renderWithProviders(<Page />, client);
    fireEvent.change(await screen.findByLabelText("Tracker key"), { target: { value: KEY } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByTestId("of-all-creators-row");
    cleanup();
    scopeAccount = "acc-b";
    renderWithProviders(<Page />, client);
    await screen.findByTestId("of-all-creators-row");
    expect(screen.queryByLabelText("Tracker key")).toBeNull();
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

  it.each([
    ["the instance key", { source: "instance" as const, masked: null }],
    ["the owner's own key", { source: "own" as const, masked: "••••aaaa" }],
  ])("%s shows the owner no key card and no brand", async (_label, extra) => {
    serve(setup({ key: "set", brand: "Example Removal", ...extra }));
    const { container } = renderWithProviders(<Page />);
    await waitFor(() => expect(container.querySelector("[data-leak-view]")).toBeTruthy());
    expect(screen.queryByLabelText("Tracker key")).toBeNull();
    expect(document.body.textContent).not.toContain("Connected to");
    expect(document.body.textContent).not.toContain("••••aaaa");
  });

  it("a Team Leader with a set key sees no key card", async () => {
    serve(setup({ key: "set", is_owner: false, can_write: false }));
    const { container } = renderWithProviders(<Page />);
    await waitFor(() => expect(container.querySelector("[data-leak-view]")).toBeTruthy());
    expect(screen.queryByLabelText("Tracker key")).toBeNull();
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
        "Creator A": "1 up now",
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
    expect(note).toMatch(/^1 up now · last checked (Today|Yesterday) \d\d:05$/);
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

  it("an owner tracks a Not tracked Creator with no consent box, and the entry reads Not checked yet", async () => {
    scopeAccount = "acc-a";
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
    expect(screen.queryByRole("checkbox")).toBeNull();
    const save = saveIn() as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/watches/acc-b", {
      username: "miavale", verified: true, display_name: "Mia Vale", aliases: [], instagram: null, x: null,
    }, { accountId: "acc-a" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Creator B" }).textContent).toContain("Not checked yet"));
    await waitFor(() => expect(row("Creator B")?.textContent).toContain("Not checked yet"));
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-b", { accountId: "acc-a" });
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
    fireEvent.click(saveIn());
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/leaks/watches/acc-b", expect.objectContaining({
      username: "mia_vale", verified: false, aliases: ["mia.v"],
    }), { accountId: null }));
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
    scopeAccount = "acc-b";
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
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/tracking", { on: false }, { accountId: "acc-b" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Tracking" }).getAttribute("aria-checked")).toBe("false"));
    expect(screen.getByRole("switch", { name: "Tracking" }).textContent).toContain("Paused");
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Paused"));
    fireEvent.click(screen.getByRole("switch", { name: "Tracking" }));
    await waitFor(() => expect(relayPost).toHaveBeenLastCalledWith("/admin/leaks/watches/acc-a/tracking", { on: true }, { accountId: "acc-b" }));
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
    scopeAccount = "acc-b";
    let deleted = false;
    const later = () => new Promise(() => {});
    serve(setup({ key: "set", brand: "Example Removal" }), {
      "/admin/leaks/roster": () => (deleted ? later() : MERGED),
      "/admin/leaks/all": () => (deleted ? NO_LEAKS : asAll("leaks")),
    });
    relayDelete.mockImplementation(async () => { deleted = true; return { tracked: false }; });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const otherRoster = ["leak-tracker", "roster", "acc-a"];
    const otherWatch = ["leak-tracker", "watch", "acc-a", "acc-a"];
    client.setQueryData(otherRoster, MERGED);
    client.setQueryData(otherWatch, tracked());
    renderWithProviders(<><Page /><IfConfirmHost /></>, client);
    await screen.findByRole("list", { name: "All Leaks" });
    const pane = await pick("Creator A");
    fireEvent.click(await within(pane).findByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("dialog", { name: "Confirm" });
    expect(ask.textContent).toContain("Delete Leak tracking for Creator A?");
    expect(ask.textContent).toContain("Tracking stops now, and Example Removal removes the data within 30 days.");
    expect(relayDelete).not.toHaveBeenCalled();
    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith("/admin/leaks/watches/acc-a", { accountId: "acc-b" }));
    expect(await screen.findByRole("region", { name: "All Models" })).toBeTruthy();
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks", { scroll: false });
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Not tracked"));
    const all = screen.getByRole("region", { name: "All Models" });
    expect(all.textContent).toContain("No Leaks found yet.");
    expect(within(all).queryByRole("button", { name: "Creator A" })).toBeNull();
    expect(relayDelete).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(otherRoster)).toEqual(MERGED);
    expect(client.getQueryData(otherWatch)).toEqual(tracked());
    expect(client.getQueryState(otherRoster)?.isInvalidated).toBe(true);
    expect(client.getQueryState(otherWatch)?.isInvalidated).toBe(true);
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

  it("an edit the service already deleted reopens as the Track form, and saving tracks anew", async () => {
    let state: "tracked" | "gone" | "again" = "tracked";
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": () => (state === "gone" ? { ...ROSTER, rows: [], untracked: [...ROSTER.untracked, { account_id: "acc-a", name: "Creator A" }] } : ROSTER),
      "/admin/leaks/watches/acc-a": () => (state === "gone" ? untracked() : tracked()),
    });
    relayPut.mockImplementation(async () => {
      if (state === "tracked") {
        state = "gone";
        throw new RelayError(409, {}, "The removal service already deleted this watch; save again to track this Creator anew");
      }
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
    fireEvent.click(saveIn());
    await waitFor(() => expect(relayPut).toHaveBeenLastCalledWith("/admin/leaks/watches/acc-a",
      expect.objectContaining({ username: "miavale" }), { accountId: null }));
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
    await screen.findByLabelText(/^Handle/);
    relayGet.mockClear();
    fireEvent.click(saveIn());
    expect((await screen.findByRole("alert")).textContent).toBe("Another Creator in this agency already uses that handle");
    expect(screen.getByRole("form", { name: "Leak identity" })).toBeTruthy();
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/leaks/setup", { accountId: null }));
  });

  it("a save the service did not take yet reads saved, synced later", async () => {
    let saved = false;
    serve(setup({ key: "set", brand: "Example Removal" }), { "/admin/leaks/watches/acc-b": () => (saved ? tracked(false) : untracked()) });
    relayPut.mockImplementation(async () => { saved = true; return { synced: false }; });
    renderWithProviders(<Page />);
    await pick("Creator B");
    fireEvent.click(screen.getByRole("button", { name: "Track this Creator" }));
    await screen.findByLabelText(/^Handle/);
    fireEvent.click(saveIn());
    expect((await screen.findByRole("status")).textContent).toBe("Saved. It reaches Example Removal on the next sync.");
  });
});

describe("/creators/leaks lists the Leaks", () => {
  const KEY_REFUSED = () => new RelayError(409, { detail: { error: "key_invalid", message: "Key no longer valid" } }, "Key no longer valid");

  it("switching Agency closes the Start removal popup", async () => {
    scopeAccount = "acc-b";
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
    client.setQueryData(["leak-tracker", "setup", "acc-c"], setup({ key: "set" }));
    client.setQueryData(["leak-tracker", "roster", "acc-c"], MERGED);
    const { rerender } = renderWithProviders(<Page />, client);
    const pane = await screen.findByRole("region", { name: "Creator A" });
    fireEvent.click(await within(pane).findByRole("button", { name: "Contact us to start removal" }));
    expect(await screen.findByRole("dialog", { name: "Start removal with Example Removal" })).toBeTruthy();
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/offer", { accountId: "acc-b" });
    scopeAccount = "acc-c";
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
    expect(leakIds(list)).toEqual(["lk_0005", "lk_0004", "lk_0003", "lk_0001", "lk_0002"]);
    expect(pane.textContent).toContain("@miavale · verified · Tracking on · Last checked");
    const counts = pane.querySelector('dl[aria-label="Counts"]')!;
    expect([...counts.querySelectorAll("div")].map((d) => d.textContent)).toEqual(
      ["Up now11 cached", "Gone0", "Listed1"]);
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
    expect(leakIds(await within(pane).findByRole("list", { name: "Creator A Leaks" }))).toEqual(["lk_0005", "lk_0004"]);
    fireEvent.click(within(pane).getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(leakIds(within(pane).getByRole("list", { name: "Creator A Leaks" })))
      .toEqual(["lk_0005", "lk_0004", "lk_0003", "lk_0001", "lk_0002"]));
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-a?cursor=c2", { accountId: null });
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
    { ...LANES[3], state: "reduced", reason: "cap_global", last_success_at: "2026-11-26T05:00:00Z", trimmed: TRIMMED },
    LANES[4],
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
      ["origin_probe", "mega_lookup", "listing_recheck", "google_full", "registry_crawl"]);
    expect(laneText(coverage, "origin_probe")).toMatch(/^Link checkOKlast OK .+ agonext attempt Sat 28 Nov( 2026)?$/);
    expect(laneText(coverage, "mega_lookup")).toMatch(/^MegaFailedlast OK .+ ago/);
    expect(laneText(coverage, "listing_recheck")).toContain("Leak-site pagesReduced");
    expect(laneText(coverage, "listing_recheck")).toContain("each is re-read every few days");
    expect(laneText(coverage, "google_full")).toContain("Google full searchReduced");
    expect(laneText(coverage, "google_full")).toContain("Skipped: Mia V, Instagram");
    expect(laneText(coverage, "registry_crawl")).toBe("Leak-site searchNot run yet");
    expect(coverage.textContent).toContain("Each Creator is checked once a week on its scan day");
    expect(coverage.textContent).not.toContain("Google (past day)");
    expect(pane.textContent?.toLowerCase()).not.toContain("next full search");
  });

  it("at phone width the Coverage section renders in the drill-in with no sideways scroll", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": covered });
    const { container } = renderWithProviders(<Page />);
    const select = await screen.findByRole("combobox", { name: "Creator" });
    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: /Creator A/ }));
    const coverage = await screen.findByRole("region", { name: "Coverage" });
    expect(within(coverage).getAllByRole("listitem")).toHaveLength(5);
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

describe("/creators/leaks shows the week's change", () => {
  type Service = { watch_id: string; account_id: string; this_week: Record<string, unknown> } & Record<string, unknown>;
  const service = ({ watch_id: _w, account_id: _a, lanes: _l, ...rest }: Service & { lanes?: unknown }) => rest;
  const [MIA_WEEK, ROWAN_WEEK] = golden("creators").creators as Service[];
  const PARTIAL_WEEK = golden("creator_one") as Service;
  const EXTRA = [{ id: "acc-d", nickname: "Creator D" }, { id: "acc-e", nickname: "Creator E" }, { id: "acc-f", nickname: "Creator F" }];
  const QUIET = { ...MIA_WEEK.this_week, came_back: 0, gone: 0 };
  const WEEK_ROSTER = {
    ...ROSTER,
    rows: [
      { account_id: "acc-a", name: "Creator A", ...LOCAL, ...service(MIA_WEEK) },
      { account_id: "acc-c", name: "Creator C", ...LOCAL, username: "rowanash", ...service(ROWAN_WEEK) },
      { account_id: "acc-d", name: "Creator D", ...LOCAL, ...service(PARTIAL_WEEK) },
      { account_id: "acc-e", name: "Creator E", ...LOCAL, ...MIA_SERVICE, this_week: { ...QUIET, state: "pending", new: 0, first_scan: 3 } },
      { account_id: "acc-f", name: "Creator F", ...LOCAL, ...MIA_SERVICE, this_week: { ...QUIET, state: "coverage_reduced", new: 0 } },
      { account_id: "acc-x", name: "Creator X", ...LOCAL, ...MIA_SERVICE,
        this_week: { ...QUIET, state: "partial", new: 5, gone: 2, first_scan: 7 } },
    ],
  };
  const LINE = "2 new this week · 2 came back · 4 gone · checked 1 of 4 · 2 partial · 3 found on first scans";
  const WIDE = /(^|\s)(w-\[\d{3,}px\]|min-w-\[\d{3,}px\]|overflow-x-(auto|scroll))/;
  const chipOf = (r: HTMLElement | undefined) => (r && within(r).queryByTestId("of-creator-chip")?.textContent) ?? null;

  beforeEach(() => {
    ACCOUNTS.push(...EXTRA);
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-27T12:00:00Z") });
  });
  afterEach(() => {
    ACCOUNTS.splice(3);
    vi.useRealTimers();
  });

  it("opens with the Agency's This week line over the Creators in the column, and each entry shows new this week and its marker", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": WEEK_ROSTER, "/admin/leaks/watches/acc-d": drill(CREATOR_LEAKS) });
    const { container } = renderWithProviders(<Page />);
    const week = await screen.findByRole("region", { name: "This week" });
    expect(week.textContent).toBe(LINE);
    const main = container.querySelector("[data-leak-view]")!.parentElement!;
    expect(main.firstElementChild).toBe(week);
    await waitFor(() => expect(row("Creator F")).toBeTruthy());
    expect(row("Creator X")).toBeUndefined();
    const entries = Object.fromEntries(["A", "B", "C", "D", "E", "F"].map((n) => {
      const r = row(`Creator ${n}`);
      return [n, [r && within(r).getByTestId("of-creator-note").textContent, chipOf(r)]];
    }));
    expect(entries).toEqual({
      A: ["1 up now · 1 new this week", null],
      B: ["Not tracked", null],
      C: ["Paused since 20 Nov", "Paused"],
      D: ["1 up now · 1 new this week", "Partial check"],
      E: ["1 up now", "Checking…"],
      F: ["1 up now", "Reduced"],
    });
    fireEvent.click(row("Creator D")!);
    const pane = await screen.findByRole("region", { name: "Creator D" });
    await within(pane).findByRole("list", { name: "Creator D Leaks" });
    const counts = pane.querySelector('dl[aria-label="Counts"]')!;
    expect([...counts.querySelectorAll("div")].map((d) => d.textContent)).toContain("New this week1");
    expect(counts.textContent).not.toContain("New today");
    expect(screen.getByRole("region", { name: "This week" }).textContent).toBe(LINE);
  });

  it("at phone width the This week line tops the main pane and the Creator dropdown carries the markers", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": WEEK_ROSTER });
    const { container } = renderWithProviders(<Page />);
    const select = await screen.findByRole("combobox", { name: "Creator" });
    const week = await screen.findByRole("region", { name: "This week" });
    expect(week.textContent).toBe(LINE);
    expect(week.closest(".md\\:hidden")).toBeNull();
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
    for (let el: HTMLElement | null = week; el && el !== container; el = el.parentElement) expect(el.className).not.toMatch(WIDE);
    for (const el of week.querySelectorAll("*")) expect(el.getAttribute("class") ?? "").not.toMatch(WIDE);
  });

  it("with no this_week anywhere (a pre-change service) there is no This week line and no marker, and the roster loads", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED });
    renderWithProviders(<Page />);
    await waitFor(() => expect(row("Creator C")).toBeTruthy());
    expect(row("Creator A")!.textContent).toContain("1 up now");
    expect(screen.queryByRole("region", { name: "This week" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Today" })).toBeNull();
    expect(screen.queryAllByTestId("of-creator-chip")).toEqual([]);
  });
});

describe("/creators/leaks Refresh now", () => {
  const WEEK = golden("creator_one").this_week as Record<string, unknown>;
  const hoursFromNow = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  const read = (over: Record<string, unknown> = {}) =>
    ({ ...drill(CREATOR_LEAKS), this_week: { ...WEEK, state: "complete" }, next_refresh_at: hoursFromNow(-2), ...over });
  const WIDE = /(^|\s)(w-\[\d{3,}px\]|min-w-\[\d{3,}px\]|overflow-x-(auto|scroll))/;
  const button = (name: string | RegExp) => screen.findByRole("button", { name });
  const watchGets = () => relayGet.mock.calls.filter(([path]) => path === "/admin/leaks/watches/acc-a").length;
  const ONCE = "One refresh per Creator every 24 hours";
  const off = (b: HTMLElement) => b.getAttribute("aria-disabled") === "true";
  const rosterGets = () => relayGet.mock.calls.filter(([path]) => path === "/admin/leaks/roster").length;

  const ROSTER_WITHOUT_A = { ...MERGED, rows: MERGED.rows.slice(1), untracked: [...MERGED.untracked, { account_id: "acc-a", name: "Creator A" }] };
  const openDesktop = async () => { await pick("Creator A"); };
  const openPhone = async () => {
    fireEvent.click(await screen.findByRole("combobox", { name: "Creator" }));
    fireEvent.click(screen.getByRole("option", { name: /Creator A/ }));
  };

  it.each([["desktop", openDesktop], ["phone", openPhone]] as const)(
    "at %s width: Refresh now, then Refreshing…, then Checking… and the drill-in is read again", async (_w, open) => {
      let queued = false;
      let answer: (v: unknown) => void = () => {};
      serve(setup({ key: "set" }), {
        "/admin/leaks/roster": MERGED,
        "/admin/leaks/watches/acc-a": () => (queued ? read({ this_week: { ...WEEK, state: "pending" }, next_refresh_at: hoursFromNow(24) }) : read()),
      });
      relayPost.mockImplementation(() => new Promise((r) => { answer = r; }));
      const { container } = renderWithProviders(<Page />);
      await open();
      const now = await button("Refresh now");
      expect(off(now)).toBe(false);
      for (let el: HTMLElement | null = now; el && el !== container; el = el.parentElement) expect(el.className).not.toMatch(WIDE);
      const before = watchGets();
      fireEvent.click(now);
      expect(off(await button("Refreshing…"))).toBe(true);
      expect(relayPost).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/refresh", undefined, { accountId: null });
      queued = true;
      answer({ queued_at: hoursFromNow(0), next_refresh_at: hoursFromNow(24) });
      expect(off(await button("Checking…"))).toBe(true);
      await waitFor(() => expect(watchGets()).toBeGreaterThan(before));
      expect(screen.getByRole("button", { name: "Checking…" })).toBeTruthy();
      expect(relayPost).toHaveBeenCalledTimes(1);
    });

  it("a queued refresh marks the other scope's roster and drill-in stale too", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read() });
    relayPost.mockResolvedValue({ queued_at: "2026-11-27T12:00:00Z", next_refresh_at: hoursFromNow(24) });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const otherRoster = ["leak-tracker", "roster", "acc-a"];
    const otherWatch = ["leak-tracker", "watch", "acc-a", "acc-a"];
    client.setQueryData(otherRoster, MERGED);
    client.setQueryData(otherWatch, read());
    renderWithProviders(<Page />, client);
    await openDesktop();
    fireEvent.click(await button("Refresh now"));
    await waitFor(() => expect(client.getQueryState(otherRoster)?.isInvalidated).toBe(true));
    expect(client.getQueryState(otherWatch)?.isInvalidated).toBe(true);
  });

  it("a cooldown answer reads Next refresh, disabled, with the once-a-day note", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read() });
    const next = hoursFromNow(16);
    relayPost.mockRejectedValue(new RelayError(429, { detail: "Refreshed recently", next_refresh_at: next }, "Refreshed recently"));
    renderWithProviders(<Page />);
    await openDesktop();
    fireEvent.click(await button("Refresh now"));
    const b = await button(/^Next refresh /);
    expect(off(b)).toBe(true);
    expect(screen.getByText(ONCE)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([["desktop", openDesktop], ["phone", openPhone]] as const)(
    "at %s width a read inside the cooldown opens on Next refresh, and a pending week on Checking…", async (_w, open) => {
      serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read({ next_refresh_at: hoursFromNow(6) }) });
      renderWithProviders(<Page />);
      await open();
      expect(off(await button(/^Next refresh /))).toBe(true);
      expect(screen.getByText(ONCE)).toBeTruthy();
      cleanup();
      serve(setup({ key: "set" }), {
        "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read({ this_week: { ...WEEK, state: "pending" }, next_refresh_at: null }),
      });
      renderWithProviders(<Page />);
      await open();
      expect(off(await button("Checking…"))).toBe(true);
    });

  it("an error shows the detail inline and the button stays enabled", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read({ next_refresh_at: null }) });
    relayPost.mockRejectedValue(new RelayError(503, { detail: "The removal service is not reachable" }, "The removal service is not reachable"));
    renderWithProviders(<Page />);
    await openDesktop();
    fireEvent.click(await button("Refresh now"));
    expect((await screen.findByRole("alert")).textContent).toBe("The removal service is not reachable");
    expect(off(await button("Refresh now"))).toBe(false);
  });

  it("a Team Leader sees no button; nor does a Creator the service reads paused, or an untracked one", async () => {
    serve(setup({ key: "set", is_owner: false, can_write: false }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read() });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    await within(pane).findByRole("list", { name: "Creator A Leaks" });
    expect(within(pane).queryByRole("button", { name: /Refresh now|Next refresh|Checking…/ })).toBeNull();
    cleanup();
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-c": read({ this_week: { ...WEEK, state: "paused" }, next_refresh_at: null }),
    });
    renderWithProviders(<Page />);
    const paused = await pick("Creator C");
    await within(paused).findByRole("list", { name: "Creator C Leaks" });
    expect(within(paused).queryByRole("button", { name: "Refresh now" })).toBeNull();
    const off = await pick("Creator B");
    await waitFor(() => expect(off.textContent).toContain("Not tracked"));
    expect(within(off).queryByRole("button", { name: "Refresh now" })).toBeNull();
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("uses the rate-limit kind even when the relay copy changes", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read() });
    const next = hoursFromNow(1);
    relayPost.mockRejectedValue(new RelayError(429, {
      detail: "Please retry later", kind: "rate_limited", next_refresh_at: next,
    }, "Please retry later"));
    renderWithProviders(<Page />);
    await openDesktop();
    fireEvent.click(await button("Refresh now"));
    expect(off(await button(/^Next refresh /))).toBe(true);
    expect(await screen.findByText("Please retry later")).toBeVisible();
  });

  it("a rate limit shows Try again shortly inline, keeps the button enabled and re-reads nothing", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read({ next_refresh_at: null }) });
    relayPost.mockRejectedValue(new RelayError(429, { detail: "Try again shortly", next_refresh_at: null }, "Try again shortly"));
    renderWithProviders(<Page />);
    await openDesktop();
    const before = watchGets();
    fireEvent.click(await button("Refresh now"));
    expect((await screen.findByRole("alert")).textContent).toBe("Try again shortly");
    expect(off(await button("Refresh now"))).toBe(false);
    expect(watchGets()).toBe(before);
  });

  it("a disabled button keeps focus and a click does nothing; the note describes it", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read({ next_refresh_at: hoursFromNow(6) }) });
    renderWithProviders(<Page />);
    await openDesktop();
    const b = await button(/^Next refresh /);
    expect(b.hasAttribute("disabled")).toBe(false);
    b.focus();
    fireEvent.click(b);
    expect(document.activeElement).toBe(b);
    expect(relayPost).not.toHaveBeenCalled();
    expect(document.getElementById(b.getAttribute("aria-describedby")!)?.textContent).toBe(ONCE);
    expect(screen.getAllByRole("status").some((el) => el.textContent?.startsWith("Next refresh "))).toBe(true);
  });

  it("a 409 watch_paused re-reads the drill-in and the button goes away", async () => {
    let paused = false;
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": () => (paused ? { ...MERGED, rows: MERGED.rows.map((r) => (r.account_id === "acc-a" ? { ...r, paused: true } : r)) } : MERGED),
      "/admin/leaks/watches/acc-a": () => (paused ? read({ this_week: { ...WEEK, state: "paused" }, next_refresh_at: null }) : read()),
    });
    relayPost.mockImplementation(async () => {
      paused = true;
      throw new RelayError(409, { detail: "Tracking is off for this Creator" }, "Tracking is off for this Creator");
    });
    renderWithProviders(<Page />);
    await openDesktop();
    const before = [watchGets(), rosterGets()];
    fireEvent.click(await button("Refresh now"));
    await waitFor(() => expect(watchGets()).toBeGreaterThan(before[0]));
    expect(rosterGets()).toBeGreaterThan(before[1]);
    await waitFor(() => expect(screen.queryByRole("button", { name: /Refresh now|Next refresh|Checking…/ })).toBeNull());
  });

  it("a 404 (the watch was deleted upstream) re-reads the drill-in and the roster", async () => {
    let gone = false;
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": () => (gone ? ROSTER_WITHOUT_A : MERGED),
      "/admin/leaks/watches/acc-a": () => (gone ? untracked() : read()),
    });
    relayPost.mockImplementation(async () => {
      gone = true;
      throw new RelayError(404, { detail: "Not Found" }, "Not Found");
    });
    renderWithProviders(<Page />);
    await openDesktop();
    const before = [watchGets(), rosterGets()];
    fireEvent.click(await button("Refresh now"));
    await waitFor(() => expect(watchGets()).toBeGreaterThan(before[0]));
    expect(rosterGets()).toBeGreaterThan(before[1]);
    await waitFor(() => expect(row("Creator A")?.textContent).toContain("Not tracked"));
  });

  it("a refused key from refresh re-reads the setup", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read() });
    relayPost.mockRejectedValue(new RelayError(409, { detail: { error: "key_invalid", message: "Key no longer valid" } }, "Key no longer valid"));
    renderWithProviders(<Page />);
    await openDesktop();
    const before = setupGets();
    fireEvent.click(await button("Refresh now"));
    await waitFor(() => expect(setupGets()).toBeGreaterThan(before));
  });

  it.each([
    ["switched off in the drill-in", { identity: { ...tracked().identity, on: false } }],
    ["not yet synced to the service", { synced: false }],
  ])("no button when the Creator is %s", async (_label, over) => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": read(over) });
    renderWithProviders(<Page />);
    const pane = await pick("Creator A");
    await within(pane).findByRole("list", { name: "Creator A Leaks" });
    expect(within(pane).queryByRole("button", { name: /Refresh now|Next refresh|Checking…/ })).toBeNull();
  });

  it("a pending read polls and completion invalidates the roster, All Models, strip and Google", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let done = false;
      serve(setup({ key: "set" }), {
        "/admin/leaks/roster": MERGED,
        "/admin/leaks/watches/acc-a": () => (done ? read() : read({ this_week: { ...WEEK, state: "pending" }, next_refresh_at: null })),
      });
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
      const keys = [leakKeys.all(null), leakKeys.strip(null), leakKeys.google("acc-a", null)];
      renderWithProviders(<Page />, client);
      await openDesktop();
      for (const key of keys) client.setQueryData(key, { pages: [], pageParams: [] });
      expect(off(await button("Checking…"))).toBe(true);
      const before = [watchGets(), rosterGets()];
      done = true;
      await vi.advanceTimersByTimeAsync(30_000);
      await waitFor(() => expect(watchGets()).toBeGreaterThan(before[0]));
      expect(off(await button("Refresh now"))).toBe(false);
      await waitFor(() => expect(rosterGets()).toBeGreaterThan(before[1]));
      for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
      const settled = watchGets();
      await vi.advanceTimersByTimeAsync(90_000);
      expect(watchGets()).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("polls after a refresh acknowledgement even when the first read fails, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let phase = "idle";
      serve(setup({ key: "set" }), {
        "/admin/leaks/roster": MERGED,
        "/admin/leaks/watches/acc-a": () => {
          if (phase === "failed") throw new RelayError(503, null);
          if (phase === "pending") return read({ this_week: { ...WEEK, state: "pending" } });
          if (phase === "complete") return read({ next_refresh_at: hoursFromNow(24) });
          return read();
        },
      });
      relayPost.mockImplementation(async () => {
        phase = "failed";
        return { queued_at: hoursFromNow(0), next_refresh_at: hoursFromNow(24) };
      });
      renderWithProviders(<Page />);
      await openDesktop();
      fireEvent.click(await button("Refresh now"));
      await button("Checking…");
      focusManager.setFocused(false);
      const hidden = watchGets();
      await vi.advanceTimersByTimeAsync(30_000);
      expect(watchGets()).toBe(hidden);
      focusManager.setFocused(true);
      const before = watchGets();
      await vi.advanceTimersByTimeAsync(30_000);
      expect(watchGets()).toBeGreaterThan(before);
      phase = "pending";
      await vi.advanceTimersByTimeAsync(600_000);
      expect(off(await button("Check refresh status"))).toBe(false);
      const settled = watchGets();
      await vi.advanceTimersByTimeAsync(90_000);
      expect(watchGets()).toBe(settled);
      phase = "complete";
      fireEvent.click(await button("Check refresh status"));
      expect(off(await button(/^Next refresh /))).toBe(true);
      expect(watchGets()).toBeGreaterThan(settled);
      expect(relayPost).toHaveBeenCalledTimes(1);
    } finally {
      focusManager.setFocused(undefined);
      vi.useRealTimers();
    }
  });

  it("enables refresh on an idle tab when the cooldown expires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED,
        "/admin/leaks/watches/acc-a": read({ next_refresh_at: new Date(Date.now() + 5_000).toISOString() }) });
      renderWithProviders(<Page />);
      await openDesktop();
      expect(off(await button(/^Next refresh /))).toBe(true);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(off(await button("Refresh now"))).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
