/**
 * The S4S schedule (docs/spec/phase-03-share-for-share.md, Testing Decisions, seam 2; page-parity 15), for the
 * creator picked on the rail, rendered with the relay mocked at `fetch` by URL. Infloww's S4S pages are in UTC, so
 * the browser's time zone is pinned to America/New_York to prove the page ignores it, and the clock to 10 May 2030
 * 12:00Z: the month query is the UTC month, and a slot at 20 May 02:00Z (19 May 22:00 in New York) sits on 20 May.
 * Fixture names and ids are invented.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import S4SSchedule, { BANNER } from "@/components/s4s/S4SSchedule";
import type { S4SProfile, S4SProjection, S4SSlot } from "@/lib/s4s";

const proj = (profile_id: number, name: string): S4SProjection => ({
  profile_id, display_name: name, username: name.toLowerCase().replace(" ", "_"), avatar_url: null,
  primary_caption: `Promo of ${name}`, daily_limit: 1, opted_in: true,
});
const OWN = proj(1, "Fixture Own");
const SIBLING = proj(2, "Fixture Sibling");
const PROFILE: S4SProfile = {
  account_id: "7000001", profile_id: 1, opted_in: true, discovery_visible: true, daily_limit: 1,
  display_name: "Fixture Own", username: "fixture_own", avatar_url: null, posts: [],
};

const slot = (id: number, at: string, display_status: S4SSlot["display_status"], partner: string,
  status: S4SSlot["status"] = "scheduled", reason: string | null = null, own = OWN): S4SSlot => ({
  id, slot_at: at, status, display_status, reason, partner: proj(100 + id, partner), own, remove_at: null,
  partner_issue: null,
});

const MAY: S4SSlot[] = [
  slot(41, "2030-05-20T02:00:00Z", "Will be posted shortly", "Fixture Upcoming"),
  slot(42, "2030-05-10T08:00:00Z", "In progress", "Fixture Live", "posted"),
  slot(43, "2030-05-10T06:15:00Z", "Completed", "Fixture Done", "posted"),
  slot(44, "2030-05-21T12:00:00Z", "Canceled", "Fixture Gone", "scheduled", "partner_opted_out"),
  slot(45, "2030-05-06T12:00:00Z", "Failed", "Fixture Broken", "failed", "job_error"),
  slot(46, "2030-05-20T12:00:00Z", "Will be posted shortly", "Fixture Elsewhere", "scheduled", null, SIBLING),
];

const MAY_Q = "from=2030-05-01T00%3A00%3A00.000Z&to=2030-06-01T00%3A00%3A00.000Z";
const JUNE_Q = "from=2030-06-01T00%3A00%3A00.000Z&to=2030-07-01T00%3A00%3A00.000Z";

let fetchMock: ReturnType<typeof vi.fn>;
let may: S4SSlot[];
let cancelAnswer: Response | null;

beforeAll(() => {
  vi.stubEnv("TZ", "America/New_York");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2030-05-10T12:00:00Z"));
  may = MAY;
  cancelAnswer = null;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === `/admin/s4s/schedule?${MAY_Q}`) return jsonRes(may);
    if (url.startsWith("/admin/s4s/schedule?")) return jsonRes([]);
    if ((init?.method ?? "GET") === "POST" && url.startsWith("/admin/s4s/slots/")) {
      return cancelAnswer ?? jsonRes({ ...MAY[0], status: "canceled", display_status: "Canceled", reason: "owner_canceled" });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const urls = (method = "GET") =>
  fetchMock.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method).map(([url]) => String(url));
const card = (partner: string) => screen.findByRole("article", { name: `S4S slot with ${partner}` });
const day = (label: string) => within(screen.getByRole("grid", { name: "May 2030" })).getByRole("button", { name: label });
const mount = (livePosting?: boolean) => renderWithProviders(<S4SSchedule profile={PROFILE} livePosting={livePosting} />);

describe("S4SSchedule", () => {
  it("opens on today in UTC with its slots, Infloww's status words, and the statistics", async () => {
    mount(true);
    expect(screen.getByRole("heading", { name: "Scheduled S4S" })).toBeInTheDocument();
    expect(screen.getByText("May 10, 2030")).toBeInTheDocument();
    expect(within(await card("Fixture Live")).getByText("In progress")).toBeInTheDocument();
    const done = await card("Fixture Done");
    expect(within(done).getByText("Complete")).toBeInTheDocument();
    expect(within(done).getByText("Posted at May. 10 06:15")).toBeInTheDocument();
    expect(screen.getByText("Scheduled for May 10").previousSibling).toHaveTextContent("2");
    expect(screen.getByText("Completed Share for Shares").previousSibling).toHaveTextContent("1");
    expect(screen.getByText("Total Growth").parentElement).toHaveAttribute("title", "not wired");
    expect(urls()).toEqual([`/admin/s4s/schedule?${MAY_Q}`]);
  });

  it("marks the days with S4S for this creator only, in UTC, and only those days and today pick", async () => {
    mount(true);
    await card("Fixture Live");
    expect(day("May 20, 2030")).toHaveAttribute("data-s4s", "true");
    expect(day("May 19, 2030")).not.toHaveAttribute("data-s4s");
    expect(day("May 19, 2030")).toBeDisabled();
    expect(day("May 10, 2030")).toBeEnabled();
    fireEvent.click(day("May 20, 2030"));
    expect(screen.getByText("May 20, 2030")).toBeInTheDocument();
    const upcoming = await card("Fixture Upcoming");
    expect(upcoming).toHaveTextContent("02:00 UTC");
    expect(within(upcoming).getByText("Will be posted shortly")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "S4S slot with Fixture Elsewhere" })).toBeNull();
  });

  it("shows a Cancelled or Failed slot's reason; Failed is ours, with its tooltip", async () => {
    mount(true);
    await card("Fixture Live");
    fireEvent.click(day("May 21, 2030"));
    const gone = await card("Fixture Gone");
    expect(within(gone).getByText("Cancelled")).not.toHaveAttribute("title");
    expect(within(gone).getByText("partner opted out")).toBeInTheDocument();
    fireEvent.click(day("May 06, 2030"));
    const broken = await card("Fixture Broken");
    expect(within(broken).getByText("Failed")).toHaveAttribute("title", "Inflowwww extra");
    expect(within(broken).getByText("job error")).toBeInTheDocument();
  });

  it("shows the live-posting-off line only while live posting is off", async () => {
    mount(false);
    expect(await screen.findByRole("status")).toHaveTextContent(BANNER);
    cleanup();
    mount(true);
    await card("Fixture Live");
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it("Cancel asks first, then cancels a future slot that will still post", async () => {
    mount(true);
    await card("Fixture Live");
    expect(within(await card("Fixture Live")).queryByRole("button")).toBeNull();
    fireEvent.click(day("May 20, 2030"));
    const upcoming = await card("Fixture Upcoming");
    fireEvent.click(within(upcoming).getByRole("button", { name: "Cancel" }));
    const confirm = screen.getByRole("dialog", { name: "Cancel this Share for Share?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "No" }));
    expect(urls("POST")).toEqual([]);
    may = MAY.filter((s) => s.id !== 41);
    fireEvent.click(within(upcoming).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Cancel this Share for Share?" })).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(urls("POST")).toEqual(["/admin/s4s/slots/41/cancel"]));
    await waitFor(() => expect(screen.queryByRole("article", { name: "S4S slot with Fixture Upcoming" })).toBeNull());
  });

  it("shows the relay's refusal when the slot can no longer be cancelled", async () => {
    cancelAnswer = jsonRes({ detail: "this slot is no longer scheduled" }, 409);
    mount(true);
    await card("Fixture Live");
    fireEvent.click(day("May 20, 2030"));
    fireEvent.click(within(await card("Fixture Upcoming")).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Cancel this Share for Share?" })).getByRole("button", { name: "Yes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("this slot is no longer scheduled");
  });

  it("moves by UTC month with the arrows", async () => {
    mount(true);
    await card("Fixture Live");
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByRole("grid", { name: "June 2030" })).toBeInTheDocument();
    await waitFor(() => expect(urls()).toContain(`/admin/s4s/schedule?${JUNE_Q}`));
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(screen.getByRole("grid", { name: "May 2030" })).toBeInTheDocument();
  });

  it("says so when the picked day has no S4S", async () => {
    may = [];
    mount(true);
    expect(await screen.findByText("No scheduled Share for Shares")).toBeInTheDocument();
  });

  it("says when the partner's own post of the pair was found deleted, archived or edited", async () => {
    may = [{ ...MAY[0], partner_issue: "post_deleted" }];
    mount();
    await waitFor(() => expect(day("May 20, 2030")).toBeEnabled());
    fireEvent.click(day("May 20, 2030"));
    expect(within(await card("Fixture Upcoming")).getByText("Partner's post: post deleted")).toBeInTheDocument();
  });
});
