/**
 * The `/share-for-share/[section]` route module (docs/spec/phase-03-share-for-share.md, UI; page-parity 15): each of
 * the four sections renders its legacy header (the UTC line on Requests and S4S schedule) and the S4S creator rail
 * (the S4S tag, the count of new requests) beside its body for the rail's creator; an unknown section is a 404, and
 * a chatter gets the owner-only sentence and no S4S call. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

let session: { user: { user_id: string; username: string } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", async (orig) => {
  const value = () => ({ user: session.user, loading: false });
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: value, useOptionalUser: value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = () => ({ chatter: session.chatter });
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: value, useOptionalChatter: value };
});
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/share-for-share/requests",
}));
vi.mock("@/hooks/useAccounts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAccounts")>()),
  useActiveAccounts: () => [
    { id: "7000001", nickname: "fixture_one", has_session: true },
    { id: "7000002", nickname: "Fixture Two", has_session: true },
  ],
}));

import Page from "@/app/share-for-share/[section]/page";

const projection = (profile_id: number, display_name: string) => ({
  profile_id, display_name, username: display_name.toLowerCase().replace(" ", "_"), avatar_url: null,
  primary_caption: "Promo", daily_limit: 1, opted_in: true,
});

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  session = { user: { user_id: "owner-1", username: "owner" }, chatter: null };
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/admin/s4s/profiles") {
      return jsonRes({
        live_posting: false,
        profiles: [
          { account_id: "7000001", profile_id: 3, opted_in: true, discovery_visible: true, daily_limit: 1,
            display_name: "fixture_one", username: "fixture_one", avatar_url: null,
            posts: [{ id: 41, caption: "Our promo", is_primary: true, media: [] }] },
          { account_id: "7000002", profile_id: null, opted_in: false, discovery_visible: true, daily_limit: 1,
            display_name: "Fixture Two", username: "fixture_two", avatar_url: null, posts: [] },
        ],
      });
    }
    if (url === "/admin/s4s/discover") {
      return jsonRes([{ ...projection(5, "Fixture Partner"), own_agency: false }]);
    }
    if (url === "/admin/s4s/requests?box=received") {
      return jsonRes([{
        id: 21, box: "received", status: "pending", slot_at: "2030-05-04T10:00:00Z",
        from: projection(5, "Fixture Partner"), to: projection(3, "fixture_one"),
        from_media: [], to_media: [], created_at: "2030-05-01T09:00:00Z", answered_at: null,
      }]);
    }
    if (url.startsWith("/admin/s4s/schedule?from=")) return jsonRes([]);
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const render = async (section: string) =>
  renderWithProviders(await Page({ params: Promise.resolve({ section }) }));
const s4sUrls = () => fetchMock.mock.calls.map(([url]) => String(url)).filter((u) => u.startsWith("/admin/s4s"));

describe("/share-for-share/[section]", () => {
  it.each([
    ["discover-creators", "Discover creators", false],
    ["requests", "Requests", true],
    ["schedule", "S4S schedule", true],
    ["settings", "S4S settings", false],
  ])("%s renders its header and the S4S rail", async (section, title, utc) => {
    await render(section);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.queryByText("Date/Time shown in UTC time zone") !== null).toBe(utc);
    const rows = await screen.findAllByTestId("of-creator-row");
    expect(rows).toHaveLength(2);
    await waitFor(() => expect(within(rows[0]).getByText("S4S")).toBeInTheDocument());
    expect(await within(rows[0]).findByLabelText("1 new request")).toBeInTheDocument();
    expect(within(rows[1]).queryByText("S4S")).toBeNull();
    expect(screen.queryByText("All creators")).toBeNull();
  });

  it("discover-creators lists Discovery cards", async () => {
    await render("discover-creators");
    expect(await screen.findByRole("article", { name: "Fixture Partner" })).toBeInTheDocument();
  });

  it("requests shows the first creator's latest request", async () => {
    await render("requests");
    const latest = screen.getByRole("region", { name: "Latest request" });
    expect(await within(latest).findByRole("article", { name: "Request from Fixture Partner" })).toBeInTheDocument();
    expect(within(latest).getByText("(1/1)")).toBeInTheDocument();
  });

  it("schedule shows the calendar and the live-posting-off line", async () => {
    await render("schedule");
    expect(await screen.findByText("No scheduled Share for Shares")).toBeInTheDocument();
    expect(await screen.findByText(/Live posting is off on this deployment/)).toBeInTheDocument();
    expect(s4sUrls().filter((u) => u.startsWith("/admin/s4s/schedule?from="))).toHaveLength(1);
  });

  it("settings shows the rail creator's settings page", async () => {
    await render("settings");
    expect(await screen.findByRole("region", { name: "S4S settings for fixture_one" })).toBeInTheDocument();
    expect(screen.getByText("Our promo")).toBeInTheDocument();
  });

  it("is a 404 for an unknown section", async () => {
    await expect(render("community")).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it.each(["requests", "discover-creators", "schedule", "settings"])("shows a chatter the owner-only sentence on %s and loads nothing", async (section) => {
    session = { user: null, chatter: { username: "chatter" } };
    await render(section);
    expect(screen.getByText("Only the agency owner manages Share for Share.")).toBeInTheDocument();
    expect(screen.queryByTestId("of-creator-row")).toBeNull();
    expect(s4sUrls()).toEqual([]);
  });
});
