import { describe, expect, it } from "vitest";

import { DRAWER_CLOSED, drawerOn, drawerReducer, type DrawerAction, type DrawerState } from "./drawerState";

const A = "/a", B = "/b";
const open = (path = A): DrawerState => ({ kind: "open", path });
const leaving = (path = A): DrawerState => ({ kind: "leaving", path });

describe("drawerReducer", () => {
  const rows: [string, DrawerState, DrawerAction, DrawerState][] = [
    ["open from closed", DRAWER_CLOSED, { type: "open", path: A }, open()],
    ["toggle from closed opens", DRAWER_CLOSED, { type: "toggle", path: A }, open()],
    ["toggle while open closes", open(), { type: "toggle", path: A }, DRAWER_CLOSED],
    ["close while open", open(), { type: "close" }, DRAWER_CLOSED],
    ["a swipe's release lets it go", open(), { type: "letGo" }, leaving()],
    ["its slide ends it", leaving(), { type: "slid" }, DRAWER_CLOSED],
    ["a reduced-motion swipe ends it at once (no let go)", open(), { type: "slid" }, DRAWER_CLOSED],
    ["leaving: toggle is ignored", leaving(), { type: "toggle", path: A }, leaving()],
    ["leaving: open is ignored", leaving(), { type: "open", path: A }, leaving()],
    ["leaving: close is ignored (a tap outside does not cut the slide short)", leaving(), { type: "close" }, leaving()],
    ["let go only from open", DRAWER_CLOSED, { type: "letGo" }, DRAWER_CLOSED],
    ["left open on another path: toggle opens it here", open(A), { type: "toggle", path: B }, open(B)],
    ["left leaving on another path: open opens it here", leaving(A), { type: "open", path: B }, open(B)],
  ];
  it.each(rows)("%s", (_name, s, a, want) => {
    expect(drawerReducer(s, a)).toEqual(want);
  });
});

describe("drawerOn", () => {
  it("is the state on its own path, closed on any other", () => {
    expect(drawerOn(open(), A)).toBe("open");
    expect(drawerOn(leaving(), A)).toBe("leaving");
    expect(drawerOn(open(), B)).toBe("closed");
    expect(drawerOn(DRAWER_CLOSED, A)).toBe("closed");
  });
});
