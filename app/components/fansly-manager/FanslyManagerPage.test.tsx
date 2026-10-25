/**
 * Fansly Manager v1 (roadmap 8.1) behind the `fansly_manager` flag: off, a direct visit is "not available" and reads
 * nothing; on, each page reads its Relay route for the picked Fansly creator (never an OnlyFans one), with the relay
 * mocked at `fetch` by URL. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { FanslyManagerPage } from "@/components/fansly-manager/FanslyManagerPage";
import { findNavLink } from "@/lib/nav";
import type { FeatureFlags } from "@/lib/appliedSettings";

let flags: FeatureFlags | undefined;
vi.mock("@/components/shell/useFlags", () => ({ useFlags: () => flags }));

const ACCOUNTS = [
  { id: "of-1", nickname: "Fixture OF", platform: "onlyfans", has_session: true },
  { id: "fy-1", nickname: "Fixture Fansly", platform: "fansly", has_session: true },
];
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ isSuccess: true, data: { accounts: ACCOUNTS } }),
  useActiveAccounts: () => ACCOUNTS,
}));

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  flags = { fansly_manager: true };
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/of/v2/users/notifications/count") return jsonRes({ all: 3, tips: 1 });
    if (url.startsWith("/api/of/v2/users/notifications?")) {
      return jsonRes({ list: [{ id: "n1", type: "tip", text: "Fixture Fan tipped $5", createdAt: null, isRead: false, user: { name: "Fixture Fan" } }] });
    }
    if (url === "/api/of/v2/lists?limit=50") return jsonRes({ list: [{ id: "l1", name: "Fixture Whales" }], hasMore: false });
    if (url === "/api/of/v2/schedules?limit=50") {
      return jsonRes({ list: [{ id: "900", type: "post", publishDateTime: "2030-05-20T12:00:00+00:00", entity: { id: "900", text: "Fixture post" } }] });
    }
    if (method === "DELETE" && url === "/api/of/v2/messages/queue/900") return jsonRes({ success: true });
    if (url.startsWith("/admin/stats/revenue?")) {
      return jsonRes({ rows: [{ kind: "tip", total_cents: 1500, count: 2 }, { kind: "ppv", total_cents: 1000, count: 1 }] });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const header = (call: unknown[], name: string) => new Headers((call[1] as RequestInit | undefined)?.headers).get(name);

describe("FanslyManagerPage", () => {
  it("with the flag off a direct visit is not available and reads nothing", () => {
    flags = { fansly_manager: false };
    renderWithProviders(<FanslyManagerPage link={findNavLink("/fansly-manager/notifications")!} />);
    expect(screen.getByText("Notifications is not available.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("waits for the flags rather than flash not available", () => {
    flags = undefined;
    const { container } = renderWithProviders(<FanslyManagerPage link={findNavLink("/fansly-manager/lists")!} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("Notifications reads the feed and counts for the Fansly creator", async () => {
    renderWithProviders(<FanslyManagerPage link={findNavLink("/fansly-manager/notifications")!} />);
    expect(await screen.findByText("Fixture Fan tipped $5")).toBeInTheDocument();
    const feed = fetchMock.mock.calls.find(([u]) => String(u).startsWith("/api/of/v2/users/notifications?"))!;
    expect(header(feed, "X-Account-Id")).toBe("fy-1");
    expect(screen.getByLabelText("Unread")).toBeInTheDocument();
  });

  it("Lists shows the names and Create list posts the name", async () => {
    renderWithProviders(<FanslyManagerPage link={findNavLink("/fansly-manager/lists")!} />);
    expect(await screen.findByText("Fixture Whales")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create list" }));
    fireEvent.change(screen.getByLabelText("List name"), { target: { value: " Fixture New " } });
    fetchMock.mockImplementationOnce(async () => jsonRes({ id: "l2", name: "Fixture New" }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const post = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "POST")!;
    expect(post[0]).toBe("/api/of/v2/lists");
    expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({ name: "Fixture New" });
    expect(header(post, "X-Account-Id")).toBe("fy-1");
  });

  it("Scheduled lists the queued post and Cancel deletes its queue item", async () => {
    renderWithProviders(<FanslyManagerPage link={findNavLink("/fansly-manager/scheduled")!} />);
    expect(await screen.findByText("Fixture post")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel post" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const del = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "DELETE")!;
    expect(del[0]).toBe("/api/of/v2/messages/queue/900");
    expect(header(del, "X-Account-Id")).toBe("fy-1");
  });

  it("Earning statistics sums our recorded purchases for the Fansly creator", async () => {
    renderWithProviders(<FanslyManagerPage link={findNavLink("/fansly-manager/earning-statistics")!} />);
    expect(await screen.findByTestId("fansly-earnings-total")).toHaveTextContent(/^\$25$/);
    expect(screen.getAllByText("Purchases recorded by us").length).toBeGreaterThan(0);
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).startsWith("/admin/stats/revenue?"))![0]);
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("account_id")).toBe("fy-1");
    expect(qs.get("group_by")).toBe("kind");
    expect(qs.get("from")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
