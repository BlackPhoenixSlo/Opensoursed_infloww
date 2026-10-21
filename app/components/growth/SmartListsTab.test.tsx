/**
 * Growth's Smart lists on Infloww's `SmartLists` page (page-parity 13): the top box (search, Create list), the
 * table heads, the empty text, "Create smart list" / "Edit smart list" pop-ups and the "Delete smart list?" confirm.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

import SmartListsTab, { includesExpired } from "@/components/growth/SmartListsTab";
import { relay } from "@/lib/relay";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const del = relay.delete as unknown as Mock;

const LISTS = [
  { id: 1, account_id: "a1", name: "Whales", created_at: null, updated_at: null,
    rules: { match: "all", rules: [{ field: "lifetime_spend", op: ">=", value: 10000 }] } },
  { id: 2, account_id: "a1", name: "Active only", created_at: null, updated_at: null,
    rules: { match: "all", rules: [{ field: "status", op: "==", value: "active" }] } },
];

let lists: unknown[] = [];
let client: QueryClient;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  [get, post, del].forEach((m) => m.mockReset());
  lists = LISTS;
  get.mockImplementation((path: string) =>
    Promise.resolve(path.startsWith("/admin/smart-lists") ? { lists } : {}));
  post.mockResolvedValue({ id: 3 });
  del.mockResolvedValue({});
});
afterEach(() => cleanup());

const mount = (accountId: string | null = "a1") =>
  render(<QueryClientProvider client={client}><SmartListsTab accountId={accountId} /></QueryClientProvider>);

describe("SmartListsTab", () => {
  it("draws Infloww's table: List name, Criteria, Incl. expired, Fans, Actions", async () => {
    mount();
    await screen.findByText("Whales");
    const table = screen.getByRole("table", { name: "Smart lists" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["List name", "Criteria", "Incl. expired", "Fans", "Actions"]);
    const row = (name: string) => within(screen.getByText(name).closest("tr")!).getAllByRole("cell").map((c) => c.textContent);
    expect(row("Whales")).toEqual(["Whales", "Lifetime spend (OnlyFans total) >= $100", "Yes", "-", "SyncEditDelete"]);
    expect(row("Active only")[2]).toBe("No");
  });

  it("filters by the list name search", async () => {
    mount();
    await screen.findByText("Whales");
    fireEvent.change(screen.getByPlaceholderText("Search list name"), { target: { value: "wha" } });
    expect(screen.queryByText("Active only")).toBeNull();
    expect(screen.getByText("Whales")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Search list name"), { target: { value: "zzz" } });
    expect(screen.getByText("No data")).toBeTruthy();
  });

  it("says Infloww's empty text with a Create list action", async () => {
    lists = [];
    mount();
    expect(await screen.findByText("You haven’t created a smart list yet")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Create list" })).toHaveLength(2);
  });

  it("Create list opens the Create smart list dialog and saves the rules", async () => {
    mount();
    await screen.findByText("Whales");
    fireEvent.click(screen.getByRole("button", { name: "Create list" }));
    const dlg = screen.getByRole("dialog", { name: "Create smart list" });
    expect(within(dlg).getByText("Fans must meet all the conditions to be included on the list")).toBeTruthy();
    fireEvent.click(within(dlg).getByRole("button", { name: "Create smart list" }));
    expect(within(dlg).getByRole("alert").textContent).toBe("This is a required field");
    fireEvent.change(within(dlg).getByLabelText("Smart list name"), { target: { value: " Big spenders " } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Add condition" }));
    expect(within(dlg).getAllByRole("combobox", { name: "Condition" })).toHaveLength(2);
    fireEvent.click(within(dlg).getByRole("button", { name: "Create smart list" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/smart-lists", {
      account_id: "a1", name: "Big spenders",
      rules: { match: "all", rules: [
        { field: "lifetime_spend", op: ">=", value: 10000 }, { field: "lifetime_spend", op: ">=", value: 10000 }] },
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Edit opens Edit smart list with the list's name", async () => {
    mount();
    await screen.findByText("Whales");
    fireEvent.click(screen.getByRole("button", { name: "Edit Whales" }));
    const dlg = screen.getByRole("dialog", { name: "Edit smart list" });
    expect((within(dlg).getByLabelText("Smart list name") as HTMLInputElement).value).toBe("Whales");
  });

  it("Delete asks Delete smart list? first", async () => {
    mount();
    await screen.findByText("Whales");
    fireEvent.click(screen.getByRole("button", { name: "Delete Whales" }));
    const dlg = screen.getByRole("dialog", { name: "Delete smart list?" });
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(within(dlg).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/smart-lists/1"));
  });

  it("Sync starts the OnlyFans sync; a synced row shows its members and can delete the OnlyFans list too", async () => {
    lists = [
      LISTS[0],
      { ...LISTS[1], is_active: true, of_list_id: 88, sync_state: "ok", sync_error: null,
        synced_at: "2026-10-20T10:00:00", member_count: 42 },
    ];
    mount();
    await screen.findByText("Whales");
    fireEvent.click(screen.getByRole("button", { name: "Sync Whales" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/smart-lists/1/activate", {}));
    const synced = within(screen.getByText("Active only").closest("tr")!).getAllByRole("cell");
    expect(synced[3].textContent).toBe("42");
    expect(within(synced[0]).getByText("synced")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete Active only" }));
    const dlg = screen.getByRole("dialog", { name: "Delete smart list?" });
    fireEvent.click(within(dlg).getByLabelText("Also delete the OnlyFans list"));
    fireEvent.click(within(dlg).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/smart-lists/2?delete_of_list=true"));
  });

  it("a preset card pre-fills the Create smart list dialog", async () => {
    mount();
    await screen.findByText("Whales");
    fireEvent.click(screen.getByRole("button", { name: "Presets" }));
    fireEvent.click(screen.getByText("Expiring soon"));
    const dlg = screen.getByRole("dialog", { name: "Create smart list" });
    expect((within(dlg).getByLabelText("Smart list name") as HTMLInputElement).value).toBe("Expiring soon");
    expect(within(dlg).getAllByRole("combobox", { name: "Condition" }).map((s) => (s as HTMLSelectElement).value))
      .toEqual(["expires_at", "renew"]);
  });

  it("the Ghost audience preset is active fans idle 30+ days", async () => {
    mount();
    await screen.findByText("Whales");
    fireEvent.click(screen.getByRole("button", { name: "Presets" }));
    fireEvent.click(screen.getByText("Ghost audience"));
    const dlg = screen.getByRole("dialog", { name: "Create smart list" });
    expect(within(dlg).getAllByRole("combobox", { name: "Condition" }).map((s) => (s as HTMLSelectElement).value))
      .toEqual(["status", "idle_days"]);
    expect(within(dlg).getAllByRole("combobox", { name: "Operator" }).map((s) => (s as HTMLSelectElement).value))
      .toEqual(["==", "more_than"]);
  });

  it("with no creator draws the frame with the creator empty state, Create list disabled", () => {
    mount(null);
    expect(screen.getByRole("columnheader", { name: "List name" })).toBeTruthy();
    expect(screen.getByText("No creator connected yet")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Create list" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("Incl. expired follows the rules and the match", () => {
    const active = { field: "status", op: "==", value: "active" } as const;
    const spend = { field: "lifetime_spend", op: ">=", value: 1 } as const;
    expect(includesExpired({ match: "all", rules: [] })).toBe(true);
    expect(includesExpired({ match: "all", rules: [spend, active] })).toBe(false);
    expect(includesExpired({ match: "any", rules: [spend, active] })).toBe(true);
    expect(includesExpired({ match: "any", rules: [active] })).toBe(false);
  });
});
