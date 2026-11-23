/** useRosterCounts: the Relay's answer cached as is, the `?bust=` rewarm, and the Knob-off fallback poll. */
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const principal = vi.hoisted(() => ({ chatter: false }));
vi.mock("@/contexts/UserContext", async (orig) => ({
  ...(await orig<object>()),
  useOptionalUser: () => (principal.chatter ? null : { user: { user_id: "u1" }, loading: false }),
}));
vi.mock("@/contexts/ChatterContext", async (orig) => ({
  ...(await orig<object>()),
  useOptionalChatter: () => (principal.chatter ? { chatter: { chatter_id: "c1" } } : null),
}));

import { eventBus } from "@/lib/events";
import { relay } from "@/lib/relay";
import { ownerAccountsQuery } from "@/lib/ownerAccounts";
import { chatterAccountsQuery } from "@/lib/chatterAccounts";
import {
  useRosterCountActions,
  useRosterCountsRead,
  resetRosterCountsModuleState,
  type RosterCountsResp,
} from "./useRosterCounts";

describe("the roster-counts cache holds the Relay's answer, nothing of the tab's own", () => {
  const KEY = ["roster-counts", "u1"] as const;
  const FULL = "/admin/accounts/roster-counts";
  const BUST = (aid: string) => `${FULL}?bust=${aid}`;
  type Answer = { resolve: (r: RosterCountsResp) => void; reject: (e: unknown) => void };
  let answers: Map<string, Answer[]>;
  let get: ReturnType<typeof vi.spyOn>;
  const qcOf = () => new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });
  const wrap = (qc: QueryClient) => function Wrap({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
  const calls = (path: string) => get.mock.calls.filter(([p]: unknown[]) => p === path).length;
  const answer = async (path: string, r: RosterCountsResp | Error) => {
    await waitFor(() => expect(answers.get(path)?.length).toBeTruthy());
    const a = answers.get(path)!.shift()!;
    await act(async () => { if (r instanceof Error) a.reject(r); else a.resolve(r); await Promise.resolve(); });
  };
  const actions = (qc: QueryClient) => renderHook(() => useRosterCountActions(), { wrapper: wrap(qc) }).result;

  beforeEach(() => {
    resetRosterCountsModuleState();
    principal.chatter = false;
    answers = new Map();
    get = vi.spyOn(relay, "get").mockImplementation((path: string) => new Promise((resolve, reject) => {
      answers.set(path, [...(answers.get(path) ?? []), { resolve, reject } as Answer]);
    }) as never);
  });
  afterEach(() => vi.restoreAllMocks());

  it("a full answer replaces the cached one as is: no merge with a prior entry", async () => {
    const qc = qcOf();
    qc.setQueryData<RosterCountsResp>(KEY, { counts: { a: { unread: 4, owe_reply: 1 }, b: { unread: 2, owe_reply: 0 } } });
    const read = renderHook(() => useRosterCountsRead(), { wrapper: wrap(qc) });
    void act(() => { void qc.refetchQueries({ queryKey: KEY }); });
    const server = { counts: { a: { unread: 0, owe_reply: 0 } } };
    await answer(FULL, server);
    await waitFor(() => expect(read.result.current.counts).toEqual(server.counts));
    expect(qc.getQueryData(KEY)).toEqual(server);
  });

  it("two concurrent refreshOne for one Creator: one ?bust=, only that Creator written as answered", async () => {
    const qc = qcOf();
    const other = { unread: 7, owe_reply: 0 };
    qc.setQueryData<RosterCountsResp>(KEY, { counts: { a: { unread: 4, owe_reply: 1 }, b: other } });
    const r = actions(qc);
    let both!: Promise<unknown>;
    act(() => { both = Promise.all([r.current.refreshOne("a"), r.current.refreshOne("a")]); });
    await answer(BUST("a"), { counts: { a: { unread: 1, owe_reply: 2 }, b: { unread: 0, owe_reply: 0 } } });
    await act(async () => { await both; });
    expect(calls(BUST("a"))).toBe(1);
    expect(qc.getQueryData<RosterCountsResp>(KEY)?.counts).toEqual({ a: { unread: 1, owe_reply: 2 }, b: other });
  });

  it("no client cooldown: a refreshOne right after one landed busts again (the Relay's Hover cooldown is the budget)", async () => {
    const qc = qcOf();
    const r = actions(qc);
    for (const unread of [1, 2]) {
      let p!: Promise<void>;
      act(() => { p = r.current.refreshOne("a"); });
      await answer(BUST("a"), { counts: { a: { unread, owe_reply: 0 } } });
      await act(async () => { await p; });
    }
    expect(calls(BUST("a"))).toBe(2);
    expect(qc.getQueryData<RosterCountsResp>(KEY)?.counts.a).toEqual({ unread: 2, owe_reply: 0 });
  });

  it("a failed bust resolves and leaves the cache untouched", async () => {
    const qc = qcOf();
    const held: RosterCountsResp = { counts: { a: { unread: 4, owe_reply: 1 } } };
    qc.setQueryData(KEY, held);
    const r = actions(qc);
    let p!: Promise<void>;
    act(() => { p = r.current.refreshOne("a"); });
    await answer(BUST("a"), new Error("relay 502"));
    await act(async () => { await expect(p).resolves.toBeUndefined(); });
    expect(qc.getQueryData(KEY)).toBe(held);
  });

  it("a full read started before a bust and answering after it does not overwrite the bust's entry", async () => {
    const qc = qcOf();
    renderHook(() => useRosterCountsRead(), { wrapper: wrap(qc) });
    await waitFor(() => expect(calls(FULL)).toBe(1));
    const r = actions(qc);
    let p!: Promise<void>;
    act(() => { p = r.current.refreshOne("a"); });
    await answer(BUST("a"), { counts: { a: { unread: 3, owe_reply: 0 } } });
    await act(async () => { await p; });
    await answer(FULL, { counts: { a: { unread: 0, owe_reply: 0 }, b: { unread: 1, owe_reply: 0 } } });
    await act(async () => { await new Promise((res) => setTimeout(res, 10)); });
    expect(qc.getQueryData<RosterCountsResp>(KEY)?.counts.a).toEqual({ unread: 3, owe_reply: 0 });
  });
});

describe("useRosterCountsRead polls only while some Creator's accounts row has no unread_total slot", () => {
  const on = { n: 2, at: 1, v: 3, grey: null };
  const slot = (unread_total: unknown) => ({ freshness: { values: { unread_total } } });
  function mount(answer?: { readonly owner: readonly object[] } | { readonly chatter: readonly object[] }) {
    const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });
    principal.chatter = !!answer && "chatter" in answer;
    if (answer && "owner" in answer) {
      qc.setQueryData(ownerAccountsQuery("u1").queryKey, { accounts: answer.owner, active_account_id: null });
    } else if (answer) qc.setQueryData(chatterAccountsQuery.queryKey, answer.chatter);
    const get = vi.spyOn(relay, "get").mockResolvedValue({ counts: {} });
    renderHook(() => useRosterCountsRead(), {
      wrapper: ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children),
    });
    return () => get.mock.calls.filter(([path]) => path === "/admin/accounts/roster-counts").length;
  }
  beforeEach(() => { vi.useFakeTimers(); resetRosterCountsModuleState(); principal.chatter = false; });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it.each([
    ["stream up", true],
    ["stream down", false],
  ])("every row has the slot (a non-OF Creator's null included): the mount read only over 10 min, %s", async (_n, up) => {
    vi.spyOn(eventBus, "isConnected").mockReturnValue(up);
    const reads = mount({ owner: [{ id: "a1", ...slot(on) }, { id: "a2", ...slot(null) }] });
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(reads()).toBe(1);
  });

  it.each([
    ["owner: Shared refresher on, Unread total off", { owner: [{ id: "a1", ...slot(on) }, { id: "a2", freshness: { values: {} } }] }, true, 3],
    ["owner: Shared refresher off (no freshness)", { owner: [{ id: "a1", ...slot(on) }, { id: "a2" }] }, true, 3],
    ["owner: Shared refresher off, stream down", { owner: [{ id: "a1", ...slot(on) }, { id: "a2" }] }, false, 11],
    ["chatter: a Creator row without the slot", { chatter: [{ account_id: "a1", ...slot(on) }, { account_id: "a2" }] }, true, 3],
    ["no accounts answer cached yet", undefined, true, 3],
  ] as const)("%s: today's 5-min poll, 60 s while the stream is down", async (_n, answer, up, want) => {
    vi.spyOn(eventBus, "isConnected").mockReturnValue(up);
    const reads = mount(answer);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(reads()).toBe(want);
  });

  it.each([
    ["owner: dead-session and deactivated Creators carry the slot too",
      { owner: [{ id: "a1", ...slot(on) }, { id: "a2", session_dead_at: 1, is_active: false, ...slot(on) }] }],
    ["chatter: a watcher row (no freshness) is not a Creator",
      { chatter: [{ account_id: "a1", ...slot(on) }, { account_id: "w1", role: "watcher" }] }],
  ] as const)("%s: no poll", async (_n, answer) => {
    vi.spyOn(eventBus, "isConnected").mockReturnValue(true);
    const reads = mount(answer);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(reads()).toBe(1);
  });
});
