/** AI rules view reducer + layout: zoom keeps the pointer's point, clamps, Fit centres, select/close, loads;
 *  layout places every node once, without overlap, in payload order. */
import { describe, expect, it } from "vitest";
import { CARD_W, layout, ranks, type Box, type LayoutEdge } from "./aiRulesLayout";
import {
  aiRulesReducer, fitView, INITIAL, MAX_K, MIN_K, zoomAt, type AiRulesState, type Rules, type View,
} from "./aiRulesView";

const toDiagram = (v: View, px: number, py: number) => ({ x: (px - v.x) / v.k, y: (py - v.y) / v.k });
const sized: AiRulesState = { ...INITIAL, viewport: { w: 1000, h: 600 } };

describe("zoomAt", () => {
  it.each([
    [{ x: 0, y: 0, k: 1 }, 200, 100, 2],
    [{ x: -50, y: 30, k: 0.5 }, 640, 300, 1.25],
    [{ x: 120, y: -80, k: 1.5 }, 10, 590, 0.8],
  ])("keeps the screen point over the same diagram point (%o @ %d,%d ×%d)", (v, px, py, f) => {
    const before = toDiagram(v, px, py);
    const after = toDiagram(zoomAt(v, px, py, f), px, py);
    expect(after.x).toBeCloseTo(before.x, 9);
    expect(after.y).toBeCloseTo(before.y, 9);
  });

  it.each([
    [1, 100, MAX_K],
    [1, 0.0001, MIN_K],
    [MAX_K, 2, MAX_K],
  ])("clamps k=%d ×%d to %d", (k, f, want) => {
    expect(zoomAt({ x: 0, y: 0, k }, 0, 0, f).k).toBe(want);
  });
});

describe("fitView", () => {
  it("centres the whole diagram, never above 1×", () => {
    const v = fitView({ w: 1000, h: 600 }, 2000, 500);
    expect(v.k).toBeCloseTo((1000 - 48) / 2000);
    expect(v.x + (2000 * v.k) / 2).toBeCloseTo(500);
    expect(v.y + (500 * v.k) / 2).toBeCloseTo(300);
    expect(fitView({ w: 1000, h: 600 }, 100, 100).k).toBe(1);
  });
  it("width fill starts at the top", () => {
    const v = fitView({ w: 390, h: 700 }, 700, 4000, "width");
    expect(v.k).toBeCloseTo((390 - 48) / 700);
    expect(v.y).toBe(24);
    expect(v.x + (700 * v.k) / 2).toBeCloseTo(195);
  });
  it("no viewport yet → identity", () => {
    expect(fitView({ w: 0, h: 0 }, 100, 100)).toEqual({ x: 0, y: 0, k: 1 });
  });
});

const RULES: Rules = { mode: "test", versions: {}, nodes: [], edges: [] };

describe("aiRulesReducer", () => {
  it.each<[string, AiRulesState, Parameters<typeof aiRulesReducer>[1], Partial<AiRulesState>]>([
    ["panBy moves", sized, { type: "panBy", dx: 5, dy: -3 }, { view: { x: 5, y: -3, k: 1 } }],
    ["select opens", sized, { type: "select", id: "sell" }, { selected: "sell" }],
    ["close closes", { ...sized, selected: "sell" }, { type: "close" }, { selected: null }],
    ["loaded lands and asks for a fit", sized, { type: "loaded", data: RULES },
      { status: "ready", data: RULES, pendingFit: true }],
    ["failed shows the error", sized, { type: "failed", error: "boom" }, { status: "error", error: "boom" }],
    ["first size asks for a fit", INITIAL, { type: "resize", w: 390, h: 700 }, { viewport: { w: 390, h: 700 }, pendingFit: true }],
    ["same-orientation resize keeps the view", sized, { type: "resize", w: 1200, h: 800 }, { pendingFit: false }],
    ["desktop → phone flip asks for a fit", sized, { type: "resize", w: 390, h: 700 }, { pendingFit: true }],
  ])("%s", (_n, s, a, want) => {
    expect(aiRulesReducer(s, a)).toMatchObject(want);
  });

  it("zoomStep zooms at the viewport centre", () => {
    const v = aiRulesReducer(sized, { type: "zoomStep", dir: 1 }).view;
    expect(toDiagram(v, 500, 300).x).toBeCloseTo(500);
    expect(v.k).toBeGreaterThan(1);
  });
  it("pinch zooms at its midpoint then pans", () => {
    const v = aiRulesReducer(sized, { type: "pinch", cx: 100, cy: 100, ratio: 2, dx: 10, dy: 0 }).view;
    expect(v).toEqual({ k: 2, x: -100 + 10, y: -100 });
  });
  it("fit uses the stored viewport, contain on desktop, width on phone, and clears pendingFit", () => {
    const desk = aiRulesReducer({ ...sized, pendingFit: true }, { type: "fit", w: 2000, h: 500 });
    expect(desk.view).toEqual(fitView(sized.viewport, 2000, 500));
    expect(desk.pendingFit).toBe(false);
    const phone: AiRulesState = { ...INITIAL, viewport: { w: 390, h: 700 } };
    expect(aiRulesReducer(phone, { type: "fit", w: 700, h: 4000 }).view).toEqual(fitView(phone.viewport, 700, 4000, "width"));
  });
});

const overlaps = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const ids = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `n${i}` }));
const E = (from: string, to: string, label = ""): LayoutEdge => ({ from, to, label });

describe("layout", () => {
  const cases: [string, { id: string }[], LayoutEdge[]][] = [
    ["chain", ids(4), [E("n0", "n1"), E("n1", "n2"), E("n2", "n3")]],
    ["fan-out side by side", ids(4), [E("n0", "n1"), E("n0", "n2"), E("n0", "n3")]],
    ["back edge ignored", ids(3), [E("n0", "n1"), E("n1", "n2"), E("n2", "n0", "back")]],
    ["parallel edges", ids(2), ["a", "b", "c"].map((l) => E("n0", "n1", l))],
    ["no edges", ids(3), []],
  ];
  it.each(cases)("%s: every node placed once, no overlaps, order kept (tb + lr)", (_n, nodes, edges) => {
    for (const o of ["tb", "lr"] as const) {
      const l = layout(nodes, edges, o);
      expect(Object.keys(l.boxes)).toEqual(nodes.map((n) => n.id));
      const bs = nodes.map((n) => l.boxes[n.id]);
      for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) expect(overlaps(bs[i], bs[j])).toBe(false);
      for (const b of bs) {
        expect(b.x).toBeGreaterThanOrEqual(0);
        expect(b.x + b.w).toBeLessThanOrEqual(l.width);
        expect(b.y + b.h).toBeLessThanOrEqual(l.height);
      }
      // Same rank: payload order runs along the cross axis.
      const r = ranks(nodes, edges);
      for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) {
        if (r[nodes[i].id] !== r[nodes[j].id]) continue;
        expect(o === "tb" ? bs[i].x < bs[j].x : bs[i].y < bs[j].y).toBe(true);
      }
      expect(l.edges).toHaveLength(edges.length);
    }
  });

  it("tb runs ranks down, lr runs them right; fan-out sits on one rank", () => {
    const edges = [E("n0", "n1"), E("n0", "n2")];
    const tb = layout(ids(3), edges, "tb");
    expect(tb.boxes.n1.y).toBeGreaterThan(tb.boxes.n0.y);
    expect(tb.boxes.n1.y).toBe(tb.boxes.n2.y);
    expect(tb.boxes.n2.x - tb.boxes.n1.x).toBeGreaterThanOrEqual(CARD_W);
    const lr = layout(ids(3), edges, "lr");
    expect(lr.boxes.n1.x).toBeGreaterThan(lr.boxes.n0.x);
    expect(lr.boxes.n1.x).toBe(lr.boxes.n2.x);
  });

  it("a source sits one rank before what it feeds; back edges are marked", () => {
    const r = ranks(ids(4), [E("n0", "n1"), E("n1", "n2"), E("n3", "n2")]);
    expect(r).toEqual({ n0: 0, n1: 1, n2: 2, n3: 1 });
    const l = layout(ids(3), [E("n0", "n1"), E("n1", "n2"), E("n2", "n0")], "lr");
    expect(l.edges.map((e) => e.back)).toEqual([false, false, true]);
  });

  it("parallel edges fan apart", () => {
    const l = layout(ids(2), ["a", "b", "c"].map((x) => E("n0", "n1", x)), "tb");
    expect(new Set(l.edges.map((e) => e.path)).size).toBe(3);
  });
});
