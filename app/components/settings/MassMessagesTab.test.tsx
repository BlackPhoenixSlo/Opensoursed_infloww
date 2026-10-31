/**
 * The Mass messages tab's bulk unsend, rendered over a mocked relay: OF's mass
 * unsend is irreversible, so a bulk button must cancel exactly the rows the
 * model chips and its own filter pick (massUnsendRules.ts `bulkTargets`), and
 * a declined confirm nothing. There are no per-row checkboxes: "selected" is
 * the chips' scope plus the action's filter.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => ACCOUNTS }));
vi.mock("@/lib/appliedSettings", () => ({ useAppliedSettings: () => ({ data: undefined }) }));

import MassMessagesTab from "@/components/settings/MassMessagesTab";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

const H = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

/** Per Creator, its cached broadcasts: every kind the bar tells apart. */
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
let confirmSpy: ReturnType<typeof vi.spyOn>;

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
  vi.spyOn(window, "alert").mockImplementation(() => undefined);
  confirmSpy = vi.spyOn(window, "confirm");
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // The rows are cached: the tab never asks OF for a refresh, nor writes anything but the cancels.
  expect(relayPost).not.toHaveBeenCalled();
});

async function mount() {
  render(<QueryClientProvider client={client}><MassMessagesTab /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText("b paid text old")).toBeTruthy(), { timeout: 5000 });
}

const button = (name: RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
/** The DELETEs sent, as "accountId:id". */
const cancels = () =>
  relayDelete.mock.calls.map(([path, ctx]) => `${(ctx as { accountId: string }).accountId}:${String(path).split("/").pop()}`);

describe("bulk unsend on the Mass messages tab", () => {
  it.each<[string, RegExp, string[]]>([
    ["free text >4h", /^Unsend free text >4h/, ["acc-a:101", "acc-a:102"]],
    ["non-image >4h", /^Unsend non-image/, ["acc-a:101", "acc-a:102", "acc-a:104"]],
    ["with images >4h", /^Unsend with images/, ["acc-a:103"]],
    ["Unsend all", /^Unsend all/, ["acc-a:101", "acc-a:102", "acc-a:103", "acc-a:104", "acc-a:105", "acc-a:108"]],
  ])("Model A's chip + %s, confirmed, cancels exactly that Creator's matching rows", async (_label, name, want) => {
    confirmSpy.mockReturnValue(true);
    await mount();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Model A" })); });
    expect(screen.queryByText("b free text old")).toBeNull();
    expect(button(name).textContent).toContain(`(${want.length})`);
    await act(async () => { fireEvent.click(button(name)); });
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(want.length));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(String(confirmSpy.mock.calls[0][0])).toContain(`Unsend ${want.length} broadcast`);
    expect(cancels().sort()).toEqual([...want].sort());
    for (const [path] of relayDelete.mock.calls) expect(String(path)).toMatch(/^\/api\/of\/v2\/messages\/queue\/\d+$/);
  });

  it("with no chip, free text >4h picks both Creators' matching rows", async () => {
    confirmSpy.mockReturnValue(true);
    await mount();
    await act(async () => { fireEvent.click(button(/^Unsend free text >4h/)); });
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(3));
    expect(cancels().sort()).toEqual(["acc-a:101", "acc-a:102", "acc-b:201"]);
  });

  it("a declined confirm sends nothing", async () => {
    confirmSpy.mockReturnValue(false);
    await mount();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Model B" })); });
    await act(async () => { fireEvent.click(button(/^Unsend all/)); });
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    await new Promise((r) => setTimeout(r, 50));
    expect(relayDelete).not.toHaveBeenCalled();
  });
});
