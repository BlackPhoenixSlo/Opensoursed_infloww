/**
 * Discover creators (docs/spec/phase-03-share-for-share.md, Testing Decisions, seam 2; ADR-0011; page-parity 15),
 * rendered with the relay mocked at `fetch` by URL. The request goes from the creator picked on the rail (`from`).
 * Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import DiscoverCreators, { DEPLOYMENT_LINE, EMPTY_LINE } from "@/components/s4s/DiscoverCreators";
import type { S4SDiscoveryItem, S4SProfile } from "@/lib/s4s";

const OWN: S4SDiscoveryItem = {
  profile_id: 3, display_name: "Fixture Own", username: "fixture_own", avatar_url: null,
  primary_caption: "Our own promo", primary_media: [], daily_limit: 1, opted_in: true, own_agency: true,
};
/** Another Creator of the owner's own Agency: the user's case, two of their own Creators opted in. */
const SIBLING: S4SDiscoveryItem = {
  profile_id: 5, display_name: "Fixture Sibling", username: "fixture_sibling", avatar_url: null,
  primary_caption: "Sibling promo", primary_media: [], daily_limit: 1, opted_in: true, own_agency: true,
};
const OTHER: S4SDiscoveryItem = {
  profile_id: 8, display_name: "Fixture Partner", username: "fixture_partner",
  avatar_url: "https://example.invalid/partner.png", primary_caption: "Partner promo text", daily_limit: 2,
  opted_in: true, own_agency: false,
  primary_media: [{ id: 71, media_type: "photo" }, { id: 72, media_type: "video" }, { id: 73, media_type: "photo" }],
};

/** The rail's creators: one opted in with a Primary post (Discovery's OWN card, which it never shows itself), one
 *  opted out. */
const SENDER: S4SProfile = {
  account_id: "7000001", profile_id: 3, opted_in: true, discovery_visible: true, daily_limit: 1,
  display_name: "Fixture Own", username: "fixture_own", avatar_url: null,
  posts: [{ id: 41, caption: "Our own promo", is_primary: true, media: [] }],
};
const RESTING: S4SProfile = {
  account_id: "7000002", profile_id: 4, opted_in: false, discovery_visible: true, daily_limit: 1,
  display_name: "Fixture Resting", username: "fixture_resting", avatar_url: null,
  posts: [{ id: 42, caption: "Resting promo", is_primary: true, media: [] }],
};

let fetchMock: ReturnType<typeof vi.fn>;
let items: unknown[];
let sendReply: Response | null;
let blocks: unknown[];
/** The Relay's proposed time per sender account id; none (null) unless a case sets one. */
let proposals: Record<string, string | null>;

beforeEach(() => {
  items = [OTHER, OWN, SIBLING];
  sendReply = null;
  blocks = [];
  proposals = {};
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/admin/s4s/discover")) return jsonRes(items);
    if (url.startsWith("/admin/s4s/requests/proposal?")) {
      const from = new URL(url, "http://x").searchParams.get("from_account_id") ?? "";
      return jsonRes({ slot_at: proposals[from] ?? null });
    }
    if (url === "/admin/s4s/requests" && init?.method === "POST") return sendReply ?? jsonRes({ id: 51 }, 201);
    if (url === "/admin/s4s/blocks" && init?.method === "POST") return jsonRes({ profile_id: 8 });
    if (url === "/admin/s4s/blocks") return jsonRes(blocks);
    if (url === "/admin/s4s/blocks/8" && init?.method === "DELETE") return jsonRes({ unblocked: 8 });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const urls = () => fetchMock.mock.calls.map(([url]) => String(url));
const openCard = (name: string) => fireEvent.click(within(screen.getByRole("article", { name })).getByRole("button"));

describe("DiscoverCreators", () => {
  it("renders one card per Creator with the projection fields only, the own agency's tagged, the rail's own left out", async () => {
    // A key outside the projection, as a buggy Relay might send, never reaches the page.
    items = [{ ...OTHER, account_id: "7000009" }, OWN, SIBLING];
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    const partner = await screen.findByRole("article", { name: "Fixture Partner" });
    expect(within(partner).getByText("@fixture_partner")).toBeInTheDocument();
    expect(within(partner).getByText("Partner promo text")).toBeInTheDocument();
    expect(within(partner).getByText("Daily limit")).toBeInTheDocument();
    expect(within(partner).getByRole("img", { name: "Fixture Partner" })).toHaveAttribute(
      "src", "https://example.invalid/partner.png");
    expect(within(partner).queryByText("Your agency")).toBeNull();

    const sibling = screen.getByRole("article", { name: "Fixture Sibling" });
    expect(within(sibling).getByText("Your agency")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Fixture Own" })).toBeNull();

    expect(document.body.textContent).not.toContain("7000009");
    expect(screen.getByRole("textbox", { name: "Search by name or @username" })).toBeInTheDocument();
    expect(screen.getByText(DEPLOYMENT_LINE)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_LINE)).toBeNull();
    expect(urls().sort()).toEqual(["/admin/s4s/blocks", "/admin/s4s/discover"]);
  });

  it("shows the empty state when the list holds nothing but the rail's own creator", async () => {
    items = [OWN];
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    expect(await screen.findByText(EMPTY_LINE)).toBeInTheDocument();
    expect(screen.getByText("No creators available")).toBeInTheDocument();
    expect(screen.queryByRole("article")).toBeNull();
  });

  it("lists the owner's other creator with no empty state when no other agency takes part", async () => {
    items = [OWN, SIBLING];
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    expect(await screen.findByRole("article", { name: "Fixture Sibling" })).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_LINE)).toBeNull();
    expect(screen.queryByText("No creators available")).toBeNull();
  });

  it("filters by name or @username through the relay, with Infloww's no-match line", async () => {
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    items = [];
    fireEvent.change(screen.getByRole("textbox", { name: "Search by name or @username" }), { target: { value: "@part ner" } });
    await waitFor(() => expect(urls()).toContain("/admin/s4s/discover?q=%40part+ner"));
    expect(await screen.findByText("Try searching another keyword")).toBeInTheDocument();
    // A filtered-out list says nothing about whether other agencies opted in.
    expect(screen.queryByText(EMPTY_LINE)).toBeNull();
  });

  it("shows Infloww's load error with Refresh when the relay fails", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === "/admin/s4s/blocks" ? jsonRes([]) : jsonRes({ detail: "boom" }, 500));
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    expect(await screen.findByText(/The creator list failed to load/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_LINE)).toBeNull();
  });

  it("a card click opens the pop-up; Send request goes from the rail's creator at a UTC time", async () => {
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    const dialog = screen.getByRole("dialog", { name: "Fixture Partner" });
    const send = within(dialog).getByRole("button", { name: "Send request" });
    expect(send).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Proposed time"), { target: { value: "2030-05-04T10:00" } });
    fireEvent.click(send);
    expect(await within(dialog).findByRole("status")).toHaveTextContent("Request sent from Fixture Own.");
    expect(within(dialog).getByRole("button", { name: "Requested" })).toBeDisabled();
    const posted = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posted.map(([url]) => url)).toEqual(["/admin/s4s/requests"]);
    expect(JSON.parse(String(posted[0][1].body))).toEqual({
      from_account_id: "7000001", to_profile_id: 8, slot_at: "2030-05-04T10:00:00.000Z",
    });
  });

  it("prefills the proposed time with the Relay's 06:00 UTC on the first day free for both, and re-proposes it for another rail creator", async () => {
    const OTHER_SENDER: S4SProfile = { ...SENDER, account_id: "7000003", profile_id: 6, display_name: "Fixture Second" };
    proposals = { "7000001": "2030-05-04T06:00:00Z", "7000003": "2030-05-06T06:00:00Z" };
    const view = renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    const dialog = screen.getByRole("dialog", { name: "Fixture Partner" });
    const field = within(dialog).getByLabelText("Proposed time");
    await waitFor(() => expect(field).toHaveValue("2030-05-04T06:00"));
    const asked = () => urls().filter((u) => u.startsWith("/admin/s4s/requests/proposal?"))
      .map((u) => Object.fromEntries(new URL(u, "http://x").searchParams));
    expect(asked()).toEqual([{ from_account_id: "7000001", to_profile_id: "8" }]);
    expect(within(dialog).getByRole("button", { name: "Send request" })).toBeEnabled();

    // Another rail creator re-proposes for that pair.
    view.rerender(<DiscoverCreators from={OTHER_SENDER} />);
    await waitFor(() => expect(field).toHaveValue("2030-05-06T06:00"));
    expect(asked()[1]).toEqual({ from_account_id: "7000003", to_profile_id: "8" });
    expect(within(dialog).getByText("from Fixture Second")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Send request" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent("Request sent from Fixture Second.");
    const posted = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(posted[0][1].body))).toEqual({
      from_account_id: "7000003", to_profile_id: 8, slot_at: "2030-05-06T06:00:00.000Z",
    });
  });

  it("keeps an edit made while the proposal loads, and asks for none from an opted-out creator", async () => {
    let answer: (r: Response) => void = () => {};
    fetchMock.mockImplementation(async (url: string) => {
      if (url.startsWith("/admin/s4s/discover")) return jsonRes(items);
      if (url.startsWith("/admin/s4s/requests/proposal?")) return new Promise<Response>((r) => { answer = r; });
      return jsonRes([]);
    });
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    const field = within(screen.getByRole("dialog", { name: "Fixture Partner" })).getByLabelText("Proposed time");
    fireEvent.change(field, { target: { value: "2030-07-01T08:00" } });
    answer(jsonRes({ slot_at: "2030-05-04T06:00:00Z" }));
    await waitFor(() => expect(urls().some((u) => u.startsWith("/admin/s4s/requests/proposal?"))).toBe(true));
    await new Promise((r) => setTimeout(r, 0));
    expect(field).toHaveValue("2030-07-01T08:00");
    cleanup();

    fetchMock.mockClear();
    renderWithProviders(<DiscoverCreators from={RESTING} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    expect(urls().some((u) => u.includes("/proposal"))).toBe(false);
  });

  it("shows the Primary post's media in the pop-up's carousel, a placeholder when there is none or a still fails", async () => {
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    const dialog = screen.getByRole("dialog", { name: "Fixture Partner" });
    expect(within(dialog).getByText("Fixture Partner's S4S post")).toBeInTheDocument();
    expect(within(dialog).getByText("Daily limit: 2 per day")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("1 videos, 2 photos")).toBeInTheDocument();
    expect(within(dialog).getByRole("img", { name: "S4S photo 1 of 3" })).toHaveAttribute("src", "/admin/s4s/media/71");
    fireEvent.click(within(dialog).getByRole("button", { name: "Next media" }));
    expect(within(dialog).getByRole("img", { name: "S4S video 2 of 3" })).toHaveAttribute("src", "/admin/s4s/media/72");
    fireEvent.click(within(dialog).getByRole("button", { name: "Previous media" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Previous media" }));
    const last = within(dialog).getByRole("img", { name: "S4S photo 3 of 3" });
    expect(within(dialog).getByRole("button", { name: "Media 3" })).toHaveAttribute("aria-current", "true");
    // A still the Relay cannot read (the item left the vault) is a placeholder, not an error.
    fireEvent.error(last);
    expect(within(dialog).getByText("Preview unavailable")).toBeInTheDocument();
    expect(within(dialog).queryByRole("alert")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    openCard("Fixture Sibling");
    const empty = screen.getByRole("dialog", { name: "Fixture Sibling" });
    expect(within(empty).getByText("No media on this post")).toBeInTheDocument();
    expect(within(empty).queryByRole("button", { name: "Next media" })).toBeNull();
  });

  it("shows the relay's refusal", async () => {
    sendReply = jsonRes({ detail: "a Daily limit is full on that day" }, 409);
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    const dialog = screen.getByRole("dialog", { name: "Fixture Partner" });
    fireEvent.change(within(dialog).getByLabelText("Proposed time"), { target: { value: "2030-05-04T10:00" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send request" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("a Daily limit is full on that day");
  });

  it("offers no send from an opted-out creator", async () => {
    renderWithProviders(<DiscoverCreators from={RESTING} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Partner");
    const dialog = screen.getByRole("dialog", { name: "Fixture Partner" });
    expect(within(dialog).getByText(/Opt Fixture Resting in under S4S settings/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Send request" })).toBeDisabled();
  });

  it("blocks another agency's Creator from its pop-up, never the owner's own, and lifts it from the blocked list", async () => {
    renderWithProviders(<DiscoverCreators from={SENDER} />);
    await screen.findByRole("article", { name: "Fixture Partner" });
    openCard("Fixture Sibling");
    expect(within(screen.getByRole("dialog", { name: "Fixture Sibling" })).queryByRole("button", { name: "Block" })).toBeNull();
    fireEvent.click(within(screen.getByRole("dialog", { name: "Fixture Sibling" })).getByRole("button", { name: "Cancel" }));
    openCard("Fixture Partner");
    blocks = [{ ...OTHER, own_agency: undefined, blocked_at: "2030-05-01T09:00:00Z" }];
    fireEvent.click(within(screen.getByRole("dialog", { name: "Fixture Partner" })).getByRole("button", { name: "Block" }));
    const list = await screen.findByRole("region", { name: "Blocked creators" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const writes = () => fetchMock.mock.calls.filter(([, init]) => init?.method && init.method !== "GET");
    expect(writes().map(([url, init]) => [init.method, url, init.body])).toEqual([
      ["POST", "/admin/s4s/blocks", JSON.stringify({ profile_id: 8 })],
    ]);
    blocks = [];
    fireEvent.click(within(list).getByRole("button", { name: "Unblock" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Blocked creators" })).toBeNull());
    expect(writes().map(([url, init]) => [init.method, url])[1]).toEqual(["DELETE", "/admin/s4s/blocks/8"]);
  });
});
