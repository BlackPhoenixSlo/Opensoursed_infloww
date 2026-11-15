/**
 * AI rules page: where each card and edge sits. Pure; no DOM.
 *
 * Rank = longest path over forward edges (an edge whose target comes earlier in the payload is ignored for ranking;
 * drawn, an edge whose target's rank is not after its source's is a back edge, dashed round the side). A node with no forward edge in sits one rank before its first successor. Nodes of one rank go side by
 * side in payload order. `tb` (phone) runs ranks top to bottom; `lr` (desktop) left to right. Edges between the
 * same pair (the six Routes) fan out side by side.
 */

export type Orientation = "tb" | "lr";
export interface LayoutNode { id: string }
export interface LayoutEdge { from: string; to: string; label: string }
export interface Box { x: number; y: number; w: number; h: number }
export interface PlacedEdge extends LayoutEdge {
  path: string;
  labelX: number;
  labelY: number;
  back: boolean;
}
export interface Layout {
  boxes: Record<string, Box>;
  edges: PlacedEdge[];
  width: number;
  height: number;
}

export const CARD_W = 320;
export const CARD_H = 230;
const RANK_GAP = 150;
const CROSS_GAP = 48;
const PAD = 24;
const FAN = 22;

export function ranks(nodes: LayoutNode[], edges: LayoutEdge[]): Record<string, number> {
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const fwd = edges.filter((e) => idx.has(e.from) && idx.has(e.to) && idx.get(e.to)! > idx.get(e.from)!);
  const rank: Record<string, number> = {};
  for (const n of nodes) {
    const ins = fwd.filter((e) => e.to === n.id);
    rank[n.id] = ins.length ? Math.max(...ins.map((e) => rank[e.from] + 1)) : 0;
  }
  // Sources pull down next to what they feed (any edge, back ones too: the switches gate the Router).
  for (const n of nodes) {
    if (fwd.some((e) => e.to === n.id)) continue;
    const outs = edges.filter((e) => e.from === n.id && idx.has(e.to)).map((e) => rank[e.to]);
    if (outs.length) rank[n.id] = Math.max(0, Math.min(...outs) - 1);
  }
  return rank;
}

export function layout(nodes: LayoutNode[], edges: LayoutEdge[], orientation: Orientation): Layout {
  const rank = ranks(nodes, edges);
  const byRank: string[][] = [];
  for (const n of nodes) (byRank[rank[n.id]] ??= []).push(n.id);
  const lanes = byRank.map((r) => r ?? []);
  const widest = Math.max(1, ...lanes.map((r) => r.length));
  const tb = orientation === "tb";
  const along = tb ? CARD_H : CARD_W; // card size along the rank axis
  const cross = tb ? CARD_W : CARD_H;
  const crossSpan = widest * cross + (widest - 1) * CROSS_GAP;

  const boxes: Record<string, Box> = {};
  lanes.forEach((ids, r) => {
    const span = ids.length * cross + (ids.length - 1) * CROSS_GAP;
    ids.forEach((id, i) => {
      const a = PAD + r * (along + RANK_GAP);
      const c = PAD + (crossSpan - span) / 2 + i * (cross + CROSS_GAP);
      boxes[id] = tb ? { x: c, y: a, w: CARD_W, h: CARD_H } : { x: a, y: c, w: CARD_W, h: CARD_H };
    });
  });

  const placed = edges.filter((e) => boxes[e.from] && boxes[e.to]);
  const pairCount = new Map<string, number>();
  for (const e of placed) pairCount.set(`${e.from}>${e.to}`, (pairCount.get(`${e.from}>${e.to}`) ?? 0) + 1);
  const seen = new Map<string, number>();
  const out: PlacedEdge[] = placed.map((e) => {
    const key = `${e.from}>${e.to}`;
    const n = pairCount.get(key)!;
    const i = seen.get(key) ?? 0;
    seen.set(key, i + 1);
    const off = (i - (n - 1) / 2) * FAN;
    const s = boxes[e.from];
    const t = boxes[e.to];
    const back = rank[e.to] <= rank[e.from];
    return { ...e, back, ...route(s, t, off, back, tb, n > 1 ? i : -1) };
  });

  const width = PAD * 2 + (tb ? crossSpan : lanes.length * along + (lanes.length - 1) * RANK_GAP);
  const height = PAD * 2 + (tb ? lanes.length * along + (lanes.length - 1) * RANK_GAP : crossSpan);
  return { boxes, edges: out, width, height };
}

/** A curved path from `s` to `t`. Forward: out of the far side, into the near side. Back: out and in on the outer
 *  side (right in `tb`, bottom in `lr`), bulging away from the cards. `fanIdx` ≥ 0 staggers fanned labels. */
function route(s: Box, t: Box, off: number, back: boolean, tb: boolean, fanIdx: number) {
  if (back) {
    const bulge = 90 + Math.abs(off);
    if (tb) {
      const x1 = s.x + s.w, y1 = s.y + s.h / 2 + off, x2 = t.x + t.w, y2 = t.y + t.h / 2 + off;
      const cx = Math.max(x1, x2) + bulge;
      return { path: `M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`, labelX: cx - 20, labelY: (y1 + y2) / 2 };
    }
    const x1 = s.x + s.w / 2 + off, y1 = s.y + s.h, x2 = t.x + t.w / 2 + off, y2 = t.y + t.h;
    const cy = Math.max(y1, y2) + bulge;
    return { path: `M${x1},${y1} C${x1},${cy} ${x2},${cy} ${x2},${y2}`, labelX: (x1 + x2) / 2, labelY: cy - 20 };
  }
  // Fanned labels stagger along the edge so six Route names never sit on one line.
  const at = fanIdx < 0 ? 0.5 : 0.3 + (fanIdx % 3) * 0.2;
  if (tb) {
    const x1 = s.x + s.w / 2 + off, y1 = s.y + s.h, x2 = t.x + t.w / 2 + off, y2 = t.y;
    const my = (y1 + y2) / 2;
    return { path: `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`, labelX: x1 + (x2 - x1) * at, labelY: y1 + (y2 - y1) * at };
  }
  const x1 = s.x + s.w, y1 = s.y + s.h / 2 + off, x2 = t.x, y2 = t.y + t.h / 2 + off;
  const mx = (x1 + x2) / 2;
  return { path: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, labelX: x1 + (x2 - x1) * at, labelY: y1 + (y2 - y1) * at };
}
