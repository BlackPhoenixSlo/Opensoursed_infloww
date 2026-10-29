/**
 * Growth's Free trial links, Infloww's Tracking links frame in its FREETRIAL variant (page-parity ticket 12): the
 * frame's "Create free trial link" and its columns, the create pop-up with Infloww's/OF's fields and Source, Promo
 * cost, Tag and List; the per-link figures from the relay's cache (Spend/Claim, Promo cost, Earnings, Fans who
 * spent, Profit, AEPS, ROI), the Source and Tag filters, Edit, Details and the dots menu's Delete.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
// An owner session, so `useAccounts` reads `/admin/accounts` through the mocked relay.
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/UserContext")>()),
  useUser: () => ({ user: { user_id: "owner-1" } }),
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/ChatterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => ({ chatter: null }),
}));

import TrialLinksTab from "@/components/growth/TrialLinksTab";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;
const del = relay.delete as unknown as Mock;

const figures = (over: Record<string, unknown>) => ({
  earnings_cents: null, earnings_net_cents: null, fans_who_spent: null, fans_counted: null, claimers: null,
  spend_unknown: 0, net_missing_count: 0, ...over,
});
const trial = (over: Record<string, unknown>) => ({
  id: null, of_trial_id: 9001, name: "Trial", url: "https://of.test/t", subscribe_days: 7, subscribe_counts: 0,
  claim_counts: 4, clicks_count: 40, expired_at: null, status: "active", created_at: null, source: "onlyfans",
  metrics: figures({}), promo_cost_cents: null, link_source: null, tags: [], ...over,
});

let links: unknown[] = [];
let extra: Record<string, unknown> = {};
beforeEach(() => {
  [get, post, put, del].forEach((m) => m.mockReset());
  links = [];
  extra = {};
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/trial-links")) return Promise.resolve({ links, of_available: true, ...extra });
    if (path.startsWith("/admin/link-metrics/fans")) return Promise.resolve({ fans: [], ledger_since: null, walked_at: null, refreshing: false });
    if (path.startsWith("/api/of/v2/lists")) {
      return Promise.resolve({ list: [{ id: 800002, name: "Whales", type: "custom" }, { id: "fans", name: "Fans", type: "build-in" },
        { id: 800001, name: "VIP", type: "custom" }], hasMore: false });
    }
    return Promise.resolve({});
  });
  post.mockResolvedValue({});
  put.mockResolvedValue({});
  del.mockResolvedValue({});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const mount = () => renderWithProviders(<TrialLinksTab accountId="a1" onAccountChange={() => {}} />);

/** Click `combobox`, then its option. */
function choose(combobox: HTMLElement, option: string | RegExp) {
  fireEvent.click(combobox);
  fireEvent.click(screen.getByRole("option", { name: option }));
}

const rowOf = (name: string) => screen.getByText(name).closest("tr")!;
const metric = (row: string, title: string) => rowOf(row).querySelector(`[data-metric="${title}"]`)?.textContent;

describe("TrialLinksTab on the Tracking links frame", () => {
  it("draws the frame: Create free trial link, the search, the switches and Infloww's columns; no Dashboard tab", async () => {
    links = [trial({ of_trial_id: 9002, name: "Fresh link", claim_counts: 1 })];
    mount();
    await screen.findByText("Fresh link");
    expect(screen.getByRole("button", { name: "Create free trial link" })).toBeTruthy();
    expect(screen.getByPlaceholderText("Search free trial link name")).toBeTruthy();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Links list", "Share links"]);
    expect(screen.getByRole("switch", { name: "Show deactivated links" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("switch", { name: "Show net earnings" }).getAttribute("aria-checked")).toBe("true");
    const heads = within(screen.getByRole("table", { name: "Links list" })).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["", "Free trial links", "Date created", "Claim", "Spend/Claim", "Promo cost", "Earnings",
      "Fans who spent", "Profit", "AEPS", "ROI", "Actions"]);
    expect(metric("Fresh link", "Claim")).toBe("1 / ∞");
  });

  it("the search filters by name, and an empty table says No data", async () => {
    links = [trial({ of_trial_id: 9002, name: "Fresh link" })];
    mount();
    await screen.findByText("Fresh link");
    fireEvent.change(screen.getByPlaceholderText("Search free trial link name"), { target: { value: "zzz" } });
    expect(screen.queryByText("Fresh link")).toBeNull();
    expect(screen.getByText("No data")).toBeTruthy();
  });

  it("while the Creators load: placeholder rows, no No data and no OnlyFans-not-reachable notice", () => {
    renderWithProviders(<TrialLinksTab accountId={null} onAccountChange={() => {}} accountsLoading />);
    const table = screen.getByRole("table", { name: "Links list" });
    expect(table.querySelectorAll("tbody [data-loading]").length).toBeGreaterThan(0);
    expect(screen.queryByText("No data")).toBeNull();
    expect(screen.queryByText(/not reachable/)).toBeNull();
  });

  it("says OnlyFans is not reachable only once the list read answers so", async () => {
    links = [trial({ id: 3, of_trial_id: null, name: "Saved link", source: "mirror" })];
    extra = { of_available: false };
    mount();
    await screen.findByText("Saved link");
    expect(screen.getByText(/OnlyFans not reachable/)).toBeTruthy();
  });
});

describe("TrialLinksTab Create", () => {
  const field = (k: string) => document.getElementById(`trial-new-${k}`) as HTMLInputElement | HTMLSelectElement;
  async function open() {
    links = [trial({ of_trial_id: 9002, name: "Fresh link" })];
    extra = { sources: ["Reddit"], tags: ["spring"] };
    mount();
    await screen.findByText("Fresh link");
    fireEvent.click(screen.getByRole("button", { name: "Create free trial link" }));
    return screen.getByRole("dialog", { name: "Create free trial link" });
  }
  async function fill() {
    const dlg = await open();
    fireEvent.change(within(dlg).getByPlaceholderText("e.g. Twitter 7-day"), { target: { value: "Reddit May" } });
    for (const k of ["source", "cost", "tag", "list"]) expect(field(k).disabled).toBe(false);
    fireEvent.change(field("source"), { target: { value: "Reddit" } });
    fireEvent.change(field("cost"), { target: { value: "40" } });
    fireEvent.change(field("tag"), { target: { value: "may" } });
    await waitFor(() => expect([...(field("list") as HTMLSelectElement).options].map((o) => o.textContent))
      .toEqual(["None", "VIP", "Whales"]));
    fireEvent.change(field("list"), { target: { value: "800002" } });
    return dlg;
  }

  it("creates with Infloww's/OF's fields, sending the offer expiration", async () => {
    const dlg = await open();
    fireEvent.change(within(dlg).getByPlaceholderText("e.g. Twitter 7-day"), { target: { value: "  Reddit" } });
    fireEvent.change(within(dlg).getByLabelText("Offer limit"), { target: { value: "50" } });
    fireEvent.change(within(dlg).getByLabelText("Offer expiration"), { target: { value: "0" } });
    fireEvent.change(within(dlg).getByLabelText("Free trial duration"), { target: { value: "30" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/trial-links", {
      account_id: "a1", name: "Reddit", subscribe_counts: 50, expire_days: 0, subscribe_days: 30,
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends the four fields with OnlyFans' fields in one request, then closes", async () => {
    post.mockResolvedValue({ of_trial_id: 9100, name: "Reddit May", meta_saved: true });
    const dlg = await fill();
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/admin/trial-links", {
      account_id: "a1", name: "Reddit May", subscribe_counts: 10, expire_days: 7, subscribe_days: 7,
      promo_cost: 40, source: "Reddit", tags: ["may"], list_id: "800002", list_name: "Whales",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("refuses a promo cost that is not an amount, and sends nothing", async () => {
    const dlg = await fill();
    fireEvent.change(field("cost"), { target: { value: "12.345" } });
    const btn = within(dlg).getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(post).not.toHaveBeenCalled();
  });

  it("says the fields were not saved when the reply says so, in place of the form", async () => {
    post.mockResolvedValue({ of_trial_id: null, name: "Reddit May", meta_saved: false });
    const dlg = await fill();
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect((await within(dlg).findByRole("alert")).textContent)
      .toBe("Link created; Source, Promo cost, Tag and List weren't saved. Use Edit.");
    // No Save is left to mint a duplicate.
    expect(within(dlg).queryByRole("button", { name: "Save" })).toBeNull();
    fireEvent.click(within(dlg).getAllByRole("button", { name: "Close" }).at(-1)!);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("asks for the name, and sends no field keys when none is filled", async () => {
    const dlg = await open();
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect(within(dlg).getByRole("alert").textContent).toBe("This is a required field");
    expect(post).not.toHaveBeenCalled();
    fireEvent.change(within(dlg).getByPlaceholderText("e.g. Twitter 7-day"), { target: { value: "Plain" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/trial-links", {
      account_id: "a1", name: "Plain", subscribe_counts: 10, expire_days: 7, subscribe_days: 7,
    }));
  });
});

describe("TrialLinksTab figures, filters, Edit, Details and Delete", () => {
  // Worked example: Reddit 7-day cost $50.00; 4 claimers, 2 who spent, $120.00 net ($150.00 gross) since claiming.
  // Spend/Claim 2 / 4 = 50.00%, Profit $70.00, AEPS $120.00 / 4 = $30.00, ROI $70.00 / $50.00 x 100 = 140.00%.
  const LINKS = [
    trial({ id: 7, of_trial_id: 9001, name: "Reddit 7-day", promo_cost_cents: 5000, link_source: "Reddit", tags: ["spring"],
      metrics: figures({ earnings_cents: 15000, earnings_net_cents: 12000, fans_who_spent: 2, fans_counted: 4, claimers: 4 }) }),
    trial({ of_trial_id: 9002, name: "Fresh link", claim_counts: 1 }),
  ];
  beforeEach(() => {
    links = LINKS;
    extra = { metrics_updated_at: null, metrics_refreshing: true, sources: ["Reddit", "Twitter"], tags: ["spring"] };
  });
  const FIGS = ["Spend/Claim", "Promo cost", "Earnings", "Fans who spent", "Profit", "AEPS", "ROI"];

  it("shows Infloww's free trial figures in its order, — for a link not read yet or with no cost", async () => {
    mount();
    await screen.findByText("Reddit 7-day");
    const spendHead = screen.getByRole("columnheader", { name: "Spend/Claim" });
    expect(spendHead.querySelector("[title]")!.getAttribute("title")).toBe(
      "Percentage of fans who claimed a free trial that purchased subscriptions, spent on content, or gave tips");
    expect(FIGS.map((t) => metric("Reddit 7-day", t))).toEqual(["50.00%", "$50", "$120", "2", "$70", "$30", "140.00%"]);
    expect(FIGS.map((t) => metric("Fresh link", t))).toEqual(Array(7).fill("—"));
    // Infloww's free trial table has no CPC or CPS; Source and Tag draw once a link has them.
    expect(screen.queryByRole("columnheader", { name: "CPC" })).toBeNull();
    expect(metric("Reddit 7-day", "Source")).toBe("Reddit");
    expect(metric("Reddit 7-day", "Tag")).toBe("spring");
    expect(document.querySelector("[data-metrics-updated]")?.textContent).toBe("Not read yet · refreshing…");
    fireEvent.click(screen.getByRole("switch", { name: "Show net earnings" }));
    expect(metric("Reddit 7-day", "Earnings")).toBe("$150");
    expect(metric("Reddit 7-day", "ROI")).toBe("200.00%");
  });

  it("filters by Source and Tag", async () => {
    mount();
    await screen.findByText("Fresh link");
    choose(screen.getByRole("combobox", { name: "Source" }), "Reddit");
    expect(screen.queryByText("Fresh link")).toBeNull();
    choose(screen.getByRole("combobox", { name: "Source" }), "Twitter");
    expect(screen.getByText("No data")).toBeTruthy();
    choose(screen.getByRole("combobox", { name: "Source" }), "All sources");
    choose(screen.getByRole("combobox", { name: "Tag" }), "spring");
    expect(screen.queryByText("Fresh link")).toBeNull();
    expect(screen.getByText("Reddit 7-day")).toBeTruthy();
  });

  it("edits Promo cost, Source and Tag in Infloww's dialog and saves them to the relay", async () => {
    mount();
    await screen.findByText("Fresh link");
    fireEvent.click(screen.getByRole("button", { name: "Edit Fresh link" }));
    const dlg = screen.getByRole("dialog", { name: "Edit free trial link" });
    expect((within(dlg).getByLabelText("Free trial link name") as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(within(dlg).getByLabelText(/^Source/), { target: { value: " Twitter " } });
    fireEvent.change(within(dlg).getByLabelText(/^Promo cost/), { target: { value: "19.9" } });
    // A tag typed but not added is kept on Save.
    fireEvent.change(within(dlg).getByLabelText(/^Tag/), { target: { value: "fall" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/link-meta", {
      account_id: "a1", kind: "trial", of_id: 9002, promo_cost: 19.9, source: "Twitter", tags: ["fall"],
      list_id: null, list_name: null,
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens Details under the row on the relay's fans read, with the row's claim count", async () => {
    mount();
    await screen.findByText("Fresh link");
    fireEvent.click(within(rowOf("Fresh link")).getByRole("button", { name: "Details" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/admin/link-metrics/fans?account_id=a1&kind=trial&of_id=9002&count=1"));
    expect(within(rowOf("Fresh link")).getByRole("button", { name: "Hide" })).toBeTruthy();
  });

  it("deletes from the dots menu, labelled as ours, behind a confirm; an OnlyFans-only link can't be deleted", async () => {
    mount();
    await screen.findByText("Fresh link");
    fireEvent.click(screen.getByRole("button", { name: "More actions for Fresh link" }));
    expect((screen.getByRole("menuitem", { name: /Delete/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "More actions for Fresh link" }));
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reddit 7-day" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));
    const dlg = screen.getByRole("dialog", { name: "Delete free trial link, Reddit 7-day?" });
    fireEvent.click(within(dlg).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/trial-links/7"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("batch edits the picked links: only the fields filled in are sent, no List", async () => {
    links = [trial({ of_trial_id: 9002, name: "Fresh link" }), trial({ of_trial_id: 9003, name: "Old link" }),
      trial({ id: 5, of_trial_id: null, name: "Unlinked" })];
    mount();
    await screen.findByText("Fresh link");
    const batch = screen.getByRole("button", { name: "Batch edit" });
    expect((batch as HTMLButtonElement).disabled).toBe(true);
    expect((within(rowOf("Unlinked")).getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    fireEvent.click(within(rowOf("Old link")).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Batch edit (1)" }));
    const dlg = screen.getByRole("dialog", { name: "Batch edit" });
    expect(within(dlg).queryByLabelText(/^List/)).toBeNull();
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect(within(dlg).getByRole("alert").textContent).toBe("Fill in Source, Promo cost or Tag");
    fireEvent.change(within(dlg).getByLabelText(/^Source/), { target: { value: " Reddit " } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/link-meta/batch", {
      account_id: "a1", kind: "trial", of_ids: [9002], source: "Reddit",
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((screen.getByRole("button", { name: "Batch edit" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("offers Share links to the owner: a table of the Creator's share links and a Create pop-up", async () => {
    links = [trial({ of_trial_id: 9002, name: "Fresh link" })];
    mount();
    await screen.findByText("Fresh link");
    get.mockImplementation((path: string) => path.startsWith("/admin/link-shares")
      ? Promise.resolve({ shares: [], limit: 50 })
      : Promise.resolve({ links, of_available: true }));
    fireEvent.click(screen.getByRole("tab", { name: "Share links" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/admin/link-shares?account_id=a1&kind=trial"));
    fireEvent.click(await screen.findByRole("button", { name: "Create share link" }));
    const dlg = screen.getByRole("dialog", { name: "Create share link" });
    fireEvent.change(within(dlg).getByLabelText("Name"), { target: { value: "For Bob" } });
    fireEvent.click(within(dlg).getByRole("checkbox", { name: "Fresh link" }));
    fireEvent.click(within(dlg).getByRole("switch", { name: "Include earnings" }));
    fireEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/link-shares", {
      account_id: "a1", kind: "trial", name: "For Bob", of_ids: [9002], include_earnings: true,
    }));
  });
});
