export type Mode = "test" | "shadow";

export interface RuleBlock {
  label: string;
  kind: "prompt" | "note" | "list" | "table";
  source: string;
  text?: string;
  items?: string[];
  rows?: string[][];
  doc?: string;
  flag?: string;
  qid?: string;
}
export interface RuleFlag { key: string; label: string; default: unknown }
export interface RuleNode {
  id: string;
  title: string;
  group: string;
  summary: string;
  flags: RuleFlag[];
  blocks: RuleBlock[];
}
export interface RuleEdge { from: string; to: string; label: string }
export interface Rules {
  mode: Mode;
  versions: Record<string, string>;
  nodes: RuleNode[];
  edges: RuleEdge[];
}

export interface View { x: number; y: number; k: number }
export interface AiRulesState {
  status: "loading" | "ready" | "error";
  data: Rules | null;
  error: string | null;
  view: View;
  viewport: { w: number; h: number };
  selected: string | null;
  pendingFit: boolean;
}

export type Action =
  | { type: "zoomAt"; px: number; py: number; factor: number }
  | { type: "panBy"; dx: number; dy: number }
  | { type: "pinch"; cx: number; cy: number; ratio: number; dx: number; dy: number }
  | { type: "zoomStep"; dir: 1 | -1 }
  | { type: "fit"; w: number; h: number }
  | { type: "resize"; w: number; h: number }
  | { type: "select"; id: string }
  | { type: "close" }
  | { type: "loaded"; data: Rules }
  | { type: "failed"; error: string };

export const MIN_K = 0.1;
export const MAX_K = 2.5;
export const DETAIL_K = 0.55;
export const STEP = 1.25;
const FIT_PAD = 24;

export const INITIAL: AiRulesState = {
  status: "loading",
  data: null,
  error: null,
  view: { x: 0, y: 0, k: 1 },
  viewport: { w: 0, h: 0 },
  selected: null,
  pendingFit: false,
};

export const clampK = (k: number) => Math.min(MAX_K, Math.max(MIN_K, k));

export function zoomAt(v: View, px: number, py: number, factor: number): View {
  const k = clampK(v.k * factor);
  const r = k / v.k;
  return { k, x: px - (px - v.x) * r, y: py - (py - v.y) * r };
}

export function fitView(viewport: { w: number; h: number }, w: number, h: number, fill: "contain" | "width" = "contain"): View {
  if (viewport.w <= 0 || viewport.h <= 0 || w <= 0 || h <= 0) return { x: 0, y: 0, k: 1 };
  const kw = (viewport.w - FIT_PAD * 2) / w;
  if (fill === "width") {
    const k = clampK(Math.min(1, kw));
    return { k, x: (viewport.w - w * k) / 2, y: FIT_PAD };
  }
  const k = clampK(Math.min(1, kw, (viewport.h - FIT_PAD * 2) / h));
  return { k, x: (viewport.w - w * k) / 2, y: (viewport.h - h * k) / 2 };
}

export function aiRulesReducer(s: AiRulesState, a: Action): AiRulesState {
  switch (a.type) {
    case "zoomAt":
      return { ...s, view: zoomAt(s.view, a.px, a.py, a.factor) };
    case "panBy":
      return { ...s, view: { ...s.view, x: s.view.x + a.dx, y: s.view.y + a.dy } };
    case "pinch": {
      const z = zoomAt(s.view, a.cx, a.cy, a.ratio);
      return { ...s, view: { ...z, x: z.x + a.dx, y: z.y + a.dy } };
    }
    case "zoomStep":
      return { ...s, view: zoomAt(s.view, s.viewport.w / 2, s.viewport.h / 2, a.dir > 0 ? STEP : 1 / STEP) };
    case "fit":
      return { ...s, pendingFit: false,
        view: fitView(s.viewport, a.w, a.h, orientationFor(s.viewport.w) === "tb" ? "width" : "contain") };
    case "resize": {
      if (a.w === s.viewport.w && a.h === s.viewport.h) return s;
      const flip = s.viewport.w <= 0 || orientationFor(a.w) !== orientationFor(s.viewport.w);
      return { ...s, viewport: { w: a.w, h: a.h }, pendingFit: s.pendingFit || flip };
    }
    case "select":
      return { ...s, selected: a.id };
    case "close":
      return s.selected === null ? s : { ...s, selected: null };
    case "loaded":
      return { ...s, status: "ready", data: a.data, error: null, pendingFit: true };
    case "failed":
      return { ...s, status: "error", error: a.error };
  }
}

export function orientationFor(w: number): "tb" | "lr" {
  return w > 0 && w < 768 ? "tb" : "lr";
}
