/**
 * PerModelKpiGrid's OnlyFans reads go only to a Creator with a live session: a
 * Creator with no captured session (or a flagged one) makes no OF call and its
 * card shows the ledger's figures under the Creators page's label.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";

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
import { jsonRes, renderWithProviders } from "@/test-utils";

const kinds = (tip: number) => ({ ppv: 0, post: 0, tip, subscription: 0, rebill: 0, custom: 0 });
const row = (id: string, cents: number) => ({
  account_id: id, display_name: `Creator ${id}`, total_revenue_cents: cents, pending_revenue_cents: 0,
  pending_clears_by: null, revenue_by_kind: kinds(cents), pending_by_kind: kinds(0), new_subs_count: 0,
  messages_sent: 3, ppv_conversions: 1,
});
const ACCOUNTS: AccountMeta[] = [
  { id: "live", has_session: true, is_active: true, proxy_down: false },
  { id: "nosession", has_session: false, is_active: true, proxy_down: false },
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
    if (u.pathname === "/api/of/v2/users/me") return jsonRes({ name: "Live One", username: "liveone", subscribePrice: 0 });
    if (u.pathname === "/api/of/v2/subscriptions/count/all") return jsonRes({ subscribers: { active: 42, all: 50, expired: 8 } });
    if (u.pathname === "/api/of/v2/subscriptions/subscribers/chart") return jsonRes({ subscribers: 7 });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The OF reads sent, as [path, X-Account-Id]. */
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
    // The ledger decides paid/free (no profile to wait for), and OF's figures read "—", never a spinner's "…".
    expect(off.getByText("free")).toBeInTheDocument();
    expect(off.queryByText("…")).toBeNull();
    expect(within(card("dead")).getByText("Disconnected")).toBeInTheDocument();
    // In the ledger but not in the accounts read: no account on this host (prod's 404 Unknown account_id).
    expect(within(card("gone")).getByText("Not connected")).toBeInTheDocument();
    expect(within(card("live")).queryByText(/connected/i)).toBeNull();
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
