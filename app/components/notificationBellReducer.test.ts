import { describe, expect, it } from "vitest";

import {
  BADGE_MAX, initialBellState, notificationBellReducer, ofListOnScreen,
  type BellAction, type BellState,
} from "./notificationBellReducer";

const run = (actions: BellAction[], from: BellState = initialBellState): BellState =>
  actions.reduce(notificationBellReducer, from);
const arrive = (n: number): BellAction[] => Array.from({ length: n }, () => ({ type: "arrived" }) as const);
const OPEN_TOPBAR: BellAction = { type: "open", agencyUnread: 0 };

describe("notificationBellReducer", () => {
  it.each<[string, BellAction[], number]>([
    ["arrivals while closed count", arrive(3), 3],
    ["opening the bell resets the badge", [...arrive(3), OPEN_TOPBAR], 0],
    ["arrivals while the OnlyFans list is open don't re-badge after close", [
      ...arrive(2), OPEN_TOPBAR, ...arrive(4), { type: "close" }], 0],
    ["arrivals after the close count again", [OPEN_TOPBAR, { type: "close" }, ...arrive(2)], 2],
    ["the cleared event zeroes it", [...arrive(5), { type: "cleared" }], 0],
    ["capped at BADGE_MAX", arrive(BADGE_MAX + 5), BADGE_MAX],
    ["arrivals while open on the Agency tab count", [
      { type: "open", agencyUnread: 2 }, ...arrive(1), { type: "close" }], 1],
    ["…until the OnlyFans tab is shown", [
      { type: "open", agencyUnread: 2 }, ...arrive(1), { type: "pane", pane: "of" }, { type: "close" }], 0],
    ["switching to Agency while closed doesn't clear", [...arrive(2), { type: "pane", pane: "agency" }], 2],
    ["switching to OnlyFans while closed doesn't clear", [...arrive(2), { type: "pane", pane: "of" }], 2],
  ])("%s", (_n, actions, arrivals) => {
    expect(run(actions).arrivals).toBe(arrivals);
  });

  it.each<[string, BellAction[], number, "of" | "agency"]>([
    ["only agency has news → Agency", [], 2, "agency"],
    ["OnlyFans arrivals too → OnlyFans", arrive(1), 2, "of"],
    ["nothing new anywhere, or no Agency tab (0) → OnlyFans", [], 0, "of"],
  ])("open lands on — %s", (_n, before, agencyUnread, pane) => {
    const s = run([...before, { type: "open", agencyUnread }]);
    expect(s.open).toBe(true);
    expect(s.pane).toBe(pane);
  });

  it("ofListOnScreen only while open on the OnlyFans tab", () => {
    expect(ofListOnScreen(initialBellState)).toBe(false);
    expect(ofListOnScreen(run([OPEN_TOPBAR]))).toBe(true);
    expect(ofListOnScreen(run([{ type: "open", agencyUnread: 3 }]))).toBe(false);
  });

  it("back to the OnlyFans tab while open (the Agency tab going away too) puts its list on screen: its arrivals are seen", () => {
    const s = run([{ type: "open", agencyUnread: 2 }, ...arrive(2), { type: "pane", pane: "of" }]);
    expect(ofListOnScreen(s)).toBe(true);
    expect(s.arrivals).toBe(0);
  });

  it.each<[string, BellAction[], boolean]>([
    ["the last row opened hit the cap", [OPEN_TOPBAR, { type: "tabsFull", full: true }], true],
    ["the next one did not", [OPEN_TOPBAR, { type: "tabsFull", full: true }, { type: "tabsFull", full: false }], false],
    ["closing keeps it", [OPEN_TOPBAR, { type: "tabsFull", full: true }, { type: "close" }], true],
    ["re-opening starts without it", [
      OPEN_TOPBAR, { type: "tabsFull", full: true }, { type: "close" }, OPEN_TOPBAR], false],
  ])("Fan tabs full note: %s", (_n, actions, want) => {
    expect(run(actions).tabsFull).toBe(want);
  });

  it("open while open and close while closed are no-ops", () => {
    const opened = run([OPEN_TOPBAR]);
    expect(notificationBellReducer(opened, OPEN_TOPBAR)).toBe(opened);
    expect(notificationBellReducer(initialBellState, { type: "close" })).toBe(initialBellState);
  });
});
