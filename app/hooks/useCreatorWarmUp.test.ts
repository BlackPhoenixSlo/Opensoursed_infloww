import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { refreshOne, refreshChatHead, accounts } = vi.hoisted(() => ({
  refreshOne: vi.fn<(id: string, opts?: unknown) => Promise<void>>(),
  refreshChatHead: vi.fn(async () => {}),
  accounts: [{ id: "acct-a" }, { id: "acct-b" }, { id: "acct-c" }],
}));
vi.mock("@/hooks/useChatList", () => ({ prefetchModelChatList: vi.fn(), refreshChatHead }));
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCountActions: () => ({ refreshOne }) }));
vi.mock("@/hooks/useAccounts", () => ({ usePlatformAccounts: () => accounts }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ setScope: vi.fn() }) }));

import { useCreatorWarmUp } from "./useCreatorWarmUp";
import { usePickAllModels } from "./usePickAllModels";

function held() {
  const lands: Array<() => void> = [];
  refreshChatHead.mockClear();
  refreshOne.mockReset();
  refreshOne.mockImplementation(() => new Promise<void>((r) => lands.push(r)));
  return lands;
}

function withClient<T>(hook: () => T) {
  const qc = new QueryClient();
  const invalidated = vi.spyOn(qc, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
  return { ...renderHook(hook, { wrapper }), invalidated };
}

describe("hover and All Models rewarm through the shared Hover cooldown", () => {
  it("hover: one plain ?bust= for the Creator, then one head refresh of its inbox, no list re-walk", async () => {
    const lands = held();
    const { result, invalidated } = withClient(() => useCreatorWarmUp());
    act(() => result.current.warm("acct-a"));
    expect(refreshOne.mock.calls).toEqual([["acct-a"]]);
    await act(async () => {});
    expect(refreshChatHead).not.toHaveBeenCalled();
    await act(async () => lands.forEach((land) => land()));
    expect(refreshChatHead.mock.calls.map((c) => (c as unknown[]).slice(1))).toEqual([[{ kind: "model", accountId: "acct-a" }, [accounts[0]]]]);
    expect(invalidated).not.toHaveBeenCalled();
  });

  it("hover on a Creator missing from the roster: the bust still runs, no head refresh", async () => {
    const lands = held();
    const { result } = withClient(() => useCreatorWarmUp());
    act(() => result.current.warm("acct-z"));
    await act(async () => lands.forEach((land) => land()));
    expect(refreshOne.mock.calls).toEqual([["acct-z"]]);
    expect(refreshChatHead).not.toHaveBeenCalled();
  });

  it("hover then pick before the bust lands: one bust and one head refresh", async () => {
    const lands = held();
    const { result } = withClient(() => useCreatorWarmUp());
    act(() => result.current.warm("acct-a"));
    act(() => result.current.warm("acct-a"));
    await act(async () => lands.forEach((land) => land()));
    await act(async () => {});
    expect(refreshOne.mock.calls).toEqual([["acct-a"]]);
    expect(refreshChatHead).toHaveBeenCalledTimes(1);
    act(() => result.current.warm("acct-a"));
    await act(async () => lands.forEach((land) => land()));
    expect(refreshChatHead).toHaveBeenCalledTimes(2);
  });

  it("All Models: one plain ?bust= per Creator, then one head refresh of the All Models inbox", async () => {
    const lands = held();
    const { result, invalidated } = withClient(() => usePickAllModels());
    act(() => result.current.pickAll());
    await vi.waitFor(() => expect(lands).toHaveLength(2));
    lands.splice(0).forEach((land) => land());
    await vi.waitFor(() => expect(lands).toHaveLength(1));
    await act(async () => {});
    expect(refreshChatHead).not.toHaveBeenCalled();
    await act(async () => lands.forEach((land) => land()));
    await vi.waitFor(() => expect(refreshChatHead).toHaveBeenCalled());
    expect(refreshOne.mock.calls).toEqual([["acct-a"], ["acct-b"], ["acct-c"]]);
    expect(refreshChatHead.mock.calls.map((c) => (c as unknown[]).slice(1))).toEqual([[{ kind: "all" }, accounts]]);
    expect(invalidated).not.toHaveBeenCalled();
  });
});
