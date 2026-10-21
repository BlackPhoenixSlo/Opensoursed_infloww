import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";

type Handler = (e: Record<string, unknown>, type: string) => void;
const handlers = new Map<string, Set<Handler>>();
vi.mock("@/lib/events", () => ({
  eventBus: {
    on(type: string, fn: Handler) {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type)!.add(fn);
      return () => handlers.get(type)!.delete(fn);
    },
  },
}));
const session = vi.hoisted(() => ({ user: null as object | null, chatter: { chatter_id: "c1" } as object | null }));
vi.mock("@/contexts/UserContext", () => ({ useOptionalUser: () => ({ user: session.user }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useOptionalChatter: () => ({ chatter: session.chatter }) }));

import { makeTestQueryClient } from "@/test-utils";
import { onNotice } from "@/lib/notices";
import { SETTLE_MS, useAccessChangeNotices } from "./useAccessChangeNotices";

const ACCOUNTS = ["chatter", "self", "accounts"];
const row = (id: string, nickname: string) => ({ account_id: id, nickname, color: null, owner_id: "o1" });
const applied = (pages: string[] | null) => ({
  preferences: { tz: null, report_tz: null, week_start: "monday" },
  messaging: { ai_translation: true },
  permissions: { enforced: true, pages, scope: "self" },
});

function emit(type: string) {
  act(() => { for (const fn of handlers.get(type) ?? []) fn({}, type); });
}

/** The refetch the event triggers: a real fetch answering `data`, or failing. */
async function refetch(qc: QueryClient, queryKey: unknown[], data: unknown) {
  await act(async () => {
    await qc.fetchQuery({
      queryKey,
      queryFn: async () => {
        if (data instanceof Error) throw data;
        return data;
      },
      retry: false,
      staleTime: 0,
    }).catch(() => {});
  });
}

let texts: string[];
let off: () => void;

function mount() {
  const qc = makeTestQueryClient();
  renderHook(() => useAccessChangeNotices(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
  return qc;
}

describe("useAccessChangeNotices", () => {
  beforeEach(() => {
    handlers.clear();
    session.user = null;
    session.chatter = { chatter_id: "c1" };
    texts = [];
    off = onNotice((n) => texts.push(n.text));
  });
  afterEach(() => { off(); vi.useRealTimers(); });

  it("names each Creator the refetch after assignment_changed no longer lists", async () => {
    const qc = mount();
    qc.setQueryData(ACCOUNTS, [row("a1", "Jade"), row("a2", ""), row("a3", "Kept")]);
    emit("assignment_changed");
    await refetch(qc, ACCOUNTS, [row("a3", "Kept"), row("a4", "New")]);
    expect(texts).toEqual(["You've been unassigned from Jade.", "You've been unassigned from a2."]);
    // Only the refetch the event triggered is compared.
    await refetch(qc, ACCOUNTS, []);
    expect(texts).toHaveLength(2);
  });

  it("a failed refetch (5xx) is no answer: no toast, and the next real one still counts", async () => {
    const qc = mount();
    qc.setQueryData(ACCOUNTS, [row("a1", "Jade")]);
    emit("assignment_changed");
    await refetch(qc, ACCOUNTS, new Error("/chatter/me/accounts 502"));
    expect(texts).toEqual([]);
    await refetch(qc, ACCOUNTS, []);
    expect(texts).toEqual(["You've been unassigned from Jade."]);
  });

  it("a setQueryData (logout writing []) is not the refetch", async () => {
    const qc = mount();
    qc.setQueryData(ACCOUNTS, [row("a1", "Jade")]);
    emit("assignment_changed");
    act(() => { qc.setQueryData(ACCOUNTS, []); });
    expect(texts).toEqual([]);
  });

  it("says nothing when another chatter's assignment changed", async () => {
    const qc = mount();
    qc.setQueryData(ACCOUNTS, [row("a1", "Jade")]);
    emit("assignment_changed");
    await refetch(qc, ACCOUNTS, [row("a1", "Jade")]);
    expect(texts).toEqual([]);
  });

  it("tells only the session whose own applied permissions changed", async () => {
    const qc = mount();
    qc.setQueryData(["applied-settings", "a1"], applied(["inbox"]));
    emit("permissions_changed");
    await refetch(qc, ["applied-settings", "a1"], applied(["inbox"]));
    expect(texts).toEqual([]);

    emit("permissions_changed");
    await refetch(qc, ["applied-settings", "a1"], applied(["inbox", "vault"]));
    expect(texts).toEqual(["Your permissions were updated."]);
  });

  it("stops waiting once the refetch is overdue", async () => {
    vi.useFakeTimers();
    const qc = mount();
    qc.setQueryData(ACCOUNTS, [row("a1", "Jade")]);
    emit("assignment_changed");
    act(() => { vi.advanceTimersByTime(SETTLE_MS); });
    vi.useRealTimers();
    await refetch(qc, ACCOUNTS, []);
    expect(texts).toEqual([]);
  });

  it("never tells an owner session", async () => {
    session.user = { user_id: "o1" };
    const qc = mount();
    qc.setQueryData(ACCOUNTS, [row("a1", "Jade")]);
    emit("assignment_changed");
    await refetch(qc, ACCOUNTS, []);
    expect(texts).toEqual([]);
    expect(handlers.get("assignment_changed")?.size ?? 0).toBe(0);
  });
});
