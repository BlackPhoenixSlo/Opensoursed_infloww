"use client";


import { wallOf } from "@/lib/ofMirrorStatsDom";
import { usd } from "@/lib/ofMirrorMoney";

export type ValueKind = "money" | "duration" | "count";

export interface ChartSeries {
  title: string;
  values: number[];
  color: string;
  kind: ValueKind;
}

export interface ChartSpec {
  labels: string[];
  series: ChartSeries;
  ticks: number;
  xLabels: boolean;
}

export const BLUE = "#00aff0";
export const GREY = "#8a96a3";
const GRID = "rgba(138,150,163,.25)";
const AXIS = 60;
const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");

export function yScale(values: number[], ticks: number): { step: number; max: number } {
  const nice = (v: number) => {
    for (const r of [5, 10, 15, 20, 30, 50, 100, 150, 200, 300, 500, 1000]) if (v <= r) return r;
    const p = 10 ** Math.floor(Math.log10(v));
    return Math.ceil(v / p) * p;
  };
  const step = nice(Math.max(0, ...values) / Math.max(ticks, 1));
  return { step, max: step * Math.max(ticks, 1) || 100 };
}

export function viewDuration(seconds: number): string {
  let s = seconds;
  const d = Math.floor(s / 86400);
  s %= 86400;
  const h = Math.floor(s / 3600);
  s %= 3600;
  return `${d ? `${d}d ` : ""}${h ? pad(h) : 0}h:${pad(Math.floor(s / 60))}m`;
}

export const tipValue = (v: number, kind: ValueKind) => (kind === "money" ? usd(v) : kind === "duration" ? viewDuration(v) : v.toLocaleString("en-US"));
export const tickLabel = (v: number, kind: ValueKind) => (!v ? "" : kind === "money" ? `$${v.toLocaleString("en-US")}` : kind === "duration" ? viewDuration(v) : v.toLocaleString("en-US"));

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
    return null;
  }
}

const slots = (spec: ChartSpec) => spec.labels.length || spec.series.values.length;
const xOf = (i: number, n: number, plot: number) => (n < 2 ? plot / 2 : (i / (n - 1)) * plot);

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

function pairOf(canvas: HTMLCanvasElement): HTMLCanvasElement[] {
  const box = canvas.closest(".b-chart") ?? canvas.parentElement;
  return [...(box?.querySelectorAll<HTMLCanvasElement>("canvas") ?? [canvas])].filter((c) => specs.has(c));
}

const TOOLTIP = "data-oi-chart-tip";

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
  if (x + width + 20 >= br.width) x -= width + 20;
  tip.style.cssText = `opacity:1;left:${Math.max(0, x + 10)}px;top:10px;width:${width}px;`;
  box.append(tip);
  return tip;
}
const boxOf = (canvas: HTMLCanvasElement) => (canvas.closest(".b-chart") ?? canvas.parentElement) as HTMLElement | null;

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

export function drawChart(canvas: HTMLCanvasElement, spec: ChartSpec): void {
  specs.set(canvas, spec);
  if (spec.ticks > 0) {
    // OF's canvas follows its box's width (Chart.js responsive): the captured fixed width would overflow a phone.
    canvas.style.width = "100%";
    bindHover(canvas);
  }
  paint(canvas, spec, null);
}

export function clearChart(canvas: HTMLCanvasElement): void {
  specs.delete(canvas);
  linesSpecs.delete(canvas);
  (canvas.closest(".b-chart") ?? canvas.parentElement)?.querySelector(`[${TOOLTIP}]`)?.remove();
  const ctx = context(canvas);
  if (ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

export const chartSpecOf = (canvas: HTMLCanvasElement) => specs.get(canvas);


const LIGHT = "#f1f2f4";
const HOVER = "#c3d1d9";
const PAD = { left: 50, bottom: 25, top: 10 };

export const hourLabel = (h: number) => `${h % 12 || 12}${h % 24 < 12 ? "am" : "pm"}`;
const hourOf = (label: string) => {
  const m = /^(\d+)(am|pm)$/.exec(label);
  return m ? (Number(m[1]) % 12) + (m[2] === "pm" ? 12 : 0) : null;
};
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
export const fansChartOf = (canvas: HTMLCanvasElement) => fansSpecs.get(canvas);

const isRec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const ratioOf = (v: unknown) => (isRec(v) && typeof v.ratio === "number" && !Number.isNaN(v.ratio) ? v.ratio : null);

export function sectorsOf(table: unknown): SectorsSpec {
  const data = isRec(table) ? table : {};
  const first = Object.values(data).find(isRec);
  const labels = [...Object.keys(first ?? {}).map((k) => hourLabel(parseInt(k, 10))), ""];
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

export function sectorColors(c: SectorCell, max: number): { fill: string; border: string } {
  if (c.ratio === null) return { fill: LIGHT, border: HOVER };
  const l = 100 * c.ratio;
  return { fill: `rgba(0, 175, 240, ${(l !== 0 ? Math.max((l / max) * 100, 5) : 1) / 100})`, border: `rgba(108, 162, 183, ${(l < 30 ? 30 : l) / 100})` };
}
export function barColor(v: number, values: number[]): string {
  const finite = values.filter((x) => Number.isFinite(x));
  const max = finite.length ? Math.max(...finite) : 1;
  const a = max ? (v / max) * 100 : 0;
  return `rgba(0, 175, 240, ${(v !== 0 ? Math.max(a, 5) : a) / 100})`;
}

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
export const drawSectors = (canvas: HTMLCanvasElement, spec: SectorsSpec) => drawFans(canvas, { kind: "sectors", spec });
export const drawBars = (canvas: HTMLCanvasElement, values: number[]) =>
  drawFans(canvas, { kind: "bars", spec: { labels: values.map((_, i) => hourLabel(i)), values } });
export function clearFans(canvas: HTMLCanvasElement) {
  fansSpecs.delete(canvas);
  boxOf(canvas)?.querySelector(`[${TOOLTIP}]`)?.remove();
  const ctx = context(canvas);
  if (ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

export interface LinesSpec {
  labels: string[];
  lines: ChartSeries[];
}
const linesSpecs = new WeakMap<HTMLCanvasElement, LinesSpec>();
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

export function linesTooltip(doc: Document, canvas: HTMLCanvasElement, i: number): HTMLElement | null {
  const spec = linesSpecs.get(canvas);
  const box = boxOf(canvas);
  if (!spec || !box) return null;
  const lines = spec.lines.flatMap((l) => (l.values[i] === undefined ? [] : [[l.color, l.title, tipValue(l.values[i], l.kind)] as [string, string, string]]));
  const left = canvas.getBoundingClientRect().left - box.getBoundingClientRect().left + linesGeom(canvas, spec).x(i);
  return tooltipAt(doc, box, spec.labels[i] ?? "", lines, left);
}

const linesBound = new WeakSet<HTMLCanvasElement>();
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
