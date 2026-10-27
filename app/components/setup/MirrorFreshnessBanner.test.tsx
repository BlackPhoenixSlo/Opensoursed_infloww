/**
 * The mirror freshness alarm (roadmap 8.7): the live OF build, as
 * /admin/rev/live reports it from the relay's own OF traffic, against the
 * build the OF Manager mirror was captured from. Fixture revs are invented
 * except OF_MIRROR_BUILD itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn() },
}));

import MirrorFreshnessBanner from "./MirrorFreshnessBanner";
import { relay } from "@/lib/relay";
import { OF_MIRROR_BUILD } from "@/lib/of-mirror-build";
const relayGet = relay.get as unknown as Mock;

const MIRROR = "OF Manager mirror is behind OnlyFans";
let live: unknown;

beforeEach(() => {
  window.localStorage.clear();
  relayGet.mockReset();
  relayGet.mockImplementation(() => Promise.resolve(live));
});
afterEach(cleanup);

const report = (live_rev: string | null) => ({ live_rev, live_fetched_at: null });

describe("MirrorFreshnessBanner", () => {
  it("flags the mirror when OF's live build is newer than the captured one, naming both", async () => {
    live = report("202612010900-abcdef0123");
    renderWithProviders(<MirrorFreshnessBanner />);
    await screen.findByText(MIRROR);
    expect(relayGet).toHaveBeenCalledWith("/admin/rev/live");
    expect(screen.getByText(OF_MIRROR_BUILD)).toBeTruthy();
    expect(screen.getByText("202612010900-abcdef0123")).toBeTruthy();
  });

  it("stays quiet on the captured build, an older one (a stale session seed), or an unknown live rev", async () => {
    for (const rev of [OF_MIRROR_BUILD, "202601010000-0000000000", "rev-2", null]) {
      live = report(rev);
      const { unmount, queryClient } = renderWithProviders(<MirrorFreshnessBanner />);
      await vi.waitFor(() => expect(queryClient.getQueryState(["live-rev"])?.status).toBe("success"));
      expect(screen.queryByText(MIRROR)).toBeNull();
      unmount();
    }
  });

  it("is dismissed per live build: a newer build brings it back", async () => {
    live = report("202612010900-abcdef0123");
    const { unmount } = renderWithProviders(<MirrorFreshnessBanner />);
    const mirror = (await screen.findByText(MIRROR)).closest("[role=alert]")!;
    fireEvent.click(mirror.querySelector("button")!);
    expect(screen.queryByText(MIRROR)).toBeNull();
    unmount();

    live = report("202612020900-fedcba9876");
    renderWithProviders(<MirrorFreshnessBanner />);
    await screen.findByText(MIRROR);
  });
});
