import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});

import { leakKeys } from "./leakKeys";
import { useLeakPages } from "./leakRead";
import type { LeakRemovalPage } from "./leakView";
import type { OfferRead } from "./StartRemovalPopup";
import { RemovalArea } from "@/components/leaks/RemovalArea";
import { leadLine, type Removal, type RemovalOffer } from "@/components/leaks/removalOffer";
import { relay } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayPost = relay.post as unknown as Mock;
const relayGet = relay.get as unknown as Mock;
const SCENES = { google: [], google_images: [], mega: [], forum: [], x: [] };
const BRAND = "Example Removal";
const CONTACT = "https://removal.example/contact?text=Hi%2C%20I%27d%20like%20help";
const UPDATED = "2026-11-27T04:05:00Z";
const removal = (over: Partial<Removal> = {}): Removal =>
  ({ status: "none", view: "offer", notices_updated_at: UPDATED, stale: false, counts: null, offer_snoozed_until: null, ...over });
const offer = (over: Partial<RemovalOffer> = {}): RemovalOffer =>
  ({ brand: BRAND, contact_url: CONTACT, angle: "came_back", n: 2, ...over });
const card = () => screen.queryByRole("region", { name: "Removal help" });
const show = (r: Removal | null, o: RemovalOffer | null = null) =>
  renderWithProviders(<RemovalArea creatorId="acc-a" scopeAccountId="acc-b" removal={r} offer={o} />);

beforeEach(() => {
  for (const m of Object.values(relay) as Mock[]) m.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Removal area views", () => {
  it("hidden shows nothing at all", () => {
    const { container } = show(removal({ status: "unknown", view: "hidden", stale: true }), null);
    expect(container.textContent).toBe("");
  });

  it("no removal read shows nothing", () => {
    const { container } = show(null);
    expect(container.textContent).toBe("");
  });

  it("none shows the notices line, no track, and the card when offered", () => {
    show(removal(), offer());
    const area = screen.getByRole("region", { name: "Removal" });
    expect(within(area).getByText(/^Notices updated /)).toBeTruthy();
    expect(card()).toBeTruthy();
    expect(screen.queryByText("Removal starting")).toBeNull();
  });

  it("none with no offer (Team Leader) shows only the notices line", () => {
    show(removal(), null);
    expect(screen.getByRole("region", { name: "Removal" }).textContent).toMatch(/^Notices updated /);
    expect(card()).toBeNull();
  });

  it("a never-updated feed says so", () => {
    show(removal({ notices_updated_at: null, stale: true }), offer());
    expect(screen.getByText("Notices not updated yet")).toBeTruthy();
    expect(card()).toBeTruthy();
  });

  it("pending reads Removal starting and never carries a card", () => {
    show(removal({ status: "pending", view: "starting" }), null);
    expect(screen.getByText("Removal starting")).toBeTruthy();
    expect(card()).toBeNull();
  });
});

describe("Removal offer card", () => {
  it.each([
    ["came_back", 3, "3 leaks came back in the last 30 days."],
    ["cached", 2, "2 leaks are gone from the site but still show in Google."],
    ["live_30d", 4, "4 leaks have been up for 30 days or more."],
    ["new_week", 1, "1 new leak this week."],
    ["new_week", 2, "2 new leaks this week."],
    ["came_back", 1, "1 leak came back in the last 30 days."],
    ["cached", 1, "1 leak is gone from the site but still shows in Google."],
    ["live_30d", 1, "1 leak has been up for 30 days or more."],
    ["visible", 1, "1 leak is up right now."],
    ["visible", 5, "5 leaks are up right now."],
    ["clean", 0, `No live leaks found. ${BRAND} also handles removals if you need them.`],
  ] as const)("the %s angle reads its copy-table line", (angle, n, line) => {
    expect(leadLine(offer({ angle, n }))).toBe(line);
    show(removal(), offer({ angle, n }));
    const c = card()!;
    expect(within(c).getByText(BRAND)).toBeTruthy();
    expect(within(c).getByRole("heading", { name: "Removal help" })).toBeTruthy();
    expect(within(c).getByText(line)).toBeTruthy();
    expect(within(c).getByText(`${BRAND} files removal notices and follows them up.`)).toBeTruthy();
    expect(c.textContent).not.toMatch(/[%$€£¥]/);
  });

  it("the only CTA opens the popup, whose contact link is contact_url exactly in a new tab with no referrer", async () => {
    relayGet.mockResolvedValue({ offer: offer(), preview_leak: null, video: null, scenes: SCENES, last_checked_at: UPDATED });
    show(removal(), offer());
    const c = card()!;
    expect(within(c).queryByRole("link")).toBeNull();
    expect(within(c).getAllByRole("button").map((b) => b.textContent)).toEqual(["Contact us to start removal", "Not now"]);
    expect(c.querySelector("form, input, select, [role=switch]")).toBeNull();
    fireEvent.click(within(c).getByRole("button", { name: "Contact us to start removal" }));
    const dialog = await screen.findByRole("dialog", { name: `Start removal with ${BRAND}` });
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/offer", { accountId: "acc-b" });
    const link = await within(dialog).findByRole("link", { name: `Contact ${BRAND}` });
    expect(link.getAttribute("href")).toBe(CONTACT);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(within(dialog).getAllByRole("link")).toHaveLength(1);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("reads a persisted snooze on mount and shows the offer when the read changes", () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-27T12:00:00Z") });
    const { rerender } = show(removal({ offer_snoozed_until: "2026-12-04T12:00:00Z" }));
    expect(screen.getByText("Removal offer hidden until 4 Dec.")).toBeTruthy();
    rerender(<RemovalArea creatorId="acc-a" scopeAccountId="acc-b" removal={removal()} offer={offer()} />);
    expect(card()).toBeTruthy();
    expect(screen.queryByText(/^Removal offer hidden/)).toBeNull();
  });

  it("Not now keeps the offer hidden when the Creator refetch fails", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-27T12:00:00Z") });
    relayPost.mockResolvedValue({ offer_snoozed_until: "2026-12-04T12:00:00Z" });
    relayGet.mockResolvedValueOnce({ leaks: [], next_cursor: null, stale: false, removal: removal(), offer: offer() })
      .mockRejectedValueOnce(new Error("refetch failed"));
    function Drill() {
      const { data } = useLeakPages<LeakRemovalPage>(
        leakKeys.watch("acc-a", "acc-b"), "/admin/leaks/watches/acc-a", "acc-b",
      );
      const page = data?.pages[0];
      return page && <RemovalArea creatorId="acc-a" scopeAccountId="acc-b" {...page} />;
    }
    const client = makeTestQueryClient();
    client.setDefaultOptions({ queries: { gcTime: Infinity, retry: false } });
    const offerKey = leakKeys.offer("acc-a", "acc-b");
    client.setQueryData<OfferRead>(offerKey, {
      offer: offer(), preview_leak: null, video: null, scenes: SCENES, last_checked_at: UPDATED,
    });
    const otherScope = [leakKeys.setup("acc-c"), leakKeys.roster("acc-c"), leakKeys.all("acc-c"), leakKeys.watch("acc-a", "acc-c")];
    for (const key of otherScope) client.setQueryData(key, {});
    renderWithProviders(<Drill />, client);
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(client.getQueryState(leakKeys.watch("acc-a", "acc-b"))?.status).toBe("error"));
    expect(card()).toBeNull();
    expect(relayGet).toHaveBeenCalledTimes(2);
    expect(client.getQueryState(offerKey)).toBeUndefined();
    expect(otherScope.map((key) => client.getQueryState(key)?.isInvalidated)).toEqual([true, true, true, true]);
    expect(relayPost).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/offer-snooze", { snoozed: true }, { accountId: "acc-b" });
    expect(screen.getByText("Removal offer hidden until 4 Dec.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/undo/i)).toBeNull();
  });

  it("a failed Not now keeps the card and says why", async () => {
    relayPost.mockRejectedValue(new Error("Only the owner or an Admin can hide the Removal offer"));
    show(removal(), offer());
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(card()).toBeTruthy();
  });
});
