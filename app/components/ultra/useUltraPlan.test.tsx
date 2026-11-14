/**
 * useUltraPlan's ordering: a read that started before a press never lands after the press's answer (no OK back on
 * screen), poll reads never overlap, a second press before the first answers posts nothing, a refused read (401/403)
 * stops the poll, and every action is tagged with the plan it is for.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useCallback, useReducer } from "react";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}));

import { RelayError } from "@/lib/relay";
import { ACT_TIMEOUT_MS, READ_TIMEOUT_MS, useUltraPlan } from "./useUltraPlan";
import { INITIAL_RUN, planActions, ultraRunReducer, type Action, type PlanStatus, type PlanView } from "./ultraRunReducer";

const view = (status: PlanStatus): PlanView => ({
  id: "p1", status, summary: "s", sha256: "a".repeat(64), card: [], step_states: [],
  created_at: "2026-11-14T12:00:00Z", expires_at: "2099-01-01T00:00:00Z", approved_at: null, finished_at: null,
});
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
const flush = () => act(async () => {});

let tags: string[];
function useHarness(planId: string) {
  const [state, dispatch] = useReducer(ultraRunReducer, INITIAL_RUN);
  const tagged = useCallback((a: Action, id: string) => { tags.push(id); dispatch(a); }, []);
  const io = useUltraPlan(planId, state, tagged);
  return { state, ...io };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  get.mockReset();
  post.mockReset();
  tags = [];
});
afterEach(() => {
  vi.restoreAllMocks();   // AbortSignal.timeout spies, even when a test fails early
  vi.useRealTimers();
});

describe("useUltraPlan ordering", () => {
  it("a poll read sent before OK that lands after OK's answer is dropped (no OK back, poll stays fast)", async () => {
    get.mockResolvedValueOnce(view("awaiting_ok"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    expect(result.current.state.plan?.status).toBe("awaiting_ok");

    const stale = deferred<PlanView>();
    get.mockReturnValueOnce(stale.promise);           // the 15 s poll, still out when OK is pressed
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(get).toHaveBeenCalledTimes(2);

    post.mockResolvedValueOnce(view("running"));
    get.mockResolvedValueOnce(view("running"));        // the read right after the OK
    await act(async () => { await result.current.act("ok"); });
    expect(result.current.state.plan?.status).toBe("running");

    await act(async () => { stale.resolve(view("awaiting_ok")); });
    expect(result.current.state.plan?.status).toBe("running");
    expect(planActions(result.current.state).map((b) => b.kind)).toEqual(["cancel"]);
    expect(tags.every((t) => t === "p1")).toBe(true);
  });

  it("a hung OK POST never blocks the poll: reads go on while it is out", async () => {
    get.mockResolvedValueOnce(view("awaiting_ok"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    post.mockReturnValueOnce(new Promise(() => {}));   // never answers (its timeout is covered below)
    act(() => { void result.current.act("ok"); });
    get.mockResolvedValue(view("running"));
    for (let i = 0; i < 3; i++) {
      act(() => { vi.advanceTimersByTime(15_000); });
      await flush();
    }
    expect(get.mock.calls.length).toBeGreaterThanOrEqual(3);
    // The run moved on server-side: the read shows it; busy keeps the OK disabled meanwhile.
    expect(result.current.state.plan?.status).toBe("running");
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("a read started while the OK is out that lands after the OK's answer is dropped", async () => {
    get.mockResolvedValueOnce(view("awaiting_ok"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    const answer = deferred<PlanView>();
    post.mockReturnValueOnce(answer.promise);
    act(() => { void result.current.act("ok"); });
    const during = deferred<PlanView>();
    get.mockReturnValueOnce(during.promise);
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(get).toHaveBeenCalledTimes(2);               // the poll reads while the OK is out
    get.mockResolvedValueOnce(view("running"));         // the read right after the OK's answer
    await act(async () => { answer.resolve(view("running")); });
    expect(get).toHaveBeenCalledTimes(3);
    await act(async () => { during.resolve(view("awaiting_ok")); });
    expect(result.current.state.plan?.status).toBe("running");
    expect(planActions(result.current.state).map((b) => b.kind)).toEqual(["cancel"]);
  });

  it("an OK POST with no answer in 30 s fails (never re-posted) and the plan is read", async () => {
    get.mockResolvedValueOnce(view("awaiting_ok"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    const timers = new Map<number, AbortController>();
    vi.spyOn(AbortSignal, "timeout").mockImplementation((ms) => {
      const c = new AbortController();
      timers.set(ms, c);
      return c.signal;
    });
    post.mockImplementationOnce((_p: string, _b: unknown, _ctx: unknown, signal?: AbortSignal) => new Promise((_res, rej) => {
      signal?.addEventListener("abort", () => rej(new DOMException("signal timed out", "TimeoutError")));
    }));
    let pressed!: Promise<void>;
    act(() => { pressed = result.current.act("ok"); });
    get.mockResolvedValue(view("running"));
    const before = get.mock.calls.length;
    await act(async () => { timers.get(ACT_TIMEOUT_MS)?.abort(); });
    await act(async () => { await Promise.race([pressed, new Promise((r) => setTimeout(r, 50))]); });
    expect([result.current.state.busy, result.current.state.actionError]).toEqual([null, "no answer in 30 s; check the steps above before pressing again"]);
    expect(post).toHaveBeenCalledTimes(1);
    expect(get.mock.calls.length).toBe(before + 1);
    expect(result.current.state.plan?.status).toBe("running");
  });

  it("poll reads never overlap: a tick while a read is out sends nothing", async () => {
    get.mockResolvedValueOnce(view("running"));
    renderHook(() => useHarness("p1"));
    await flush();
    const slow = deferred<PlanView>();
    get.mockReturnValueOnce(slow.promise);
    act(() => { vi.advanceTimersByTime(2_000); });
    act(() => { vi.advanceTimersByTime(2_000); });
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(get).toHaveBeenCalledTimes(2);
    get.mockResolvedValue(view("running"));
    await act(async () => { slow.resolve(view("running")); });
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(get).toHaveBeenCalledTimes(3);
  });

  it("a second press before the first answers posts nothing", async () => {
    get.mockResolvedValue(view("awaiting_ok"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    const answer = deferred<PlanView>();
    post.mockReturnValueOnce(answer.promise);
    const ok = result.current.act;                      // the same render's handler, pressed twice
    let first!: Promise<void>;
    act(() => { first = ok("ok"); void ok("ok"); });
    expect(post).toHaveBeenCalledTimes(1);
    get.mockResolvedValue(view("running"));
    await act(async () => { answer.resolve(view("running")); await first; });
    expect(result.current.state.busy).toBeNull();
  });

  it("a hung read times out as a failed read; the poll goes on", async () => {
    get.mockResolvedValueOnce(view("running"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    const timeouts: AbortController[] = [];
    const spy = vi.spyOn(AbortSignal, "timeout").mockImplementation((ms) => {
      expect(ms).toBe(READ_TIMEOUT_MS);
      const c = new AbortController();
      timeouts.push(c);
      return c.signal;
    });
    // A GET that never answers until its signal fires.
    get.mockImplementationOnce((_p: string, _ctx: unknown, signal: AbortSignal) => new Promise((_res, rej) => {
      signal.addEventListener("abort", () => rej(new DOMException("signal timed out", "TimeoutError")));
    }));
    act(() => { vi.advanceTimersByTime(2_000); });
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(get).toHaveBeenCalledTimes(2);              // hung: the tick is skipped
    await act(async () => { timeouts[0].abort(); });
    expect([result.current.state.loadError, result.current.state.pollStopped]).toEqual(["no answer in 20 s", false]);
    get.mockResolvedValue(view("running"));
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(get).toHaveBeenCalledTimes(3);
    spy.mockRestore();
  });

  it("a refused re-poll (401) stops polling; Try again resumes it", async () => {
    get.mockResolvedValueOnce(view("running"));
    const { result } = renderHook(() => useHarness("p1"));
    await flush();
    get.mockRejectedValueOnce(new RelayError(401, {}, "sign in again"));
    act(() => { vi.advanceTimersByTime(2_000); });
    await flush();
    expect([result.current.state.loadError, result.current.state.pollStopped]).toEqual(["sign in again", true]);
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(get).toHaveBeenCalledTimes(2);

    get.mockResolvedValue(view("running"));
    await act(async () => { await result.current.read(); });
    expect(result.current.state.pollStopped).toBe(false);
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(get).toHaveBeenCalledTimes(4);
  });
});
