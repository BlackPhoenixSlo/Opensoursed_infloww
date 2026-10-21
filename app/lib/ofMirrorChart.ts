"use client";

/**
 * OF's Statistics charts on the captured canvases (OF draws them with Chart.js; build 202610091632: ChartJs.js's
 * DoubleLineChart, app.js's chart options `ee`, ticks `z`, labels `d2`, tooltip MultipleLineChartTooltip):
 * - a line in the series' colour over its fill (14% alpha), from the left edge to the axis column (60px) on the right;
 * - the y axis on the right: `ticks` steps (the main chart 3, the aside 2) of OF's rounded step (5, 10, 15, 20, 30, 50,
 *   100, 150, 200, 300, 500, 1000, then the next round number; all zero: steps of 5), dashed grid lines at each, their
 *   labels "$5" for money, durations as OF's view duration, else the number, none at 0;
 * - the x axis (the aside, or a chart drawn alone): the first and last dates, in OF's format for the span (`H:mm` up to a
 *   day, `H:mm, MMM DD` for two, `MMM DD, YYYY` up to 181 days, else `MMM, YYYY`), in the owner's time zone (Last 24
 *   hours: UTC, as OF);
 * - hovering a chart marks that day on every chart of its pair (a line and a dot) and shows OF's tooltip
 *   (`.b-chart__tooltip`): the date, then each series' dot, title and value (money as $1,234.00, a view duration as OF's,
 *   else the number grouped).
 * Charts are idempotent per canvas (the last spec wins); `clearChart` blanks one and stops its hover.
 */

import { wallOf } from "@/lib/ofMirrorStatsDom";
import { usd } from "@/lib/ofMirrorMoney";

export type ValueKind = "money" | "duration" | "count";

export interface ChartSeries {
  /** The tooltip's title for the line (OF's CSS capitalises it). */
  title: string;
  values: number[];
  color: string;
  kind: ValueKind;
}

export interface ChartSpec {
  /** One label per x slot (OF's tooltip title; the x axis shows the first and last): a pair's both from its main line. */
  labels: string[];
  series: ChartSeries;
  /** y steps: OF's main chart 3, its aside 2. 0: no axes (a sidebar sparkline). */
  ticks: number;
  /** Draw the x axis' first and last labels under the chart. */
  xLabels: boolean;
}

/** OF's colours: the main line, the aside line, the grid, the axis text, the hover line. */
export const BLUE = "#00aff0";
export const GREY = "#8a96a3";
const GRID = "rgba(138,150,163,.25)";
const AXIS = 60;
const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");

/** OF's y axis (app.js `z`): its step for `ticks` steps over `values` and the axis' top. */
export function yScale(values: number[], ticks: number): { step: number; max: number } {
  const nice = (v: number) => {
    for (const r of [5, 10, 15, 20, 30, 50, 100, 150, 200, 300, 500, 1000]) if (v <= r) return r;
    const p = 10 ** Math.floor(Math.log10(v));
    return Math.ceil(v / p) * p;
  };
  const step = nice(Math.max(0, ...values) / Math.max(ticks, 1));
  return { step, max: step * Math.max(ticks, 1) || 100 };
}

/** OF's view duration (utils' `Sl`): "[<d>d ]<h>h:<mm>m" from seconds. */
export function viewDuration(seconds: number): string {
  let s = seconds;
  const d = Math.floor(s / 86400);
  s %= 86400;
  const h = Math.floor(s / 3600);
  s %= 3600;
  return `${d ? `${d}d ` : ""}${h ? pad(h) : 0}h:${pad(Math.floor(s / 60))}m`;
}

/** A value as OF's tooltip shows it. */
export const tipValue = (v: number, kind: ValueKind) => (kind === "money" ? usd(v) : kind === "duration" ? viewDuration(v) : v.toLocaleString("en-US"));
/** A y tick as OF labels it (none at 0). */
export const tickLabel = (v: number, kind: ValueKind) => (!v ? "" : kind === "money" ? `$${v.toLocaleString("en-US")}` : kind === "duration" ? viewDuration(v) : v.toLocaleString("en-US"));

/**
 * OF's labels (app.js `d2`) for a chart's points dated `dates` (ISO), by the span from the first to the last, in `tz`
 * (null: the browser's; "UTC" for Last 24 hours).
 */
export function chartLabels(dates: (string | null | undefined)[], tz: string | null): string[] {
  const at = dates.map((d) => (d ? new Date(d) : null));
  const valid = at.filter((d): d is Date => !!d && !Number.isNaN(d.getTime()));
  if (!valid.length) return dates.map(() => "");
  const days = Math.floor((valid.at(-1)!.getTime() - valid[0].getTime()) / 86_400_000);
  return at.map((d) => {
    if (!d || Number.isNaN(d.getTime())) return "";
    const w = wallOf(d, tz);
    // OF's first matching span: 0-1 days, then 1-2 (so 2), then 2-181 (so 3-181).
    if (days <= 1) return `${w.h}:${pad(w.mi)}`;
    if (days <= 2) return `${w.h}:${pad(w.mi)}, ${SHORT[w.m - 1]} ${pad(w.d)}`;
    if (days <= 181) return `${SHORT[w.m - 1]} ${pad(w.d)}, ${w.y}`;
    return `${SHORT[w.m - 1]}, ${w.y}`;
  });
}

const specs = new WeakMap<HTMLCanvasElement, ChartSpec>();

/** The canvas' size in CSS pixels (its box, else its attributes at the device ratio) and the ratio. */
function size(canvas: HTMLCanvasElement) {
  const win = canvas.ownerDocument.defaultView;
  const ratio = win?.devicePixelRatio || 1;
  const box = canvas.getBoundingClientRect();
  const w = box.width || canvas.width / ratio;
  const h = box.height || canvas.height / ratio;
  return { w, h, ratio };
}

function context(canvas: HTMLCanvasElement): CanvasRenderingContext2D | null {
  try {
    return canvas.getContext("2d");
  } catch {
    return null; // no canvas (tests)
  }
}

/** A chart's x slots: its labels (the pair's main line's points), else its own points. */
const slots = (spec: ChartSpec) => spec.labels.length || spec.series.values.length;
/** The x of point `i` of `n` across `plot` pixels. */
const xOf = (i: number, n: number, plot: number) => (n < 2 ? plot / 2 : (i / (n - 1)) * plot);

/** Draw `spec` on `canvas` (hover: the point marked, OF's hover line and dot). */
function paint(canvas: HTMLCanvasElement, spec: ChartSpec, hover: number | null) {
  const ctx = context(canvas);
  if (!ctx) return;
  const { w, h, ratio } = size(canvas);
  if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const values = spec.series.values;
  const axes = spec.ticks > 0;
  const plot = axes ? Math.max(10, w - AXIS) : w;
  const bottom = h - (spec.xLabels ? 18 : 2);
  const top = axes ? 6 : 2;
  const { step, max } = axes ? yScale(values, spec.ticks) : { step: 0, max: Math.max(...values, 1) };
  const y = (v: number) => bottom - (Math.max(0, v) / max) * (bottom - top);
  ctx.font = "11px Roboto, Arial, sans-serif";
  if (axes) {
    ctx.save();
    ctx.strokeStyle = GRID;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 2]);
    ctx.fillStyle = GREY;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    for (let i = 0; i <= spec.ticks; i++) {
      const v = step * i;
      const yy = Math.round(y(v)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, yy);
      ctx.lineTo(plot, yy);
      ctx.stroke();
      const label = tickLabel(v, spec.series.kind);
      if (label) ctx.fillText(label, plot + 8, yy);
    }
    ctx.restore();
  }
  if (spec.xLabels && spec.labels.length) {
    ctx.save();
    ctx.fillStyle = GREY;
    ctx.textBaseline = "bottom";
    ctx.textAlign = "left";
    ctx.fillText(spec.labels[0], 0, h);
    if (spec.labels.length > 1) {
      ctx.textAlign = "right";
      ctx.fillText(spec.labels.at(-1)!, plot, h);
    }
    ctx.restore();
  }
  // Points on the labels' slots (the pair's main line's), as Chart.js's category axis: a longer line is cut at the last.
  const n = slots(spec);
  const shown = values.slice(0, n);
  if (!shown.length) return;
  ctx.beginPath();
  shown.forEach((v, i) => (i ? ctx.lineTo(xOf(i, n, plot), y(v)) : ctx.moveTo(xOf(i, n, plot), y(v))));
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.strokeStyle = spec.series.color;
  ctx.stroke();
  ctx.lineTo(xOf(shown.length - 1, n, plot), bottom);
  ctx.lineTo(xOf(0, n, plot), bottom);
  ctx.closePath();
  ctx.globalAlpha = 0.14;
  ctx.fillStyle = spec.series.color;
  ctx.fill();
  ctx.globalAlpha = 1;
  if (hover !== null && hover >= 0 && hover < shown.length) {
    const hx = xOf(hover, n, plot);
    ctx.save();
    ctx.strokeStyle = GREY;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(hx, top);
    ctx.lineTo(hx, bottom);
    ctx.stroke();
    ctx.restore();
    ctx.beginPath();
    ctx.arc(hx, y(values[hover]), 4, 0, Math.PI * 2);
    ctx.fillStyle = spec.series.color;
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#fff";
    ctx.stroke();
  }
}

/** The charts drawn with `canvas` (its `.b-chart`'s canvases with a spec), in order. */
function pairOf(canvas: HTMLCanvasElement): HTMLCanvasElement[] {
  const box = canvas.closest(".b-chart") ?? canvas.parentElement;
  return [...(box?.querySelectorAll<HTMLCanvasElement>("canvas") ?? [canvas])].filter((c) => specs.has(c));
}

const TOOLTIP = "data-oi-chart-tip";

/** OF's tooltip box (MultipleLineChartTooltip) in `box`: its title, then a dot, title and value per line, at `left`. */
function tooltipAt(doc: Document, box: HTMLElement, title: string, lines: [color: string, name: string, value: string][], left: number): HTMLElement {
  box.querySelector(`[${TOOLTIP}]`)?.remove();
  const tip = doc.createElement("div");
  tip.setAttribute(TOOLTIP, "");
  tip.className = "b-chart__tooltip";
  const head = doc.createElement("div");
  head.className = "b-chart__tooltip__title";
  head.textContent = ` ${title} `;
  tip.append(head);
  for (const [color, name, value] of lines) {
    const line = doc.createElement("div");
    line.className = "b-chart__tooltip__text";
    const dot = doc.createElement("div");
    dot.className = "b-chart__tooltip__circle";
    dot.style.background = color;
    const n = doc.createElement("div");
    n.className = "b-chart__tooltip__text__title";
    n.textContent = ` ${name} `;
    const v = doc.createElement("div");
    v.className = "b-chart__tooltip__text__value";
    v.textContent = ` ${value} `;
    line.append(dot, n, v);
    tip.append(line);
  }
  const win = doc.defaultView;
  if (win && win.getComputedStyle(box).position === "static") box.style.position = "relative";
  const width = 156;
  const br = box.getBoundingClientRect();
  let x = left;
  if (x + width + 20 >= br.width) x -= width + 20; // OF flips it left of the point near the right edge
  tip.style.cssText = `opacity:1;left:${Math.max(0, x + 10)}px;top:10px;width:${width}px;`;
  box.append(tip);
  return tip;
}
const boxOf = (canvas: HTMLCanvasElement) => (canvas.closest(".b-chart") ?? canvas.parentElement) as HTMLElement | null;

/** OF's tooltip (MultipleLineChartTooltip) for point `i` of `canvas`' pair, beside the point, inside the chart's box. */
export function chartTooltip(doc: Document, canvas: HTMLCanvasElement, i: number): HTMLElement | null {
  const spec = specs.get(canvas);
  const box = boxOf(canvas);
  if (!spec || !box) return null;
  const lines = pairOf(canvas).flatMap((c) => {
    const s = specs.get(c)!.series;
    const v = s.values[i];
    return v === undefined || i >= slots(specs.get(c)!) ? [] : [[s.color, s.title, tipValue(v, s.kind)] as [string, string, string]];
  });
  const { w } = size(canvas);
  const plot = spec.ticks > 0 ? Math.max(10, w - AXIS) : w;
  const left = canvas.getBoundingClientRect().left - box.getBoundingClientRect().left + xOf(i, slots(spec), plot);
  return tooltipAt(doc, box, spec.labels[i] ?? "", lines, left);
}

function hoverAt(canvas: HTMLCanvasElement, clientX: number): number | null {
  const spec = specs.get(canvas);
  if (!spec || !slots(spec)) return null;
  const { w } = size(canvas);
  const plot = spec.ticks > 0 ? Math.max(10, w - AXIS) : w;
  const x = clientX - canvas.getBoundingClientRect().left;
  if (x < 0 || x > plot + 4) return null;
  const n = slots(spec);
  return n < 2 ? 0 : Math.max(0, Math.min(n - 1, Math.round((x / plot) * (n - 1))));
}

const bound = new WeakSet<HTMLCanvasElement>();
function bindHover(canvas: HTMLCanvasElement) {
  if (bound.has(canvas)) return;
  bound.add(canvas);
  const doc = canvas.ownerDocument;
  canvas.addEventListener("mousemove", (ev) => {
    if (!specs.has(canvas)) return;
    const i = hoverAt(canvas, ev.clientX);
    for (const c of pairOf(canvas)) paint(c, specs.get(c)!, i);
    if (i === null) leave(canvas);
    else chartTooltip(doc, canvas, i);
  });
  canvas.addEventListener("mouseleave", () => leave(canvas));
}
function leave(canvas: HTMLCanvasElement) {
  for (const c of pairOf(canvas)) paint(c, specs.get(c)!, null);
  (canvas.closest(".b-chart") ?? canvas.parentElement)?.querySelector(`[${TOOLTIP}]`)?.remove();
}

/** Draw `spec` on `canvas` and let a hover show its tooltip (a sparkline, `ticks` 0: no hover). */
export function drawChart(canvas: HTMLCanvasElement, spec: ChartSpec): void {
  specs.set(canvas, spec);
  // OF's canvas follows its box's width (Chart.js responsive): the captured fixed width would overflow a phone.
  if (spec.ticks > 0) {
    canvas.style.width = "100%";
    bindHover(canvas);
  }
  paint(canvas, spec, null);
}

/** Blank `canvas` and stop its hover. */
export function clearChart(canvas: HTMLCanvasElement): void {
  specs.delete(canvas);
  (canvas.closest(".b-chart") ?? canvas.parentElement)?.querySelector(`[${TOOLTIP}]`)?.remove();
  const ctx = context(canvas);
  if (ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

/** The spec drawn on `canvas` (tests). */
export const chartSpecOf = (canvas: HTMLCanvasElement) => specs.get(canvas);

/*
 * Fans › Fans activity (statistics-fans-activity.js 159239), from `/fans-activity/list` alone:
 * - "Subscribers activity": OF's SectorsChart (ChartJs.js 936004; its boxes, options and tooltip are app.js 263601
 *   `pe`, `he`, `me`, `ue`): a column per hour key of the first day (labelled "ha", plus a trailing ""), a row per day
 *   in the data (Sat at the bottom up to Sun), each box blue at OF's alpha (`max(ratio / max * 100, 5)`%, 1% at 0) with
 *   a border of `rgba(108,162,183, max(ratio, 30)%)`; a cell without a number grey (#f1f2f4 / #c3d1d9). Hover: "Mon 9pm
 *   - 12am" and "Fans online" with the rounded %. Padding: 50 left, 25 below, 10 above.
 * - "Most active hours": OF's BarChart (ChartJs.js 772006, options app.js `fe`): 24 bars of `ratio * 100` over 0–100
 *   ("33%", "66%", "100%" grid lines), each #00AFF0 at `max(v / max * 100, 5)`% (0 for a 0), every third hour labelled;
 *   hover: "9pm - 10pm" and "Fans online" `${v}%`.
 */

const LIGHT = "#f1f2f4";
const HOVER = "#c3d1d9";
const PAD = { left: 50, bottom: 25, top: 10 };

/** dayjs' `hour(h).minute(0).format("ha")`: "12am", "1am", … "11pm". */
export const hourLabel = (h: number) => `${h % 12 || 12}${h % 24 < 12 ? "am" : "pm"}`;
const hourOf = (label: string) => {
  const m = /^(\d+)(am|pm)$/.exec(label);
  return m ? (Number(m[1]) % 12) + (m[2] === "pm" ? 12 : 0) : null;
};
/** OF's next label (app.js 263601 `ue`): the following one, else the last plus the labels' step. */
export function nextLabel(labels: string[], i: number): string {
  if (i + 1 < labels.length && labels[i + 1]) return labels[i + 1];
  if (labels.length >= 2) {
    const a = hourOf(labels[i] ?? "");
    const b = hourOf(labels[i - 1] ?? "");
    if (a !== null && b !== null) return hourLabel((a + (a - b) + 24) % 24);
  }
  return labels[0] ?? "";
}

export interface SectorCell { day: string; slot: number; row: number; ratio: number | null }
export interface SectorsSpec { labels: string[]; days: string[]; cells: SectorCell[]; max: number }
export interface BarsSpec { labels: string[]; values: number[] }
type FansSpec = { kind: "sectors"; spec: SectorsSpec } | { kind: "bars"; spec: BarsSpec };
const fansSpecs = new WeakMap<HTMLCanvasElement, FansSpec>();
/** The Fans activity chart drawn on `canvas` (tests). */
export const fansChartOf = (canvas: HTMLCanvasElement) => fansSpecs.get(canvas);

const isRec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const ratioOf = (v: unknown) => (isRec(v) && typeof v.ratio === "number" && !Number.isNaN(v.ratio) ? v.ratio : null);

/** OF's sectors from `format=table`'s `{Mon: {"0": {ratio}, "3": …}, …}`. */
export function sectorsOf(table: unknown): SectorsSpec {
  const data = isRec(table) ? table : {};
  const first = Object.values(data).find(isRec);
  const labels = [...Object.keys(first ?? {}).map((k) => hourLabel(parseInt(k, 10))), ""];
  // new Date(1970, 0, 4 + i) is Sun … Sat, reversed: Sat is row 0, at the bottom.
  const days = ["Sat", "Fri", "Thu", "Wed", "Tue", "Mon", "Sun"].filter((d) => d in data);
  const ratios = Object.values(data).flatMap((d) => (isRec(d) ? Object.values(d).map(ratioOf) : [])).filter((r): r is number => r !== null);
  const max = ratios.length ? 100 * Math.max(...ratios, 0) : 0;
  const cells: SectorCell[] = [];
  days.forEach((day, row) => {
    const hours = Object.values(isRec(data[day]) ? (data[day] as Record<string, unknown>) : {});
    for (let slot = 1; slot < labels.length && slot <= hours.length; slot++) cells.push({ day, slot, row, ratio: ratioOf(hours[slot - 1]) });
  });
  return { labels, days, cells, max };
}

/** OF's box colours for a cell (263601 `pe`'s `m` and `u`). */
export function sectorColors(c: SectorCell, max: number): { fill: string; border: string } {
  if (c.ratio === null) return { fill: LIGHT, border: HOVER };
  const l = 100 * c.ratio;
  return { fill: `rgba(0, 175, 240, ${(l !== 0 ? Math.max((l / max) * 100, 5) : 1) / 100})`, border: `rgba(108, 162, 183, ${(l < 30 ? 30 : l) / 100})` };
}
/** OF's bar colour (772006 `v`): #00AFF0 at `max(v / max * 100, 5)`%, the share itself at 0. */
export function barColor(v: number, values: number[]): string {
  const finite = values.filter((x) => Number.isFinite(x));
  const max = finite.length ? Math.max(...finite) : 1;
  const a = max ? (v / max) * 100 : 0;
  return `rgba(0, 175, 240, ${(v !== 0 ? Math.max(a, 5) : a) / 100})`;
}

/** The sectors' plot: x per label slot, y per row (one day: a double row, as OF's 0–2). */
function sectorsGeom(canvas: HTMLCanvasElement, spec: SectorsSpec) {
  const { w, h } = size(canvas);
  const cols = Math.max(1, spec.labels.length - 1);
  const one = spec.days.length === 1;
  const [y0, y1] = one ? [0, 2] : [1, spec.days.length + 1];
  const x = (v: number) => PAD.left + (v / cols) * Math.max(10, w - PAD.left);
  const y = (v: number) => h - PAD.bottom - ((v - y0) / Math.max(1, y1 - y0)) * (h - PAD.bottom - PAD.top);
  const box = (c: SectorCell) => {
    const lo = one ? 0 : 1 + c.row;
    return { x0: x(c.slot - 1), x1: x(c.slot), yTop: y(lo + (one ? 2 : 1)), yBottom: y(lo) };
  };
  return { w, h, x, y, box };
}
/** The bars' plot: 24 columns over 0–100. */
function barsGeom(canvas: HTMLCanvasElement, spec: BarsSpec) {
  const { w, h } = size(canvas);
  const n = Math.max(1, spec.values.length);
  const col = Math.max(10, w - PAD.left) / n;
  const y = (v: number) => h - PAD.bottom - (Math.max(0, Math.min(100, v)) / 100) * (h - PAD.bottom - PAD.top);
  return { w, h, col, y, x: (i: number) => PAD.left + i * col };
}

function fansPaint(canvas: HTMLCanvasElement, hover: number | null) {
  const f = fansSpecs.get(canvas);
  const ctx = context(canvas);
  if (!f || !ctx) return;
  const { w, h, ratio } = size(canvas);
  canvas.width = Math.round(w * ratio);
  canvas.height = Math.round(h * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.font = "11px Roboto, Arial, sans-serif";
  ctx.fillStyle = GREY;
  if (f.kind === "sectors") {
    const g = sectorsGeom(canvas, f.spec);
    for (const c of f.spec.cells) {
      const b = g.box(c);
      const { fill, border } = sectorColors(c, f.spec.max);
      ctx.fillStyle = fill;
      ctx.fillRect(b.x0, b.yTop, b.x1 - b.x0, b.yBottom - b.yTop);
      ctx.strokeStyle = border;
      ctx.lineWidth = 1;
      ctx.strokeRect(b.x0 + 0.5, b.yTop + 0.5, b.x1 - b.x0 - 1, b.yBottom - b.yTop - 1);
    }
    ctx.fillStyle = GREY;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    f.spec.days.forEach((d, row) => {
      const one = f.spec.days.length === 1;
      ctx.fillText(d, 0, (g.y(one ? 0 : 1 + row) + g.y(one ? 2 : 2 + row)) / 2);
    });
    ctx.textBaseline = "bottom";
    f.spec.labels.forEach((l, i) => l && ctx.fillText(l, g.x(i), h - 4));
    return;
  }
  const g = barsGeom(canvas, f.spec);
  ctx.strokeStyle = LIGHT;
  ctx.lineWidth = 1;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ["", "33%", "66%", "100%"].forEach((label, i) => {
    const yy = Math.round(g.y((100 * i) / 3)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(PAD.left, yy);
    ctx.lineTo(w, yy);
    ctx.stroke();
    if (label) ctx.fillText(label, 0, yy);
  });
  f.spec.values.forEach((v, i) => {
    ctx.fillStyle = barColor(v, f.spec.values);
    ctx.fillRect(g.x(i), g.y(v), g.col, g.y(0) - g.y(v));
  });
  if (hover !== null) {
    ctx.strokeStyle = HOVER;
    ctx.beginPath();
    ctx.moveTo(g.x(hover) + g.col / 2, PAD.top);
    ctx.lineTo(g.x(hover) + g.col / 2, g.y(0));
    ctx.stroke();
  }
  ctx.fillStyle = GREY;
  ctx.textBaseline = "bottom";
  ctx.textAlign = "center";
  f.spec.labels.forEach((l, i) => i % 3 === 0 && ctx.fillText(l, g.x(i) + g.col / 2, h - 4));
}

/** OF's tooltip for sectors cell `i` (its box's centre, shifted 40px right as OF's) or bar `i`. */
export function fansTooltip(doc: Document, canvas: HTMLCanvasElement, i: number): HTMLElement | null {
  const f = fansSpecs.get(canvas);
  const box = boxOf(canvas);
  if (!f || !box) return null;
  const offset = canvas.getBoundingClientRect().left - box.getBoundingClientRect().left;
  if (f.kind === "sectors") {
    const c = f.spec.cells[i];
    if (!c || c.ratio === null) return null;
    const b = sectorsGeom(canvas, f.spec).box(c);
    const title = `${c.day} ${f.spec.labels[c.slot - 1]} - ${nextLabel(f.spec.labels, c.slot - 1)}`;
    return tooltipAt(doc, box, title, [[BLUE, "Fans online", `${Math.round(100 * c.ratio)}%`]], offset + (b.x0 + b.x1) / 2 + 40);
  }
  const v = f.spec.values[i];
  if (v === undefined) return null;
  const g = barsGeom(canvas, f.spec);
  return tooltipAt(doc, box, `${f.spec.labels[i]} - ${nextLabel(f.spec.labels, i)}`, [[BLUE, "Fans online", v ? `${v}%` : "0%"]], offset + g.x(i) + g.col / 2);
}

function fansHit(canvas: HTMLCanvasElement, ev: MouseEvent): number | null {
  const f = fansSpecs.get(canvas);
  if (!f) return null;
  const r = canvas.getBoundingClientRect();
  const px = ev.clientX - r.left;
  const py = ev.clientY - r.top;
  if (f.kind === "sectors") {
    const g = sectorsGeom(canvas, f.spec);
    const i = f.spec.cells.findIndex((c) => {
      const b = g.box(c);
      return c.ratio !== null && px >= b.x0 && px < b.x1 && py >= b.yTop && py < b.yBottom;
    });
    return i < 0 ? null : i;
  }
  const g = barsGeom(canvas, f.spec);
  const i = Math.floor((px - PAD.left) / g.col);
  return i >= 0 && i < f.spec.values.length ? i : null;
}

const fansBound = new WeakSet<HTMLCanvasElement>();
function drawFans(canvas: HTMLCanvasElement, f: FansSpec) {
  fansSpecs.set(canvas, f);
  canvas.style.width = "100%";
  if (!fansBound.has(canvas)) {
    fansBound.add(canvas);
    const off = () => {
      fansPaint(canvas, null);
      boxOf(canvas)?.querySelector(`[${TOOLTIP}]`)?.remove();
    };
    canvas.addEventListener("mousemove", (ev) => {
      const i = fansHit(canvas, ev);
      if (i === null) return off();
      fansPaint(canvas, fansSpecs.get(canvas)?.kind === "bars" ? i : null);
      fansTooltip(canvas.ownerDocument, canvas, i);
    });
    canvas.addEventListener("mouseleave", off);
  }
  fansPaint(canvas, null);
}
/** Draw OF's "Subscribers activity" sectors on `canvas`. */
export const drawSectors = (canvas: HTMLCanvasElement, spec: SectorsSpec) => drawFans(canvas, { kind: "sectors", spec });
/** Draw OF's "Most active hours" bars (`ratio * 100` per hour) on `canvas`. */
export const drawBars = (canvas: HTMLCanvasElement, values: number[]) =>
  drawFans(canvas, { kind: "bars", spec: { labels: values.map((_, i) => hourLabel(i)), values } });
/** Blank a Fans activity chart and stop its tooltip. */
export function clearFans(canvas: HTMLCanvasElement) {
  fansSpecs.delete(canvas);
  boxOf(canvas)?.querySelector(`[${TOOLTIP}]`)?.remove();
  const ctx = context(canvas);
  if (ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

/*
 * The per-item stats popup's chart (MultipleLineChartItem, chunk 75441 module 775441; options app.js 263601 `tf`,
 * datasets `lN`): every picked line over one y scale from 0 (no axis text, no grid), filled with its colour fading down
 * (alpha .3 to .05), points hidden until hovered (radius 4, white border), 14px above, 5px each side. Hover: OF's
 * tooltip, the label and a dot, title and value per shown line.
 */
export interface LinesSpec {
  labels: string[];
  lines: ChartSeries[];
}
const linesSpecs = new WeakMap<HTMLCanvasElement, LinesSpec>();
/** The lines drawn on `canvas` (tests). */
export const linesOf = (canvas: HTMLCanvasElement) => linesSpecs.get(canvas);

function linesGeom(canvas: HTMLCanvasElement, spec: LinesSpec) {
  const { w, h } = size(canvas);
  const n = Math.max(spec.labels.length, ...spec.lines.map((l) => l.values.length), 1);
  const plot = Math.max(10, w - 10);
  const max = Math.max(1, ...spec.lines.flatMap((l) => l.values));
  const top = 14;
  const bottom = h - 2;
  return { n, x: (i: number) => 5 + xOf(i, n, plot), y: (v: number) => bottom - (Math.max(0, v) / max) * (bottom - top), top, bottom, plot };
}

function linesPaint(canvas: HTMLCanvasElement, hover: number | null) {
  const spec = linesSpecs.get(canvas);
  const ctx = context(canvas);
  if (!spec || !ctx) return;
  const { w, h, ratio } = size(canvas);
  canvas.width = Math.round(w * ratio);
  canvas.height = Math.round(h * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const g = linesGeom(canvas, spec);
  for (const l of spec.lines) {
    // OF doubles a single point into a line from 0 (MultipleLineChart).
    const vals = l.values.length === 1 ? [0, l.values[0]] : l.values;
    if (!vals.length) continue;
    ctx.beginPath();
    vals.forEach((v, i) => (i ? ctx.lineTo(g.x(i), g.y(v)) : ctx.moveTo(g.x(i), g.y(v))));
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.strokeStyle = l.color;
    ctx.stroke();
    ctx.lineTo(g.x(vals.length - 1), g.bottom);
    ctx.lineTo(g.x(0), g.bottom);
    ctx.closePath();
    ctx.save();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = l.color;
    ctx.fill();
    ctx.restore();
    if (hover !== null && hover < vals.length) {
      ctx.beginPath();
      ctx.arc(g.x(hover), g.y(vals[hover]), 4, 0, Math.PI * 2);
      ctx.fillStyle = l.color;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
    }
  }
}

/** OF's tooltip for slot `i` of the lines on `canvas`. */
export function linesTooltip(doc: Document, canvas: HTMLCanvasElement, i: number): HTMLElement | null {
  const spec = linesSpecs.get(canvas);
  const box = boxOf(canvas);
  if (!spec || !box) return null;
  const lines = spec.lines.flatMap((l) => (l.values[i] === undefined ? [] : [[l.color, l.title, tipValue(l.values[i], l.kind)] as [string, string, string]]));
  const left = canvas.getBoundingClientRect().left - box.getBoundingClientRect().left + linesGeom(canvas, spec).x(i);
  return tooltipAt(doc, box, spec.labels[i] ?? "", lines, left);
}

const linesBound = new WeakSet<HTMLCanvasElement>();
/** Draw `spec`'s lines on `canvas` with OF's hover. */
export function drawLines(canvas: HTMLCanvasElement, spec: LinesSpec) {
  linesSpecs.set(canvas, spec);
  canvas.style.width = "100%";
  if (!linesBound.has(canvas)) {
    linesBound.add(canvas);
    const off = () => {
      linesPaint(canvas, null);
      boxOf(canvas)?.querySelector(`[${TOOLTIP}]`)?.remove();
    };
    canvas.addEventListener("mousemove", (ev) => {
      const s = linesSpecs.get(canvas);
      if (!s) return;
      const g = linesGeom(canvas, s);
      const x = ev.clientX - canvas.getBoundingClientRect().left - 5;
      if (x < -4 || x > g.plot + 4) return off();
      const i = g.n < 2 ? 0 : Math.max(0, Math.min(g.n - 1, Math.round((x / g.plot) * (g.n - 1))));
      linesPaint(canvas, i);
      linesTooltip(canvas.ownerDocument, canvas, i);
    });
    canvas.addEventListener("mouseleave", off);
  }
  linesPaint(canvas, null);
}
