/**
 * The answer's live cards (spec D12): a figure comes from the endpoint with the
 * asker's session, never from the model. A role the endpoint refuses (403)
 * reads "Not available for your role" — never $0.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";

const { relayGet } = vi.hoisted(() => ({ relayGet: vi.fn() }));

vi.mock("@/lib/relay", () => ({ relay: { get: (...a: unknown[]) => relayGet(...a) } }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: "1001" }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a {...rest} href={href}>{children}</a>,
}));

import { renderWithProviders } from "@/test-utils";
import { AnswerText } from "./AnswerText";

/** The relay's 403 as `request` throws it: a status on the error. */
const forbidden = () => Object.assign(new Error("relay 403"), { status: 403 });

function serve(routes: Record<string, unknown>) {
  relayGet.mockImplementation((path: string) => {
    if (path.startsWith("/admin/settings/applied")) return Promise.resolve({ preferences: { report_tz: "UTC" } });
    for (const [prefix, body] of Object.entries(routes)) {
      if (path.startsWith(prefix)) return body instanceof Error ? Promise.reject(body) : Promise.resolve(body);
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

beforeEach(() => { relayGet.mockReset(); });
afterEach(cleanup);

describe("AnswerText markers", () => {
  it("a 403 reads 'Not available for your role', never $0", async () => {
    serve({ "/admin/stats/revenue": forbidden() });
    renderWithProviders(<AnswerText text="Here's today: [[data:revenue|today|this]]" focus="1001" />);
    expect(await screen.findByText("Not available for your role")).toBeTruthy();
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("an invalid marker is dropped silently: no card, no brackets", async () => {
    serve({});
    const { container } = renderWithProviders(<AnswerText text="Online now [[data:online_fans|now|all]]." focus="1001" />);
    expect(container.textContent).toBe("Online now.");
    expect(screen.queryByTestId("assistant-data-card")).toBeNull();
    expect(relayGet).not.toHaveBeenCalled();
  });

  it("past 2 markers the rest are dropped", async () => {
    serve({
      "/admin/stats/revenue": { rows: [{ total_cents: 500 }] },
      "/admin/top-tippers": { rows: [{ fan_id: 9, fan: { display_name: "Big Tim", username: "tim" }, total_cents: 2500 }] },
      "/admin/stats/per-model": { per_model: [] },
    });
    renderWithProviders(
      <AnswerText
        text={"[[data:revenue|7d|this]] [[data:top_tippers|7d|this]] [[data:per_model|7d|all]]"}
        focus="1001"
      />,
    );
    await waitFor(() => expect(screen.getAllByTestId("assistant-data-card")).toHaveLength(2));
    expect(await screen.findByText("$5")).toBeTruthy();
    expect(await screen.findByText("Big Tim")).toBeTruthy();
    expect(relayGet.mock.calls.some(([p]) => String(p).startsWith("/admin/stats/per-model"))).toBe(false);
  });

  it("strips the model's digits beside a marker; the card shows the live figure", async () => {
    serve({ "/admin/stats/fan-report": { top_fans: [{ fan_id: 1, fan_name: null, username: "lena", total_cents: 12300 }] } });
    const { container } = renderWithProviders(
      <AnswerText text="Your 3 best fans spent $4,000 [[data:top_spenders|this_month|all]]. Settings has 3 tabs." />,
    );
    expect(await screen.findByText("@lena")).toBeTruthy();
    expect(screen.getByText("$123")).toBeTruthy();
    expect(container.querySelector("p")?.textContent).toBe("Your best fans spent. Settings has 3 tabs.");
    const [path] = relayGet.mock.calls.find(([p]) => String(p).startsWith("/admin/stats/fan-report"))!;
    expect(String(path)).not.toContain("account_id"); // all = every account the session sees
    expect(String(path)).toContain("from=");
  });

  /** `/users/me` per account: a count, an Error to reject, or undefined (no count). */
  function serveUnread(byAccount: Record<string, number | Error | undefined>) {
    relayGet.mockImplementation((path: string, ctx?: { accountId?: string }) => {
      if (path.startsWith("/admin/settings/applied")) return Promise.resolve({});
      const v = byAccount[ctx?.accountId ?? ""];
      return v instanceof Error ? Promise.reject(v) : Promise.resolve({ chatMessagesCount: v });
    });
  }
  const unreadCalls = () => relayGet.mock.calls.filter(([p]) => p === "/api/of/v2/users/me").length;

  it("unread sums every account's live chat count for 'all'", async () => {
    serveUnread({ "1001": 4, "1002": 3 });
    renderWithProviders(<AnswerText text="Unread: [[data:unread|now|all]]" focus="1001" accountIds={["1001", "1002"]} />);
    expect(await screen.findByText("7")).toBeTruthy();
  });

  it("unread 'all' waits for the roster: no '0' while it loads", async () => {
    serveUnread({});
    renderWithProviders(<AnswerText text="Unread: [[data:unread|now|all]]" focus="1001" accountIds={null} />);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/settings/applied", expect.anything()));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("Loading…")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
    expect(unreadCalls()).toBe(0);
  });

  it("unread 'all' with no models connected says so, never '0'", async () => {
    serveUnread({});
    renderWithProviders(<AnswerText text="Unread: [[data:unread|now|all]]" focus="1001" accountIds={[]} />);
    expect(await screen.findByText("No models connected")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it.each<[string, Record<string, number | Error | undefined>]>([
    ["one account failing", { "1001": 4, "1002": new Error("relay 502") }],
    ["one account with no count", { "1001": 4, "1002": undefined }],
  ])("unread 'all' with %s is an error, never a partial sum", async (_name, byAccount) => {
    serveUnread(byAccount);
    renderWithProviders(<AnswerText text="Unread: [[data:unread|now|all]]" focus="1001" accountIds={["1001", "1002"]} />);
    expect(await screen.findByText("Couldn't load this right now")).toBeTruthy();
    expect(screen.queryByText("4")).toBeNull();
  });

  it("revenue by model shows the top 5 and says how many more", async () => {
    const rows = Array.from({ length: 7 }, (_, i) => ({ account_id: `m${i}`, display_name: `Model ${i}`, total_revenue_cents: (7 - i) * 100 }));
    serve({ "/admin/stats/per-model": { per_model: rows } });
    renderWithProviders(<AnswerText text="By model: [[data:per_model|7d|all]]" focus="1001" />);
    expect(await screen.findByText("Model 4")).toBeTruthy();
    expect(screen.queryByText("Model 5")).toBeNull();
    expect(screen.getByText("Top 5 models · 2 more")).toBeTruthy();
  });

  it("cuts the window in the card's own model's report zone, not the app's", async () => {
    relayGet.mockImplementation((path: string, ctx?: { accountId?: string | null }) => {
      if (path.startsWith("/admin/settings/applied")) {
        return Promise.resolve({ preferences: { report_tz: ctx?.accountId === "1002" ? "America/New_York" : "UTC" } });
      }
      return Promise.resolve({ rows: [{ total_cents: 500 }] });
    });
    renderWithProviders(<AnswerText text="Today: [[data:revenue|today|this]]" focus="1002" />); // app scope: 1001
    expect(await screen.findByText("$5")).toBeTruthy();
    const [path] = relayGet.mock.calls.find(([p]) => String(p).startsWith("/admin/stats/revenue"))!;
    const from = new URL(String(path), "http://x").searchParams.get("from");
    expect(from).toMatch(/T0[45]:00:00\.000Z$/); // New York midnight, not UTC's
  });

  it("a chat marker is a button into the fan's chat once the handle resolves; else plain text", async () => {
    relayGet.mockImplementation((path: string) =>
      path === "/api/of/v2/users/lena" ? Promise.resolve({ id: 555 }) : Promise.reject(new Error("404")));
    renderWithProviders(<AnswerText text="Reply to [[chat:@lena]] and [[chat:@ghost]]." focus="1001" canChat />);
    const link = await screen.findByRole("link", { name: "Open @lena's chat" });
    expect(link.getAttribute("href")).toBe("/messages-pro/1001/555");
    expect(screen.getByText("Reply to @lena and @ghost.")).toBeTruthy();
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/api/of/v2/users/ghost", expect.anything()));
    expect(screen.queryByRole("link", { name: "Open @ghost's chat" })).toBeNull();
  });

  it("no chat button when the session may not open Messages Pro: the handle stays plain text", async () => {
    relayGet.mockImplementation((path: string) =>
      path === "/api/of/v2/users/lena" ? Promise.resolve({ id: 555 }) : Promise.reject(new Error("404")));
    renderWithProviders(<AnswerText text="Reply to [[chat:@lena]]." focus="1001" canChat={false} />);
    expect(screen.getByText("Reply to @lena.")).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("link")).toBeNull();
    expect(relayGet).not.toHaveBeenCalledWith("/api/of/v2/users/lena", expect.anything());
  });
});
