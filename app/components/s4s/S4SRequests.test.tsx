/**
 * Requests (docs/spec/phase-03-share-for-share.md, Testing Decisions, seam 2; page-parity 15), for the creator picked
 * on the rail, rendered with the relay mocked at `fetch` by URL: "Latest request" one pending received request at a
 * time with Accept / Decline / Skip, then the Received and Sent tables with Infloww's status words, Review and Cancel
 * behind its confirm. Every request is shown from its stored snapshots. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import S4SRequests, { CANCEL_CONFIRM } from "@/components/s4s/S4SRequests";
import type { S4SProfile, S4SProjection, S4SRequest } from "@/lib/s4s";

const OWN: S4SProjection = {
  profile_id: 3, display_name: "Fixture Own", username: "fixture_own", avatar_url: null,
  primary_caption: "Our own promo", daily_limit: 1, opted_in: true,
};
const SIBLING: S4SProjection = { ...OWN, profile_id: 5, display_name: "Fixture Sibling", username: "fixture_sibling" };
const PARTNER: S4SProjection = {
  profile_id: 8, display_name: "Fixture Partner", username: "fixture_partner", avatar_url: null,
  primary_caption: "Partner promo text", daily_limit: 2, opted_in: true,
};
const OTHER: S4SProjection = { ...PARTNER, profile_id: 9, display_name: "Fixture Other", username: "fixture_other" };

const PROFILE: S4SProfile = {
  account_id: "7000001", profile_id: 3, opted_in: true, discovery_visible: true, daily_limit: 1,
  display_name: "Fixture Own", username: "fixture_own", avatar_url: null,
  posts: [{ id: 41, caption: "Our own promo", is_primary: true, media: [] }],
};

const req = (id: number, box: "received" | "sent", status: S4SRequest["status"], partner = PARTNER, own = OWN): S4SRequest => ({
  id, box, status, slot_at: "2030-05-04T23:30:00Z",
  from: box === "received" ? partner : own, to: box === "received" ? own : partner,
  from_media: [], to_media: [],
  created_at: "2030-05-01T09:00:00Z", answered_at: status === "pending" ? null : "2030-05-02T09:00:00Z",
});

type Call = { method: string; url: string };
let fetchMock: ReturnType<typeof vi.fn>;
let received: S4SRequest[];
let sent: S4SRequest[];
let answer: Response | null;

beforeEach(() => {
  received = [
    req(21, "received", "pending"),
    req(23, "received", "pending", OTHER),
    req(22, "received", "declined", OTHER),
    req(24, "received", "pending", PARTNER, SIBLING),
  ];
  sent = [req(31, "sent", "pending"), req(32, "sent", "accepted", OTHER), req(33, "sent", "expired", OTHER)];
  answer = null;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/admin/s4s/requests?box=received") return jsonRes(received);
    if (url === "/admin/s4s/requests?box=sent") return jsonRes(sent);
    if ((init?.method ?? "GET") === "POST" && url.startsWith("/admin/s4s/requests/")) {
      return answer ?? jsonRes({ ...req(0, "received", "accepted") });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const calls = (): Call[] =>
  fetchMock.mock.calls.map(([url, init]) => ({ method: (init?.method ?? "GET") as string, url: String(url) }));
const posts = () => calls().filter((c) => c.method === "POST").map((c) => c.url);
const mount = () => renderWithProviders(<S4SRequests profile={PROFILE} accountId="7000001" />);
const latest = () => screen.getByRole("region", { name: "Latest request" });

describe("S4SRequests", () => {
  it("Latest request shows this creator's pending received requests one at a time, from the snapshot", async () => {
    mount();
    const card = await within(latest()).findByRole("article", { name: "Request from Fixture Partner" });
    expect(within(latest()).getByText("(1/2)")).toBeInTheDocument();
    expect(within(card).getByText("@fixture_partner")).toBeInTheDocument();
    expect(within(card).getByText("Partner promo text")).toBeInTheDocument();
    for (const name of ["Accept", "Decline", "Skip"]) expect(within(card).getByRole("button", { name })).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "View Schedule" })).toHaveAttribute(
      "href", "/share-for-share/schedule?creator=7000001");
  });

  it("Skip posts the answer and moves to the next request", async () => {
    mount();
    const card = await within(latest()).findByRole("article", { name: "Request from Fixture Partner" });
    received = received.filter((r) => r.id !== 21);
    fireEvent.click(within(card).getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(posts()).toEqual(["/admin/s4s/requests/21/skip"]));
    expect(await within(latest()).findByRole("article", { name: "Request from Fixture Other" })).toBeInTheDocument();
    expect(within(latest()).getByText("(1/1)")).toBeInTheDocument();
  });

  it("Accept opens Share for Share Scheduled! in UTC", async () => {
    mount();
    const card = await within(latest()).findByRole("article", { name: "Request from Fixture Partner" });
    fireEvent.click(within(card).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(posts()).toEqual(["/admin/s4s/requests/21/accept"]));
    const dialog = await screen.findByRole("dialog", { name: "Share for Share Scheduled!" });
    expect(within(dialog).getByText(/in UTC time zone on May 04, 2030 at 23:30/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Got It" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says so when there is no new request", async () => {
    received = [];
    sent = [];
    mount();
    expect(await within(latest()).findByText("You don’t have any new requests")).toBeInTheDocument();
    expect(await screen.findByText("You haven’t received any requests from other Creators")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Sent" }));
    expect(await screen.findByText("You haven’t sent any requests to other Creators")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Discover Creators" })).toBeInTheDocument();
  });

  it("the Received table lists this creator's requests with Infloww's status words and Review", async () => {
    mount();
    const table = await screen.findByRole("table", { name: "Received requests" });
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(4));
    expect(within(table).queryByText("Fixture Sibling")).toBeNull();
    expect(within(table).getAllByText("New Request")).toHaveLength(2);
    expect(within(table).getByText("Declined")).toHaveClass("text-[#ffa15f]");
    expect(within(table).getAllByText("May 01, 2030").length).toBe(3);
    fireEvent.click(within(table).getAllByRole("button", { name: "Review" })[0]);
    const dialog = screen.getByRole("dialog", { name: "Review request" });
    expect(within(dialog).getByRole("article", { name: "Request from Fixture Partner" })).toBeInTheDocument();
  });

  it("the Sent table shows each status, and Cancel asks first", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Sent" }));
    const table = await screen.findByRole("table", { name: "Sent requests" });
    await within(table).findByText("Request Sent");
    expect(within(table).getByText("Scheduled")).toHaveClass("text-[#ffa15f]");
    expect(within(table).getByText("Expired")).toHaveClass("text-[#ff7c71]");
    expect(within(table).getByRole("link", { name: "View Schedule" })).toBeInTheDocument();

    fireEvent.click(within(table).getByRole("button", { name: "Cancel" }));
    const confirm = screen.getByRole("dialog", { name: CANCEL_CONFIRM });
    fireEvent.click(within(confirm).getByRole("button", { name: "No" }));
    expect(posts()).toEqual([]);
    fireEvent.click(within(table).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: CANCEL_CONFIRM })).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(posts()).toEqual(["/admin/s4s/requests/31/cancel"]));
  });

  it("shows the relay's refusal when an answer is no longer possible", async () => {
    answer = jsonRes({ detail: "this request is no longer pending" }, 409);
    mount();
    const card = await within(latest()).findByRole("article", { name: "Request from Fixture Partner" });
    fireEvent.click(within(card).getByRole("button", { name: "Accept" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("this request is no longer pending");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows both snapshots before Accept: the partner's media your Creator posts, and your own they post", async () => {
    received = [{ ...req(21, "received", "pending"), from_media: [{ id: 5, media_type: "photo" }, { id: 6, media_type: "video" }],
      to_media: [{ id: 7, media_type: "photo" }] }];
    mount();
    const card = await within(latest()).findByRole("article", { name: "Request from Fixture Partner" });
    const mine = within(card).getByRole("group", { name: "Your Creator posts" });
    expect(within(mine).getByRole("img", { name: "S4S photo" })).toHaveAttribute("src", "/admin/s4s/media/5");
    expect(within(mine).getByRole("img", { name: "S4S video" })).toHaveAttribute("src", "/admin/s4s/media/6");
    expect(within(mine).getAllByRole("img")).toHaveLength(2);
    const theirs = within(card).getByRole("group", { name: "They post" });
    expect(within(theirs).getByRole("img", { name: "S4S photo" })).toHaveAttribute("src", "/admin/s4s/media/7");
  });
});
