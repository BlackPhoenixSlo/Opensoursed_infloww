import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
vi.mock("@/components/shell/useFlags", () => ({ useFlags: () => ({ fansly_manager: false, leak_tracker: true }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "acc-a", nickname: "Mia Vale" }] }));
let employeeKey: string | null = "emp-1";
vi.mock("@/hooks/useEmployeeKey", () => ({ useEmployeeKey: () => employeeKey, usePrincipalId: () => "owner-1" }));

import { PREVIEW_LINE } from "@/components/leaks/LeakDisclaimer";
import { LeakTracker } from "@/components/leaks/LeakTracker";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const TITLE = "These results are automated";
const body = (brand: string) =>
  `Every link here was found by bots that scrape Google, Mega and pirate sites. Some may be wrong or not about this Creator. ${brand} personally checks every leak before any removal starts.`;
const setup = (over: Record<string, unknown> = {}) =>
  ({ key: "set", masked: "••••aaaa", is_owner: true, can_write: true, brand: "Example Removal", previews: true, ...over });
const dialog = () => screen.queryByRole("dialog", { name: TITLE });
const ROSTER = { rows: [], untracked: [{ account_id: "acc-a", name: "Mia Vale" }], stale: false, fetched_at: null };
const open = async (over: Record<string, unknown> = {}) => {
  relayGet.mockImplementation(async (path: string) => (path === "/admin/leaks/roster" ? ROSTER : setup(over)));
  renderWithProviders(<LeakTracker />);
  await screen.findByTestId("of-all-creators-row");
};

beforeEach(() => {
  window.localStorage.clear();
  employeeKey = "emp-1";
  for (const m of Object.values(relay) as Mock[]) m.mockReset();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Leak disclaimer", () => {
  it("first open of the results view shows the dialog with the brand", async () => {
    await open();
    const d = await screen.findByRole("dialog", { name: TITLE });
    expect(within(d).getByText(body("Example Removal"))).toBeTruthy();
    expect(within(d).getAllByRole("button").map((b) => b.textContent || b.getAttribute("aria-label"))).toEqual(["Close", "Got it"]);
  });

  it("previews on: the dialog adds the preview line and closing writes the v2 key", async () => {
    await open();
    const d = await screen.findByRole("dialog", { name: TITLE });
    expect(within(d).getByText(PREVIEW_LINE)).toBeTruthy();
    expect(PREVIEW_LINE).toBe("Google previews are automated search matches. They can be explicit or show someone else. "
      + "They stay blurred until you click one, and this app keeps no copy.");
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(window.localStorage.getItem("chatterly:leak_disclaimer_seen:v2:emp-1")).toBe("1");
    expect(window.localStorage.getItem("chatterly:leak_disclaimer_seen:emp-1")).toBeNull();
  });

  it("previews on: a person who closed the old text sees the dialog once more", async () => {
    window.localStorage.setItem("chatterly:leak_disclaimer_seen:emp-1", "1");
    await open();
    expect(await screen.findByRole("dialog", { name: TITLE })).toBeTruthy();
  });

  it("previews off: no preview line, the old key is written and still keeps it shut", async () => {
    await open({ previews: false });
    const d = await screen.findByRole("dialog", { name: TITLE });
    expect(within(d).getByText(body("Example Removal"))).toBeTruthy();
    expect(within(d).queryByText(PREVIEW_LINE)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(window.localStorage.getItem("chatterly:leak_disclaimer_seen:emp-1")).toBe("1");
    expect(window.localStorage.getItem("chatterly:leak_disclaimer_seen:v2:emp-1")).toBeNull();
    cleanup();
    await open({ previews: false });
    expect(dialog()).toBeNull();
  });

  it("previews off: someone who closed the v2 text sees no dialog", async () => {
    window.localStorage.setItem("chatterly:leak_disclaimer_seen:v2:emp-1", "1");
    await open({ previews: false });
    expect(dialog()).toBeNull();
  });

  it("falls back to The removal team when the brand is null", async () => {
    await open({ brand: null });
    const d = await screen.findByRole("dialog", { name: TITLE });
    expect(within(d).getByText(body("The removal team"))).toBeTruthy();
  });

  it.each([
    ["the setup card", { key: "missing", masked: null, brand: null }, "Tracker key"],
    ["the Team Leader no-key line", { key: "missing", masked: null, is_owner: false, can_write: false }, "The agency owner has not connected the removal service yet."],
  ])("no dialog on %s", async (_label, over, marker) => {
    relayGet.mockResolvedValue(setup(over));
    renderWithProviders(<LeakTracker />);
    expect(await screen.findAllByText(marker)).toBeTruthy();
    expect(dialog()).toBeNull();
  });

  it("no dialog before the employee key resolves", async () => {
    employeeKey = null;
    await open();
    expect(dialog()).toBeNull();
  });

  it.each([
    ["Got it", () => fireEvent.click(screen.getByRole("button", { name: "Got it" }))],
    ["Esc", () => fireEvent.keyDown(document, { key: "Escape" })],
    ["the close icon", () => fireEvent.click(within(dialog()!).getByRole("button", { name: "Close" }))],
    ["the overlay", () => fireEvent.click(dialog()!.parentElement!)],
  ])("%s stores the per-Employee key, a remount stays shut, another Employee still sees it", async (_label, close) => {
    await open();
    await screen.findByRole("dialog", { name: TITLE });
    close();
    expect(dialog()).toBeNull();
    expect(window.localStorage.getItem("chatterly:leak_disclaimer_seen:v2:emp-1")).toBe("1");
    cleanup();
    await open();
    expect(dialog()).toBeNull();
    cleanup();
    employeeKey = "emp-2";
    await open();
    expect(await screen.findByRole("dialog", { name: TITLE })).toBeTruthy();
  });

  it("makes no fetch on dismiss", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await open();
    await screen.findByRole("dialog", { name: TITLE });
    const before = relayGet.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(relayGet.mock.calls.length).toBe(before);
    for (const m of [relay.put, relay.post, relay.delete] as Mock[]) expect(m).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a throwing disclaimer key still renders the page, and the dialog shows again next open", async () => {
    const deny = <A extends unknown[], R>(real: (this: Storage, ...a: A) => R) =>
      function (this: Storage, ...a: A): R {
        if (String(a[0]).startsWith("chatterly:leak_disclaimer_seen:")) throw new Error("denied");
        return real.apply(this, a);
      };
    const { getItem, setItem } = Storage.prototype;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(deny(getItem));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(deny(setItem));
    await open();
    expect(screen.getByTestId("of-all-creators-row")).toBeTruthy();
    await screen.findByRole("dialog", { name: TITLE });
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(dialog()).toBeNull();
    cleanup();
    await open();
    expect(await screen.findByRole("dialog", { name: TITLE })).toBeTruthy();
  });
});
