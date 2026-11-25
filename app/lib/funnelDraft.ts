import type { FunnelFull, FunnelStep, PpvStep } from "@/hooks/useFunnels";
import { parseJsonObject, type RawJsonCodec } from "@/lib/rawJsonReducer";


export type StepKind = "reply" | "ppv";

export interface DraftStep {
  kind: StepKind;
  step: number;
  intervals: string;
  messages: string[];
  generate: boolean;
  prompt: string;
  price: string;
  lockedText: boolean;
  extra: Record<string, unknown>;
}

const KNOWN_STEP_KEYS = new Set([
  "type", "step", "messages", "generate", "prompt", "price",
  "locked_text", "check_intervals_min",
]);

export function blankStep(kind: StepKind, step: number): DraftStep {
  return {
    kind,
    step,
    intervals: "",
    messages: [""],
    generate: false,
    prompt: "",
    price: kind === "ppv" ? "0" : "",
    lockedText: false,
    extra: {},
  };
}

export function toDraft(step: FunnelStep): DraftStep {
  const isPpv = step.type === "paid_ppv";
  const msgs = Array.isArray(step.messages) ? step.messages.map(String) : [];
  const hasStatic = msgs.some((m) => m.trim());
  const generate = !hasStatic && Boolean(step.generate || (step.prompt && step.prompt.trim()));
  const ivRaw = step.check_intervals_min;
  const intervals = Array.isArray(ivRaw) ? ivRaw.join(", ") : "";
  const ppv = step as PpvStep;
  const extra: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(step)) {
    if (!KNOWN_STEP_KEYS.has(k)) extra[k] = v;
  }
  return {
    kind: isPpv ? "ppv" : "reply",
    step: step.step,
    intervals,
    messages: msgs.length ? msgs : [""],
    generate,
    prompt: step.prompt ?? "",
    price: isPpv && typeof ppv.price === "number" ? String(ppv.price) : "",
    lockedText: isPpv ? Boolean(ppv.locked_text) : false,
    extra,
  };
}

function parseIntervals(raw: string, label: string): number[] {
  const parts = raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
  const out: number[] = [];
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isInteger(n) || n <= 0) {
      throw new Error(`${label} interval "${p}" must be a positive whole number of minutes`);
    }
    out.push(n);
  }
  return out;
}

export function toWire(d: DraftStep, idx: number): FunnelStep {
  const label = `Step ${idx + 1}`;
  const msgs = d.messages.map((m) => m.trim()).filter(Boolean);
  if (!d.generate && msgs.length === 0) {
    throw new Error(`${label} needs at least one message (or switch it to AI-generated).`);
  }
  const out: Omit<PpvStep, "type"> & { type?: "paid_ppv" } = { step: d.step };
  // TEXT-ONLY: PPV media is per-account (FunnelMediaPane), never written here.
  if (d.kind === "ppv") {
    out.type = "paid_ppv";
    if (d.price.trim() !== "") {
      const price = Number(d.price);
      if (!Number.isInteger(price) || price < 0) {
        throw new Error(`${label} price must be a whole number ≥ 0.`);
      }
      out.price = price;
    }
    if (d.lockedText) out.locked_text = true;
  }
  const intervals = parseIntervals(d.intervals, label);
  if (intervals.length) out.check_intervals_min = intervals;
  if (d.generate) {
    out.generate = true;
    if (d.prompt.trim()) out.prompt = d.prompt.trim();
  } else {
    out.messages = msgs;
  }
  return { ...d.extra, ...out } as FunnelStep;
}


export interface FunnelDraft {
  name: string;
  description: string;
  opening: string;
  steps: DraftStep[];
  open: number | null;
}

export interface FunnelBody {
  name: string;
  opening_message: string;
  description: string | null;
  steps: FunnelStep[];
}

export const EMPTY_FUNNEL: FunnelDraft = { name: "", description: "", opening: "", steps: [], open: null };

function badIntervals(iv: unknown): boolean {
  if (iv == null) return false;
  return !Array.isArray(iv) || iv.length === 0
    || !iv.every((x) => typeof x === "number" && Number.isInteger(x) && x > 0);
}

const warnedRepairs = new Set<number>();

export function funnelDraftOf(f: FunnelFull): FunnelDraft {
  const repaired: number[] = [];
  const steps = (f.steps ?? []).map((s, i) => {
    const d = toDraft(s);
    if (!badIntervals(s.check_intervals_min)) return d;
    repaired.push(i + 1);
    return { ...d, intervals: "" };
  });
  if (repaired.length && !warnedRepairs.has(f.id)) {
    warnedRepairs.add(f.id);
    console.warn(
      `Funnel "${f.name}" (id ${f.id}): invalid check_intervals_min on `
      + `${repaired.map((n) => `Step ${n}`).join(", ")} — loaded blank, dropped on save; the walker default [2,4,10] applies after that.`,
    );
  }
  return {
    name: f.name,
    description: f.description ?? "",
    opening: f.opening_message,
    steps,
    open: null,
  };
}

export function stepErrorText(msg: string, steps: Pick<DraftStep, "step">[]): string {
  const dangling = /^step\[(\d+)\]\.next\.(.+) → step (-?\d+) references no existing step$/.exec(msg);
  if (dangling) {
    const [, i, label, id] = dangling;
    const at = steps.findIndex((s) => s.step === Number(id));
    const where = at >= 0
      ? `points to Step ${at + 1} (id ${id}), which the server could not find`
      : `points to a step that does not exist (id ${id})`;
    return `Step ${Number(i) + 1} next.${label} ${where}.`;
  }
  return msg.replace(/^step\[(\d+)\](\.?)/, (_m, i: string, dot: string) => `Step ${Number(i) + 1}${dot ? " " : ""}`);
}

export type FunnelEdit =
  | { type: "header"; patch: Partial<Pick<FunnelDraft, "name" | "description" | "opening">> }
  | { type: "addStep"; kind: StepKind }
  | { type: "patchStep"; i: number; patch: Partial<DraftStep> }
  | { type: "removeStep"; i: number }
  | { type: "moveStep"; i: number; dir: -1 | 1 }
  | { type: "toggleStep"; i: number };

function nextStepNumber(steps: Pick<DraftStep, "step">[]): number {
  return steps.reduce((m, s) => Math.max(m, s.step), 0) + 1;
}

export function followOpen(d: Pick<FunnelDraft, "open" | "steps">, e: FunnelEdit): number | null {
  const { open } = d;
  const len = d.steps.length;
  switch (e.type) {
    case "addStep":
      return len;
    case "toggleStep":
      return open === e.i ? null : e.i;
    case "removeStep":
      if (open === null || open < e.i) return open;
      return open === e.i ? null : open - 1;
    case "moveStep": {
      const j = e.i + e.dir;
      if (j < 0 || j >= len || open === null) return open;
      return open === e.i ? j : open === j ? e.i : open;
    }
    default:
      return open;
  }
}

export function editFunnel(d: FunnelDraft, e: FunnelEdit): FunnelDraft {
  const next = applyEdit(d, e);
  const open = followOpen(d, e);
  return next === d && open === d.open ? d : { ...next, open };
}

function applyEdit(d: FunnelDraft, e: FunnelEdit): FunnelDraft {
  const mapStep = (i: number, f: (s: DraftStep) => DraftStep) =>
    ({ ...d, steps: d.steps.map((s, idx) => (idx === i ? f(s) : s)) });
  switch (e.type) {
    case "header":
      return { ...d, ...e.patch };
    case "addStep":
      return { ...d, steps: [...d.steps, blankStep(e.kind, nextStepNumber(d.steps))] };
    case "patchStep":
      return mapStep(e.i, (s) => ({ ...s, ...e.patch }));
    case "removeStep":
      return { ...d, steps: d.steps.filter((_, idx) => idx !== e.i) };
    case "moveStep": {
      const j = e.i + e.dir;
      if (j < 0 || j >= d.steps.length) return d;
      const steps = d.steps.slice();
      [steps[e.i], steps[j]] = [steps[j], steps[e.i]];
      return { ...d, steps };
    }
    case "toggleStep":
      return d;
  }
}

function wireBody(d: FunnelDraft): FunnelBody {
  const steps = d.steps.map(toWire);
  const seen = new Map<number, number>();
  steps.forEach((s, i) => {
    const first = seen.get(s.step);
    if (first != null) throw new Error(`Step ${i + 1} has the same id as Step ${first} (id ${s.step}).`);
    seen.set(s.step, i + 1);
  });
  return {
    name: d.name.trim(),
    opening_message: d.opening.trim(),
    description: d.description.trim() || null,
    steps,
  };
}

export function saveBody(d: FunnelDraft): FunnelBody {
  if (!d.name.trim()) throw new Error("Name is required.");
  if (!d.opening.trim()) throw new Error("Opening message is required.");
  return wireBody(d);
}

function assertRawStep(s: unknown, idx: number): asserts s is FunnelStep {
  const label = `Step ${idx + 1}`;
  if (typeof s !== "object" || s === null || Array.isArray(s)) throw new Error(`${label} must be an object.`);
  const o = s as Record<string, unknown>;
  if (o.step != null && (typeof o.step !== "number" || !Number.isInteger(o.step) || o.step < 1)) {
    throw new Error(`${label} step must be a whole number ≥ 1.`);
  }
  if (o.type != null && o.type !== "paid_ppv") {
    throw new Error(`${label} has unknown type ${JSON.stringify(o.type)} (only "paid_ppv").`);
  }
  if (o.type === "paid_ppv" && o.price != null && typeof o.price !== "number") {
    throw new Error(`${label} price must be a whole number ≥ 0.`);
  }
  if (o.messages != null && !Array.isArray(o.messages)) throw new Error(`${label} messages must be a list.`);
  if (o.check_intervals_min != null && !Array.isArray(o.check_intervals_min)) {
    throw new Error(`${label} check_intervals_min must be a list of minutes.`);
  }
}

function rawDraftSteps(raw: unknown[]): DraftStep[] {
  const steps = raw.map((s, i) => {
    assertRawStep(s, i);
    return s;
  });
  let next = nextStepNumber(steps.filter((s) => s.step != null));
  return steps.map((s) => toDraft(s.step != null ? s : { ...s, step: next++ }));
}

export const FUNNEL_RAW: RawJsonCodec<FunnelDraft> = {
  format: (d) => JSON.stringify(wireBody(d), null, 2),
  parse(text) {
    const o = parseJsonObject(text, "Funnel", '{ "name": "…", "opening_message": "…", "steps": [] }');
    const steps = o.steps ?? [];
    if (!Array.isArray(steps)) throw new Error("steps must be a list.");
    const draft: FunnelDraft = {
      name: String(o.name ?? "").trim(),
      description: o.description == null ? "" : String(o.description).trim(),
      opening: String(o.opening_message ?? "").trim(),
      steps: rawDraftSteps(steps),
      open: null,
    };
    wireBody(draft);
    return draft;
  },
};
