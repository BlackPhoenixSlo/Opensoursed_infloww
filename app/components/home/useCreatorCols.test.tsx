import type { ReactNode } from "react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const scope = vi.hoisted(() => ({ accountId: "a1" as string | null, principal: "owner-1" }));
const applied = vi.hoisted(() => ({
  stored: {} as Record<string, string[]>,
  failed: false,
  retry: vi.fn(),
  unread: null as string | null,
  last: "a1",
}));
const relayMock = vi.hoisted(() => ({ calls: [] as { cols: string[]; done: () => void; fail: (e: unknown) => void }[] }));

vi.mock("@/lib/appliedSettings", () => ({
  APPLIED_SETTINGS_KEY: ["applied-settings"],
  useAppliedSettings: () => {
    const placeholder = scope.accountId === applied.unread;
    if (!placeholder) applied.last = scope.accountId ?? "";
    return { data: { reports: { creator_cols: applied.stored[applied.last] } }, isPlaceholderData: placeholder };
  },
  useAppliedSettingsAfterMount: () => {
    const key = `owner-1|${scope.accountId}`;
    if (scope.accountId === applied.unread) return { settings: undefined, failed: false, retry: applied.retry, key };
    return applied.failed
      ? { settings: undefined, failed: true, retry: applied.retry, key }
      : { settings: { reports: { creator_cols: applied.stored[scope.accountId ?? ""] } }, failed: false, retry: applied.retry, key };
  },
}));
vi.mock("@/hooks/useEmployeeKey", () => ({ usePrincipalId: () => scope.principal }));
vi.mock("@/lib/relay", () => ({
  RelayError: class RelayError extends Error {
    status: number;
    constructor(status: number) {
      super(`relay ${status}`);
      this.status = status;
    }
  },
  request: (_path: string, init: { body: string }) =>
    new Promise<void>((resolve, reject) => {
      relayMock.calls.push({ cols: JSON.parse(init.body).creator_cols, done: resolve, fail: reject });
    }),
}));

import { clearIdentityMemory } from "@/contexts/UserContext";
import { shownKeys } from "./creatorCols";
import { CustomMetricsPill } from "./ReportsControls";
import { useCreatorCols } from "./useCreatorCols";

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const tick = () => act(async () => void (await vi.advanceTimersByTimeAsync(700)));
let server: string[] | null = null;
const land = async (i: number) => {
  server = relayMock.calls[i].cols;
  await act(async () => relayMock.calls[i].done());
};

beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient();
  scope.accountId = "a1";
  scope.principal = "owner-1";
  applied.stored = { a1: ["revenue", "subs"], a2: ["tips"] };
  applied.failed = false;
  applied.unread = null;
  applied.last = "a1";
  applied.retry.mockReset();
  relayMock.calls = [];
  server = null;
});
afterEach(async () => {
  cleanup();
  for (let i = 0; i < relayMock.calls.length; i++) await act(async () => relayMock.calls[i].done());
  vi.useRealTimers();
});

describe("useCreatorCols", () => {
  it("a change made in one scope does not show in another Creator's scope", async () => {
    const { result, rerender } = renderHook(() => useCreatorCols(), { wrapper });
    act(() => result.current[1]!(["fans"]));
    expect(result.current[0]).toEqual(["fans"]);
    scope.accountId = "a2";
    rerender();
    expect(result.current[0]).toEqual(shownKeys(["tips"]));
  });

  it("leaving the page mid-save: the latest layout lands last, even when the older PUT is slower", async () => {
    const { result, unmount } = renderHook(() => useCreatorCols(), { wrapper });
    act(() => result.current[1]!(["a"]));
    await tick();
    expect(relayMock.calls.map((c) => c.cols)).toEqual([["a"]]);
    act(() => result.current[1]!(["b"]));
    unmount();
    await land(0);
    for (let i = 1; i < relayMock.calls.length; i++) await land(i);
    expect(server).toEqual(["b"]);
    expect(relayMock.calls.map((c) => c.cols)).toEqual([["a"], ["b"]]);
  });

  it("navigating away and back: the left page's queued layout never lands after the new page's newer save", async () => {
    const first = renderHook(() => useCreatorCols(), { wrapper });
    act(() => first.result.current[1]!(["a"]));
    await tick();
    act(() => first.result.current[1]!(["b"]));
    first.unmount();
    const second = renderHook(() => useCreatorCols(), { wrapper });
    act(() => second.result.current[1]!(["c"]));
    await tick();
    for (let i = 0; i < relayMock.calls.length; i++) await land(i);
    expect(server).toEqual(["c"]);
    expect(relayMock.calls.filter((c) => c.cols[0] !== "b").map((c) => c.cols)).toEqual([["a"], ["c"]]);
  });

  it("a layout queued by one principal never goes out under the next principal's session", async () => {
    const { result, rerender } = renderHook(() => useCreatorCols(), { wrapper });
    act(() => result.current[1]!(["a"]));
    await tick();
    act(() => result.current[1]!(["b"]));
    scope.principal = "owner-2";
    rerender();
    await land(0);
    expect(relayMock.calls.map((c) => c.cols)).toEqual([["a"]]);
  });

  it("an identity switch (clearIdentityMemory) drops the queued layout", async () => {
    const { result } = renderHook(() => useCreatorCols(), { wrapper });
    act(() => result.current[1]!(["a"]));
    await tick();
    act(() => result.current[1]!(["b"]));
    clearIdentityMemory();
    await land(0);
    expect(relayMock.calls.map((c) => c.cols)).toEqual([["a"]]);
  });

  it("pagehide with a save in flight sends the queued layout at once, and never replays it", async () => {
    const { result } = renderHook(() => useCreatorCols(), { wrapper });
    act(() => result.current[1]!(["a"]));
    await tick();
    act(() => result.current[1]!(["b"]));
    act(() => void window.dispatchEvent(new Event("pagehide")));
    expect(relayMock.calls.map((c) => c.cols)).toEqual([["a"], ["b"]]);
    await land(0);
    await land(1);
    expect(relayMock.calls.map((c) => c.cols)).toEqual([["a"], ["b"]]);
  });

  it("a Creator whose layout read has not answered shows the defaults, not the previous Creator's placeholder", () => {
    const { result, rerender } = renderHook(() => useCreatorCols(), { wrapper });
    expect(result.current[0]).toEqual(shownKeys(["revenue", "subs"]));
    applied.unread = "a3";
    scope.accountId = "a3";
    rerender();
    expect(result.current[0]).toEqual(shownKeys(undefined));
    expect(result.current[1]).toBeNull();
  });

  it("a failed layout read: no picker, but a retry that asks again", () => {
    applied.failed = true;
    const { result } = renderHook(() => useCreatorCols(), { wrapper });
    expect(result.current[1]).toBeNull();
    expect(result.current[2]).not.toBeNull();
    result.current[2]!();
    expect(applied.retry).toHaveBeenCalledTimes(1);
  });
});

describe("CustomMetricsPill on a failed layout read", () => {
  it("says so and asks again on click; while loading it stays off", () => {
    const retry = vi.fn();
    const { rerender } = render(<CustomMetricsPill keys={[]} onChange={null} onRetry={retry} />);
    const btn = screen.getByRole("button", { name: /Custom metrics/ });
    expect(btn).not.toBeDisabled();
    expect(btn.getAttribute("title")).toMatch(/Couldn't load/);
    fireEvent.click(btn);
    expect(retry).toHaveBeenCalledTimes(1);
    rerender(<CustomMetricsPill keys={[]} onChange={null} />);
    expect(screen.getByRole("button", { name: /Custom metrics/ })).toBeDisabled();
  });
});
