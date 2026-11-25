import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { BadgeAge, LiveMark } from "@/components/chat/dataAge";
import { unreadBadgeSources } from "@/components/chat/unreadBadge";
import { dispatchCreatorFreshness, useCreatorFreshnessState } from "@/hooks/useCreatorFreshness";
import { useLiveMark, useUnreadBadgeAge } from "@/hooks/useDataAge";
import { setRelayOffset, TICK_MS } from "@/lib/ageClock";
import type { Freshness } from "@/lib/creatorFreshness";
import { eventBus } from "@/lib/events";

const T = 1_800_000_000_000;
const S = 1_000;
const MIN = 60 * S;
const PRINCIPAL = "anon";

const fresh = (aid: string, ago: number, over: Partial<Freshness> = {}): Freshness => ({
  account_id: aid, boot: T - 60 * MIN, seq: 1, now: T, at: T - ago, cycle_s: 120, live: "up", live_since: T - 10 * MIN,
  values: { unread_total: { n: 2, at: T - ago } }, ...over,
});
const ids = (n: number) => Array.from({ length: n }, (_, i) => `c${i}`);
const account = (id: string) => ({ id, session_dead_at: null, has_session: true, is_active: true });
const NO_DEAD: ReadonlySet<string> = new Set();

let qc: QueryClient;
const seed = (rows: { id: string; freshness?: Freshness | null }[]) =>
  dispatchCreatorFreshness(qc, PRINCIPAL, { type: "seeded", rows, receivedAt: Date.now() });
const tick = (n = 1) => act(() => { vi.advanceTimersByTime(n * TICK_MS); });

function Chip({ aids, log }: { aids: string[]; log: (BadgeAge | null)[] }) {
  const age = useUnreadBadgeAge(unreadBadgeSources(useCreatorFreshnessState(), aids), NO_DEAD);
  log.push(age);
  return <span>{age ? `${age.text}|${age.title}` : "fresh"}</span>;
}
function Mark({ id, log }: { id: string; log: (LiveMark | null)[] }) {
  const m = useLiveMark(account(id));
  log.push(m);
  return null;
}
const mount = (ui: React.ReactNode) => render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);

let visibility: DocumentVisibilityState = "visible";
const setVisibility = (v: DocumentVisibilityState) => {
  visibility = v;
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T);
  qc = new QueryClient();
  setRelayOffset(0);
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const tickIntervals = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.filter((c) => c[1] === TICK_MS).length;

describe("useDataAge", () => {
  it("one timer: 50 hooks mounted → 1 interval", () => {
    const spy = vi.spyOn(globalThis, "setInterval");
    seed(ids(50).map((id) => ({ id, freshness: fresh(id, 30 * S) })));
    const log: (LiveMark | null)[] = [];
    mount(<>{ids(50).map((id) => <Mark key={id} id={id} log={log} />)}<Chip aids={ids(50)} log={[]} /></>);
    expect(tickIntervals(spy)).toBe(1);
  });

  it("re-renders only on change: 4 unchanged ticks → 0; one Creator turns late → only its badge", () => {
    seed(["a", "b"].map((id) => ({ id, freshness: fresh(id, id === "a" ? 100 * S : 30 * S) })));
    const a: (BadgeAge | null)[] = [];
    const b: (BadgeAge | null)[] = [];
    const marks: (LiveMark | null)[] = [];
    mount(<><Chip aids={["a"]} log={a} /><Chip aids={["b"]} log={b} /><Mark id="a" log={marks} /></>);
    const [ra, rb, rm] = [a.length, b.length, marks.length];
    tick(4);
    expect([a.length, b.length, marks.length]).toEqual([ra, rb, rm]);
    tick(1);
    expect(a.length).toBe(ra + 1);
    expect(a.at(-1)?.text).toBe("as of 2 min");
    expect([b.length, marks.length]).toEqual([rb, rm]);
  });

  it("a second Creator turning late under an unchanged \"as of 4 min\" re-renders the chip (\"2 of 10\")", () => {
    seed(ids(10).map((id, i) => ({ id, freshness: fresh(id, i === 0 ? 4 * MIN : i === 1 ? 150 * S : 30 * S) })));
    const log: (BadgeAge | null)[] = [];
    const { container } = mount(<Chip aids={ids(10)} log={log} />);
    expect(container.textContent).toBe("as of 4 min|As of 4 min ago: 1 of 10 Creators not refreshed within its Cycle");
    const before = log.length;
    tick(1);
    expect(log.length).toBe(before + 1);
    expect(container.textContent).toBe("as of 4 min|As of 4 min ago: 2 of 10 Creators not refreshed within its Cycle");
  });

  it("hidden tab: no interval while hidden; visibilitychange to visible → an immediate tick", () => {
    const spy = vi.spyOn(globalThis, "setInterval");
    visibility = "hidden";
    seed([{ id: "a", freshness: fresh("a", 30 * S) }]);
    const log: (BadgeAge | null)[] = [];
    const { container } = mount(<Chip aids={["a"]} log={log} />);
    expect(tickIntervals(spy)).toBe(0);
    act(() => { vi.advanceTimersByTime(5 * MIN); });
    expect(container.textContent).toBe("fresh");
    setVisibility("visible");
    expect(container.textContent).toBe("as of 5 min|As of 5 min ago: not refreshed within its 2 min Cycle");
    expect(tickIntervals(spy)).toBe(1);
    setVisibility("hidden");
    const n = log.length;
    act(() => { vi.advanceTimersByTime(10 * MIN); });
    expect(log.length).toBe(n);
  });

  it("idle return: paused then resumed with a late at → age at once; gone on the next confirmation", () => {
    vi.stubGlobal("EventSource", class { readyState = 1; addEventListener() {} close() { this.readyState = 2; } });
    seed([{ id: "a", freshness: fresh("a", 30 * S) }]);
    const { container } = mount(<Chip aids={["a"]} log={[]} />);
    eventBus.pause();
    act(() => { vi.advanceTimersByTime(6 * MIN); });
    act(() => { eventBus.resume(); });
    expect(container.textContent).toMatch(/^as of 6 min\|/);
    act(() => {
      dispatchCreatorFreshness(qc, PRINCIPAL, { type: "confirmed", fresh: { a: Date.now() }, now: Date.now(), receivedAt: Date.now() });
    });
    expect(container.textContent).toBe("fresh");
    eventBus.pause();
  });

  it("kill switch: a seed without freshness after one with it → no age, no amber dot", () => {
    seed([{ id: "a", freshness: fresh("a", 10 * MIN, { live: "down", live_since: T - 3 * MIN }) }]);
    const marks: (LiveMark | null)[] = [];
    const ages: (BadgeAge | null)[] = [];
    mount(<><Chip aids={["a"]} log={ages} /><Mark id="a" log={marks} /></>);
    expect(ages.at(-1)?.text).toBe("as of 10 min");
    expect(marks.at(-1)?.kind).toBe("down");
    act(() => { seed([{ id: "a" }]); });
    expect(marks.at(-1)).toBeNull();
    expect(ages.at(-1)).toBeNull();
  });

  it("makes no request: 50 Creators, 10 ticks, a ping and a visibility return → no fetch, no new query", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    seed(ids(50).map((id, i) => ({ id, freshness: fresh(id, i * 10 * S, { live: i % 2 ? "down" : "up" }) })));
    const queries = qc.getQueryCache().getAll().length;
    mount(<>{ids(50).map((id) => <Mark key={id} id={id} log={[]} />)}<Chip aids={ids(50)} log={[]} /></>);
    tick(10);
    act(() => {
      setRelayOffset(2 * S);
      dispatchCreatorFreshness(qc, PRINCIPAL, {
        type: "confirmed", fresh: Object.fromEntries(ids(50).map((id) => [id, Date.now()])), now: Date.now(),
        receivedAt: Date.now(),
      });
    });
    setVisibility("hidden");
    setVisibility("visible");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(qc.getQueryCache().getAll().length).toBe(queries);
  });
});
