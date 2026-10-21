/**
 * Growth's Profile promotion on Infloww's legacy page (page-parity ticket 12): Create promotion in its pop-up with
 * Infloww's/OF's fields (the body OF Manager sends), Auto-activate campaign, Add fans to list, Campaign insights'
 * table with Show expired, Deactivate behind Infloww's confirm, the pager, bundles under it; a promotion's Revenue
 * "from N fans" from the relay's cache. The free trial links tests are in TrialLinksTab.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

import PromoListRow from "@/components/growth/PromoListRow";
import PromotionTab from "@/components/growth/PromotionTab";
import { relay } from "@/lib/relay";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const patch = relay.patch as unknown as Mock;
const put = relay.put as unknown as Mock;

const promo = (over: Record<string, unknown>) => ({
  id: null, of_promo_id: null, name: "Promo", discount_percent: null, price_cents: 0, subscribe_counts: 10,
  subscribe_days: 7, message: "", promo_type: "all", status: "active", subscriber_count: 0, auto_reactivate: false,
  reactivate_count: 0, last_reactivated_at: null, created_at: null, source: "mirror", ...over,
});
const CAMPAIGNS = [
  promo({ id: 1, of_promo_id: 501, name: "Live week", discount_percent: 100, subscriber_count: 2, auto_reactivate: true,
    created_at: "2026-10-01T10:00:00+00:00", promo_type: "all,expired" }),
  promo({ id: 2, of_promo_id: 502, name: "Old one", status: "finished", subscribe_counts: 0 }),
];

let client: QueryClient;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  [get, post, patch, put].forEach((m) => m.mockReset());
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/promotions")) return Promise.resolve({ campaigns: CAMPAIGNS, of_available: true });
    if (path === "/api/of/v2/users/me") return Promise.resolve({ subscribePrice: 10, subscriptionBundles: [] });
    return Promise.resolve({});
  });
  post.mockResolvedValue({});
  patch.mockResolvedValue({});
  put.mockResolvedValue({});
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const mount = (ui: React.ReactElement) => render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);

/** Click `combobox`, then its option. */
function choose(combobox: HTMLElement, option: string | RegExp) {
  fireEvent.click(combobox);
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: option }));
}
/** The combobox's option names (opens it, reads, closes it). */
function optionsOf(combobox: HTMLElement) {
  fireEvent.click(combobox);
  const names = within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent);
  fireEvent.click(combobox);
  return names;
}

describe("PromotionTab", () => {
  it("creates in Infloww's pop-up with its fields and sends OF Manager's body (audience list, offer expiration)", async () => {
    mount(<PromotionTab accountId="a1" />);
    fireEvent.click(screen.getByRole("button", { name: "Create promotion" }));
    const dlg = screen.getByRole("dialog", { name: "Create promotion" });
    fireEvent.change(within(dlg).getByPlaceholderText("e.g. Summer free week"), { target: { value: "Fall" } });
    choose(within(dlg).getByRole("combobox", { name: "User type" }), "Both new and expired");
    fireEvent.click(within(dlg).getByLabelText("First-month discount"));
    choose(within(dlg).getByRole("combobox", { name: "Offer limit" }), "No limits");
    choose(within(dlg).getByRole("combobox", { name: "Offer expiration" }), "14 days");
    await waitFor(() => expect(within(dlg).getByRole("combobox", { name: "Discount percent" })).toBeTruthy());
    choose(within(dlg).getByRole("combobox", { name: "Discount percent" }), "30% discount");
    fireEvent.click(within(dlg).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/promotions", {
      account_id: "a1", name: "Fall", discount: 30, subscribe_counts: 0, subscribe_days: 14, finish_days: 14,
      message: "", promo_type: ["all", "expired"],
    }));
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it("lists only campaigns on offer until Show expired, in Infloww's table with bundles under it", async () => {
    mount(<PromotionTab accountId="a1" />);
    await screen.findByText("Live week");
    expect(screen.queryByText("Old one")).toBeNull();
    const table = screen.getByRole("table", { name: "Campaigns" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Promo", "Claims", "Revenue", "Actions"]);
    expect(within(table).getByText("2 / 10")).toBeTruthy();
    expect(within(table).getByText(/Oct\. 01, 2026 \| For expired and new subscribers/)).toBeTruthy();
    expect(screen.getByText(/Total: 1 record/)).toBeTruthy();
    // Bundles follow the table in the page.
    const bundles = screen.getByRole("region", { name: "Subscription bundles" });
    expect(table.compareDocumentPosition(bundles) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Show expired" }));
    expect(await screen.findByText("Old one")).toBeTruthy();
    expect(screen.getByText("0 / ∞")).toBeTruthy();
  });

  it("Deactivate asks Infloww's confirm, then turns Keep running off first and stops the offer on OF", async () => {
    mount(<PromotionTab accountId="a1" />);
    await screen.findByText("Live week");
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const dlg = screen.getByRole("dialog", { name: "Deactivate the campaign?" });
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(within(dlg).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/of/v2/promotions/501/finish", undefined, { accountId: "a1" }));
    expect(patch).toHaveBeenCalledWith("/admin/promotions/1", { auto_reactivate: false });
    expect(patch.mock.invocationCallOrder[0]).toBeLessThan(post.mock.invocationCallOrder[0]);
  });

  it("Cancel on the Deactivate confirm sends nothing", async () => {
    mount(<PromotionTab accountId="a1" />);
    await screen.findByText("Live week");
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Deactivate the campaign?" })).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(post).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it("draws the Auto-activate campaign row with its switch", async () => {
    mount(<PromotionTab accountId="a1" />);
    const row = await screen.findByRole("region", { name: "Auto-activate campaign" });
    expect(within(row).getByText("Enable to automatically reactivate your promotions when they expire")).toBeTruthy();
    expect(within(row).getByRole("switch", { name: "Auto-activate campaign" })).toBeTruthy();
  });
});

describe("Profile promotion's Add fans to list", () => {
  let setting: { enabled: boolean; list_id: string | null; list_name: string | null };
  let settingFails: boolean;
  let extraLists: { id: number; name: string; type: string }[];
  beforeEach(() => {
    setting = { enabled: false, list_id: null, list_name: null };
    settingFails = false;
    extraLists = [];
    get.mockImplementation((path: string) => {
      if (path.startsWith("/admin/promo-list")) {
        return settingFails ? Promise.reject(new Error("500 Internal Server Error")) : Promise.resolve(setting);
      }
      if (path.startsWith("/api/of/v2/lists")) {
        return Promise.resolve({ list: [{ id: 800001, name: "VIP", type: "custom" }, { id: 800002, name: "Whales", type: "custom" },
          { id: "following", name: "Following", type: "build-in" }, ...extraLists], hasMore: false });
      }
      if (path.startsWith("/admin/promotions")) return Promise.resolve({ campaigns: [], of_available: true });
      if (path === "/api/of/v2/users/me") return Promise.resolve({ subscribePrice: 10, subscriptionBundles: [] });
      return Promise.resolve({});
    });
    // The relay answers with the saved setting.
    put.mockImplementation((_p: string, body: Record<string, unknown>) =>
      Promise.resolve({ enabled: body.enabled, list_id: body.list_id, list_name: body.list_name }));
  });
  const select = () => screen.getByRole("combobox", { name: "Add fans to list" }) as HTMLButtonElement;
  const toggle = () => screen.getByRole("switch", { name: "Add fans to list" }) as HTMLButtonElement;
  const dialog = (name: string) => screen.getByRole("dialog", { name });
  const answer = (name: string, button: "Cancel" | "Confirm") =>
    fireEvent.click(within(dialog(name)).getByRole("button", { name: button }));

  it("sits on Profile promotion above Campaign insights", async () => {
    mount(<PromotionTab accountId="a1" />);
    const row = await screen.findByRole("region", { name: "Add fans to list" });
    const insights = screen.getByRole("region", { name: "Campaign insights" });
    expect(row.compareDocumentPosition(insights) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("offers the custom lists; the switch needs a list; the first pick turns it on with no confirm", async () => {
    mount(<PromoListRow accountId="a1" />);
    await waitFor(() => expect(optionsOf(select())).toEqual(["None", "VIP", "Whales"]));
    expect(toggle().disabled).toBe(true);
    // Later claimers are added by the next figures read (about hourly); the copy says so, not "as fans claim".
    expect(screen.getByText("Adds every promotion's fans to this OnlyFans list now. Fans who claim later are added " +
      "when the figures are next read from OnlyFans, about every hour. Fans already added stay in it.")).toBeTruthy();
    choose(select(), "Whales");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: true, list_id: "800002", list_name: "Whales" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(toggle().getAttribute("aria-checked")).toBe("true"));
    expect(select().textContent).toContain("Whales");
  });

  it("asks Modify list? before another list; Cancel keeps the stored one", async () => {
    setting = { enabled: true, list_id: "800001", list_name: "VIP" };
    mount(<PromoListRow accountId="a1" />);
    await waitFor(() => expect(select().textContent).toContain("VIP"));
    choose(select(), "Whales");
    expect(within(dialog("Modify list?")).getByText("Editing the list will not affect already-added fans")).toBeTruthy();
    answer("Modify list?", "Cancel");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(put).not.toHaveBeenCalled();
    expect(select().textContent).toContain("VIP");
    choose(select(), "Whales");
    answer("Modify list?", "Confirm");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: true, list_id: "800002", list_name: "Whales" }));
  });

  it("asks Delete the list? before None or switching off; Cancel leaves it on", async () => {
    setting = { enabled: true, list_id: "800001", list_name: "VIP" };
    mount(<PromoListRow accountId="a1" />);
    await waitFor(() => expect(toggle().getAttribute("aria-checked")).toBe("true"));
    fireEvent.click(toggle());
    answer("Delete the list?", "Cancel");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(put).not.toHaveBeenCalled();
    expect(toggle().getAttribute("aria-checked")).toBe("true");
    fireEvent.click(toggle());
    answer("Delete the list?", "Confirm");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: false, list_id: "800001", list_name: "VIP" }));
    await waitFor(() => expect(toggle().getAttribute("aria-checked")).toBe("false"));
    // Off with a list kept: switching on again needs no confirm.
    fireEvent.click(toggle());
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(put).toHaveBeenLastCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: true, list_id: "800001", list_name: "VIP" }));
    await waitFor(() => expect(toggle().getAttribute("aria-checked")).toBe("true"));
    choose(select(), "None");
    answer("Delete the list?", "Confirm");
    await waitFor(() => expect(put).toHaveBeenLastCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: false, list_id: null, list_name: null }));
  });

  it("another list keeps the switch off when it was off; a first pick from None turns it on", async () => {
    setting = { enabled: false, list_id: "800001", list_name: "VIP" };
    mount(<PromoListRow accountId="a1" />);
    await waitFor(() => expect(select().textContent).toContain("VIP"));
    choose(select(), "Whales");
    answer("Modify list?", "Confirm");
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: false, list_id: "800002", list_name: "Whales" }));
    await waitFor(() => expect(select().textContent).toContain("Whales"));
    expect(toggle().getAttribute("aria-checked")).toBe("false");
  });

  it("a failed settings read disables the row and says so, so nothing overwrites the stored setting", async () => {
    settingFails = true;
    mount(<PromoListRow accountId="a1" />);
    expect((await screen.findByRole("alert")).textContent).toBe("Couldn't read this setting. Reload to try again.");
    expect(select().disabled).toBe(true);
    expect(toggle().disabled).toBe(true);
    fireEvent.click(toggle());
    expect(put).not.toHaveBeenCalled();
  });

  it("cuts a long list name to the relay's 64 characters", async () => {
    const long = "Fans from the autumn promotion who claimed the free week and then renewed twice";
    extraLists = [{ id: 800003, name: long, type: "custom" }];
    mount(<PromoListRow accountId="a1" />);
    await waitFor(() => expect(optionsOf(select())).toContain(long));
    choose(select(), long);
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/promo-list",
      { account_id: "a1", enabled: true, list_id: "800003", list_name: long.slice(0, 64) }));
    expect(long.length).toBeGreaterThan(64);
  });

  it("keeps showing a stored list OnlyFans no longer has, and shows a save error", async () => {
    setting = { enabled: true, list_id: "800009", list_name: "Old promo fans" };
    put.mockRejectedValue(new Error("OnlyFans said no"));
    mount(<PromoListRow accountId="a1" />);
    await waitFor(() => expect(optionsOf(select())).toEqual(["None", "Old promo fans", "VIP", "Whales"]));
    expect(select().textContent).toContain("Old promo fans");
    fireEvent.click(toggle());
    answer("Delete the list?", "Confirm");
    expect((await screen.findByRole("alert")).textContent).toContain("OnlyFans said no");
  });
});

const figures = (over: Record<string, unknown>) => ({
  earnings_cents: null, earnings_net_cents: null, fans_who_spent: null, fans_counted: null, claimers: null,
  spend_unknown: 0, net_missing_count: 0, ...over,
});

describe("PromotionTab Revenue", () => {
  it("shows Infloww's Revenue over \"from N fans\", with Spend/Claim and AEPS, and — before the first read", async () => {
    get.mockImplementation((path: string) => {
      if (path.startsWith("/admin/promotions")) {
        return Promise.resolve({
          campaigns: [
            { ...CAMPAIGNS[0], metrics: figures({ earnings_cents: 9000, earnings_net_cents: 7200, fans_who_spent: 1, fans_counted: 2, claimers: 2 }) },
            { ...CAMPAIGNS[1], status: "active", metrics: figures({}) },
          ],
          of_available: true, metrics_updated_at: new Date(Date.now() - 5 * 60_000).toISOString(), metrics_refreshing: false,
        });
      }
      return Promise.resolve({});
    });
    mount(<PromotionTab accountId="a1" />);
    await screen.findByText("Live week");
    const [a, b] = [...document.querySelectorAll<HTMLElement>("[data-revenue]")];
    expect(a.textContent).toBe("$72.00from 1 fanSpend/Claim 50.00%AEPS $36.00");
    expect(b.textContent).toBe("—Spend/Claim —AEPS —");
    expect(document.querySelector("[data-metrics-updated]")?.textContent).toMatch(/Revenue updated 5 min ago/);
  });
});
