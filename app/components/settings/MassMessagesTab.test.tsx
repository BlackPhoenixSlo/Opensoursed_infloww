import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const ACCOUNTS = [
  { id: "acc-a", nickname: "Model A", has_session: true, is_active: true },
  { id: "acc-b", nickname: "Model B", has_session: true, is_active: true },
];
let accounts: Array<(typeof ACCOUNTS)[number] & { platform?: string }> = ACCOUNTS;
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => accounts }));
vi.mock("@/lib/appliedSettings", () => ({ useAppliedSettings: () => ({ data: undefined }) }));

import MassMessagesTab from "@/components/settings/MassMessagesTab";
import { SM, SM_MASS_ACTIONS } from "@/components/growth/smartMessagesControls";
import { BULK_ACTIONS } from "@/components/settings/massUnsendRules";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

const H = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

const ITEMS: Record<string, unknown[]> = {
  "acc-a": [
    { id: 101, date: ago(5 * H), text: "a free text old", isFree: true, mediaCount: 0, canUnsend: true },
    { id: 102, date: ago(6 * H), text: "", giphyId: "g1", isFree: true, mediaCount: 0, canUnsend: true },
    { id: 103, date: ago(5 * H), text: "a free image old", isFree: true, mediaCount: 2, canUnsend: true },
    { id: 104, date: ago(5 * H), text: "a paid text old", isFree: false, mediaCount: 0, canUnsend: true },
    { id: 105, date: ago(1 * H), text: "a free text fresh", isFree: true, mediaCount: 0, canUnsend: true },
    { id: 106, date: ago(7 * H), text: "a unsent", isFree: true, mediaCount: 0, canUnsend: false, isCanceled: true },
    { id: 107, date: ago(8 * H), text: "a OF says no", isFree: true, mediaCount: 0, canUnsend: false },
    { id: 108, date: null, text: "a no date", isFree: true, mediaCount: 0, canUnsend: true },
  ],
  "acc-b": [
    { id: 201, date: ago(5 * H), text: "b free text old", isFree: true, mediaCount: 0, canUnsend: true },
    { id: 202, date: ago(5 * H), text: "b free image old", isFree: true, mediaCount: 1, canUnsend: true },
    { id: 203, date: ago(9 * H), text: "b paid text old", isFree: false, mediaCount: 0, canUnsend: true },
  ],
};

let client: QueryClient;

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  [relayGet, relayPost, relayDelete].forEach((m) => m.mockReset());
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/mass-messages")) {
      const aid = new URLSearchParams(p.split("?")[1]).get("account_id") ?? "";
      return Promise.resolve({ account_id: aid, days_back: 30, items: ITEMS[aid] ?? [] });
    }
    if (p.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: [] });
    return Promise.resolve({});
  });
  relayDelete.mockResolvedValue({ success: true });
  vi.spyOn(window, "alert").mockImplementation(() => { throw new Error("window.alert"); });
  vi.spyOn(window, "confirm").mockImplementation(() => { throw new Error("window.confirm"); });
});
afterEach(() => {
  cleanup();
  accounts = ACCOUNTS;
  vi.restoreAllMocks();
  expect(relayPost).not.toHaveBeenCalled();
});

async function mount() {
  render(<QueryClientProvider client={client}><MassMessagesTab /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText("b paid text old")).toBeTruthy(), { timeout: 5000 });
}

const button = (name: RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
async function answer(choice: "Unsend" | "Cancel"): Promise<string> {
  const dialog = await screen.findByRole("dialog");
  const text = dialog.textContent ?? "";
  await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: choice })); });
  return text;
}
const cancels = () =>
  relayDelete.mock.calls.map(([path, ctx]) => `${(ctx as { accountId: string }).accountId}:${String(path).split("/").pop()}`);

describe("bulk unsend on the Mass messages tab", () => {
  it.each<[string, RegExp, string[]]>([
    ["free text >4h", /^Unsend free text >4h/, ["acc-a:101", "acc-a:102"]],
    ["non-image >4h", /^Unsend non-image/, ["acc-a:101", "acc-a:102", "acc-a:104"]],
    ["with images >4h", /^Unsend with images/, ["acc-a:103"]],
    ["Unsend all", /^Unsend all/, ["acc-a:101", "acc-a:102", "acc-a:103", "acc-a:104", "acc-a:105", "acc-a:108"]],
  ])("Model A's chip + %s, confirmed, cancels exactly that Creator's matching rows", async (_label, name, want) => {
    await mount();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Model A" })); });
    expect(screen.queryByText("b free text old")).toBeNull();
    expect(button(name).textContent).toContain(`(${want.length})`);
    await act(async () => { fireEvent.click(button(name)); });
    expect(relayDelete).not.toHaveBeenCalled();
    expect(await answer("Unsend")).toContain(`Unsend ${want.length} broadcast${want.length === 1 ? "" : "s"} of Model A from EVERY recipient`);
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(want.length));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(cancels().sort()).toEqual([...want].sort());
    for (const [path] of relayDelete.mock.calls) expect(String(path)).toMatch(/^\/api\/of\/v2\/messages\/queue\/\d+$/);
  });

  it("with no chip, free text >4h picks both Creators' matching rows", async () => {
    await mount();
    await act(async () => { fireEvent.click(button(/^Unsend free text >4h/)); });
    await answer("Unsend");
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(3));
    expect(cancels().sort()).toEqual(["acc-a:101", "acc-a:102", "acc-b:201"]);
  });

  it("a search over a Creator's full read (100 newest) says older matches may be hidden", async () => {
    const full = Array.from({ length: 100 }, (_, i) => ({ id: 1000 + i, date: ago((i + 1) * H), text: `promo ${i}`, canUnsend: false }));
    const base = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string) => String(path).includes("account_id=acc-b")
      ? Promise.resolve({ account_id: "acc-b", days_back: 30, items: [...ITEMS["acc-b"], ...full].slice(0, 100) })
      : base(path));
    await mount();
    expect(screen.queryByText(/older matches may be hidden/)).toBeNull();
    await act(async () => { fireEvent.change(screen.getByRole("textbox", { name: SM.search.label }), { target: { value: "promo" } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: SM.searchButton.label })); });
    expect(screen.getByText("Showing the newest 100 per Creator: older matches may be hidden.")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Model A" })); });
    expect(screen.queryByText(/older matches may be hidden/)).toBeNull();
  });

  it("a declined confirm sends nothing", async () => {
    await mount();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Model B" })); });
    await act(async () => { fireEvent.click(button(/^Unsend all/)); });
    await answer("Cancel");
    expect(screen.queryByRole("dialog")).toBeNull();
    await new Promise((r) => setTimeout(r, 50));
    expect(relayDelete).not.toHaveBeenCalled();
  });

  it("a row's Unsend asks first; the dialog's Unsend sends that one row's cancel", async () => {
    await mount();
    const row = screen.getByText("b paid text old").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Actions" }));
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: SM_MASS_ACTIONS.unsend.label })); });
    expect(relayDelete).not.toHaveBeenCalled();
    expect(await answer("Unsend")).toContain("Unsend this mass message from every recipient?");
    await waitFor(() => expect(cancels()).toEqual(["acc-b:203"]));
  });

  it("the button counts follow the clock: a row crossing 4h joins \"(N)\" within a minute", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setInterval", "clearInterval", "Date"] });
    try {
      await mount();
      expect(button(/^Unsend free text >4h/).textContent).toContain("(3)");
      await act(async () => { vi.advanceTimersByTime(3 * H + 60_000); });
      expect(button(/^Unsend free text >4h/).textContent).toContain("(4)");
    } finally {
      vi.useRealTimers();
    }
  });

  it("Unsend all with no chip deletes one at a time, Creator by Creator", async () => {
    let inFlight = 0;
    let peak = 0;
    relayDelete.mockImplementation(async () => {
      peak = Math.max(peak, ++inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight -= 1;
      return { success: true };
    });
    await mount();
    await act(async () => { fireEvent.click(button(/^Unsend all/)); });
    await answer("Unsend");
    await waitFor(() => expect(cancels()).toHaveLength(9));
    expect(peak).toBe(1);
    const creators = cancels().map((c) => c.split(":")[0]);
    expect(creators.filter((c, i) => i === 0 || c !== creators[i - 1])).toHaveLength(2);
  });

  function heldDeletes() {
    const waiting: (() => void)[] = [];
    relayDelete.mockImplementation(() => new Promise((res) => waiting.push(() => res({ success: true }))));
    return async () => {
      await waitFor(() => expect(waiting.length).toBeGreaterThan(0));
      await act(async () => { waiting.shift()!(); });
    };
  }
  const closeIsWarned = () => {
    const e = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(e);
    return e.defaultPrevented;
  };

  it("shows \"Unsending N of M…\" while it runs and warns before the tab closes until it ends", async () => {
    const release = heldDeletes();
    await mount();
    expect(closeIsWarned()).toBe(false);
    await act(async () => { fireEvent.click(button(/^Unsend free text >4h/)); });
    await answer("Unsend");
    expect(await screen.findByRole("status")).toHaveTextContent("Unsending 0 of 3…");
    expect(closeIsWarned()).toBe(true);
    await release();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Unsending 1 of 3…"));
    expect(relayDelete).toHaveBeenCalledTimes(2);
    await release();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Unsending 2 of 3…"));
    await release();
    await waitFor(() => expect(screen.queryByText(/^Unsending \d+ of/)).toBeNull());
    expect(closeIsWarned()).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a run whose deletes fail still ends the warning and leaves the failed note", async () => {
    relayDelete.mockRejectedValue(new Error("OF said no"));
    await mount();
    await act(async () => { fireEvent.click(button(/^Unsend free text >4h/)); });
    await answer("Unsend");
    expect(await screen.findByRole("alert")).toHaveTextContent("3 of 3 unsends failed.");
    expect(closeIsWarned()).toBe(false);
  });

  it("leaving the tab mid-run keeps the run: back on it, live N of M, buttons held, no second run", async () => {
    const release = heldDeletes();
    await mount();
    await act(async () => { fireEvent.click(button(/^Unsend free text >4h/)); });
    await answer("Unsend");
    await release();
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(2));
    cleanup();
    expect(closeIsWarned()).toBe(true);
    await mount();
    expect(screen.getByRole("status")).toHaveTextContent("Unsending 1 of 3…");
    const bar = screen.getAllByRole("button").filter((b) => /^(Unsend |Unsending)/.test(b.textContent ?? ""));
    expect(bar).toHaveLength(BULK_ACTIONS.length);
    for (const b of bar) expect((b as HTMLButtonElement).disabled).toBe(true);
    const row = screen.getByText("b paid text old").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Actions" }));
    expect((screen.getByRole("menuitem", { name: SM_MASS_ACTIONS.unsend.label }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    await release();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Unsending 2 of 3…"));
    await release();
    await waitFor(() => expect(screen.queryByText(/^Unsending \d+ of/)).toBeNull());
    expect(relayDelete).toHaveBeenCalledTimes(3);
    expect(closeIsWarned()).toBe(false);
  });

  it("some unsends failing says so under the bar, not in a browser alert", async () => {
    relayDelete.mockRejectedValueOnce(new Error("OF said no"));
    await mount();
    await act(async () => { fireEvent.click(button(/^Unsend free text >4h/)); });
    await answer("Unsend");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "1 of 3 unsends failed. Those broadcasts may still be live — refresh and retry.");
  });
});

describe("which Creators the Mass messages tab reads", () => {
  const FANSLY = { id: "acc-f", nickname: "Nova Reyes", has_session: true, is_active: true, platform: "fansly" };
  const NO_HISTORY = { id: "acc-x", nickname: "Model X", has_session: true, is_active: true, platform: "mym" };
  const BIG = ["900539700124344321", "900539700124344322"];
  const reads = () => relayGet.mock.calls.map(([p]) => String(p)).filter((p) => p.startsWith("/admin/mass-messages"))
    .map((p) => new URLSearchParams(p.split("?")[1]).get("account_id"));

  function serve(extra: Record<string, Record<string, unknown>>) {
    const base = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string) => {
      const aid = new URLSearchParams(String(path).split("?")[1]).get("account_id") ?? "";
      return String(path).startsWith("/admin/mass-messages") && extra[aid]
        ? Promise.resolve({ account_id: aid, days_back: 30, items: ITEMS[aid] ?? [], ...extra[aid] })
        : base(path);
    });
  }

  it("a Creator whose Platform lacks mass history gets no query and no chip", async () => {
    accounts = [...ACCOUNTS, NO_HISTORY];
    await mount();
    expect(reads().sort()).toEqual(["acc-a", "acc-b"]);
    expect(screen.queryByRole("button", { name: "Model X" })).toBeNull();
    expect(screen.getByRole("button", { name: "All (2)" })).toBeTruthy();
  });

  it("two adjacent big string ids render as two rows, neither offering an unsend", async () => {
    accounts = [...ACCOUNTS, FANSLY];
    serve({ "acc-f": { items: BIG.map((id) => ({ id, date: ago(5 * H), text: "nova hello", isFree: true, canUnsend: false, unsendSeconds: 0 })) } });
    const keyClash = vi.spyOn(console, "error");
    await mount();
    await waitFor(() => expect(screen.getAllByText("nova hello")).toHaveLength(2));
    expect(keyClash.mock.calls.flat().join(" ")).not.toMatch(/same key/);
    expect(button(/^Unsend all/).textContent).toContain("(9)");
    const row = screen.getAllByText("nova hello")[0].closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Actions" }));
    expect((screen.getByRole("menuitem", { name: SM_MASS_ACTIONS.unsend.label }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("the more-not-loaded line names only the Creator whose last read was incomplete", async () => {
    serve({ "acc-a": { hasMore: true, incomplete: true }, "acc-b": { hasMore: false, incomplete: false } });
    await mount();
    expect(await screen.findByText("Older broadcasts not loaded for Model A.")).toBeTruthy();
    expect(screen.queryByText(/Model B\./)).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Model B" })); });
    expect(screen.queryByText(/Older broadcasts not loaded/)).toBeNull();
  });

  it("no line when every read was whole or did not say", async () => {
    serve({ "acc-a": { hasMore: false, incomplete: false } });
    await mount();
    expect(screen.queryByText(/Older broadcasts not loaded/)).toBeNull();
  });
});
