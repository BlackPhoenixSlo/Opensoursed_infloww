import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  etaFor,
  hoverPreviewReducer,
  IDLE_HOVER,
  posterCountdownSec,
  POSTER_ETA_SEC,
  scrubCountdownSec,
  SCRUB_FRAMES,
  useHoverPreview,
  type HoverPreviewAction,
  type HoverPreviewState,
} from "@/hooks/useHoverPreview";

const T0 = 1_000_000;
const enter = (id = 7, durationSec = 30, sid = "s1"): HoverPreviewAction =>
  ({ type: "enter", id, durationSec, url: "https://cdn/v.mp4", sid, now: T0 });
const hovering = (patch: Partial<HoverPreviewState> = {}): HoverPreviewState =>
  ({ ...hoverPreviewReducer(IDLE_HOVER, enter()), ...patch });

describe("etaFor", () => {
  // VaultPicker's ×1.3-padded formula; FanDrawer's copy had dropped the ×1.3.
  it.each([
    [0, 7], [Number.NaN, 7], [-5, 7], [1, 7], [15, 7], [30, 7], [34, 8],
    [60, 8], [61, 9], [120, 18], [600, 90],
  ])("a %ss video builds in about %ss", (dur, eta) => {
    expect(etaFor(dur)).toBe(eta);
  });
});

describe("countdowns", () => {
  it.each([
    ["idle", IDLE_HOVER, 0, 0],
    ["just committed", hovering(), 7, POSTER_ETA_SEC],
    ["1.5s in", hovering({ now: T0 + 1500 }), 5.5, 1],
    ["past both ETAs", hovering({ now: T0 + 60_000 }), 0, 0],
  ] as const)("%s", (_, s, scrub, poster) => {
    expect(scrubCountdownSec(s)).toBeCloseTo(scrub);
    expect(posterCountdownSec(s)).toBeCloseTo(poster);
  });
});

describe("hoverPreviewReducer", () => {
  const cases: [string, HoverPreviewState, HoverPreviewAction, Partial<HoverPreviewState> | "same"][] = [
    ["enter starts a fresh session at frame 0, loading", IDLE_HOVER, enter(9, 34, "sA"),
      { id: 9, sid: "sA", durationSec: 34, frame: 0, scrub: "loading", posterLoaded: false, posterGrace: false, startedAt: T0, now: T0 }],
    ["enter over another hover resets everything", hovering({ frame: 5, scrub: "ready", posterLoaded: true, posterGrace: true }),
      enter(8, 30, "s2"), { id: 8, sid: "s2", frame: 0, scrub: "loading", posterLoaded: false, posterGrace: false }],
    ["enter keeps a missing duration at 0 and an empty url as null", IDLE_HOVER,
      { type: "enter", id: 1, durationSec: Number.NaN, url: "", sid: "s", now: T0 }, { durationSec: 0, url: null }],
    ["leave ends the hover and resets the cursor", hovering({ frame: 5, scrub: "ready" }), { type: "leave" }, IDLE_HOVER],
    ["leave while idle is a no-op", IDLE_HOVER, { type: "leave" }, "same"],
    ["beat advances the cursor", hovering({ frame: 3 }), { type: "beat" }, { frame: 4 }],
    ["beat wraps after the last frame", hovering({ frame: SCRUB_FRAMES - 1 }), { type: "beat" }, { frame: 0 }],
    ["beat while idle is a no-op", IDLE_HOVER, { type: "beat" }, "same"],
    ["tick moves the clock while a countdown runs", hovering(), { type: "tick", now: T0 + 100 }, { now: T0 + 100 }],
    ["tick stops once nothing counts down", hovering({ scrub: "ready", posterLoaded: true }), { type: "tick", now: T0 + 100 }, "same"],
    ["tick runs the poster ETA after a failed build", hovering({ scrub: "failed" }), { type: "tick", now: T0 + 100 }, { now: T0 + 100 }],
    ["a warm storyboard stops the poster ETA", hovering({ scrub: "ready" }), { type: "tick", now: T0 + 100 }, "same"],
    ["no url (drm): poster ETA ticks", hovering({ url: null }), { type: "tick", now: T0 + 100 }, { now: T0 + 100 }],
    ["no url → no scrub tick once the poster ETA ran out", hovering({ url: null, now: T0 + 3000 }), { type: "tick", now: T0 + 3100 }, "same"],
    ["no url → no scrub tick once the poster painted", hovering({ url: null, posterLoaded: true }), { type: "tick", now: T0 + 100 }, "same"],
    ["tick stops once both countdowns hit 0", hovering({ now: T0 + 60_000 }), { type: "tick", now: T0 + 60_100 }, "same"],
    ["tick while idle is a no-op", IDLE_HOVER, { type: "tick", now: T0 }, "same"],
    ["frame 0 loads: ready on frame 0", hovering({ frame: 6 }), { type: "frameLoaded", sid: "s1", idx: 0 }, { scrub: "ready", frame: 0 }],
    ["any frame loads first: ready on that frame", hovering(), { type: "frameLoaded", sid: "s1", idx: 4 }, { scrub: "ready", frame: 4 }],
    ["a later load after ready keeps the cursor", hovering({ scrub: "ready", frame: 2 }), { type: "frameLoaded", sid: "s1", idx: 9 }, "same"],
    ["a load from an old session is dropped", hovering(), { type: "frameLoaded", sid: "old", idx: 0 }, "same"],
    ["a load while idle is dropped", IDLE_HOVER, { type: "frameLoaded", sid: "s1", idx: 0 }, "same"],
    ["frame 0 errors: failed", hovering(), { type: "frameError", sid: "s1", idx: 0 }, { scrub: "failed" }],
    ["another frame erroring keeps loading", hovering(), { type: "frameError", sid: "s1", idx: 3 }, "same"],
    ["frame 0 erroring after ready keeps ready", hovering({ scrub: "ready" }), { type: "frameError", sid: "s1", idx: 0 }, "same"],
    ["an error from an old session is dropped", hovering(), { type: "frameError", sid: "old", idx: 0 }, "same"],
    ["a frame landing after a frame-0 failure recovers", hovering({ scrub: "failed" }), { type: "frameLoaded", sid: "s1", idx: 5 }, { scrub: "ready", frame: 5 }],
    ["poster lands", hovering(), { type: "posterLoaded", sid: "s1" }, { posterLoaded: true }],
    ["poster from an old session is dropped", hovering(), { type: "posterLoaded", sid: "old" }, "same"],
    ["grace elapses", hovering(), { type: "graceElapsed", sid: "s1" }, { posterGrace: true }],
    ["grace from an old session is dropped", hovering(), { type: "graceElapsed", sid: "old" }, "same"],
  ];
  it.each(cases)("%s", (_, state, action, expected) => {
    const next = hoverPreviewReducer(state, action);
    if (expected === "same") expect(next).toBe(state);
    else expect(next).toMatchObject(expected);
  });
});

describe("useHoverPreview", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  const cancels = (f: ReturnType<typeof vi.fn>) =>
    f.mock.calls.map(([u]) => new URL(String(u), "http://x").searchParams.get("sid"));

  it("commits after the dwell, cancels the build on leave, and a brush-past never commits", () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null)));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useHoverPreview(400));

    act(() => result.current.start(1, 30, "https://cdn/a.mp4"));
    act(() => { vi.advanceTimersByTime(399); });
    act(() => result.current.stop());
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current.state.id).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();

    act(() => result.current.start(1, 30, "https://cdn/a.mp4"));
    act(() => { vi.advanceTimersByTime(400); });
    const sid = result.current.state.sid;
    expect(result.current.state.id).toBe(1);
    expect(sid).not.toBe("");
    act(() => { vi.advanceTimersByTime(1200); });
    expect(result.current.state.frame).toBe(2);
    expect(result.current.state.posterGrace).toBe(true);
    expect(scrubCountdownSec(result.current.state)).toBeCloseTo(7 - 1.2);

    act(() => result.current.stop());
    expect(cancels(fetchMock)).toEqual([sid]);
  });

  it("re-hovering another tile cancels the first build exactly once and drops its late frames", () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null)));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useHoverPreview(400));

    act(() => result.current.start(1, 30, "https://cdn/a.mp4"));
    act(() => { vi.advanceTimersByTime(400); });
    const sidA = result.current.state.sid;
    const lateA = result.current.frameProps(0);
    act(() => result.current.start(2, 30, "https://cdn/b.mp4"));
    act(() => { vi.advanceTimersByTime(400); });
    const sidB = result.current.state.sid;
    expect(sidB).not.toBe(sidA);
    expect(cancels(fetchMock)).toEqual([sidA]);

    act(() => lateA.onLoad());
    expect(result.current.state.scrub).toBe("loading");
    act(() => result.current.frameProps(3).onLoad());
    expect(result.current.state).toMatchObject({ id: 2, scrub: "ready", frame: 3 });

    act(() => result.current.stop());
    expect(cancels(fetchMock)).toEqual([sidA, sidB]);
  });

  it("unmounting during the dwell never commits or fetches", () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null)));
    vi.stubGlobal("fetch", fetchMock);
    const { result, unmount } = renderHook(() => useHoverPreview(400));
    act(() => result.current.start(1, 30, "https://cdn/a.mp4"));
    act(() => { vi.advanceTimersByTime(200); });
    unmount();
    // A dwell timer left armed would fire into the unmounted hook; its state and
    // fetches can't show that (both stay frozen), the pending timer does.
    expect(vi.getTimerCount()).toBe(0);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current.state.id).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("cancels the build when unmounted mid-hover", () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null)));
    vi.stubGlobal("fetch", fetchMock);
    const { result, unmount } = renderHook(() => useHoverPreview(400));
    act(() => result.current.start(1, 30, "https://cdn/a.mp4"));
    act(() => { vi.advanceTimersByTime(400); });
    const sid = result.current.state.sid;
    unmount();
    expect(cancels(fetchMock)).toEqual([sid]);
  });
});
