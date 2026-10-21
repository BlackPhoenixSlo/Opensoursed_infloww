import { afterEach, describe, expect, it, vi } from "vitest";

import { gridColumnCount, moveIndex, rangeBetween } from "./vaultPickerSelection";

const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }];
const ids = (xs: Array<{ id: number }>) => xs.map((x) => x.id);

describe("rangeBetween", () => {
  it("returns the cards from the anchor to the target in display order, either direction", () => {
    expect(ids(rangeBetween(items, 2, 4))).toEqual([2, 3, 4]);
    expect(ids(rangeBetween(items, 4, 2))).toEqual([2, 3, 4]);
    expect(ids(rangeBetween(items, 3, 3))).toEqual([3]);
  });

  it("is empty when the anchor or the target is not displayed", () => {
    expect(rangeBetween(items, null, 2)).toEqual([]);
    expect(rangeBetween(items, 99, 2)).toEqual([]);
    expect(rangeBetween(items, 2, 99)).toEqual([]);
  });
});

describe("moveIndex", () => {
  it("moves by one left/right and by the column count up/down, clamped to the grid", () => {
    expect(moveIndex(1, "ArrowRight", 3, 7)).toBe(2);
    expect(moveIndex(1, "ArrowLeft", 3, 7)).toBe(0);
    expect(moveIndex(0, "ArrowLeft", 3, 7)).toBe(0);
    expect(moveIndex(6, "ArrowRight", 3, 7)).toBe(6);
    expect(moveIndex(1, "ArrowDown", 3, 7)).toBe(4);
    expect(moveIndex(5, "ArrowDown", 3, 7)).toBe(6);
    expect(moveIndex(4, "ArrowUp", 3, 7)).toBe(1);
    expect(moveIndex(1, "ArrowUp", 3, 7)).toBe(0);
  });

  it("starts on the first card when nothing has focus, and returns null for other keys or an empty grid", () => {
    expect(moveIndex(null, "ArrowDown", 3, 7)).toBe(0);
    expect(moveIndex(1, "Tab", 3, 7)).toBeNull();
    expect(moveIndex(null, "ArrowRight", 3, 0)).toBeNull();
  });
});

describe("gridColumnCount", () => {
  afterEach(() => vi.restoreAllMocks());

  it("counts the rendered grid's column tracks", () => {
    const grid = document.createElement("div");
    vi.spyOn(window, "getComputedStyle").mockReturnValue(
      { gridTemplateColumns: "120px 120px 120px 120px" } as CSSStyleDeclaration,
    );
    expect(gridColumnCount(grid)).toBe(4);
  });

  it("falls back to the cards sharing the first card's row, and to 1", () => {
    const grid = document.createElement("div");
    for (const top of [0, 0, 0, 90, 90]) {
      const tile = document.createElement("button");
      Object.defineProperty(tile, "offsetTop", { value: top });
      grid.appendChild(tile);
    }
    expect(gridColumnCount(grid)).toBe(3);
    expect(gridColumnCount(null)).toBe(1);
  });
});
