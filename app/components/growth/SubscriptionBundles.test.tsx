/**
 * Growth's Subscription bundles: the same reads, writes and rules as OF Manager's mirror (the settings-bundles
 * fixture its own tests use: synthetic, PII-free), plus Edit (OF's saveBundle with an id).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

import SubscriptionBundles from "@/components/growth/SubscriptionBundles";
import { relay, RelayError } from "@/lib/relay";

const fx = JSON.parse(readFileSync(resolve(__dirname, "../../lib/__fixtures__/of/settings-bundles.json"), "utf8"));
const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;
const del = relay.delete as unknown as Mock;

let client: QueryClient;
let me: Record<string, unknown>;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  me = structuredClone(fx.me);
  [get, post, put, del].forEach((m) => m.mockReset());
  get.mockImplementation((path: string) =>
    Promise.resolve(path === "/api/of/v2/users/me" ? me : path === "/api/of/v2/users/me/settings" ? fx.settings : {}));
  post.mockResolvedValue({});
  put.mockResolvedValue({});
  del.mockResolvedValue({});
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const mount = () => render(<QueryClientProvider client={client}><SubscriptionBundles accountId="a1" /></QueryClientProvider>);
const rows = () => document.querySelectorAll("[data-bundle-row]");
const addButton = () => screen.getByRole("button", { name: "Add bundle" });

describe("SubscriptionBundles", () => {
  it("lists users/me's bundles worded as OF's rows, read for the picked account", async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()[0].textContent).toContain("$25.47 USD");
    expect(rows()[0].textContent).toContain("total for 3 months");
    expect(rows()[0].textContent).toContain("-15%");
    expect(rows()[1].textContent).not.toContain("%");
    expect(get).toHaveBeenCalledWith("/api/of/v2/users/me", { accountId: "a1" });
    expect(screen.getByText("Offer several months of subscription as a discounted bundle.")).toBeTruthy();
  });

  it("adds a bundle with OF's {discount, duration}, offering only the lengths left", async () => {
    mount();
    await waitFor(() => expect((addButton() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(addButton());
    const duration = screen.getByLabelText("Discount duration") as HTMLSelectElement;
    expect([...duration.options].map((o) => o.value)).toEqual(["12"]);
    fireEvent.change(screen.getByLabelText("Discount percent"), { target: { value: String(fx.create.form.discount) } });
    expect(screen.getByText(`Promotional subscription $${fx.create.amount.toFixed(2)} for 12 months.`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(fx.create.relay.path, fx.create.relay.body, { accountId: "a1" }));
  });

  it("edits a bundle with OF's PUT /{id} {discount, duration}", async () => {
    mount();
    await waitFor(() => expect(rows()).toHaveLength(2));
    fireEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Discount percent"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith(fx.edit.relay.path, fx.edit.relay.body, { accountId: "a1" }));
  });

  it("deletes after OF's confirm and shows OF's own error when it fails", async () => {
    del.mockRejectedValueOnce(new RelayError(fx.error.status, fx.error.body, "upstream 400"));
    mount();
    await waitFor(() => expect(rows()).toHaveLength(2));
    fireEvent.click(within(rows()[1] as HTMLElement).getByRole("button", { name: "Delete" }));
    expect(window.confirm).toHaveBeenCalledWith("Are you sure you want to delete this subscription bundle?");
    await waitFor(() => expect(del).toHaveBeenCalledWith(fx.delete.relay.path, { accountId: "a1" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", fx.error.message);
  });

  it("disables Add bundle on a free page and once every length has a bundle", async () => {
    me = { ...me, subscribePrice: 0 };
    const { unmount } = mount();
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect((addButton() as HTMLButtonElement).disabled).toBe(true);
    unmount();
    client.clear();
    me = { ...structuredClone(fx.me), subscriptionBundles: [...fx.me.subscriptionBundles, { id: 900003, discount: 10, duration: 12, price: 107.89 }] };
    mount();
    await waitFor(() => expect(rows()).toHaveLength(3));
    await waitFor(() => expect(addButton().getAttribute("title")).toBe("Every bundle length already has a bundle"));
    expect((addButton() as HTMLButtonElement).disabled).toBe(true);
  });
});
