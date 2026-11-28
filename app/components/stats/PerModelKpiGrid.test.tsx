import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";

vi.mock("@/contexts/UserContext", async (orig) => {
  const value = () => ({ user: { user_id: "owner-1", username: "owner" }, loading: false });
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: value, useOptionalUser: value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = () => ({ chatter: null });
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: value, useOptionalChatter: value };
});

import PerModelKpiGrid, { ofReadState } from "@/components/stats/PerModelKpiGrid";
import type { AccountMeta } from "@/lib/relay";
import { forgetScreenBundles, resetScreenBundles } from "@/lib/screenBundle";
import { jsonRes, renderWithProviders } from "@/test-utils";

const kinds = (tip: number) => ({ ppv: 0, post: 0, tip, subscription: 0, rebill: 0, custom: 0 });
const row = (id: string, cents: number) => ({
  account_id: id, display_name: `Creator ${id}`, total_revenue_cents: cents, pending_revenue_cents: 0,
  pending_clears_by: null, revenue_by_kind: kinds(cents), pending_by_kind: kinds(0), new_subs_count: 0,
  messages_sent: 3, ppv_conversions: 1,
});
const ACCOUNTS: AccountMeta[] = [
  { id: "live", has_session: true, is_active: true, proxy_down: false },
  { id: "nosession", has_session: false, is_active: true, proxy_down: false, color: "#ff0088" },
  { id: "dead", has_session: true, session_dead_at: "2026-10-28T09:00:00Z", is_active: true, proxy_down: false },
];

let fetchMock: ReturnType<typeof vi.fn>;
let accounts: () => Promise<Response>;

beforeEach(() => {
  accounts = async () => jsonRes({ accounts: ACCOUNTS, active_account_id: null });
  fetchMock = vi.fn(async (url: string) => {
    const u = new URL(String(url), "http://localhost");
    if (u.pathname === "/admin/stats/per-model") {
      return jsonRes({ per_model: [row("live", 1200), row("nosession", 3400), row("dead", 5600), row("gone", 780)] });
    }
    if (u.pathname === "/admin/accounts") return accounts();
    if (u.pathname === "/api/of/v2/users/me") return jsonRes({ id: "live", name: "Live One", username: "liveone", subscribePrice: 0,
      avatarThumbs: { c50: "https://public.onlyfans.com/files/live-c50.jpg" } });
    if (u.pathname === "/api/of/v2/subscriptions/count/all") return jsonRes({ subscribers: { active: 42, all: 50, expired: 8 } });
    if (u.pathname === "/api/of/v2/subscriptions/subscribers/chart") return jsonRes({ subscribers: 7 });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetScreenBundles();
});

const ofReads = () => fetchMock.mock.calls
  .map(([url, init]) => [new URL(String(url), "http://localhost").pathname,
    new Headers((init as RequestInit | undefined)?.headers).get("X-Account-Id")] as const)
  .filter(([path]) => path.startsWith("/api/of/"));

const card = (id: string) =>
  screen.getByText(id, { exact: false, selector: "div.text-\\[10px\\]" }).closest<HTMLElement>("div.p-4")!;

describe("PerModelKpiGrid on a Creator with no live OnlyFans session", () => {
  it("reads OF for the live Creator only, and labels the others from the accounts read", async () => {
    renderWithProviders(<PerModelKpiGrid from="2026-10-26T07:00:00.000Z" to="2026-11-02T07:59:59.999Z" />);
    await screen.findByText("Live One");
    await waitFor(() => expect(within(card("live")).getByText("42")).toBeInTheDocument());

    const sent = ofReads();
    expect(new Set(sent.map(([, id]) => id))).toEqual(new Set(["live"]));
    expect(sent.map(([path]) => path).sort()).toEqual([
      "/api/of/v2/subscriptions/count/all", "/api/of/v2/subscriptions/subscribers/chart", "/api/of/v2/users/me",
    ]);

    const off = within(card("nosession"));
    expect(off.getByText("Not connected")).toBeInTheDocument();
    expect(off.getAllByText("$34").length).toBeGreaterThan(0);
    expect(off.getByText("free")).toBeInTheDocument();
    expect(off.queryByText("…")).toBeNull();
    expect(within(card("dead")).getByText("Disconnected")).toBeInTheDocument();
    expect(within(card("gone")).getByText("Not connected")).toBeInTheDocument();
    expect(within(card("live")).queryByText(/connected/i)).toBeNull();
  });

  it("shows the live Creator's OF logo and the others' coloured initial, with no OF read for the others", async () => {
    renderWithProviders(<PerModelKpiGrid from="2026-10-26T07:00:00.000Z" to="2026-11-02T07:59:59.999Z" />);
    await screen.findByText("Live One");
    const logo = await waitFor(() => {
      const img = card("live").querySelector<HTMLImageElement>("[data-model-avatar] img");
      expect(img).not.toBeNull();
      return img!;
    });
    expect(logo.getAttribute("src")).toContain("live-c50.jpg");
    const initial = card("nosession").querySelector<HTMLElement>("[data-model-avatar] > span")!;
    expect(initial).toHaveTextContent("C");
    expect(initial).toHaveStyle({ background: "#ff0088" });
    expect(new Set(ofReads().map(([, id]) => id))).toEqual(new Set(["live"]));
  });

  it("sends no OF read before the accounts read answers", async () => {
    let answer!: () => void;
    accounts = () => new Promise((done) => { answer = () => done(jsonRes({ accounts: ACCOUNTS, active_account_id: null })); });
    renderWithProviders(<PerModelKpiGrid from="2026-10-26T07:00:00.000Z" to="2026-11-02T07:59:59.999Z" />);
    await screen.findByText("Creator nosession");
    expect(ofReads()).toHaveLength(0);
    answer();
    await screen.findByText("Live One");
    expect(new Set(ofReads().map(([, id]) => id))).toEqual(new Set(["live"]));
  });
});

describe("PerModelKpiGrid on a Fansly Creator, which lacks the subscribers chart", () => {
  const FROM = "2026-10-26T07:00:00.000Z";
  const TO = "2026-11-02T07:59:59.999Z";
  const MIXED: AccountMeta[] = [
    { id: "live", has_session: true, is_active: true, proxy_down: false },
    { id: "flfree", platform: "fansly", has_session: true, is_active: true, proxy_down: false },
    { id: "flpaid", platform: "fansly", has_session: true, is_active: true, proxy_down: false },
  ];
  const profiles: Record<string, object> = {
    live: { id: "live", name: "Live One", subscribePrice: 0 },
    flfree: { id: "flfree", name: "Fansly Free", subscribePrice: 0 },
    flpaid: { id: "flpaid", name: "Fansly Paid", subscribePrice: 9.99 },
  };
  const kpi = (id: string, label: string) =>
    within(card(id)).getByText(label).closest("div")!.querySelector("dd")!.textContent;

  beforeEach(() => {
    forgetScreenBundles();
    accounts = async () => jsonRes({ accounts: MIXED, active_account_id: null });
    const base = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://localhost");
      const id = new Headers(init?.headers).get("X-Account-Id") ?? "";
      if (u.pathname === "/admin/screens/dashboard") {
        return jsonRes({ answers: ["live", "flfree", "flpaid"].map((a) => ({ accountId: a, read: "newFans", body: { subscribers: 9 } })) });
      }
      if (u.pathname === "/admin/stats/per-model") {
        return jsonRes({ per_model: [row("live", 1200), row("flfree", 3400), { ...row("flpaid", 3400), new_subs_count: 4 }] });
      }
      if (u.pathname === "/api/of/v2/users/me") return jsonRes(profiles[id]);
      return base(url, init);
    });
  });

  it("settles the free card's New fans and LTV to — over a stale cached 0 and a warm bundle value, with no chart read; the paid card keeps New subs and LTV", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    client.setQueryData(["of-new-fans", "flfree", FROM, TO], 0);
    client.setQueryData(["of-new-fans", "flpaid", FROM, TO], 0);
    renderWithProviders(<PerModelKpiGrid from={FROM} to={TO} />, client);
    await screen.findByText("Fansly Free");
    await screen.findByText("Fansly Paid");
    await waitFor(() => expect(kpi("live", "New fans (30d)")).toBe("9"));
    await waitFor(() => expect(within(card("flfree")).getByText("free")).toBeInTheDocument());

    expect(kpi("flfree", "New fans (30d)")).toBe("—");
    expect(kpi("flfree", "LTV")).toBe("—");
    expect(kpi("flpaid", "New subs")).toBe("4");
    expect(kpi("flpaid", "LTV")).toBe("$8.50");
    expect(ofReads().filter(([path, id]) => path === "/api/of/v2/subscriptions/subscribers/chart" && id !== "live")).toEqual([]);
  });
});

describe("PerModelKpiGrid's card copy", () => {
  it("labels its revenue gross, and New subs / LTV say what is counted (sub starts, free and trial on the roster too)", async () => {
    const base = fetchMock.getMockImplementation() as (url: string) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string) => new URL(String(url), "http://localhost").pathname === "/admin/stats/per-model"
      ? jsonRes({ per_model: [{ ...row("nosession", 3400), revenue_by_kind: { ...kinds(0), subscription: 3400 }, new_subs_count: 4 }] })
      : base(url));
    renderWithProviders(<PerModelKpiGrid from="2026-10-26T07:00:00.000Z" to="2026-11-02T07:59:59.999Z" />);
    await screen.findByText("Creator nosession");
    const c = within(card("nosession"));
    expect(c.getByText("total revenue · gross")).toBeInTheDocument();
    const newSubs = c.getByText("New subs").closest("div")!.getAttribute("title")!;
    expect(newSubs).not.toMatch(/NOT counted|PAID/);
    expect(newSubs).toMatch(/free and trial/);
    expect(c.getByText("LTV").closest("div")!.getAttribute("title")).not.toMatch(/PAID/);
  });
});

describe("ofReadState", () => {
  const pending = { isPending: true, isError: false };
  const done = { isPending: false, isError: false };
  const offline = (a: AccountMeta | undefined) => {
    const s = ofReadState(a, done);
    return s && { live: s.live, label: s.conn?.label ?? null, tone: s.conn?.tone ?? null };
  };
  it("waits for the accounts read, then follows has_session, session_dead_at and is_active", () => {
    expect(ofReadState(undefined, pending)).toBeNull();
    expect(offline(ACCOUNTS[0])).toEqual({ live: true, label: null, tone: null });
    expect(offline(ACCOUNTS[1])).toEqual({ live: false, label: "Not connected", tone: "muted" });
    expect(offline(ACCOUNTS[2])).toEqual({ live: false, label: "Disconnected", tone: "err" });
    expect(offline({ id: "off", has_session: true, is_active: false, proxy_down: false })).toEqual({ live: false, label: "—", tone: "muted" });
  });
  it("labels a Creator the answered list lacks Not connected; a failed list reads OF as before", () => {
    expect(offline(undefined)).toEqual({ live: false, label: "Not connected", tone: "muted" });
    expect(ofReadState(undefined, { isPending: false, isError: true })).toEqual({ live: true, conn: null });
    expect(ofReadState(ACCOUNTS[1], { isPending: true, isError: true })).toEqual({ live: true, conn: null });
  });
});
